---
name: file_reader
description: "Leia e resuma apenas tipos de arquivo baseados em texto. Prefira read_file para formatos de texto; use execute_shell_command para detecção de tipo quando necessário. PDF/Office/imagens/arquivos compactados são tratados por outras skills."
metadata:
  builtin_skill_version: "1.2"
  qwenpaw:
    emoji: "📄"
    requires: {}
---
# Caixa de Ferramentas para Leitura de Arquivos

Use esta skill quando o usuário pedir para ler ou resumir arquivos de texto locais. PDFs, documentos Office, imagens, áudio e vídeo estão fora do escopo desta skill e devem ser tratados pelas skills/ferramentas dedicadas.

## Verificação Rápida de Tipo

Use uma sondagem de tipo antes de ler:

```bash
file -b --mime-type "/caminho/para/arquivo"
```

Se o arquivo for grande, evite despejar todo o conteúdo; extraia uma pequena porção relevante e resuma.

## Arquivos Baseados em Texto (use read_file)

Preferido para: `.txt`, `.md`, `.json`, `.yaml/.yml`, `.csv/.tsv`, `.log`, `.sql`, `ini`, `toml`, `py`, `js`, `html`, `xml` código-fonte.

Passos:

1. Use `read_file` para buscar o conteúdo.
2. Resuma as seções principais ou mostre a fatia relevante solicitada pelo usuário.
3. Para JSON/YAML, liste as chaves de nível superior e campos importantes.
4. Para CSV/TSV, mostre o cabeçalho + primeiras linhas, depois resuma as colunas.

## Logs Grandes

Se o arquivo for enorme, use uma janela tail:

```bash
tail -n 200 "/caminho/para/arquivo.log"
```

Resuma os últimos erros/avisos e padrões notáveis.

## Fora do Escopo

Não trate o seguinte nesta skill (eles são cobertos por outras skills):

- PDF
- Office (docx/xlsx/pptx)
- Imagens
- Áudio/Vídeo

## Segurança e Comportamento

- Nunca execute arquivos não confiáveis.
- Prefira ler a menor porção necessária.
- Se uma ferramenta estiver faltando, explique a limitação e peça ao usuário um formato alternativo.
