# Agente de Discovery Empresarial — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir o "cérebro" do produto — um agente de discovery que entrevista o empresário via terminal, raciocina em profundidade por segmento (sem formulário) e gera um blueprint de time de agentes (`blueprint.json` + `blueprint.md`).

**Architecture:** Um único agente AgentScope v2 (`Agent`) com um `DiscoveryState` Pydantic explícito e persistido. Três tools — `segment_lookup` (trilhos CNAE), `reflect` (atualiza o estado a cada resposta) e `emit_blueprint` (valida + grava o blueprint). Loop conduzido por um `runner` no terminal; superfície CLI `qwenpaw discovery`.

**Tech Stack:** Python ≥3.11, AgentScope 2.0.0 (`agentscope.agent.Agent`, `agentscope.tool.Toolkit/FunctionTool`, `agentscope.message`), Pydantic v2, Click (CLI), pytest. Reusa `qwenpaw.agents.model_factory.create_model_and_formatter`.

**Gate:** `/agentscope-guardian` (KB `docs/agentscope-v2/`) antes de fechar. Spec: `docs/superpowers/specs/2026-06-11-discovery-agent-design.md`.

---

## Estrutura de arquivos

```
src/qwenpaw/discovery/
  __init__.py            # exports: DiscoverySession, run_discovery_cli
  state.py               # Pydantic: CompanyProfile, OpenArea, Integration, Turn,
                         #   DiscoveryState, ProcessArea, AgentSpec, RoadmapItem,
                         #   TeamBlueprint, ReflectUpdate
  segments/
    __init__.py
    taxonomy.py          # load_segments(), lookup_segment(query) -> SegmentInfo|None
    data/cnae_seed.json  # ~7 segmentos BR curados
  prompts.py             # build_discovery_system_prompt(blueprint_schema_json)
  tools.py               # DiscoverySession (state + métodos-tool) + build_toolkit()
  agent.py               # build_discovery_agent(session) -> agentscope Agent
  runner.py              # run_discovery_cli(workspace_dir) loop de terminal
src/qwenpaw/cli/discovery_cmd.py   # grupo click `discovery`
tests/discovery/
  __init__.py
  test_state.py
  test_taxonomy.py
  test_tools.py
  test_runner.py
```

Convenção do repo confirmada: tools são funções `async` que retornam `ToolChunk` (ver `src/qwenpaw/agents/tools/get_current_time.py`); o agente base é AgentScope v2 `Agent` (ver `src/qwenpaw/agents/react_agent.py:16-17,180-200`); modelo via `create_model_and_formatter()` (`src/qwenpaw/agents/model_factory.py:1019`).

---

## Task 1: Schemas Pydantic e DiscoveryState

**Files:**
- Create: `src/qwenpaw/discovery/__init__.py` (vazio por enquanto)
- Create: `src/qwenpaw/discovery/state.py`
- Test: `tests/discovery/__init__.py` (vazio), `tests/discovery/test_state.py`

- [ ] **Step 1: Escrever o teste que falha**

`tests/discovery/test_state.py`:
```python
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
    OpenArea(id="vendas", topic="processo de vendas", confidence=0.5, priority=3)
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
        company_profile={"segment": "e-commerce", "size": "micro",
                         "business_model": "venda online", "pains": ["atendimento lento"]},
        process_map=[{"name": "atendimento", "description": "SAC via WhatsApp"}],
        detected_integrations=[{"kind": "whatsapp", "name": "Evolution",
                                "data_location": "instância própria", "confidence": 0.8}],
        proposed_team=[{"name": "Atendente WhatsApp", "role": "SAC",
                        "objective": "responder clientes", "tasks": ["responder dúvidas"],
                        "tools_integrations": ["mcp:evolution-whatsapp"], "talks_to": []}],
        roadmap=[{"order": 1, "title": "Atendimento WhatsApp", "rationale": "dor principal"}],
        open_questions=["confirmar volume de mensagens/dia"],
    )
    data = bp.model_dump_json()
    again = TeamBlueprint.model_validate_json(data)
    assert again.proposed_team[0].name == "Atendente WhatsApp"


def test_reflect_update_parses():
    upd = ReflectUpdate.model_validate_json(
        '{"learned":"empresa é e-commerce de roupas",'
        '"close_area_ids":["segmento"],'
        '"new_areas":[{"id":"logistica","topic":"como entrega","confidence":0.1,"priority":4}],'
        '"integrations":[{"kind":"planilha","name":"Google Sheets",'
        '"data_location":"drive","confidence":0.6}],'
        '"company_updates":{"segment":"e-commerce"}}'
    )
    assert upd.new_areas[0].id == "logistica"
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `python -m pytest tests/discovery/test_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'qwenpaw.discovery'`

- [ ] **Step 3: Implementar `state.py`**

`src/qwenpaw/discovery/state.py`:
```python
# -*- coding: utf-8 -*-
"""Schemas Pydantic do discovery agent: estado da entrevista + blueprint do time."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


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
        """Pronto quando toda área prioritária (priority>=3) passa do limiar."""
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
```

Criar `src/qwenpaw/discovery/__init__.py` e `tests/discovery/__init__.py` vazios.

- [ ] **Step 4: Rodar e confirmar o sucesso**

Run: `python -m pytest tests/discovery/test_state.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/qwenpaw/discovery/__init__.py src/qwenpaw/discovery/state.py tests/discovery/__init__.py tests/discovery/test_state.py
git commit -m "feat(discovery): schemas Pydantic do estado e do blueprint"
```

---

## Task 2: Taxonomia de segmento (trilhos CNAE)

**Files:**
- Create: `src/qwenpaw/discovery/segments/__init__.py` (vazio)
- Create: `src/qwenpaw/discovery/segments/data/cnae_seed.json`
- Create: `src/qwenpaw/discovery/segments/taxonomy.py`
- Test: `tests/discovery/test_taxonomy.py`

- [ ] **Step 1: Escrever o teste que falha**

`tests/discovery/test_taxonomy.py`:
```python
# -*- coding: utf-8 -*-
from qwenpaw.discovery.segments.taxonomy import load_segments, lookup_segment


def test_seed_loads_and_has_ecommerce():
    segs = load_segments()
    assert any(s.key == "ecommerce" for s in segs)
    eco = next(s for s in segs if s.key == "ecommerce")
    assert eco.typical_areas
    assert eco.common_integrations


def test_lookup_matches_known_segment_by_keyword():
    info = lookup_segment("tenho uma loja virtual de roupas")
    assert info is not None
    assert info.key == "ecommerce"


def test_lookup_unknown_returns_none():
    assert lookup_segment("mineração de asteroides") is None
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `python -m pytest tests/discovery/test_taxonomy.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: Criar a seed e o módulo**

`src/qwenpaw/discovery/segments/data/cnae_seed.json` (começar com 7 segmentos; cada um com `keywords`, `typical_areas`, `typical_processes`, `common_pains`, `common_integrations`):
```json
[
  {
    "key": "ecommerce", "label": "E-commerce / Loja virtual", "cnae": "47.xx",
    "keywords": ["loja virtual", "e-commerce", "ecommerce", "venda online", "loja online", "marketplace"],
    "typical_areas": ["atendimento", "vendas", "logística/entrega", "pós-venda", "marketing"],
    "typical_processes": ["responder dúvidas", "rastrear pedido", "recuperar carrinho", "trocas/devoluções"],
    "common_pains": ["atendimento lento", "abandono de carrinho", "dúvidas repetitivas sobre entrega"],
    "common_integrations": ["whatsapp", "plataforma de e-commerce", "planilha/erp", "gateway de pagamento"]
  },
  {
    "key": "varejo", "label": "Varejo / Loja física", "cnae": "47.xx",
    "keywords": ["loja física", "varejo", "comércio", "loja de", "mercado"],
    "typical_areas": ["atendimento", "vendas", "estoque", "caixa"],
    "typical_processes": ["tirar dúvidas", "consultar estoque", "agendar retirada"],
    "common_pains": ["fila no atendimento", "perda de venda por falta de info"],
    "common_integrations": ["whatsapp", "pdv", "planilha"]
  },
  {
    "key": "servicos", "label": "Serviços / Prestador", "cnae": "card. 7-9",
    "keywords": ["presto serviço", "serviços", "consultoria", "agência", "assistência"],
    "typical_areas": ["atendimento", "agendamento", "orçamento", "pós-atendimento"],
    "typical_processes": ["qualificar lead", "enviar orçamento", "agendar"],
    "common_pains": ["lead frio", "demora no orçamento"],
    "common_integrations": ["whatsapp", "crm", "agenda/calendar"]
  },
  {
    "key": "alimentacao", "label": "Alimentação / Restaurante / Delivery", "cnae": "56.xx",
    "keywords": ["restaurante", "delivery", "lanchonete", "pizzaria", "comida", "food"],
    "typical_areas": ["atendimento", "pedidos", "entrega", "fidelização"],
    "typical_processes": ["receber pedido", "informar cardápio", "status da entrega"],
    "common_pains": ["pedido por whatsapp manual", "erro no pedido"],
    "common_integrations": ["whatsapp", "ifood/cardápio", "planilha"]
  },
  {
    "key": "saude", "label": "Saúde / Clínica / Consultório", "cnae": "86.xx",
    "keywords": ["clínica", "consultório", "dentista", "médico", "saúde", "estética avançada"],
    "typical_areas": ["agendamento", "atendimento", "confirmação de consulta", "pós-consulta"],
    "typical_processes": ["agendar consulta", "confirmar/lembrar", "reagendar"],
    "common_pains": ["faltas (no-show)", "agenda manual"],
    "common_integrations": ["whatsapp", "agenda", "prontuário/erp"]
  },
  {
    "key": "educacao", "label": "Educação / Cursos / Escola", "cnae": "85.xx",
    "keywords": ["curso", "escola", "ensino", "educação", "treinamento", "aulas"],
    "typical_areas": ["captação", "matrícula", "atendimento ao aluno", "secretaria"],
    "typical_processes": ["tirar dúvidas do curso", "matricular", "suporte ao aluno"],
    "common_pains": ["dúvidas repetitivas", "evasão"],
    "common_integrations": ["whatsapp", "crm", "plataforma/lms"]
  },
  {
    "key": "beleza", "label": "Beleza / Estética / Salão", "cnae": "96.02",
    "keywords": ["salão", "barbearia", "estética", "beleza", "manicure", "cabeleireiro"],
    "typical_areas": ["agendamento", "atendimento", "confirmação", "fidelização"],
    "typical_processes": ["agendar horário", "confirmar/lembrar", "remarcar"],
    "common_pains": ["faltas", "agenda no caderno", "horários ociosos"],
    "common_integrations": ["whatsapp", "agenda online"]
  }
]
```

`src/qwenpaw/discovery/segments/taxonomy.py`:
```python
# -*- coding: utf-8 -*-
"""Taxonomia híbrida de segmento: trilhos curados (CNAE) + fallback p/ LLM."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

_DATA = Path(__file__).parent / "data" / "cnae_seed.json"


class SegmentInfo(BaseModel):
    key: str
    label: str
    cnae: str = ""
    keywords: list[str] = []
    typical_areas: list[str] = []
    typical_processes: list[str] = []
    common_pains: list[str] = []
    common_integrations: list[str] = []


@lru_cache(maxsize=1)
def load_segments() -> tuple[SegmentInfo, ...]:
    raw = json.loads(_DATA.read_text(encoding="utf-8"))
    return tuple(SegmentInfo.model_validate(item) for item in raw)


def lookup_segment(query: str) -> SegmentInfo | None:
    """Casa o texto do empresário com um segmento da seed por palavra-chave.

    Retorna None quando nenhum trilho casa (cai no raciocínio livre do LLM).
    """
    q = (query or "").lower()
    best: SegmentInfo | None = None
    best_hits = 0
    for seg in load_segments():
        hits = sum(1 for kw in seg.keywords if kw.lower() in q)
        if hits > best_hits:
            best, best_hits = seg, hits
    return best if best_hits > 0 else None
```

- [ ] **Step 4: Rodar e confirmar o sucesso**

Run: `python -m pytest tests/discovery/test_taxonomy.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/qwenpaw/discovery/segments tests/discovery/test_taxonomy.py
git commit -m "feat(discovery): taxonomia híbrida de segmento com seed CNAE"
```

---

## Task 3: Session + tools (`segment_lookup`, `reflect`, `emit_blueprint`)

As tools são **métodos** de uma `DiscoverySession` (fecham sobre o estado mutável). Cada uma é `async` e retorna `ToolChunk`, seguindo `agents/tools/get_current_time.py`.

**Files:**
- Create: `src/qwenpaw/discovery/tools.py`
- Test: `tests/discovery/test_tools.py`

- [ ] **Step 1: Escrever o teste que falha**

`tests/discovery/test_tools.py`:
```python
# -*- coding: utf-8 -*-
import json
import pytest

from qwenpaw.discovery.state import DiscoveryState
from qwenpaw.discovery.tools import DiscoverySession


def _text(chunk):
    return "".join(b["text"] for b in chunk.content if b.get("type") == "text")


@pytest.mark.asyncio
async def test_segment_lookup_known(tmp_path):
    s = DiscoverySession(DiscoveryState(session_id="s1"), out_dir=tmp_path)
    chunk = await s.segment_lookup("tenho uma loja virtual")
    assert "ecommerce" in _text(chunk).lower()
    assert s.state.company.segment == "ecommerce"


@pytest.mark.asyncio
async def test_segment_lookup_unknown_records_open_question(tmp_path):
    s = DiscoverySession(DiscoveryState(session_id="s1"), out_dir=tmp_path)
    chunk = await s.segment_lookup("mineração de asteroides")
    assert "livre" in _text(chunk).lower() or "não" in _text(chunk).lower()
    assert any(a.id == "validar-segmento" for a in s.state.open_areas)


@pytest.mark.asyncio
async def test_reflect_mutates_state(tmp_path):
    s = DiscoverySession(DiscoveryState(session_id="s1"), out_dir=tmp_path)
    s.state.open_areas.append(
        __import__("qwenpaw.discovery.state", fromlist=["OpenArea"]).OpenArea(
            id="segmento", topic="qual segmento", confidence=0.1, priority=5)
    )
    updates = json.dumps({
        "learned": "e-commerce de roupas",
        "close_area_ids": ["segmento"],
        "new_areas": [{"id": "logistica", "topic": "entrega", "confidence": 0.1, "priority": 4}],
        "integrations": [{"kind": "planilha", "name": "Sheets", "data_location": "drive", "confidence": 0.6}],
        "company_updates": {"segment": "e-commerce"},
        "confidence_updates": {},
    })
    await s.reflect("e-commerce de roupas", updates)
    ids = [a.id for a in s.state.open_areas]
    assert "segmento" not in ids and "logistica" in ids
    assert s.state.company.segment == "e-commerce"
    assert s.state.integrations[0].name == "Sheets"


@pytest.mark.asyncio
async def test_emit_blueprint_writes_files(tmp_path):
    s = DiscoverySession(DiscoveryState(session_id="s1"), out_dir=tmp_path)
    bp = {
        "company_profile": {"segment": "e-commerce", "size": "micro",
                            "business_model": "venda online", "pains": ["atendimento lento"]},
        "process_map": [{"name": "atendimento", "description": "SAC"}],
        "detected_integrations": [],
        "proposed_team": [{"name": "Atendente", "role": "SAC", "objective": "responder",
                           "tasks": ["responder"], "tools_integrations": ["mcp:evolution-whatsapp"],
                           "talks_to": []}],
        "roadmap": [{"order": 1, "title": "WhatsApp", "rationale": "dor"}],
        "open_questions": [],
    }
    chunk = await s.emit_blueprint(json.dumps(bp))
    assert (tmp_path / "blueprint.json").exists()
    assert (tmp_path / "blueprint.md").exists()
    assert "Atendente" in (tmp_path / "blueprint.md").read_text(encoding="utf-8")
    assert s.emitted is True


@pytest.mark.asyncio
async def test_emit_blueprint_invalid_json_does_not_write(tmp_path):
    s = DiscoverySession(DiscoveryState(session_id="s1"), out_dir=tmp_path)
    chunk = await s.emit_blueprint('{"company_profile": ')  # JSON quebrado
    assert not (tmp_path / "blueprint.json").exists()
    assert "erro" in _text(chunk).lower() or "inválid" in _text(chunk).lower()
    assert s.emitted is False
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `python -m pytest tests/discovery/test_tools.py -v`
Expected: FAIL — ModuleNotFoundError em `qwenpaw.discovery.tools`

- [ ] **Step 3: Implementar `tools.py`**

`src/qwenpaw/discovery/tools.py`:
```python
# -*- coding: utf-8 -*-
"""DiscoverySession: estado mutável + as três tools do discovery agent."""
from __future__ import annotations

import json
from pathlib import Path

from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import FunctionTool, ToolChunk, Toolkit

from .segments.taxonomy import lookup_segment
from .state import (
    DiscoveryState,
    Integration,
    OpenArea,
    ReflectUpdate,
    TeamBlueprint,
)


def _ok(text: str) -> ToolChunk:
    return ToolChunk(
        is_last=True,
        state=ToolResultState.SUCCESS,
        content=[TextBlock(type="text", text=text)],
    )


def _blueprint_to_markdown(bp: TeamBlueprint) -> str:
    lines: list[str] = ["# Blueprint do Time de Agentes\n"]
    cp = bp.company_profile
    lines.append("## Perfil da empresa")
    lines.append(f"- Segmento: {cp.segment or '—'}")
    lines.append(f"- Porte: {cp.size or '—'}")
    lines.append(f"- Modelo de negócio: {cp.business_model or '—'}")
    if cp.pains:
        lines.append(f"- Dores: {', '.join(cp.pains)}")
    lines.append("\n## Mapa de processos")
    for p in bp.process_map:
        lines.append(f"- **{p.name}**: {p.description}")
    lines.append("\n## Integrações detectadas")
    for i in bp.detected_integrations:
        lines.append(f"- {i.kind} — {i.name} (dados em: {i.data_location or '—'})")
    lines.append("\n## Time de agentes proposto")
    for a in bp.proposed_team:
        lines.append(f"### {a.name} — {a.role}")
        lines.append(f"- Objetivo: {a.objective}")
        if a.tasks:
            lines.append(f"- Tarefas: {', '.join(a.tasks)}")
        if a.tools_integrations:
            lines.append(f"- Integrações: {', '.join(a.tools_integrations)}")
        if a.talks_to:
            lines.append(f"- Conversa com: {', '.join(a.talks_to)}")
    lines.append("\n## Roadmap")
    for r in sorted(bp.roadmap, key=lambda x: x.order):
        lines.append(f"{r.order}. **{r.title}** — {r.rationale}")
    if bp.open_questions:
        lines.append("\n## Perguntas em aberto")
        for q in bp.open_questions:
            lines.append(f"- {q}")
    return "\n".join(lines) + "\n"


class DiscoverySession:
    """Mantém o DiscoveryState e expõe as tools que o operam."""

    def __init__(self, state: DiscoveryState, out_dir: Path):
        self.state = state
        self.out_dir = Path(out_dir)
        self.emitted = False

    # --- tools -----------------------------------------------------------

    async def segment_lookup(self, description: str) -> ToolChunk:
        """Classifica o segmento da empresa a partir da descrição do empresário.

        Use assim que o empresário descrever o que a empresa faz. Retorna os
        'trilhos' do segmento (áreas, processos, dores e integrações típicas)
        quando a empresa cai num segmento conhecido; caso contrário sinaliza
        que você deve raciocinar livremente sobre o segmento.

        Args:
            description: O que a empresa faz, nas palavras do empresário.

        Returns:
            `ToolChunk`: trilhos do segmento, ou aviso de fallback livre.
        """
        info = lookup_segment(description)
        if info is None:
            if not any(a.id == "validar-segmento" for a in self.state.open_areas):
                self.state.open_areas.append(OpenArea(
                    id="validar-segmento",
                    topic="validar a taxonomia deste segmento (fora da seed)",
                    confidence=0.1, priority=4,
                ))
            return _ok(
                "Segmento não está na taxonomia curada. Raciocine de forma "
                "LIVRE sobre as áreas, processos, dores e integrações típicas "
                "deste tipo de negócio antes de continuar a entrevista."
            )
        self.state.company.segment = info.key
        if info.cnae:
            self.state.company.cnae = info.cnae
        payload = {
            "segment_key": info.key, "label": info.label,
            "typical_areas": info.typical_areas,
            "typical_processes": info.typical_processes,
            "common_pains": info.common_pains,
            "common_integrations": info.common_integrations,
        }
        return _ok(
            f"Segmento identificado: {info.key} ({info.label}). Use estes "
            f"trilhos como ponto de partida e APROFUNDE com perguntas:\n"
            + json.dumps(payload, ensure_ascii=False, indent=2)
        )

    async def reflect(self, learned: str, updates_json: str) -> ToolChunk:
        """Raciocínio profundo sobre a última resposta do empresário.

        Chame ESTE tool ANTES de fazer a próxima pergunta, sempre. Atualiza o
        estado interno da entrevista: o que aprendeu, quais áreas pode fechar,
        quais novas ramificações abrir, integrações detectadas e ajustes de
        confiança. É o que torna a entrevista um raciocínio, não um formulário.

        Args:
            learned: Resumo em 1-2 frases do que ficou entendido agora.
            updates_json: JSON conforme o schema ReflectUpdate, com os campos:
                learned, close_area_ids (list[str]), new_areas (list de
                {id, topic, confidence, priority}), integrations (list de
                {kind, name, data_location, confidence}), company_updates
                (dict parcial de CompanyProfile), confidence_updates
                (dict area_id->float).

        Returns:
            `ToolChunk`: resumo do estado atualizado e qual a próxima área foco.
        """
        try:
            upd = ReflectUpdate.model_validate_json(updates_json)
        except Exception as exc:  # validação explícita, sem engolir
            return _ok(
                f"updates_json inválido ({exc}). Reenvie um JSON válido "
                f"conforme o schema ReflectUpdate."
            )
        # fecha áreas
        if upd.close_area_ids:
            self.state.open_areas = [
                a for a in self.state.open_areas if a.id not in upd.close_area_ids
            ]
        # ajusta confiança
        for a in self.state.open_areas:
            if a.id in upd.confidence_updates:
                a.confidence = max(0.0, min(1.0, upd.confidence_updates[a.id]))
        # adiciona novas áreas (sem duplicar id)
        existing = {a.id for a in self.state.open_areas}
        for na in upd.new_areas:
            if na.id not in existing:
                self.state.open_areas.append(na)
                existing.add(na.id)
        # integrações (dedup por (kind,name))
        seen = {(i.kind, i.name) for i in self.state.integrations}
        for ig in upd.integrations:
            if (ig.kind, ig.name) not in seen:
                self.state.integrations.append(ig)
                seen.add((ig.kind, ig.name))
        # company
        if upd.company_updates:
            merged = self.state.company.model_dump()
            for k, v in upd.company_updates.items():
                if k in merged and v not in (None, "", []):
                    merged[k] = v
            self.state.company = type(self.state.company).model_validate(merged)
        self.state.transcript.append(__import__("qwenpaw.discovery.state",
            fromlist=["Turn"]).Turn(role="assistant", text=learned))

        focus = self.state.next_focus()
        focus_txt = f"{focus.id} — {focus.topic}" if focus else "nenhuma (pode emitir)"
        return _ok(
            f"Estado atualizado. Próxima área foco: {focus_txt}. "
            f"Pronto p/ emitir? {self.state.ready_to_emit()}"
        )

    async def emit_blueprint(self, blueprint_json: str) -> ToolChunk:
        """Valida e grava o blueprint final do time de agentes.

        Só chame quando as áreas prioritárias estiverem suficientemente
        compreendidas (ou o empresário sinalizar fim). Grava blueprint.json
        e blueprint.md no diretório da sessão.

        Args:
            blueprint_json: JSON conforme o schema TeamBlueprint.

        Returns:
            `ToolChunk`: confirmação com os caminhos, ou o erro de validação.
        """
        try:
            bp = TeamBlueprint.model_validate_json(blueprint_json)
        except Exception as exc:
            return _ok(
                f"Blueprint inválido ({exc}). Corrija o JSON conforme o "
                f"schema TeamBlueprint e chame emit_blueprint de novo."
            )
        self.out_dir.mkdir(parents=True, exist_ok=True)
        (self.out_dir / "blueprint.json").write_text(
            bp.model_dump_json(indent=2), encoding="utf-8")
        (self.out_dir / "blueprint.md").write_text(
            _blueprint_to_markdown(bp), encoding="utf-8")
        self.emitted = True
        return _ok(
            f"Blueprint gravado em {self.out_dir / 'blueprint.json'} e "
            f"{self.out_dir / 'blueprint.md'}. Entrevista concluída."
        )

    # --- toolkit ---------------------------------------------------------

    def build_toolkit(self) -> Toolkit:
        return Toolkit(tools=[
            FunctionTool(self.segment_lookup),
            FunctionTool(self.reflect),
            FunctionTool(self.emit_blueprint),
        ])
```

> Nota p/ o implementador: confirmar contra `docs/agentscope-v2/building-blocks/tool.md` que `FunctionTool` aceita um método bound (a assinatura sem `self` vira o schema). Se a versão exigir função top-level, trocar por funções que recebem `session` via `functools.partial` mantendo a mesma docstring/assinatura visível ao modelo. `TextBlock`/`ToolChunk`/`ToolResultState` já são usados em `agents/tools/get_current_time.py`.

- [ ] **Step 4: Rodar e confirmar o sucesso**

Run: `python -m pytest tests/discovery/test_tools.py -v`
Expected: PASS (5 passed). Requer `pytest-asyncio` (já em uso no repo — confirmar `pyproject.toml`; o modo `asyncio_mode` deve cobrir os testes `@pytest.mark.asyncio`).

- [ ] **Step 5: Commit**

```bash
git add src/qwenpaw/discovery/tools.py tests/discovery/test_tools.py
git commit -m "feat(discovery): DiscoverySession e tools segment_lookup/reflect/emit_blueprint"
```

---

## Task 4: Prompt de sistema (entrevista de raciocínio profundo)

**Files:**
- Create: `src/qwenpaw/discovery/prompts.py`

- [ ] **Step 1: Implementar `prompts.py`** (sem teste dedicado — é texto; será exercitado no Task 6)

`src/qwenpaw/discovery/prompts.py`:
```python
# -*- coding: utf-8 -*-
"""System prompt do discovery agent."""
from __future__ import annotations

from .state import TeamBlueprint

_SYSTEM = """\
Você é um consultor sênior que entrevista o dono de uma empresa brasileira para
desenhar um time de agentes de IA sob medida. Fale português do Brasil, tom
profissional e acolhedor.

REGRAS DE RACIOCÍNIO (NÃO é um formulário):
- A CADA resposta do empresário, primeiro chame a tool `reflect` para raciocinar
  em profundidade e atualizar seu entendimento (o que aprendeu, o que pode
  fechar, que novas ramificações abrir, integrações, confiança). Só então faça a
  PRÓXIMA pergunta.
- Faça UMA pergunta por vez, sempre mirando a área de MAIOR incerteza/prioridade.
- Assim que o empresário descrever o que a empresa faz, chame `segment_lookup`
  para puxar os trilhos do segmento e APROFUNDE a ramificação (áreas → processos
  → dores → integrações). Se o segmento não estiver na taxonomia, raciocine
  livremente.
- Descubra sempre: segmento e modelo de negócio; áreas/processos; dores reais
  (não só as ditas); quais sistemas usam (CRM, ERP, planilha, WhatsApp) e ONDE
  guardam os dados; e do caso mais simples (atendimento WhatsApp) ao mais
  complexo.

ENCERRAMENTO:
- Quando as áreas prioritárias estiverem bem compreendidas (ou o empresário
  sinalizar que quer fechar), chame `emit_blueprint` com um JSON que valide
  contra o schema TeamBlueprint abaixo. Inclua um roadmap começando pelo mais
  simples e liste perguntas em aberto para confirmação humana.

SCHEMA TeamBlueprint (JSON):
{schema}
"""


def build_discovery_system_prompt() -> str:
    schema = TeamBlueprint.model_json_schema()
    import json
    return _SYSTEM.format(schema=json.dumps(schema, ensure_ascii=False, indent=2))
```

- [ ] **Step 2: Verificação rápida**

Run: `python -c "from qwenpaw.discovery.prompts import build_discovery_system_prompt; print(build_discovery_system_prompt()[:200])"`
Expected: imprime o início do prompt sem erro.

- [ ] **Step 3: Commit**

```bash
git add src/qwenpaw/discovery/prompts.py
git commit -m "feat(discovery): system prompt de entrevista por raciocínio profundo"
```

---

## Task 5: Fábrica do agente (`agent.py`)

**Files:**
- Create: `src/qwenpaw/discovery/agent.py`

- [ ] **Step 1: Implementar `agent.py`**

Grounded em `src/qwenpaw/agents/react_agent.py:16-17,180-200` (construção do `Agent`, attach do formatter) e `model_factory.create_model_and_formatter`.

`src/qwenpaw/discovery/agent.py`:
```python
# -*- coding: utf-8 -*-
"""Fábrica do discovery agent (AgentScope v2 Agent)."""
from __future__ import annotations

from agentscope.agent import Agent, ReActConfig

from ..agents.model_factory import create_model_and_formatter
from .prompts import build_discovery_system_prompt
from .tools import DiscoverySession


def build_discovery_agent(session: DiscoverySession, max_iters: int = 6) -> Agent:
    """Monta o Agent de discovery com o toolkit da sessão e o modelo ativo."""
    model, formatter = create_model_and_formatter()
    # Mesmo attach de formatter feito pelo QwenPawAgent (react_agent.py).
    if formatter is not None:
        innermost = model
        while hasattr(innermost, "_inner"):
            innermost = innermost._inner
        while hasattr(innermost, "_model"):
            innermost = innermost._model
        if hasattr(innermost, "formatter"):
            innermost.formatter = formatter
    return Agent(
        name="DiscoveryAgent",
        system_prompt=build_discovery_system_prompt(),
        model=model,
        toolkit=session.build_toolkit(),
        react_config=ReActConfig(max_iters=max_iters),
    )
```

> Nota p/ o implementador: confirmar a assinatura de `Agent.__init__` em `docs/agentscope-v2/building-blocks/agent.md` (kwargs `name`, `system_prompt`, `model`, `toolkit`, `react_config`). Se o `Agent` base exigir mais kwargs, espelhar `react_agent.py:180-198`.

- [ ] **Step 2: Verificação de import (sem rodar modelo)**

Run: `python -c "import qwenpaw.discovery.agent as a; print(a.build_discovery_agent.__name__)"`
Expected: `build_discovery_agent` (import OK; não instancia o modelo).

- [ ] **Step 3: Commit**

```bash
git add src/qwenpaw/discovery/agent.py
git commit -m "feat(discovery): fábrica do discovery agent sobre AgentScope v2"
```

---

## Task 6: Runner (loop de terminal + persistência) e teste com LLM mockado

**Files:**
- Create: `src/qwenpaw/discovery/runner.py`
- Modify: `src/qwenpaw/discovery/__init__.py` (exports)
- Test: `tests/discovery/test_runner.py`

- [ ] **Step 1: Escrever o teste que falha (entrevista roteirizada, LLM mockado)**

`tests/discovery/test_runner.py`:
```python
# -*- coding: utf-8 -*-
import json
from pathlib import Path

import pytest

from qwenpaw.discovery.state import DiscoveryState
from qwenpaw.discovery.tools import DiscoverySession
from qwenpaw.discovery import runner as runner_mod


class FakeAgent:
    """Agent falso: em vez de chamar LLM, chama as tools da sessão na ordem
    de uma entrevista de e-commerce e emite o blueprint."""

    def __init__(self, session: DiscoverySession):
        self.session = session
        self._turn = 0

    async def reply(self, msg):
        self._turn += 1
        s = self.session
        if self._turn == 1:
            await s.segment_lookup("tenho uma loja virtual de roupas")
            await s.reflect("e-commerce de roupas", json.dumps({
                "learned": "e-commerce de roupas", "close_area_ids": [],
                "new_areas": [{"id": "atendimento", "topic": "como atende hoje",
                               "confidence": 0.1, "priority": 5}],
                "integrations": [], "company_updates": {"segment": "ecommerce"},
                "confidence_updates": {}}))
            return _MsgStub("Como você atende seus clientes hoje?")
        if self._turn == 2:
            await s.reflect("atende manual no WhatsApp", json.dumps({
                "learned": "atendimento manual no WhatsApp",
                "close_area_ids": ["atendimento"],
                "new_areas": [],
                "integrations": [{"kind": "whatsapp", "name": "WhatsApp",
                                  "data_location": "celular", "confidence": 0.9}],
                "company_updates": {}, "confidence_updates": {}}))
            bp = {
                "company_profile": {"segment": "ecommerce", "size": "micro",
                    "business_model": "venda online de roupas",
                    "pains": ["atendimento manual lento"]},
                "process_map": [{"name": "atendimento", "description": "SAC WhatsApp"}],
                "detected_integrations": [{"kind": "whatsapp", "name": "WhatsApp",
                    "data_location": "celular", "confidence": 0.9}],
                "proposed_team": [{"name": "Atendente WhatsApp", "role": "SAC",
                    "objective": "responder clientes 24/7",
                    "tasks": ["responder dúvidas", "rastrear pedido"],
                    "tools_integrations": ["mcp:evolution-whatsapp"], "talks_to": []}],
                "roadmap": [{"order": 1, "title": "Atendimento WhatsApp",
                    "rationale": "dor principal"}],
                "open_questions": ["volume de mensagens/dia?"],
            }
            await s.emit_blueprint(json.dumps(bp))
            return _MsgStub("Pronto! Gerei o blueprint do seu time.")
        return _MsgStub("...")


class _MsgStub:
    def __init__(self, text):
        self._t = text

    def get_text_content(self):
        return self._t


@pytest.mark.asyncio
async def test_runner_scripted_interview(tmp_path, monkeypatch):
    # respostas do empresário, terminando com /fim
    inputs = iter(["tenho uma loja virtual de roupas",
                   "atendo manual no zap", "/fim"])
    monkeypatch.setattr(runner_mod, "_read_user_input", lambda prompt: next(inputs))
    monkeypatch.setattr(runner_mod, "build_discovery_agent",
                        lambda session, **kw: FakeAgent(session))

    out = await runner_mod.run_discovery_session(
        session_id="t1", out_dir=tmp_path)

    assert (tmp_path / "blueprint.json").exists()
    bp = json.loads((tmp_path / "blueprint.json").read_text(encoding="utf-8"))
    assert bp["proposed_team"][0]["name"] == "Atendente WhatsApp"
    assert (tmp_path / "discovery_state.json").exists()
    assert out.emitted is True
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `python -m pytest tests/discovery/test_runner.py -v`
Expected: FAIL — `AttributeError`/`ImportError` em `runner.run_discovery_session`

- [ ] **Step 3: Implementar `runner.py`**

`src/qwenpaw/discovery/runner.py`:
```python
# -*- coding: utf-8 -*-
"""Loop de terminal do discovery agent + persistência da sessão."""
from __future__ import annotations

from pathlib import Path

from agentscope.message import UserMsg

from .agent import build_discovery_agent
from .state import DiscoveryState, OpenArea, Turn
from .tools import DiscoverySession

_GREETING = (
    "Olá! Vou te ajudar a montar um time de agentes para a sua empresa. "
    "Me conta: o que a sua empresa faz?"
)
_SEED_AREA = OpenArea(id="segmento", topic="qual o segmento/negócio da empresa",
                      confidence=0.0, priority=5)


def _read_user_input(prompt: str) -> str:  # isolado p/ teste (monkeypatch)
    return input(prompt)


def _persist(state: DiscoveryState, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "discovery_state.json").write_text(
        state.model_dump_json(indent=2), encoding="utf-8")


async def run_discovery_session(session_id: str, out_dir: Path) -> DiscoverySession:
    """Conduz a entrevista no terminal e retorna a sessão (com estado/flags)."""
    out_dir = Path(out_dir)
    state = DiscoveryState(session_id=session_id)
    state.open_areas.append(_SEED_AREA)
    session = DiscoverySession(state, out_dir=out_dir)
    agent = build_discovery_agent(session)

    print(_GREETING)
    while not session.emitted:
        user_text = _read_user_input("\nVocê: ").strip()
        if user_text.lower() in ("/fim", "/sair", "exit", "quit"):
            # pede ao agente que feche com o que já sabe
            user_text = ("Pode encerrar a entrevista e gerar o blueprint com o "
                         "que já temos, listando o que ficou em aberto.")
            state.transcript.append(Turn(role="user", text="/fim"))
            reply = await agent.reply(UserMsg(name="user", content=user_text))
            _persist(state, out_dir)
            print(f"\nConsultor: {reply.get_text_content()}")
            break
        state.transcript.append(Turn(role="user", text=user_text))
        reply = await agent.reply(UserMsg(name="user", content=user_text))
        _persist(state, out_dir)
        print(f"\nConsultor: {reply.get_text_content()}")

    if not session.emitted:
        print("\n(Entrevista encerrada sem blueprint — estado salvo para retomar.)")
    return session
```

Atualizar `src/qwenpaw/discovery/__init__.py`:
```python
# -*- coding: utf-8 -*-
"""Discovery agent — entrevista o empresário e gera o blueprint do time."""
from .runner import run_discovery_session
from .tools import DiscoverySession

__all__ = ["run_discovery_session", "DiscoverySession"]
```

> Nota: o teste faz `monkeypatch` de `runner_mod.build_discovery_agent` e `_read_user_input`, então nenhum LLM é chamado. Em produção o `build_discovery_agent` real instancia o modelo ativo.

- [ ] **Step 4: Rodar e confirmar o sucesso**

Run: `python -m pytest tests/discovery/test_runner.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Rodar a suíte do pacote**

Run: `python -m pytest tests/discovery -v`
Expected: todos passam.

- [ ] **Step 6: Commit**

```bash
git add src/qwenpaw/discovery/runner.py src/qwenpaw/discovery/__init__.py tests/discovery/test_runner.py
git commit -m "feat(discovery): runner de entrevista no terminal + persistência da sessão"
```

---

## Task 7: Comando CLI `qwenpaw discovery`

**Files:**
- Create: `src/qwenpaw/cli/discovery_cmd.py`
- Modify: `src/qwenpaw/cli/main.py` (registrar o grupo)

- [ ] **Step 1: Inspecionar como `main.py` registra grupos**

Run: `python - <<'PY'`
```python
import re, pathlib
t = pathlib.Path("src/qwenpaw/cli/main.py").read_text(encoding="utf-8")
for ln in t.splitlines():
    if "add_command" in ln or "_group" in ln or "import" in ln and "cmd" in ln:
        print(ln)
PY
```
Expected: lista as linhas `cli.add_command(<grupo>)` e os imports `from .<x>_cmd import <grupo>`. Seguir exatamente esse padrão.

- [ ] **Step 2: Implementar `discovery_cmd.py`**

`src/qwenpaw/cli/discovery_cmd.py`:
```python
# -*- coding: utf-8 -*-
"""CLI do discovery agent — ``qwenpaw discovery start``."""
from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import click


@click.group("discovery")
def discovery_group():
    """Entrevista o empresário e gera o blueprint de um time de agentes."""


@discovery_group.command("start")
@click.option("--out", "out_dir", default=None,
              help="Diretório de saída (default: ./discovery/<session_id>).")
def discovery_start(out_dir):
    """Inicia uma entrevista de discovery no terminal."""
    from ..discovery import run_discovery_session

    session_id = uuid4().hex[:8]
    target = Path(out_dir) if out_dir else Path("discovery") / session_id
    click.echo(f"Sessão de discovery: {session_id} → {target}")
    session = asyncio.run(run_discovery_session(session_id=session_id, out_dir=target))
    if session.emitted:
        click.echo(f"\n✅ Blueprint em {target / 'blueprint.md'}")
    else:
        click.echo("\n⚠️ Encerrado sem blueprint (estado salvo).")
```

- [ ] **Step 3: Registrar em `main.py`**

Seguindo o padrão observado no Step 1, adicionar o import e o registro (exemplo — ajustar ao nome real do objeto CLI em `main.py`):
```python
from .discovery_cmd import discovery_group
# ...
cli.add_command(discovery_group)
```

- [ ] **Step 4: Verificar o comando**

Run: `python -m qwenpaw discovery --help`
Expected: mostra o grupo `discovery` com o subcomando `start`.

- [ ] **Step 5: Commit**

```bash
git add src/qwenpaw/cli/discovery_cmd.py src/qwenpaw/cli/main.py
git commit -m "feat(discovery): comando CLI 'qwenpaw discovery start'"
```

---

## Task 8: Lint, suíte completa e gate do guardian

- [ ] **Step 1: Lint/format do que foi criado**

Run: `python -m flake8 src/qwenpaw/discovery tests/discovery` (config `.flake8`).
Corrigir o que aparecer. Se o repo usa `make lint`/pre-commit, rodar conforme `Makefile`.

- [ ] **Step 2: Suíte completa do pacote**

Run: `python -m pytest tests/discovery -v`
Expected: todos passam.

- [ ] **Step 3: Gate `/agentscope-guardian`**

Rodar o review do guardian (KB `docs/agentscope-v2/`, checklist `_guardian-checklist.md`) sobre o subpacote `src/qwenpaw/discovery/`. Endereçar todos os apontamentos antes de fechar (uso correto de `Agent`, `Toolkit`, `FunctionTool`, `ToolChunk`, `UserMsg`).

- [ ] **Step 4: Commit final / fechamento**

```bash
git add -A
git commit -m "chore(discovery): lint, suíte verde e gate do guardian aprovado"
```

---

## Self-review (cobertura do spec)

- §1 escopo cérebro-only / CLI → Tasks 6–7. ✅
- §2 organização do código → estrutura de arquivos + Tasks 1–7. ✅
- §3 motor A+B (DiscoveryState explícito, reflect, next_focus, critério de parada) → Tasks 1, 3, 6. ✅
- §4 taxonomia híbrida CNAE + fallback → Task 2, 3 (`segment_lookup`). ✅
- §5 blueprint JSON+MD + persistência por turno → Tasks 1, 3 (`emit_blueprint`), 6 (`_persist`). ✅
- §6 erros sem falha silenciosa (validação Pydantic re-pede; segmento fora da seed vira open_question; emitir cedo é desencorajado pelo prompt) → Tasks 3, 4, 6. ✅ Testes unit+integração mockada → Tasks 1–3, 6. Gate guardian → Task 8. ✅
- §7 critérios de aceite → cobertos pelos testes do runner (caso e-commerce ponta-a-ponta) e CLI. ✅

Consistência de tipos: `DiscoveryState`, `OpenArea`, `Integration`, `ReflectUpdate`, `TeamBlueprint`, `AgentSpec` usados com os mesmos nomes/campos em todas as tasks. `DiscoverySession(state, out_dir=...)` e métodos `segment_lookup/reflect/emit_blueprint/build_toolkit` consistentes entre Tasks 3, 5, 6. `run_discovery_session(session_id, out_dir)` consistente entre Tasks 6 e 7.
