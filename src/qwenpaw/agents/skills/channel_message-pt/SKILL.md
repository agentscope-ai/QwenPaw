---
name: channel_message
description: Use esta skill para enviar proativamente uma mensagem unidirecional a um usuário/sessão/canal, geralmente apenas quando o usuário pede explicitamente para enviar a um canal/sessão ou quando notificação proativa é necessária. Primeiro consulte sessões com qwenpaw chats list, depois envie com qwenpaw channels send.
metadata:
  builtin_skill_version: "1.3"
  qwenpaw:
    emoji: "📤"
---

# Mensagem de Canal

## Quando Usar

Use esta skill apenas quando o **usuário pedir explicitamente para enviar uma mensagem a um canal/sessão**, ou quando você precisar **enviar proativamente uma notificação** (por exemplo, conclusão de tarefa, lembretes, alertas).
Este é um **envio unidirecional** — **nenhuma resposta é retornada**.

### Deve Usar
- O usuário pede explicitamente para enviar a um canal/sessão específico
- Notificar proativamente o usuário após a conclusão de uma tarefa
- Lembretes agendados, alertas ou atualizações de status
- Enviar resultados assíncronos de volta a uma sessão existente
- O usuário diz explicitamente "me notifique quando terminar"

### Não Deve Usar
- Se você está simplesmente respondendo na sessão atual, **não use `qwenpaw channels send`**
- Você precisa de uma conversa bidirecional e espera uma resposta imediata
- Você não sabe qual sessão alvo usar
- Você está adivinhando `target-user` ou `target-session`

## Regras de Decisão

1. **Use somente quando o usuário pedir explicitamente para enviar a um canal/sessão, ou notificação proativa for necessária**
2. **Você deve consultar sessões antes de enviar**
3. **Não adivinhe `target-user` ou `target-session`**
4. **Se múltiplas sessões forem encontradas, prefira a mais recentemente ativa**
5. **`channel send` é um push unidirecional — nenhuma resposta do usuário é retornada**

---

## Comandos Mais Comuns

### 1) Consulte as sessões disponíveis primeiro

```bash
qwenpaw chats list --agent-id <seu_agente> --channel <canal>
```

Você também pode filtrar por usuário:

```bash
qwenpaw chats list --agent-id <seu_agente> --user-id <user_id>
```

### 2) Enviar uma mensagem

```bash
qwenpaw channels send \
  --agent-id <seu_agente> \
  --channel <canal> \
  --target-user <user_id> \
  --target-session <session_id> \
  --text "..."
```

---

## Fluxo Mínimo

```
1. Determinar: o usuário está pedindo explicitamente um envio, ou notificação proativa é necessária?
2. qwenpaw chats list — consultar a sessão alvo
3. Extrair user_id e session_id dos resultados
4. Se múltiplas sessões existirem, prefira a mais recentemente ativa
5. qwenpaw channels send — enviar a mensagem
6. Concluído (sem resposta)
```

---

## Regras Principais

### Parâmetros Obrigatórios

`qwenpaw channels send` requer todos os seguintes:
- `--agent-id`
- `--channel`
- `--target-user`
- `--target-session`
- `--text`

### Deve Consultar Primeiro

Antes de enviar, execute:

```bash
qwenpaw chats list --agent-id <seu_agente> --channel <canal>
```

Extraia dos resultados:
- `user_id` → `--target-user`
- `session_id` → `--target-session`

Se houver múltiplas sessões candidatas, prefira a com `updated_at` mais recente.

### Push Unidirecional

`qwenpaw channels send` apenas envia — não aguarda uma resposta.

---

## Exemplos Breves

### Usuário pede explicitamente para enviar a um canal

```bash
qwenpaw chats list --agent-id notify_bot --channel feishu

qwenpaw channels send \
  --agent-id notify_bot \
  --channel feishu \
  --target-user manager_id \
  --target-session manager_session \
  --text "Relatório semanal está pronto, por favor revise"
```

### Notificação de conclusão de tarefa

```bash
qwenpaw chats list --agent-id task_bot --channel console

qwenpaw channels send \
  --agent-id task_bot \
  --channel console \
  --target-user alice \
  --target-session alice_console_001 \
  --text "Tarefa concluída"
```

### Push de resultado assíncrono

```bash
qwenpaw chats list --agent-id analyst_bot --user-id alice

qwenpaw channels send \
  --agent-id analyst_bot \
  --channel console \
  --target-user alice \
  --target-session alice_console_001 \
  --text "Análise de dados concluída. Resultados salvos em report.pdf"
```

---

## Erros Comuns

### Erro 1: Usar channel send para uma resposta normal

Se você está respondendo ao usuário na sessão atual, não use `qwenpaw channels send`.

### Erro 2: Enviar sem consultar sessões primeiro

Não adivinhe `target-user` ou `target-session`. Execute primeiro:

```bash
qwenpaw chats list --agent-id <seu_agente> --channel <canal>
```

### Erro 3: Parâmetros obrigatórios faltando

Todos os cinco são obrigatórios: `--agent-id`, `--channel`, `--target-user`, `--target-session`, `--text`.

### Erro 4: Esperar uma resposta do envio

Não há resposta. Ele apenas envia a mensagem.

### Erro 5: Escolher uma sessão arbitrária quando o usuário tem múltiplas

Prefira a sessão mais recentemente ativa.

---

## Comandos Opcionais

### Listar todas as sessões

```bash
qwenpaw chats list --agent-id <seu_agente>
```

### Listar sessões de um usuário específico

```bash
qwenpaw chats list --agent-id <seu_agente> --user-id <user_id>
```

### Listar canais disponíveis

```bash
qwenpaw channels list --agent-id <seu_agente>
```

---

## Diferença do Chat de Agente

- **qwenpaw agents chat**: envia para outro agente, bidirecional, retorna uma resposta
- **qwenpaw channels send**: envia para um usuário/sessão/canal, unidirecional, sem resposta

**Princípio de seleção**:
- Precisa colaborar com outro agente → `qwenpaw agents chat`
- Precisa enviar proativamente uma mensagem para um usuário → `qwenpaw channels send`

---

## Referência Completa de Parâmetros

### qwenpaw chats list

**Parâmetros obrigatórios**:
- `--agent-id`: ID do agente

**Parâmetros opcionais**:
- `--channel`: filtrar por canal
- `--user-id`: filtrar por usuário
- `--base-url`: substituir endereço da API

### qwenpaw channels send

**Parâmetros obrigatórios** (5):
- `--agent-id`: ID do agente remetente
- `--channel`: canal alvo (console/dingtalk/feishu/discord/imessage/qq/...)
- `--target-user`: ID do usuário alvo (obtido de `qwenpaw chats list`)
- `--target-session`: ID da sessão alvo (obtido de `qwenpaw chats list`)
- `--text`: conteúdo da mensagem

**Parâmetros opcionais**:
- `--base-url`: substituir endereço da API

---

## Ajuda

Use `-h` a qualquer momento para ver ajuda detalhada:

```bash
qwenpaw channels -h
qwenpaw channels send -h
qwenpaw chats -h
qwenpaw chats list -h
```
