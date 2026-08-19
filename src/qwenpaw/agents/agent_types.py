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
TEST_DESIGN_AGENT_TYPE = "test_design"

# Map agent types to knowledge-dream domains. ``business`` extracts durable
# business knowledge; ``testcase`` extracts test scenarios/cases/data/defect
# patterns with structured preconditions/steps/expected fields and
# traceability links to business nodes. Default agents do not run
# knowledge dream at all (``knowledge_base`` capability is False).
_AGENT_TYPE_DOMAINS: dict[str, str] = {
    BUSINESS_ANALYSIS_AGENT_TYPE: "business",
    TEST_DESIGN_AGENT_TYPE: "testcase",
}


class AgentTypeCapabilities(BaseModel):
    """Capability flags gated by agent type."""

    knowledge_base: bool = Field(
        default=False,
        description=(
            "Whether this agent type mounts a shared knowledge base and "
            "runs knowledge dream / scoped memory search."
        ),
    )


class AgentTypeDefinition(BaseModel):
    """Metadata for a selectable agent type."""

    id: str = Field(..., description="Stable agent type identifier")
    name: str = Field(..., description="Human-readable display name")
    description: str = Field(
        default="",
        description="Short description shown in create UI",
    )
    capabilities: AgentTypeCapabilities = Field(
        default_factory=AgentTypeCapabilities,
        description="Type-level feature gates (e.g. knowledge_base).",
    )


_AGENT_TYPES: dict[str, AgentTypeDefinition] = {
    DEFAULT_AGENT_TYPE: AgentTypeDefinition(
        id=DEFAULT_AGENT_TYPE,
        name="Default",
        description="General-purpose personal assistant agent.",
        capabilities=AgentTypeCapabilities(knowledge_base=False),
    ),
    BUSINESS_ANALYSIS_AGENT_TYPE: AgentTypeDefinition(
        id=BUSINESS_ANALYSIS_AGENT_TYPE,
        name="Business Analysis",
        description=(
            "Analyzes unstructured business documents and consolidates "
            "insights into the knowledge base."
        ),
        capabilities=AgentTypeCapabilities(knowledge_base=True),
    ),
    TEST_DESIGN_AGENT_TYPE: AgentTypeDefinition(
        id=TEST_DESIGN_AGENT_TYPE,
        name="Test Design",
        description=(
            "Designs test scenarios and cases from business knowledge, "
            "consolidating reusable test artifacts into the shared "
            "knowledge base."
        ),
        capabilities=AgentTypeCapabilities(knowledge_base=True),
    ),
}


def agent_type_has_knowledge_base(type_id: str) -> bool:
    """Return whether ``type_id`` enables the knowledge-base capability."""
    definition = get_agent_type(type_id)
    if definition is None:
        return False
    return bool(definition.capabilities.knowledge_base)


def agent_type_to_domain(type_id: str) -> str:
    """Return the knowledge-dream domain for an agent type.

    Returns ``"business"`` for business-analysis agents, ``"testcase"``
    for test-design agents. Unknown / non-KB agent types default to
    ``"business"`` (callers gate on ``agent_type_has_knowledge_base``
    first, so the default only matters for logging fallbacks).
    """
    return _AGENT_TYPE_DOMAINS.get(type_id, "business")


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
