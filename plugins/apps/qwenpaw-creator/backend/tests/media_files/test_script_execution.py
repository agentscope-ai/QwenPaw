# -*- coding: utf-8 -*-
"""script_draft 执行服务：文本模型起草剧本并写回 timeline_script 版本。"""

from __future__ import annotations

import asyncio

import pytest

from domain.errors import ValidationError
from services.file_agent_runtime.work_graph import (
    WorkNodeStatus,
    derive_work_graph,
)
from services.file_agent_runtime import work_scheduler
from services.media_files import script_execution
from services.media_files.script_execution import (
    execute_file_script_command,
)
from services.project_files.facade import CreatorFileServices
from services.project_files.agent_tools import (
    AgentProjectToolContext,
    AgentProjectTools,
)
from services.project_files.edit_impact import apply_frontend_edit_impacts
from services.project_files.models import Project, Timeline
from services.runtime_files.models import ChangeOrigin, ReviewPolicy

pytestmark = pytest.mark.unit

PROJECT_ID = "p-script-exec"

DRAFT = """\
## 场 1 · 内景 · 旧宅大厅 · 夜

烛光摇曳，林晚推开木门。

**林晚**（低声）：这里……和二十年前一模一样。

> 钥匙上的家徽和母亲遗物一模一样。
"""


def _services(tmp_path) -> CreatorFileServices:
    services = CreatorFileServices.create(tmp_path.resolve())
    project = Project.new(project_id=PROJECT_ID, name="Script Exec")
    project.strategy.creative_brief = "旧宅悬疑短剧"
    project.timelines.items["timeline:ep2"] = Timeline(
        timeline_id="timeline:ep2",
        title="第二集 · 旧宅疑云",
        synopsis="林晚发现母亲遗物的秘密。",
        planned_duration_seconds=60,
    )
    project.timelines.order.append("timeline:ep2")
    services.projects.create(
        Project.model_validate(project.model_dump(mode="json")),
    )
    return services


def _mock_chat(monkeypatch, replies: list[str]):
    calls: list[dict] = []

    async def fake_chat_completion(prompt, *, system_prompt="", **_kwargs):
        calls.append({"prompt": prompt, "system": system_prompt})
        return replies[min(len(calls) - 1, len(replies) - 1)]

    monkeypatch.setattr(
        script_execution.text_model,
        "chat_completion",
        fake_chat_completion,
    )
    return calls


def test_script_command_publishes_selected_version(
    tmp_path,
    monkeypatch,
) -> None:
    services = _services(tmp_path)
    calls = _mock_chat(monkeypatch, [DRAFT])

    result = asyncio.run(
        execute_file_script_command(
            services,
            project_id=PROJECT_ID,
            target_ref="timeline:timeline:ep2",
            arguments={},
            idempotency_key="dag-script-1",
        ),
    )

    assert not result.replayed
    assert result.slot_id == "script:timeline:ep2"
    snapshot = services.projects.read(PROJECT_ID)
    slot = snapshot.project.assets.artifact_slots_by_id[result.slot_id]
    assert slot.kind == "timeline_script"
    assert slot.selected_version_id == result.artifact_version_id
    version = snapshot.project.assets.artifact_versions_by_id[
        result.artifact_version_id
    ]
    assert version.input_fingerprint is not None
    # markdown 文件真实落盘且与索引一致。
    indexed = snapshot.project.assets.files_by_id[result.file_id]
    payload = (
        services.projects.project_root(PROJECT_ID) / indexed.relative_uri
    ).read_text(encoding="utf-8")
    assert "## 场 1 · 内景 · 旧宅大厅 · 夜" in payload
    assert "**林晚**（低声）：这里……和二十年前一模一样。" in payload
    # prompt 携带本集标题/梗概与策略。
    assert "第二集 · 旧宅疑云" in calls[0]["prompt"]
    assert "旧宅悬疑短剧" in calls[0]["prompt"]
    # 工作图上该 timeline 的 script 节点转 DONE。
    graph = derive_work_graph(snapshot.project)
    assert graph.by_id["script:timeline:ep2"].status is WorkNodeStatus.DONE


def test_same_inputs_replay_without_second_model_call(
    tmp_path,
    monkeypatch,
) -> None:
    services = _services(tmp_path)
    calls = _mock_chat(monkeypatch, [DRAFT])

    first = asyncio.run(
        execute_file_script_command(
            services,
            project_id=PROJECT_ID,
            target_ref="timeline:timeline:ep2",
            arguments={},
            idempotency_key="dag-script-1",
        ),
    )
    replay = asyncio.run(
        execute_file_script_command(
            services,
            project_id=PROJECT_ID,
            target_ref="timeline:timeline:ep2",
            arguments={},
            idempotency_key="dag-script-2",
        ),
    )

    assert replay.replayed
    assert replay.artifact_version_id == first.artifact_version_id
    assert len(calls) == 1


def test_unused_default_duration_does_not_redraft_script(
    tmp_path,
    monkeypatch,
):
    services = _services(tmp_path)
    calls = _mock_chat(monkeypatch, [DRAFT])
    first = _draft(services, key="first")
    tools = AgentProjectTools(
        services.projects,
        context=AgentProjectToolContext(origin=ChangeOrigin.INITIAL_CREATION),
    )
    tools.read_project(PROJECT_ID)
    result = tools.patch_project(
        project_id=PROJECT_ID,
        ops=[
            {
                "op": "replace",
                "path": "/settings/target_duration_seconds",
                "value": 90,
            },
        ],
    )
    assert not result.project.assets.artifact_versions_by_id[
        first.artifact_version_id
    ].stale
    replay = _draft(services, key="retry")
    assert replay.replayed
    assert replay.artifact_version_id == first.artifact_version_id
    assert len(calls) == 1


@pytest.mark.parametrize("automatic", [False, True])
def test_scheduler_regenerates_stale_script_once_and_keeps_saved_body(
    tmp_path,
    monkeypatch,
    automatic,
):
    services = _services(tmp_path)
    calls = _mock_chat(monkeypatch, [DRAFT, DRAFT + "\n**管家**：请保管钥匙。\n"])
    monkeypatch.setattr(
        work_scheduler,
        "get_execution_authorization_mode",
        lambda: "allow_all" if automatic else "required",
    )

    async def scenario():
        first = await execute_file_script_command(
            services,
            project_id=PROJECT_ID,
            target_ref="timeline:timeline:ep2",
            arguments={},
            idempotency_key="first-script",
        )
        base = services.projects.read(PROJECT_ID)
        candidate = base.project.model_dump(mode="json")
        candidate["timelines"]["items"]["timeline:main"][
            "description"
        ] = "已发布第一集正文"
        episode = candidate["timelines"]["items"]["timeline:ep2"]
        episode["synopsis"] = "林晚决定留下钥匙，进入旧宅。"
        episode["description"] = "林晚把钥匙收进口袋，然后走进旧宅。必须保留这个动作。"
        candidate, _ = apply_frontend_edit_impacts(
            candidate,
            [
                "/timelines/items/timeline:ep2/synopsis",
                "/timelines/items/timeline:ep2/description",
            ],
            base=base.project.model_dump(mode="json"),
        )
        services.commits.commit(
            base=base,
            candidate=candidate,
            origin=ChangeOrigin.FRONTEND_EDIT,
            review_policy=ReviewPolicy.AUTO_FIX,
        )
        scheduler = work_scheduler.WorkGraphScheduler(services)
        try:
            await scheduler.tick(PROJECT_ID)
            if automatic:
                deadline = asyncio.get_running_loop().time() + 5
                while (
                    services.projects.read(PROJECT_ID)
                    .project.assets.artifact_slots_by_id["script:timeline:ep2"]
                    .selected_version_id
                    == first.artifact_version_id
                ):
                    assert asyncio.get_running_loop().time() < deadline
                    await asyncio.sleep(0.01)
            for _ in range(3):
                await scheduler.tick(PROJECT_ID)
                await asyncio.sleep(0.01)
            project = services.projects.read(PROJECT_ID).project
            assert project.assets.artifact_versions_by_id[
                first.artifact_version_id
            ].stale
            selected = project.assets.artifact_slots_by_id[
                "script:timeline:ep2"
            ].selected_version_id
            if automatic:
                assert selected != first.artifact_version_id
                assert not project.assets.artifact_versions_by_id[
                    selected
                ].stale
                assert len(calls) == 1
                version = project.assets.artifact_versions_by_id[selected]
                file = project.assets.files_by_id[version.file_id]
                assert (
                    services.projects.project_root(PROJECT_ID)
                    / file.relative_uri
                ).read_text(encoding="utf-8") == episode["description"]
            else:
                assert selected == first.artifact_version_id
                assert len(calls) == 1
        finally:
            await scheduler.shutdown()

    asyncio.run(scenario())


def test_changed_synopsis_drafts_a_new_selected_version(
    tmp_path,
    monkeypatch,
) -> None:
    services = _services(tmp_path)
    calls = _mock_chat(monkeypatch, [DRAFT, DRAFT + "\n**管家**：小姐。\n"])

    first = asyncio.run(
        execute_file_script_command(
            services,
            project_id=PROJECT_ID,
            target_ref="timeline:timeline:ep2",
            arguments={},
            idempotency_key="dag-script-1",
        ),
    )
    # 梗概更新：指纹变化，复放失效，起草新版本并重新 selected。
    with services.projects.lifecycle_lock(PROJECT_ID):
        base = services.projects.read(PROJECT_ID)
        candidate = base.project.model_dump(mode="json")
        candidate["timelines"]["items"]["timeline:ep2"][
            "synopsis"
        ] = "改：林晚在阁楼发现日记。"
        commit = services.commits.commit(
            base=base,
            candidate=candidate,
            origin=ChangeOrigin.FRONTEND_EDIT,
            review_policy=ReviewPolicy.AUTO_FIX,
            caused_by_request_id="edit-synopsis",
            round_id="round-edit-synopsis",
            transaction_id="tx-edit-synopsis",
            advance_accepted_baseline=True,
            _lifecycle_lock_held=True,
        )
        services.poller.note_commit(commit.snapshot)

    second = asyncio.run(
        execute_file_script_command(
            services,
            project_id=PROJECT_ID,
            target_ref="timeline:timeline:ep2",
            arguments={},
            idempotency_key="dag-script-3",
        ),
    )

    assert not second.replayed
    assert second.artifact_version_id != first.artifact_version_id
    assert len(calls) == 2
    snapshot = services.projects.read(PROJECT_ID)
    slot = snapshot.project.assets.artifact_slots_by_id["script:timeline:ep2"]
    assert slot.version_ids == [
        first.artifact_version_id,
        second.artifact_version_id,
    ]
    assert slot.selected_version_id == second.artifact_version_id


def test_unknown_timeline_is_rejected(tmp_path, monkeypatch) -> None:
    services = _services(tmp_path)
    _mock_chat(monkeypatch, [DRAFT])
    with pytest.raises(ValidationError, match="timeline 不存在"):
        asyncio.run(
            execute_file_script_command(
                services,
                project_id=PROJECT_ID,
                target_ref="timeline:timeline:ghost",
                arguments={},
                idempotency_key="dag-script-x",
            ),
        )


# ---- guidance 是 prompt 输入：必须进指纹，不能被语义复放吞掉 -------------


def _draft(services, *, guidance=None, key):
    arguments = {} if guidance is None else {"guidance": guidance}
    return asyncio.run(
        execute_file_script_command(
            services,
            project_id=PROJECT_ID,
            target_ref="timeline:timeline:ep2",
            arguments=arguments,
            idempotency_key=key,
        ),
    )


def test_changed_guidance_always_reaches_the_model(
    tmp_path,
    monkeypatch,
) -> None:
    services = _services(tmp_path)
    calls = _mock_chat(
        monkeypatch,
        [DRAFT, DRAFT + "\n\n（喜剧结尾稿）", DRAFT + "\n\n（悲剧结尾稿）"],
    )

    first = _draft(services, key="dag-script-1")
    # none → A：首次 guidance 必达模型并产出新版本。
    second = _draft(services, guidance="改成喜剧结尾", key="dag-script-2")
    assert not second.replayed
    assert second.artifact_version_id != first.artifact_version_id
    assert "改成喜剧结尾" in calls[1]["prompt"]
    # A → B：guidance 变化同样不被语义复放吞掉。
    third = _draft(services, guidance="改成悲剧结尾", key="dag-script-3")
    assert not third.replayed
    assert third.artifact_version_id != second.artifact_version_id
    assert len(calls) == 3
    assert "改成悲剧结尾" in calls[2]["prompt"]


def test_same_guidance_retry_still_replays(tmp_path, monkeypatch) -> None:
    services = _services(tmp_path)
    calls = _mock_chat(monkeypatch, [DRAFT])

    first = _draft(services, guidance="改成喜剧结尾", key="dag-script-1")
    retry = _draft(services, guidance="改成喜剧结尾", key="dag-script-2")

    assert retry.replayed
    assert retry.artifact_version_id == first.artifact_version_id
    assert len(calls) == 1


@pytest.mark.parametrize("change", ["stale", "guidance"])
def test_identical_redraft_is_fresh_and_next_retry_does_not_regenerate(
    tmp_path,
    monkeypatch,
    change,
):
    services = _services(tmp_path)
    calls = _mock_chat(monkeypatch, [DRAFT])
    first = _draft(services, key="original")
    if change == "stale":
        base = services.projects.read(PROJECT_ID)
        candidate = base.project.model_dump(mode="json")
        candidate["assets"]["artifact_versions_by_id"][
            first.artifact_version_id
        ]["stale"] = True
        services.commits.commit(
            base=base,
            candidate=candidate,
            origin=ChangeOrigin.FRONTEND_EDIT,
            review_policy=ReviewPolicy.AUTO_FIX,
            caused_by_request_id="invalidate",
            round_id="invalidate",
            transaction_id="invalidate",
        )
    guidance = "保留同样的正文" if change == "guidance" else None
    second = _draft(services, key="regenerate", guidance=guidance)
    assert second.artifact_version_id != first.artifact_version_id
    snapshot = services.projects.read(PROJECT_ID)
    assert not snapshot.project.assets.artifact_versions_by_id[
        second.artifact_version_id
    ].stale
    assert (
        derive_work_graph(snapshot.project).by_id["script:timeline:ep2"].status
        is WorkNodeStatus.DONE
    )
    third = _draft(services, key="retry", guidance=guidance)
    assert (
        third.replayed
        and third.artifact_version_id == second.artifact_version_id
    )
    assert len(calls) == 2
    assert services.projects.read(PROJECT_ID).etag == snapshot.etag


@pytest.mark.parametrize("field", ["synopsis", "description"])
def test_changed_inputs_during_model_call_do_not_publish_old_script(
    tmp_path,
    monkeypatch,
    field,
):
    services = _services(tmp_path)

    async def change_then_return(*_args, **_kwargs):
        base = services.projects.read(PROJECT_ID)
        candidate = base.project.model_dump(mode="json")
        candidate["timelines"]["items"]["timeline:ep2"][
            field
        ] = "New story during generation"
        services.commits.commit(
            base=base,
            candidate=candidate,
            origin=ChangeOrigin.FRONTEND_EDIT,
            review_policy=ReviewPolicy.AUTO_FIX,
            caused_by_request_id="during",
            round_id="during",
            transaction_id="during",
        )
        return DRAFT

    monkeypatch.setattr(
        script_execution.text_model,
        "chat_completion",
        change_then_return,
    )
    with pytest.raises(ValidationError, match="旧结果未发布"):
        _draft(services, key="old-inputs")
    assert (
        "script:timeline:ep2"
        not in services.projects.read(
            PROJECT_ID,
        ).project.assets.artifact_slots_by_id
    )


def test_stale_script_sync_preserves_authored_body_without_model_call(
    tmp_path,
    monkeypatch,
):
    services = _services(tmp_path)
    calls = _mock_chat(monkeypatch, [DRAFT])
    first = _draft(services, key="initial")
    authored = "\n  原稿的空格与台词都要保留。\n\n陈默：还有七天以后，他们全部倒下。\n"
    base = services.projects.read(PROJECT_ID)
    candidate = base.project.model_dump(mode="json")
    candidate["timelines"]["items"]["timeline:ep2"]["description"] = authored
    candidate["assets"]["artifact_versions_by_id"][first.artifact_version_id][
        "stale"
    ] = True
    services.commits.commit(
        base=base,
        candidate=candidate,
        origin=ChangeOrigin.FRONTEND_EDIT,
    )

    def sync(key):
        return asyncio.run(
            execute_file_script_command(
                services,
                project_id=PROJECT_ID,
                target_ref="timeline:timeline:ep2",
                arguments={"source": "timeline"},
                idempotency_key=key,
            ),
        )

    result = sync("sync-body")
    current = services.projects.read(PROJECT_ID)
    version = current.project.assets.artifact_versions_by_id[
        result.artifact_version_id
    ]
    file = current.project.assets.files_by_id[version.file_id]
    assert (
        services.projects.project_root(PROJECT_ID) / file.relative_uri
    ).read_bytes() == authored.encode("utf-8")
    assert (
        current.project.timelines.items["timeline:ep2"].description == authored
    )
    assert version.metadata["scriptSource"] == "timeline"
    assert not version.stale
    assert current.project.assets.artifact_versions_by_id[
        first.artifact_version_id
    ].stale
    assert sync("sync-again").replayed
    assert len(calls) == 1


def test_explicit_script_revision_includes_existing_authored_body(
    tmp_path,
    monkeypatch,
):
    services = _services(tmp_path)
    calls = _mock_chat(monkeypatch, [DRAFT])
    base = services.projects.read(PROJECT_ID)
    candidate = base.project.model_dump(mode="json")
    candidate["timelines"]["items"]["timeline:ep2"]["description"] = DRAFT
    services.commits.commit(
        base=base,
        candidate=candidate,
        origin=ChangeOrigin.FRONTEND_EDIT,
    )
    _draft(services, key="revise", guidance="只调整开场动作")
    assert DRAFT in calls[0]["prompt"]
    assert "只调整开场动作" in calls[0]["prompt"]


def test_unchanged_legacy_script_replays_without_a_model_call(tmp_path, monkeypatch):
    services = _services(tmp_path)
    calls = _mock_chat(monkeypatch, [DRAFT])
    first = _draft(services, key="original")
    base = services.projects.read(PROJECT_ID)
    candidate = base.project.model_dump(mode="json")
    version = candidate["assets"]["artifact_versions_by_id"][first.artifact_version_id]
    version["metadata"].pop("scriptSource")
    version["input_fingerprint"] = "sha256:6bfccdd989dbb00d64bf7921c1674e0a2489d6991c09f59fc234604f75220b24"
    services.commits.commit(
        base=base,
        candidate=candidate,
        origin=ChangeOrigin.RUNTIME_TASK,
        review_policy=ReviewPolicy.AUTO_FIX,
    )
    replay = _draft(services, key="retry")
    assert replay.replayed and replay.artifact_version_id == first.artifact_version_id
    assert len(calls) == 1
