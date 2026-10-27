---
name: docx
description: "当用户需要创建、读取、编辑或处理 Word 文档（.docx 文件）或 Word 模板（.dotx 文件）时，使用此技能。触发场景包括提到“Word 文档”“word document”“.docx”“.dotx”，或要求生成带目录、标题、页码、信头等格式的专业文档；也包括从 .docx 或 .dotx 文件中提取或重组内容、在文档中插入或替换图片、在 Word 文件中查找替换、处理修订或批注，以及将内容转换为正式的 Word 文档。如果用户要求以 Word / .docx 文件形式交付“报告”“备忘录”“信函”“模板”等成果物，也应使用此技能。不要用于 PDF、电子表格、Google Docs，或与文档生成无关的一般编码任务。"
license: Proprietary. LICENSE.txt has complete terms
metadata:
  builtin_skill_version: "2.0"
---

> **重要说明:** 所有 `scripts/` 路径均相对于本技能目录。
> 运行方式: `cd {this_skill_dir} && python scripts/...`
> 或使用 `execute_shell_command` 的 `cwd` 参数。

# DOCX 创建、编辑与分析

## 前置依赖

- **docx** (npm, 已预装 — 仅当 `require('docx')` 失败时才安装): 新文档创建
- **pandoc**: 文本提取
- **LibreOffice** (`soffice`): `.doc` -> `.docx` 转换、修订接受和 PDF 导出
- **pdftoppm** (poppler-utils): 文档转图片工作流
- 如果 `pdftoppm` 不可用，Python 备用路径可能使用 `pdf2image`。
- 在 Windows 上，依赖项必须已安装并在 `PATH` 中可用；如缺失，请报告依赖问题并停止（不要反复重试）。

`.docx` 文件是 XML 文件的 ZIP 压缩包。按任务选择方法：

| 任务 | 方法 |
|------|------|
| **创建**新文档 | 编写 `docx` (npm) 脚本 — 见下方注意事项 |
| **编辑**现有文档 | `unzip` → 编辑 `word/document.xml` → `zip`（docx-js 无法打开已有文件） |
| **读取**内容 | `pandoc -t markdown file.docx` |

> 下方脚本路径均相对于本技能目录。

## 使用 docx-js 创建 — 注意事项

`docx` 已预装 — 不要先运行 `npm install`；直接编写脚本并 `require('docx')`。仅当 require 失败时才运行 `npm install docx`。模型已了解该 API；以下是常见的坑：

- **页面尺寸默认为 A4。** 如需 US Letter，设置 `page: { size: { width: 12240, height: 15840 } }`（DXA 单位；1440 = 1 英寸）。
- **横向：** 传入纵向尺寸并设置 `orientation: PageOrientation.LANDSCAPE` — docx-js 会在内部交换宽高。
- **表格需要双重宽度：** 在表格上设置 `columnWidths`，并在每个单元格上设置 `width`，均使用 `WidthType.DXA`（PERCENTAGE 在 Google Docs 中会出问题）。各列宽度之和必须等于表格宽度。
- **表格底纹：** 使用 `ShadingType.CLEAR`，绝不用 `SOLID`（会渲染成黑色）。
- **列表：** 绝不直接插入 `•` 字符；使用带 `LevelFormat.BULLET` 的 `numbering` 配置。
- **`ImageRun` 需要 `type:`**（`"png"`、`"jpg"` 等）。
- **`PageBreak` 必须位于 `Paragraph` 内部。**
- **绝不使用 `\n`** — 使用独立的 `Paragraph` 元素。
- **目录：** 标题必须使用内置的 `HeadingLevel.*`；自定义标题样式需要设置 `outlineLevel`，否则不会出现在目录中。
- **不要用表格当水平分隔线** — 改用段落底边框。
- **点式前导符 / 同行右对齐：** 在 `TextRun` 内使用 `PositionalTab`（`alignment: PositionalTabAlignment.RIGHT`、`leader: PositionalTabLeader.DOT`），而不是字面 `.` 或空格填充。

## 验证输出

写完 `.docx` 后，将其渲染成图片查看：

```bash
python scripts/office/soffice.py --headless --convert-to pdf output.docx
pdftoppm -jpeg -r 100 output.pdf page
ls page-*.jpg   # 然后查看这些图片
```

`pdftoppm` 会按总页数宽度对页码补零（`page-01.jpg`…`page-12.jpg`）。

## 编辑现有文档

旧版 `.doc` 文件必须先转换：`python scripts/office/soffice.py --headless --convert-to docx file.doc`。

```bash
unzip -q doc.docx -d unpacked/
find unpacked -type l -delete   # 删除符号链接条目 — 来自外部方的 docx 不可信
python scripts/merge_runs.py unpacked/   # 合并碎片化的 run，使文本可被查找到
# 原地编辑 unpacked/word/document.xml — 不要重新格式化或美化打印
(cd unpacked && rm -f ../out.docx && zip -Xr ../out.docx .)
python scripts/office/validate.py out.docx --original doc.docx   # XSD 校验；--auto-repair 修复常见问题
# 要做修订？加 --author "<你修订时使用的名称>" 以检查每处修改都有追踪记录
```

Word 会把文本拆分到多个 `<w:r>` run 中（修订 ID、拼写检查标记等），因此你在文档中看到的短语在 XML 里往往不是一段连续字符串。`merge_runs.py` 会在不改变内容和渲染效果的前提下，合并 `word/document.xml` 中相邻且格式相同的 run；它也接受直接传入 `.docx`（`python scripts/merge_runs.py doc.docx -o merged.docx`）。

**修订：** 做修订（redline）时，用 `--author "<你修订时使用的名称>"` 进行校验（需要 `--original`）— 它会报告你修改了文本却没有用 `<w:ins>`/`<w:del>` 包裹的情况，这种错误很容易犯，而且在“接受修订”视图中看不出来。用带 `w:id`、`w:author`、`w:date` 属性的 `<w:ins>`/`<w:del>` 包裹 run。在 `<w:del>` 内部，文本元素是 `<w:delText>` 而不是 `<w:t>`。被删除的段落标记（`<w:pPr><w:rPr><w:del w:id=".." w:author=".." w:date=".."/></w:rPr></w:pPr>`）表示“把本段合并进下一段” — 因此整段删除就是在此基础上，再给每个 run 都包上 `<w:del>`。`<w:del/>` 必须放在 rPr 的其他子元素之前；这一顺序由 schema 强制。

生成接受所有修订后的干净副本：`python scripts/accept_changes.py in.docx out.docx`。

接受被删除的段落标记时，该段落应与下一段合并，因此所有 run 都被删除的段落会整体消失。Word 会这样做；`accept_changes.py` 和 `pandoc --track-changes=accept` 则不总是如此。两者的失败方式相同 — 它们删掉了被删除的文本，却把空段落留在原地，当该段落原本是自动编号时，看起来就像一个多余的空项目符号：

- `pandoc --track-changes=accept` 从不合并段落。
- `accept_changes.py`（LibreOffice）能正确合并，但当被删段落后面跟着一个空的间隔段落时除外。

无论在哪个视图中，空项目符号都是该视图的产物，而不是文档本身的缺陷。请在 XML 中检查段落删除情况。

## 批注

批注需要六个相互关联的文件。请使用辅助脚本 — 如果还要编辑 `document.xml`，用目录模式（省去一次解压/重打包）；否则直接用 `.docx` 模式：

```bash
# 针对已解压的目录（同时还要放置标记时首选）
python scripts/comment.py unpacked/ "Fees & expenses cap is too low"
python scripts/comment.py unpacked/ "Agreed" --parent 0

# 直接针对 .docx
python scripts/comment.py contract.docx "This cap is too low" -o annotated.docx
```

该脚本会写入 `comments.xml`、`commentsExtended.xml`、`commentsIds.xml`、`commentsExtensible.xml`、关系文件以及内容类型覆盖项。批注 ID 自动分配。随后它会打印需要添加到 `word/document.xml` 的 `<w:commentRangeStart>`/`<w:commentRangeEnd>`/`<w:commentReference>` 代码片段，使批注锚定到具体文本 — 在放置这些标记之前，批注存在但不可见。
