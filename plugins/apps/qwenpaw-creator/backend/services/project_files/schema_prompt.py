# -*- coding: utf-8 -*-
"""Deterministic Project schema prompt generated once per runtime schema."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache

from .models import Project
from .prompts import render_workspace_schema_prompt


@dataclass(frozen=True, slots=True)
class ProjectSchemaPrompt:
    text: str
    sha256: str


@lru_cache(maxsize=1)
def build_project_schema_prompt() -> ProjectSchemaPrompt:
    schema = json.dumps(
        Project.model_json_schema(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    text = render_workspace_schema_prompt(
        project_json_schema=schema,
    )
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return ProjectSchemaPrompt(text=text, sha256=f"sha256:{digest}")
