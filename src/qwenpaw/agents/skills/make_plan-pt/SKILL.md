---
name: make_plan
description: Para cenários de solicitação de plano externo, guia o Agente a solicitar um plano claro, acionável e passo a passo de um Agente mais forte via list_agents e chat_with_agent, enfatizando que o plano é executado pelo solicitante, não pelo Agente consultado.
metadata:
  builtin_skill_version: "1.3"
  qwenpaw:
    emoji: "🗺️"
---

# Criar Plano

Use esta Skill quando precisar fazer uma **solicitação de plano externo** para um Agente mais forte.

O objetivo desta Skill não é terceirizar uma tarefa, mas sim:
- Solicitar um plano de um Agente mais forte
- O plano deve consistir em **etapas claras e acionáveis**
- **Você executa o plano por conta própria**
- Não peça ao Agente consultado para executar a tarefa diretamente

Como invocar:
- Use `list_agents()` para verificar os Agentes disponíveis
- Use `chat_with_agent(...)` para solicitar ao Agente mais forte que "crie um plano"
- Em `text`, inclua explicitamente o prompt: **forneça apenas um plano executável passo a passo, não execute**
- Para complementar ou refinar o plano original em um acompanhamento, passe `session_id`

Esqueleto de invocação recomendado:

```text
list_agents()

chat_with_agent(
  to_agent="<agente_mais_forte>",
  text="[Agente <auto> solicitando] Por favor, ajude-me a criar um plano de execução para a seguinte tarefa. Você não precisa executar a tarefa -- apenas produza etapas claras e acionáveis em ordem.",
)
```

## Regras Fundamentais

Esta Skill trata de uma única coisa:
1. Encontrar um Agente mais forte
2. Solicitar que esse Agente produza um plano de execução
3. Exigir que o plano seja passo a passo, acionável e em ordem sequencial
4. Você executa o plano por conta própria em vez de pedir ao outro Agente para fazê-lo

Se o que você realmente precisa é de um "plano", use esta Skill.
Se o que você precisa é de uma resposta final, julgamento arquitetural, conclusão de revisão ou execução direta, não use esta Skill indevidamente.

## Cenários Aplicáveis

Os seguintes cenários são adequados para fazer uma solicitação de plano externo:
- A tarefa requer decomposição em múltiplas etapas
- As etapas têm dependências entre si
- Uma sequência clara, pontos de verificação ou pontos de validação são necessários
- Múltiplos módulos, arquivos, sistemas ou funções estão envolvidos
- O usuário solicita explicitamente um plano antes da execução
- Você quer obter um caminho de execução mais completo e confiável primeiro

## Não Use Desta Forma

Não use esta Skill nas seguintes situações:
- Você realmente quer que o outro Agente faça a tarefa por você
- O que você realmente está faltando é um pequeno pedaço de informação factual, não um plano
- O que você realmente precisa é de um julgamento arquitetural ou comparação de soluções
- Você ainda não entendeu claramente o objetivo da tarefa

## O Que Pedir ao Agente Mais Forte

Ao chamar `chat_with_agent(...)`, declare claramente:
- **Você precisa de um plano, não de execução**
- **Os passos devem ser concretos, não apenas conselho abstrato**
- **De preferência inclua métodos de verificação e critérios de conclusão**

## Regras de Invocação de Ferramentas

Execute nesta ordem por padrão:
1. Chame `list_agents()` para confirmar os Agentes mais fortes disponíveis
2. Selecione o Agente alvo mais adequado para criar o plano
3. Chame `chat_with_agent(...)` para solicitar a geração de um plano de execução
4. Após receber o plano, execute-o por conta própria -- não continue terceirizando a tarefa para o outro Agente

Ao solicitar o plano, declare explicitamente:
- Apenas o plano é necessário, não a execução
- Os passos devem ser específicos, não conselho geral
- Solicite claramente sequência, dependências, pontos de verificação e métodos de validação quando necessário

Parâmetros comuns para `chat_with_agent`:
- `to_agent`: ID do Agente alvo
- `text`: Conteúdo da solicitação; deve declarar explicitamente "apenas produza o plano, não execute a tarefa"
- `session_id`: Opcional; passe para continuar uma conversa existente

Notas:
- `base_url` geralmente não precisa ser fornecida; a ferramenta resolverá automaticamente o endereço da API atual
- Não passar `session_id` criará automaticamente uma nova sessão

## Modelo de Solicitação

Por favor, ajude-me a criar um plano de execução para a seguinte tarefa.
Você **não precisa executar a tarefa em si** -- apenas produza o plano.

Tarefa:
[O que precisa ser feito]

Objetivo:
[Qual deve ser o resultado final]

Restrições:
- [...]
- [...]

Requisitos do plano:
1. Divida em etapas claras e executáveis
2. Indique a ordem recomendada
3. Aponte dependências, pontos de verificação ou métodos de validação onde necessário
4. Se houver riscos óbvios, inclua pontos-chave a observar

Formato de saída:
[ex.: Produza 5-8 etapas numeradas, 1-3 frases cada]

Exemplo:

```text
chat_with_agent(
  to_agent="strong_reasoner",
  text="""
Por favor, ajude-me a criar um plano de execução para a seguinte tarefa.
Você não precisa executar a tarefa em si -- apenas produza o plano.

Tarefa:
Modificar um recurso de múltiplos módulos.

Objetivo:
Completar a mudança com baixo risco e evitar perder pontos de integração.

Restrições:
- Minimizar retrabalho
- Incluir pontos de verificação intermediários verificáveis

Requisitos do plano:
1. Divida em etapas acionáveis
2. Indique a ordem recomendada
3. Marque dependências e pontos de verificação chave
4. Inclua métodos de verificação onde possível

Formato de saída:
Por favor, produza 3-5 etapas numeradas, cada uma tão específica quanto possível.
""",
)
```

Para conversas de acompanhamento:

```text
chat_with_agent(
  to_agent="strong_reasoner",
  text="Com base no plano anterior, refine ainda mais os pontos de verificação para as etapas 3 e 4. Ainda apenas forneça o plano -- não execute a tarefa.",
  session_id="<session_id_anterior>",
)
```

## O Que Fazer Após Receber o Plano

Trate a resposta do Agente mais forte como "entrada de plano de execução", não como "a tarefa já foi feita".

O que você deve fazer:
1. Destile as etapas verdadeiramente executáveis
2. Determine se ajustes são necessários para seu ambiente
3. Execute as etapas por conta própria
4. Se surgirem novas incertezas, continue refinando o plano

Não entregue o plano como está ao usuário como resultado final, a menos que o usuário tenha especificamente pedido o próprio plano.

## Padrões de Qualidade do Plano

Um plano qualificado deve atender pelo menos os seguintes critérios:
- Tem etapas claras, não conselhos vagos
- A ordem dos passos é clara
- Cada passo é uma ação executável
- Dependências-chave são identificadas
- Pontos de verificação necessários são incluídos
- Não delega secretamente "execução da tarefa" ao Agente consultado

Se o que você receber for conselho vago como "primeiro analise, depois implemente, depois teste", não é suficiente -- acompanhe para solicitar refinamento.

## Proteções de Comportamento

- Não transforme "por favor me ajude a planejar" em "por favor faça tudo por mim"
- Não solicite que o outro Agente execute código, comandos ou mudanças em seu nome
- Não aceite respostas que fornecem apenas direção sem etapas
- Não solicite um plano quando o objetivo da tarefa ainda não estiver claro
- Não pare de pensar após receber o plano -- ainda avalie-o em relação ao seu ambiente atual

## Princípio Final

Quando você não tiver um caminho de execução, solicite um plano primeiro.
O plano deve ser passo a passo, específico e acionável.
O Agente consultado é responsável por produzir o plano, não por executá-lo.
Após receber o plano, o solicitante o executa por conta própria.
