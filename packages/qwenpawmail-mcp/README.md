# qwenpawmail-mcp

English | [中文](README_zh.md)

A stdio [MCP](https://modelcontextprotocol.io/) (Model Context Protocol) server that lets AI agents read, search, send, and organize email over IMAP/SMTP. Built as the mail subpackage of [QwenPaw](../../README.md), it also works standalone with any MCP-compatible client such as Claude Desktop.

## Features

- **22 tools** covering folders, messages, attachments, search, sending, threads, labels, and mailbox analytics — each annotated as read-only, write, or destructive so MCP clients can apply appropriate guardrails.
- **Automatic provider routing** — 12 built-in email domains (NetEase, Tencent QQ, Sina, Aliyun, Gmail, and major Chinese enterprise mail providers) resolve IMAP/SMTP endpoints from the email address alone; unknown domains work via explicit host overrides.
- **Local thread index** — messages are aggregated into conversation threads (References/In-Reply-To chains) with custom labels, incremental sync, and full-text thread search, stored as atomic-write JSON namespaced per mailbox so multiple accounts never pollute each other.
- **Robust by design**:
  - 30-second timeouts on all IMAP and SMTP connections
  - Fully async tool handlers — network I/O never blocks the event loop
  - Graceful shutdown on SIGTERM/SIGINT
  - Per-host connection throttling to avoid provider connection limits
  - Stateless connection model: every operation opens a fresh connection and closes it when done — no connection leaks
- **Conversational credential setup** — credentials can be provided at runtime through the `set_credentials` tool instead of environment variables. The server starts fine without any credentials.

## Supported Providers

The server routes IMAP/SMTP endpoints automatically based on the email domain — no manual host configuration needed for these 12 domains:

| Domain | Provider | IMAP | SMTP | Credential type |
| --- | --- | --- | --- | --- |
| 163.com | NetEase 163 | imap.163.com:993 | smtp.163.com:465 | Authorization code |
| 126.com | NetEase 126 | imap.126.com:993 | smtp.126.com:465 | Authorization code |
| yeah.net | NetEase yeah.net | imap.yeah.net:993 | smtp.yeah.net:465 | Authorization code |
| qq.com | Tencent QQ Mail | imap.qq.com:993 | smtp.qq.com:465 | Authorization code |
| foxmail.com | Tencent QQ Mail (alias) | imap.qq.com:993 | smtp.qq.com:465 | Authorization code |
| sina.com | Sina Mail | imap.sina.com:993 | smtp.sina.com:465 | Authorization code |
| sina.cn | Sina Mail (sina.cn) | imap.sina.cn:993 | smtp.sina.cn:465 | Authorization code |
| aliyun.com | Aliyun Mail | imap.aliyun.com:993 | smtp.aliyun.com:465 | Login password |
| gmail.com | Gmail | imap.gmail.com:993 | smtp.gmail.com:465 | App-specific password |
| exmail.qq.com | Tencent Exmail | imap.exmail.qq.com:993 | smtp.exmail.qq.com:465 | Client-specific password |
| qiye.aliyun.com | Aliyun Enterprise Mail | imap.qiye.aliyun.com:993 | smtp.qiye.aliyun.com:465 | Login/security password |
| qiye.163.com | NetEase Enterprise Mail | imap.qiye.163.com:993 | smtp.qiye.163.com:**994** | Login password |

Any other domain (e.g. enterprise mail on a custom company domain) is supported by setting `QWENPAWMAIL_IMAP_HOST` / `QWENPAWMAIL_SMTP_HOST` explicitly — see [Configuration](#configuration).

## How It Works

qwenpawmail-mcp is a pure-Python (>= 3.10) MCP server built on the FastMCP SDK (`mcp>=1.28`) plus `imap-tools`, communicating over **stdio**.

Within QwenPaw, the main process spawns it automatically as a subprocess (`sys.executable -m qwenpawmail_mcp`) and injects credentials and state directories through environment variables — users never start it by hand. Outside QwenPaw, any MCP client that supports stdio transport (Claude Desktop, Cursor, etc.) can launch it the same way.

## Installation

This package lives in the QwenPaw monorepo under `packages/qwenpawmail-mcp/` and is not published to PyPI.

**Option 1: With QwenPaw** (installs the main project and this subpackage together):

```bash
make install-dev
```

**Option 2:Standalone** (subpackage only, from the repo root):

```bash
make install-mail-mcp
# or equivalently:
pip install -e packages/qwenpawmail-mcp
```

**Docker**: the main project's Dockerfile already copies and installs this package — no extra steps.

## Configuration

All settings are environment variables. Credentials are **optional at startup** — they can also be supplied at runtime via the `set_credentials` tool.

| Variable | Required | Description |
| --- | --- | --- |
| `QWENPAWMAIL_EMAIL` | For mail ops* | Full email address, e.g. `someone@163.com` |
| `QWENPAWMAIL_AUTH_CODE` | For mail ops* | Login credential — **semantics vary by provider** (see below) |
| `QWENPAWMAIL_IMAP_HOST` | Unknown domains | IMAP host override for domains not in the built-in table |
| `QWENPAWMAIL_IMAP_PORT` | No | IMAP port override (default: provider value or 993) |
| `QWENPAWMAIL_SMTP_HOST` | Unknown domains | SMTP host override for domains not in the built-in table |
| `QWENPAWMAIL_SMTP_PORT` | No | SMTP port override (default: provider value or 465) |
| `QWENPAWMAIL_STATE_DIR` | No | State directory for the local thread/label index; defaults to `~/.qwenpawmail-mcp/state/<email>/` (QwenPaw points it at the agent workspace's `mail_state/`) |
| `QWENPAWMAIL_WORKSPACE_DIR` | No | Agent workspace root, used to resolve relative attachment save paths (injected by QwenPaw) |

\* The server starts without credentials; tools that need them return a friendly error until credentials are set via env or `set_credentials`.

> **About `QWENPAWMAIL_AUTH_CODE`**: this is *not* necessarily your login password. Its meaning depends on the provider:
> - **NetEase / QQ / Sina** — the 16-character *authorization code* generated in webmail settings (not the account password)
> - **Gmail** — a 16-character *app-specific password* (requires 2-Step Verification)
> - **Aliyun Mail / Aliyun Enterprise / NetEase Enterprise** — the login or security password
> - **Tencent Exmail** — the client-specific password

Example for a custom enterprise domain:

```bash
export QWENPAWMAIL_EMAIL="someone@mycompany.com"
export QWENPAWMAIL_AUTH_CODE="your-credential"
export QWENPAWMAIL_IMAP_HOST="imap.mycompany.com"
export QWENPAWMAIL_SMTP_HOST="smtp.mycompany.com"
```

## Tools Reference (22 tools in three categories)

### Read-only (11)

| Tool | Description |
| --- | --- |
| `check_auth` | Verify that IMAP and SMTP logins both succeed (recommended first call) |
| `list_folders` | List all folders (Chinese names auto-decoded from modified UTF-7) |
| `list_messages` | Page through message envelopes (folder / limit ≤ 100 / offset; no bodies fetched) |
| `get_message` | Fetch one message's text/html body and attachment metadata by UID |
| `get_attachment` | Download an attachment by filename or index (base64 or save to disk) |
| `search_messages` | Search by keyword, sender, and/or date range |
| `create_mailbox` | Guided registration for a new mailbox: validates usernames, suggests alternatives, returns signup links and step-by-step instructions |
| `list_threads` | List conversation threads filtered by labels/sender/recipient/subject/date, newest first |
| `search_threads` | Full-text search across INBOX + Sent, mapped to threads, ranked by hits + recency |
| `get_thread` | Fetch all message envelopes in a thread, oldest first |
| `get_mailbox_stats` | Mailbox insights over the last N days: volumes, top senders/recipients, daily trend, response times, pending replies, attachment stats |

### Write (9)

| Tool | Description |
| --- | --- |
| `send_message` | Send a plain-text email (to/cc/bcc/subject/body) |
| `reply_message` | Reply with automatic In-Reply-To/References headers and `Re:` prefix |
| `forward_message` | Forward with the original message attached as rfc822 and `Fwd:` prefix |
| `mark_messages` | Bulk mark read/unread/flag/unflag |
| `move_message` | Move a message to another folder |
| `create_folder` | Create a folder (Chinese names auto-encoded to modified UTF-7) |
| `set_credentials` | Set/update mailbox credentials at runtime (overrides env; unknown domains also need imap_host/smtp_host) |
| `clear_credentials` | Clear runtime credentials (falls back to env, if set) |
| `update_thread` | Add/remove custom labels on a thread (system labels `inbox`/`sent`/`spam`/`trash` are read-only) |

### Destructive (2)

| Tool | Description |
| --- | --- |
| `delete_message` | Mark a message `\Deleted` and immediately remove it with RFC 4315 UID EXPUNGE when supported. Cleanup is scoped to the given UID; global EXPUNGE is never used |
| `delete_thread` | Move every message in a thread to Trash and drop the thread from the index |

For domains outside the built-in provider table, add `QWENPAWMAIL_IMAP_HOST` and `QWENPAWMAIL_SMTP_HOST` to `env`.

## Security Notes

- **Treat the authorization code like a password.** It grants full IMAP/SMTP access to the mailbox. Never commit it, log it, or share it. It can be revoked and regenerated at any time in your provider's webmail settings.
- **Destructive tools** (`delete_message`, `delete_thread`) are annotated as destructive via MCP tool annotations — clients should require confirmation before invoking them.
- QQ Mail invalidates existing authorization codes when the account password changes; regenerate if authentication suddenly fails.
- Credentials set via `set_credentials` live only in server process memory and are gone when the process exits.

## License

MIT
