---
name: pdf
description: Use esta skill sempre que o usuário quiser fazer qualquer coisa com arquivos PDF. Isso inclui ler ou extrair texto/tabelas de PDFs, combinar ou mesclar múltiplos PDFs em um, dividir PDFs, girar páginas, adicionar marcas d'água, criar novos PDFs, preencher formulários PDF, criptografar/descriptografar PDFs, extrair imagens e fazer OCR em PDFs digitalizados para torná-los pesquisáveis. Se o usuário mencionar um arquivo .pdf ou pedir para produzir um, use esta skill.
license: Proprietary. LICENSE.txt has complete terms
metadata:
  builtin_skill_version: "1.1"
---

> **Importante:** Todos os caminhos em `scripts/` são relativos ao diretório desta skill.
> Execute com: `cd {this_skill_dir} && python scripts/...`
> Ou use o parâmetro `cwd` do `execute_shell_command`.

# Guia de Processamento de PDF

## Pré-requisitos

- **pypdf**: leitura e escrita de PDF central
- **pdfplumber**: extração de texto e tabelas
- **reportlab**: criação de PDF
- **pdftotext** (poppler-utils): extração de texto por linha de comando
- **pdftoppm** (poppler-utils): conversão de PDF para imagem
- **qpdf**: manipulação de PDF (mesclar, dividir, girar, descriptografar)

## Visão Geral

Este guia cobre operações essenciais de processamento de PDF usando bibliotecas Python e ferramentas de linha de comando. Para recursos avançados, bibliotecas JavaScript e exemplos detalhados, consulte REFERENCE.md. Se você precisar preencher um formulário PDF, leia FORMS.md e siga suas instruções.

## Início Rápido

```python
from pypdf import PdfReader, PdfWriter

# Ler um PDF
reader = PdfReader("document.pdf")
print(f"Páginas: {len(reader.pages)}")

# Extrair texto
text = ""
for page in reader.pages:
    text += page.extract_text()
```

## Bibliotecas Python

### pypdf - Operações Básicas

#### Mesclar PDFs
```python
from pypdf import PdfWriter, PdfReader

writer = PdfWriter()
for pdf_file in ["doc1.pdf", "doc2.pdf", "doc3.pdf"]:
    reader = PdfReader(pdf_file)
    for page in reader.pages:
        writer.add_page(page)

with open("merged.pdf", "wb") as output:
    writer.write(output)
```

#### Dividir PDF
```python
reader = PdfReader("input.pdf")
for i, page in enumerate(reader.pages):
    writer = PdfWriter()
    writer.add_page(page)
    with open(f"page_{i+1}.pdf", "wb") as output:
        writer.write(output)
```

#### Extrair Metadados
```python
reader = PdfReader("document.pdf")
meta = reader.metadata
print(f"Título: {meta.title}")
print(f"Autor: {meta.author}")
print(f"Assunto: {meta.subject}")
print(f"Criador: {meta.creator}")
```

#### Girar Páginas
```python
reader = PdfReader("input.pdf")
writer = PdfWriter()

page = reader.pages[0]
page.rotate(90)  # Girar 90 graus no sentido horário
writer.add_page(page)

with open("rotated.pdf", "wb") as output:
    writer.write(output)
```

### pdfplumber - Extração de Texto e Tabelas

#### Extrair Texto com Layout
```python
import pdfplumber

with pdfplumber.open("document.pdf") as pdf:
    for page in pdf.pages:
        text = page.extract_text()
        print(text)
```

#### Extrair Tabelas
```python
with pdfplumber.open("document.pdf") as pdf:
    for i, page in enumerate(pdf.pages):
        tables = page.extract_tables()
        for j, table in enumerate(tables):
            print(f"Tabela {j+1} na página {i+1}:")
            for row in table:
                print(row)
```

#### Extração Avançada de Tabelas
```python
import pandas as pd

with pdfplumber.open("document.pdf") as pdf:
    all_tables = []
    for page in pdf.pages:
        tables = page.extract_tables()
        for table in tables:
            if table:  # Verificar se a tabela não está vazia
                df = pd.DataFrame(table[1:], columns=table[0])
                all_tables.append(df)

# Combinar todas as tabelas
if all_tables:
    combined_df = pd.concat(all_tables, ignore_index=True)
    combined_df.to_excel("extracted_tables.xlsx", index=False)
```

### reportlab - Criar PDFs

#### Criação Básica de PDF
```python
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

c = canvas.Canvas("hello.pdf", pagesize=letter)
width, height = letter

# Adicionar texto
c.drawString(100, height - 100, "Olá Mundo!")
c.drawString(100, height - 120, "Este é um PDF criado com reportlab")

# Adicionar uma linha
c.line(100, height - 140, 400, height - 140)

# Salvar
c.save()
```

#### Criar PDF com Múltiplas Páginas
```python
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet

doc = SimpleDocTemplate("report.pdf", pagesize=letter)
styles = getSampleStyleSheet()
story = []

# Adicionar conteúdo
title = Paragraph("Título do Relatório", styles['Title'])
story.append(title)
story.append(Spacer(1, 12))

body = Paragraph("Este é o corpo do relatório. " * 20, styles['Normal'])
story.append(body)
story.append(PageBreak())

# Página 2
story.append(Paragraph("Página 2", styles['Heading1']))
story.append(Paragraph("Conteúdo para a página 2", styles['Normal']))

# Construir PDF
doc.build(story)
```

#### Subscritos e Superscritos

**IMPORTANTE**: Nunca use caracteres Unicode de subscrito/superscrito (₀₁₂₃₄₅₆₇₈₉, ⁰¹²³⁴⁵⁶⁷⁸⁹) em PDFs do ReportLab. As fontes embutidas não incluem esses glifos, fazendo com que sejam renderizados como caixas pretas sólidas.

Em vez disso, use as tags de marcação XML do ReportLab em objetos Paragraph:
```python
from reportlab.platypus import Paragraph
from reportlab.lib.styles import getSampleStyleSheet

styles = getSampleStyleSheet()

# Subscritos: use a tag <sub>
chemical = Paragraph("H<sub>2</sub>O", styles['Normal'])

# Superscritos: use a tag <super>
squared = Paragraph("x<super>2</super> + y<super>2</super>", styles['Normal'])
```

Para texto desenhado na tela (não objetos Paragraph), ajuste manualmente o tamanho da fonte e a posição em vez de usar subscritos/superscritos Unicode.

## Ferramentas de Linha de Comando

### pdftotext (poppler-utils)
```bash
# Extrair texto
pdftotext input.pdf output.txt

# Extrair texto preservando layout
pdftotext -layout input.pdf output.txt

# Extrair páginas específicas
pdftotext -f 1 -l 5 input.pdf output.txt  # Páginas 1-5
```

### qpdf
```bash
# Mesclar PDFs
qpdf --empty --pages file1.pdf file2.pdf -- merged.pdf

# Dividir páginas
qpdf input.pdf --pages . 1-5 -- pages1-5.pdf
qpdf input.pdf --pages . 6-10 -- pages6-10.pdf

# Girar páginas
qpdf input.pdf output.pdf --rotate=+90:1  # Girar página 1 em 90 graus

# Remover senha
qpdf --password=minhasenha --decrypt encrypted.pdf decrypted.pdf
```

### pdftk (se disponível)
```bash
# Mesclar
pdftk file1.pdf file2.pdf cat output merged.pdf

# Dividir
pdftk input.pdf burst

# Girar
pdftk input.pdf rotate 1east output rotated.pdf
```

## Tarefas Comuns

### Extrair Texto de PDFs Digitalizados
```python
# Requer: pip install pytesseract pdf2image
import pytesseract
from pdf2image import convert_from_path

# Converter PDF para imagens
images = convert_from_path('scanned.pdf')

# OCR em cada página
text = ""
for i, image in enumerate(images):
    text += f"Página {i+1}:\n"
    text += pytesseract.image_to_string(image)
    text += "\n\n"

print(text)
```

### Adicionar Marca d'Água
```python
from pypdf import PdfReader, PdfWriter

# Criar marca d'água (ou carregar existente)
watermark = PdfReader("watermark.pdf").pages[0]

# Aplicar a todas as páginas
reader = PdfReader("document.pdf")
writer = PdfWriter()

for page in reader.pages:
    page.merge_page(watermark)
    writer.add_page(page)

with open("watermarked.pdf", "wb") as output:
    writer.write(output)
```

### Extrair Imagens
```bash
# Usando pdfimages (poppler-utils)
pdfimages -j input.pdf output_prefix

# Extrai todas as imagens como output_prefix-000.jpg, output_prefix-001.jpg, etc.
```

### Proteção por Senha
```python
from pypdf import PdfReader, PdfWriter

reader = PdfReader("input.pdf")
writer = PdfWriter()

for page in reader.pages:
    writer.add_page(page)

# Adicionar senha
writer.encrypt("senhausuario", "senhaproprietario")

with open("encrypted.pdf", "wb") as output:
    writer.write(output)
```

## Referência Rápida

| Tarefa | Melhor Ferramenta | Comando/Código |
|--------|-------------------|----------------|
| Mesclar PDFs | pypdf | `writer.add_page(page)` |
| Dividir PDFs | pypdf | Uma página por arquivo |
| Extrair texto | pdfplumber | `page.extract_text()` |
| Extrair tabelas | pdfplumber | `page.extract_tables()` |
| Criar PDFs | reportlab | Canvas ou Platypus |
| Mesclar por linha de comando | qpdf | `qpdf --empty --pages ...` |
| OCR em PDFs digitalizados | pytesseract | Converter para imagem primeiro |
| Preencher formulários PDF | pdf-lib ou pypdf (veja FORMS.md) | Veja FORMS.md |

## Próximos Passos

- Para uso avançado do pypdfium2, veja REFERENCE.md
- Para bibliotecas JavaScript (pdf-lib), veja REFERENCE.md
- Se você precisar preencher um formulário PDF, siga as instruções em FORMS.md
- Para guias de solução de problemas, veja REFERENCE.md
