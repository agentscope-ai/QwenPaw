# pt-BR Workspace Translation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Traduzir o workspace completo do QwenPaw para pt-BR seguindo o padrão chinês existente, e adicionar um hook que avisa quando novos arquivos de skill/agente/plugin são criados sem contraparte pt-BR.

**Architecture:** Espelhar a estrutura `-zh`/`zh/`/`zh-CN` já existente criando variantes `-pt`/`pt/`/`pt-BR`. O registry de skills recebe `"pt"` como idioma suportado, os arquivos de agente ganham pasta `pt/`, os plugins ganham campo `pt-BR` em `description_i18n`, e o locale do frontend é completado. Um script Python verifica novos arquivos via hook Claude Code.

**Tech Stack:** Python (registry, hook), Markdown (SKILL.md, PROFILE.md, SOUL.md), JSON (locales, plugin.json), Claude Code hooks (settings.json)

---

## Arquivo de Referência

Antes de cada tarefa, leia a versão `-en` correspondente para traduzir fielmente. **Nunca inventar conteúdo** — a tradução preserva toda a semântica do original.

---

## Task 1: Atualizar registry de skills para suportar `pt`

**Files:**
- Modify: `src/qwenpaw/agents/skill_system/registry.py:50-53`

- [ ] **Step 1: Escrever o teste**

```python
# tests/skill_system/test_registry_pt.py
from qwenpaw.agents.skill_system.registry import (
    BUILTIN_SKILL_LANGUAGES,
    _BUILTIN_SKILL_DIR_RE,
)

def test_pt_in_builtin_languages():
    assert "pt" in BUILTIN_SKILL_LANGUAGES

def test_pt_dir_regex_matches():
    m = _BUILTIN_SKILL_DIR_RE.match("cron-pt")
    assert m is not None
    assert m.group("language") == "pt"
    assert m.group("name") == "cron"

def test_pt_dir_regex_does_not_match_ptbr():
    # o sufixo do diretório é "-pt", não "-pt-BR"
    m = _BUILTIN_SKILL_DIR_RE.match("cron-pt-BR")
    assert m is None
```

- [ ] **Step 2: Rodar o teste para confirmar falha**

```bash
pytest tests/skill_system/test_registry_pt.py -v
```
Esperado: FAIL — `"pt" not in BUILTIN_SKILL_LANGUAGES`

- [ ] **Step 3: Implementar a mudança no registry**

Em `src/qwenpaw/agents/skill_system/registry.py`, linhas 50-53:

```python
# antes
BUILTIN_SKILL_LANGUAGES = ("en", "zh")
_BUILTIN_SKILL_DIR_RE = re.compile(
    r"^(?P<name>.+)-(?P<language>en|zh)$",
)

# depois
BUILTIN_SKILL_LANGUAGES = ("en", "zh", "pt")
_BUILTIN_SKILL_DIR_RE = re.compile(
    r"^(?P<name>.+)-(?P<language>en|zh|pt)$",
)
```

- [ ] **Step 4: Rodar os testes**

```bash
pytest tests/skill_system/test_registry_pt.py -v
```
Esperado: PASS (3 testes)

- [ ] **Step 5: Commit**

```bash
git add src/qwenpaw/agents/skill_system/registry.py tests/skill_system/test_registry_pt.py
git commit -m "feat(i18n): adicionar suporte a idioma pt no registry de skills"
```

---

## Task 2: Completar `locales/pt-BR.json`

**Files:**
- Modify: `console/src/locales/pt-BR.json`

- [ ] **Step 1: Escrever o teste**

```python
# tests/frontend/test_ptbr_locale.py
import json
from pathlib import Path

LOCALES = Path("console/src/locales")

def _flat_keys(d, prefix=""):
    keys = set()
    for k, v in d.items():
        full = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            keys |= _flat_keys(v, full)
        else:
            keys.add(full)
    return keys

def test_ptbr_has_all_en_keys():
    en = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))
    pt = json.loads((LOCALES / "pt-BR.json").read_text(encoding="utf-8"))
    missing = _flat_keys(en) - _flat_keys(pt)
    assert not missing, f"Chaves faltando em pt-BR.json: {sorted(missing)}"
```

- [ ] **Step 2: Rodar o teste para confirmar falha**

```bash
pytest tests/frontend/test_ptbr_locale.py -v
```
Esperado: FAIL — 31 chaves faltando

- [ ] **Step 3: Adicionar as chaves faltantes em `pt-BR.json`**

Adicione as seguintes entradas ao objeto JSON (dentro das seções correspondentes):

```json
{
  "nav": {
    "inbox": "Caixa de Entrada",
    "market": "Mercado de Skills"
  },
  "inbox": {
    "filterByAgent": "Filtrar por agente"
  },
  "mcp": {
    "tab": {
      "json": "Importação JSON",
      "form": "Modo Formulário"
    },
    "form": {
      "key": "Chave do Cliente",
      "keyPlaceholder": "meu-servidor-mcp",
      "keyRequired": "A chave do cliente é obrigatória",
      "name": "Nome de Exibição",
      "namePlaceholder": "Meu Servidor MCP",
      "nameRequired": "O nome de exibição é obrigatório",
      "transport": "Transporte",
      "url": "URL do Servidor",
      "urlRequired": "URL é obrigatória para servidores MCP remotos",
      "command": "Comando",
      "commandRequired": "O comando é obrigatório para transporte stdio",
      "args": "Argumentos (separados por espaço ou nova linha)",
      "description": "Descrição",
      "descriptionPlaceholder": "Descrição opcional",
      "env": "Variáveis de Ambiente",
      "envPlaceholder": "CHAVE=VALOR (uma por linha)"
    }
  },
  "tokenUsage": {
    "modelTrend": "Tendência de Uso por Modelo",
    "tokenTypeChart": "Tendência por Tipo de Token",
    "selectAll": "Selecionar Todos",
    "allSelected": "Todos",
    "itemsSelected": "{{count}} selecionados",
    "selectModels": "Selecionar modelos",
    "selectTokenTypes": "Selecionar tipos de token"
  },
  "agentConfig": {
    "autoGenerateSessionTitle": "Gerar títulos de sessão automaticamente",
    "autoGenerateSessionTitleTooltip": "Após a primeira mensagem do usuário em um novo chat, executa uma chamada LLM rápida em segundo plano para substituir o marcador temporário por um título conciso. Gera uma chamada LLM extra por novo chat. Desative para manter o marcador e economizar tokens.",
    "adbpgMemoryTitle": "Memória de Longo Prazo ADBPG",
    "adbpgConfig": {
      "title": "Configuração de Memória ADBPG",
      "apiMode": "Modo de API",
      "host": "Host",
      "port": "Porta",
      "user": "Usuário",
      "password": "Senha",
      "dbname": "Banco de Dados",
      "llmModel": "Modelo LLM",
      "llmApiKey": "Chave de API LLM",
      "llmBaseUrl": "URL Base LLM",
      "embeddingModel": "Modelo de Embedding",
      "embeddingApiKey": "Chave de API de Embedding",
      "embeddingBaseUrl": "URL Base de Embedding",
      "embeddingDims": "Dimensões de Embedding",
      "restBaseUrl": "URL Base REST",
      "restApiKey": "Chave de API REST",
      "memoryIsolation": "Isolamento de Memória (por agente)",
      "searchTimeout": "Timeout de Busca"
    }
  },
  "tools": {
    "configure": "Configurar",
    "configured": "Configurado",
    "requiresConfig": "Requer configuração",
    "configSaved": "Configuração salva"
  },
  "tool": "Ferramenta"
}
```

> **Atenção:** Mescle dentro das seções existentes no arquivo. Não crie seções duplicadas.

- [ ] **Step 4: Rodar o teste**

```bash
pytest tests/frontend/test_ptbr_locale.py -v
```
Esperado: PASS

- [ ] **Step 5: Commit**

```bash
git add console/src/locales/pt-BR.json tests/frontend/test_ptbr_locale.py
git commit -m "feat(i18n): completar locale pt-BR com 31 chaves faltantes"
```

---

## Task 3: Adicionar `pt-BR` nos `plugin.json`

**Files:**
- Modify: `plugins/bundle/cloudpaw/plugin.json`
- Modify: `plugins/bundle/qwenpaw-pet/plugin.json`

- [ ] **Step 1: Escrever o teste**

```python
# tests/plugins/test_plugin_ptbr.py
import json
from pathlib import Path

PLUGINS = Path("plugins/bundle")

def test_cloudpaw_has_ptbr_description():
    p = json.loads((PLUGINS / "cloudpaw/plugin.json").read_text(encoding="utf-8"))
    assert "pt-BR" in p["description_i18n"], "cloudpaw/plugin.json sem pt-BR"

def test_qwenpaw_pet_has_ptbr_description():
    p = json.loads((PLUGINS / "qwenpaw-pet/plugin.json").read_text(encoding="utf-8"))
    assert "pt-BR" in p["description_i18n"], "qwenpaw-pet/plugin.json sem pt-BR"
```

- [ ] **Step 2: Rodar o teste para confirmar falha**

```bash
pytest tests/plugins/test_plugin_ptbr.py -v
```
Esperado: FAIL

- [ ] **Step 3: Editar `plugins/bundle/cloudpaw/plugin.json`**

Adicionar dentro de `description_i18n`:

```json
"pt-BR": "CloudPaw — Plugin de capacidades de nuvem para QwenPaw. Descreva seus requisitos em linguagem natural e automatize todo o fluxo, desde a criação de recursos até a implantação de aplicações. Após instalar: 1) Configure as credenciais da Alibaba Cloud (ALIBABA_CLOUD_ACCESS_KEY_ID / ALIBABA_CLOUD_ACCESS_KEY_SECRET) em Variáveis de Ambiente; 2) Atualize a página para carregar o plugin."
```

- [ ] **Step 4: Editar `plugins/bundle/qwenpaw-pet/plugin.json`**

Adicionar dentro de `description_i18n`:

```json
"pt-BR": "Emite eventos do ciclo de vida do backend do QwenPaw para o QwenPaw Pet Desktop."
```

- [ ] **Step 5: Rodar o teste**

```bash
pytest tests/plugins/test_plugin_ptbr.py -v
```
Esperado: PASS

- [ ] **Step 6: Commit**

```bash
git add plugins/bundle/cloudpaw/plugin.json plugins/bundle/qwenpaw-pet/plugin.json tests/plugins/test_plugin_ptbr.py
git commit -m "feat(i18n): adicionar descrição pt-BR nos plugin.json"
```

---

## Task 4: Criar perfis de agentes em pt-BR

**Files:**
- Create: `plugins/bundle/cloudpaw/agents/executor/pt/PROFILE.md`
- Create: `plugins/bundle/cloudpaw/agents/executor/pt/SOUL.md`
- Create: `plugins/bundle/cloudpaw/agents/orchestration/pt/PROFILE.md`
- Create: `plugins/bundle/cloudpaw/agents/orchestration/pt/SOUL.md`
- Create: `plugins/bundle/cloudpaw/agents/verifier/pt/PROFILE.md`
- Create: `plugins/bundle/cloudpaw/agents/verifier/pt/SOUL.md`

- [ ] **Step 1: Escrever o teste**

```python
# tests/plugins/test_agent_pt_profiles.py
from pathlib import Path

AGENTS_DIR = Path("plugins/bundle/cloudpaw/agents")
AGENTS = ["executor", "orchestration", "verifier"]

def test_pt_profile_exists():
    for agent in AGENTS:
        p = AGENTS_DIR / agent / "pt" / "PROFILE.md"
        assert p.exists(), f"Faltando: {p}"

def test_pt_soul_exists():
    for agent in AGENTS:
        s = AGENTS_DIR / agent / "pt" / "SOUL.md"
        assert s.exists(), f"Faltando: {s}"

def test_pt_profiles_not_empty():
    for agent in AGENTS:
        content = (AGENTS_DIR / agent / "pt" / "PROFILE.md").read_text(encoding="utf-8")
        assert len(content) > 100, f"{agent}/pt/PROFILE.md parece vazio"
```

- [ ] **Step 2: Rodar o teste para confirmar falha**

```bash
pytest tests/plugins/test_agent_pt_profiles.py -v
```
Esperado: FAIL

- [ ] **Step 3: Criar `executor/pt/PROFILE.md`**

```markdown
---
summary: "Identidade do Agente Executor"
---

## Identidade

**CloudPaw-Executor**: ID estável do Agente é `cloud-executor`. Executa as tarefas concretas delegadas pelo orquestrador (código, implantação, configuração, CLI, scripts, arquivos, etc.), escolhendo o caminho de execução mais adequado conforme a delegação e retornando resultados estruturados.

## Perfil do Usuário

(Preenchido progressivamente durante a conversa; nunca incluir credenciais.)

## Instruções de Execução

**[Leitura Obrigatória]** Antes de qualquer tarefa de execução, leia a skill **alicloud_cli** na íntegra.

**[Função]** Você é o Agente executor de uso geral. Escolha flexivelmente o caminho de execução com base na delegação do orquestrador, realize o trabalho concreto e retorne resultados estruturados.

**[Exemplos de Capacidade (ilustrativos, não exaustivos)]**
- Escrita de código de aplicação e scripts
- Implantação de aplicações e configuração de ambiente em hosts de nuvem existentes
- Execução de scripts locais ou remotos
- Operações de CLI de nuvem e consultas de recursos
- Criação e modificação de arquivos
- Qualquer outra tarefa de execução delegada pelo orquestrador

As tarefas reais seguem a delegação do orquestrador; escolha as skills e ferramentas mais adequadas.

**[Pontos Essenciais de Execução]**
- Confirme que as entradas-chave necessárias para a tarefa estão disponíveis (ambiente de destino, credenciais ou método de login, caminhos de entrada/saída, etc.)
- Escolha o caminho de operação mais adequado para a tarefa específica (ex.: gravações locais, execução remota, chamadas de CLI)
- Retorne resultados estruturados incluindo status, saídas principais (caminhos / IDs / URLs de acesso, etc.) e trechos de log relevantes

**[Tratamento de Falhas]** Em caso de falha, colete informações de erro e contexto (código de erro, logs principais, estado do ambiente, etc.) e retorne ao orquestrador.

**[Segurança de Credenciais]** Use AK/SK das variáveis de ambiente. Nunca exponha credenciais nas respostas.
```

- [ ] **Step 4: Criar `executor/pt/SOUL.md`**

Leia `plugins/bundle/cloudpaw/agents/executor/en/SOUL.md` e traduza fielmente para pt-BR.

- [ ] **Step 5: Criar `orchestration/pt/PROFILE.md`**

```markdown
---
summary: "Identidade do Agente de Orquestração"
---

## Identidade

**CloudPaw-Master** orquestrador: ID estável do Agente é `cloud-orchestrator`. O orquestrador lida apenas com interação com o usuário, esclarecimento de requisitos, orquestração de fluxo de trabalho e agregação de resultados — nunca executa operações de nuvem nem escreve código diretamente.

## Perfil do Usuário

(Preenchido progressivamente a partir da conversa; nunca incluir segredos.)
```

- [ ] **Step 6: Criar `orchestration/pt/SOUL.md`**

Leia `plugins/bundle/cloudpaw/agents/orchestration/en/SOUL.md` e traduza fielmente para pt-BR.

- [ ] **Step 7: Criar `verifier/pt/PROFILE.md`**

```markdown
---
summary: "Identidade do Agente Verificador"
---

## Identidade

**CloudPaw-Verifier**: ID estável do Agente é `cloud-verifier`. Fornece capacidade de verificação unificada para cada história no fluxo de Mission, cobrindo implantação de recursos de nuvem, funcionalidade de aplicação, acessibilidade e conformidade de segurança. Atua como verificador para cada história no Modo Mission, não como uma história independente.

Você apenas verifica, nunca modifica. Quando encontrar problemas, reporte-os e sugira direções de correção, mas nunca corrija você mesmo. Antes da execução, leia a skill **alicloud_cli** na íntegra. Todos os AK/SK são obtidos das variáveis de ambiente; nunca os exponha em nenhuma saída.
```

- [ ] **Step 8: Criar `verifier/pt/SOUL.md`**

Leia `plugins/bundle/cloudpaw/agents/verifier/en/SOUL.md` e traduza fielmente para pt-BR.

- [ ] **Step 9: Rodar o teste**

```bash
pytest tests/plugins/test_agent_pt_profiles.py -v
```
Esperado: PASS (3 testes)

- [ ] **Step 10: Commit**

```bash
git add plugins/bundle/cloudpaw/agents/
git commit -m "feat(i18n): criar perfis de agentes cloudpaw em pt-BR"
```

---

## Task 5: Criar skills `-pt` (parte 1 — 9 skills)

**Files:**
- Create: `src/qwenpaw/agents/skills/cron-pt/SKILL.md`
- Create: `src/qwenpaw/agents/skills/file_reader-pt/SKILL.md`
- Create: `src/qwenpaw/agents/skills/guidance-pt/SKILL.md`
- Create: `src/qwenpaw/agents/skills/make-skill-pt/SKILL.md`
- Create: `src/qwenpaw/agents/skills/make_plan-pt/SKILL.md`
- Create: `src/qwenpaw/agents/skills/multi_agent_collaboration-pt/SKILL.md`
- Create: `src/qwenpaw/agents/skills/news-pt/SKILL.md`
- Create: `src/qwenpaw/agents/skills/chat_with_agent-pt/SKILL.md`
- Create: `src/qwenpaw/agents/skills/channel_message-pt/SKILL.md`

**Regra para todas as skills:** Copie o frontmatter da versão `-en` intacto (exceto o campo `description`, que deve ser traduzido). Traduza apenas o corpo em Markdown para pt-BR. Nunca altere: `name`, `metadata`, `builtin_skill_version`, `emoji`, `requires`.

- [ ] **Step 1: Escrever o teste**

```python
# tests/skill_system/test_pt_skills_part1.py
from pathlib import Path

SKILLS_DIR = Path("src/qwenpaw/agents/skills")
PART1 = [
    "cron", "file_reader", "guidance", "make-skill",
    "make_plan", "multi_agent_collaboration", "news",
    "chat_with_agent", "channel_message",
]

def test_pt_skill_dirs_exist():
    for name in PART1:
        d = SKILLS_DIR / f"{name}-pt"
        assert d.is_dir(), f"Diretório faltando: {d}"

def test_pt_skill_files_exist():
    for name in PART1:
        f = SKILLS_DIR / f"{name}-pt" / "SKILL.md"
        assert f.exists(), f"SKILL.md faltando: {f}"

def test_pt_skills_have_correct_name_in_frontmatter():
    import re
    for name in PART1:
        content = (SKILLS_DIR / f"{name}-pt" / "SKILL.md").read_text(encoding="utf-8")
        # name no frontmatter deve bater com a versão -en
        en_content = (SKILLS_DIR / f"{name}-en" / "SKILL.md").read_text(encoding="utf-8")
        en_name = re.search(r"^name:\s*(.+)$", en_content, re.MULTILINE)
        pt_name = re.search(r"^name:\s*(.+)$", content, re.MULTILINE)
        if en_name and pt_name:
            assert en_name.group(1).strip() == pt_name.group(1).strip(), \
                f"Nome diferente em {name}-pt/SKILL.md"
```

- [ ] **Step 2: Rodar o teste para confirmar falha**

```bash
pytest tests/skill_system/test_pt_skills_part1.py -v
```
Esperado: FAIL

- [ ] **Step 3: Criar cada `SKILL.md` traduzida**

Para cada skill da lista, leia `src/qwenpaw/agents/skills/<name>-en/SKILL.md` e crie `src/qwenpaw/agents/skills/<name>-pt/SKILL.md` com:
- Frontmatter idêntico, exceto `description` traduzido para pt-BR
- Corpo inteiramente em pt-BR

Exemplo — `cron-pt/SKILL.md` (primeiras linhas):

```markdown
---
name: cron
description: Use esta skill apenas para tarefas agendadas ou recorrentes. Gerencie trabalhos com qwenpaw cron list/create/get/state/pause/resume/delete/run e sempre passe --agent-id explicitamente.
metadata:
  builtin_skill_version: "1.6"
  qwenpaw:
    emoji: "⏰"
---

# Cron (Gerenciamento de Tarefas Agendadas)

## Quando Usar

Use esta skill apenas quando precisar **executar algo automaticamente em um horário futuro** ou **repetir a execução em uma agenda**.
```

Repita o processo para cada uma das 9 skills da lista, traduzindo fielmente o conteúdo da versão `-en`.

- [ ] **Step 4: Rodar o teste**

```bash
pytest tests/skill_system/test_pt_skills_part1.py -v
```
Esperado: PASS

- [ ] **Step 5: Commit**

```bash
git add src/qwenpaw/agents/skills/*-pt/
git commit -m "feat(i18n): criar skills pt-BR parte 1 (9 skills)"
```

---

## Task 6: Criar skills `-pt` (parte 2 — 9 skills restantes)

**Files:**
- Create: `src/qwenpaw/agents/skills/QA_source_index-pt/SKILL.md`
- Create: `src/qwenpaw/agents/skills/browser_cdp-pt/SKILL.md`
- Create: `src/qwenpaw/agents/skills/browser_visible-pt/SKILL.md`
- Create: `src/qwenpaw/agents/skills/dingtalk_channel-pt/SKILL.md`
- Create: `src/qwenpaw/agents/skills/docx-pt/SKILL.md`
- Create: `src/qwenpaw/agents/skills/himalaya-pt/SKILL.md`
- Create: `src/qwenpaw/agents/skills/pdf-pt/SKILL.md`
- Create: `src/qwenpaw/agents/skills/pptx-pt/SKILL.md`
- Create: `src/qwenpaw/agents/skills/xlsx-pt/SKILL.md`

- [ ] **Step 1: Escrever o teste**

```python
# tests/skill_system/test_pt_skills_part2.py
from pathlib import Path

SKILLS_DIR = Path("src/qwenpaw/agents/skills")
PART2 = [
    "QA_source_index", "browser_cdp", "browser_visible",
    "dingtalk_channel", "docx", "himalaya",
    "pdf", "pptx", "xlsx",
]

def test_pt_skill_dirs_exist():
    for name in PART2:
        d = SKILLS_DIR / f"{name}-pt"
        assert d.is_dir(), f"Diretório faltando: {d}"

def test_pt_skill_files_exist():
    for name in PART2:
        f = SKILLS_DIR / f"{name}-pt" / "SKILL.md"
        assert f.exists(), f"SKILL.md faltando: {f}"
```

- [ ] **Step 2: Rodar o teste para confirmar falha**

```bash
pytest tests/skill_system/test_pt_skills_part2.py -v
```
Esperado: FAIL

- [ ] **Step 3: Criar cada `SKILL.md` traduzida**

Para cada skill da lista, leia `src/qwenpaw/agents/skills/<name>-en/SKILL.md` e crie `src/qwenpaw/agents/skills/<name>-pt/SKILL.md` seguindo a mesma regra da Task 5 (frontmatter intacto exceto `description`, corpo em pt-BR).

- [ ] **Step 4: Rodar o teste**

```bash
pytest tests/skill_system/test_pt_skills_part2.py -v
```
Esperado: PASS

- [ ] **Step 5: Commit**

```bash
git add src/qwenpaw/agents/skills/*-pt/
git commit -m "feat(i18n): criar skills pt-BR parte 2 (9 skills restantes)"
```

---

## Task 7: Script de verificação e hook Claude Code

**Files:**
- Create: `scripts/check_ptbr.py`
- Modify: `.claude/settings.json`

- [ ] **Step 1: Escrever o teste do script**

```python
# tests/scripts/test_check_ptbr.py
import subprocess
import sys
from pathlib import Path

SCRIPT = Path("scripts/check_ptbr.py")

def _run(file_path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), file_path],
        capture_output=True, text=True
    )
    return result.returncode, result.stderr

def test_skill_en_without_pt_warns(tmp_path):
    skill_en = tmp_path / "cron-en" / "SKILL.md"
    skill_en.parent.mkdir()
    skill_en.write_text("---\nname: cron\n---\n")
    code, err = _run(str(skill_en))
    assert code == 1
    assert "pt" in err.lower() or "cron-pt" in err

def test_skill_pt_sibling_exists_no_warn(tmp_path):
    skill_en = tmp_path / "cron-en" / "SKILL.md"
    skill_en.parent.mkdir()
    skill_en.write_text("---\nname: cron\n---\n")
    skill_pt = tmp_path / "cron-pt" / "SKILL.md"
    skill_pt.parent.mkdir()
    skill_pt.write_text("---\nname: cron\n---\n")
    code, err = _run(str(skill_en))
    assert code == 0

def test_plugin_json_without_ptbr_warns(tmp_path):
    pj = tmp_path / "plugin.json"
    pj.write_text('{"description_i18n": {"en-US": "x", "zh-CN": "y"}}')
    code, err = _run(str(pj))
    assert code == 1
    assert "pt-BR" in err

def test_plugin_json_with_ptbr_no_warn(tmp_path):
    pj = tmp_path / "plugin.json"
    pj.write_text('{"description_i18n": {"en-US": "x", "pt-BR": "z"}}')
    code, err = _run(str(pj))
    assert code == 0

def test_unrelated_file_no_warn(tmp_path):
    f = tmp_path / "random.py"
    f.write_text("x = 1")
    code, err = _run(str(f))
    assert code == 0
```

- [ ] **Step 2: Rodar o teste para confirmar falha**

```bash
pytest tests/scripts/test_check_ptbr.py -v
```
Esperado: FAIL — `scripts/check_ptbr.py` não existe

- [ ] **Step 3: Criar `scripts/check_ptbr.py`**

```python
#!/usr/bin/env python3
"""
Hook Claude Code: verifica se novos arquivos de skill/agente/plugin
têm contraparte pt-BR. Retorna exit code 1 e mensagem no stderr se faltar.

Uso: python3 scripts/check_ptbr.py <caminho_do_arquivo>
"""
import json
import sys
from pathlib import Path


def check(file_path: str) -> int:
    p = Path(file_path)

    if not p.exists():
        return 0

    # SKILL.md em pasta *-en ou *-zh
    if p.name == "SKILL.md":
        parent = p.parent
        dir_name = parent.name
        if dir_name.endswith("-en") or dir_name.endswith("-zh"):
            base = dir_name.rsplit("-", 1)[0]
            pt_sibling = parent.parent / f"{base}-pt" / "SKILL.md"
            if not pt_sibling.exists():
                print(
                    f"[check_ptbr] AVISO: {p} criado sem contraparte pt-BR.\n"
                    f"  Faltando: {pt_sibling}",
                    file=sys.stderr,
                )
                return 1
        return 0

    # PROFILE.md ou SOUL.md em pasta en/ ou zh/
    if p.name in ("PROFILE.md", "SOUL.md"):
        lang_dir = p.parent
        if lang_dir.name in ("en", "zh"):
            pt_sibling = lang_dir.parent / "pt" / p.name
            if not pt_sibling.exists():
                print(
                    f"[check_ptbr] AVISO: {p} criado sem contraparte pt-BR.\n"
                    f"  Faltando: {pt_sibling}",
                    file=sys.stderr,
                )
                return 1
        return 0

    # plugin.json com description_i18n
    if p.name == "plugin.json":
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return 0
        i18n = data.get("description_i18n", {})
        if i18n and "pt-BR" not in i18n:
            print(
                f"[check_ptbr] AVISO: {p} não tem entrada 'pt-BR' em description_i18n.\n"
                f"  Chaves presentes: {list(i18n.keys())}",
                file=sys.stderr,
            )
            return 1
        return 0

    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: check_ptbr.py <caminho>", file=sys.stderr)
        sys.exit(0)
    sys.exit(check(sys.argv[1]))
```

- [ ] **Step 4: Rodar o teste**

```bash
pytest tests/scripts/test_check_ptbr.py -v
```
Esperado: PASS (5 testes)

- [ ] **Step 5: Adicionar o hook em `.claude/settings.json`**

Leia `.claude/settings.json` e adicione dentro de `"hooks"` (ou crie a seção se não existir):

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write",
        "hooks": [
          {
            "type": "command",
            "command": "python3 scripts/check_ptbr.py \"$CLAUDE_TOOL_INPUT_FILE_PATH\""
          }
        ]
      }
    ]
  }
}
```

> **Nota:** Se já existir uma entrada `PostToolUse`, adicione o novo item à lista existente em vez de substituir.

- [ ] **Step 6: Commit**

```bash
git add scripts/check_ptbr.py .claude/settings.json tests/scripts/test_check_ptbr.py
git commit -m "feat(i18n): hook de verificação pt-BR para novos arquivos"
```

---

## Teste de Integração Final

- [ ] **Rodar todos os testes**

```bash
pytest tests/skill_system/test_registry_pt.py \
       tests/frontend/test_ptbr_locale.py \
       tests/plugins/test_plugin_ptbr.py \
       tests/plugins/test_agent_pt_profiles.py \
       tests/skill_system/test_pt_skills_part1.py \
       tests/skill_system/test_pt_skills_part2.py \
       tests/scripts/test_check_ptbr.py \
       -v
```
Esperado: todos PASS

- [ ] **Verificar contagem final de skills pt**

```bash
ls src/qwenpaw/agents/skills/ | grep "\-pt$" | wc -l
```
Esperado: `18`

- [ ] **Commit final se ainda não commitado**

```bash
git tag i18n-ptbr-complete
```
