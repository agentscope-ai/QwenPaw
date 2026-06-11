---
name: cron
description: Use esta skill apenas para tarefas agendadas ou recorrentes. Gerencie jobs com qwenpaw cron list/create/get/state/pause/resume/delete/run e sempre passe --agent-id explicitamente.
metadata:
  builtin_skill_version: "1.6"
  qwenpaw:
    emoji: "⏰"
---

# Cron (Gerenciamento de Tarefas Agendadas)

## Quando Usar

Use esta skill apenas quando precisar **executar algo automaticamente em um horário futuro** ou **repetir a execução em um agendamento**.

### Deve Usar
- O usuário pede para fazer algo "diariamente / semanalmente / a cada hora"
- O usuário pede lembretes automáticos ou execução "amanhã às 9h / na próxima segunda / em um horário específico"
- Notificações periódicas de longo prazo, verificações ou relatórios são necessários

### Não Deve Usar
- A tarefa só precisa ser **executada uma vez agora**
- É apenas uma resposta normal dentro da sessão atual
- O usuário não especificou um horário de execução ou agendamento
- O canal / usuário / sessão alvo ainda está indefinido

## Regras de Decisão

1. **Use cron somente para execução agendada futura ou periódica**
2. **Se precisar ser feito apenas uma vez imediatamente, não crie um job cron**
3. **Antes de criar, confirme horário/agendamento de execução, canal alvo, target-user e target-session**
4. **Todos os comandos cron devem incluir explicitamente `--agent-id`**
5. **Não dependa do agente padrão, ou a tarefa pode acabar no workspace padrão**

---

## Regras Obrigatórias

### Deve Especificar `--agent-id` Explicitamente

Todos os comandos `qwenpaw cron` **devem** incluir:

```bash
--agent-id <seu_agent_id>
```

Seu agent_id é encontrado na seção de Identidade do Agente no prompt do sistema (Your agent id is ...).
Não omita, ou a tarefa pode ser criada incorretamente no workspace do agente padrão.

---

## Comandos Comuns

```bash
# Listar tarefas
qwenpaw cron list --agent-id <agent_id>

# Ver detalhes da tarefa
qwenpaw cron get <job_id> --agent-id <agent_id>

# Ver status da tarefa
qwenpaw cron state <job_id> --agent-id <agent_id>

# Criar uma tarefa
qwenpaw cron create --agent-id <agent_id> ...

# Deletar uma tarefa
qwenpaw cron delete <job_id> --agent-id <agent_id>

# Pausar / Retomar uma tarefa
qwenpaw cron pause <job_id> --agent-id <agent_id>
qwenpaw cron resume <job_id> --agent-id <agent_id>

# Executar uma tarefa existente uma vez imediatamente
qwenpaw cron run <job_id> --agent-id <agent_id>
```

---

## Criando Tarefas

Dois tipos são suportados:
- **text**: Envia uma mensagem fixa no agendamento
- **agent**: Faz uma pergunta a um agente no agendamento e envia a resposta ao canal alvo

Dois modos de agendamento são suportados:
- **cron** (`--schedule-type cron`): recorrência clássica cron (por exemplo, diariamente 09:00 ou a cada 2 horas)
- **scheduled** (`--schedule-type scheduled`): agendamento estilo calendário a partir de `--run-at`, único ou repetindo por dia

### Regras de Seleção de Agendamento (Deve Seguir)
- Se a intenção do usuário é recorrência genérica ("a cada hora/dia/semana") sem data de início específica, prefira `cron`
- Se a intenção do usuário inclui uma data de início concreta ("amanhã", "próxima segunda", "a partir de <data>", "pelas próximas duas semanas"), prefira `scheduled`
- Para tarefas `scheduled` únicas: passe apenas `--run-at` e não passe nenhuma opção `--repeat-*`
- Para tarefas `scheduled` repetidas: passe `--repeat-every-days` e escolha uma condição de término:
  - contagem fixa: `--repeat-end-type count --repeat-count N`
  - data/hora de término: `--repeat-end-type until --repeat-until <ISO8601>`
  - sem fim: `--repeat-end-type never`

### Configurações de Timeout

O timeout padrão é de 120 segundos (2 minutos). Para tarefas de agente mais longas, você **deve** definir explicitamente um timeout maior para evitar cancelamento prematuro:

```bash
--timeout 600   # 10 minutos
--timeout 3600   # 1 hora
```

**Regras Principais**:
1. Se a tarefa do agente envolve pesquisa web, execução de código ou chamadas de ferramentas em múltiplas etapas, defina `--timeout 600` ou maior
2. **O timeout deve ser menor que o intervalo de agendamento** para evitar sobreposição (uma nova execução disparando enquanto a anterior ainda está em execução). Exemplos:
   - A cada 15 minutos: `--timeout` não deve exceder 900 segundos
   - A cada 10 minutos: `--timeout` recomendado não mais que 80% do intervalo (ou seja, 480 segundos)
   - Diariamente: `--timeout` pode ser maior, sem restrição especial
3. Para tarefas frequentes (intervalo ≤ 10 minutos), siga **timeout ≤ 80% do intervalo**; para tarefas infrequentes (a cada hora ou mais), defina com base nas necessidades reais

### Informações Mínimas Necessárias Antes de Criar
- `--type`
- `--name`
- `--schedule-type`
- `--cron` (quando `--schedule-type cron`)
- `--run-at` (quando `--schedule-type scheduled`)
- `--channel`
- `--target-user`
- `--target-session`
- `--text`
- `--agent-id`
- `--timeout` (para tarefas do tipo agent, defina um timeout apropriado baseado no tempo de execução esperado)

Se alguma dessas informações estiver faltando, confirme com o usuário antes de criar a tarefa.

### Exemplos de Criação

```bash
# Tarefa recorrente (--schedule-type cron)
qwenpaw cron create \
  --agent-id <agent_id> \
  --type text \
  --schedule-type cron \
  --name "Saudação Diária" \
  --cron "0 9 * * *" \
  --channel imessage \
  --target-user "CHANGEME" \
  --target-session "CHANGEME" \
  --text "Bom dia!"
```

```bash
# Tarefa recorrente (--schedule-type cron)
qwenpaw cron create \
  --agent-id <agent_id> \
  --type agent \
  --schedule-type cron \
  --name "Verificar Tarefas" \
  --cron "0 */2 * * *" \
  --channel dingtalk \
  --target-user "CHANGEME" \
  --target-session "CHANGEME" \
  --text "Quais são minhas tarefas pendentes?" \
  --timeout 600
```

```bash
# Agendado único: lembrete às 9h de amanhã (sem repetição)
qwenpaw cron create \
  --agent-id <agent_id> \
  --type text \
  --schedule-type scheduled \
  --name "Lembrete Manhã de Amanhã" \
  --run-at "2026-05-13T09:00:00+08:00" \
  --channel dingtalk \
  --target-user "CHANGEME" \
  --target-session "CHANGEME" \
  --text "Standup começa às 9:00." \
  --save-result-to-inbox
```

```bash
# Agendado repetido: próximas duas semanas, todos os dias às 9h (14 execuções)
qwenpaw cron create \
  --agent-id <agent_id> \
  --type text \
  --schedule-type scheduled \
  --name "Lembrete Standup Duas Semanas" \
  --run-at "2026-05-13T09:00:00+08:00" \
  --repeat-every-days 1 \
  --repeat-end-type count \
  --repeat-count 14 \
  --channel dingtalk \
  --target-user "CHANGEME" \
  --target-session "CHANGEME" \
  --text "Standup começa às 9:00." \
  --save-result-to-inbox
```

### Criar a partir de JSON

```bash
qwenpaw cron create --agent-id <agent_id> -f job_spec.json
```

---

## Fluxo Mínimo

```
1. Determinar se realmente requer "agendamento futuro" ou "execução periódica"
2. Confirmar horário/agendamento de execução
3. Confirmar canal, target-user, target-session
4. Incluir explicitamente --agent-id
5. Criar a tarefa com qwenpaw cron create
6. Gerenciar tarefas posteriormente com list / state / pause / resume / delete
```

---

## Exemplos de Expressão Cron

```
0 9 * * *      Todo dia às 9:00
0 */2 * * *    A cada 2 horas
30 8 * * 1-5   Dias úteis às 8:30
0 0 * * 0      Todo domingo à meia-noite
*/15 * * * *   A cada 15 minutos
```

---

## Erros Comuns

### Erro 1: Criar um job cron para execução imediata única

Se a tarefa só precisa ser feita uma vez agora, não crie um job cron.

### Erro 2: Não passar --agent-id

Isso faz com que a tarefa seja atribuída ao agente / workspace errado. Todos os comandos cron devem incluir explicitamente `--agent-id`.

### Erro 3: Criar uma tarefa sem informações completas

Se o usuário não especificou o horário, agendamento, canal alvo ou sessão alvo, peça esclarecimento primeiro.

### Erro 4: Modificar tarefas existentes sem verificar primeiro

Antes de pausar, retomar ou deletar, execute primeiro:

```bash
qwenpaw cron list --agent-id <agent_id>
```

para encontrar o `job_id` correto.

---

## Dicas de Uso

- Quando parâmetros estiverem faltando, pergunte ao usuário antes de criar
- Antes de modificar/pausar/deletar, execute `qwenpaw cron list --agent-id <agent_id>` primeiro
- Para solucionar problemas, use `qwenpaw cron state <job_id> --agent-id <agent_id>`
- Ao mostrar comandos ao usuário, forneça versões completas prontas para copiar e colar
- Se o usuário mencionar "salvar na caixa de entrada" (ou não), inclua explicitamente `--save-result-to-inbox` ou `--no-save-result-to-inbox`
- Antes de criar, você pode executar `qwenpaw chats list --agent-id <agent_id>` para obter `target-user` e `target-session` válidos

---

## Informações de Ajuda

```bash
qwenpaw cron -h
qwenpaw cron list -h
qwenpaw cron create -h
qwenpaw cron get -h
qwenpaw cron state -h
qwenpaw cron pause -h
qwenpaw cron resume -h
qwenpaw cron delete -h
qwenpaw cron run -h
```
