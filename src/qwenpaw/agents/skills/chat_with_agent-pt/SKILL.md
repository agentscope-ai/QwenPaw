---
name: chat_with_agent
description: Use esta skill quando precisar consultar outro agente, pedir ajuda ou envolver um agente específico que o usuário solicitou.
metadata:
  builtin_skill_version: "1.2"
  qwenpaw:
    emoji: "💬"
---

# Conversar com Agente

## Quando Usar

Use esta skill quando precisar **fazer uma pergunta a outro agente, buscar ajuda, solicitar um plano, solicitar uma revisão, solicitar suporte para decisão ou se engajar em qualquer forma de comunicação**.
Se o **usuário pedir explicitamente para falar com um agente específico**, você também deve usar esta skill.

### Deve Usar

- Você precisa da expertise, julgamento ou segunda opinião de outro agente
- Você precisa solicitar um plano, revisão ou recomendação de um agente
- O usuário pede explicitamente que um agente específico participe, auxilie ou responda
- Você precisa continuar uma sessão de agente existente preservando o contexto

### Não Deve Usar

- Você pode completar a tarefa por conta própria e o usuário não pediu explicitamente para envolver outro agente
- É um Q&A simples que não requer um agente especializado
- O agente alvo é unclear — você deve pedir esclarecimento ou listar agentes disponíveis primeiro
- Você acabou de receber uma mensagem de um agente e está prestes a chamar imediatamente o mesmo agente de volta, o que pode causar um loop

## Regras de Decisão

1. **Se o usuário solicitar um agente específico, siga essa solicitação — mas ainda consulte o agente primeiro; não adivinhe o ID**
2. **Se você puder completar a tarefa por conta própria, não chame outro agente**
3. **Ao continuar uma conversa, você deve passar `session_id`**
4. **Por padrão, prefira usar `list_agents()` e `chat_with_agent(...)` para conversas em primeiro plano — não recorra a outros métodos**
5. **Se a tarefa deve rodar em segundo plano, use `submit_to_agent(...)` para submetê-la, depois `check_agent_task(...)` para verificar o status**

## Fluxo de Uso

Siga este fluxo estritamente ao usar esta skill:

1) Certifique-se de que sua lista de ferramentas inclua as ferramentas integradas `list_agents()` e `chat_with_agent(...)`

  - Essas duas ferramentas são a base para comunicação com outros agentes — não as remova ou desative
  - Se você não tiver essas ferramentas, informe ao usuário que você precisa delas para falar com outros agentes, e peça ao usuário para adicioná-las

2) Use `list_agents()` para ver os agentes atualmente disponíveis, e selecione um extraindo seu ID

  - Escolha o agente mais apropriado com base nas necessidades do usuário e na descrição de cada agente
  - Se nenhum agente adequado for encontrado e você não for o Agente Padrão, use o Agente Padrão
  - Caso contrário, informe ao usuário que nenhum agente adequado está disponível, e sugira criar um novo agente ou ajustar descrições de agentes existentes para melhor correspondência

3) Chame `chat_with_agent(...)` para iniciar uma conversa em primeiro plano. Parâmetros-chave incluem:
  - `to_agent`: o ID do agente alvo (nota: este é o ID, não o nome)
  - `text`: o que você quer dizer ao agente alvo
  - `session_id`: (opcional) se você precisar de múltiplas rodadas de conversa com o mesmo agente, passe o mesmo `session_id` a partir da segunda rodada para manter continuidade de contexto
  - `timeout`: (opcional) tempo estimado necessário para a espera em primeiro plano, para evitar timeouts prematuros

4) Se a tarefa for mais adequada para execução em segundo plano, use o caminho de ferramentas em segundo plano:
  - `submit_to_agent(...)`: submeter uma tarefa em segundo plano — requer apenas `to_agent`, `text` e opcionalmente `session_id`
  - `check_agent_task(...)`: verificar status da tarefa por `task_id`; retorna o resultado final quando completo

## Exemplos Mínimos de Chamada

### Nova Conversa

```text
list_agents()

chat_with_agent(
  to_agent="<id_do_agente_alvo>",
  text="[Agente <seu_id_de_agente> solicitando] Preciso da sua ajuda para determinar a abordagem para este problema.",
)
```

### Continuando uma Conversa Existente

```text
chat_with_agent(
  to_agent="<id_do_agente_alvo>",
  text="[Agente <seu_id_de_agente> solicitando] Por favor, continue expandindo o ponto 2 com base na conclusão anterior.",
  session_id="<session_id_anterior>",
)
```

### Submissão em Segundo Plano e Verificação de Status

```text
submit_to_agent(
  to_agent="<id_do_agente_alvo>",
  text="[Agente <seu_id_de_agente> solicitando] Por favor, complete esta tarefa mais longa em segundo plano.",
)

check_agent_task(
  task_id="<task_id>",
)
```


## Notas Importantes

- **Adicione um identificador de conversa**: é recomendado iniciar sua mensagem com:

```text
[Agente <seu_id_de_agente> solicitando]
```
Isso ajuda o outro agente a identificar claramente quem está falando, melhorando a eficiência e precisão da comunicação.


- **Reutilize sessões sabiamente**: se você precisar de múltiplas rodadas de conversa com o mesmo agente, certifique-se de passar o mesmo `session_id` para manter continuidade de contexto. Caso contrário, cada chamada é tratada como uma nova conversa, e o outro agente pode não entender corretamente suas necessidades. Você pode obter o `session_id` da resposta da primeira rodada, por exemplo:

  ```text
  [SESSION: xxx]
  ```

  onde `xxx` é o valor do `session_id`. Este valor é tipicamente gerado pelo sistema e tem um formato longo e único. Salve este `session_id` e continue usando-o em conversas subsequentes com o mesmo agente.
