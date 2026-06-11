---
name: guidance
description: "Responda perguntas do usuário sobre instalação e configuração do QwenPaw: primeiro localize e leia a documentação local, depois destile a resposta; se a informação local for insuficiente, recorra à documentação do site oficial."
metadata:
  builtin_skill_version: "1.3"
  qwenpaw:
    emoji: "🧭"
    requires: {}
---

# Guia de Perguntas e Respostas sobre Instalação e Configuração do QwenPaw

Use esta skill quando o usuário perguntar sobre **instalação do QwenPaw, inicialização, configuração de ambiente, requisitos de dependências ou opções de configuração comuns**.

Princípios fundamentais:

- Verifique a documentação local primeiro, depois responda
- Baseie as respostas no que foi realmente lido, não especule
- Responda no mesmo idioma que o usuário usou para perguntar

## Fluxo Padrão

### Passo 1: Localizar o Diretório de Documentação

**Use a resolução de caminho integrada (funciona para todos os métodos de instalação)**

```bash
DOCS_DIR=$(python3 -c "from qwenpaw.constant import DOCS_DIR; print(DOCS_DIR or '')" 2>/dev/null)
```

Se o comando acima retornar um caminho não vazio e o diretório existir, use-o diretamente e pule para o Passo 2.

Se falhar (por exemplo, versão mais antiga sem DOCS_DIR), recorra na seguinte ordem:

**Verificar diretório de documentação na memória**

Primeiro, verifique se há um diretório de documentação na memória. Se encontrado, use diretamente; caso contrário, prossiga para o próximo passo.

```bash
# Obter o diretório de documentação da memória
DOCS_DIR=$(find ~/.qwenpaw/memory/ -type d -name "docs")
```

Se não houver diretório de documentação na memória, continue com a lógica a seguir.

**Verificar o diretório de documentação no código-fonte do projeto**

Execute a seguinte lógica de script para obter a variável $QWENPAW_ROOT:

```bash
# Obter o caminho absoluto do binário
QWENPAW_PATH=$(which qwenpaw 2>/dev/null || whereis qwenpaw | awk '{print $2}')

# Dedução lógica: se o caminho contiver .qwenpaw/bin/qwenpaw, a raiz está três níveis acima
# Exemplo: /caminho/para/QwenPaw/.qwenpaw/bin/qwenpaw -> /caminho/para/QwenPaw
if [[ "$QWENPAW_PATH" == *".qwenpaw/bin/qwenpaw" ]]; then
    QWENPAW_ROOT=$(echo "$QWENPAW_PATH" | sed 's/\/\.qwenpaw\/bin\/qwenpaw//')
else
    # Fallback: tentar obter o pai do diretório pai
    QWENPAW_ROOT=$(dirname $(dirname "$QWENPAW_PATH") 2>/dev/null || echo ".")
fi

echo "QwenPaw Root detectado: $QWENPAW_ROOT"
```

Verificar e listar o diretório de documentação:
Use o $QWENPAW_ROOT derivado para localizar a documentação:

```bash
# Construir o caminho padrão de documentação
DOCS_DIR="$QWENPAW_ROOT/website/public/docs/"

# Verificar se o caminho existe e listar arquivos
if [ -d "$DOCS_DIR" ]; then
    find "$DOCS_DIR" -type f -name "*.md" | head -n 100
else
    # Se o caminho derivado estiver incorreto, realizar busca global fuzzy
    find "$QWENPAW_ROOT" -type d -name "docs" | grep "website/public/docs"
fi
```

**Se a documentação do projeto não existir, buscar no diretório de trabalho**

Se a documentação ainda não for encontrada, busque conteúdo de documentação disponível no caminho de instalação do qwenpaw:

```bash
# Procurar arquivos característicos como faq.en.md ou config.zh.md
FILE_PATH=$(find . -type f -name "faq.en.md" -o -name "config.zh.md" | head -n 1)
if [ -n "$FILE_PATH" ]; then
    # Usar dirname para obter o diretório que contém o arquivo
    DOCS_DIR=$(dirname "$FILE_PATH")
fi
```

Se um diretório de documentação for encontrado, salve-o na memória neste formato:

```markdown
# Diretório de Documentação
$DOCS_DIR = <caminho_doc>
```

### Passo 2: Busca e Correspondência de Documentação

Os arquivos de documentação seguem o formato de nomeação `<tópico>.<lang>.md` (por exemplo, `config.zh.md`, `config.en.md`, `quickstart.zh.md`).

Use o comando find para listar todos os documentos correspondentes no diretório alvo e identifique o alvo como <caminho_doc> com base em palavras-chave do nome do arquivo (por exemplo, install, env, setup).

```bash
# Listar todos os documentos correspondentes
find $DOCS_DIR -type f -name "*.md"
```

Se nenhum documento adequado for encontrado, leia todo o conteúdo da documentação no próximo passo.

### Passo 3: Ler o Conteúdo da Documentação

Após encontrar documentos candidatos, leia e identifique os parágrafos relevantes para a pergunta. Você pode usar:

- `cat <caminho_doc>`
- skill `file_reader` (recomendado para documentos mais longos ou leitura paginada)

Se a documentação for longa, priorize a leitura das seções mais relevantes para a pergunta (etapas de instalação, opções de configuração, exemplos de comandos, notas, requisitos de versão).

### Passo 4: Extrair Informações e Responder

Extraia informações-chave da documentação e organize em uma resposta acionável:

- Dê a conclusão direta primeiro
- Depois forneça etapas / comandos / exemplos de configuração
- Inclua pré-requisitos necessários e armadilhas comuns

Requisito de idioma: o idioma da resposta deve corresponder ao idioma da pergunta do usuário (responda em português se perguntado em português, responda em inglês se perguntado em inglês).

### Passo 5 (Opcional): Consulta ao Site Oficial

Se os passos anteriores não puderem ser concluídos (sem documentação local, documentação ausente ou informação insuficiente), use o site oficial como fallback:

- http://qwenpaw.agentscope.io/

Responda com base no conteúdo disponível no site oficial, e declare claramente na resposta que a conclusão vem da documentação do site oficial.

## Requisitos de Qualidade da Saída

- Não fabrique opções de configuração ou comandos inexistentes
- Quando houver diferenças de versão, note claramente "consulte a versão atual da documentação"
- Para caminhos, comandos e chaves de configuração, forneça trechos originais prontos para copiar e colar sempre que possível
- Se a informação ainda for insuficiente, declare claramente as lacunas e diga ao usuário quais informações adicionais são necessárias (por exemplo, sistema operacional, método de instalação, logs de erro)
