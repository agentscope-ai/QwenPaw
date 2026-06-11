---
name: pptx
description: "Use esta skill sempre que um arquivo .pptx estiver envolvido de qualquer forma — como entrada, saída ou ambos. Isso inclui: criar apresentações de slides, pitch decks ou apresentações; ler, analisar ou extrair texto de qualquer arquivo .pptx (mesmo que o conteúdo extraído seja usado em outro lugar, como em um e-mail ou resumo); editar, modificar ou atualizar apresentações existentes; combinar ou dividir arquivos de slides; trabalhar com modelos, layouts, notas do apresentador ou comentários. Ative sempre que o usuário mencionar \"deck\", \"slides\", \"apresentação\" ou referenciar um nome de arquivo .pptx, independentemente do que planeja fazer com o conteúdo. Se um arquivo .pptx precisar ser aberto, criado ou tocado, use esta skill."
license: Proprietary. LICENSE.txt has complete terms
metadata:
  builtin_skill_version: "1.1"
---

> **Importante:** Todos os caminhos em `scripts/` são relativos ao diretório desta skill.
> Execute com: `cd {this_skill_dir} && python scripts/...`
> Ou use o parâmetro `cwd` do `execute_shell_command`.

# Skill PPTX

## Pré-requisitos

- **markitdown[pptx]**: extração de texto de apresentações
- **Pillow**: geração de grade de miniaturas
- **pptxgenjs** (`npm install -g pptxgenjs`): criação de apresentações do zero
- **LibreOffice** (`soffice`): conversão de apresentação para PDF
- **pdftoppm** (poppler-utils): conversão de PDF para imagem para fluxos de trabalho visuais/miniaturas
- Se `pdftoppm` não estiver disponível, um caminho de fallback em Python pode usar `pdf2image`.
- No Windows, as dependências devem estar instaladas e disponíveis no `PATH`; se ausentes, reporte o problema de dependência e pare (não continue tentando).

## Referência Rápida

| Tarefa | Guia |
|--------|------|
| Ler/analisar conteúdo | `python -m markitdown presentation.pptx` |
| Editar ou criar a partir de modelo | Leia [editing.md](editing.md) |
| Criar do zero | Leia [pptxgenjs.md](pptxgenjs.md) |

---

## Lendo Conteúdo

```bash
# Extração de texto
python -m markitdown presentation.pptx

# Visão geral visual
python scripts/thumbnail.py presentation.pptx

# XML bruto
python scripts/office/unpack.py presentation.pptx unpacked/
```

---

## Fluxo de Edição

**Leia [editing.md](editing.md) para detalhes completos.**

1. Analise o modelo com `thumbnail.py`
2. Descompacte → manipule slides → edite conteúdo → limpe → recompacte

---

## Criando do Zero

**Leia [pptxgenjs.md](pptxgenjs.md) para detalhes completos.**

Use quando nenhum modelo ou apresentação de referência estiver disponível.

---

## Ideias de Design

**Não crie slides entediantes.** Bullets simples em fundo branco não impressionam ninguém. Considere ideias desta lista para cada slide.

### Antes de Começar

- **Escolha uma paleta de cores ousada e informada pelo conteúdo**: A paleta deve parecer projetada para ESTE tema. Se trocar suas cores em uma apresentação completamente diferente ainda "funcionar", você não fez escolhas específicas o suficiente.
- **Dominância sobre igualdade**: Uma cor deve dominar (60-70% do peso visual), com 1-2 tons de suporte e um acento nítido. Nunca dê a todas as cores peso igual.
- **Contraste escuro/claro**: Fundos escuros para slides de título + conclusão, claros para conteúdo (estrutura "sanduíche"). Ou comprometa-se com escuro em toda a apresentação para uma sensação premium.
- **Comprometa-se com um motivo visual**: Escolha UM elemento distintivo e repita-o — molduras de imagem arredondadas, ícones em círculos coloridos, bordas espessas de um lado. Mantenha em todos os slides.

### Paletas de Cores

Escolha cores que combinem com seu tema — não use azul genérico por padrão. Use estas paletas como inspiração:

| Tema | Primária | Secundária | Acento |
|------|----------|------------|--------|
| **Executivo Meia-Noite** | `1E2761` (marinho) | `CADCFC` (azul gelo) | `FFFFFF` (branco) |
| **Floresta & Musgo** | `2C5F2D` (floresta) | `97BC62` (musgo) | `F5F5F5` (creme) |
| **Energia Coral** | `F96167` (coral) | `F9E795` (dourado) | `2F3C7E` (marinho) |
| **Terracota Quente** | `B85042` (terracota) | `E7E8D1` (areia) | `A7BEAE` (sálvia) |
| **Gradiente Oceano** | `065A82` (azul profundo) | `1C7293` (azul-petróleo) | `21295C` (meia-noite) |
| **Minimal Carvão** | `36454F` (carvão) | `F2F2F2` (branco suave) | `212121` (preto) |
| **Confiança Teal** | `028090` (teal) | `00A896` (água-marinha) | `02C39A` (menta) |
| **Berry & Creme** | `6D2E46` (berry) | `A26769` (rosa empoeirado) | `ECE2D0` (creme) |
| **Calma Sálvia** | `84B59F` (sálvia) | `69A297` (eucalipto) | `50808E` (ardósia) |
| **Cherry Ousado** | `990011` (cereja) | `FCF6F5` (branco suave) | `2F3C7E` (marinho) |

### Para Cada Slide

**Todo slide precisa de um elemento visual** — imagem, gráfico, ícone ou forma. Slides somente com texto são esquecíveis.

**Opções de layout:**
- Duas colunas (texto à esquerda, ilustração à direita)
- Linhas de ícone + texto (ícone em círculo colorido, cabeçalho em negrito, descrição abaixo)
- Grade 2x2 ou 2x3 (imagem de um lado, grade de blocos de conteúdo do outro)
- Imagem com sangramento pela metade (lado esquerdo ou direito inteiro) com sobreposição de conteúdo

**Exibição de dados:**
- Chamadas de estatísticas grandes (números grandes 60-72pt com pequenos rótulos abaixo)
- Colunas de comparação (antes/depois, prós/contras, opções lado a lado)
- Linha do tempo ou fluxo de processo (etapas numeradas, setas)

**Polimento visual:**
- Ícones em pequenos círculos coloridos ao lado de cabeçalhos de seção
- Texto de acento em itálico para estatísticas-chave ou taglines

### Tipografia

**Escolha um par de fontes interessante** — não use Arial por padrão. Escolha uma fonte de cabeçalho com personalidade e combine com uma fonte de corpo limpa.

| Fonte de Cabeçalho | Fonte de Corpo |
|---------------------|----------------|
| Georgia | Calibri |
| Arial Black | Arial |
| Calibri | Calibri Light |
| Cambria | Calibri |
| Trebuchet MS | Calibri |
| Impact | Arial |
| Palatino | Garamond |
| Consolas | Calibri |

| Elemento | Tamanho |
|----------|---------|
| Título do slide | 36-44pt negrito |
| Cabeçalho de seção | 20-24pt negrito |
| Texto do corpo | 14-16pt |
| Legendas | 10-12pt suave |

### Espaçamento

- Margens mínimas de 0,5"
- 0,3-0,5" entre blocos de conteúdo
- Deixe espaço para respirar — não preencha cada centímetro

### Evite (Erros Comuns)

- **Não repita o mesmo layout** — varie colunas, cards e chamadas nos slides
- **Não centralize o texto do corpo** — alinhe à esquerda parágrafos e listas; centralize apenas títulos
- **Não economize no contraste de tamanho** — títulos precisam de 36pt+ para se destacar do corpo de 14-16pt
- **Não use azul por padrão** — escolha cores que reflitam o tema específico
- **Não misture espaçamento aleatoriamente** — escolha espaços de 0,3" ou 0,5" e use consistentemente
- **Não estilize um slide e deixe o resto simples** — comprometa-se totalmente ou mantenha simples em toda a apresentação
- **Não crie slides somente com texto** — adicione imagens, ícones, gráficos ou elementos visuais; evite título simples + bullets
- **Não esqueça o preenchimento da caixa de texto** — ao alinhar linhas ou formas com bordas de texto, defina `margin: 0` na caixa de texto ou desloque a forma para compensar o preenchimento
- **Não use elementos com baixo contraste** — ícones E texto precisam de forte contraste contra o fundo; evite texto claro em fundos claros ou texto escuro em fundos escuros
- **NUNCA use linhas de acento sob títulos** — estas são uma marca de slides gerados por IA; use espaço em branco ou cor de fundo em vez disso

---

## QA (Obrigatório)

**Assuma que há problemas. Seu trabalho é encontrá-los.**

Sua primeira renderização quase nunca está correta. Aborde o QA como uma caçada a bugs, não como uma etapa de confirmação. Se você não encontrou nenhum problema na primeira inspeção, não estava olhando com atenção suficiente.

### QA de Conteúdo

```bash
python -m markitdown output.pptx
```

Verifique conteúdo faltando, erros de digitação, ordem errada.

**Ao usar modelos, verifique se há texto de placeholder restante:**

```bash
python -m markitdown output.pptx | grep -iE "xxxx|lorem|ipsum|this.*(page|slide).*layout"
```

Se o grep retornar resultados, corrija-os antes de declarar sucesso.

### QA Visual

**⚠️ USE SUBAGENTES** — mesmo para 2-3 slides. Você ficou olhando para o código e verá o que espera, não o que está lá. Subagentes têm olhos frescos.

Converta slides para imagens (veja [Convertendo para Imagens](#convertendo-para-imagens)), depois use este prompt:

```
Inspecione visualmente estes slides. Assuma que há problemas — encontre-os.

Procure por:
- Elementos sobrepostos (texto através de formas, linhas sobre palavras, elementos empilhados)
- Texto transbordando ou cortado nas bordas/limites da caixa
- Linhas decorativas posicionadas para texto de uma linha, mas o título quebrou em duas linhas
- Citações de fonte ou rodapés colidindo com o conteúdo acima
- Elementos muito próximos (< 0,3" de espaço) ou cards/seções quase se tocando
- Espaços desiguais (grande área vazia em um lugar, apertado em outro)
- Margem insuficiente das bordas do slide (< 0,5")
- Colunas ou elementos similares não alinhados consistentemente
- Texto de baixo contraste (ex.: texto cinza claro em fundo cor creme)
- Ícones de baixo contraste (ex.: ícones escuros em fundos escuros sem círculo contrastante)
- Caixas de texto muito estreitas causando quebra excessiva
- Conteúdo de placeholder restante

Para cada slide, liste problemas ou áreas de preocupação, mesmo que menores.

Leia e analise estas imagens:
1. /caminho/para/slide-01.jpg (Esperado: [breve descrição])
2. /caminho/para/slide-02.jpg (Esperado: [breve descrição])

Reporte TODOS os problemas encontrados, incluindo os menores.
```

### Ciclo de Verificação

1. Gere slides → Converta para imagens → Inspecione
2. **Liste os problemas encontrados** (se nenhum encontrado, olhe novamente com mais atenção)
3. Corrija os problemas
4. **Re-verifique os slides afetados** — uma correção frequentemente cria outro problema
5. Repita até que uma passagem completa não revele novos problemas

**Não declare sucesso até completar pelo menos um ciclo de correção e verificação.**

---

## Convertendo para Imagens

Converta apresentações em imagens de slides individuais para inspeção visual:

```bash
python scripts/office/soffice.py --headless --convert-to pdf output.pptx
pdftoppm -jpeg -r 150 output.pdf slide
```

Isso cria `slide-01.jpg`, `slide-02.jpg`, etc.

Para re-renderizar slides específicos após correções:

```bash
pdftoppm -jpeg -r 150 -f N -l N output.pdf slide-fixed
```
