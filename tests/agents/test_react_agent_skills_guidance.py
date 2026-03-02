# -*- coding: utf-8 -*-

from copaw.agents.react_agent import _build_active_skills_guidance


def test_build_active_skills_guidance_empty() -> None:
    assert _build_active_skills_guidance([]) == ""


def test_build_active_skills_guidance_lists_skills_sorted() -> None:
    out = _build_active_skills_guidance(["desktop-control", "browser-use"])
    assert "# Active Skills" in out
    assert "browser-use" in out
    assert "desktop-control" in out
    assert out.index("browser-use") < out.index("desktop-control")
