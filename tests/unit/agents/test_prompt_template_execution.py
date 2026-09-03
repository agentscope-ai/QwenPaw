# -*- coding: utf-8 -*-
"""Tests for completion semantics in default workspace templates."""
from __future__ import annotations

from pathlib import Path

import qwenpaw.agents


_TEMPLATE_ROOT = Path(qwenpaw.agents.__file__).parent / "md_files"


def _read_template(relative_path: str) -> str:
    """Read one packaged prompt template."""
    return (_TEMPLATE_ROOT / relative_path).read_text(encoding="utf-8")


def test_default_agents_templates_narrow_user_confirmation():
    """Ordinary reversible uncertainty should trigger investigation."""
    zh_text = _read_template("zh/AGENTS.md")
    en_text = _read_template("en/AGENTS.md")

    assert "任何你不确定的事" not in zh_text
    assert "Anything you're uncertain about" not in en_text
    assert "普通可逆的内部工作先调查和验证" in zh_text
    assert "ordinary reversible internal work" in en_text


def test_local_soul_templates_continue_after_plan():
    """Classification and planning remain intermediate actions."""
    zh_text = _read_template("local/zh/SOUL.md")
    en_text = _read_template("local/en/SOUL.md")

    assert "不要只回复分类结果就停止" in zh_text
    assert "do not stop merely to report the classification" in en_text
    assert "求助和计划都不是完成" in zh_text
    assert "Escalation and planning are not completion" in en_text
    assert "直到完成或真实阻塞" in zh_text
    assert "complete or genuinely blocked" in en_text
