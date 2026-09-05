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
    shot_ids = tuple(f"shot:{index}" for index in range(1, len(dialogues) + 1))
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
                                "shots": {
                                    "items": {
                                        shot_id: {"dialogue": dialogue}
                                        for shot_id, dialogue in zip(
                                            shot_ids,
                                            dialogues,
                                            strict=True,
                                        )
                                    },
                                    "order": list(shot_ids),
                                },
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
    assert _review("版本五", "txn-5") is None


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

    async def fake_script_check(*, strategy_payload, shots_payload):
        observed["strategy"] = strategy_payload
        observed["shots"] = shots_payload
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
                                "shots": {
                                    "items": {
                                        "s1": {"description": "猫看向窗外"},
                                    },
                                },
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
            "/timelines/items/t/elements_by_id/e/creation/shots",
        ],
        transaction_id="txn-mixed",
    )
    assert result is not None
    assert result["pointer_group"] == "shots"
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
    assert max_active == 2


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
    assert blockers[0]["pointer_group"] == "shots"
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
                                "shots": {
                                    "items": {
                                        "shot:1": {
                                            "description": "纸船随涟漪前进",
                                        },
                                    },
                                    "order": ["shot:1"],
                                },
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
    expanded = reviewable_changed_pointers(project, [root])
    assert f"{root}/creation/shots" in expanded
    assert f"{root}/creation/storyboard_prompt" in expanded
    assert f"{root}/creation/video_prompt" in expanded
    groups = classify_pointer_groups(expanded)
    assert groups
    assert groups[0][0] == "shots"


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
                                "shots": {
                                    "items": {
                                        "shot:1": {
                                            "dialogue": "我们出发。",
                                        },
                                    },
                                    "order": ["shot:1"],
                                },
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
    assert [item["pointer_group"] for item in blockers] == ["shots"]


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
                                "shots": {
                                    "items": {
                                        "shot:1": {
                                            "dialogue": "我们出发。",
                                        },
                                    },
                                    "order": ["shot:1"],
                                },
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
        pointer_group="shots",
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
                                "shots": {
                                    "items": {"s": {"dialogue": ""}},
                                    "order": ["s"],
                                },
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
                                "shots": {
                                    "items": {
                                        "s1": {"dialogue": ""},
                                        "s2": {"dialogue": ""},
                                        "s3": {"dialogue": ""},
                                    },
                                    "order": ["s1", "s2", "s3"],
                                },
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


def test_prompt_contract_normalizes_dialogue_plan_annotations(
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
        video_prompt=("[Image 1] 仅提供分镜动作顺序。阿穆低声说：“灯塔，亮起来！”"),
        dialogues=("阿穆：（喘息）灯 塔，亮 起 来！",),
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


def test_dialogue_match_tolerates_punctuation_width_variants(
    monkeypatch,
) -> None:
    """Full-width vs half-width punctuation must not gate a paid call."""

    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "happyhorse-1.1",
    )
    monkeypatch.setattr(model_config, "get_video_backend", lambda: "wan")
    project = _r2v_contract_project(
        storyboard_prompt=("16:9 故事板，1 个分镜格；每一个分镜格内部均为 16:9。"),
        video_prompt=('[Image 1] 仅提供分镜动作顺序。阿穆低声说:"灯塔,亮起来!"'),
        dialogues=("阿穆：“灯塔，亮起来！”",),
    )

    report = check_changed_r2v_prompt_contracts(
        project,
        ["/timelines/items/t/elements_by_id/e"],
    )

    assert report["passed"] is True


def test_panel_count_accepts_chinese_numerals(monkeypatch) -> None:
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "happyhorse-1.1",
    )
    monkeypatch.setattr(model_config, "get_video_backend", lambda: "wan")
    dialogues = ("",) * 6  # six shots pad to a 3x3 grid of nine cells
    declared = _r2v_contract_project(
        storyboard_prompt=("16:9 故事板，九宫格布局；" "每一个分镜格内部均为 16:9。"),
        video_prompt="[Image 1] 仅提供分镜动作顺序。",
        dialogues=dialogues,
    )
    mismatched = _r2v_contract_project(
        storyboard_prompt=("16:9 故事板，十六宫格布局；" "每一个分镜格内部均为 16:9。"),
        video_prompt="[Image 1] 仅提供分镜动作顺序。",
        dialogues=dialogues,
    )

    declared_report = check_changed_r2v_prompt_contracts(
        declared,
        ["/timelines/items/t/elements_by_id/e"],
    )
    mismatched_report = check_changed_r2v_prompt_contracts(
        mismatched,
        ["/timelines/items/t/elements_by_id/e"],
    )

    assert declared_report["passed"] is True
    assert [item["code"] for item in mismatched_report["findings"]] == [
        "STORYBOARD_PANEL_COUNT_MISSING",
    ]


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
