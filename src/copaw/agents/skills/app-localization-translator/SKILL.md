---
name: app-localization-translator
description: "Batch translates app localization text using qwen-mt MCP. Each translation task is managed as an independent project folder with source files, glossary, translation memory, progress tracking Excel, and output files. Use when user asks to translate Excel files, localize apps, do i18n translation, or mentions 翻译、本地化、多语言."
---

# App Localization Translator

Each translation task is an independent **project folder**. All source files, glossary, translation memory, progress tracking, and outputs live inside this folder.

## Prerequisites

Requires the **qwen-mt MCP** (`translate` and `get_supported_languages` tools). If unavailable, remind user to configure it first.

## CRITICAL RULES

1. **EVERY row MUST be translated by calling the MCP `translate` tool individually.** This is non-negotiable.
2. **NEVER write Python scripts, shell scripts, or any code to batch-translate.** Do not use `execute_shell_command`, `subprocess`, `requests`, or any other method to call translation APIs directly. The MCP `translate` tool is the ONLY permitted translation method.
3. **NEVER skip the `terms` and `tm_list` parameters.** Each `translate` call must include filtered glossary terms and selected translation memory. This is what ensures translation quality. Batch scripts cannot do per-row context selection — that is exactly why they are forbidden.
4. **NEVER combine multiple source texts into a single `translate` call.** One call = one row. Combining degrades quality because the tool cannot distinguish which terms and TM apply to which text.
5. **Translation results MUST be written back to `进度表.xlsx` every 10 rows.** Do NOT accumulate more than 10 translated rows in memory without saving. This is the checkpoint mechanism that prevents data loss. See "Write-back Protocol" for details.

## Project Folder Structure

```
<用户指定位置>/<项目名>/
├── 源文件/
│   └── xxx.xlsx                 ← copy of source file
├── 术语表.xlsx                   ← project-specific glossary (user-editable)
├── tm.json                      ← project-specific translation memory
├── 进度表.xlsx                   ← progress tracking (core management file)
│   ├── Sheet "翻译明细"          ← row-level detail
│   └── Sheet "批次汇总"          ← batch-level summary
└── 翻译结果_批次N.xlsx           ← output per batch
```

## Workflow

### Step 0: Detect project state (ALWAYS run first)

Before asking any questions, check if the user provided or mentioned a project folder path:

1. **If a folder path is given**, check whether it contains `进度表.xlsx`.
   - **`进度表.xlsx` exists** → this is a **resume** task. Read the progress Excel "翻译明细" sheet and "批次汇总" sheet. Count rows where status = "待翻译". Report to user: "Found existing project with X/Y rows translated, Z rows remaining. Resuming from batch N." Then jump to **Step 3**.
   - **`进度表.xlsx` does not exist** → the folder exists but is not a translation project. Ask user if they want to initialize a new project here.
2. **If no folder path is given**, ask the user for project location and proceed to **Step 1** (new project).

### Step 1: Create new project

Ask the user (use AskUserQuestion tool):

1. **Project folder location and name** — where to create the project folder
2. **Source file path** — which Excel file to translate
3. **Source & target language** (default: Chinese → English)
4. **Domain hint** (e.g. `"game"`, `"social"`, `"e-commerce"`, `"IT"`)
5. **Which column(s)** need translation
6. **Custom glossary terms** — any project-specific terms to add

Then:

1. Create the project folder and `源文件/` subdirectory.
2. **Copy** the source Excel into `源文件/`.
3. Initialize `术语表.xlsx` — seed from the Default Glossary Terms below, plus any user-provided terms. See "术语表.xlsx Format" for column structure.
4. Initialize `tm.json` as `{"version": "1.0", "pairs": []}`.

### Step 2: Initialize progress Excel

Use the **xlsx skill** to read the source file from `源文件/`. Identify columns to translate and total row count. Create `进度表.xlsx` with:

- "翻译明细" sheet: populate all rows with status = "待翻译".
- "批次汇总" sheet: pre-plan batches (100 rows each), all status = "未开始".

### Step 3: Translate current batch

Determine which batch to work on:

- **New project**: start with batch 1.
- **Resume**: read "批次汇总" to find the first batch where status != "已完成". Read "翻译明细" to find the first row where status = "待翻译".

For each row in the current batch, call MCP `translate`:

```
translate(
  text: "待翻译文本",
  target_lang: "English",
  source_lang: "Chinese",
  model: "qwen-mt-plus",
  terms: [filtered from 术语表.xlsx — see Context Selection],
  tm_list: [selected from tm.json — see Context Selection],
  domains: "domain hint"
)
```

**Rules:**

- **One MCP `translate` call per row. No exceptions. No batch scripts.** (See CRITICAL RULES above.)
- Use the **Context Selection Strategy** below to pick `terms` and `tm_list` for each call. Each row gets its own tailored context — this is the core quality advantage over batch translation.
- **Follow the Write-back Protocol below** to save results to `进度表.xlsx`. Do NOT hold more than 10 translated rows without saving.
- Report progress to user every 50 rows.

### Write-back Protocol

Translation results MUST be persisted to `进度表.xlsx` frequently to prevent data loss. Follow this exact cycle:

**Translate → Buffer → Save → Verify → Repeat**

1. **Translate 10 rows** (or remaining rows if <10 left in batch). For each row, store the translation result and Tips in memory. Also track any new glossary terms discovered and good translation pairs produced.
2. **Save checkpoint** (all three files at once):
   - **`进度表.xlsx`**: write all 10 results into the "翻译明细" sheet (columns C=译文, D=状态→"已翻译", E=Tips). Save and close.
   - **`术语表.xlsx`**: if any new terms were discovered in these 10 rows (recurring translations that should be standardized, or user-confirmed terms), append new rows. Deduplicate by 原文 column.
   - **`tm.json`**: append 2-3 high-quality translation pairs from these 10 rows. Prefer clear, unambiguous, representative pairs. Cap at 500 total.
3. **Verify write**: Re-read the saved rows from `进度表.xlsx` to confirm the data was written correctly. Check that:
   - All 10 rows have status = "已翻译"
   - All 10 rows have non-empty 译文 column
   - Row count of "已翻译" increased by 10
4. **If verification fails**: Report the error to the user immediately. Do NOT continue translating until the write issue is resolved.
5. **Repeat** from step 1 for the next 10 rows.

**At the end of each batch**, run a final verification: count all "已翻译" rows in the sheet and compare with expected total. Report any discrepancy.

**Why 10 rows?** This is the maximum acceptable data loss window. If the session crashes, at most 10 translations (not 100) need to be redone. Glossary (`术语表.xlsx`) and TM (`tm.json`) are also saved at the same cadence, so new terms discovered in rows 1-10 are immediately available for rows 11-20.

### Step 4: Generate Tips

For each row, generate Tips annotations:

| Tag | When to use |
|-----|-------------|
| `[术语]` | Used a glossary term |
| `[占位符]` | Contains %s, %d, {xxx} etc. |
| `[待确认]` | Translation uncertain or >2x source length |
| `[文化适配]` | Cultural adaptation applied |
| `[格式代码]` | Contains HTML/format codes |

Leave empty if nothing noteworthy.

### Step 5: Finish batch

After completing a batch:

1. **Output**: create `翻译结果_批次N.xlsx` with three columns (原文 | 译文 | Tips). Styling: Header = blue (#4472C4) + white bold; Tips cells with content = yellow (#FFFF99); Widths A=50, B=50, C=30; wrap text, top-aligned.
2. **Update 进度表.xlsx**: update "批次汇总" with completion time and status = "已完成".
3. **Final verification**: `术语表.xlsx` and `tm.json` should already be up-to-date (saved every 10 rows via Write-back Protocol). Do a final check that the files exist and are valid.
4. **Report**: tell the user batch N is done, show remaining batches and rows, and list any new glossary terms added during this batch.

## Context Selection Strategy

The translate tool has limited context. Do NOT pass the entire glossary or all TM pairs. Select intelligently for each row:

### Glossary terms (`terms` parameter)

1. **Read `术语表.xlsx`** at the start of each batch. Load all rows into memory as the glossary pool.
2. **Scan the source text** for each term's 原文 field.
3. **Only include terms whose 原文 appears in (or is a substring of) the current row's text.**
4. If no terms match the current text, pass an empty array. Do not pad with unrelated terms.
5. **Maximum 20 terms per call** — if more than 20 match, prioritize by: exact match > substring match > category relevance.

Example: for text "物品配置错误，无该物品(%u)", only pass terms for "物品", "错误", "配置" — not "登录", "密码" etc.

### Translation memory (`tm_list` parameter)

1. **Pick pairs that share keywords or structure with the current text.** Look for: same subject (e.g. both about items, both about login), similar sentence pattern (e.g. both error messages), shared key terms.
2. **Maximum 10 pairs per call.**
3. **Prioritize recent translations from the current batch** — they share the most context with the text being translated now.
4. If tm.json has <10 pairs total, pass all of them. If >10, select the 10 most relevant.
5. **Never pass pairs that are completely unrelated** (e.g. don't pass a "login success" pair when translating an "item error" text).

### Building context as you go

During batch translation, maintain a running buffer of the last 20 translated pairs from the current session. When selecting `tm_list`, prefer these recent pairs over older ones in `tm.json`, because they reflect the current project's tone and terminology most accurately.

## Progress Excel (进度表.xlsx) Format

### Sheet "翻译明细"

| A: 行号 | B: 原文 | C: 译文 | D: 状态 | E: Tips |
|---------|---------|---------|---------|---------|

- 状态 values: `待翻译` / `已翻译` / `待确认`
- Header: blue (#4472C4), white bold
- 待翻译 rows: no fill
- 已翻译 rows: light green fill (#E2EFDA)
- 待确认 rows: light yellow fill (#FFFF99)
- Column widths: A=8, B=50, C=50, D=10, E=30

### Sheet "批次汇总"

| A: 批次 | B: 起始行 | C: 结束行 | D: 行数 | E: 完成时间 | F: 状态 |
|---------|----------|----------|---------|------------|---------|

- 状态 values: `已完成` / `进行中` / `未开始`
- Header: blue (#4472C4), white bold

## 术语表.xlsx Format

The glossary is an Excel file that the user can view and edit directly.

| A: 原文 | B: 译文 | C: 分类 | D: 来源 |
|---------|---------|---------|---------|

- **原文**: source term (Chinese)
- **译文**: target translation (English)
- **分类**: category tag (e.g. UI, 游戏, 账户, 操作, 提示, 系统)
- **来源**: how this term was added — `默认` (seed), `用户` (user-provided), or `自动` (discovered during translation)

**Styling:**

- Header: blue (#4472C4), white bold
- 来源="自动" rows: light blue fill (#D6E4F0) so user can easily spot and review auto-discovered terms
- Column widths: A=20, B=20, C=10, D=10

**User editing**: The user may manually add, edit, or delete rows between translation sessions. The agent must always re-read `术语表.xlsx` at the start of each batch to pick up any manual changes.

## TM File Format

**tm.json:**
```json
{
  "version": "1.0",
  "pairs": [
    {"source": "登录成功", "target": "Login Successful"}
  ]
}
```

## Default Glossary Terms (Seed)

Used to initialize a new project's `术语表.xlsx`. All seeded rows have 来源 = `默认`.

| 原文 | 译文 | 分类 |
|------|------|------|
| 设置 | Settings | UI |
| 确定 | OK | UI |
| 取消 | Cancel | UI |
| 保存 | Save | 操作 |
| 删除 | Delete | 操作 |
| 编辑 | Edit | 操作 |
| 搜索 | Search | 操作 |
| 登录 | Login | 账户 |
| 注册 | Sign Up | 账户 |
| 密码 | Password | 账户 |
| 首页 | Home | 导航 |
| 我的 | Mine | 导航 |
| 消息 | Messages | 功能 |
| 通知 | Notifications | 功能 |
| 返回 | Back | 导航 |
| 下一步 | Next | 导航 |
| 完成 | Done | 操作 |
| 跳过 | Skip | 操作 |
| 刷新 | Refresh | 操作 |
| 下载 | Download | 操作 |
| 上传 | Upload | 操作 |
| 分享 | Share | 操作 |
| 收藏 | Favorite | 操作 |
| 点赞 | Like | 社交 |
| 评论 | Comment | 社交 |
| 关注 | Follow | 社交 |
| 加载 | Loading | 状态 |
| 成功 | Success | 提示 |
| 失败 | Failed | 提示 |
| 错误 | Error | 提示 |
| 警告 | Warning | 提示 |
| 确认 | Confirm | 操作 |
| 退出 | Exit | 操作 |
| 更新 | Update | 系统 |
| 权限 | Permission | 系统 |
| 隐私 | Privacy | 法律 |
| 反馈 | Feedback | 服务 |
| 客服 | Support | 服务 |

## Translation Quality Rules

1. **Placeholder protection**: `%s`, `%d`, `%u`, `{xxx}`, `{{xxx}}` must be preserved exactly.
2. **Format code protection**: HTML tags, `{wordsColor;...}`, `{gather;...}` must not be translated.
3. **Length awareness**: Flag with `[待确认]` if translation is >2x source length.
4. **Consistency**: Same source term must produce same translation. Enforced by `terms` parameter.
5. **Tone matching**: Preserve original tone. App UI should be concise and direct.
6. **No over-translation**: Simple confirmations like "OK", "Yes", "No" stay simple.
