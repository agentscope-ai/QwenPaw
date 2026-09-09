# -*- coding: utf-8 -*-
# pylint: disable=consider-using-from-import,protected-access
from __future__ import annotations

import asyncio

from fastapi import FastAPI

import api.project_file_routes as project_file_routes
from api.dependencies import creator_error_handler, project_file_services
from api.project_file_routes import router
from domain.errors import CreatorError
from services.project_files.commit import ProjectCommitBoundary
from services.project_files.facade import CreatorFileServices
from services.project_files.json_pointer import MISSING, hash_json_value
from services.project_files.models import Project
from services.runtime_files import IdempotencyRecordStore, IdempotencyStatus
from services.runtime_files.models import ReviewBoundary


def _business_error(response) -> dict:
    volatile = {"errorId", "traceId", "requestId", "occurredAt"}
    return {
        key: value
        for key, value in response.json().items()
        if key not in volatile
    }


PROJECT_URL = "/projects/project-1/project"
PATCH_SCOPE = "PATCH /projects/{projectId}/project"


def _app(tmp_path):
    services = CreatorFileServices.create(tmp_path.resolve())
    snapshot = services.projects.create(
        Project.new(project_id="project-1", name="Initial", description="old"),
    )
    app = FastAPI()
    app.add_exception_handler(CreatorError, creator_error_handler)
    app.include_router(router)
    app.dependency_overrides[project_file_services] = lambda: services
    return app, services, snapshot


def _patch_payload(
    command_id,
    value,
    base,
    *,
    path="/name",
    expected="Initial",
    session="edit",
):
    return {
        "clientCommandId": command_id,
        "editSessionId": session,
        "baseGeneration": base.generation,
        "baseEtag": base.etag,
        "operations": [
            {
                "op": "replace",
                "path": path,
                "value": value,
                "expectedValueHash": hash_json_value(expected),
            },
        ],
    }


def _pending_review(services, base):
    candidate = base.project.model_dump(mode="json")
    candidate["name"] = "Review candidate"
    result = ProjectCommitBoundary(services.projects).commit(
        base=base,
        candidate=candidate,
        origin="agentdock_interrupt",
        review_policy="require_review",
        review_boundary=ReviewBoundary(
            request_message_seq=2,
            request_id="request-2",
            interrupted_run_id="run-1",
            accepted_generation=base.generation,
            accepted_etag=base.etag,
        ),
        caused_by_request_id="request-2",
        caused_by_message_seq=2,
        round_id="round-2",
    )
    assert result.review is not None
    return result.review


def _decisions_url(review):
    return f"/projects/project-1/runtime/reviews/{review.review_id}/decisions"


def _decision_payload(review, decision_id, decision="ACCEPT", **extra):
    return {
        "decisionId": decision_id,
        "decisionToken": review.decision_token,
        "decisions": [
            {
                "operation_id": review.operations[0].operation_id,
                "decision": decision,
            },
        ],
        **extra,
    }


def _decide_twice(run_scenario, app, url, payload):
    headers = {"Idempotency-Key": payload["decisionId"]}

    async def scenario(client):
        first = await client.post(url, headers=headers, json=payload)
        replay = await client.post(url, headers=headers, json=payload)
        return first, replay

    return run_scenario(app, scenario)


def _idempotency_store(services):
    return IdempotencyRecordStore(
        services.projects.project_root("project-1")
        / "runtime"
        / "commands"
        / "idempotency",
    )


def _messages(sessions, session_id):
    return sessions.list_messages(
        "project-1",
        session_id,
        after_seq=0,
        limit=None,
    )


def test_project_snapshot_etag_patch_and_disjoint_stale_merge(
    tmp_path,
    run_scenario,
) -> None:
    app, _services, base = _app(tmp_path)

    async def scenario(client):
        first = await client.get(PROJECT_URL)
        unchanged = await client.get(
            PROJECT_URL,
            headers={"If-None-Match": first.headers["etag"]},
        )
        patch_name = await client.patch(
            PROJECT_URL,
            headers={"Idempotency-Key": "command-name"},
            json=_patch_payload(
                "command-name",
                "Agent name",
                base,
                session="edit-1",
            ),
        )
        patch_description = await client.patch(
            PROJECT_URL,
            headers={"Idempotency-Key": "command-description"},
            json=_patch_payload(
                "command-description",
                "User description",
                base,
                path="/description",
                expected="old",
                session="edit-2",
            ),
        )
        return first, unchanged, patch_name, patch_description

    first, unchanged, patch_name, patch_description = run_scenario(
        app,
        scenario,
    )
    assert first.status_code == 200
    assert first.json()["project"]["name"] == "Initial"
    assert unchanged.status_code == 304
    assert patch_name.status_code == 200
    assert patch_description.status_code == 200
    assert patch_description.json()["generation"] == 2
    assert patch_description.json()["project"]["name"] == "Agent name"
    assert (
        patch_description.json()["project"]["description"]
        == "User description"
    )


def test_same_field_stale_patch_returns_cas_conflict(
    tmp_path,
    run_scenario,
) -> None:
    app, _services, base = _app(tmp_path)

    async def scenario(client):
        first = await client.patch(
            PROJECT_URL,
            headers={"Idempotency-Key": "first"},
            json=_patch_payload("first", "first", base),
        )
        second = await client.patch(
            PROJECT_URL,
            headers={"Idempotency-Key": "second"},
            json=_patch_payload("second", "second", base),
        )
        return first, second

    first, second = run_scenario(app, scenario)
    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["code"] == "CAS_CONFLICT"
    assert second.json()["details"]["conflicts"][0]["pointer"] == "/name"


def test_invalid_external_project_keeps_last_good_and_reports_sync_error(
    tmp_path,
    api_request,
) -> None:
    app, services, _base = _app(tmp_path)
    # Seed the last-good cache before simulating an out-of-protocol writer.
    services.poller.open("project-1")
    services.projects.project_path("project-1").write_text(
        "{invalid",
        encoding="utf-8",
    )

    result = api_request(app, "GET", PROJECT_URL)
    assert result.status_code == 503
    assert result.json()["code"] == "PROJECT_INVALID"
    assert result.json()["lastGoodGeneration"] == 0


def test_active_review_poll_is_created_only_from_review_boundary(
    tmp_path,
    run_scenario,
) -> None:
    app, services, base = _app(tmp_path)
    _pending_review(services, base)

    async def scenario(client):
        first = await client.get("/projects/project-1/runtime/reviews/active")
        second = await client.get(
            "/projects/project-1/runtime/reviews/active",
            headers={"If-None-Match": first.headers["etag"]},
        )
        return first, second

    first, second = run_scenario(app, scenario)
    assert first.status_code == 200
    reviews = first.json()
    assert isinstance(reviews, list) and len(reviews) == 1
    assert reviews[0]["request_id"] == "request-2"
    assert second.status_code == 304


def test_project_patch_replays_success_and_rejects_payload_drift(
    tmp_path,
    run_scenario,
    api_request,
) -> None:
    app, _services, base = _app(tmp_path)
    payload = _patch_payload(
        "command-replay",
        "Replayed name",
        base,
        session="edit-1",
    )
    headers = {"Idempotency-Key": "command-replay"}

    async def scenario(client):
        first = await client.patch(PROJECT_URL, headers=headers, json=payload)
        replay = await client.patch(PROJECT_URL, headers=headers, json=payload)
        return first, replay

    first, replay = run_scenario(app, scenario)
    drift_payload = _patch_payload(
        "command-replay",
        "Payload drift",
        base,
        session="edit-1",
    )
    drift = api_request(
        app,
        "PATCH",
        PROJECT_URL,
        headers=headers,
        json=drift_payload,
    )
    assert first.status_code == 200
    assert replay.status_code == 200
    assert _business_error(replay) == _business_error(first)
    assert replay.headers["X-Idempotent-Replay"] == "true"
    assert replay.headers["etag"] == first.headers["etag"]
    assert drift.status_code == 409
    assert drift.json()["code"] == "CONFLICT"


def test_project_patch_recovers_crash_before_idempotency_completion(
    tmp_path,
    monkeypatch,
    run_scenario,
) -> None:
    app, services, base = _app(tmp_path)
    payload = _patch_payload(
        "crash-recovery-command",
        "Published exactly once",
        base,
        session="edit-crash",
    )
    original_complete = IdempotencyRecordStore.complete
    crashed = False

    def crash_before_completion(self, **kwargs):
        nonlocal crashed
        if not crashed and kwargs["scope"] == PATCH_SCOPE:
            crashed = True
            raise RuntimeError("simulated completion write failure")
        return original_complete(self, **kwargs)

    monkeypatch.setattr(
        IdempotencyRecordStore,
        "complete",
        crash_before_completion,
    )
    headers = {"Idempotency-Key": "crash-recovery-command"}

    async def scenario(client):
        failed_completion = await client.patch(
            PROJECT_URL,
            headers=headers,
            json=payload,
        )
        assert failed_completion.status_code == 503

        record_after_crash = _idempotency_store(services).get(
            owner_id="project-1",
            scope=PATCH_SCOPE,
            idempotency_key="crash-recovery-command",
        )
        assert record_after_crash is not None
        assert record_after_crash.status is IdempotencyStatus.IN_PROGRESS
        assert services.projects.read("project-1").generation == 1

        monkeypatch.setattr(
            IdempotencyRecordStore,
            "complete",
            original_complete,
        )
        return await client.patch(
            PROJECT_URL,
            headers=headers,
            json=payload,
        )

    replay = run_scenario(app, scenario)
    assert replay.status_code == 200
    assert replay.headers["X-Idempotent-Replay"] == "true"
    assert replay.json()["generation"] == 1
    assert replay.json()["project"]["name"] == "Published exactly once"

    completed = _idempotency_store(services).get(
        owner_id="project-1",
        scope=PATCH_SCOPE,
        idempotency_key="crash-recovery-command",
    )
    assert completed is not None
    assert completed.status is IdempotencyStatus.COMPLETED


def test_review_decision_replays_success_and_rejects_payload_drift(
    tmp_path,
    run_scenario,
    api_request,
) -> None:
    app, services, base = _app(tmp_path)
    review = _pending_review(services, base)
    payload = _decision_payload(review, "decision-1")
    url = _decisions_url(review)

    first, replay = _decide_twice(run_scenario, app, url, payload)
    drift = api_request(
        app,
        "POST",
        url,
        headers={"Idempotency-Key": "decision-1"},
        json=_decision_payload(review, "decision-1", decision="REJECT"),
    )
    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert replay.headers["X-Idempotent-Replay"] == "true"
    assert drift.status_code == 409
    assert drift.json()["code"] == "CONFLICT"


def test_rejection_feedback_appends_exactly_one_action_specific_message(
    tmp_path,
    run_scenario,
) -> None:
    for action, expected_role, expected_channel, expected_text in (
        ("UNDO_ONLY", "system", "runtime", "没有要求重做"),
        ("UNDO_AND_REGENERATE", "user", "agentdock", "明确要求重新生成"),
    ):
        app, services, base = _app(tmp_path / action.lower())
        runtime = services.sessions.create_project_runtime(
            "project-1",
            session_id="session-1",
            conversation_id="conversation-1",
        )
        review = _pending_review(services, base)
        payload = _decision_payload(
            review,
            f"decision-{action.lower()}",
            decision="REJECT",
            rejectionFeedback={
                "action": action,
                "feedbackNote": "人物状态不对；保持身份一致",
            },
        )

        first, replay = _decide_twice(
            run_scenario,
            app,
            _decisions_url(review),
            payload,
        )
        assert first.status_code == 200
        assert replay.status_code == 200
        assert replay.headers["X-Idempotent-Replay"] == "true"

        messages = _messages(services.sessions, runtime.session.session_id)
        assert len(messages) == 1
        assert messages[0].role == expected_role
        assert messages[0].channel.value == expected_channel
        assert messages[0].source == "review_rejection_feedback"
        assert messages[0].content_parts[0].text is not None
        assert expected_text in messages[0].content_parts[0].text
        assert "人物状态不对" in messages[0].content_parts[0].text


def test_rejection_feedback_requires_a_reject_decision(
    tmp_path,
    api_request,
) -> None:
    app, services, base = _app(tmp_path)
    review = _pending_review(services, base)

    result = api_request(
        app,
        "POST",
        _decisions_url(review),
        headers={"Idempotency-Key": "invalid-feedback"},
        json=_decision_payload(
            review,
            "invalid-feedback",
            rejectionFeedback={"action": "UNDO_ONLY"},
        ),
    )
    assert result.status_code == 422


def test_stale_decision_token_fails_closed_with_cas_conflict(
    tmp_path,
    api_request,
) -> None:
    app, services, base = _app(tmp_path)
    review = _pending_review(services, base)
    payload = _decision_payload(review, "failed-decision")
    payload["decisionToken"] = "stale-token"

    result = api_request(
        app,
        "POST",
        _decisions_url(review),
        headers={"Idempotency-Key": "failed-decision"},
        json=payload,
    )
    assert result.status_code == 409
    assert result.json()["code"] == "CAS_CONFLICT"


def test_review_reject_does_not_use_decision_id_as_a_path(
    tmp_path,
    api_request,
) -> None:
    app, services, base = _app(tmp_path)
    review = _pending_review(services, base)
    malicious_id = "x/../../../../escaped"

    result = api_request(
        app,
        "POST",
        _decisions_url(review),
        headers={"Idempotency-Key": malicious_id},
        json=_decision_payload(review, malicious_id, decision="REJECT"),
    )
    assert result.status_code == 200
    assert not (tmp_path / "escaped").exists()


def test_missing_project_writes_do_not_create_a_phantom_directory(
    tmp_path,
    run_scenario,
) -> None:
    services = CreatorFileServices.create(tmp_path.resolve())
    app = FastAPI()
    app.add_exception_handler(CreatorError, creator_error_handler)
    app.include_router(router)
    app.dependency_overrides[project_file_services] = lambda: services

    async def scenario(client):
        patch = await client.patch(
            "/projects/missing/project",
            headers={"Idempotency-Key": "missing-patch"},
            json={
                "clientCommandId": "missing-patch",
                "editSessionId": "edit",
                "baseGeneration": 0,
                "baseEtag": "etag",
                "operations": [
                    {
                        "op": "replace",
                        "path": "/name",
                        "value": "name",
                        "expectedValueHash": hash_json_value("old"),
                    },
                ],
            },
        )
        acquire = await client.post(
            "/projects/missing/runtime/blocks",
            json={
                "jsonPointer": "/name",
                "ownerKind": "user",
                "ownerId": "user-1",
                "baseFieldHash": "hash",
            },
        )
        review = await client.post(
            "/projects/missing/runtime/reviews/review-1/decisions",
            headers={"Idempotency-Key": "missing-decision"},
            json={
                "decisionId": "missing-decision",
                "decisionToken": "token",
                "decisions": [
                    {"operation_id": "operation-1", "decision": "ACCEPT"},
                ],
            },
        )
        return patch, acquire, review

    results = run_scenario(app, scenario)
    assert [result.status_code for result in results] == [404] * 3
    assert not (tmp_path / "missing").exists()


def test_project_delete_between_patch_precheck_and_lifecycle_admission_is_404(
    tmp_path,
    monkeypatch,
    run_scenario,
) -> None:
    app, services, base = _app(tmp_path)
    initial_check_complete = asyncio.Event()
    allow_request_to_continue = asyncio.Event()
    original = project_file_routes._require_existing_project
    calls = 0

    async def pause_after_initial_check(file_services, project_id):
        nonlocal calls
        await original(file_services, project_id)
        calls += 1
        if calls == 1:
            initial_check_complete.set()
            await allow_request_to_continue.wait()

    monkeypatch.setattr(
        project_file_routes,
        "_require_existing_project",
        pause_after_initial_check,
    )

    async def scenario(client):
        request = asyncio.create_task(
            client.patch(
                PROJECT_URL,
                headers={"Idempotency-Key": "delete-race"},
                json=_patch_payload(
                    "delete-race",
                    "Must not resurrect",
                    base,
                    session="edit-delete-race",
                ),
            ),
        )
        await asyncio.wait_for(initial_check_complete.wait(), timeout=1)
        await asyncio.to_thread(services.projects.delete, "project-1")
        allow_request_to_continue.set()
        return await request

    result = run_scenario(app, scenario)
    assert result.status_code == 404
    assert not services.projects.project_root("project-1").exists()


def _snapshot_app(tmp_path):
    """A ``project-1`` with one timeline element and a Runtime Session."""

    # pylint: disable=import-outside-toplevel
    from services.project_files.models import (
        ElementLocation,
        R2VCreation,
        TimelineElement,
        TimelineSpan,
    )

    services = CreatorFileServices.create(tmp_path.resolve())
    element = TimelineElement(
        element_id="el-1",
        label="原始",
        span=TimelineSpan(start_tick=0, duration_tick=4000),
        location=ElementLocation(),
        creation=R2VCreation(
            narrative="猫发现老鼠后追逐",
            storyboard_prompt="动画分镜：猫发现并追逐老鼠",
            video_prompt="动画，猫从左向右追逐老鼠",
        ),
    )
    project = Project.new(project_id="project-1", name="Snapshot")
    main = project.timelines.items["timeline:main"]
    project.timelines.items["timeline:main"] = main.model_copy(
        update={"elements_by_id": {element.element_id: element}},
    )
    services.projects.create(
        project,
        initialize_staged_project=lambda staged_root: (
            services.sessions.initialize_staged_project(
                staged_root,
                "project-1",
                session_id="session-1",
                conversation_id="conversation-1",
                initial_goal="做一条视频",
                goal_id="goal-1",
                initial_message_id="message-initial",
                initial_client_message_id="client-initial",
            )
        ),
    )
    app = FastAPI()
    app.add_exception_handler(CreatorError, creator_error_handler)
    app.include_router(router)
    app.dependency_overrides[project_file_services] = lambda: services
    return app, services


def _agent_edit(services, label: str):
    """One agent commit that runs the auto-snapshot pass; returns candidate."""

    # pylint: disable=import-outside-toplevel
    from services.project_files.auto_snapshot import auto_snapshot_timelines

    base = services.projects.read("project-1")
    base_data = base.project.model_dump(mode="json")
    candidate = base.project.model_dump(mode="json")
    candidate["timelines"]["items"]["timeline:main"]["elements_by_id"]["el-1"][
        "label"
    ] = label
    auto_snapshot_timelines(base_data, candidate)
    return base, candidate


def test_applying_a_snapshot_steers_the_agent_and_forces_a_fresh_baseline(
    tmp_path,
    monkeypatch,
    run_scenario,
) -> None:
    """回滚落地后：agent 收到 inbox 通知，且下一次 agent 写入必须留底。

    两处产品缺口的守护：快照切换对 agent 可感知（steer，不是 quiet），
    且十分钟去重窗口不再压制回滚后的第一份基线。
    """

    # pylint: disable=import-outside-toplevel
    from types import SimpleNamespace

    from services.file_agent_runtime.notifications import (
        RuntimeEventKind,
        RuntimeNotificationBus,
    )
    from services.project_files import snapshot_restore_hold

    snapshot_restore_hold.clear()
    app, services = _snapshot_app(tmp_path)

    wakes: list[str] = []
    bus = RuntimeNotificationBus(services, wake_dispatcher=wakes.append)
    monkeypatch.setattr(
        project_file_routes,
        "get_creator_agent_runtime",
        lambda: SimpleNamespace(notifications=bus),
    )

    # Agent 改一次 → 铸出改前的自动快照，窗口随之打开。
    base, candidate = _agent_edit(services, "agent 改过")
    services.commits.commit(
        base=base,
        candidate=candidate,
        origin="runtime_task",
    )
    snapshot_id = "snapshot:timeline:main:1"
    after_agent = services.projects.read("project-1")
    assert snapshot_id in after_agent.project.timelines.items

    # 用户在前端应用该快照。真实 applySnapshot 在同一个 PATCH 里先建
    # "应用前备份"快照，再回滚 live —— 备份不得被误判成回滚目标。
    frozen = after_agent.project.timelines.items[snapshot_id]
    restored_elements = {}
    for snap_id, frozen_element in frozen.elements_by_id.items():
        original = snap_id[len(f"{snapshot_id}:") :]
        restored_elements[original] = frozen_element.model_copy(
            update={"element_id": original},
        ).model_dump(mode="json")
    live_now = after_agent.project.timelines.items["timeline:main"]
    backup_id = "snapshot:timeline:main:2"
    backup = live_now.model_copy(
        update={
            "timeline_id": backup_id,
            "name": "应用前备份 · 2026-09-05 04:00",
            "elements_by_id": {
                f"{backup_id}:{element_id}": item.model_copy(
                    update={"element_id": f"{backup_id}:{element_id}"},
                )
                for element_id, item in live_now.elements_by_id.items()
            },
        },
    ).model_dump(mode="json")
    order_index = len(after_agent.project.timelines.order)

    async def scenario(client):
        return await client.patch(
            PROJECT_URL,
            headers={"Idempotency-Key": "apply-snapshot"},
            json={
                "clientCommandId": "apply-snapshot",
                "editSessionId": "edit",
                "baseGeneration": after_agent.generation,
                "baseEtag": after_agent.etag,
                "operations": [
                    {
                        "op": "add",
                        "path": f"/timelines/items/{backup_id}",
                        "value": backup,
                        "expectedValueHash": hash_json_value(MISSING),
                    },
                    {
                        "op": "add",
                        "path": f"/timelines/order/{order_index}",
                        "value": backup_id,
                        "expectedValueHash": hash_json_value(MISSING),
                    },
                    {
                        "op": "replace",
                        "path": (
                            "/timelines/items/timeline:main/elements_by_id"
                        ),
                        "value": restored_elements,
                        "expectedValueHash": hash_json_value(
                            live_now.model_dump(mode="json")["elements_by_id"],
                        ),
                    },
                ],
            },
        )

    response = run_scenario(app, scenario)
    assert response.status_code == 200
    rolled_back = response.json()["project"]["timelines"]["items"][
        "timeline:main"
    ]["elements_by_id"]["el-1"]
    assert rolled_back["label"] == "原始"

    # ① agent 感知：一条 user-role RUNTIME inbox 消息 + 唤醒。
    steers = [
        item
        for item in _messages(services.sessions, "session-1")
        if item.metadata.get("notificationKind")
        == RuntimeEventKind.TIMELINE_SNAPSHOT_RESTORED.value
    ]
    assert len(steers) == 1
    assert steers[0].role == "user"
    text = steers[0].content_parts[0].text
    assert snapshot_id in text
    assert backup_id not in text, "备份快照不得被当成回滚目标"
    assert wakes == ["project-1"]

    # ② 回滚后 agent 的下一次写入留底，尽管仍在十分钟窗口内。
    # 备份占了 :2，所以强制留下的基线是 :3。
    _base2, candidate2 = _agent_edit(services, "agent 回滚后改写")
    assert "snapshot:timeline:main:3" in candidate2["timelines"]["items"]
    snapshot_restore_hold.clear()


def test_only_a_wholesale_element_replace_pays_for_rollback_detection() -> (
    None
):
    """短路守护：只有整体替换 live 元素表的 PATCH 才跑回滚检测。

    检测要与项目内每个快照比对内容，且发生在 lifecycle 排他锁内（实测
    在 15 快照项目上约 275ms/请求）。前端每次 blur 都发 PATCH，普通字段
    编辑必须完全不进这条路径。
    """

    def op(path: str, kind: str = "replace"):
        return project_file_routes.ProjectPatchOperation(
            op=kind,
            path=path,
            value={},
            expectedValueHash=hash_json_value({}),
        )

    replaces = project_file_routes._replaces_live_elements_wholesale
    # 回滚形状：整体替换 live 元素表。
    assert replaces([op("/timelines/items/timeline:main/elements_by_id")])
    # 普通编辑：更深的 pointer。
    assert not replaces(
        [op("/timelines/items/timeline:main/elements_by_id/el-1/label")],
    )
    # 建快照 / 改时间线属性 / 改无关字段都不触发。
    assert not replaces(
        [
            op("/timelines/items/snapshot:timeline:main:1", "add"),
            op("/timelines/items/timeline:main/color_grade"),
            op("/name"),
        ],
    )
    # 冻结快照自己的元素表不算回滚（agent 侧另有 fail-closed 拦截）。
    assert not replaces(
        [op("/timelines/items/snapshot:timeline:main:1/elements_by_id")],
    )
