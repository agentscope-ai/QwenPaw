# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument
"""User template extraction, persistence, and round-trip tests."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from services.media_files.user_templates import (
    UserVideoTemplate,
    delete_user_template,
    extract_template_from_project,
    list_user_templates,
    load_user_template,
    save_user_template,
    template_to_apply_dict,
)


@pytest.fixture()
def data_root(tmp_path):
    with patch(
        "services.media_files.user_templates.require_creator_data_root",
        return_value=tmp_path,
    ):
        yield tmp_path


def _make_project_data(**overrides):
    base = {
        "scenario": "video_edit",
        "settings": {"content_type": "vlog"},
        "timelines": {
            "order": ["main"],
            "items": {
                "main": {
                    "color_grade": "warm",
                    "edit_plan": {
                        "concept": (
                            "字幕蓝图: title_card, lower_third"
                            " | 片头字幕: opening_v1"
                            " | 片尾字幕: closing_v1"
                        ),
                        "signature_device": ("默认转场: dissolve (0.6s)"),
                        "dials": {
                            "energy": "high",
                            "density": "mid",
                            "decoration": "low",
                        },
                        "design_floor": {
                            "opening": "Bold title",
                            "transitions": "Smooth dissolve",
                            "body": "Clean cuts",
                            "ending": "Fade out",
                        },
                    },
                },
            },
        },
    }
    for key, value in overrides.items():
        if key == "timeline_overrides":
            base["timelines"]["items"]["main"].update(value)
        else:
            base[key] = value
    return base


class TestExtractTemplate:
    def test_extracts_all_fields(self, data_root):
        project = _make_project_data()
        tpl = extract_template_from_project(
            project,
            name="My Style",
            description="A custom style",
            icon_emoji="\U0001f3ac",
        )
        assert tpl.name == "My Style"
        assert tpl.description == "A custom style"
        assert tpl.icon_emoji == "\U0001f3ac"
        assert tpl.template_id.startswith("user:")
        assert tpl.content_type == "vlog"
        assert tpl.scenario == "video_edit"
        assert tpl.color_grade == "warm"
        assert tpl.energy == "high"
        assert tpl.density == "mid"
        assert tpl.decoration == "low"
        assert tpl.opening_caption_blueprint == "opening_v1"
        assert tpl.closing_caption_blueprint == "closing_v1"
        assert tpl.caption_blueprint_order == [
            "title_card",
            "lower_third",
        ]
        assert tpl.default_transition_kind == "dissolve"
        assert tpl.transition_blend_seconds == 0.6
        assert tpl.design_floor_opening == "Bold title"
        assert tpl.design_floor_transitions == "Smooth dissolve"
        assert tpl.design_floor_body == "Clean cuts"
        assert tpl.design_floor_ending == "Fade out"

    def test_defaults_when_timeline_empty(self, data_root):
        project = {
            "scenario": "general",
            "settings": {},
            "timelines": {"order": [], "items": {}},
        }
        tpl = extract_template_from_project(project, name="Empty")
        assert tpl.energy == "mid"
        assert tpl.default_transition_kind == "fade"
        assert tpl.transition_blend_seconds == 0.4
        assert tpl.caption_blueprint_order == []

    def test_specific_timeline_id(self, data_root):
        project = _make_project_data()
        project["timelines"]["items"]["alt"] = {
            "color_grade": "cool",
            "edit_plan": {
                "concept": "",
                "signature_device": "",
                "dials": {"energy": "low"},
                "design_floor": {},
            },
        }
        project["timelines"]["order"].append("alt")
        tpl = extract_template_from_project(
            project,
            name="Alt",
            timeline_id="alt",
        )
        assert tpl.color_grade == "cool"
        assert tpl.energy == "low"


class TestPersistence:
    def test_save_and_load_roundtrip(self, data_root):
        tpl = UserVideoTemplate(
            template_id="user:abcd1234",
            name="Test",
            energy="high",
        )
        save_user_template(tpl)
        loaded = load_user_template("user:abcd1234")
        assert loaded is not None
        assert loaded.name == "Test"
        assert loaded.energy == "high"
        assert loaded.template_id == "user:abcd1234"

    def test_load_missing_returns_none(self, data_root):
        assert load_user_template("user:nonexistent") is None

    def test_list_returns_all(self, data_root):
        for i in range(3):
            save_user_template(
                UserVideoTemplate(
                    template_id=f"user:tpl{i:04d}",
                    name=f"Template {i}",
                ),
            )
        templates = list_user_templates()
        assert len(templates) == 3
        names = {t.name for t in templates}
        assert names == {"Template 0", "Template 1", "Template 2"}

    def test_delete_existing(self, data_root):
        save_user_template(
            UserVideoTemplate(
                template_id="user:del00001",
                name="To Delete",
            ),
        )
        assert delete_user_template("user:del00001") is True
        assert load_user_template("user:del00001") is None

    def test_delete_missing(self, data_root):
        assert delete_user_template("user:nope0001") is False


class TestTemplateToApplyDict:
    def test_roundtrip_concept_and_signature(self, data_root):
        project = _make_project_data()
        tpl = extract_template_from_project(project, name="RT")
        apply = template_to_apply_dict(tpl)
        assert "opening_v1" in apply["concept"]
        assert "closing_v1" in apply["concept"]
        assert "title_card" in apply["concept"]
        assert "dissolve" in apply["signature_device"]
        assert "0.6" in apply["signature_device"]
        assert apply["color_grade"] == "warm"
        assert apply["energy"] == "high"
