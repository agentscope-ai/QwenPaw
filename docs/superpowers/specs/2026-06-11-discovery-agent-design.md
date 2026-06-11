# Design — Agente de Discovery Empresarial (núcleo do criador conversacional de times de agentes)

- **Data:** 2026-06-11
- **Status:** Aprovado (brainstorming) — aguardando revisão do spec antes do plano de implementação
- **Stack:** qwenpaw (fork de AgentScope 2.0.0, Python ≥3.11) — Windows / PowerShell
- **Gate obrigatório:** `/agentscope-guardian` (KB em `docs/agentscope-v2/`)
- **Execução prevista:** `/dev-team` (coder → reviewer → tester)

---

## 1. Contexto e visão do produto

Estamos construindo uma plataforma para **empresas brasileiras criarem seus próprios times de agentes de forma rápida, fácil e conversacional**. O usuário final é o **dono/gestor da empresa** (PME), não um técnico.

O coração do produto é um **agente de discovery empresarial**: um agente que **conversa** com o empresário e, em vez de aplicar um formulário, **raciocina em profundidade** sobre cada resposta. Ele faz análise por **segmento de negócio** (ex.: empresa de vendas → quais áreas/processos existem, aprofundando a ramificação), descobre **integrações existentes** (CRM, ERP, planilhas, WhatsApp, onde a empresa guarda dados) e, ao final, **gera a especificação de um time de agentes sob medida** — do mais simples (atendimento por WhatsApp) ao mais complexo.

### Escopo deste ciclo (decomposição)

O produto completo (UI no console, deploy real do time, conectores ativos, multi-tenant) é grande e será quebrado em camadas, cada uma com seu próprio spec. **Este ciclo entrega apenas o "cérebro"**:

- ✅ **No escopo:** o discovery agent que entrevista, raciocina e **produz um blueprint do time** (artefato `blueprint.json` + `blueprint.md`), rodável e testável via **CLI/terminal**.
- ❌ **Fora do escopo (camadas futuras):** UI conversacional no console (React/Tauri); gerar/deployar o time de verdade; conexões reais com WhatsApp/CRM/ERP; persistência multi-tenant / banco de dados; cobrança.

O blueprint gerado é o **contrato** entre este ciclo e as próximas camadas.

### Decisões de design tomadas no brainstorming

1. **Conhecimento de segmento = híbrido.** Trilhos curados a partir da **CNAE (IBGE, domínio público)** para os segmentos BR mais comuns + raciocínio livre do LLM por cima (cobre nichos fora da taxonomia).
2. **Saída = blueprint estruturado** (JSON + resumo legível) com perfil da empresa, mapa de processos, integrações detectadas, time proposto, roadmap e lacunas em aberto.
3. **Superfície deste ciclo = CLI/terminal**, com blueprint salvo em arquivo.
4. **Arquitetura do raciocínio = híbrido A+B:** um único `QwenPawAgent` (leve, fica no fork) que mantém um **`DiscoveryState` estruturado e explícito** (comportamento plan-driven/auditável do padrão `deep_research`, sem o peso de orquestrar múltiplos agentes ainda).

### Recursos do ecossistema (resultado do resource-scout, 2026-06-11)

Reaproveitar como **padrão** (sem `pip install`, registrando upstream + licença):

- **Discovery/entrevista** → padrão de `agentscope-ai/agentscope-samples` → `conversational_agents/` + `deep_research/agent_deep_research` (Apache-2.0, AgentScope 2.x nativo, mesma org do fork). O padrão "planejar → sub-perguntas → aprofundar ramificação" é a base do raciocínio não-formulário.
- **Geração de time (camada futura)** → padrão `agentscope-samples/Meta_tools` (meta-agente que compõe capacidades).
- **Memória entre turnos** → `nano-memory` de `agentscope-ai/skills` (avaliar; para o 1º ciclo o `DiscoveryState` persistido pode bastar).

Plugar como **MCP** em camadas futuras (código externo, entrada em `.mcp.json`): Google Sheets (`xing5/mcp-google-sheets`), HubSpot (`baryhuang`/`shinzo-labs`), WhatsApp via **Evolution API** (`aiteks-ltda/mcp-evolution-whatsapp-api`), ERPNext/Odoo, Pipedrive. Todos passam por `security-reviewer` antes (rodam código / guardam credenciais).

**Construir do zero (diferencial BR):** taxonomia por segmento baseada em CNAE; conector RD Station (não há MCP maduro); o **orquestrador discovery → blueprint** (o coração).

> ⚠️ WhatsApp via Evolution API é o padrão de fato em PME BR porém **não-oficial** (risco de ban / "lethal trifecta"); para produção, considerar a WhatsApp Business Cloud API oficial. Decisão adiada para a camada de conectores.

---

## 2. Arquitetura e organização do código

Novo subpacote **`src/qwenpaw/discovery/`**, espelhando o padrão de `src/qwenpaw/agents/mission/` (handler + runner + state).

```
src/qwenpaw/discovery/
  __init__.py
  state.py            # DiscoveryState + schemas Pydantic (estado + blueprint)
  agent.py            # monta o QwenPawAgent c/ system prompt de entrevista + toolkit de discovery
  prompts.py          # prompt de "raciocínio profundo / entrevista por segmento"
  runner.py           # loop da sessão (conduz turnos, persiste estado, emite blueprint)
  segments/
    __init__.py
    taxonomy.py           # lookup da taxonomia híbrida
    data/cnae_seed.json   # subset curado de segmentos BR p/ o 1º ciclo
  tools/
    __init__.py
    segment_lookup.py     # tool: áreas/processos/integrações típicas do segmento
    reflect.py            # tool: passo de raciocínio que atualiza o DiscoveryState
    emit_blueprint.py     # tool: valida e emite o blueprint final
```

Superfície CLI: comando novo **`qwenpaw discovery`** em `src/qwenpaw/cli/` (espelhar um comando existente, ex.: `mission_cmd.py`). Abre a entrevista no terminal e, ao final, grava `blueprint.json` + `blueprint.md` no diretório da sessão.

### Unidades e responsabilidades

- **`state.py`** — define os contratos Pydantic. Não depende de agentscope. Testável isoladamente.
- **`segments/taxonomy.py`** — carrega/consulta a seed CNAE. Função pura sobre dados. Testável isoladamente.
- **`tools/*`** — funções `async` retornando `ToolChunk` (padrão de `agents/tools/get_current_time.py`), docstring = schema da tool.
- **`agent.py`** — fábrica que monta o `QwenPawAgent` com o `Toolkit(tools=[...])` de discovery e o system prompt. Reusa `create_model_and_formatter` de `model_factory`.
- **`runner.py`** — orquestra a sessão: turno do usuário → reflexão → próxima pergunta → critério de parada → emissão. Persiste o `DiscoveryState` a cada turno.

---

## 3. Motor de raciocínio (híbrido A+B)

Um único `QwenPawAgent` (sobre `ReActAgent`) com um **`DiscoveryState` explícito mantido fora do prompt**.

### DiscoveryState (Pydantic, em `state.py`)

- `company: CompanyProfile` — fatos confirmados (segmento, CNAE inferida, porte, modelo de negócio, dores).
- `open_areas: list[OpenArea]` — ramificações **ainda por aprofundar**; cada uma com `topic`, `confidence` (0–1), `priority`, `notes`.
- `integrations: list[Integration]` — sistemas detectados (tipo, nome, onde guardam dados, confiança).
- `transcript: list[Turn]` — histórico da conversa.
- `metadata` — id da sessão, timestamps, segmento classificado.

### Loop (em `runner.py`), a cada resposta do empresário

1. **`reflect`** (tool, **saída estruturada**) — o agente raciocina sobre a resposta e **atualiza o `DiscoveryState`**: o que aprendeu, quais `open_areas` fecham, quais novas ramificações abrir, confiança atual. É aqui que vive o "pensamento profundo antes de responder" — auditável e persistido, não texto solto.
2. **Próxima pergunta** — o agente mira a `open_area` de maior prioridade / menor confiança (não há roteiro fixo → não-formulário). Uma pergunta por vez.
3. **Critério de parada** — quando as áreas prioritárias atingem confiança suficiente (limiar configurável) **ou** o empresário sinaliza fim → o agente chama **`emit_blueprint`**. Emitir antes do limiar é desencorajado: o agente confirma com o empresário em vez de forçar.

`reflect` e `emit_blueprint` usam **saída estruturada (Pydantic)** para garantir que o estado e o blueprint nunca degradem para texto livre.

---

## 4. Taxonomia de segmento (trilhos CNAE + LLM)

`segments/taxonomy.py` carrega um **subset curado de CNAE** (`data/cnae_seed.json`). Para o 1º ciclo, ~6–8 segmentos BR comuns: varejo, e-commerce, serviços, alimentação, saúde, educação, beleza/estética (lista final definida na implementação). Cada segmento traz: áreas típicas, processos, dores frequentes e integrações comuns.

A tool **`segment_lookup`** entrega esses trilhos ao agente quando ele classifica o segmento; o LLM **aprofunda livre** por cima. Segmento fora da seed → não quebra: cai 100% no raciocínio do LLM e registra uma `open_area` "validar taxonomia deste segmento".

---

## 5. Saída (blueprint) e persistência

Schemas Pydantic em `state.py`:

```python
class AgentSpec(BaseModel):       # cada agente do time proposto
    name: str
    role: str
    objective: str
    tasks: list[str]
    tools_integrations: list[str]      # ex.: "mcp:evolution-whatsapp", "mcp:google-sheets"
    talks_to: list[str]                # orquestração (quem conversa com quem)

class TeamBlueprint(BaseModel):
    company_profile: CompanyProfile
    process_map: list[ProcessArea]
    detected_integrations: list[Integration]
    proposed_team: list[AgentSpec]
    roadmap: list[RoadmapItem]           # 1º entregar (ex.: atendimento WhatsApp) → depois
    open_questions: list[str]            # lacunas p/ confirmação humana
```

`emit_blueprint` valida contra `TeamBlueprint` e o `runner` grava no diretório da sessão:

- **`blueprint.json`** — contrato para as próximas camadas.
- **`blueprint.md`** — versão legível para o empresário revisar.

Persistência da sessão: o `DiscoveryState` é salvo a cada turno (`discovery_state.json`), seguindo o molde de `mission/state.py`. Isso já permite **retomar** uma entrevista interrompida sem ampliar o escopo. Integrações entram no blueprint como **referências** (`tools_integrations`), não conexões reais.

---

## 6. Erros, testes e gate

### Tratamento de erros (sem falha silenciosa)

- Saída estruturada inválida do LLM → o `runner` re-pede com a mensagem de validação Pydantic (não engole o erro).
- Segmento fora da seed CNAE → registra `open_question` e segue no raciocínio livre.
- `emit_blueprint` antes da confiança mínima → o agente confirma com o empresário, não força.

### Testes (pytest, seguindo `tests/`)

- **Unit:** `taxonomy.segment_lookup` (segmento conhecido vs. desconhecido); validação dos schemas Pydantic; transições do `DiscoveryState` no `reflect` (área fecha/abre conforme a resposta).
- **Integração (LLM mockado):** "entrevista roteirizada" ponta-a-ponta (respostas canned de um empresário fictício de e-commerce) → o `runner` produz um `TeamBlueprint` válido com ≥1 agente de atendimento + integrações esperadas.
- **Sem chamadas reais de LLM** nos testes (mock de `create_model_and_formatter` / model_factory), espelhando os testes existentes do agente.

### Gate

Mexe em `src/qwenpaw/` sobre AgentScope 2.x → passa por **`/agentscope-guardian`** (KB em `docs/agentscope-v2/`) antes de fechar. Implementação conduzida pelo **`/dev-team`**.

---

## 7. Critérios de aceite do ciclo

1. `qwenpaw discovery` abre uma entrevista no terminal que **raciocina** (atualiza `DiscoveryState` visível/persistido) e faz perguntas guiadas pela maior incerteza — não um roteiro fixo.
2. Cobre ao menos o caso simples (atendimento WhatsApp para um e-commerce) ponta-a-ponta.
3. Ao final, gera `blueprint.json` válido contra `TeamBlueprint` + `blueprint.md` legível.
4. Taxonomia híbrida funciona: segmento na seed usa os trilhos CNAE; fora da seed degrada para raciocínio livre + `open_question`.
5. Testes (unit + integração mockada) passam; `/agentscope-guardian` aprova.

---

## 8. Camadas futuras (fora deste ciclo, para contexto)

1. **Gerador/deploy do time** — consome `blueprint.json` e instancia/deploya o time (padrão `Meta_tools`; `docs/agentscope-v2/deploy-agent-team.md`).
2. **Conectores** — MCP de WhatsApp (Evolution → depois oficial), Google Sheets, HubSpot, RD Station (build), ERPNext/Odoo, Pipedrive. Cada um via `security-reviewer`.
3. **UI conversacional** no console (React/Tauri).
4. **Multi-tenant / persistência em banco / cobrança.**
