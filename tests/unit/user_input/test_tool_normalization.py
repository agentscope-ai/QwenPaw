# -*- coding: utf-8 -*-
from qwenpaw.agents.tools.user_input import _normalize_question


def test_normalize_claw_code_like_single_choice_question():
    normalized = _normalize_question(
        {
            "type": "single_choice",
            "name": "traveler_type",
            "label": "同行人员类型？",
            "options": ["独自/情侣/朋友（默认）", "亲子", "带老人"],
            "required": True,
        },
        0,
    )

    assert normalized["id"] == "traveler_type"
    assert normalized["question"] == "同行人员类型？"
    assert normalized["kind"] == "choice_with_custom"
    assert normalized["options"][0]["label"] == "独自/情侣/朋友（默认）"
    assert normalized["options"][0]["recommended"] is True


def test_normalize_text_question():
    normalized = _normalize_question(
        {
            "type": "text",
            "name": "travel_date",
            "label": "计划哪三天出行？",
            "hint": "例如 2026-05-20 至 2026-05-22",
        },
        0,
    )

    assert normalized["id"] == "travel_date"
    assert normalized["kind"] == "free_text"
    assert normalized["placeholder"] == "例如 2026-05-20 至 2026-05-22"
