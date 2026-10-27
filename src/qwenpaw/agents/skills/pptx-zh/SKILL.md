---
name: pptx
description: "当任何涉及 .pptx 或 .potx 文件的操作发生时使用此技能——无论是作为输入、输出还是两者兼有。包括：创建幻灯片、路演材料或演示文稿；从任何 .pptx 或 .potx 文件中读取、解析或提取文本（即使提取的内容将用于其他地方，如邮件或摘要）；编辑、修改或更新现有演示文稿；合并或拆分幻灯片文件；处理模板（.potx）、布局、演讲者备注或批注。当用户提到“演示文稿”“幻灯片”“PPT”或引用 .pptx / .potx 文件名时触发，无论他们之后打算如何使用内容。只要需要打开、创建或操作 .pptx / .potx 文件，就使用此技能。"
license: Proprietary. LICENSE.txt has complete terms
metadata:
  builtin_skill_version: "2.0"
---

> **重要说明:** 所有 `scripts/` 路径均相对于本技能目录。
> 运行方式: `cd {this_skill_dir} && python scripts/...`
> 或使用 `execute_shell_command` 的 `cwd` 参数。

# PPTX 创建、编辑与分析

## 前置依赖

- **pptxgenjs** (npm, 已预装 — 仅当 `require('pptxgenjs')` 失败时才安装): 从零创建演示文稿
- **markitdown[pptx]**: 从演示文稿提取文本
- **Pillow**: 生成缩略图网格
- **defusedxml**、**lxml**: clean/validate/thumbnail 脚本使用的 XML 解析库
- **LibreOffice** (`soffice`): 演示文稿转 PDF（通过 `scripts/office/soffice.py` 为沙箱环境自动配置）
- **pdftoppm** (poppler-utils): PDF 转图片，用于缩略图/视觉工作流
- 如果 `pdftoppm` 不可用，Python 备用路径可能使用 `pdf2image`。
- 在 Windows 上，依赖项必须已安装并在 `PATH` 中可用；如缺失，请报告依赖问题并停止（不要反复重试）。

`.pptx` 文件是 XML 文件的 ZIP 压缩包。按任务选择方法：

| 任务 | 方法 |
|------|------|
| **创建**新演示文稿 | 编写 `pptxgenjs` 脚本 — 见下方注意事项 |
| **编辑**现有演示文稿，或基于模板构建 | unzip → 编辑 `ppt/slides/slideN.xml` → zip |
| **读取**内容 | `markitdown deck.pptx`（在 `<!-- Slide number: N -->` 标记下每张幻灯片一个文本块）；视觉网格：`python scripts/thumbnail.py deck.pptx` |

## 脚本

路径均相对于本技能目录。其余都是普通 Python、`node` 或 shell。

| 脚本 | 功能 |
|---|---|
| `scripts/thumbnail.py deck.pptx [prefix]` | 带标签的每张幻灯片网格图，用于挑选模板版式。仅限 `.pptx`。务必传 `prefix` — 默认值是 `thumbnails`，会覆盖同一目录里其他演示文稿的网格图 |
| `scripts/add_slide.py unpacked/ slide2.xml [--after slideN.xml]` | 复制一张幻灯片（或 `slideLayoutN.xml`）并完成所有包内登记。也支持直接传 `.pptx` 配合 `-o out.pptx` |
| `scripts/clean.py unpacked/` | 删除不再被引用的幻灯片、媒体和关系。在 `<p:sldIdLst>` 定稿**之后**运行 |
| `scripts/office/validate.py deck.pptx [--original src.pptx]` | Schema、关系、内容类型、图表和幻灯片检查；每条失败信息都给出修复方法。模板衍生的文件务必传 `--original` — 它会把 schema 检查与模板基线对比，避免模板自身的 XSD 错误被算到你头上 |
| `scripts/office/soffice.py --headless --convert-to pdf deck.pptx` | LibreOffice 封装 — 直接调 `soffice` 在本沙箱中会挂起 |

## 使用 pptxgenjs 创建 — 注意事项

`pptxgenjs` 已预装 — 不要先运行 `npm install`；直接编写脚本并 `require('pptxgenjs')`。仅当 require 失败时才运行 `npm install pptxgenjs`。模型已了解该 API；以下是常见的坑：

- **添加幻灯片之前先设置 `pres.layout`。** 默认画布是 `LAYOUT_16x9` = **10" × 5.625"**，不是 13.3" 宽。超出边界的坐标会被直接写入而不是截断 — 形状只是不在幻灯片上。(`LAYOUT_WIDE` 是 13.3" × 7.5"。)
- **十六进制颜色：绝不带 `#`，绝不用 8 位。** `color: "FF0000"`。`"#FF0000"` 和把 alpha 写进十六进制（`"00000020"`）都会**损坏文件**。半透明效果：填充和图片用 `transparency: 0-100`，阴影用 `opacity: 0.0-1.0` — 用错位置会被静默忽略。
- **pptxgenjs 会原地修改选项对象**（首次使用时把值转换为 EMU）。绝不在两个 `add*` 调用之间共享同一个 `shadow`/选项对象 — 每次都新建对象。
- **阴影 `offset` 必须 ≥ 0** — 负偏移会损坏文件。要向上投影，用 `angle: 270` 配正偏移。
- **`letterSpacing` 会被静默忽略** — 真正的选项是 `charSpacing`。
- **列表：** 每个列表项设 `bullet: true`，绝不用字面 `•`（会渲染出双项目符号）。除最后一项外，每个数组元素都要设 `breakLine: true`。项目符号段落之间用 `paraSpaceAfter` 控制间距，不要用 `lineSpacing`（会出现巨大空隙）。
- **每个输出文件一个 `new pptxgen()`** — 绝不复用实例。
- **`rectRadius` 只对 `ROUNDED_RECTANGLE` 有效**，对 `RECTANGLE` 无效。
- **不支持渐变填充** — 改用渐变图片作为背景。
- **文本框自带内边距** — 文本与形状、线条或图标需要同 x 对齐时，设置 `margin: 0`。
- **演讲者备注放在 `slide.addNotes("...")` 中**（纯文本，每张幻灯片一次），绝不要放在幻灯片上的文本框里。
- **图表尽量用原生图表。** PowerPoint 能绘制的图表都用 `addChart()`（组合图传 `{type, data, options}` 数组）。库未暴露的 PowerPoint 原生功能（趋势线、误差线）就自己计算额外的数据序列或对生成的 OOXML 做后处理 — 不要退回渲染图片。只有 PowerPoint 没有原生形式的图表类型（Sankey、网络图、弦图）才用图片。
- **默认图表渲染得很素** — 无标题、无数据标签、配色过时。设置 `showTitle` + `title`、`showValue: true` + `dataLabelPosition`、从你的调色板取 `chartColors: [...]`，并把图表框架调安静（`catAxisLabelColor`/`valAxisLabelColor`、`valGridLine: { color, size }`、`catGridLine: { style: "none" }`、单系列时 `showLegend: false`）。
- **堆叠柱状图/条形图上 `dataLabelPosition` 必须是 `ctr`、`inEnd` 或 `inBase`。** `outEnd` 会**损坏文件**。
- **使用 `secondaryValAxis`/`secondaryCatAxis` 的组合系列，需要在图表选项上同时提供 `valAxes` 和 `catAxes`，各两项。** 缺了它们 pptxgenjs 会写入它从未声明的轴 *id*，PowerPoint 会**丢弃该图表**并报告文件损坏。只给 `valAxes` 不够。
- **`writeFile()` 之后，运行 `python scripts/office/validate.py deck.pptx`。** 它会报告上面两类图表问题和 PowerPoint 拒绝打开的幻灯片 XML 缺陷，并给出每条的修复方法。在生成器里修，不要手改打包后的 XML。
- **绝不要重排 `<p:presentation>` 的子元素。** pptxgenjs 会把 `<p:notesMasterIdLst>` 写在 `<p:sldIdLst>` 之后，并让两个母版指向同一个主题部件。PowerPoint 能正常读取 — 移动该元素后同一份文件就打不开了。
- **图标：** 用 `react-icons` 渲染成 SVG（`ReactDOMServer.renderToStaticMarkup`），用 `sharp` 以 ≥256px 栅格化，然后通过 `addImage({ data: "image/png;base64," + buf.toString("base64") })` 插入 — `image/png;base64,` 前缀是必需的（`react-icons`、`react`、`react-dom`、`sharp` 已预装 — 仅当 require 失败时才 `npm install react-icons react react-dom sharp`）。

## 编辑现有演示文稿与模板

先挑版式：`python scripts/thumbnail.py template.pptx template-thumbs` 会生成带标签的每张幻灯片网格图，并打印创建的文件 — `template-thumbs.jpg`，超过 12 张幻灯片时拆分为 `template-thumbs-N.jpg`。**务必传第二个参数，以演示文稿命名。** 默认值是 `thumbnails`，同一目录里两份演示文稿的网格图会互相静默覆盖 — 先处理的那份直接丢失（仅限模板分析 — 视觉 QA 需要用[转换为图片](#转换为图片)中的全分辨率渲染；它只接受 `.pptx`，所以先把 `.potx` 复制成 `.pptx` 文件名）。配合 `markitdown` 使用，把每个内容段落映射到模板幻灯片上，并变换版式 — 不要每一段都放在同一种“标题+要点”幻灯片上。

```bash
python3 -c "import sys,zipfile; zipfile.ZipFile(sys.argv[1]).extractall('unpacked')" deck.pptx
python scripts/add_slide.py unpacked/ slide2.xml --after slide2.xml   # 复制一张幻灯片（或 slideLayoutN.xml）；打印新幻灯片的路径
# 重排 / 删除幻灯片 = 编辑 ppt/presentation.xml 中的 <p:sldIdLst>
python scripts/clean.py unpacked/                                     # 删除操作之后：清理孤立的幻灯片、媒体、关系
# 在 ppt/slides/slideN.xml 中编辑幻灯片内容
(cd unpacked && rm -f ../out.pptx && zip -Xr ../out.pptx .)           # 从目录内部打包；先 rm，否则已删除的部件会残留
python scripts/office/validate.py out.pptx --original deck.pptx
```

- **所有结构操作 — 新增、删除、重排 — 都要在编辑任何幻灯片内容之前完成。** `add_slide.py` 会原样复制幻灯片文件，所以编辑之后再复制会把已编辑的内容一并克隆；而且 `clean.py` 会删除 `<p:sldIdLst>` 中缺失的幻灯片，包括你刚写好的那张。
- **绝不要手动复制幻灯片文件** — `add_slide.py` 会完成新幻灯片需要的全部登记，并报告它做了什么（`Created ppt/slides/slide17.xml from slide2.xml`）。它也可以直接作用于文件：`add_slide.py deck.pptx slide2.xml -o out.pptx` — **必须传 `-o`，否则会原地重写输入文件。** 复制出的幻灯片仍然*引用*源幻灯片的图表/SmartArt/嵌入对象部件而不是克隆它们，因此修改其中一张的图表会同时影响另一张。
- **如果你使用 `python-pptx`**，注意它做不到的三件事：复制幻灯片（唯一入口是 `add_slide(layout)`）、通过 `text_frame.text = "..."` 保留格式（这会把段落塌缩成单个无样式 run — 改为给 `run.text` 赋值），以及读取大多数模板美术资源用的 SVG/EMF（`add_picture` 会抛 `UnidentifiedImageError`）。
- 旧版 `.ppt` 必须先转换：`python scripts/office/soffice.py --headless --convert-to pptx file.ppt`。`.potx` 模板的解包与打包方式相同 — 输出保留 `.potx` 扩展名。
- 要复用模板中的图标或图片，复制一份已经包含它的幻灯片或版式。

填充模板时：

- 如果用脚本做 XML 变换，用 `defusedxml.minidom` 解析 — 用 `xml.etree.ElementTree` 往返 OOXML 会重写命名空间前缀并损坏文件。
- **模板槽位 ≠ 源条目。** 模板展示 4 名团队成员而你有 3 个时，删除第 4 名成员的整个组（图片 + 文本框），而不只是它的文本 — 然后在 QA 时检查有无孤立的视觉元素。
- 每个列表项一个 `<a:p>` — 绝不把多个条目拼进一个段落。复制相邻的 `<a:pPr>` 以保留间距，并在标题、小节标题和行内标签（`Status:`、`Owner:`）的 `<a:rPr>` 上加 `b="1"`。
- 让项目符号继承版式；只在需要覆盖时添加 `<a:buChar>`、`<a:buAutoNum>`（编号）或 `<a:buNone>` — 绝不在文本里写字面 `•`。
- 带前导或尾随空格的文本需要在其 `<a:t>` 上设置 `xml:space="preserve"`。

## 设计思路

**不要做无聊的幻灯片。** 白底纯文字的要点列表打动不了任何人。为每张幻灯片从下面的清单中汲取灵感。

### 开始之前

- **选一套大胆、与内容相关的配色**：配色应当是为“这个”主题专门设计的。如果把你的配色换到一场完全不同的演示里还照样“能用”，说明你的选择还不够具体。
- **主导优于均衡**：一种颜色占主导（60-70% 视觉权重），配 1-2 个辅助色和一个锐利的强调色。绝不让所有颜色平分权重。
- **深浅对比**：标题页和结尾页用深色背景，内容页用浅色（“三明治”结构）。或者全程深色以呈现高级感。
- **坚持一个视觉母题**：选一个独特元素并贯穿始终 — 圆角图片框、彩色圆圈中的图标。**不要用色条或强调条纹当母题**（见“避免”清单）。

### 配色方案

选择与主题匹配的颜色 — 不要默认用大众蓝。以下配色仅供参考：

| 主题 | 主色 | 辅色 | 强调色 |
|-------|---------|-----------|--------|
| **午夜行政** | `1E2761`（海军蓝） | `CADCFC`（冰蓝） | `FFFFFF`（白） |
| **森林与苔藓** | `2C5F2D`（森林绿） | `97BC62`（苔藓绿） | `F5F5F5`（奶油白） |
| **珊瑚活力** | `F96167`（珊瑚色） | `F9E795`（金色） | `2F3C7E`（海军蓝） |
| **暖陶土** | `B85042`（陶土色） | `E7E8D1`（沙色） | `A7BEAE`（鼠尾草绿） |
| **海洋渐变** | `065A82`（深蓝） | `1C7293`（青色） | `21295C`（午夜蓝） |
| **炭黑极简** | `36454F`（炭灰） | `F2F2F2`（米白） | `212121`（黑） |
| **信赖青** | `028090`（青色） | `00A896`（海沫绿） | `02C39A`（薄荷绿） |
| **浆果奶油** | `6D2E46`（浆果色） | `A26769`（灰玫瑰） | `ECE2D0`（奶油白） |
| **鼠尾草宁静** | `84B59F`（鼠尾草绿） | `69A297`（桉叶绿） | `50808E`（岩板灰） |
| **浓烈樱桃** | `990011`（樱桃红） | `FCF6F5`（米白） | `2F3C7E`（海军蓝） |

### 每张幻灯片

**每张幻灯片都需要一个视觉元素** — 图片、图表、图标或形状。纯文字的幻灯片令人过目即忘。

**版式选择：**
- 两栏（左文右图）
- 图标 + 文字行（彩色圆圈中的图标，加粗小标题，下方是描述）
- 2x2 或 2x3 网格（一侧是图片，另一侧是内容块网格）
- 半出血图片（占满左侧或右侧）叠加内容

**数据展示：**
- 大数字标注（60-72pt 大数字，下方配小标签）
- 对比栏（前后对比、优缺点对比、并排选项）
- 时间线或流程图（编号步骤、箭头）

**视觉润色：**
- 小节标题旁彩色小圆圈里的图标
- 关键数据或标语用斜体强调

### 字体排版

**你写进 .pptx 的字体名称由用户机器上的 PowerPoint 渲染，而不是本环境。** 你的视觉 QA 通过 LibreOffice 渲染，它对没有的字体做替换 — 有些替换字体宽度不同，因此 QA 预览可能显示真实文件中不会出现的文本溢出（或刚好放得下）。要让 QA 可信：

- **安全字体**（在 QA 中宽度还原真实*且*随 Office 附带）：**Arial, Calibri, Cambria, Times New Roman, Courier New, Bookman Old Style, Century Schoolbook**。正文和一切需要关心是否放得下的文本都用它们。
- **零 QA 风险的个性化标题**：安全清单中的衬线标题（Cambria, Bookman Old Style, Century Schoolbook）搭配安全清单中的无衬线正文（Calibri 或 Arial）。既有视觉对比，又不放弃可靠的溢出检查。
- **如果用户指定了安全清单之外的字体**（如 Georgia 或 Trebuchet MS）：在用户要求之处使用，但给这些容器预留约 10% 的额外空间，并且不要相信 QA 对这些元素的文本适配判断 — 该字体的预览是近似的。用户未指定时，正文优先用安全清单字体。
- **QA 不可信字体**（替换字体宽度不同 — 溢出检查可能出错）：Georgia, Trebuchet MS, Impact, Arial Black, Garamond, Consolas, Palatino Linotype。Calibri Light 的替换因环境而异；视为 QA 不可信。用于标题/强调并预留空间没问题；不要在这些字体上相信 QA 的文本适配判断。
- **绝不默认使用 Aptos** — Office 2023 之后的默认字体既没有宽度兼容的替换字体，又不在旧版 Office 中，两端都不可靠。

| 元素 | 字号 |
|---------|------|
| 幻灯片标题 | 36-44pt 加粗 |
| 小节标题 | 20-24pt 加粗 |
| 正文 | 14-16pt |
| 说明文字 | 10-12pt 弱化 |

### 间距

- 最小边距 0.5"
- 内容块之间 0.3-0.5"
- 留出呼吸空间 — 不要填满每一寸

### 避免（常见错误）

- **不要重复同一版式** — 在各幻灯片间变换栏式、卡片和标注
- **不要居中正文** — 段落和列表左对齐；只有标题可以居中
- **不要吝啬字号对比** — 标题需要 36pt 以上才能从 14-16pt 的正文中凸显
- **不要默认蓝色** — 选能反映具体主题的颜色
- **不要混用间距** — 选定 0.3" 或 0.5" 的间隔并保持一致
- **不要只精修一张幻灯片而其余保持朴素** — 要么全程投入，要么全程简洁
- **不要做纯文字幻灯片** — 加入图片、图标、图表或视觉元素；避免朴素的“标题 + 要点”
- **不要忘记文本框内边距** — 让文本或形状与文本边缘对齐时，给文本框设置 `margin: 0`，或按内边距偏移形状
- **不要使用低对比元素** — 图标和文字都要与背景有足够对比；避免浅底浅字或深底深字
- **绝不在标题下加强调线** — 这是 AI 生成幻灯片的标志性特征；用留白或背景色代替
- **绝不加装饰性色条或强调条纹** — 包括：横贯幻灯片宽度的页眉/页脚色条、沿一边的竖向侧边条纹、卡片或内容块边缘的细条纹，以及矩形的“单侧边框”。这些都像 AI 生成的填充物。想让卡片突出，用淡背景色、投影或图标 — 而不是边缘条纹。
- **不要默认奶油色/米色背景** — 未指定背景时用白色（`FFFFFF`）或用户的品牌色；避免 `F5F5DC`、`FAF0E6`、`FAEBD7`、`FFF8E1` 这类暖中性默认色
- **不要交付溢出容器的文本** — 放不下就缩小字号、拆分幻灯片或放大容器；绝不让内容被截断或溢出边界

## QA（必需）

第一次渲染通常都有几个真实问题 — 重叠、溢出、错位。找出并修复它们，只重新渲染改动的幻灯片，然后停止。

### 内容 QA

```bash
markitdown output.pptx
```

检查缺失内容、错别字、顺序错误。

**使用模板时，检查残留的占位文本：**

```bash
markitdown output.pptx | grep -iE "\bx{3,}\b|lorem|ipsum|\bTODO|\[insert|this.*(page|slide).*layout"
```

如果 grep 有输出，先修复再宣告完成。

### 文件 QA（必需）

```bash
python scripts/office/validate.py output.pptx                      # 从零构建的文件
python scripts/office/validate.py output.pptx --original src.pptx  # 基于模板构建的文件
```

**演示文稿来自模板时，务必传 `--original`。** 模板本身可能包含 XSD 拒绝的部件，因此裸跑会报告一些并非你造成的失败 — 而真正的回归可能混在其中。`--original` 把 schema 和幻灯片检查与模板基线对比，抑制模板已有的错误。结构检查 — 关系、内容类型、图表 — 不受 `--original` 影响，无论是否传都会报告模板继承的问题，请自行甄别。

pptxgenjs 生成的图表 XML 会被 PowerPoint 拒绝打开，而其他所有工具都接受：python-pptx 能打开这些文件，LibreOffice 能渲染，XSD 校验也能通过。每条失败信息都给出修复方法。在生成器里修，然后重新构建。

### 视觉 QA

把幻灯片转换成图片（见[转换为图片](#转换为图片)）并逐张检查。盯着生成代码看久了，你往往会看到自己期望的画面而不是实际渲染的结果，所以要以全新的眼光看图（如果有子代理，用它来做这件事很合适）。需要关注的用户可见缺陷：

- **文本溢出或在文本框/幻灯片边界被截断 — 首先检查这个。** 这是最常见且必然用户可见的缺陷。（对排版字体预览不可靠的字体，预览是近似的：相信你预留的约 10% 余量，而不是它表面上放得下。）
- 元素重叠（文字穿过形状、线条穿过文字、元素堆叠）
- 来源引用或页脚与上方内容相撞
- 元素间距过近（< 0.3"）或卡片/小节几乎贴在一起
- 间距不均（一处大片空白，另一处拥挤）
- 距幻灯片边缘的边距不足（< 0.5"）
- 栏或类似元素未对齐
- 低对比文本（如奶油色背景上的浅灰文字）
- 文本替换后模板装饰错位 — 例如下划线按一行标题定位，替换后的标题却折成两行
- 低对比图标（如深色背景上的深色图标，没有对比圆圈衬托）
- 文本框过窄导致过度换行
- 残留的占位内容

## 转换为图片

把演示文稿转换为单张幻灯片图片以便视觉检查：

```bash
python scripts/office/soffice.py --headless --convert-to pdf output.pptx
rm -f slide-*.jpg
pdftoppm -jpeg -r 150 output.pdf slide
ls -1 "$PWD"/slide-*.jpg
```

**把上面打印出的绝对路径直接交给查看工具。** `rm` 清掉上次运行留下的旧图片。`pdftoppm` 按总页数补零：10 页以内的文件是 `slide-1.jpg`，10-99 页是 `slide-01.jpg`，100 页以上是 `slide-001.jpg`。

**修复之后，重跑上面的全部四条命令** — 必须先从编辑后的 `.pptx` 重新生成 PDF，`pdftoppm` 才能反映你的修改。
