---
name: himalaya
description: "CLI to manage emails via IMAP/SMTP. Use `himalaya` to list, read, write, reply, forward, search, and organize emails from the terminal. Supports multiple accounts and message composition with MML (MIME Meta Language)."
homepage: https://github.com/pimalaya/himalaya
metadata:
  builtin_skill_version: "1.3"
  qwenpaw:
    emoji: "📧"
    requires:
      bins:
        - himalaya
    install:
      - id: brew
        kind: brew
        formula: himalaya
        bins:
          - himalaya
        label: "Install Himalaya (brew)"
---
# Himalaya Email CLI

Himalaya is a CLI email client that lets you manage emails from the terminal using IMAP, SMTP, Notmuch, or Sendmail backends.

## References

- `references/configuration.md` (config file setup + IMAP/SMTP authentication)

## Prerequisites

1. **Himalaya CLI** - the `himalaya` binary must already be on `PATH`. Check with `himalaya --version`.
   - **Recommended: v1.2.0 or newer.** Older releases can fail against some IMAP servers; v1.2.0+ includes related fixes.
2. A configuration file at `~/.config/himalaya/config.toml`
3. IMAP/SMTP credentials configured (password stored securely)

## Configuration Setup

Run the interactive wizard to set up an account (replace `default` with
any name you want, e.g. `gmail`, `work`):

```bash
himalaya account configure default
```

Or create `~/.config/himalaya/config.toml` manually:

```toml
[accounts.personal]
email = "you@example.com"
display-name = "Your Name"
default = true

backend.type = "imap"
backend.host = "imap.example.com"
backend.port = 993
backend.encryption.type = "tls"
backend.login = "you@example.com"
backend.auth.type = "password"
backend.auth.cmd = "pass show email/imap"  # or use keyring

message.send.backend.type = "smtp"
message.send.backend.host = "smtp.example.com"
message.send.backend.port = 587
message.send.backend.encryption.type = "start-tls"
message.send.backend.login = "you@example.com"
message.send.backend.auth.type = "password"
message.send.backend.auth.cmd = "pass show email/smtp"
```

If you are using 163 mail account, add `backend.extensions.id.send-after-auth = true` in the config file to ensure proper functionality.

## Common Operations

### List Folders

```bash
himalaya folder list
```

### List Emails

List emails in INBOX (default):

```bash
himalaya envelope list
```

List emails in a specific folder:

```bash
himalaya envelope list --folder "Sent"
```

List with pagination:

```bash
himalaya envelope list --page 1 --page-size 20
```

If meet with error, try:

```bash
himalaya envelope list -f INBOX -s 1
```

### Search Emails

```bash
himalaya envelope list from john@example.com subject meeting
```

### Read an Email

Read email by ID (shows plain text):

```bash
himalaya message read 42
```

Export raw MIME:

```bash
himalaya message export 42 --full
```

### Send / Compose Emails

**Recommended approach:** Use `template write | template send` pipeline for simple emails.

**Send a simple email:**

```bash
export EDITOR=cat
himalaya template write \
  -H "To: recipient@example.com" \
  -H "Subject: Email Subject" \
  "Email body content" | himalaya template send
```

**Send with multiple headers:**

```bash
export EDITOR=cat
himalaya template write \
  -H "To: recipient@example.com" \
  -H "Cc: cc@example.com" \
  -H "Subject: Email Subject" \
  "Email body content" | himalaya template send
```

**Send with attachments (using Python):**

For emails with attachments, use Python's `smtplib` and `email.mime` modules:

```python
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

msg = MIMEMultipart()
msg['From'] = 'sender@163.com'
msg['To'] = 'recipient@example.com'
msg['Subject'] = 'Email with attachment'

msg.attach(MIMEText('Email body', 'plain'))

# Add attachment
with open('/path/to/file.pdf', 'rb') as f:
    part = MIMEBase('application', 'octet-stream')
    part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header('Content-Disposition', 'attachment; filename="file.pdf"')
    msg.attach(part)

server = smtplib.SMTP_SSL('smtp.163.com', 465)
server.login('sender@163.com', 'password')
server.send_message(msg)
server.quit()
```

**⚠️ MML attachment limitations:** The `template send` command with MML format may fail with "cannot parse MML message: empty body" when using multipart/attachments. This is a known issue in himalaya v1.1.0. Use Python approach for attachments.

**⚠️ Avoid `message write` for automation:** The `himalaya message write` command requires interactive TUI selection (Edit/Discard/Quit) and will hang in non-interactive environments.

**⚠️ `message send` limitations:** Direct `himalaya message send <raw_email>` may fail with "cannot send message without a recipient" due to header parsing issues. Use `template send` instead.

**Configuration requirement:** Ensure `message.send.save-to-folder` is set in config.toml to avoid "Folder not exist" errors:

```toml
[accounts.163]
# ... other config ...
message.send.save-to-folder = "Sent"
```

For 163 mail accounts, create the Sent folder first if it doesn't exist:

```bash
himalaya folder create Sent
```

### Move/Copy Emails

Move to folder:

```bash
himalaya message move 42 "Archive"
```

Copy to folder:

```bash
himalaya message copy 42 "Important"
```

### Delete an Email

```bash
himalaya message delete 42
```

### Manage Flags

Add flag:

```bash
himalaya flag add 42 --flag seen
```

Remove flag:

```bash
himalaya flag remove 42 --flag seen
```

## Multiple Accounts

List accounts:

```bash
himalaya account list
```

Use a specific account:

```bash
himalaya --account work envelope list
```

## Attachments

Save attachments from a message:

```bash
himalaya attachment download 42
```

Save to specific directory:

```bash
himalaya attachment download 42 --dir ~/Downloads
```

## Output Formats

Most commands support `--output` for structured output:

```bash
himalaya envelope list --output json
himalaya envelope list --output plain
```

## Debugging

Enable debug logging:

```bash
RUST_LOG=debug himalaya envelope list
```

Full trace with backtrace:

```bash
RUST_LOG=trace RUST_BACKTRACE=1 himalaya envelope list
```

## Tips

- Use `himalaya --help` or `himalaya <command> --help` for detailed usage.
- Message IDs are relative to the current folder; re-list after folder changes.
- For composing rich emails with attachments, use MML syntax (see `references/message-composition.md`).
- Store passwords securely using `pass`, system keyring, or a command that outputs the password.
- **For automation:** Always use `template write | template send` pipeline with `export EDITOR=cat`.
- **163 Mail users:** Set `backend.extensions.id.send-after-auth = true` and `message.send.save-to-folder = "Sent"` in config.
- **Folder names:** Use English folder names (e.g., "Sent" instead of "已发送") for better compatibility.
