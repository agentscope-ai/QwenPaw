---
name: docx
description: "Use esta skill sempre que o usuário quiser criar, ler, editar ou manipular documentos Word (arquivos .docx). Gatilhos incluem: qualquer menção a \"documento Word\", \"word document\", \".docx\", ou solicitações para produzir documentos profissionais com formatação como sumários, títulos, números de página ou cabeçalhos. Use também ao extrair ou reorganizar conteúdo de arquivos .docx, inserir ou substituir imagens em documentos, realizar localizar-e-substituir em arquivos Word, trabalhar com alterações controladas ou comentários, ou converter conteúdo em um documento Word refinado. Se o usuário solicitar um \"relatório\", \"memorando\", \"carta\", \"modelo\" ou entregável semelhante como arquivo Word ou .docx, use esta skill. NÃO use para PDFs, planilhas, Google Docs ou tarefas de programação gerais não relacionadas à geração de documentos."
license: Proprietary. LICENSE.txt has complete terms
metadata:
  builtin_skill_version: "1.1"
---

> **Importante:** Todos os caminhos em `scripts/` são relativos ao diretório desta skill.
> Execute com: `cd {this_skill_dir} && python scripts/...`
> Ou use o parâmetro `cwd` do `execute_shell_command`.

# Criação, edição e análise de DOCX

## Pré-requisitos

- **docx** (`npm install -g docx`): criação de novos documentos
- **LibreOffice** (`soffice`): conversão `.doc` -> `.docx`, aceitação de alterações controladas e exportação para PDF
- **pandoc**: extração de texto
- **pdftoppm** (poppler-utils): fluxos de trabalho de documento para imagem
- Se `pdftoppm` não estiver disponível, um caminho de fallback em Python pode usar `pdf2image`.
- No Windows, as dependências devem estar instaladas e disponíveis no `PATH`; se ausentes, reporte o problema de dependência e pare (não continue tentando).

## Visão Geral

Um arquivo .docx é um arquivo ZIP contendo arquivos XML.

## Referência Rápida

| Tarefa | Abordagem |
|--------|-----------|
| Ler/analisar conteúdo | `pandoc` ou descompactar para XML bruto |
| Criar novo documento | Use `docx-js` - veja Criando Novos Documentos abaixo |
| Editar documento existente | Descompactar → editar XML → recompactar - veja Editando Documentos Existentes abaixo |

### Convertendo .doc para .docx

Arquivos `.doc` legados devem ser convertidos antes de editar:

```bash
python scripts/office/soffice.py --headless --convert-to docx document.doc
```

### Lendo Conteúdo

```bash
# Extração de texto com alterações controladas
pandoc --track-changes=all document.docx -o output.md

# Acesso ao XML bruto
python scripts/office/unpack.py document.docx unpacked/
```

### Convertendo para Imagens

```bash
python scripts/office/soffice.py --headless --convert-to pdf document.docx
pdftoppm -jpeg -r 150 document.pdf page
```

### Aceitando Alterações Controladas

Para produzir um documento limpo com todas as alterações controladas aceitas (requer LibreOffice):

```bash
python scripts/accept_changes.py input.docx output.docx
```

---

## Criando Novos Documentos

Gere arquivos .docx com JavaScript, depois valide. Instale: `npm install -g docx`

### Configuração
```javascript
const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, ImageRun,
        Header, Footer, AlignmentType, PageOrientation, LevelFormat, ExternalHyperlink,
        TableOfContents, HeadingLevel, BorderStyle, WidthType, ShadingType,
        VerticalAlign, PageNumber, PageBreak } = require('docx');

const doc = new Document({ sections: [{ children: [/* conteúdo */] }] });
Packer.toBuffer(doc).then(buffer => fs.writeFileSync("doc.docx", buffer));
```

### Validação
Após criar o arquivo, valide-o. Se a validação falhar, descompacte, corrija o XML e recompacte.
```bash
python scripts/office/validate.py doc.docx
```

### Tamanho de Página

```javascript
// CRÍTICO: docx-js usa A4 por padrão, não Letter EUA
// Sempre defina o tamanho de página explicitamente para resultados consistentes
sections: [{
  properties: {
    page: {
      size: {
        width: 12240,   // 8,5 polegadas em DXA
        height: 15840   // 11 polegadas em DXA
      },
      margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } // margens de 1 polegada
    }
  },
  children: [/* conteúdo */]
}]
```

**Tamanhos de página comuns (unidades DXA, 1440 DXA = 1 polegada):**

| Papel | Largura | Altura | Largura do Conteúdo (margens de 1") |
|-------|---------|--------|--------------------------------------|
| Letter EUA | 12.240 | 15.840 | 9.360 |
| A4 (padrão) | 11.906 | 16.838 | 9.026 |

**Orientação paisagem:** o docx-js troca largura/altura internamente, então passe as dimensões retrato e deixe-o tratar a troca:
```javascript
size: {
  width: 12240,   // Passe o lado CURTO como largura
  height: 15840,  // Passe o lado LONGO como altura
  orientation: PageOrientation.LANDSCAPE  // docx-js faz a troca no XML
},
// Largura do conteúdo = 15840 - margem esquerda - margem direita (usa o lado longo)
```

### Estilos (Substituir Títulos Embutidos)

Use Arial como fonte padrão (suporte universal). Mantenha títulos em preto para legibilidade.

```javascript
const doc = new Document({
  styles: {
    default: { document: { run: { font: "Arial", size: 24 } } }, // padrão 12pt
    paragraphStyles: [
      // IMPORTANTE: Use IDs exatos para substituir estilos embutidos
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 32, bold: true, font: "Arial" },
        paragraph: { spacing: { before: 240, after: 240 }, outlineLevel: 0 } }, // outlineLevel necessário para sumário
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, font: "Arial" },
        paragraph: { spacing: { before: 180, after: 180 }, outlineLevel: 1 } },
    ]
  },
  sections: [{
    children: [
      new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("Título")] }),
    ]
  }]
});
```

### Listas (NUNCA use marcadores unicode)

```javascript
// ❌ ERRADO - nunca insira caracteres de marcador manualmente
new Paragraph({ children: [new TextRun("• Item")] })  // ERRADO
new Paragraph({ children: [new TextRun("• Item")] })  // ERRADO

// ✅ CORRETO - use configuração de numeração com LevelFormat.BULLET
const doc = new Document({
  numbering: {
    config: [
      { reference: "bullets",
        levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
      { reference: "numbers",
        levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
    ]
  },
  sections: [{
    children: [
      new Paragraph({ numbering: { reference: "bullets", level: 0 },
        children: [new TextRun("Item com marcador")] }),
      new Paragraph({ numbering: { reference: "numbers", level: 0 },
        children: [new TextRun("Item numerado")] }),
    ]
  }]
});

// ⚠️ Cada reference cria numeração INDEPENDENTE
// Mesma reference = continua (1,2,3 depois 4,5,6)
// Reference diferente = reinicia (1,2,3 depois 1,2,3)
```

### Tabelas

**CRÍTICO: Tabelas precisam de larguras duplas** - defina tanto `columnWidths` na tabela QUANTO `width` em cada célula. Sem ambos, as tabelas são renderizadas incorretamente em algumas plataformas.

```javascript
// CRÍTICO: Sempre defina a largura da tabela para renderização consistente
// CRÍTICO: Use ShadingType.CLEAR (não SOLID) para evitar fundos pretos
const border = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const borders = { top: border, bottom: border, left: border, right: border };

new Table({
  width: { size: 9360, type: WidthType.DXA }, // Sempre use DXA (porcentagens quebram no Google Docs)
  columnWidths: [4680, 4680], // Deve somar à largura da tabela (DXA: 1440 = 1 polegada)
  rows: [
    new TableRow({
      children: [
        new TableCell({
          borders,
          width: { size: 4680, type: WidthType.DXA }, // Também defina em cada célula
          shading: { fill: "D5E8F0", type: ShadingType.CLEAR }, // CLEAR não SOLID
          margins: { top: 80, bottom: 80, left: 120, right: 120 }, // Preenchimento da célula (interno, não adicionado à largura)
          children: [new Paragraph({ children: [new TextRun("Célula")] })]
        })
      ]
    })
  ]
})
```

**Cálculo da largura da tabela:**

Sempre use `WidthType.DXA` — `WidthType.PERCENTAGE` quebra no Google Docs.

```javascript
// Largura da tabela = soma dos columnWidths = largura do conteúdo
// Letter EUA com margens de 1": 12240 - 2880 = 9360 DXA
width: { size: 9360, type: WidthType.DXA },
columnWidths: [7000, 2360]  // Deve somar à largura da tabela
```

**Regras de largura:**
- **Sempre use `WidthType.DXA`** — nunca `WidthType.PERCENTAGE` (incompatível com Google Docs)
- A largura da tabela deve ser igual à soma dos `columnWidths`
- O `width` da célula deve corresponder ao `columnWidth` correspondente
- As `margins` da célula são preenchimento interno - elas reduzem a área de conteúdo, não adicionam à largura da célula
- Para tabelas de largura total: use a largura do conteúdo (largura da página menos margens esquerda e direita)

### Imagens

```javascript
// CRÍTICO: o parâmetro type é OBRIGATÓRIO
new Paragraph({
  children: [new ImageRun({
    type: "png", // Obrigatório: png, jpg, jpeg, gif, bmp, svg
    data: fs.readFileSync("image.png"),
    transformation: { width: 200, height: 150 },
    altText: { title: "Título", description: "Desc", name: "Nome" } // Todos os três são obrigatórios
  })]
})
```

### Quebras de Página

```javascript
// CRÍTICO: PageBreak deve estar dentro de um Paragraph
new Paragraph({ children: [new PageBreak()] })

// Ou use pageBreakBefore
new Paragraph({ pageBreakBefore: true, children: [new TextRun("Nova página")] })
```

### Sumário

```javascript
// CRÍTICO: Os títulos devem usar apenas HeadingLevel - sem estilos personalizados
new TableOfContents("Sumário", { hyperlink: true, headingStyleRange: "1-3" })
```

### Cabeçalhos/Rodapés

```javascript
sections: [{
  properties: {
    page: { margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } // 1440 = 1 polegada
  },
  headers: {
    default: new Header({ children: [new Paragraph({ children: [new TextRun("Cabeçalho")] })] })
  },
  footers: {
    default: new Footer({ children: [new Paragraph({
      children: [new TextRun("Página "), new TextRun({ children: [PageNumber.CURRENT] })]
    })] })
  },
  children: [/* conteúdo */]
}]
```

### Regras Críticas para docx-js

- **Defina o tamanho de página explicitamente** - docx-js usa A4 por padrão; use Letter EUA (12240 x 15840 DXA) para documentos americanos
- **Paisagem: passe dimensões retrato** - docx-js troca largura/altura internamente; passe o lado curto como `width`, o lado longo como `height`, e defina `orientation: PageOrientation.LANDSCAPE`
- **Nunca use `\n`** - use elementos Paragraph separados
- **Nunca use marcadores unicode** - use `LevelFormat.BULLET` com configuração de numeração
- **PageBreak deve estar em Paragraph** - elemento independente cria XML inválido
- **ImageRun requer `type`** - sempre especifique png/jpg/etc
- **Sempre defina `width` da tabela com DXA** - nunca use `WidthType.PERCENTAGE` (quebra no Google Docs)
- **Tabelas precisam de larguras duplas** - array `columnWidths` E `width` da célula, ambos devem corresponder
- **Largura da tabela = soma dos columnWidths** - para DXA, garanta que somem exatamente
- **Sempre adicione margens às células** - use `margins: { top: 80, bottom: 80, left: 120, right: 120 }` para preenchimento legível
- **Use `ShadingType.CLEAR`** - nunca SOLID para sombreamento de tabela
- **Sumário requer apenas HeadingLevel** - sem estilos personalizados em parágrafos de título
- **Substitua estilos embutidos** - use IDs exatos: "Heading1", "Heading2", etc.
- **Inclua `outlineLevel`** - necessário para sumário (0 para H1, 1 para H2, etc.)

---

## Editando Documentos Existentes

**Siga todas as 3 etapas em ordem.**

### Etapa 1: Descompactar
```bash
python scripts/office/unpack.py document.docx unpacked/
```
Extrai XML, formata com indentação, mescla runs adjacentes e converte aspas tipográficas para entidades XML (`&#x201C;` etc.) para que sobrevivam à edição. Use `--merge-runs false` para pular a mesclagem de runs.

### Etapa 2: Editar XML

Edite os arquivos em `unpacked/word/`. Veja a Referência XML abaixo para padrões.

**Use "Claude" como autor** para alterações controladas e comentários, a menos que o usuário solicite explicitamente o uso de um nome diferente.

**Use a ferramenta Edit diretamente para substituição de strings. Não escreva scripts Python.** Scripts introduzem complexidade desnecessária. A ferramenta Edit mostra exatamente o que está sendo substituído.

**CRÍTICO: Use aspas tipográficas para novo conteúdo.** Ao adicionar texto com apóstrofos ou aspas, use entidades XML para produzir aspas tipográficas:
```xml
<!-- Use estas entidades para tipografia profissional -->
<w:t>Aqui&#x2019;s uma citação: &#x201C;Olá&#x201D;</w:t>
```
| Entidade | Caractere |
|----------|-----------|
| `&#x2018;` | ' (aspas simples esquerda) |
| `&#x2019;` | ' (aspas simples direita / apóstrofo) |
| `&#x201C;` | " (aspas duplas esquerda) |
| `&#x201D;` | " (aspas duplas direita) |

**Adicionando comentários:** Use `comment.py` para tratar boilerplate em múltiplos arquivos XML (o texto deve ser XML pré-escapado):
```bash
python scripts/comment.py unpacked/ 0 "Texto do comentário com &amp; e &#x2019;"
python scripts/comment.py unpacked/ 1 "Texto de resposta" --parent 0  # resposta ao comentário 0
python scripts/comment.py unpacked/ 0 "Texto" --author "Autor Personalizado"  # autor personalizado
```
Depois adicione marcadores ao document.xml (veja Comentários na Referência XML).

### Etapa 3: Recompactar
```bash
python scripts/office/pack.py unpacked/ output.docx --original document.docx
```
Valida com reparo automático, condensa XML e cria DOCX. Use `--validate false` para pular.

**O reparo automático corrigirá:**
- `durableId` >= 0x7FFFFFFF (regenera ID válido)
- `xml:space="preserve"` ausente em `<w:t>` com espaço em branco

**O reparo automático NÃO corrigirá:**
- XML malformado, aninhamento inválido de elementos, relacionamentos ausentes, violações de esquema

### Armadilhas Comuns

- **Substitua elementos `<w:r>` inteiros**: Ao adicionar alterações controladas, substitua o bloco `<w:r>...</w:r>` inteiro com `<w:del>...<w:ins>...` como elementos irmãos. Não injete tags de alteração controlada dentro de um run.
- **Preserve a formatação `<w:rPr>`**: Copie o bloco `<w:rPr>` do run original para seus runs de alteração controlada para manter negrito, tamanho de fonte, etc.

---

## Referência XML

### Conformidade com Esquema

- **Ordem dos elementos em `<w:pPr>`**: `<w:pStyle>`, `<w:numPr>`, `<w:spacing>`, `<w:ind>`, `<w:jc>`, `<w:rPr>` por último
- **Espaço em branco**: Adicione `xml:space="preserve"` a `<w:t>` com espaços iniciais/finais
- **RSIDs**: Devem ser hexadecimais de 8 dígitos (ex.: `00AB1234`)

### Alterações Controladas

**Inserção:**
```xml
<w:ins w:id="1" w:author="Claude" w:date="2025-01-01T00:00:00Z">
  <w:r><w:t>texto inserido</w:t></w:r>
</w:ins>
```

**Exclusão:**
```xml
<w:del w:id="2" w:author="Claude" w:date="2025-01-01T00:00:00Z">
  <w:r><w:delText>texto excluído</w:delText></w:r>
</w:del>
```

**Dentro de `<w:del>`**: Use `<w:delText>` em vez de `<w:t>`, e `<w:delInstrText>` em vez de `<w:instrText>`.

**Edições mínimas** - marque apenas o que muda:
```xml
<!-- Mudar "30 dias" para "60 dias" -->
<w:r><w:t>O prazo é </w:t></w:r>
<w:del w:id="1" w:author="Claude" w:date="...">
  <w:r><w:delText>30</w:delText></w:r>
</w:del>
<w:ins w:id="2" w:author="Claude" w:date="...">
  <w:r><w:t>60</w:t></w:r>
</w:ins>
<w:r><w:t> dias.</w:t></w:r>
```

**Excluindo parágrafos/itens de lista inteiros** - ao remover TODO o conteúdo de um parágrafo, marque também o marcador de parágrafo como excluído para que ele se mescle com o próximo parágrafo. Adicione `<w:del/>` dentro de `<w:pPr><w:rPr>`:
```xml
<w:p>
  <w:pPr>
    <w:numPr>...</w:numPr>  <!-- numeração de lista se presente -->
    <w:rPr>
      <w:del w:id="1" w:author="Claude" w:date="2025-01-01T00:00:00Z"/>
    </w:rPr>
  </w:pPr>
  <w:del w:id="2" w:author="Claude" w:date="2025-01-01T00:00:00Z">
    <w:r><w:delText>Todo o conteúdo do parágrafo sendo excluído...</w:delText></w:r>
  </w:del>
</w:p>
```
Sem o `<w:del/>` em `<w:pPr><w:rPr>`, aceitar as alterações deixa um parágrafo/item de lista vazio.

**Rejeitando inserção de outro autor** - aninhe a exclusão dentro da inserção deles:
```xml
<w:ins w:author="Jana" w:id="5">
  <w:del w:author="Claude" w:id="10">
    <w:r><w:delText>texto inserido por eles</w:delText></w:r>
  </w:del>
</w:ins>
```

**Restaurando exclusão de outro autor** - adicione inserção depois (não modifique a exclusão deles):
```xml
<w:del w:author="Jana" w:id="5">
  <w:r><w:delText>texto excluído</w:delText></w:r>
</w:del>
<w:ins w:author="Claude" w:id="10">
  <w:r><w:t>texto excluído</w:t></w:r>
</w:ins>
```

### Comentários

Após executar `comment.py` (veja Etapa 2), adicione marcadores ao document.xml. Para respostas, use a flag `--parent` e aninhe os marcadores dentro do pai.

**CRÍTICO: `<w:commentRangeStart>` e `<w:commentRangeEnd>` são irmãos de `<w:r>`, nunca dentro de `<w:r>`.**

```xml
<!-- Marcadores de comentário são filhos diretos de w:p, nunca dentro de w:r -->
<w:commentRangeStart w:id="0"/>
<w:del w:id="1" w:author="Claude" w:date="2025-01-01T00:00:00Z">
  <w:r><w:delText>excluído</w:delText></w:r>
</w:del>
<w:r><w:t> mais texto</w:t></w:r>
<w:commentRangeEnd w:id="0"/>
<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:commentReference w:id="0"/></w:r>

<!-- Comentário 0 com resposta 1 aninhada dentro -->
<w:commentRangeStart w:id="0"/>
  <w:commentRangeStart w:id="1"/>
  <w:r><w:t>texto</w:t></w:r>
  <w:commentRangeEnd w:id="1"/>
<w:commentRangeEnd w:id="0"/>
<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:commentReference w:id="0"/></w:r>
<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:commentReference w:id="1"/></w:r>
```

### Imagens

1. Adicione o arquivo de imagem em `word/media/`
2. Adicione o relacionamento em `word/_rels/document.xml.rels`:
```xml
<Relationship Id="rId5" Type=".../image" Target="media/image1.png"/>
```
3. Adicione o tipo de conteúdo em `[Content_Types].xml`:
```xml
<Default Extension="png" ContentType="image/png"/>
```
4. Referencie em document.xml:
```xml
<w:drawing>
  <wp:inline>
    <wp:extent cx="914400" cy="914400"/>  <!-- EMUs: 914400 = 1 polegada -->
    <a:graphic>
      <a:graphicData uri=".../picture">
        <pic:pic>
          <pic:blipFill><a:blip r:embed="rId5"/></pic:blipFill>
        </pic:pic>
      </a:graphicData>
    </a:graphic>
  </wp:inline>
</w:drawing>
```
