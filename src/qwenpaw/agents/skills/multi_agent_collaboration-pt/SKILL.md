---
name: multi_agent_collaboration
description: Use esta skill quando a expertise ou contexto de outro agente for necessário, ou quando o usuário pedir explicitamente para envolver outro agente. Primeiro liste os agentes, depois use qwenpaw agents chat para comunicação bidirecional com respostas.
metadata:
  builtin_skill_version: "1.4"
  qwenpaw:
    emoji: "🤝"
---

# Colaboração Multi-Agente

## Quando Usar

Use esta skill quando você **precisar da expertise, contexto, conteúdo do workspace ou suporte colaborativo de outro agente**.
Se o **usuário pedir explicitamente que um agente específico participe/auxilie/responda**, você também deve usar esta skill.

### Deve Usar
- A tarefa atual é claramente mais adequada para um agente especializado
- Você precisa do workspace / arquivos / contexto de outro agente
- Você precisa de uma segunda opinião ou revisão especializada
- O usuário pede explicitamente que um agente específico participe ou invoque outro agente

### Não Deve Usar
- Você pode completar a tarefa por conta própria e o usuário não pediu explicitamente para invocar outro agente
- É apenas um Q&A normal que não requer um agente especializado
- A informação é insuficiente -- você deve pedir esclarecimento ao usuário primeiro
- Você acabou de receber uma mensagem do Agente B -- **não chame o Agente B novamente** para evitar loops

## Regras de Decisão

1. **Se o usuário pedir explicitamente para invocar outro agente, priorize seguir a solicitação**
2. **Caso contrário, se você puder fazer por conta própria, não invoque outro agente**
3. **Verifique os agentes antes de invocar -- não adivinhe IDs**
4. **Quando continuação de contexto for necessária, você deve passar `--session-id`**
5. **Não chame de volta o agente de origem**

---

## Comandos Mais Comuns

### 1) Primeiro Consulte os Agentes Disponíveis

```bash
qwenpaw agents list
```

### 2) Iniciar uma Nova Conversa (Modo em Tempo Real)

```bash
qwenpaw agents chat \
  --from-agent <seu_agente> \
  --to-agent <agente_alvo> \
  --text "[Agente <seu_agente> solicitando] ..."
```

### 3) Submeter uma Tarefa Complexa (Modo em Segundo Plano)

**Tarefas complexas** incluem: análise de dados, geração de relatórios, processamento em lote, chamadas de API externas, etc.

```bash
qwenpaw agents chat --background \
  --from-agent <seu_agente> \
  --to-agent <agente_alvo> \
  --text "[Agente <seu_agente> solicitando] ..."
```

**Saída**:
```
[TASK_ID: xxx-xxx-xxx]
[SESSION: ...]
```

### 4) Consultar Status de Tarefa em Segundo Plano

```bash
qwenpaw agents chat --background --task-id <task_id>
```

**Importante**: Não consulte com frequência! Após submeter uma tarefa:
1. **Não bloqueie** - Continue tratando outras tarefas ou trabalho
2. **Aguarde um tempo razoável antes de consultar** - Escolha com base na complexidade da tarefa:
   - Análise simples: consulte após 10-20 segundos
   - Análise complexa: consulte após 30-60 segundos
   - Processamento em lote: consulte após 1-3 minutos
3. **Durante a espera** - Você pode responder ao usuário, tratar outras solicitações ou executar outras tarefas

### 5) Continuar uma Conversa Existente

```bash
qwenpaw agents chat \
  --from-agent <seu_agente> \
  --to-agent <agente_alvo> \
  --session-id "<session_id>" \
  --text "[Agente <seu_agente> solicitando] ..."
```

**Pontos-chave**:
- Não passar `--session-id` = nova conversa
- Passar `--session-id` = continuar conversa (contexto preservado)
- Use `--background` para tarefas complexas; registre o task_id após submissão

---

## Seleção de Modo de Tarefa

### Modo em Tempo Real vs Modo em Segundo Plano

| Tipo de Tarefa | Modo a Usar | Comando |
|----------------|-------------|---------|
| Consulta rápida simples | Modo em tempo real | `qwenpaw agents chat` |
| Tarefa complexa (análise de dados, processamento em lote, etc.) | Modo em segundo plano | `qwenpaw agents chat --background` |

**Exemplos de tarefas complexas**:
- Analisar grandes quantidades de dados ou arquivos de log
- Gerar relatórios detalhados
- Processar arquivos em lote (10+ arquivos)
- Chamar APIs externas lentas
- Tarefas independentes que precisam de execução paralela

**Critério de decisão**: Se você não tem certeza de quanto tempo uma tarefa levará, ou se a tarefa é complexa, prefira o modo em segundo plano.

---

## Fluxo Mínimo

### Fluxo do Modo em Tempo Real

```
1. Determinar se outro agente é necessário, ou se o usuário pediu explicitamente
2. qwenpaw agents list
3. qwenpaw agents chat para iniciar uma conversa
4. Registrar [SESSION: ...] da saída
5. Incluir --session-id quando continuação de contexto for necessária depois
```

### Fluxo do Modo em Segundo Plano

```
1. Determinar se a tarefa é complexa (análise de dados, geração de relatório, etc.)
2. qwenpaw agents list
3. qwenpaw agents chat --background para submeter a tarefa
4. Registrar [TASK_ID: ...] da saída
5. Continuar tratando outro trabalho
6. Aguardar um tempo razoável (30-60 segundos) antes de consultar o status
7. Usar --background --task-id para consultar resultados
```

---

## Regras Principais

### Parâmetros Obrigatórios

`qwenpaw agents chat` deve incluir todos os seguintes:
- `--from-agent`
- `--to-agent`
- `--text`

### Prefixo de Identidade

As mensagens devem começar com o seguinte prefixo:

```text
[Agente meu_agente solicitando] ...
```

### Reutilização de Sessão

A primeira chamada retornará:

```text
[SESSION: seu_agente:para:agente_alvo:...]
```

Para acompanhamentos subsequentes, você deve copiar este session_id e passá-lo via `--session-id`.

---

## Exemplos Breves

### Usuário Pede Explicitamente para Invocar Outro Agente

```bash
qwenpaw agents list

qwenpaw agents chat \
  --from-agent scheduler_bot \
  --to-agent finance_bot \
  --text "[Agente scheduler_bot solicitando] Usuário pediu explicitamente para consultar finance_bot. Por favor, responda quais tarefas financeiras pendentes existem."
```

### Nova Conversa

```bash
qwenpaw agents chat \
  --from-agent scheduler_bot \
  --to-agent finance_bot \
  --text "[Agente scheduler_bot solicitando] Quais tarefas financeiras pendentes existem hoje?"
```

### Continuar Conversa

```bash
qwenpaw agents chat \
  --from-agent scheduler_bot \
  --to-agent finance_bot \
  --session-id "scheduler_bot:to:finance_bot:1710912345:a1b2c3d4" \
  --text "[Agente scheduler_bot solicitando] Expanda o item 2"
```

---

## Erros Comuns

### Erro 1: Não verificar agentes primeiro

Não adivinhe IDs de agentes. Execute primeiro:

```bash
qwenpaw agents list
```

### Erro 2: Querer continuar uma conversa mas não passar session-id

Isso criará uma nova conversa, perdendo o contexto.

### Erro 3: Chamar de volta o agente de origem

Se você acabou de receber uma mensagem do Agente B, não chame o Agente B novamente.

---

## Comandos Opcionais

### Ver Sessões Existentes

```bash
qwenpaw chats list --agent-id <seu_agente>
```

### Saída em Streaming

```bash
qwenpaw agents chat \
  --from-agent <seu_agente> \
  --to-agent <agente_alvo> \
  --mode stream \
  --text "[Agente <seu_agente> solicitando] ..."
```

### Saída em JSON

```bash
qwenpaw agents chat \
  --from-agent <seu_agente> \
  --to-agent <agente_alvo> \
  --json-output \
  --text "[Agente <seu_agente> solicitando] ..."
```

---

## Referência Completa de Parâmetros

### qwenpaw agents list

**Parâmetros**:
- `--base-url` (opcional): Substituir o endereço da API

**Nenhum parâmetro obrigatório** -- apenas execute diretamente.

### qwenpaw agents chat

**Parâmetros obrigatórios** (modo em tempo real):
- `--from-agent`: ID do agente remetente
- `--to-agent`: ID do agente alvo
- `--text`: Conteúdo da mensagem

**Parâmetros de tarefa em segundo plano**:
- `--background`: Modo de tarefa em segundo plano
- `--task-id`: Consultar status da tarefa (usado junto com --background)

**Parâmetros opcionais**:
- `--session-id`: Reutilizar contexto de sessão (copie da saída anterior)
- `--new-session`: Forçar criação de nova sessão (mesmo se session-id for passado)
- `--mode`: stream (streaming) ou final (completo, padrão)
- `--timeout`: Timeout em segundos (padrão 300)
- `--json-output`: Produzir JSON completo em vez de texto simples
- `--base-url`: Substituir o endereço da API

---

## Detalhes do Modo de Tarefa em Segundo Plano

### Quando Usar o Modo em Segundo Plano?

Quando a tarefa é uma **tarefa complexa**, use `--background` para submetê-la ao segundo plano:

**Deve usar o modo em segundo plano**:
- Análise de dados (analisar logs, computar estatísticas)
- Geração de relatório (gerar relatórios ou documentos longos)
- Processamento em lote (processar múltiplos arquivos)
- Chamadas de API externas (chamar serviços lentos)
- Tarefas complexas com duração incerta

**Não precisa do modo em segundo plano**:
- Consultas rápidas simples
- Tarefas que claramente serão concluídas rapidamente

---

## Informações de Ajuda

Use `-h` a qualquer momento para ver ajuda detalhada:

```bash
qwenpaw agents -h
qwenpaw agents list -h
qwenpaw agents chat -h
```
