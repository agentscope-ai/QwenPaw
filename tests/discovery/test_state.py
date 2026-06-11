# -*- coding: utf-8 -*-
import pytest
from pydantic import ValidationError

from qwenpaw.discovery.state import (
    DiscoveryState,
    OpenArea,
    TeamBlueprint,
    ReflectUpdate,
)


def test_open_area_confidence_bounds():
    OpenArea(
        id="vendas", topic="processo de vendas", confidence=0.5, priority=3
    )
    with pytest.raises(ValidationError):
        OpenArea(id="x", topic="t", confidence=1.5, priority=1)


def test_discovery_state_defaults_and_helpers():
    st = DiscoveryState(session_id="s1")
    assert st.open_areas == []
    assert st.integrations == []
    # next_focus picks lowest-confidence, highest-priority open area
    st.open_areas = [
        OpenArea(id="a", topic="A", confidence=0.9, priority=1),
        OpenArea(id="b", topic="B", confidence=0.2, priority=2),
    ]
    assert st.next_focus().id == "b"
    # ready_to_emit() True only when all priority>=3 areas pass threshold
    assert st.ready_to_emit(threshold=0.7) is True  # nenhuma área prio>=3


def test_blueprint_roundtrip_json():
    bp = TeamBlueprint(
        company_profile={
            "segment": "e-commerce",
            "size": "micro",
            "business_model": "venda online",
            "pains": ["atendimento lento"],
        },
        process_map=[
            {"name": "atendimento", "description": "SAC via WhatsApp"}
        ],
        detected_integrations=[
            {
                "kind": "whatsapp",
                "name": "Evolution",
                "data_location": "instância própria",
                "confidence": 0.8,
            }
        ],
        proposed_team=[
            {
                "name": "Atendente WhatsApp",
                "role": "SAC",
                "objective": "responder clientes",
                "tasks": ["responder dúvidas"],
                "tools_integrations": ["mcp:evolution-whatsapp"],
                "talks_to": [],
            }
        ],
        roadmap=[
            {
                "order": 1,
                "title": "Atendimento WhatsApp",
                "rationale": "dor principal",
            }
        ],
        open_questions=["confirmar volume de mensagens/dia"],
    )
    data = bp.model_dump_json()
    again = TeamBlueprint.model_validate_json(data)
    assert again.proposed_team[0].name == "Atendente WhatsApp"


def test_reflect_update_parses():
    upd = ReflectUpdate.model_validate_json(
        '{"learned":"empresa é e-commerce de roupas",'
        '"close_area_ids":["segmento"],'
        '"new_areas":[{"id":"logistica","topic":"como entrega",'
        '"confidence":0.1,"priority":4}],'
        '"integrations":[{"kind":"planilha","name":"Google Sheets",'
        '"data_location":"drive","confidence":0.6}],'
        '"company_updates":{"segment":"e-commerce"}}'
    )
    assert upd.new_areas[0].id == "logistica"
