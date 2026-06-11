---
name: make-skill
description: "Use esta skill ao sedimentar uma sessão em uma skill reutilizável do workspace. Ativa quando o usuário quer transformar a conversa atual, fluxo de trabalho ou caminho de solução de problemas em um SKILL.md. Frases como 'transforme isso em uma skill', 'lembre como fiz X', 'salve este fluxo', 'crie uma skill disso' e qualquer invocação /make-skill <foco> devem acionar esta skill."
metadata:
  builtin_skill_version: "1.1"
  qwenpaw:
    emoji: "✍️"
    requires: {}
---

<!--
  Inspirado na skill `skill-creator` da Anthropic (especialmente a parte de "criar uma skill").
  Reescrito para o QwenPaw.
  Crédito: https://github.com/anthropics/skills/blob/main/skill-creator/SKILL.md
-->

# Criar Skill

Transforme a sessão atual em uma skill reutilizável do workspace.

Você orquestra um fluxo em duas fases:

* **Fase A.** Proponha um plano compacto, ceda a vez para aprovação do usuário.
* **Fase B.** Após aprovação, escreva o corpo completo do SKILL.md baseado NESTA conversa, depois persista via `materialize_skill`.

**Não** chame `write_file` para criar o SKILL.md ou quaisquer arquivos auxiliares (scripts, JSON, etc.) diretamente. Toda criação inicial de arquivos deve passar por `materialize_skill` (via os parâmetros `body` e `extra_files`), que executa o scanner de segurança e escreve o manifesto atomicamente. Após criação bem-sucedida, use `edit_file` para modificar arquivos existentes se necessário.

## Passo 0. Determinar o foco e derivar um nome de skill

### 0a. Determinar o foco

Dois caminhos de invocação:

* `/make-skill <foco>`. O foco segue o comando literalmente.
* Linguagem natural ("transforme isso em uma skill", "salve este fluxo", "把刚才的 X 流程变成 skill"). Derive uma frase de foco curta do tópico da conversa que o usuário quer capturar. Se ambíguo, peça uma esclarecimento de uma linha primeiro.

### 0b. Derivar o nome da skill

Derive o nome da skill do foco com **esta regra exata**:

```
skill_name = "-".join(foco.split())
```

Espaço interno (espaço, tab, espaço de largura total, múltiplos espaços) colapsa para um único `-`. Outros caracteres permanecem como estão.

Exemplos:

* `culinária` → `culinária`
* `depurar imagem` → `depurar-imagem`
* `烹饪 食谱` → `烹饪-食谱`
* `Preço Ação` → `Preço-Ação` (capitalização preservada)

Use este `skill_name` consistentemente como `plan.name` no Passo 1 e como argumento `name=` para `materialize_skill` no Passo 3.

## Passo 1. Propor o plano e ceder para aprovação

Chame `create_plan` com **todos os quatro argumentos obrigatórios** (`name`, `description`, `expected_outcome`, `subtasks`):

* **`name`**: o `skill_name` normalizado do Passo 0.
* **`description`**: uma prévia COMPACTA que o usuário revisa. Duas partes:
  * **Parte 1: Prévia do gatilho.** 2 a 4 frases, linguagem simples. Cubra todos os três:
    * **Objetivo.** O resultado final que esta skill produz.
    * **Gatilho.** Formulações e contextos do usuário que devem invocá-la. Seja um pouco insistente com sinônimos.
    * **E/S.** Quais entradas espera, quais saídas produz.
    Ainda não está no formato frontmatter do SKILL.md; isso é destilado depois.
  * **Parte 2: Esboço de passos e plano de lote.** Duas partes:
    * **Esboço de passos.** Lista numerada, uma frase curta de verbo por linha. Sem detalhe por passo, sem parâmetros, sem tratamento de erros, sem sub-bullets, sem sub-títulos `##`. Apenas a forma, para que o usuário possa julgar ordenação e escopo. Derive os nomes dos passos do que realmente aconteceu NESTA conversa. Não fabrique; omita qualquer coisa não fundamentada na conversa.
    * **Plano de lote.** Descreva brevemente como os passos acima serão organizados em arquivos JSON de `run_tool_batch`.
* **`expected_outcome`** (nível do plano, OBRIGATÓRIO — distinto do `expected_outcome` da subtarefa): uma frase concreta sobre como é o sucesso para toda a criação da skill. Use a string literal `"Uma nova skill do workspace <skill_name> é criada, habilitada e invocável via /<skill_name>."` com `<skill_name>` substituído.
* **`subtasks`**: uma lista com uma única subtarefa:
  * `name`: `"Escrever e materializar skill"`
  * `description`: `"Escrever o corpo do SKILL.md e chamar materialize_skill."`
  * `expected_outcome`: `"Skill criada e visível via /skills."`

Escreva `plan.name` e `plan.description` no mesmo idioma das mensagens recentes do usuário. `expected_outcome` pode permanecer em inglês.

Após `create_plan` retornar, **ceda a vez**. O usuário responderá aprovando, refinando ou cancelando.

## Passo 2. Após aprovação, escreva o corpo do SKILL.md

Uma vez que o usuário aprove o plano e a única subtarefa esteja em andamento, escreva um corpo SKILL.md completo e detalhado fundamentado NESTA conversa.

Estilo de escrita:

* Use a forma imperativa.
* Explique POR QUE instruções não óbvias importam. Evite `DEVE`s pesados.
* Comprimento alvo do corpo abaixo de ~500 linhas. Se estiver se aproximando, divida em sub-seções com ponteiros claros.

## Passo 3. Persistir via `materialize_skill`

Chame `materialize_skill` com:

* **`name`**: o mesmo `skill_name` normalizado que você usou para `plan.name`.
* **`description`**: uma string `Use esta skill quando …` destilada de `plan.description` Parte 1. ≤ 200 caracteres.
* **`body`**: o corpo SKILL.md revisado. Sem frontmatter; a ferramenta renderiza isso.
* **`extra_files`** (opcional): se o Passo 2 produziu arquivos JSON de lote ou outros arquivos auxiliares, bundle-os aqui.

**Não** chame `write_file` para criar SKILL.md ou arquivos auxiliares diretamente. Toda criação inicial deve passar por `materialize_skill`. Após criação, use `edit_file` para modificar arquivos existentes.

## Passo 4. Tratar resposta de `materialize_skill`

### 4a. Verificar referências `$steps` (quando JSON de lote é incluído)

Quando `extra_files` contém arquivos JSON de `run_tool_batch`, `materialize_skill` analisa automaticamente todas as referências `${steps.<índice>.<caminho>}` e lista cada referência em sua resposta.

**Você deve verificar a lista de referências retornada e verificar que cada campo referenciado realmente existe.**

### 4b. Executar o lote de teste (quando JSON de lote é incluído)

Após a verificação de referências passar, tente executar o lote uma vez com argumentos de amostra.

### 4c. Conflito (nome de skill já em uso)

Recupere automaticamente escolhendo um novo nome (por exemplo, com `-v2` ou sufixo de timestamp).

## Passo 5. Finalizar

Uma vez que `materialize_skill` retorne sucesso:

1. Chame `finish_subtask` para a única subtarefa.
2. Chame `finish_plan` com `state="completed"`.
3. Informe ao usuário que a nova skill foi criada e habilitada, e que pode ser invocada via `/<skill_name>`.
