# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument
"""Synchronous text review: classification, parsing, caps and fail-open."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from models import text_model
from models import config as model_config
from services.media_files.visual_reference_resolution import (
    preview_r2v_reference_order,
)
from services.project_files.models import Project
from services.run_review import admission, text_review
from services.run_review.prompt_contract import (
    check_changed_r2v_prompt_contracts,
)
from services.run_review.text_review import (
    classify_pointer_groups,
    classify_pointers,
    maybe_sync_review,
    parse_sync_advisory,
    reviewable_changed_pointers,
)

pytestmark = pytest.mark.unit

PROJECT_JSON = {
    "project_id": "project-run-review",
    "strategy": {"creative_brief": "一只猫的雨天独白短片"},
}
MOTION_PTR = "/timelines/items/t/elements_by_id/e/creation/motion/concept"


def _advisory_payload(*, weak_concept: bool) -> str:
    scores = [
        {"row_key": k, "score": 8, "ok": True, "finding": "", "suggestion": ""}
        for k in ("concept", "contract", "rhythm")
    ]
    if weak_concept:
        scores[0] |= {
            "score": 3,
            "ok": False,
            "finding": "/strategy/creative_brief 只是素材罗列",
            "suggestion": "补一个一句话概念",
        }
    return json.dumps(
        {"scores": scores, "summary": "总体可用"},
        ensure_ascii=False,
    )


def _parse_advisory(text: str):
    return parse_sync_advisory(
        text,
        stage="text",
        transaction_id="txn-1",
        pointer_group="strategy",
        reviewed_pointers=["/strategy/creative_brief"],
        round_number=1,
    )


def _sync_review(tmp_path: Path, *, txn: str, project_json=None):
    return maybe_sync_review(
        project_id="project-run-review",
        project_root=tmp_path,
        project_json=project_json or PROJECT_JSON,
        changed_pointers=["/strategy/creative_brief"],
        transaction_id=txn,
    )


def test_classify_pointers_priority_and_match() -> None:
    assert classify_pointers(["/settings/resolution"]) is None
    # Declaration order decides the winner: strategy outranks motion.
    assert classify_pointers([MOTION_PTR, "/strategy/creative_brief"]) == (
        "strategy",
        "text",
        ["/strategy/creative_brief"],
    )
    assert classify_pointers([MOTION_PTR]) == (
        "motion",
        "motion",
        [MOTION_PTR],
    )


def test_parse_sync_advisory_derives_ok_deterministically() -> None:
    advisory = _parse_advisory(_advisory_payload(weak_concept=True))
    weak = advisory.weak_scores()
    assert [item.row_key for item in weak] == ["concept"]
    # A weak score without a cited finding cannot stand (fail-closed).
    payload = json.loads(_advisory_payload(weak_concept=True))
    payload["scores"][0]["finding"] = ""
    advisory = _parse_advisory(json.dumps(payload, ensure_ascii=False))
    assert advisory.weak_scores() == []
    # Every rubric row must be present.
    payload = json.loads(_advisory_payload(weak_concept=False))
    payload["scores"] = payload["scores"][:2]
    with pytest.raises(ValueError):
        _parse_advisory(json.dumps(payload))


def _stub_model(monkeypatch, responses: list[str]) -> list[str]:
    calls: list[str] = []

    async def fake_chat_completion(prompt, **kwargs):
        calls.append(prompt)
        return responses[min(len(calls), len(responses)) - 1]

    monkeypatch.setattr(text_model, "chat_completion", fake_chat_completion)
    return calls


def _r2v_contract_project(
    *,
    storyboard_prompt: str,
    video_prompt: str,
    dialogues: tuple[str, ...] = ("",),
    character_refs: tuple[str, ...] = (),
    scene_ref: str | None = None,
) -> dict:
    return {
        "settings": {"aspect_ratio": "16:9", "language": "zh-CN"},
        "timelines": {
            "items": {
                "t": {
                    "elements_by_id": {
                        "e": {
                            "creation": {
                                "type": "r2v",
                                "character_refs": list(character_refs),
                                "scene_ref": scene_ref,
                                "narrative": "。".join(dialogues),
                                "storyboard_prompt": storyboard_prompt,
                                "video_prompt": video_prompt,
                            },
                        },
                    },
                },
            },
        },
    }


def test_sync_review_lifecycle_rounds_dedup_cap_and_reset(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # Off means the model is never touched and no state is written.
    monkeypatch.delenv("CREATOR_SYNC_REVIEW_ENABLED", raising=False)
    monkeypatch.setattr(text_model, "chat_completion", None)
    assert _sync_review(tmp_path, txn="txn-off") is None
    assert not (tmp_path / "runtime").exists()

    monkeypatch.setenv("CREATOR_SYNC_REVIEW_ENABLED", "1")
    # Turning the switch on must not review unchanged historical content.
    # A later no-op or unrelated commit still has no reviewable changes.
    for pointers in ([], ["/name"]):
        assert (
            maybe_sync_review(
                project_id="project-run-review",
                project_root=tmp_path,
                project_json=PROJECT_JSON,
                changed_pointers=pointers,
                transaction_id="txn-after-toggle",
            )
            is None
        )
    assert not (tmp_path / "runtime").exists()
    weak = _advisory_payload(weak_concept=True)
    clean = _advisory_payload(weak_concept=False)
    calls = _stub_model(monkeypatch, [weak, weak, clean])

    def _review(brief: str, txn: str):
        document = json.loads(json.dumps(PROJECT_JSON))
        document["strategy"]["creative_brief"] = brief
        return _sync_review(tmp_path, txn=txn, project_json=document)

    advisory = _review("版本一", "txn-1")
    assert advisory is not None
    assert advisory["pointer_group"] == "strategy"
    assert _review("版本一", "txn-1b") is None, "identical content dedups"
    assert len(calls) == 1
    assert _review("版本二", "txn-2") is not None
    # Two consecutive advisories exhaust the group's budget.
    assert _review("版本三", "txn-3") is None
    assert len(calls) == 2
    # A clean review resets the counter for later work.
    state_path = tmp_path / "runtime" / "run-review" / "sync" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["strategy"]["rounds"] = 0
    state_path.write_text(json.dumps(state), encoding="utf-8")
    assert _review("版本四", "txn-4") is None  # clean review -> no advisory
    assert len(calls) == 3

    # Model failure is fail-open: commits never block on review errors.
    async def _boom(prompt, **kwargs):
        raise RuntimeError("model exploded")

    monkeypatch.setattr(text_model, "chat_completion", _boom)
    failure = _review("版本五", "txn-5")
    assert failure["status"] == "unavailable"
    assert failure["review_errors"] == ["RuntimeError"]
    assert failure["scores"] == []


def test_review_deadline_cancels_call_and_backs_off_changed_content(
    tmp_path,
    monkeypatch,
):
    import time

    monkeypatch.setenv("CREATOR_SYNC_REVIEW_ENABLED", "1")
    monkeypatch.setattr(text_review, "_SYNC_REVIEW_BUDGET_SECONDS", 0.01)
    calls = []
    cancelled = []

    async def slow(*args, **kwargs):
        calls.append(True)
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    monkeypatch.setattr(text_model, "chat_completion", slow)
    start = time.monotonic()
    first = _sync_review(tmp_path, txn="timeout")
    assert time.monotonic() - start < 2
    assert first["status"] == "unavailable"
    assert first["review_errors"] == ["TimeoutError"]
    assert len(cancelled) == 1
    changed = {**PROJECT_JSON, "strategy": {"creative_brief": "新的创意"}}
    second = _sync_review(tmp_path, txn="skip", project_json=changed)
    assert second["review_errors"] == ["REVIEW_COOLDOWN"]
    assert len(calls) == 1
    state_path = tmp_path / "runtime/run-review/sync/state.json"
    state = json.loads(state_path.read_text())
    assert state["strategy"].get("hashes", []) == []
    assert state["strategy"]["failures"] == 1
    state["strategy"]["retry_after"] = 1
    state_path.write_text(json.dumps(state))
    recovered = _stub_model(
        monkeypatch,
        [_advisory_payload(weak_concept=False)],
    )
    assert (
        _sync_review(tmp_path, txn="recovered", project_json=changed) is None
    )
    assert len(recovered) == 1
    assert json.loads(state_path.read_text())["strategy"]["failures"] == 0


def test_script_timeout_keeps_completed_appeal_and_reports_partial(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("CREATOR_SYNC_REVIEW_ENABLED", "1")
    monkeypatch.setattr(text_review, "_SYNC_REVIEW_BUDGET_SECONDS", 0.01)
    monkeypatch.setattr(text_review, "_script_check_enabled", lambda: True)
    _stub_model(monkeypatch, [_advisory_payload(weak_concept=False)])

    async def slow_script(**kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(
        "services.run_review.script_review.run_script_check",
        slow_script,
    )
    project = {
        **PROJECT_JSON,
        "timelines": {
            "items": {
                "t": {
                    "elements_by_id": {
                        "e": {
                            "creation": {
                                "type": "r2v",
                                "narrative": "小猫迈出脚步",
                                "storyboard_prompt": "画出迈步过程",
                                "video_prompt": "缓缓迈步",
                            },
                        },
                    },
                },
            },
        },
    }
    # Exercise parent-pointer expansion and the shared two-call budget.
    result = maybe_sync_review(
        project_id="project-run-review",
        project_root=tmp_path,
        project_json=project,
        changed_pointers=["/timelines/items/t/elements_by_id/e"],
        transaction_id="partial",
    )
    payloads = result.get("advisories", [result])
    partial = next(
        payload for payload in payloads if payload.get("status") == "partial"
    )
    assert len(partial["scores"]) == 3
    assert partial["script_check"]["status"] == "unavailable"
    assert partial["review_errors"] == ["SCRIPT_CHECK_UNAVAILABLE"]
    # Deterministic prompt findings still reach the agent during degradation.
    assert any(
        (payload.get("prompt_check") or {}).get("findings")
        for payload in payloads
    )


def test_mixed_strategy_and_shots_commit_still_runs_script_check(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CREATOR_SYNC_REVIEW_ENABLED", "1")
    monkeypatch.setattr(text_review, "_script_check_enabled", lambda: True)
    calls = _stub_model(
        monkeypatch,
        [_advisory_payload(weak_concept=False)],
    )
    observed: dict[str, str] = {}

    async def fake_script_check(*, strategy_payload, content_payload):
        observed["strategy"] = strategy_payload
        observed["shots"] = content_payload
        return {
            "coverage_missing": [
                {"source_quote": "雨天独白", "note": "分镜未承接"},
            ],
            "hallucinated": [],
            "unshootable": [],
            "summary": "有一处覆盖缺失",
        }

    monkeypatch.setattr(
        "services.run_review.script_review.run_script_check",
        fake_script_check,
    )
    project = {
        **PROJECT_JSON,
        "timelines": {
            "items": {
                "t": {
                    "elements_by_id": {
                        "e": {
                            "creation": {
                                "narrative": "猫看向窗外",
                            },
                        },
                    },
                },
            },
        },
    }
    result = maybe_sync_review(
        project_id="project-run-review",
        project_root=tmp_path,
        project_json=project,
        changed_pointers=[
            "/strategy/creative_brief",
            "/timelines/items/t/elements_by_id/e/creation/narrative",
        ],
        transaction_id="txn-mixed",
    )
    assert result is not None
    assert result["pointer_group"] == "generation_content"
    assert len(calls) == 2, "strategy and shots are both reviewed"
    assert result["script_check"]["coverage_missing"]
    assert "雨天独白" in observed["strategy"]
    assert "猫看向窗外" in observed["shots"]


def test_mixed_pointer_groups_review_concurrently(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CREATOR_SYNC_REVIEW_ENABLED", "1")
    active = 0
    max_active = 0

    async def fake_chat_completion(_prompt, **_kwargs):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0)
        active -= 1
        return _advisory_payload(weak_concept=False)

    monkeypatch.setattr(text_model, "chat_completion", fake_chat_completion)
    project = {
        **PROJECT_JSON,
        "timelines": {
            "items": {
                "t": {
                    "elements_by_id": {
                        "e": {
                            "creation": {
                                "video_prompt": "纸船穿过晨光倒影",
                            },
                        },
                    },
                },
            },
        },
    }
    result = maybe_sync_review(
        project_id="project-run-review",
        project_root=tmp_path,
        project_json=project,
        changed_pointers=[
            "/strategy/creative_brief",
            "/timelines/items/t/elements_by_id/e/creation/video_prompt",
        ],
        transaction_id="txn-concurrent-groups",
    )
    assert result is None
    assert max_active == 3  # Strategy, content taste and script alignment.


def test_generation_text_blocker_survives_repair_turn_but_not_hard_cap(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CREATOR_SYNC_REVIEW_ENABLED", "1")
    weak = _advisory_payload(weak_concept=True)
    _stub_model(monkeypatch, [weak, weak])
    pointer = "/timelines/items/t/elements_by_id/e/creation/video_prompt"

    def review(prompt: str, txn: str):
        return maybe_sync_review(
            project_id="project-run-review",
            project_root=tmp_path,
            project_json={
                "timelines": {
                    "items": {
                        "t": {
                            "elements_by_id": {
                                "e": {"creation": {"video_prompt": prompt}},
                            },
                        },
                    },
                },
            },
            changed_pointers=[pointer],
            transaction_id=txn,
            gate_token=f"gate-{txn}",
        )

    reports_root = tmp_path / "runtime" / "run-review"
    assert review("纸船缓慢驶入晨雾", "txn-shots-1") is not None
    blockers = admission.active_sync_fences(reports_root)
    assert len(blockers) == 1
    assert blockers[0]["pointer_group"] == "generation_content"
    assert review("纸船穿过金色倒影驶入晨雾", "txn-shots-2") is not None
    assert not admission.active_sync_fences(reports_root)


def test_whole_element_create_expands_nested_generation_text() -> None:
    project = {
        "timelines": {
            "items": {
                "timeline:main": {
                    "elements_by_id": {
                        "elem:one": {
                            "creation": {
                                "type": "r2v",
                                "intent": "纸船驶向晨雾",
                                "narrative": "纸船随涟漪前进",
                                "storyboard_prompt": "晨雾湖面与白色纸船",
                                "video_prompt": "纸船缓慢向前漂移",
                            },
                        },
                    },
                },
            },
        },
    }
    root = "/timelines/items/timeline:main/elements_by_id/elem:one"
    snapshot_id = "snapshot:timeline:main:1"
    snapshot_root = f"/timelines/items/{snapshot_id}"
    # An automatic copy can retain prompts invalid under current rules.
    # Saving it must not create fresh review or repair work for old content.
    project["timelines"]["items"][snapshot_id] = {
        "elements_by_id": {
            f"{snapshot_id}:elem:old": {
                "creation": {
                    "type": "r2v",
                    "storyboard_prompt": "",
                    "video_prompt": "",
                    "intent": "Historical text only",
                },
            },
        },
    }
    expanded = reviewable_changed_pointers(project, [root, snapshot_root])
    assert expanded == reviewable_changed_pointers(project, ["/timelines"])
    assert f"{root}/creation/narrative" in expanded
    assert f"{root}/creation/storyboard_prompt" in expanded
    assert f"{root}/creation/video_prompt" in expanded
    assert not any(snapshot_id in pointer for pointer in expanded)
    groups = classify_pointer_groups(expanded)
    assert groups
    assert groups[0][0] == "generation_content"
    assert not reviewable_changed_pointers(project, [snapshot_root])
    assert not check_changed_r2v_prompt_contracts(
        project,
        [snapshot_root],
    )["applicable"]
    assert check_changed_r2v_prompt_contracts(
        project,
        ["/timelines"],
    )[
        "checked_elements"
    ] == ["elem:one"]


def test_empty_r2v_prompt_is_reported_without_calling_review_model(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CREATOR_SYNC_REVIEW_ENABLED", "1")
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "happyhorse-1.1",
    )
    monkeypatch.setattr(model_config, "get_video_backend", lambda: "wan")
    monkeypatch.setattr(text_model, "chat_completion", None)
    pointer = (
        "/timelines/items/timeline:main/elements_by_id/elem:one/"
        "creation/video_prompt"
    )
    project = {
        "settings": {"aspect_ratio": "16:9", "language": "zh-CN"},
        "timelines": {
            "items": {
                "timeline:main": {
                    "elements_by_id": {
                        "elem:one": {
                            "enabled": True,
                            "creation": {
                                "type": "r2v",
                                "narrative": "我们出发。",
                                "storyboard_prompt": (
                                    "16:9 故事板，1 个分镜格；" "每一个分镜格内部均为 16:9。"
                                ),
                                "video_prompt": "",
                            },
                        },
                    },
                },
            },
        },
    }

    result = maybe_sync_review(
        project_id="project-run-review",
        project_root=tmp_path,
        project_json=project,
        changed_pointers=[pointer],
        transaction_id="txn-empty-video",
        gate_token="gate-empty-video",
    )

    assert result is not None
    assert result["prompt_check"]["passed"] is False
    assert [item["code"] for item in result["prompt_check"]["findings"]] == [
        "VIDEO_PROMPT_EMPTY",
    ]
    blockers = admission.active_sync_fences(
        tmp_path / "runtime" / "run-review",
    )
    assert [item["pointer_group"] for item in blockers] == [
        "generation_content",
    ]


def test_clean_r2v_prompt_repair_releases_contract_blocker(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CREATOR_SYNC_REVIEW_ENABLED", "1")
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "happyhorse-1.1",
    )
    monkeypatch.setattr(model_config, "get_video_backend", lambda: "wan")
    _stub_model(monkeypatch, [_advisory_payload(weak_concept=False)])
    base = "/timelines/items/timeline:main/elements_by_id/elem:one"
    project = {
        "settings": {"aspect_ratio": "16:9", "language": "zh-CN"},
        "timelines": {
            "items": {
                "timeline:main": {
                    "elements_by_id": {
                        "elem:one": {
                            "enabled": True,
                            "creation": {
                                "type": "r2v",
                                "narrative": "我们出发。",
                                "storyboard_prompt": (
                                    "16:9 故事板，1 个分镜格；" "每一个分镜格内部均为 16:9。"
                                ),
                                "video_prompt": (
                                    "[Image 1] 仅提供分镜动作顺序。" "角色坚定地说：‘我们出发。’"
                                ),
                            },
                        },
                    },
                },
            },
        },
    }
    reports_root = tmp_path / "runtime" / "run-review"
    admission.hold_sync_blocker(
        reports_root,
        project_id="project-run-review",
        pointer_group="generation_content",
        reviewed_pointers=[f"{base}/creation/video_prompt"],
        round_number=1,
    )

    result = maybe_sync_review(
        project_id="project-run-review",
        project_root=tmp_path,
        project_json=project,
        changed_pointers=[f"{base}/creation/video_prompt"],
        transaction_id="txn-fixed-video",
        gate_token="gate-fixed-video",
    )

    assert result is None
    assert not admission.active_sync_fences(reports_root)


def test_happyhorse_explicit_reference_roles_follow_runtime_order(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "happyhorse-1.1",
    )
    monkeypatch.setattr(model_config, "get_video_backend", lambda: "wan")
    base = "/timelines/items/t/elements_by_id/e"
    project = {
        "settings": {"aspect_ratio": "16:9", "language": "zh-CN"},
        "timelines": {
            "items": {
                "t": {
                    "elements_by_id": {
                        "e": {
                            "creation": {
                                "type": "r2v",
                                "character_refs": ["char:hero"],
                                "scene_ref": "scene:room",
                                "prop_refs": ["prop:lamp"],
                                "narrative": "",
                                "storyboard_prompt": (
                                    "16:9 故事板，1 个分镜格；" "每一个分镜格内部均为 16:9。"
                                ),
                                "video_prompt": (
                                    "[Image 1] is the storyboard. "
                                    "[Image 2] is the character reference. "
                                    "[Image 3] is the lamp prop study. "
                                    "[Image 4] is the room environment."
                                ),
                            },
                        },
                    },
                },
            },
        },
    }

    report = check_changed_r2v_prompt_contracts(project, [base])

    assert [item["code"] for item in report["findings"]] == [
        "VIDEO_REFERENCE_ROLE_MISMATCH",
        "VIDEO_REFERENCE_ROLE_MISMATCH",
    ]
    assert "实际是 scene" in report["findings"][0]["message"]
    assert "实际是 prop" in report["findings"][1]["message"]


def _add_reference_artifact(
    project: dict,
    version_id: str,
    *,
    owner_ref: str,
    kind: str = "visual_asset_image",
    slot_id: str | None = None,
) -> None:
    slot_id = slot_id or f"{owner_ref}:image"
    file_id = f"file-{version_id}"
    assets = project["assets"]
    assets["files_by_id"][file_id] = {
        "file_id": file_id,
        "kind": "artifact_payload",
        "relative_uri": f"assets/artifacts/{file_id}.png",
        "sha256": "0" * 64,
        "size_bytes": 1,
        "media_type": "image/png",
        "created_at": project["created_at"],
    }
    slot = assets["artifact_slots_by_id"].setdefault(
        slot_id,
        {
            "slot_id": slot_id,
            "kind": kind,
            "owner_ref": owner_ref,
            "version_ids": [],
        },
    )
    slot["version_ids"].append(version_id)
    slot["selected_version_id"] = version_id
    assets["artifact_versions_by_id"][version_id] = {
        "version_id": version_id,
        "slot_id": slot_id,
        "kind": kind,
        "owner_ref": owner_ref,
        "name": version_id,
        "file_id": file_id,
        "checksum": "0" * 64,
        "based_on_generation": 0,
        "created_at": project["created_at"],
    }


def _explicit_order_project(video_prompt: str) -> dict:
    """Schema-valid Element with authored character → prop → scene order."""

    project = Project.new(
        project_id="project-reference-contract",
        name="Reference contract",
    ).model_dump(mode="json")
    for role, entity_id in (
        ("character", "char:hero"),
        ("prop", "prop:lamp"),
        ("scene", "scene:room"),
    ):
        version_id = f"artifact-version-{role}"
        _add_reference_artifact(
            project,
            version_id,
            owner_ref=f"asset:{entity_id}",
        )
        project["visual"]["entities"]["items"][entity_id] = {
            "entity_id": entity_id,
            "kind": role,
            "name": entity_id,
            "required_variant_ids": ["default"],
            "variants": {
                "order": ["default"],
                "items": {
                    "default": {
                        "variant_id": "default",
                        "generated_artifact_version_ids": [version_id],
                        "selected_artifact_version_id": version_id,
                    },
                },
            },
        }
        project["visual"]["entities"]["order"].append(entity_id)
    _add_reference_artifact(
        project,
        "artifact-version-storyboard",
        owner_ref="element:e",
        kind="r2v_storyboard_image",
        slot_id="element:e:storyboard",
    )
    project["timelines"] = {
        "order": ["t"],
        "items": {
            "t": {
                "timeline_id": "t",
                "elements_by_id": {
                    "e": {
                        "element_id": "e",
                        "span": {"start_tick": 0, "duration_tick": 4_000},
                        "location": {},
                        "outputs": {
                            "storyboard": {"slot_id": "element:e:storyboard"},
                        },
                        "creation": {
                            "type": "r2v",
                            "character_refs": ["char:hero"],
                            "scene_ref": "scene:room",
                            "prop_refs": ["prop:lamp"],
                            "video_reference_version_ids": [
                                "artifact-version-character",
                                "artifact-version-prop",
                                "artifact-version-scene",
                            ],
                            "storyboard_prompt": (
                                "16:9 故事板，1 个分镜格；每一个分镜格内部均为 16:9。"
                            ),
                            "video_prompt": video_prompt,
                        },
                    },
                },
            },
        },
    }
    return Project.model_validate(project).model_dump(mode="json")


@pytest.mark.parametrize("unselected", [False, True])
def test_default_reference_roles_follow_selected_deduplicated_runtime_slots(
    monkeypatch,
    unselected,
):
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "happyhorse-1.1",
    )
    monkeypatch.setattr(model_config, "get_video_backend", lambda: "wan")
    project = _explicit_order_project("")
    creation = project["timelines"]["items"]["t"]["elements_by_id"]["e"][
        "creation"
    ]
    creation["video_reference_version_ids"] = []
    creation["character_refs"] = ["char:hero", "char:hero"]
    if unselected:
        project["visual"]["entities"]["items"]["char:hero"]["variants"][
            "items"
        ]["default"]["selected_artifact_version_id"] = None
    creation["video_prompt"] = (
        "[Image 1] is the storyboard. "
        + ("" if unselected else "[Image 2] is the character. ")
        + f"[Image {2 if unselected else 3}] is the scene. "
        + f"[Image {3 if unselected else 4}] is the prop."
    )
    validated = Project.model_validate(project)
    report = check_changed_r2v_prompt_contracts(
        validated.model_dump(mode="json"),
        ["/timelines/items/t/elements_by_id/e"],
    )
    assert report["passed"], report


def test_explicit_reference_order_overrides_canonical_type_roles(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "happyhorse-1.1",
    )
    monkeypatch.setattr(model_config, "get_video_backend", lambda: "wan")
    project = _explicit_order_project(
        "[Image 1] is the storyboard. "
        "[Image 2] is the character reference. "
        "[Image 3] is the lamp prop study. "
        "[Image 4] is the room environment.",
    )

    report = check_changed_r2v_prompt_contracts(
        project,
        ["/timelines/items/t/elements_by_id/e"],
    )

    # [Image 3] really is the prop in the authored runtime order, so the
    # prompt is correct and nothing may be gated.
    assert report["passed"] is True


def test_explicit_reference_order_still_catches_a_real_swap(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "happyhorse-1.1",
    )
    monkeypatch.setattr(model_config, "get_video_backend", lambda: "wan")
    project = _explicit_order_project(
        "[Image 1] is the storyboard. "
        "[Image 2] is the character reference. "
        "[Image 3] is the room environment. "
        "[Image 4] continues the action.",
    )

    report = check_changed_r2v_prompt_contracts(
        project,
        ["/timelines/items/t/elements_by_id/e"],
    )

    assert [item["code"] for item in report["findings"]] == [
        "VIDEO_REFERENCE_ROLE_MISMATCH",
    ]
    assert "实际是 prop" in report["findings"][0]["message"]


@pytest.mark.parametrize("storyboard_state", ["absent", "unselected"])
@pytest.mark.parametrize(
    "roles",
    [("character", "scene", "prop"), ("character", "prop", "scene")],
    ids=["canonical", "noncanonical"],
)
@pytest.mark.parametrize("wrong_label", [False, True])
def test_explicit_references_reserve_ungenerated_storyboard_position(
    monkeypatch,
    storyboard_state,
    roles,
    wrong_label,
) -> None:
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "happyhorse-1.1",
    )
    monkeypatch.setattr(model_config, "get_video_backend", lambda: "wan")
    labels = ["storyboard", *roles]
    if wrong_label:
        labels[2] = "character"
    project = _explicit_order_project(
        " ".join(
            f"[Image {index}] is the {role} reference."
            for index, role in enumerate(labels, start=1)
        ),
    )
    element = project["timelines"]["items"]["t"]["elements_by_id"]["e"]
    versions = [f"artifact-version-{role}" for role in roles]
    element["creation"]["video_reference_version_ids"] = [
        *versions,
        versions[0],
    ]
    assets = project["assets"]
    if storyboard_state == "absent":
        element["outputs"].clear()
        del assets["artifact_slots_by_id"]["element:e:storyboard"]
        del assets["artifact_versions_by_id"]["artifact-version-storyboard"]
        del assets["files_by_id"]["file-artifact-version-storyboard"]
    else:
        assets["artifact_slots_by_id"]["element:e:storyboard"][
            "selected_version_id"
        ] = None
    validated = Project.model_validate(project)
    preview = preview_r2v_reference_order(validated, "e")
    assert [
        (ref["index"], ref["versionId"]) for ref in preview["references"]
    ] == [
        (1, ""),
        *enumerate(versions, start=2),
    ]
    assert preview["storyboardSelected"] is False
    assert preview["ready"] is False

    report = check_changed_r2v_prompt_contracts(
        validated.model_dump(mode="json"),
        ["/timelines/items/t/elements_by_id/e"],
    )

    assert report["passed"] is not wrong_label
    assert [item["code"] for item in report["findings"]] == (
        ["VIDEO_REFERENCE_ROLE_MISMATCH"] if wrong_label else []
    )
    if wrong_label:
        assert "[Image 3]" in report["findings"][0]["message"]
        assert f"实际是 {roles[1]}" in report["findings"][0]["message"]


@pytest.mark.parametrize("selected", [False, True])
@pytest.mark.parametrize("storyboard_only", [False, True])
def test_explicit_references_filter_own_storyboard_versions(
    monkeypatch,
    selected,
    storyboard_only,
) -> None:
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "happyhorse-1.1",
    )
    monkeypatch.setattr(model_config, "get_video_backend", lambda: "wan")
    project = _explicit_order_project(
        "[Image 1] is the storyboard. [Image 2] is the character. "
        "[Image 3] is the prop. [Image 4] is the scene.",
    )
    _add_reference_artifact(
        project,
        "artifact-version-storyboard-new",
        owner_ref="element:e",
        kind="r2v_storyboard_image",
        slot_id="element:e:storyboard",
    )
    if not selected:
        project["assets"]["artifact_slots_by_id"]["element:e:storyboard"][
            "selected_version_id"
        ] = None
    creation = project["timelines"]["items"]["t"]["elements_by_id"]["e"][
        "creation"
    ]
    references = creation["video_reference_version_ids"]
    if storyboard_only:
        references.clear()
    references.insert(0, "artifact-version-storyboard")
    references.append("artifact-version-storyboard-new")
    validated = Project.model_validate(project)
    preview = preview_r2v_reference_order(validated, "e")
    assert len(preview["references"]) == (1 if storyboard_only else 4)
    report = check_changed_r2v_prompt_contracts(
        validated.model_dump(mode="json"),
        ["/timelines/items/t/elements_by_id/e"],
    )
    assert report["passed"] is True


@pytest.mark.parametrize("lineup_id", ["main", "lineup:main", "char:hero"])
@pytest.mark.parametrize("bound", [False, True])
@pytest.mark.parametrize("label", ["lineup", "scene"])
def test_explicit_lineup_reference_roles_require_bound_owner(
    monkeypatch,
    lineup_id,
    bound,
    label,
) -> None:
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "happyhorse-1.1",
    )
    monkeypatch.setattr(model_config, "get_video_backend", lambda: "wan")
    project = _explicit_order_project(
        f"[Image 1] is the storyboard. [Image 2] is the {label}. "
        "[Image 3] is the character. [Image 4] is the prop. "
        "[Image 5] is the scene.",
    )
    entities = project["visual"]["entities"]
    entities["items"]["char:friend"] = {
        "entity_id": "char:friend",
        "kind": "character",
        "name": "Friend",
        "required_variant_ids": [],
    }
    entities["order"].append("char:friend")
    _add_reference_artifact(
        project,
        "artifact-version-lineup",
        owner_ref=f"lineup:{lineup_id}",
        kind="cast_lineup_image",
    )
    project["visual"]["cast_lineups"] = {
        "order": [lineup_id],
        "items": {
            lineup_id: {
                "lineup_id": lineup_id,
                "name": "Main cast",
                "character_refs": ["char:hero", "char:friend"],
                "generated_artifact_version_ids": ["artifact-version-lineup"],
                "selected_artifact_version_id": "artifact-version-lineup",
            },
        },
    }
    creation = project["timelines"]["items"]["t"]["elements_by_id"]["e"][
        "creation"
    ]
    creation["cast_lineup_refs"] = [lineup_id] if bound else []
    creation["video_reference_version_ids"].insert(
        0,
        "artifact-version-lineup",
    )
    report = check_changed_r2v_prompt_contracts(
        Project.model_validate(project).model_dump(mode="json"),
        ["/timelines/items/t/elements_by_id/e"],
    )
    mismatch = bound and label != "lineup"
    assert report["passed"] is not mismatch
    assert [item["code"] for item in report["findings"]] == (
        ["VIDEO_REFERENCE_ROLE_MISMATCH"] if mismatch else []
    )
    if mismatch:
        assert "[Image 2]" in report["findings"][0]["message"]
        assert "实际是 lineup" in report["findings"][0]["message"]


@pytest.mark.parametrize(
    "owner_ref",
    ["unknown:char:hero", "asset:unknown", None],
)
def test_explicit_reference_unknown_owner_is_not_guessed(
    monkeypatch,
    owner_ref,
) -> None:
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "happyhorse-1.1",
    )
    monkeypatch.setattr(model_config, "get_video_backend", lambda: "wan")
    project = _explicit_order_project(
        "[Image 1] is the storyboard. [Image 2] is the scene. "
        "[Image 3] is the character. [Image 4] is the prop. "
        "[Image 5] is the scene.",
    )
    _add_reference_artifact(
        project,
        "version-unknown",
        owner_ref=owner_ref or "asset:char:hero",
    )
    if owner_ref is None:
        assets = project["assets"]
        artifact = assets["artifact_versions_by_id"].pop("version-unknown")
        slot = assets["artifact_slots_by_id"][artifact["slot_id"]]
        slot["version_ids"].remove("version-unknown")
        slot["selected_version_id"] = slot["version_ids"][0]
        assets["source_versions_by_id"]["version-unknown"] = {
            "version_id": "version-unknown",
            "logical_asset_id": "char:hero",
            "name": "Unowned source",
            "file_id": artifact["file_id"],
            "checksum": artifact["checksum"],
            "media_kind": "image",
            "media_type": "image/png",
            "created_at": project["created_at"],
        }
    creation = project["timelines"]["items"]["t"]["elements_by_id"]["e"][
        "creation"
    ]
    creation["video_reference_version_ids"].insert(0, "version-unknown")
    report = check_changed_r2v_prompt_contracts(
        Project.model_validate(project).model_dump(mode="json"),
        ["/timelines/items/t/elements_by_id/e"],
    )
    assert report["passed"] is True


def test_borderless_outer_whitespace_is_not_a_panel_border_conflict(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "happyhorse-1.1",
    )
    monkeypatch.setattr(model_config, "get_video_backend", lambda: "wan")
    base = "/timelines/items/t/elements_by_id/e"
    project = {
        "settings": {"aspect_ratio": "16:9", "language": "zh-CN"},
        "timelines": {
            "items": {
                "t": {
                    "elements_by_id": {
                        "e": {
                            "creation": {
                                "type": "r2v",
                                "narrative": "",
                                "storyboard_prompt": (
                                    "16:9 故事板，3 个分镜格；每一个分镜格内部均为 "
                                    "16:9，并有完整清晰边界。末行居中，剩余面积只作"
                                    "无边框外层留白，不画第 4 个带框空槽。"
                                ),
                                "video_prompt": "[Image 1] 仅提供分镜动作顺序。",
                            },
                        },
                    },
                },
            },
        },
    }

    report = check_changed_r2v_prompt_contracts(project, [base])

    assert report["passed"] is True


@pytest.mark.parametrize(
    ("video_prompt", "dialogue"),
    [
        pytest.param(
            "阿穆低声说：“灯塔，亮起来！”",
            "阿穆：（喘息）灯 塔，亮 起 来！",
            id="annotations",
        ),
        pytest.param(
            '阿穆低声说:"灯塔,亮起来!"',
            "阿穆：“灯塔，亮起来！”",
            id="punctuation-width",
        ),
    ],
)
def test_prompt_contract_normalizes_dialogue_without_blocking_generation(
    monkeypatch,
    video_prompt,
    dialogue,
) -> None:
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "happyhorse-1.1",
    )
    monkeypatch.setattr(model_config, "get_video_backend", lambda: "wan")
    project = _r2v_contract_project(
        storyboard_prompt="16:9 故事板，1 个分镜格；每一个分镜格内部均为 16:9。",
        video_prompt=f"[Image 1] 仅提供分镜动作顺序。{video_prompt}",
        dialogues=(dialogue,),
    )
    report = check_changed_r2v_prompt_contracts(
        project,
        ["/timelines/items/t/elements_by_id/e"],
    )
    assert report["passed"] is True


def test_panel_count_requires_an_explicit_panel_noun(monkeypatch) -> None:
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "happyhorse-1.1",
    )
    monkeypatch.setattr(model_config, "get_video_backend", lambda: "wan")
    project = _r2v_contract_project(
        storyboard_prompt=("16:9 故事板，3 格角色造型研究；" "每一个分镜格内部均为 16:9。"),
        video_prompt="[Image 1] 仅提供分镜动作顺序。",
        dialogues=("", "", ""),
    )

    report = check_changed_r2v_prompt_contracts(
        project,
        ["/timelines/items/t/elements_by_id/e"],
    )

    assert [item["code"] for item in report["findings"]] == [
        "STORYBOARD_PANEL_COUNT_MISSING",
    ]


def test_narrative_speech_must_reach_video_prompt_but_sign_text_need_not():
    project = _r2v_contract_project(
        storyboard_prompt="16:9 故事板，1 个分镜格，每格 16:9。",
        video_prompt="[Image 1]提供分镜顺序，女子回头。",
        dialogues=(
            "招牌写着“星光旅店”。纸上的说明：“此门不通行”。"
            '女子没说“再会”。She does not say "farewell". '
            'The sign says "CLOSED"。女子不舍地说：“别走！”',
        ),
    )
    pointer = "/timelines/items/t/elements_by_id/e"
    report = check_changed_r2v_prompt_contracts(project, [pointer])
    assert [item["code"] for item in report["findings"]] == [
        "VIDEO_DIALOGUE_MISSING",
    ]
    project["timelines"]["items"]["t"]["elements_by_id"]["e"]["creation"][
        "video_prompt"
    ] += "女子低声说：‘别走!’"
    assert check_changed_r2v_prompt_contracts(project, [pointer])["passed"]


def test_keyframe_count_is_independent_of_shots(monkeypatch) -> None:
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "happyhorse-1.1",
    )
    monkeypatch.setattr(model_config, "get_video_backend", lambda: "wan")
    dialogues = ("",)  # one continuous shot can have many reference frames
    declared = _r2v_contract_project(
        storyboard_prompt=("16:9 故事板，九宫格布局；" "每一个分镜格内部均为 16:9。"),
        video_prompt="[Image 1] 仅提供分镜动作顺序。",
        dialogues=dialogues,
    )
    more_keyframes = _r2v_contract_project(
        storyboard_prompt=("16:9 故事板，十六宫格布局；" "每一个分镜格内部均为 16:9。"),
        video_prompt="[Image 1] 仅提供分镜动作顺序。",
        dialogues=dialogues,
    )

    declared_report = check_changed_r2v_prompt_contracts(
        declared,
        ["/timelines/items/t/elements_by_id/e"],
    )
    more_keyframes_report = check_changed_r2v_prompt_contracts(
        more_keyframes,
        ["/timelines/items/t/elements_by_id/e"],
    )

    assert declared_report["passed"] is True
    assert more_keyframes_report["passed"] is True


def test_happyhorse_role_scan_uses_the_full_reference_segment(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "happyhorse-1.1",
    )
    monkeypatch.setattr(model_config, "get_video_backend", lambda: "wan")
    project = _r2v_contract_project(
        storyboard_prompt=("16:9 故事板，1 个分镜格；每一个分镜格内部均为 16:9。"),
        video_prompt=(
            "[Image 1] " + ("中性视觉说明。" * 100) + "This is the scene environment."
        ),
    )

    report = check_changed_r2v_prompt_contracts(
        project,
        ["/timelines/items/t/elements_by_id/e"],
    )

    assert [item["code"] for item in report["findings"]] == [
        "VIDEO_REFERENCE_ROLE_MISMATCH",
    ]


@pytest.mark.parametrize(
    ("model", "backend", "language", "prompt"),
    [
        (
            "wan3.0-video",
            "wan",
            "zh-CN",
            "图1 为分镜。图2 为场景环境。图3 为角色人物。",
        ),
        (
            "wan2.7-i2v",
            "wan",
            "zh-CN",
            "图1 为分镜。图2 为场景环境。图3 为角色人物。",
        ),
        (
            "wan2.6-r2v",
            "wan",
            "en-US",
            "character1 is storyboard. character2 is scene environment. "
            "character3 is character reference.",
        ),
        (
            "doubao-seedance-2-0-250428",
            "seedance2",
            "zh-CN",
            "图片1 为分镜。图片2 为场景环境。图片3 为角色人物。",
        ),
        (
            "kling-v3-omni",
            "kling",
            "zh-CN",
            "@image_1 为分镜。@image_2 为场景环境。@image_3 为角色人物。",
        ),
        (
            "kling/kling-v3-omni-video-generation",
            "kling",
            "zh-CN",
            "<<<image_1>>> 为分镜。<<<image_2>>> 为场景环境。" + "<<<image_3>>> 为角色人物。",
        ),
        (
            "vidu/viduq3-mix_reference2video",
            "vidu",
            "zh-CN",
            "图1 为分镜。图2 为场景环境。图3 为角色人物。",
        ),
    ],
)
def test_positional_provider_reference_roles_follow_runtime_order(
    monkeypatch,
    model,
    backend,
    language,
    prompt,
) -> None:
    monkeypatch.setattr(model_config, "get_video_model_name", lambda: model)
    monkeypatch.setattr(model_config, "get_video_backend", lambda: backend)
    project = _r2v_contract_project(
        storyboard_prompt=("16:9 故事板，1 个分镜格；每一个分镜格内部均为 16:9。"),
        video_prompt=prompt,
        character_refs=("char:hero",),
        scene_ref="scene:room",
    )
    project["settings"]["language"] = language

    report = check_changed_r2v_prompt_contracts(
        project,
        ["/timelines/items/t/elements_by_id/e"],
    )

    assert [item["code"] for item in report["findings"]] == [
        "VIDEO_REFERENCE_ROLE_MISMATCH",
        "VIDEO_REFERENCE_ROLE_MISMATCH",
    ]
