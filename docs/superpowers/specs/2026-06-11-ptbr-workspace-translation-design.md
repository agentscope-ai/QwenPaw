# Design: Tradução pt-BR do Workspace QwenPaw

**Data:** 2026-06-11  
**Status:** Aprovado

## Objetivo

Traduzir o workspace completo do QwenPaw para português brasileiro (pt-BR) seguindo o mesmo padrão já usado para chinês (`-zh`, `zh/`, `zh-CN`). Incluir um hook de verificação que detecta novos arquivos e avisa quando a contraparte pt-BR está faltando.

## Escopo

### 1. Skills internas (`src/qwenpaw/agents/skills/`)

Cada skill `-zh` tem uma contraparte `-en`. Vamos criar `-pt` para cada uma:

- `QA_source_index-pt/SKILL.md`
- `browser_cdp-pt/SKILL.md`
- `browser_visible-pt/SKILL.md`
- `channel_message-pt/SKILL.md`
- `chat_with_agent-pt/SKILL.md`
- `cron-pt/SKILL.md`
- `dingtalk_channel-pt/SKILL.md`
- `docx-pt/SKILL.md`
- `file_reader-pt/SKILL.md`
- `guidance-pt/SKILL.md`
- `himalaya-pt/SKILL.md`
- `make-skill-pt/SKILL.md`
- `make_plan-pt/SKILL.md`
- `multi_agent_collaboration-pt/SKILL.md`
- `news-pt/SKILL.md`
- `pdf-pt/SKILL.md`
- `pptx-pt/SKILL.md`
- `xlsx-pt/SKILL.md`

Cada `SKILL.md` é uma tradução fiel da versão `-en`, com frontmatter preservado e corpo em pt-BR.

### 2. Agentes dos plugins (`plugins/bundle/*/agents/`)

Cada agente tem `en/` e `zh/`. Criar `pt/` com:

- `plugins/bundle/cloudpaw/agents/executor/pt/PROFILE.md`
- `plugins/bundle/cloudpaw/agents/executor/pt/SOUL.md`
- `plugins/bundle/cloudpaw/agents/orchestration/pt/PROFILE.md`
- `plugins/bundle/cloudpaw/agents/orchestration/pt/SOUL.md`
- `plugins/bundle/cloudpaw/agents/verifier/pt/PROFILE.md`
- `plugins/bundle/cloudpaw/agents/verifier/pt/SOUL.md`

### 3. Metadados dos plugins (`plugin.json`)

Adicionar `pt-BR` em `description_i18n` nos dois plugins:

```json
"description_i18n": {
  "zh-CN": "...",
  "en-US": "...",
  "pt-BR": "..."
}
```

Arquivos afetados:
- `plugins/bundle/cloudpaw/plugin.json`
- `plugins/bundle/qwenpaw-pet/plugin.json`

### 4. Locale do frontend (`console/src/locales/pt-BR.json`)

Completar a chave `tool` que existe em `en.json` mas falta em `pt-BR.json`.

### 5. Registry do sistema de skills (`src/qwenpaw/agents/skill_system/registry.py`)

Adicionar `"pt"` na constante `BUILTIN_SKILL_LANGUAGES`:

```python
# antes
BUILTIN_SKILL_LANGUAGES = ("en", "zh")

# depois
BUILTIN_SKILL_LANGUAGES = ("en", "zh", "pt")
```

Também adicionar `pt` no regex `_BUILTIN_SKILL_DIR_RE`:

```python
_BUILTIN_SKILL_DIR_RE = re.compile(
    r"^(?P<name>.+)-(?P<language>en|zh|pt)$",
)
```

### 6. Hook de verificação (`.claude/settings.json`)

Hook `PostToolUse` no evento `Write` que executa um script Python verificador:

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

Script `scripts/check_ptbr.py`:
- Recebe o caminho do arquivo recém-criado
- Se for `SKILL.md` em pasta `*-en/` ou `*-zh/`: verifica se existe `*-pt/SKILL.md` irmão
- Se for `PROFILE.md` ou `SOUL.md` em pasta `en/` ou `zh/`: verifica se existe `pt/` irmão
- Se for `plugin.json`: verifica se `description_i18n` tem chave `pt-BR`
- Se faltar algo: imprime aviso no stderr (aparece no terminal do Claude Code)

## Arquitetura de detecção de idioma

O registry já tem `get_builtin_skill_language_preference()`. A função lê o locale configurado pelo usuário no QwenPaw. Com `"pt"` adicionado em `BUILTIN_SKILL_LANGUAGES`, quando o usuário configura o idioma como `pt`, o sistema carrega automaticamente as skills `-pt` em vez de `-en`.

## O que não está no escopo

- Tradução de strings hardcoded no backend Python (prompts internos do sistema) — esses são prompts de sistema, não UI do usuário
- Tradução do console React além do `locales/pt-BR.json` — o sistema `t()` já funciona, só falta completar o arquivo
- README.md dos plugins (documentação de desenvolvedor, mantém em inglês/chinês)

## Critérios de sucesso

1. Configurar idioma como `pt` no QwenPaw carrega skills em português
2. Agentes dos plugins respondem com persona em pt-BR
3. `plugin.json` exibe descrição em pt-BR na interface
4. `locales/pt-BR.json` completo (sem fallback para inglês)
5. Hook avisa no terminal quando novo arquivo de skill/agente/plugin é criado sem contraparte pt-BR
