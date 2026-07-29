# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Hash-verified Project Workspace prompt templates."""

from __future__ import annotations

import hashlib
from pathlib import Path


_PROMPT_PATH = Path(__file__).resolve().parent / "workspace_schema.system.txt"
_PROMPT_SHA256 = (
    "5cbe92ec5f2ebf5b27c5091843512e1fb3b23b041c61467b4298b379d87a153a"
)
_SCHEMA_PLACEHOLDER = "{{project_json_schema}}"


def render_workspace_schema_prompt(*, project_json_schema: str) -> str:
    data = _PROMPT_PATH.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != _PROMPT_SHA256:
        raise RuntimeError("Prompt hash mismatch: workspace_schema.system")
    text = data.decode("utf-8").strip()
    if text.count(_SCHEMA_PLACEHOLDER) != 1:
        raise RuntimeError(
            "Prompt placeholder mismatch: workspace_schema.system requires project_json_schema",
        )
    return text.replace(_SCHEMA_PLACEHOLDER, project_json_schema)


__all__ = ["render_workspace_schema_prompt"]
