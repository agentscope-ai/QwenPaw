---
name: QA_source_index
description: "Mapeia tópicos e palavras-chave de perguntas dos usuários para caminhos da documentação oficial do QwenPaw e pontos de entrada comuns no código-fonte, reduzindo buscas cegas. Destinado ao Agente de QA embutido para identificar rapidamente quais arquivos ler ao responder perguntas sobre instalação, configuração, skills, MCP, multi-agente, memória, CLI, etc."
metadata:
  builtin_skill_version: "1.3"
  qwenpaw:
    emoji: "🗂️"
    requires: {}
---

# Referência Rápida de Documentação e Código-Fonte

Ao responder perguntas sobre **instalação, configuração ou princípios de comportamento**, primeiro **classifique pela palavra-chave**, depois **abra 1–2 caminhos com maior probabilidade de conter a resposta** na tabela abaixo, evitando percorrer diretórios sem rumo.

## Passos de Uso

1. Extraia o tópico da pergunta do usuário (compare com a coluna da esquerda ou sinônimos na tabela abaixo).
2. Resolva **`$QWENPAW_ROOT`**: use `which qwenpaw` para obter o caminho do executável. Se for `…/.qwenpaw/bin/qwenpaw`, a raiz do código-fonte fica três níveis acima (consistente com a skill **guidance**); caso contrário, determine-a a partir do caminho de instalação fornecido pelo usuário.
3. Resolva **`$DOCS_DIR`** primeiro (compatível com qualquer instalação): execute `python3 -c "from qwenpaw.constant import DOCS_DIR; print(DOCS_DIR or '')" 2>/dev/null`. Se retornar um caminho válido, use-o diretamente. Caso contrário, use como fallback `$QWENPAW_ROOT/website/public/docs/`.
4. **Leia a documentação primeiro**: `$DOCS_DIR/<tópico>.<idioma>.md` (use o mesmo idioma do usuário: `zh` / `en`). Se insuficiente, leia os **pontos de entrada no código-fonte** listados na tabela.

## Tópico / Palavras-chave → Documentação e Código-Fonte Preferenciais

| Tópico ou Palavras-chave (exemplos) | Documentação preferencial (`$DOCS_DIR/`) | Pontos de entrada no código-fonte (relativos a `$QWENPAW_ROOT`) |
|---------------------|-----------------------------------|-----------------------------------|
| Instalação, dependências, primeiros passos | `quickstart`, `intro` | `src/qwenpaw/cli/`, `pyproject.toml` |
| Configuração, config.json, variáveis de ambiente | `config` | `src/qwenpaw/config/config.py`, `src/qwenpaw/constant.py` |
| Skills, SKILL, skill_pool, skills embutidas | `skills` | `src/qwenpaw/agents/skill_system/`, `src/qwenpaw/agents/skills/` |
| MCP, plugins | `mcp` | `src/qwenpaw/app/routers/` (grep `mcp` conforme necessário) |
| Multi-agente, workspace, agente, QA embutido | `multi-agent` | `src/qwenpaw/app/routers/agents.py`, `src/qwenpaw/app/migration.py`, `src/qwenpaw/constant.py` (`BUILTIN_QA_AGENT_ID`, etc.) |
| Memória, MEMORY, memory_search | `memory` | `src/qwenpaw/agents/memory/memory_manager.py`, `src/qwenpaw/agents/tools/memory_search.py` |
| Console, frontend | `console` | `console/` |
| CLI, subcomandos, init | `cli` | `src/qwenpaw/cli/` (ex.: `init_cmd.py`) |
| Canais, sessões | `channels` | Pesquise a palavra-chave `channels` em `src/qwenpaw` |
| Contexto, janela | `context` | Documentação `config` + lógica relacionada em `src/qwenpaw/agents/` |
| Modelos, API Key | `models` | `src/qwenpaw/config/config.py` |
| Heartbeat, HEARTBEAT | `heartbeat` | Pesquise `heartbeat` / `HEARTBEAT` em `src/qwenpaw` |
| Cliente desktop | `desktop` | `desktop/` (se presente no repositório) |
| Segurança | `security` | Leia `security.<lang>.md` primeiro |
| Erros, FAQ | `faq` | Leia `faq.<lang>.md` primeiro; examine o código-fonte conforme necessário |
| Comandos e slash commands | `commands` | Módulos de registro de comandos CLI em `src/qwenpaw` (pesquise conforme necessário) |

## Convenções

- Caminho completo da documentação: `$DOCS_DIR/<tópico>.<idioma>.md` (use `.en.md` como fallback se o arquivo no idioma correspondente não existir). Prefira `DOCS_DIR` de `qwenpaw.constant`; fallback para `$QWENPAW_ROOT/website/public/docs/`.
- Os **pontos de entrada no código-fonte** na tabela são pontos de partida; use `read_file` ou `grep` direcionado para localizar símbolos específicos — não percorra um diretório grande inteiro de uma vez.

## Observações

- Esta skill **não substitui** o `read_file`: após identificar os caminhos candidatos, você deve lê-los e verificar o conteúdo imediatamente.
- Se um caminho não existir localmente (ex.: instalação sem código-fonte), use o **pacote de documentação instalado** ou o diretório raiz fornecido pelo usuário, e indique claramente qual caminho está sendo utilizado.
