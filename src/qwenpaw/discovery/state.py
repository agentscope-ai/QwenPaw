# -*- coding: utf-8 -*-
"""Schemas Pydantic do discovery agent.

Estado da entrevista e blueprint do time.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# --- Estado da entrevista -------------------------------------------------

class CompanyProfile(BaseModel):
    segment: Optional[str] = None
    cnae: Optional[str] = None
    size: Optional[str] = None
    business_model: Optional[str] = None
    pains: list[str] = Field(default_factory=list)


class OpenArea(BaseModel):
    """Uma ramificação ainda por aprofundar na entrevista."""
    id: str
    topic: str
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    priority: int = Field(ge=1, le=5, default=3)
    notes: str = ""


class Integration(BaseModel):
    kind: str            # crm | erp | planilha | whatsapp | outro
    name: str
    data_location: str = ""
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)


class Turn(BaseModel):
    role: str            # "user" | "assistant"
    text: str


class DiscoveryState(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    session_id: str
    company: CompanyProfile = Field(default_factory=CompanyProfile)
    open_areas: list[OpenArea] = Field(default_factory=list)
    integrations: list[Integration] = Field(default_factory=list)
    transcript: list[Turn] = Field(default_factory=list)

    def next_focus(self) -> Optional[OpenArea]:
        """Área de maior prioridade e menor confiança (não-formulário)."""
        if not self.open_areas:
            return None
        return sorted(
            self.open_areas, key=lambda a: (a.confidence, -a.priority)
        )[0]

    def ready_to_emit(self, threshold: float = 0.7) -> bool:
        """Pronto quando toda área prioritária (priority>=3) supera limiar."""
        critical = [a for a in self.open_areas if a.priority >= 3]
        return all(a.confidence >= threshold for a in critical)


class ReflectUpdate(BaseModel):
    """Saída estruturada do passo de raciocínio `reflect`."""
    learned: str
    close_area_ids: list[str] = Field(default_factory=list)
    new_areas: list[OpenArea] = Field(default_factory=list)
    integrations: list[Integration] = Field(default_factory=list)
    company_updates: dict = Field(default_factory=dict)
    confidence_updates: dict[str, float] = Field(default_factory=dict)


# --- Blueprint do time ----------------------------------------------------

class ProcessArea(BaseModel):
    name: str
    description: str = ""


class AgentSpec(BaseModel):
    name: str
    role: str
    objective: str
    tasks: list[str] = Field(default_factory=list)
    tools_integrations: list[str] = Field(default_factory=list)
    talks_to: list[str] = Field(default_factory=list)


class RoadmapItem(BaseModel):
    order: int
    title: str
    rationale: str = ""


class TeamBlueprint(BaseModel):
    company_profile: CompanyProfile
    process_map: list[ProcessArea] = Field(default_factory=list)
    detected_integrations: list[Integration] = Field(default_factory=list)
    proposed_team: list[AgentSpec] = Field(default_factory=list)
    roadmap: list[RoadmapItem] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
