> **重要：** 所有 `scripts/` 路径都相对于技能目录（SKILL.md 所在位置）。
> 运行方式：`cd {this_skill_dir} && python scripts/...`
> 或使用 `execute_shell_command` 的 `cwd` 参数。

# 编辑演示文稿

## 基于模板的工作流

使用现有演示文稿作为模板时：

1. **分析现有幻灯片**：
   ```bash
   python scripts/thumbnail.py template.pptx
   python -m markitdown template.pptx
   ```
   查看 `thumbnails.jpg` 了解布局，查看 markitdown 输出了解占位符文本。

2. **规划幻灯片映射**：为每个内容部分选择一个模板幻灯片。

   ⚠️ **使用多样化的布局**——千篇一律的演示文稿是常见的失败模式。不要默认使用基本的标题加要点幻灯片。积极寻找：
   - 多栏布局（两栏、三栏）
   - 图片 + 文字组合
   - 全出血图片加文字叠加
   - 引用或标注幻灯片
   - 章节分隔页
   - 数据/数字突出显示
   - 图标网格或图标 + 文字行

   **避免：** 每张幻灯片都重复相同的文字密集型布局。

   将内容类型与布局风格匹配（例如：要点 → 要点幻灯片，团队信息 → 多栏布局，用户评价 → 引用幻灯片）。

3. **解包**：`python scripts/office/unpack.py template.pptx unpacked/`

4. **构建演示文稿**（自己完成，不要使用子代理）：
   - 删除不需要的幻灯片（从 `<p:sldIdLst>` 中移除）
   - 复制需要重用的幻灯片（`add_slide.py`）
   - 在 `<p:sldIdLst>` 中重新排列幻灯片顺序
   - **在第 5 步之前完成所有结构性更改**

5. **编辑内容**：更新每个 `slide{N}.xml` 中的文本。
   **如有子代理可用，在此处使用**——幻灯片是独立的 XML 文件，子代理可以并行编辑。

6. **清理**：`python scripts/clean.py unpacked/`

7. **打包**：`python scripts/office/pack.py unpacked/ output.pptx --original template.pptx`

---

## 脚本

| 脚本 | 用途 |
|------|------|
| `unpack.py` | 提取并格式化 PPTX |
| `add_slide.py` | 复制幻灯片或从布局创建 |
| `clean.py` | 移除孤立文件 |
| `pack.py` | 重新打包并验证 |
| `thumbnail.py` | 创建幻灯片视觉网格 |

### unpack.py

```bash
python scripts/office/unpack.py input.pptx unpacked/
```

提取 PPTX，格式化 XML，转义智能引号。

### add_slide.py

```bash
python scripts/add_slide.py unpacked/ slide2.xml      # 复制幻灯片
python scripts/add_slide.py unpacked/ slideLayout2.xml # 从布局创建
```

输出要添加到 `<p:sldIdLst>` 指定位置的 `<p:sldId>`。

### clean.py

```bash
python scripts/clean.py unpacked/
```

移除不在 `<p:sldIdLst>` 中的幻灯片、未引用的媒体文件和孤立的关系文件。

### pack.py

```bash
python scripts/office/pack.py unpacked/ output.pptx --original input.pptx
```

验证、修复、压缩 XML、重新编码智能引号。

### thumbnail.py

```bash
python scripts/thumbnail.py input.pptx [output_prefix] [--cols N]
```

创建 `thumbnails.jpg`，以幻灯片文件名作为标签。默认 3 列，每个网格最多 12 张。

**仅用于模板分析**（选择布局）。视觉质量检查请使用 `soffice` + `pdftoppm` 创建全分辨率的单张幻灯片图片——参见 SKILL.md。

---

## 幻灯片操作

幻灯片顺序在 `ppt/presentation.xml` → `<p:sldIdLst>` 中。

**重新排序**：重新排列 `<p:sldId>` 元素。

**删除**：移除 `<p:sldId>`，然后运行 `clean.py`。

**添加**：使用 `add_slide.py`。切勿手动复制幻灯片文件——脚本会处理备注引用、Content_Types.xml 和关系 ID，手动复制会遗漏这些。

---

## 编辑内容

**子代理：** 如可用，在此处使用（完成第 4 步之后）。每张幻灯片是独立的 XML 文件，子代理可以并行编辑。在向子代理发出的提示中包含：
- 要编辑的幻灯片文件路径
- **"使用 Edit 工具进行所有更改"**
- 以下格式规则和常见问题

对每张幻灯片：
1. 读取幻灯片的 XML
2. 识别所有占位符内容——文本、图片、图表、图标、说明文字
3. 将每个占位符替换为最终内容

**使用 Edit 工具，而非 sed 或 Python 脚本。** Edit 工具要求明确指定替换内容和位置，可靠性更高。

### 格式规则

- **所有标题、副标题和行内标签加粗**：在 `<a:rPr>` 上使用 `b="1"`。包括：
  - 幻灯片标题
  - 幻灯片内的章节标题
  - 行内标签（例如行首的"状态："、"描述："）
- **切勿使用 Unicode 项目符号（•）**：使用 `<a:buChar>` 或 `<a:buAutoNum>` 进行正确的列表格式化
- **项目符号一致性**：让项目符号从布局继承。只指定 `<a:buChar>` 或 `<a:buNone>`。

---

## 常见问题

### 模板适配

当源内容的项目数少于模板时：
- **完整移除多余元素**（图片、形状、文本框），不要只清空文本
- 清空文本内容后检查是否有孤立的视觉元素
- 运行视觉质量检查以捕获数量不匹配的问题

当替换文本长度不同时：
- **较短的替换**：通常安全
- **较长的替换**：可能溢出或意外换行
- 文本更改后进行视觉质量检查
- 考虑截断或拆分内容以适应模板的设计约束

**模板槽位 ≠ 源项目数**：如果模板有 4 个团队成员但源数据只有 3 个用户，删除第 4 个成员的整个组（图片 + 文本框），而不仅仅是文本。

### 多项目内容

如果源数据有多个项目（编号列表、多个章节），为每个项目创建单独的 `<a:p>` 元素——**切勿将所有内容拼接成一个字符串**。

**❌ 错误** ——所有项目在一个段落中：
```xml
<a:p>
  <a:r><a:rPr .../><a:t>Step 1: Do the first thing. Step 2: Do the second thing.</a:t></a:r>
</a:p>
```

**✅ 正确** ——独立段落加粗体标题：
```xml
<a:p>
  <a:pPr algn="l"><a:lnSpc><a:spcPts val="3919"/></a:lnSpc></a:pPr>
  <a:r><a:rPr lang="en-US" sz="2799" b="1" .../><a:t>Step 1</a:t></a:r>
</a:p>
<a:p>
  <a:pPr algn="l"><a:lnSpc><a:spcPts val="3919"/></a:lnSpc></a:pPr>
  <a:r><a:rPr lang="en-US" sz="2799" .../><a:t>Do the first thing.</a:t></a:r>
</a:p>
<a:p>
  <a:pPr algn="l"><a:lnSpc><a:spcPts val="3919"/></a:lnSpc></a:pPr>
  <a:r><a:rPr lang="en-US" sz="2799" b="1" .../><a:t>Step 2</a:t></a:r>
</a:p>
<!-- 继续此模式 -->
```

从原始段落复制 `<a:pPr>` 以保留行间距。标题使用 `b="1"`。

### 智能引号

由 unpack/pack 自动处理。但 Edit 工具会将智能引号转换为 ASCII。

**添加包含引号的新文本时，使用 XML 实体：**

```xml
<a:t>the &#x201C;Agreement&#x201D;</a:t>
```

| 字符 | 名称 | Unicode | XML 实体 |
|------|------|---------|----------|
| `\u201c` | 左双引号 | U+201C | `&#x201C;` |
| `\u201d` | 右双引号 | U+201D | `&#x201D;` |
| `\u2018` | 左单引号 | U+2018 | `&#x2018;` |
| `\u2019` | 右单引号 | U+2019 | `&#x2019;` |

### 其他

- **空白字符**：在有前导/尾随空格的 `<a:t>` 上使用 `xml:space="preserve"`
- **XML 解析**：使用 `defusedxml.minidom`，而非 `xml.etree.ElementTree`（会破坏命名空间）
