---
name: app-localization-translator
description: "Batch translates app localization text using qwen-mt MCP. Reads Excel source files, translates with glossary and translation memory support, outputs three-column Excel (Original | Translation | Tips). Use when user asks to translate Excel files, localize apps, do i18n translation, or mentions 翻译、本地化、多语言."
---

# App Localization Translator

Batch translate app localization text via the qwen-mt MCP `translate` tool. Output: three-column Excel (原文 | 译文 | Tips).

## Prerequisites

This skill requires the **qwen-mt MCP** to be configured and available. It provides two tools:

- `translate` — translate text with glossary terms, translation memory, and domain hints
- `get_supported_languages` — list supported languages

If the MCP tools are not available, remind the user to configure qwen-mt MCP first.

## Persistent Data (Glossary & Translation Memory)

This skill maintains two JSON files in the skill directory to accumulate translation knowledge across sessions:

- **`glossary.json`** — glossary terms, grows as you translate more projects
- **`tm.json`** — translation memory, stores high-quality source→target pairs

Both files are at: `~/.qoderwork/skills/app-localization-translator/`

### On every session start

1. Read `glossary.json`. If it doesn't exist, create it from the Default Glossary Terms section below.
2. Read `tm.json`. If it doesn't exist, create it as `{"pairs": []}`.
3. Merge the loaded glossary into the `terms` parameter for every `translate` call.
4. Select up to 10 relevant pairs from `tm.json` for the `tm_list` parameter (pick pairs most similar to the current text being translated).

### After each batch completes

1. **Update glossary**: If the user confirmed new terms during translation (or you identified recurring translations that should be standardized), append them to `glossary.json`. Deduplicate by source field.
2. **Update translation memory**: Append 10-20 high-quality translations from this batch to `tm.json`. Prefer pairs that are representative, unambiguous, and confirmed correct. Cap `tm.json` at 500 pairs total — when exceeding, remove the oldest entries.
3. Save both files immediately.

### File formats

**glossary.json:**
```json
{
  "version": "1.0",
  "terms": [
    {"source": "设置", "target": "Settings", "category": "UI"},
    {"source": "登录", "target": "Login", "category": "账户"}
  ]
}
```

**tm.json:**
```json
{
  "version": "1.0",
  "pairs": [
    {"source": "登录成功", "target": "Login Successful"},
    {"source": "密码错误，请重试", "target": "Incorrect Password. Please Try Again"}
  ]
}
```

## Workflow

### Step 1: Confirm parameters

Ask the user:

1. **Source & target language** (default: Chinese → English)
2. **Domain hint** for specialized style (e.g. `"game"`, `"social"`, `"e-commerce"`, `"IT"`)
3. **Which column(s)** in the Excel need translation
4. **Custom glossary terms** — any project-specific terms beyond the defaults

### Step 2: Read source Excel

Use the **xlsx skill** to read the user's Excel file. Identify the column(s) to translate and the total row count.

### Step 3: Translate

Call the MCP `translate` tool for each text entry:

```
translate(
  text: "待翻译文本",
  target_lang: "English",
  source_lang: "Chinese",
  model: "qwen-mt-plus",
  terms: [glossary terms array],
  tm_list: [translation memory array],
  domains: "domain hint"
)
```

**Important rules:**

- Translate each row individually to preserve context and accuracy.
- Always pass the `terms` parameter loaded from `glossary.json` (plus any user-provided terms for this session).
- Pass the `tm_list` parameter with up to 10 relevant pairs from `tm.json`. Select pairs that are contextually similar to the current text.
- Report progress to the user every 50 rows.
- After each batch, update `glossary.json` and `tm.json` per the Persistent Data rules above.

### Step 4: Generate Tips

For each translated row, generate a Tips annotation in column C:

| Tag | When to use | Example |
|-----|-------------|---------|
| `[术语]` | Used a glossary term | `[术语] 设置→Settings` |
| `[占位符]` | Contains %s, %d, {xxx} etc. | `[占位符] %s preserved` |
| `[待确认]` | Translation uncertain | `[待确认] ambiguous source` |
| `[文化适配]` | Cultural adaptation applied | `[文化适配] localized expression` |
| `[格式代码]` | Contains HTML/format codes | `[格式代码] tags preserved` |

Leave Tips empty if nothing noteworthy.

### Step 5: Output Excel

Use the **xlsx skill** to create the result file with three columns:

| A: 原文 | B: 译文 | C: Tips |
|---------|---------|---------|
| 登录成功 | Login Successful | `[术语] 登录→Login` |
| 玩家%s已离线 | Player %s is offline | `[占位符] %s` |

**Styling:**

- Header row: blue background (#4472C4), white bold font, centered
- Tips cells with content: light yellow background (#FFFF99)
- Column widths: A=50, B=50, C=30
- All cells: wrap text, top-aligned

**File naming:** `翻译结果.xlsx` (single batch) or `翻译结果_批次N.xlsx` (multiple batches)

### Step 6: Large files (>100 rows)

For files with more than 100 rows:

- Split into batches of 100 rows each.
- Generate a separate Excel file per batch.
- After all batches, provide a summary: total rows, batches completed, terms used, Tips count.

## Default Glossary Terms (Initial Seed)

These are the initial terms used to create `glossary.json` on first run. Once the file exists, the agent always reads from `glossary.json` instead (which will contain these plus any accumulated terms).

```json
[
  {"source": "设置", "target": "Settings"},
  {"source": "确定", "target": "OK"},
  {"source": "取消", "target": "Cancel"},
  {"source": "保存", "target": "Save"},
  {"source": "删除", "target": "Delete"},
  {"source": "编辑", "target": "Edit"},
  {"source": "搜索", "target": "Search"},
  {"source": "登录", "target": "Login"},
  {"source": "注册", "target": "Sign Up"},
  {"source": "密码", "target": "Password"},
  {"source": "首页", "target": "Home"},
  {"source": "我的", "target": "Mine"},
  {"source": "消息", "target": "Messages"},
  {"source": "通知", "target": "Notifications"},
  {"source": "返回", "target": "Back"},
  {"source": "下一步", "target": "Next"},
  {"source": "完成", "target": "Done"},
  {"source": "跳过", "target": "Skip"},
  {"source": "刷新", "target": "Refresh"},
  {"source": "下载", "target": "Download"},
  {"source": "上传", "target": "Upload"},
  {"source": "分享", "target": "Share"},
  {"source": "收藏", "target": "Favorite"},
  {"source": "点赞", "target": "Like"},
  {"source": "评论", "target": "Comment"},
  {"source": "关注", "target": "Follow"},
  {"source": "加载", "target": "Loading"},
  {"source": "成功", "target": "Success"},
  {"source": "失败", "target": "Failed"},
  {"source": "错误", "target": "Error"},
  {"source": "警告", "target": "Warning"},
  {"source": "确认", "target": "Confirm"},
  {"source": "退出", "target": "Exit"},
  {"source": "更新", "target": "Update"},
  {"source": "权限", "target": "Permission"},
  {"source": "隐私", "target": "Privacy"},
  {"source": "反馈", "target": "Feedback"},
  {"source": "客服", "target": "Support"}
]
```

## Translation Quality Rules

1. **Placeholder protection**: `%s`, `%d`, `%u`, `{xxx}`, `{{xxx}}` must be preserved exactly as-is.
2. **Format code protection**: HTML tags, `{wordsColor;...}`, `{gather;...}` etc. must not be translated.
3. **Length awareness**: UI strings should not be significantly longer than the original — flag with `[待确认]` if >2x length.
4. **Consistency**: Same source term → same translation throughout. The `terms` parameter enforces this.
5. **Tone matching**: Preserve the original tone (formal/casual). App UI is typically concise and direct.
6. **No over-translation**: Short confirmations like "OK", "Yes", "No" should stay simple.
