---
name: xlsx
description: "Use esta skill sempre que um arquivo de planilha for a entrada ou saída principal. Isso significa qualquer tarefa em que o usuário queira: abrir, ler, editar ou corrigir um arquivo .xlsx, .xlsm, .csv ou .tsv existente (ex.: adicionar colunas, calcular fórmulas, formatar, criar gráficos, limpar dados bagunçados); criar uma nova planilha do zero ou a partir de outras fontes de dados; ou converter entre formatos de arquivo tabulares. Ative especialmente quando o usuário referenciar um arquivo de planilha por nome ou caminho — mesmo casualmente (como \"o xlsx nos meus downloads\") — e quiser fazer algo com ele ou produzir algo a partir dele. Ative também para limpar ou reestruturar arquivos de dados tabulares bagunçados (linhas malformadas, cabeçalhos mal posicionados, dados inúteis) em planilhas adequadas. O produto final deve ser um arquivo de planilha. NÃO ative quando o produto final for um documento Word, relatório HTML, script Python independente, pipeline de banco de dados ou integração com Google Sheets API, mesmo que dados tabulares estejam envolvidos."
license: Proprietary. LICENSE.txt has complete terms
metadata:
  builtin_skill_version: "1.1"
---

> **Importante:** Todos os caminhos em `scripts/` são relativos ao diretório desta skill.
> Execute com: `cd {this_skill_dir} && python scripts/...`
> Ou use o parâmetro `cwd` do `execute_shell_command`.

# Requisitos para Saídas

## Todos os arquivos Excel

### Fonte Profissional
- Use uma fonte consistente e profissional (ex.: Arial, Times New Roman) para todos os produtos, a menos que o usuário instrua de outra forma

### Zero Erros de Fórmula
- Todo modelo Excel DEVE ser entregue com ZERO erros de fórmula (#REF!, #DIV/0!, #VALUE!, #N/A, #NAME?)

### Preservar Modelos Existentes (ao atualizar modelos)
- Estude e corresponda EXATAMENTE o formato, estilo e convenções existentes ao modificar arquivos
- Nunca imponha formatação padronizada em arquivos com padrões estabelecidos
- Convenções de modelos existentes SEMPRE substituem estas diretrizes

## Modelos Financeiros

### Padrões de Codificação por Cores
A menos que o usuário ou modelo existente especifique de outra forma

#### Convenções de Cores do Setor
- **Texto azul (RGB: 0,0,255)**: Entradas fixas e números que os usuários alterarão para cenários
- **Texto preto (RGB: 0,0,0)**: TODAS as fórmulas e cálculos
- **Texto verde (RGB: 0,128,0)**: Links que puxam de outras planilhas na mesma pasta de trabalho
- **Texto vermelho (RGB: 255,0,0)**: Links externos para outros arquivos
- **Fundo amarelo (RGB: 255,255,0)**: Premissas-chave que precisam de atenção ou células que precisam ser atualizadas

### Padrões de Formatação de Números

#### Regras de Formato Obrigatórias
- **Anos**: Formatar como strings de texto (ex.: "2024" não "2.024")
- **Moeda**: Use o formato $#.##0; SEMPRE especifique unidades nos cabeçalhos ("Receita ($mm)")
- **Zeros**: Use formatação de números para que todos os zeros apareçam como "-", incluindo porcentagens (ex.: "$#.##0;($#.##0);-")
- **Porcentagens**: Padrão para formato 0,0% (uma decimal)
- **Múltiplos**: Formatar como 0,0x para múltiplos de avaliação (EV/EBITDA, P/L)
- **Números negativos**: Use parênteses (123) não menos -123

### Regras de Construção de Fórmulas

#### Posicionamento de Premissas
- Coloque TODAS as premissas (taxas de crescimento, margens, múltiplos, etc.) em células de premissas separadas
- Use referências de células em vez de valores fixos nas fórmulas
- Exemplo: Use =B5*(1+$B$6) em vez de =B5*1,05

#### Prevenção de Erros de Fórmula
- Verifique se todas as referências de células estão corretas
- Verifique erros de deslocamento em intervalos
- Garanta fórmulas consistentes em todos os períodos de projeção
- Teste com casos extremos (valores zero, números negativos)
- Verifique referências circulares não intencionais

#### Requisitos de Documentação para Valores Fixos
- Comentário ou em células ao lado (se fim da tabela). Formato: "Fonte: [Sistema/Documento], [Data], [Referência Específica], [URL se aplicável]"
- Exemplos:
  - "Fonte: 10-K da Empresa, FY2024, Página 45, Nota de Receita, [URL SEC EDGAR]"
  - "Fonte: 10-Q da Empresa, Q2 2025, Exhibit 99.1, [URL SEC EDGAR]"
  - "Fonte: Bloomberg Terminal, 15/08/2025, AAPL US Equity"
  - "Fonte: FactSet, 20/08/2025, Tela de Estimativas de Consenso"

# Criação, edição e análise de XLSX

## Visão Geral

O usuário pode pedir para criar, editar ou analisar o conteúdo de um arquivo .xlsx. Você tem diferentes ferramentas e fluxos de trabalho disponíveis para diferentes tarefas.

## Pré-requisitos

- **openpyxl**: criação e edição de arquivos Excel
- **pandas**: análise de dados e operações em massa
- **LibreOffice** (`soffice`): recálculo de fórmulas via `scripts/recalc.py`
- `git` é opcional, mas melhora a saída de diff de redlining em fluxos de trabalho de validação.
- No Windows, as dependências devem estar instaladas e disponíveis no `PATH`; se ausentes, reporte o problema de dependência e pare (não continue tentando).

## Requisitos Importantes

**LibreOffice Necessário para Recálculo de Fórmulas**: Use `scripts/recalc.py` para recalcular valores de fórmulas. O script configura automaticamente o LibreOffice na primeira execução e trata ambientes em sandbox onde sockets Unix são restritos (via `scripts/office/soffice.py`).

## Lendo e analisando dados

### Análise de dados com pandas
Para análise de dados, visualização e operações básicas, use **pandas** que fornece capacidades poderosas de manipulação de dados:

```python
import pandas as pd

# Ler Excel
df = pd.read_excel('file.xlsx')  # Padrão: primeira planilha
all_sheets = pd.read_excel('file.xlsx', sheet_name=None)  # Todas as planilhas como dicionário

# Analisar
df.head()      # Prévia dos dados
df.info()      # Info das colunas
df.describe()  # Estatísticas

# Escrever Excel
df.to_excel('output.xlsx', index=False)
```

## Fluxos de Trabalho com Arquivos Excel

## CRÍTICO: Use Fórmulas, Não Valores Fixos

**Sempre use fórmulas Excel em vez de calcular valores em Python e fixá-los.** Isso garante que a planilha permaneça dinâmica e atualizável.

### ❌ ERRADO - Fixar Valores Calculados
```python
# Ruim: Calcular em Python e fixar o resultado
total = df['Vendas'].sum()
sheet['B10'] = total  # Fixa 5000

# Ruim: Calcular taxa de crescimento em Python
growth = (df.iloc[-1]['Receita'] - df.iloc[0]['Receita']) / df.iloc[0]['Receita']
sheet['C5'] = growth  # Fixa 0,15

# Ruim: Cálculo Python para média
avg = sum(values) / len(values)
sheet['D20'] = avg  # Fixa 42,5
```

### ✅ CORRETO - Usar Fórmulas Excel
```python
# Bom: Deixar o Excel calcular a soma
sheet['B10'] = '=SUM(B2:B9)'

# Bom: Taxa de crescimento como fórmula Excel
sheet['C5'] = '=(C4-C2)/C2'

# Bom: Média usando função Excel
sheet['D20'] = '=AVERAGE(D2:D19)'
```

Isso se aplica a TODOS os cálculos - totais, porcentagens, razões, diferenças, etc. A planilha deve poder recalcular quando os dados de origem mudarem.

## Fluxo de Trabalho Comum
1. **Escolher ferramenta**: pandas para dados, openpyxl para fórmulas/formatação
2. **Criar/Carregar**: Criar nova pasta de trabalho ou carregar arquivo existente
3. **Modificar**: Adicionar/editar dados, fórmulas e formatação
4. **Salvar**: Gravar no arquivo
5. **Recalcular fórmulas (OBRIGATÓRIO SE USAR FÓRMULAS)**: Use o script scripts/recalc.py
   ```bash
   python scripts/recalc.py output.xlsx
   ```
6. **Verificar e corrigir erros**: 
   - O script retorna JSON com detalhes do erro
   - Se `status` for `errors_found`, verifique `error_summary` para tipos e locais específicos de erros
   - Corrija os erros identificados e recalcule novamente
   - Erros comuns a corrigir:
     - `#REF!`: Referências de células inválidas
     - `#DIV/0!`: Divisão por zero
     - `#VALUE!`: Tipo de dado errado na fórmula
     - `#NAME?`: Nome de fórmula não reconhecido

### Criando novos arquivos Excel

```python
# Usando openpyxl para fórmulas e formatação
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

wb = Workbook()
sheet = wb.active

# Adicionar dados
sheet['A1'] = 'Olá'
sheet['B1'] = 'Mundo'
sheet.append(['Linha', 'de', 'dados'])

# Adicionar fórmula
sheet['B2'] = '=SUM(A1:A10)'

# Formatação
sheet['A1'].font = Font(bold=True, color='FF0000')
sheet['A1'].fill = PatternFill('solid', start_color='FFFF00')
sheet['A1'].alignment = Alignment(horizontal='center')

# Largura da coluna
sheet.column_dimensions['A'].width = 20

wb.save('output.xlsx')
```

### Editando arquivos Excel existentes

```python
# Usando openpyxl para preservar fórmulas e formatação
from openpyxl import load_workbook

# Carregar arquivo existente
wb = load_workbook('existing.xlsx')
sheet = wb.active  # ou wb['NomePlanilha'] para planilha específica

# Trabalhar com múltiplas planilhas
for sheet_name in wb.sheetnames:
    sheet = wb[sheet_name]
    print(f"Planilha: {sheet_name}")

# Modificar células
sheet['A1'] = 'Novo Valor'
sheet.insert_rows(2)  # Inserir linha na posição 2
sheet.delete_cols(3)  # Excluir coluna 3

# Adicionar nova planilha
new_sheet = wb.create_sheet('NovaPlanilha')
new_sheet['A1'] = 'Dados'

wb.save('modified.xlsx')
```

## Recalculando fórmulas

Arquivos Excel criados ou modificados pelo openpyxl contêm fórmulas como strings, mas não valores calculados. Use o script `scripts/recalc.py` fornecido para recalcular fórmulas:

```bash
python scripts/recalc.py <arquivo_excel> [timeout_segundos]
```

Exemplo:
```bash
python scripts/recalc.py output.xlsx 30
```

O script:
- Configura automaticamente a macro do LibreOffice na primeira execução
- Recalcula todas as fórmulas em todas as planilhas
- Verifica TODAS as células em busca de erros Excel (#REF!, #DIV/0!, etc.)
- Retorna JSON com locais e contagens detalhados de erros
- Funciona no Linux, macOS e Windows

## Lista de Verificação de Fórmulas

Verificações rápidas para garantir que as fórmulas funcionem corretamente:

### Verificação Essencial
- [ ] **Teste 2-3 referências de amostra**: Verifique se puxam os valores corretos antes de construir o modelo completo
- [ ] **Mapeamento de colunas**: Confirme as colunas Excel correspondentes (ex.: coluna 64 = BL, não BK)
- [ ] **Deslocamento de linhas**: Lembre-se que as linhas do Excel são indexadas a partir de 1 (linha 5 do DataFrame = linha 6 do Excel)

### Armadilhas Comuns
- [ ] **Tratamento de NaN**: Verifique valores nulos com `pd.notna()`
- [ ] **Colunas à extrema direita**: Dados FY frequentemente nas colunas 50+
- [ ] **Múltiplas correspondências**: Pesquise todas as ocorrências, não apenas a primeira
- [ ] **Divisão por zero**: Verifique denominadores antes de usar `/` em fórmulas (#DIV/0!)
- [ ] **Referências erradas**: Verifique se todas as referências de células apontam para as células pretendidas (#REF!)
- [ ] **Referências entre planilhas**: Use o formato correto (Planilha1!A1) para vincular planilhas

### Estratégia de Teste de Fórmulas
- [ ] **Comece pequeno**: Teste fórmulas em 2-3 células antes de aplicar amplamente
- [ ] **Verifique dependências**: Confira se todas as células referenciadas nas fórmulas existem
- [ ] **Teste casos extremos**: Inclua zero, negativo e valores muito grandes

### Interpretando a Saída do scripts/recalc.py
O script retorna JSON com detalhes de erros:
```json
{
  "status": "success",           // ou "errors_found"
  "total_errors": 0,              // Total de erros
  "total_formulas": 42,           // Número de fórmulas no arquivo
  "error_summary": {              // Presente apenas se houver erros
    "#REF!": {
      "count": 2,
      "locations": ["Sheet1!B5", "Sheet1!C10"]
    }
  }
}
```

## Boas Práticas

### Seleção de Biblioteca
- **pandas**: Melhor para análise de dados, operações em massa e exportação simples de dados
- **openpyxl**: Melhor para formatação complexa, fórmulas e recursos específicos do Excel

### Trabalhando com openpyxl
- Índices de células são baseados em 1 (row=1, column=1 refere-se à célula A1)
- Use `data_only=True` para ler valores calculados: `load_workbook('file.xlsx', data_only=True)`
- **Aviso**: Se aberto com `data_only=True` e salvo, as fórmulas são substituídas por valores e permanentemente perdidas
- Para arquivos grandes: Use `read_only=True` para leitura ou `write_only=True` para escrita
- Fórmulas são preservadas, mas não avaliadas - use scripts/recalc.py para atualizar valores

### Trabalhando com pandas
- Especifique tipos de dados para evitar problemas de inferência: `pd.read_excel('file.xlsx', dtype={'id': str})`
- Para arquivos grandes, leia colunas específicas: `pd.read_excel('file.xlsx', usecols=['A', 'C', 'E'])`
- Trate datas corretamente: `pd.read_excel('file.xlsx', parse_dates=['coluna_data'])`

## Diretrizes de Estilo de Código
**IMPORTANTE**: Ao gerar código Python para operações Excel:
- Escreva código Python mínimo e conciso sem comentários desnecessários
- Evite nomes de variáveis verbosos e operações redundantes
- Evite declarações print desnecessárias

**Para os próprios arquivos Excel**:
- Adicione comentários às células com fórmulas complexas ou premissas importantes
- Documente fontes de dados para valores fixos
- Inclua notas para cálculos-chave e seções do modelo
