---
name: xlsx
description: "当电子表格文件是主要输入或输出时使用此技能。这意味着用户想要：打开、读取、编辑或修复现有的 .xlsx、.xlsm、.csv 或 .tsv 文件（例如添加列、计算公式、格式化、制图、清理混乱数据）；从头创建新的电子表格或从其他数据源创建；或在表格文件格式之间进行转换。当用户通过名称或路径引用电子表格文件时特别触发——即使是随意提及（如\"我下载目录里的 xlsx\"）——并且想对其进行操作或从中生成内容。也适用于将混乱的表格数据文件（格式错误的行、错位的表头、垃圾数据）清理或重构为规范的电子表格。交付物必须是电子表格文件。当主要交付物是 Word 文档、HTML 报告、独立 Python 脚本、数据库管道或 Google Sheets API 集成时不触发，即使涉及表格数据也不触发。"
license: Proprietary. LICENSE.txt has complete terms
metadata:
  builtin_skill_version: "1.1"
---

> **重要说明：** 所有 `scripts/` 路径均相对于此技能目录。
> 运行方式：`cd {this_skill_dir} && python scripts/...`
> 或使用 `execute_shell_command` 的 `cwd` 参数。

# 输出要求

## 所有 Excel 文件

### 专业字体
- 除非用户另有指示，所有交付物应使用统一的专业字体（如 Arial、Times New Roman）

### 零公式错误
- 每个 Excel 模型必须以零公式错误交付（#REF!、#DIV/0!、#VALUE!、#N/A、#NAME?）

### 保留现有模板（更新模板时）
- 修改文件时需仔细研究并完全匹配现有的格式、样式和约定
- 切勿对已有既定模式的文件强加标准化格式
- 现有模板约定始终优先于本指南

## 财务模型

### 颜色编码标准
除非用户或现有模板另有规定

#### 行业标准颜色约定
- **蓝色文本 (RGB: 0,0,255)**：硬编码输入，以及用户会为不同情景更改的数字
- **黑色文本 (RGB: 0,0,0)**：所有公式和计算
- **绿色文本 (RGB: 0,128,0)**：从同一工作簿中其他工作表拉取的链接
- **红色文本 (RGB: 255,0,0)**：指向其他文件的外部链接
- **黄色背景 (RGB: 255,255,0)**：需要关注的关键假设或需要更新的单元格

### 数字格式标准

#### 必需的格式规则
- **年份**：格式化为文本字符串（例如 "2024" 而非 "2,024"）
- **货币**：使用 $#,##0 格式；始终在表头中注明单位（"Revenue ($mm)"）
- **零值**：使用数字格式将所有零值显示为 "-"，包括百分比（例如 "$#,##0;($#,##0);-"）
- **百分比**：默认使用 0.0% 格式（一位小数）
- **倍数**：估值倍数使用 0.0x 格式（EV/EBITDA、P/E）
- **负数**：使用括号 (123) 而非负号 -123

### 公式构建规则

#### 假设放置
- 将所有假设（增长率、利润率、倍数等）放在单独的假设单元格中
- 在公式中使用单元格引用而非硬编码值
- 示例：使用 =B5*(1+$B$6) 而非 =B5*1.05

#### 公式错误预防
- 验证所有单元格引用是否正确
- 检查范围中的偏移错误
- 确保所有预测期间的公式一致
- 使用边界情况测试（零值、负数）
- 验证没有非预期的循环引用

#### 硬编码值的文档要求
- 在注释中或旁边的单元格中（如果在表格末尾）添加说明。格式："Source: [系统/文档], [日期], [具体引用], [URL（如适用）]"
- 示例：
  - "Source: Company 10-K, FY2024, Page 45, Revenue Note, [SEC EDGAR URL]"
  - "Source: Company 10-Q, Q2 2025, Exhibit 99.1, [SEC EDGAR URL]"
  - "Source: Bloomberg Terminal, 8/15/2025, AAPL US Equity"
  - "Source: FactSet, 8/20/2025, Consensus Estimates Screen"

# XLSX 创建、编辑和分析

## 概述

用户可能要求您创建、编辑或分析 .xlsx 文件的内容。您有不同的工具和工作流可用于不同的任务。

## 前置条件

- **openpyxl**：Excel 文件创建和编辑
- **pandas**：数据分析和批量操作
- **LibreOffice** (`soffice`)：通过 `scripts/recalc.py` 进行公式重新计算
- `git` 是可选的，但可以改善验证工作流中的红线差异输出。
- 在 Windows 上，依赖项必须已安装并在 `PATH` 中可用；如果缺失，报告依赖问题并停止（不要反复重试）。

## 重要要求

**公式重新计算需要 LibreOffice**：使用 `scripts/recalc.py` 重新计算公式值。该脚本在首次运行时自动配置 LibreOffice，并处理 Unix 套接字受限的沙箱环境（通过 `scripts/office/soffice.py`）。

## 读取和分析数据

### 使用 pandas 进行数据分析
对于数据分析、可视化和基本操作，使用 **pandas** 提供的强大数据操作功能：

```python
import pandas as pd

# 读取 Excel
df = pd.read_excel('file.xlsx')  # Default: first sheet
all_sheets = pd.read_excel('file.xlsx', sheet_name=None)  # All sheets as dict

# 分析数据
df.head()      # Preview data
df.info()      # Column info
df.describe()  # Statistics

# 写入 Excel
df.to_excel('output.xlsx', index=False)
```

## Excel 文件工作流

## 关键要求：使用公式，而非硬编码值

**始终使用 Excel 公式，而不是在 Python 中计算值后硬编码。** 这确保电子表格保持动态且可更新。

### 错误做法 - 硬编码计算值
```python
# 错误做法：在 Python 中计算并硬编码结果
total = df['Sales'].sum()
sheet['B10'] = total  # Hardcodes 5000

# 错误做法：在 Python 中计算增长率
growth = (df.iloc[-1]['Revenue'] - df.iloc[0]['Revenue']) / df.iloc[0]['Revenue']
sheet['C5'] = growth  # Hardcodes 0.15

# 错误做法：在 Python 中计算平均值
avg = sum(values) / len(values)
sheet['D20'] = avg  # Hardcodes 42.5
```

### 正确做法 - 使用 Excel 公式
```python
# 正确做法：让 Excel 自行计算总和
sheet['B10'] = '=SUM(B2:B9)'

# 正确做法：将增长率写成 Excel 公式
sheet['C5'] = '=(C4-C2)/C2'

# 正确做法：使用 Excel 函数计算平均值
sheet['D20'] = '=AVERAGE(D2:D19)'
```

这适用于所有计算——总计、百分比、比率、差值等。电子表格应能在源数据更改时重新计算。

## 通用工作流
1. **选择工具**：pandas 用于数据处理，openpyxl 用于公式/格式化
2. **创建/加载**：创建新工作簿或加载现有文件
3. **修改**：添加/编辑数据、公式和格式
4. **保存**：写入文件
5. **重新计算公式（使用公式时为必需步骤）**：使用 scripts/recalc.py 脚本
   ```bash
   python scripts/recalc.py output.xlsx
   ```
6. **验证并修复任何错误**：
   - 脚本返回包含错误详情的 JSON
   - 如果 `status` 为 `errors_found`，检查 `error_summary` 获取具体错误类型和位置
   - 修复已识别的错误并再次重新计算
   - 常见需修复的错误：
     - `#REF!`：无效的单元格引用
     - `#DIV/0!`：除以零
     - `#VALUE!`：公式中的数据类型错误
     - `#NAME?`：无法识别的公式名称

### 创建新的 Excel 文件

```python
# 使用 openpyxl 处理公式和格式
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

wb = Workbook()
sheet = wb.active

# 添加数据
sheet['A1'] = 'Hello'
sheet['B1'] = 'World'
sheet.append(['Row', 'of', 'data'])

# 添加公式
sheet['B2'] = '=SUM(A1:A10)'

# 设置格式
sheet['A1'].font = Font(bold=True, color='FF0000')
sheet['A1'].fill = PatternFill('solid', start_color='FFFF00')
sheet['A1'].alignment = Alignment(horizontal='center')

# 列宽
sheet.column_dimensions['A'].width = 20

wb.save('output.xlsx')
```

### 编辑现有 Excel 文件

```python
# 使用 openpyxl 保留公式和格式
from openpyxl import load_workbook

# 加载现有文件
wb = load_workbook('existing.xlsx')
sheet = wb.active  # or wb['SheetName'] for specific sheet

# 处理多个工作表
for sheet_name in wb.sheetnames:
    sheet = wb[sheet_name]
    print(f"Sheet: {sheet_name}")

# 修改单元格
sheet['A1'] = 'New Value'
sheet.insert_rows(2)  # Insert row at position 2
sheet.delete_cols(3)  # Delete column 3

# 新增工作表
new_sheet = wb.create_sheet('NewSheet')
new_sheet['A1'] = 'Data'

wb.save('modified.xlsx')
```

## 重新计算公式

通过 openpyxl 创建或修改的 Excel 文件包含公式字符串但不包含计算值。使用提供的 `scripts/recalc.py` 脚本重新计算公式：

```bash
python scripts/recalc.py <excel_file> [timeout_seconds]
```

示例：
```bash
python scripts/recalc.py output.xlsx 30
```

该脚本：
- 首次运行时自动设置 LibreOffice 宏
- 重新计算所有工作表中的所有公式
- 扫描所有单元格以查找 Excel 错误（#REF!、#DIV/0! 等）
- 返回包含详细错误位置和计数的 JSON
- 适用于 Linux、macOS 和 Windows

## 公式验证清单

确保公式正常工作的快速检查：

### 基本验证
- [ ] **测试 2-3 个示例引用**：在构建完整模型之前验证它们是否获取了正确的值
- [ ] **列映射**：确认 Excel 列匹配（例如第 64 列 = BL，而非 BK）
- [ ] **行偏移**：记住 Excel 行从 1 开始索引（DataFrame 第 5 行 = Excel 第 6 行）

### 常见陷阱
- [ ] **NaN 处理**：使用 `pd.notna()` 检查空值
- [ ] **靠右侧的列**：财年数据通常在第 50+ 列
- [ ] **多个匹配项**：搜索所有出现的位置，而非仅第一个
- [ ] **除以零**：在公式中使用 `/` 之前检查分母（#DIV/0!）
- [ ] **错误引用**：验证所有单元格引用指向预期的单元格（#REF!）
- [ ] **跨工作表引用**：使用正确的格式（Sheet1!A1）链接工作表

### 公式测试策略
- [ ] **从小处开始**：在广泛应用之前先在 2-3 个单元格上测试公式
- [ ] **验证依赖关系**：检查公式中引用的所有单元格是否存在
- [ ] **测试边界情况**：包含零值、负值和极大值

### 解读 scripts/recalc.py 输出
脚本返回包含错误详情的 JSON：
```json
{
  "status": "success",           // or "errors_found"
  "total_errors": 0,              // Total error count
  "total_formulas": 42,           // Number of formulas in file
  "error_summary": {              // Only present if errors found
    "#REF!": {
      "count": 2,
      "locations": ["Sheet1!B5", "Sheet1!C10"]
    }
  }
}
```

## 最佳实践

### 库的选择
- **pandas**：最适合数据分析、批量操作和简单数据导出
- **openpyxl**：最适合复杂格式化、公式和 Excel 特定功能

### 使用 openpyxl
- 单元格索引从 1 开始（row=1, column=1 指向单元格 A1）
- 使用 `data_only=True` 读取计算值：`load_workbook('file.xlsx', data_only=True)`
- **警告**：如果以 `data_only=True` 打开并保存，公式将被替换为值并永久丢失
- 对于大文件：读取时使用 `read_only=True`，写入时使用 `write_only=True`
- 公式会被保留但不会被计算——使用 scripts/recalc.py 更新值

### 使用 pandas
- 指定数据类型以避免推断问题：`pd.read_excel('file.xlsx', dtype={'id': str})`
- 对于大文件，读取指定列：`pd.read_excel('file.xlsx', usecols=['A', 'C', 'E'])`
- 正确处理日期：`pd.read_excel('file.xlsx', parse_dates=['date_column'])`

## 代码风格指南
**重要**：生成用于 Excel 操作的 Python 代码时：
- 编写简洁的 Python 代码，不添加不必要的注释
- 避免冗长的变量名和冗余操作
- 避免不必要的 print 语句

**对于 Excel 文件本身**：
- 为包含复杂公式或重要假设的单元格添加注释
- 记录硬编码值的数据来源
- 为关键计算和模型部分添加说明
