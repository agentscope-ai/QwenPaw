---
name: himalaya
description: "通过 IMAP/SMTP 管理邮件的命令行工具。使用 `himalaya` 可以在终端中列出、阅读、撰写、回复、转发、搜索和整理邮件。支持多账户和使用 MML（MIME Meta Language）撰写邮件。"
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
# Himalaya 邮件命令行工具

Himalaya 是一个命令行邮件客户端，可以通过 IMAP、SMTP、Notmuch 或 Sendmail 后端在终端中管理邮件。

## 参考资料

- `references/configuration.md`（配置文件设置 + IMAP/SMTP 认证）

## 前置条件

1. **Himalaya CLI** - `himalaya` 二进制文件必须已在 `PATH` 中。通过 `himalaya --version` 检查。
   - **推荐使用 v1.2.0 或更新版本。** 旧版本在某些 IMAP 服务器上可能会失败；v1.2.0+ 包含了相关修复。
2. 配置文件位于 `~/.config/himalaya/config.toml`
3. 已配置 IMAP/SMTP 凭据（密码安全存储）

## 配置设置

运行交互式向导来设置账户（将 `default` 替换为你想要的名称，例如 `gmail`、`work`）：

```bash
himalaya account configure default
```

或手动创建 `~/.config/himalaya/config.toml`：

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
backend.auth.cmd = "pass show email/imap"  # 或使用 keyring

message.send.backend.type = "smtp"
message.send.backend.host = "smtp.example.com"
message.send.backend.port = 587
message.send.backend.encryption.type = "start-tls"
message.send.backend.login = "you@example.com"
message.send.backend.auth.type = "password"
message.send.backend.auth.cmd = "pass show email/smtp"
```

如果你使用的是 163 邮箱账户，请在配置文件中添加 `backend.extensions.id.send-after-auth = true` 以确保正常运作。

## 常用操作

### 列出文件夹

```bash
himalaya folder list
```

### 列出邮件

列出收件箱（默认）中的邮件：

```bash
himalaya envelope list
```

列出指定文件夹中的邮件：

```bash
himalaya envelope list --folder "Sent"
```

分页列出：

```bash
himalaya envelope list --page 1 --page-size 20
```

如果遇到错误，请尝试：

```bash
himalaya envelope list -f INBOX -s 1
```

### 搜索邮件

```bash
himalaya envelope list from john@example.com subject meeting
```

### 阅读邮件

通过 ID 阅读邮件（显示纯文本）：

```bash
himalaya message read 42
```

导出原始 MIME：

```bash
himalaya message export 42 --full
```

### 发送 / 撰写邮件

**推荐方式：** 使用 `template write | template send` 管道来发送简单邮件。

**发送一封简单邮件：**

```bash
export EDITOR=cat
himalaya template write \
  -H "To: recipient@example.com" \
  -H "Subject: Email Subject" \
  "Email body content" | himalaya template send
```

**发送带多个头字段的邮件：**

```bash
export EDITOR=cat
himalaya template write \
  -H "To: recipient@example.com" \
  -H "Cc: cc@example.com" \
  -H "Subject: Email Subject" \
  "Email body content" | himalaya template send
```

**发送带附件的邮件（使用 Python）：**

对于带附件的邮件，请使用 Python 的 `smtplib` 和 `email.mime` 模块：

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

# 添加附件
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

**注意：MML 附件限制：** 使用 MML 格式的 `template send` 命令在处理 multipart/附件时可能会失败，报错 "cannot parse MML message: empty body"。这是 himalaya v1.1.0 的已知问题。发送附件请使用 Python 方式。

**注意：避免在自动化中使用 `message write`：** `himalaya message write` 命令需要交互式 TUI 选择（Edit/Discard/Quit），在非交互式环境中会挂起。

**注意：`message send` 的限制：** 直接使用 `himalaya message send <raw_email>` 可能会因头字段解析问题而失败，报错 "cannot send message without a recipient"。请改用 `template send`。

**配置要求：** 确保在 config.toml 中设置了 `message.send.save-to-folder`，以避免 "Folder not exist" 错误：

```toml
[accounts.163]
# ... 其他配置 ...
message.send.save-to-folder = "Sent"
```

对于 163 邮箱账户，如果已发送文件夹不存在，请先创建：

```bash
himalaya folder create Sent
```

### 移动/复制邮件

移动到文件夹：

```bash
himalaya message move 42 "Archive"
```

复制到文件夹：

```bash
himalaya message copy 42 "Important"
```

### 删除邮件

```bash
himalaya message delete 42
```

### 管理标记

添加标记：

```bash
himalaya flag add 42 --flag seen
```

移除标记：

```bash
himalaya flag remove 42 --flag seen
```

## 多账户

列出账户：

```bash
himalaya account list
```

使用指定账户：

```bash
himalaya --account work envelope list
```

## 附件

保存邮件中的附件：

```bash
himalaya attachment download 42
```

保存到指定目录：

```bash
himalaya attachment download 42 --dir ~/Downloads
```

## 输出格式

大多数命令支持 `--output` 来获取结构化输出：

```bash
himalaya envelope list --output json
himalaya envelope list --output plain
```

## 调试

启用调试日志：

```bash
RUST_LOG=debug himalaya envelope list
```

完整跟踪和回溯：

```bash
RUST_LOG=trace RUST_BACKTRACE=1 himalaya envelope list
```

## 提示

- 使用 `himalaya --help` 或 `himalaya <command> --help` 查看详细用法。
- 邮件 ID 是相对于当前文件夹的；切换文件夹后需要重新列出。
- 要撰写带附件的富文本邮件，请使用 MML 语法（参见 `references/message-composition.md`）。
- 使用 `pass`、系统 keyring 或输出密码的命令来安全存储密码。
- **自动化场景：** 始终使用 `template write | template send` 管道，并设置 `export EDITOR=cat`。
- **163 邮箱用户：** 在配置中设置 `backend.extensions.id.send-after-auth = true` 和 `message.send.save-to-folder = "Sent"`。
- **文件夹名称：** 使用英文文件夹名称（例如 "Sent" 而非 "已发送"）以获得更好的兼容性。
