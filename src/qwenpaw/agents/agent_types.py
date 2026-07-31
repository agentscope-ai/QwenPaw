# -*- coding: utf-8 -*-
"""Extensible agent type registry.

Agent types identify lasting agent identity (e.g. default assistant vs
business analysis), distinct from runtime ``backend`` (qwenpaw/codex/…)
and create-time ``template_id`` recipes.

New types can be registered via :func:`register_agent_type` without
changing call sites that list or validate types.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


DEFAULT_AGENT_TYPE = "default"
BUSINESS_ANALYSIS_AGENT_TYPE = "business_analysis"


class AgentTypeDefinition(BaseModel):
    """Metadata for a selectable agent type."""

    id: str = Field(..., description="Stable agent type identifier")
    name: str = Field(..., description="Human-readable display name")
    description: str = Field(
        default="",
        description="Short description shown in create UI",
    )


_AGENT_TYPES: dict[str, AgentTypeDefinition] = {
    DEFAULT_AGENT_TYPE: AgentTypeDefinition(
        id=DEFAULT_AGENT_TYPE,
        name="Default",
        description="General-purpose personal assistant agent.",
    ),
    BUSINESS_ANALYSIS_AGENT_TYPE: AgentTypeDefinition(
        id=BUSINESS_ANALYSIS_AGENT_TYPE,
        name="Business Analysis",
        description=(
            "Analyzes unstructured business documents and consolidates "
            "insights into the knowledge base."
        ),
    ),
}


def list_agent_types() -> list[AgentTypeDefinition]:
    """Return registered agent types in stable registration order."""
    return list(_AGENT_TYPES.values())


def get_agent_type(type_id: str) -> AgentTypeDefinition | None:
    """Look up an agent type by id, or ``None`` if unknown."""
    return _AGENT_TYPES.get(type_id)


def is_valid_agent_type(type_id: str) -> bool:
    """Return whether ``type_id`` is a registered agent type."""
    return type_id in _AGENT_TYPES


def register_agent_type(definition: AgentTypeDefinition) -> None:
    """Register or replace an agent type definition.

    Intended for plugins and future built-in types.
    """
    if not definition.id:
        raise ValueError("agent type id must be non-empty")
    _AGENT_TYPES[definition.id] = definition


def list_supported_agent_type_ids() -> tuple[str, ...]:
    """Return registered agent type ids."""
    return tuple(_AGENT_TYPES.keys())
