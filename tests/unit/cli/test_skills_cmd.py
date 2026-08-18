# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

from qwenpaw.cli import skills_cmd
from qwenpaw.cli.skills_cmd import (
    _filter_skill_options,
    _merge_filtered_skill_selection,
)


def test_filter_skill_options_matches_names_case_insensitively() -> None:
    options = [
        ("GitHub  [pool] (hub)", "GitHub"),
        ("Google Calendar  [pool] (hub)", "google-calendar"),
        ("Local Notes  [✓] (local)", "local-notes"),
    ]

    assert _filter_skill_options(options, "  GOOGLE  ") == [options[1]]


def test_filter_skill_options_blank_query_returns_all_options() -> None:
    options = [("GitHub", "github"), ("Slack", "slack")]

    assert _filter_skill_options(options, "  ") == options


def test_merge_filtered_selection_preserves_hidden_enabled_skills() -> None:
    selected = ["visible-new"]
    visible_names = {"visible-old", "visible-new"}
    enabled = {"visible-old", "hidden-enabled"}

    assert _merge_filtered_skill_selection(
        selected,
        visible_names,
        enabled,
    ) == {"visible-new", "hidden-enabled"}


def test_merge_filtered_selection_does_not_select_hidden_pool_skills() -> None:
    selected = ["visible-skill"]

    assert _merge_filtered_skill_selection(
        selected,
        {"visible-skill"},
        set(),
    ) == {"visible-skill"}


def test_configure_skills_filters_options_and_preserves_hidden_enabled(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    skills = [
        SimpleNamespace(name="hidden-enabled", source="local"),
        SimpleNamespace(name="visible-disabled", source="local"),
    ]
    search_queries = iter(["missing", "VISIBLE"])
    captured_options: list[tuple[str, str]] = []

    monkeypatch.setattr(
        skills_cmd,
        "SkillService",
        lambda working_dir: SimpleNamespace(list_all_skills=lambda: skills),
    )
    monkeypatch.setattr(
        skills_cmd,
        "reconcile_workspace_manifest",
        lambda working_dir: None,
    )
    monkeypatch.setattr(
        skills_cmd,
        "read_skill_manifest",
        lambda working_dir: {"skills": {"hidden-enabled": {"enabled": True}}},
    )
    monkeypatch.setattr(
        skills_cmd,
        "prompt_text",
        lambda question: next(search_queries),
    )

    def fake_prompt_checkbox(_question, options, **_kwargs):
        captured_options.extend(options)
        return []

    monkeypatch.setattr(skills_cmd, "prompt_checkbox", fake_prompt_checkbox)

    skills_cmd.configure_skills_interactive(working_dir=tmp_path)

    assert [value for _, value in captured_options] == ["visible-disabled"]
    assert 'No skills match "missing". Try again.' in capsys.readouterr().out
