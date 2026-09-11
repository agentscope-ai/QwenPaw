# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Placeholder-verified Project Workspace prompt templates."""

from __future__ import annotations

from pathlib import Path


_PROMPT_PATH = Path(__file__).resolve().parent / "workspace_schema.system.txt"
_SCHEMA_PLACEHOLDER = "{{project_json_schema}}"


def render_workspace_schema_prompt(*, project_json_schema: str) -> str:
    text = _PROMPT_PATH.read_text(encoding="utf-8").strip()
    if text.count(_SCHEMA_PLACEHOLDER) != 1:
        raise RuntimeError(
            "Prompt placeholder mismatch: workspace_schema.system requires project_json_schema",
        )
    return text.replace(_SCHEMA_PLACEHOLDER, project_json_schema)


__all__ = ["render_workspace_schema_prompt"]
