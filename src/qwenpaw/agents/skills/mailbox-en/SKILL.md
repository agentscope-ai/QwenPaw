---
name: mailbox
description: "Use this skill whenever the user needs ANY mailbox/email operation — checking, reading, searching, sending, replying, forwarding, organizing or deleting email, managing threads, connecting a personal mailbox, or registering a new mailbox. This skill is the single entry point for email tasks and orchestrates qwenpawmail-mcp for nine supported personal-mail domains."
metadata:
  builtin_skill_version: "1.2"
  qwenpaw:
    emoji: "📧"
    requires:
      mcp: ["qwenpawmail-mcp"]
---

# Mailbox Operations (qwenpawmail-mcp)

Use **qwenpawmail-mcp** to connect or register a mailbox and perform email operations.

## Supported Providers

The managed QwenPaw mailbox workflow supports these nine mail domains:

| Provider | Domains | Login credential |
| --- | --- | --- |
| NetEase | `163.com`, `126.com`, `yeah.net` | 16-character authorization code |
| Tencent | `qq.com`, `foxmail.com` | 16-character authorization code |
| Sina | `sina.com`, `sina.cn` | 16-character authorization code |
| Alibaba | `aliyun.com` | Mailbox login password; existing accounts only |
| Google | `gmail.com` | 16-character app password after enabling 2-Step Verification |

Enterprise mailboxes, custom domains, and Microsoft mailboxes are not supported by the current managed workflow. Do not try enterprise provider overrides or custom IMAP/SMTP hosts. Ask the user to choose one of the supported personal domains instead.

`create_mailbox` provides built-in registration guidance only for `163.com`, `126.com`, `yeah.net`, `qq.com`, and `foxmail.com`. Other supported domains require their official registration flow. New `aliyun.com` registration is unavailable; only existing accounts can be connected.

## Invocation Rule

For any email operation, use this skill as the entry point. Do not invent another email workflow or bypass qwenpawmail-mcp with raw IMAP/SMTP commands.

## Credential and Configuration Model

`agent.json` contains only public mailbox configuration. Its expected mail shape is:

```json
{
  "mail": {
    "is_new_account": false,
    "credential": {
      "name": "myaccount",
      "domain": "163.com",
      "provider": ""
    },
    "push": {
      "mode": "off",
      "rules": [],
      "poll_interval_seconds": 120,
      "access_control_enabled": false
    }
  }
}
```

The sensitive fields `auth_code`, `password`, and `phone_number` are intentionally absent from `agent.json` and redacted from Agent API responses. The provider credential represented by `auth_code` is stored encrypted after it is configured. Registration passwords and phone numbers are entered only on the provider page and are not stored by the current QwenPaw workflow. The absence of `auth_code` from public configuration does **not** mean that the user did not configure it.

QwenPaw resolves the encrypted provider credential into the managed DriverCard only at runtime. Never read, decrypt, print, copy, or modify `credentials.yaml`, and never search files or logs for a secret. Use the workflows below.

## Workflow: Connect or Create the Mailbox Account

### Step 1 — Read public mailbox state

Read `mail.is_new_account`, `mail.credential.name`, and `mail.credential.domain` from `agent.json`. Treat `provider` as empty for every currently supported personal domain.

If `mail` is missing, ask the user to configure Email Management in the QwenPaw Agent Settings UI before continuing.

### Step 2a — `is_new_account` is `false`: manage an existing mailbox

1. Call `check_auth` directly. The managed DriverCard already receives the stored email credential through a runtime credential reference; do not look it up in `agent.json` and do not call `set_credentials` merely because secret fields are absent.
2. If `check_auth` succeeds, perform the requested mailbox operation.
3. If credentials are missing or invalid, ask the user to edit this agent in QwenPaw, choose **Manage your personal mailbox**, enter the mailbox credential again, and save. Retry `check_auth` after the agent reloads.
4. If the user explicitly supplies an email and credential in the current conversation, `set_credentials` may be used as a temporary session-only override, followed by `check_auth`. It does not update the encrypted QwenPaw configuration and is lost when the MCP process restarts.

For temporary `set_credentials`, pass the full email and the provider-specific credential in the `auth_code` parameter. For `aliyun.com`, that parameter contains the login password; for the other supported domains, it contains the 16-character authorization code or app password.

### Step 2b — `is_new_account` is `true`: register a dedicated mailbox

Use the public username and domain from `agent.json`. If the username is blank, let `create_mailbox` generate one or agree on one with the user.

Registration passwords and phone numbers are entered on the provider page and are deliberately unavailable to the Agent. Do not try to recover them from files. The optional credential field in the QwenPaw dedicated-mailbox form is only for the final provider authorization code, app password, or mailbox login password after registration. Use one of these paths:

#### Preferred path — visible browser registration

1. For NetEase or Tencent domains, call `create_mailbox(domain, username)` first to validate the username and obtain current provider guidance.
2. Open the provider's official registration page in a visible browser.
3. When the page requests a password, phone number, CAPTCHA, SMS code, or other identity verification, ask the user to enter it directly in the visible browser. If the user explicitly provides a value for this task, use it only for the current registration and never persist or repeat it.
4. Keep the browser open while waiting for user action, then continue after confirmation.

Official registration entry points:

| Domain | Registration entry | Notes |
| --- | --- | --- |
| `163.com`, `126.com`, `yeah.net` | `https://zc.reg.163.com/regInitialized` | Shared NetEase flow; phone verification required |
| `qq.com`, `foxmail.com` | `https://ssl.zc.qq.com/v3/index-chs.html` | QQ registration; phone verification required |
| `sina.com` | `https://mail.sina.com.cn/register/weixin.php` | WeChat-authorized registration |
| `sina.cn` | `https://mail.sina.cn/register/regmail.php` | Phone/SMS registration |
| `gmail.com` | `https://accounts.google.com/signup` | Enable 2-Step Verification, then create an app password |
| `aliyun.com` | Unavailable | New personal registrations are closed; use an existing account |

Consider registration successful only after a clear success message or successful inbox access. If the final username differs from the requested one, report the reason and final address.

#### Fallback path — user-completed registration

For NetEase or Tencent domains, call `create_mailbox(domain, username)` and relay its alternatives, registration URL, and steps. Ask the user to complete all password, phone, CAPTCHA, and SMS steps in their own browser.

For Sina or Gmail, direct the user to the official entry above. For `aliyun.com`, explain that a new account cannot be registered and ask the user to choose another supported domain.

### Step 3 — After successful registration

1. Do **not** write an authorization code, password, or phone number into `agent.json`.
2. Ask the user to edit the agent in the QwenPaw Agent Settings UI and keep **Provision a dedicated mailbox** selected. Enter the final mailbox name and the optional provider credential shown for that domain, then save. The field accepts a 16-character authorization code/app password for NetEase, Tencent, Sina, or Gmail, and a login password for a provider that uses one. QwenPaw will automatically set `is_new_account` to `false`, store the secret in encrypted form, synchronize the managed DriverCard, and reload the agent.
3. After reload, call `check_auth`. Do not run other mail tools until it succeeds.
4. Read `CONTACTS.md` before contact-dependent work.

## Available Tools

### Read-Only Tools

| Tool | Purpose |
| --- | --- |
| `list_folders` | List all mailbox folders |
| `list_messages` | List message envelopes in a folder with pagination |
| `get_message` | Fetch one message by folder and UID |
| `get_attachment` | Get an attachment by filename or index |
| `search_messages` | Search by keyword, sender, or date range |
| `check_auth` | Verify fresh IMAP and SMTP logins using the current runtime credential |
| `create_mailbox` | Return registration guidance for supported NetEase/Tencent domains |
| `list_threads` | List conversation threads with incremental sync |
| `search_threads` | Search conversation threads |
| `get_thread` | Get all messages in one thread |
| `get_mailbox_stats` | Get recent mailbox statistics |

### Write Tools

| Tool | Purpose |
| --- | --- |
| `send_message` | Send a plain-text email with to/cc/bcc |
| `reply_message` | Reply with proper threading headers |
| `forward_message` | Forward a message as an RFC 822 attachment |
| `mark_messages` | Mark messages read/unread/flagged/unflagged |
| `move_message` | Move a message to another folder |
| `create_folder` | Create a mailbox folder |
| `set_credentials` | Set a temporary in-memory credential for this MCP process |
| `clear_credentials` | Clear the temporary override and fall back to injected startup credentials |
| `update_thread` | Add or remove custom thread labels |

### Destructive Tools

| Tool | Purpose |
| --- | --- |
| `delete_message` | Permanently delete one message |
| `delete_thread` | Move a whole thread to trash |

## Safety and Reliability Notes

- Never guess or expose an authorization code, password, phone number, CAPTCHA, or SMS code.
- Never interpret redacted secret fields as empty credentials; verify with `check_auth`.
- Never place secrets in `agent.json`, DriverCard YAML, CONTACTS.md, logs, or chat summaries.
- Confirm with the user before `delete_message` or `delete_thread`.
- Message UIDs are folder-scoped and can change. Refresh with `list_messages` or `search_messages` immediately before acting.
- After any runtime or UI credential change, call `check_auth` first.
- Update `CONTACTS.md` when the user wants newly discovered contact information retained, but never store credentials there.
