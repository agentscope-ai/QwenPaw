---
name: feishu_cloud_doc
description: "当用户需要操作飞书/Lark 云文档时使用此 skill。涵盖四大模块：1) 在线文档（Docx）— 创建、读取、编辑飞书文档；2) 电子表格（Sheets）— 创建、读写飞书表格；3) 多维表格（Bitable）— 创建多维表格、管理字段和记录；4) 知识库（Wiki）— 管理知识空间和节点。触发关键词：飞书文档、飞书表格、飞书多维表格、飞书知识库、Feishu doc、Lark doc、云文档、在线文档、在线表格。不适用于本地 .docx/.xlsx 文件操作（那是 docx/xlsx skill 的职责）。"
metadata:
  builtin_skill_version: "1.0"
  qwenpaw:
    emoji: "📝"
    requires:
      envs: ["FEISHU_APP_ID", "FEISHU_APP_SECRET"]
      bins: []
---

> **Important:** All `scripts/` paths are relative to this skill directory.
> Run with: `cd {this_skill_dir} && python scripts/...`
> Or use the `cwd` parameter of `execute_shell_command`.

# Feishu Cloud Document Skill

Operate on Feishu/Lark cloud documents via the Open API. Covers **Documents**, **Spreadsheets**, **Bitables** (multi-dimensional tables), and **Wiki** (knowledge base).

## Prerequisites

- **httpx**: HTTP client (already included in QwenPaw dependencies)
- **Feishu App credentials**: `FEISHU_APP_ID` and `FEISHU_APP_SECRET` (env vars or `~/.qwenpaw/config.json` → `channels.feishu`)
- **App permissions** (enable in Feishu developer console):
  - `docx:document` / `docx:document:readonly` — Documents
  - `sheets:spreadsheet` / `sheets:spreadsheet:readonly` — Spreadsheets
  - `bitable:app` / `bitable:app:readonly` — Bitables
  - `wiki:wiki` / `wiki:wiki:readonly` — Wiki
  - `drive:drive` — Cloud space access
  - `drive:permission` — Permission management (sharing)

## Authentication

All scripts auto-obtain `tenant_access_token`. Credentials resolved in order:
1. Env vars: `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, `FEISHU_DOMAIN`
2. Config: `~/.qwenpaw/config.json` → `channels.feishu`

Set `FEISHU_DOMAIN=lark` for international (Lark) endpoints; default is `feishu` (China).

---

## Module 1: Documents (Docx)

### Quick Reference

| Task | Command |
|------|---------|
| Create document | `python scripts/doc_create.py --title "Title" [--folder TOKEN]` |
| Read plain text | `python scripts/doc_read.py --doc-id ID --format raw` |
| Read block tree | `python scripts/doc_read.py --doc-id ID --format blocks` |
| Get doc metadata | `python scripts/doc_read.py --doc-id ID --format info` |
| Add content blocks | `python scripts/doc_edit.py --doc-id ID --blocks-json '[...]'` |
| Add from file | `python scripts/doc_edit.py --doc-id ID --blocks-file path.json` |
| Insert at position | `python scripts/doc_edit.py --doc-id ID --blocks-json '[...]' --index 0` |
| Delete block by ID | `python scripts/doc_edit.py --doc-id ID --action delete --block-id BID` |
| Delete by text (substring) | `python scripts/doc_edit.py --doc-id ID --action delete-by-text --text "content"` |
| Delete by text (exact) | `python scripts/doc_edit.py --doc-id ID --action delete-by-text --text "content" --exact` |

### Block Types

| Type | Name | Content Key |
|------|------|-------------|
| 2 | Text | `text` |
| 3–8 | Heading 1–6 | `heading1`–`heading6` |
| 9 | Bullet list | `bullet` |
| 10 | Ordered list | `ordered` |
| 12 | Code block | `code` |
| 14 | Divider | — |
| 15 | Callout | `callout` |

### Block Element Structure

```json
{"block_type": 3, "heading1": {"elements": [{"text_run": {"content": "Title", "text_element_style": {"bold": true}}}]}}
```

Code block language codes: 1=PlainText, 7=Python, 12=Java, 15=JavaScript, 22=Go, 33=SQL, 40=Bash

### Example: Create doc with content

```bash
python scripts/doc_create.py --title "Meeting Notes"
# → get document_id from output

python scripts/doc_edit.py --doc-id DOC_ID --blocks-json '[
  {"block_type": 3, "heading1": {"elements": [{"text_run": {"content": "Agenda"}}]}},
  {"block_type": 9, "bullet": {"elements": [{"text_run": {"content": "Item 1"}}]}},
  {"block_type": 9, "bullet": {"elements": [{"text_run": {"content": "Item 2"}}]}}
]'

python scripts/share.py --token DOC_ID --type docx --public --link-access tenant_readable
```

---

## Module 2: Spreadsheets (Sheets)

### Quick Reference

| Task | Command |
|------|---------|
| Create spreadsheet | `python scripts/sheet_create.py --title "Title" [--folder TOKEN]` |
| Get info | `python scripts/sheet_read.py --token TOKEN --info` |
| List worksheets | `python scripts/sheet_read.py --token TOKEN --list-sheets` |
| Read range | `python scripts/sheet_read.py --token TOKEN --range "Sheet1!A1:D10"` |
| Write range | `python scripts/sheet_write.py --token TOKEN --range "Sheet1!A1:B2" --values-json '[["a","b"],[1,2]]'` |
| Append rows | `python scripts/sheet_write.py --token TOKEN --range "Sheet1!A1" --append --values-json '[["c",3]]'` |
| Add worksheet | `python scripts/sheet_write.py --token TOKEN --add-sheet --sheet-title "Sheet2"` |

### Value Types

- String: `"text"`, Number: `123`, Boolean: `true`/`false`, Empty: `null`, Formula: `"=SUM(A1:A10)"`

### Example: Create and populate

```bash
python scripts/sheet_create.py --title "Q1 Report"
python scripts/sheet_write.py --token TOKEN --range "Sheet1!A1:C1" --values-json '[["Date","Revenue","Cost"]]'
python scripts/sheet_write.py --token TOKEN --range "Sheet1!A2" --append --values-json '[["Jan",50000,30000],["Feb",55000,32000]]'
```

---

## Module 3: Bitable (Multi-dimensional Table)

### Quick Reference

| Task | Command |
|------|---------|
| Create bitable | `python scripts/bitable_manage.py create --name "Tracker" [--folder TOKEN]` |
| List tables | `python scripts/bitable_manage.py list-tables --app-token TOKEN` |
| Add table | `python scripts/bitable_manage.py add-table --app-token TOKEN --table-name "Tasks"` |
| List fields | `python scripts/bitable_manage.py list-fields --app-token TOKEN --table-id TID` |
| Add field | `python scripts/bitable_manage.py add-field --app-token TOKEN --table-id TID --field-name "Status" --field-type 3` |
| List records | `python scripts/bitable_records.py list --app-token TOKEN --table-id TID [--page-size 50]` |
| Get record | `python scripts/bitable_records.py get --app-token TOKEN --table-id TID --record-id RID` |
| Create record | `python scripts/bitable_records.py create --app-token TOKEN --table-id TID --fields-json '{...}'` |
| Batch create | `python scripts/bitable_records.py batch-create --app-token TOKEN --table-id TID --records-json '[...]'` |
| Update record | `python scripts/bitable_records.py update --app-token TOKEN --table-id TID --record-id RID --fields-json '{...}'` |
| Delete record | `python scripts/bitable_records.py delete --app-token TOKEN --table-id TID --record-id RID` |

### Field Types

| ID | Type | Value Format |
|----|------|-------------|
| 1 | Text | `"text"` |
| 2 | Number | `123.45` |
| 3 | SingleSelect | `"Option A"` |
| 4 | MultiSelect | `["A", "B"]` |
| 5 | DateTime | `1704067200000` (Unix ms) |
| 7 | Checkbox | `true`/`false` |
| 13 | Link | `{"text": "t", "link": "url"}` |

**Important**: Use field IDs (e.g. `fldXXXXXX`) not field names when creating/updating records. Get IDs via `list-fields`.

---

## Module 4: Wiki (Knowledge Base)

### Quick Reference

| Task | Command |
|------|---------|
| List spaces | `python scripts/wiki.py list-spaces` |
| Create space | `python scripts/wiki.py create-space --name "Wiki" [--description "..."]` |
| List root nodes | `python scripts/wiki.py list-nodes --space-id SID` |
| List child nodes | `python scripts/wiki.py list-nodes --space-id SID --parent-node-token TOKEN` |
| Get node info | `python scripts/wiki.py get-node --space-id SID --node-token TOKEN` |
| Create doc node | `python scripts/wiki.py create-node --space-id SID --obj-type docx --title "Page"` |
| Create child node | `python scripts/wiki.py create-node --space-id SID --obj-type docx --title "Sub" --parent-node-token TOKEN` |
| Move node | `python scripts/wiki.py move-node --space-id SID --node-token TOKEN --target-parent-token PARENT` |

Supported `--obj-type`: `docx`, `sheet`, `bitable`, `mindnote`, `slides`

**Key concept**: `get-node` returns `obj_token` — use it with the corresponding module to read/edit content (e.g. `doc_read.py --doc-id <obj_token>`).

---

## Sharing & Permissions

Works for all document types (docx, sheet, bitable, wiki):

```bash
# Share with a user by open_id
python scripts/share.py --token TOKEN --type docx --member-type openid --member-id ou_xxx --perm view

# Share by email
python scripts/share.py --token TOKEN --type sheet --member-type email --member-id user@example.com --perm edit

# Set org-wide link sharing
python scripts/share.py --token TOKEN --type bitable --public --link-access tenant_readable

```

`--type` values: `docx`, `sheet`, `bitable`, `wiki`, `file`, `folder`
`--perm` values: `view`, `edit`, `full_access`
`--link-access` values: `tenant_readable`, `tenant_editable`, `anyone_readable`, `anyone_editable`

---

## Error Handling

All scripts output JSON with `"success": true/false`. Common error codes:
- `99991668`: No permission — check app permissions
- `99991672`: Resource not found
- `99991663`: Rate limit — wait and retry
- `1254043`: Bitable permission error — add app as collaborator
