---
name: browser_cdp
description: "Use esta skill quando o usuário quiser explicitamente conectar-se a um Chrome em execução, escanear portas CDP locais, especificar um `cdp_port`, ou compartilhar um único navegador entre múltiplos agentes/ferramentas. Por padrão, o browser_use já inicia o navegador usando CDP gerenciado; se o usuário não quiser expor histórico do navegador, cookies ou outros dados sensíveis, recomende usar `private_mode=true`."
metadata:
  builtin_skill_version: "1.2"
  qwenpaw:
    emoji: "🔌"
    requires: {}
---

# Referência de Browser CDP

Por padrão, o **browser_use** inicia e gerencia o Chrome/Chromium local via **CDP gerenciado**, mas isso não significa que a porta CDP deva ser exposta ao usuário ou a outras ferramentas a cada uso.

Esta skill foca nos usos mais "explícitos" do CDP:

1. **Escanear portas CDP locais**
2. **Conectar a um Chrome existente (`connect_cdp`)**
3. **Especificar explicitamente um `cdp_port` ao iniciar o navegador**
4. **Compartilhar uma única instância do navegador entre múltiplos agentes/ferramentas**

Em outras palavras:

- O `start` padrão usa CDP gerenciado internamente, mas os usuários normalmente não precisam entender ou ter consciência dos detalhes do CDP
- Só entre no escopo desta skill quando o usuário mencionar explicitamente "conectar a um navegador existente / escanear portas / especificar uma porta / compartilhar um navegador"

> **Recomendação de Privacidade**
>
> Se o usuário não quiser expor histórico do navegador, cookies, conteúdo de páginas ou dados de sessão, recomende usar `private_mode=true`, que alterna para o modo gerenciado pelo Playwright.

> **Aviso: Uma instância de navegador por workspace**
>
> Apenas um navegador pode estar em execução ou conectado por workspace ao mesmo tempo. Se uma instância de navegador já existir, você deve executar `stop` primeiro antes de trocar para um novo navegador ou nova conexão CDP.

---

## Quando Usar

Use esta skill apenas quando o usuário expressar explicitamente uma das seguintes intenções:

- "Conectar ao meu Chrome já aberto"
- "Escanear portas CDP disponíveis nesta máquina"
- "Iniciar o navegador com uma porta de depuração fixa"
- "Permitir que outros agentes/ferramentas se conectem a este navegador também"
- "Anexar ao navegador via porta de depuração remota"

Nos seguintes casos, você geralmente **não** deve usar esta skill:

- O usuário simplesmente diz "abrir o navegador"
- O usuário simplesmente diz "abrir uma janela visível"
- O usuário não menciona compartilhamento, portas, CDP ou depuração remota

Nesses casos, use o `start` padrão, adicionando `headed=true` se necessário — consulte **browser_visible**.

---

## Cenário 1: Escanear Portas CDP Locais

O intervalo de varredura padrão é **9000–10000**:

```json
{"action": "list_cdp_targets"}
```

Especificar uma única porta:

```json
{"action": "list_cdp_targets", "port": 9222}
```

Intervalo personalizado:

```json
{"action": "list_cdp_targets", "port_min": 8000, "port_max": 12000}
```

Casos de uso:

- O usuário iniciou manualmente o Chrome com uma porta de depuração remota
- Você não sabe a porta exata e precisa escanear primeiro
- Você precisa verificar os alvos disponíveis para conexão na máquina local antes de conectar

---

## Cenário 2: Conectar a um Chrome Existente

Conectar a um endpoint CDP existente:

```json
{"action": "connect_cdp", "cdp_url": "http://localhost:9222"}
```

Características:

- Após uma conexão bem-sucedida, você pode continuar usando operações padrão como `open`, `snapshot`, `click`, `type`, etc.
- Isso **anexa a um navegador externo**, não a um novo processo iniciado pelo QwenPaw
- `stop` apenas desconecta — **não fechará o navegador externo**
- Conexões CDP externas também estão sujeitas ao gerenciamento de parada automática por inatividade, mas a semântica de parada automática para CDP externo é "desconectar automaticamente, não fechar o navegador externo"

Casos de uso:

- O usuário tem seu próprio Chrome aberto e quer que o agente assuma diretamente
- Você precisa acessar o estado de login existente do usuário ou abas abertas

---

## Cenário 3: Iniciar com um cdp_port Explícito

Se o usuário solicitar explicitamente uma porta fixa, ou precisar fornecer o endpoint para outras ferramentas, especifique `cdp_port` no `start`:

```json
{"action": "start", "cdp_port": 9222}
```

Para também abrir uma janela visível:

```json
{"action": "start", "headed": true, "cdp_port": 9222}
```

Comportamento atual:

- Se o `cdp_port` especificado explicitamente já estiver em uso, um erro é gerado imediatamente — a porta não será reutilizada à força
- Se `cdp_port` não for especificado, uma porta disponível é selecionada automaticamente, o que geralmente evita conflitos entre workspaces
- A seleção automática de uma porta disponível ainda tem uma pequena janela de corrida: entre "encontrar uma porta disponível" e "o Chrome realmente vincular à porta", outro processo poderia teoricamente reivindicá-la; em caso de falha, é feita a limpeza e um erro é reportado, mas não há tentativa automática

Portanto:

- **Não passe `cdp_port` proativamente quando o usuário não solicitou explicitamente uma porta**
- **Passe `cdp_port` explicitamente apenas quando o usuário solicitar uma porta fixa ou compartilhamento externo**

---

## Múltiplos Workspaces e Conflitos de Porta

A estratégia de porta atual para múltiplos workspaces:

- **Porta especificada explicitamente**: verifica se `127.0.0.1:cdp_port` já está em uso; se sim, falha imediatamente e solicita ao usuário que escolha uma porta diferente ou pare o processo antigo
- **Sem porta explícita**: reduz a probabilidade de conflito selecionando automaticamente uma porta disponível

Isso significa que:

- Múltiplos workspaces usando o lançamento padrão geralmente podem coexistir
- Se múltiplos workspaces solicitarem o mesmo `cdp_port` fixo, o segundo falhará porque a porta já está em uso

---

## Comportamento de Parada

O comportamento de parada relacionado ao CDP difere dependendo do tipo:

### 1. CDP Gerenciado iniciado pelo QwenPaw

Por exemplo:

```json
{"action": "start"}
```

Ou:

```json
{"action": "start", "cdp_port": 9222}
```

Esses navegadores são iniciados e gerenciados pelo QwenPaw. O `stop` irá:

- Desconectar a conexão Playwright / CDP
- Encerrar o processo do navegador

### 2. Navegador CDP Externo

Por exemplo:

```json
{"action": "connect_cdp", "cdp_url": "http://localhost:9222"}
```

Esses navegadores não são iniciados pelo QwenPaw. O `stop` irá apenas:

- Desconectar
- **Não fechar o processo do navegador externo**

---

## Divisão de Responsabilidades com browser_visible

- **browser_visible**: trata de "se deve mostrar uma janela" e "se deve usar private_mode"
- **browser_cdp**: trata de "se deve conectar / expor / especificar / escanear portas CDP"

Em resumo:

- Usuário se preocupa em "ver a janela do navegador" → pense em browser_visible primeiro
- Usuário se preocupa em "conectar a um navegador existente / especificar uma porta de depuração / compartilhar com outros" → pense em browser_cdp primeiro

---

## Observações

- Embora o `start` padrão use CDP gerenciado internamente, esse é um detalhe de implementação da ferramenta e não significa que os conceitos de CDP devam ser expostos ao usuário a cada uso
- Antes de usar capacidades CDP explícitas, avise o usuário sobre o risco de exposição de dados sensíveis
- A parada automática para CDP externo significa "desconectar automaticamente", não "fechar automaticamente o navegador do usuário"
- A atividade é atualizada principalmente por operações de ferramentas; as interações manuais do usuário na janela do navegador geralmente não reiniciam o temporizador de inatividade
- `private_mode` é um parâmetro explícito para cada chamada `start` e não persiste como estado do workspace
