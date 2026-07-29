# -*- coding: utf-8 -*-
"""Hash-verified prompts owned by the file-native Creator Runtime."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re

_PROMPT_ROOT = Path(__file__).resolve().parent
_PLACEHOLDER = re.compile(r"\{\{([a-zA-Z0-9_]+)\}\}")


@dataclass(frozen=True, slots=True)
class FileAgentPromptSpec:
    prompt_id: str
    filename: str
    sha256: str
    placeholders: frozenset[str]


def _spec(
    prompt_id: str,
    filename: str,
    sha256: str,
    *placeholders: str,
) -> FileAgentPromptSpec:
    return FileAgentPromptSpec(
        prompt_id=prompt_id,
        filename=filename,
        sha256=sha256,
        placeholders=frozenset(placeholders),
    )


FILE_AGENT_PROMPT_SPECS = {
    item.prompt_id: item
    for item in (
        _spec(
            "creator_agent.system",
            "creator_agent.system.txt",
            "e5d82de05e71935edd84dd133f75de71b1ef9930f3ec0f65e1143bb982db75c5",
            "project_id",
            "workspace_schema",
        ),
        _spec(
            "source_intelligence_agent.system",
            "source_intelligence_agent.system.txt",
            "822b70473bf65c2ae0c9168d7a16ffd7485dcdd7076746ec51b79b3f58fe84c1",
            "project_id",
            "workspace_schema",
        ),
        _spec(
            "visual_development_agent.system",
            "visual_development_agent.system.txt",
            "a5d2182a6ebe2cc4972e712b62c043e945279242ff026911a129c8fd2d65c0fa",
            "project_id",
            "workspace_schema",
        ),
        _spec(
            "r2v_generation_director.system",
            "r2v_generation_director.system.txt",
            "26a31dc0c4f8d6efc7c82a5f7ff64a6771e6d370406501ae1786b24e54c31057",
            "project_id",
            "workspace_schema",
            "video_model_guidance",
        ),
        _spec(
            "ai_editing_director.system",
            "ai_editing_director.system.txt",
            "4ed7950e9854c29765990df37a8109295094c5ed51752283a3f74ead6521ebae",
            "project_id",
            "workspace_schema",
            "content_type",
            "target_duration_seconds",
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
    if hashlib.sha256(data).hexdigest() != spec.sha256:
        raise RuntimeError(f"Prompt hash mismatch: {prompt_id}")
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
) -> str:
    if workspace_schema is None:
        from services.project_files.schema_prompt import (
            build_project_schema_prompt,
        )

        workspace_schema = build_project_schema_prompt().text
    return render_file_agent_prompt(
        "creator_agent.system",
        project_id=project_id,
        workspace_schema=workspace_schema,
    )


__all__ = [
    "FILE_AGENT_PROMPT_SPECS",
    "FileAgentPromptSpec",
    "load_file_agent_prompt",
    "render_creator_system_prompt",
    "render_file_agent_prompt",
]
