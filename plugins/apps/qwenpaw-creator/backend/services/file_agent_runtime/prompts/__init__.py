# -*- coding: utf-8 -*-
"""Placeholder-verified prompts owned by the file-native Creator Runtime."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

_PROMPT_ROOT = Path(__file__).resolve().parent
_PLACEHOLDER = re.compile(r"\{\{([a-zA-Z0-9_]+)\}\}")


@dataclass(frozen=True, slots=True)
class FileAgentPromptSpec:
    prompt_id: str
    filename: str
    placeholders: frozenset[str]


def _spec(
    prompt_id: str,
    filename: str,
    *placeholders: str,
) -> FileAgentPromptSpec:
    return FileAgentPromptSpec(
        prompt_id=prompt_id,
        filename=filename,
        placeholders=frozenset(placeholders),
    )


FILE_AGENT_PROMPT_SPECS = {
    item.prompt_id: item
    for item in (
        _spec(
            "creator_agent.system",
            "creator_agent.system.txt",
            "project_id",
            "workspace_schema",
            "tts_guidance",
            "external_skills",
        ),
        _spec(
            "source_intelligence_agent.system",
            "source_intelligence_agent.system.txt",
            "project_id",
            "workspace_schema",
            "memory_guidance",
        ),
        _spec(
            "visual_development_agent.system",
            "visual_development_agent.system.txt",
            "project_id",
            "workspace_schema",
            "tts_guidance",
        ),
        _spec(
            "r2v_generation_director.system",
            "r2v_generation_director.system.txt",
            "project_id",
            "workspace_schema",
            "video_model_guidance",
        ),
        _spec(
            "ai_editing_director.system",
            "ai_editing_director.system.txt",
            "project_id",
            "workspace_schema",
            "content_type",
            "target_duration_seconds",
            "tts_guidance",
        ),
    )
}


def load_file_agent_prompt(prompt_id: str) -> str:
    try:
        spec = FILE_AGENT_PROMPT_SPECS[prompt_id]
    except KeyError as exc:
        raise KeyError(
            f"File Agent prompt is not allowlisted: {prompt_id}",
        ) from exc
    data = (_PROMPT_ROOT / spec.filename).read_bytes()
    text = data.decode("utf-8").strip()
    actual = frozenset(_PLACEHOLDER.findall(text))
    if actual != spec.placeholders:
        raise RuntimeError(
            f"Prompt placeholders mismatch for {prompt_id}: "
            f"expected={sorted(spec.placeholders)} actual={sorted(actual)}",
        )
    return text


def render_file_agent_prompt(prompt_id: str, **values: str) -> str:
    spec = FILE_AGENT_PROMPT_SPECS[prompt_id]
    supplied = frozenset(values)
    if supplied != spec.placeholders:
        raise ValueError(
            f"Prompt values mismatch for {prompt_id}: "
            f"expected={sorted(spec.placeholders)} actual={sorted(supplied)}",
        )
    rendered = load_file_agent_prompt(prompt_id)
    for name, value in values.items():
        rendered = rendered.replace("{{" + name + "}}", value)
    if _PLACEHOLDER.search(rendered):
        raise RuntimeError(f"Unresolved prompt placeholder: {prompt_id}")
    return rendered


def render_creator_system_prompt(
    *,
    project_id: str,
    workspace_schema: str | None = None,
    external_skills: str | None = None,
) -> str:
    if workspace_schema is None:
        from services.project_files.schema_prompt import (
            build_project_schema_prompt,
        )

        workspace_schema = build_project_schema_prompt().text
    # Mirrors the specialist-side dynamic injection: the delegator learns that
    # narration exists exactly when the tools do, and learns that a character
    # voice is a prerequisite exactly when the configured model needs one.
    from services.file_agent_runtime.prompts.tts_guidance import (
        delegator_guidance,
    )

    if external_skills is None:
        # Isolated by design: the loader never raises, a broken skill only
        # yields an empty context block.
        from services.external_skills import render_external_skills_context

        external_skills = render_external_skills_context()
    return render_file_agent_prompt(
        "creator_agent.system",
        project_id=project_id,
        workspace_schema=workspace_schema,
        tts_guidance=delegator_guidance(),
        external_skills=external_skills,
    )


__all__ = [
    "FILE_AGENT_PROMPT_SPECS",
    "FileAgentPromptSpec",
    "load_file_agent_prompt",
    "render_creator_system_prompt",
    "render_file_agent_prompt",
]
