---
name: mailbox
description: "当用户需要任何邮箱/邮件操作时使用此技能——包括查看、阅读、搜索、发送、回复、转发、整理或删除邮件，管理会话线程，绑定个人邮箱或注册新邮箱。此技能是邮件任务的统一且唯一入口，通过 qwenpawmail-mcp 编排操作，当前支持 9 个个人邮箱域名。"
metadata:
  builtin_skill_version: "1.2"
  qwenpaw:
    emoji: "📧"
    requires:
      mcp: ["qwenpawmail-mcp"]
---

# 邮箱操作 (qwenpawmail-mcp)

使用 **qwenpawmail-mcp** 绑定或注册邮箱并执行邮件操作。

## 支持的邮箱服务商

QwenPaw 托管邮箱流程当前支持以下 9 个邮箱域名：

| 服务商 | 域名 | 登录凭据 |
| --- | --- | --- |
| 网易 | `163.com`、`126.com`、`yeah.net` | 16 位授权码 |
| 腾讯 | `qq.com`、`foxmail.com` | 16 位授权码 |
| 新浪 | `sina.com`、`sina.cn` | 16 位授权码 |
| 阿里 | `aliyun.com` | 邮箱登录密码；仅支持已有账号 |
| Google | `gmail.com` | 开启两步验证后生成的 16 位应用专用密码 |

当前托管流程不支持企业邮箱、自定义域名和 Microsoft 邮箱。

`create_mailbox` 仅为 `163.com`、`126.com`、`yeah.net`、`qq.com` 和 `foxmail.com` 提供内置注册引导。其他受支持域名需走服务商官方注册流程。`aliyun.com` 已关闭个人邮箱新注册，只能绑定已有账号。

## 调用规则

任何邮件操作都必须从此技能进入。不要自行编造其他邮件流程，也不要绕过 qwenpawmail-mcp 直接执行原始 IMAP/SMTP 命令。

## 凭据与配置模型

`agent.json` 只保存公开邮箱配置。`mail` 的预期结构为：

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

敏感字段 `auth_code`、`password` 和 `phone_number` 会被刻意排除在 `agent.json` 之外，Agent API 响应也不会返回它们。服务商凭据统一通过 `auth_code` 表示，配置后会被加密保存；注册密码和手机号只在对应邮箱的注册网页内填写，当前 QwenPaw 流程不会保存。公开配置中看不到 `auth_code` 并不表示用户没有配置凭据。

QwenPaw 仅在运行时通过托管 DriverCard 解析加密的服务商凭据。绝不要读取、解密、打印、复制或修改 `credentials.yaml`，也不要在文件或日志中搜索 secret。请严格使用下述流程。

## 工作流程：绑定或注册邮箱账号

### 第 1 步 — 读取公开邮箱状态

从 `agent.json` 读取 `mail.is_new_account`、`mail.credential.name` 和 `mail.credential.domain`。当前支持的个人邮箱域名对应的 `provider` 应为空字符串。

如果不存在 `mail`，请用户先在 QwenPaw 的智能体设置界面配置“邮箱管理”。

### 第 2a 步 — `is_new_account` 为 `false`：管理已有邮箱

1. 直接调用 `check_auth`。托管 DriverCard 已经通过运行时凭据引用获取加密存储中的邮箱凭据；不要从 `agent.json` 查找凭据，也不要因为看不到 secret 字段就调用 `set_credentials`。
2. `check_auth` 成功后，执行用户要求的邮件操作。
3. 如果凭据缺失或失效，请用户在 QwenPaw 中编辑当前智能体，选择“管理你的个人邮箱”，重新填写邮箱凭据并保存。智能体重载后再次调用 `check_auth`。
4. 如果用户在当前对话中明确提供邮箱地址和凭据，可以调用 `set_credentials` 作为仅限当前会话的临时覆盖，随后调用 `check_auth`。它不会更新 QwenPaw 的加密配置，MCP 进程重启后即失效。

临时调用 `set_credentials` 时，传入完整邮箱地址，并把服务商所需凭据放入名为 `auth_code` 的参数。对于 `aliyun.com`，该参数实际填写登录密码；其他受支持域名填写 16 位授权码或应用专用密码。

### 第 2b 步 — `is_new_account` 为 `true`：注册专属邮箱

使用 `agent.json` 中公开的用户名和域名。如果用户名为空，让 `create_mailbox` 生成用户名，或先与用户确定用户名。

注册密码和手机号只在对应邮箱的注册网页内填写，Agent 无法读取。不要尝试从文件恢复它们。QwenPaw 专属邮箱表单中的可选凭据字段仅用于注册完成后的最终授权码、应用专用密码或邮箱登录密码。请选择以下路径之一：

#### 首选路径 — 可视浏览器注册

1. 对网易或腾讯域名，先调用 `create_mailbox(domain, username)` 校验用户名并获取当前服务商引导。
2. 在可视浏览器中打开服务商官方注册页面。
3. 页面要求密码、手机号、验证码、短信验证码或其他身份验证时，请用户直接在可视浏览器中填写。如果用户明确为本次任务提供了某个值，只能在本次注册中使用，绝不落盘或复述。
4. 等待用户操作时保持浏览器开启；用户确认完成后继续。

官方注册入口：

| 域名 | 注册入口 | 说明 |
| --- | --- | --- |
| `163.com`、`126.com`、`yeah.net` | `https://zc.reg.163.com/regInitialized` | 网易统一流程，需要手机验证 |
| `qq.com`、`foxmail.com` | `https://ssl.zc.qq.com/v3/index-chs.html` | QQ 注册流程，需要手机验证 |
| `sina.com` | `https://mail.sina.com.cn/register/weixin.php` | 微信授权注册 |
| `sina.cn` | `https://mail.sina.cn/register/regmail.php` | 手机短信注册 |
| `gmail.com` | `https://accounts.google.com/signup` | 注册后开启两步验证并创建应用专用密码 |
| `aliyun.com` | 不可用 | 已关闭个人邮箱新注册，只能使用已有账号 |

只有看到明确的注册成功提示或成功进入收件箱后，才能判定注册成功。如果最终用户名与原计划不同，应报告原因和最终邮箱地址。

#### 备选路径 — 用户自行完成注册

对于网易或腾讯域名，调用 `create_mailbox(domain, username)`，把返回的备选用户名、注册链接和步骤告知用户。请用户在自己的浏览器中完成密码、手机号、验证码和短信验证等所有敏感步骤。

对于新浪或 Gmail，引导用户使用上方官方入口。对于 `aliyun.com`，说明无法注册新账号，并请用户选择其他受支持域名。

### 第 3 步 — 注册成功后

1. 不要把授权码、密码或手机号写入 `agent.json`。
2. 请用户在 QwenPaw 智能体设置界面编辑该智能体，保持选择“为智能体配备专属邮箱”，填写最终邮箱名以及该域名对应的可选凭据，然后保存。网易、腾讯、新浪或 Gmail 填写 16 位授权码/应用专用密码；使用登录密码的服务商则填写邮箱登录密码。QwenPaw 会自动将 `is_new_account` 设为 `false`、加密保存 secret、同步托管 DriverCard 并重载智能体。
3. 重载后调用 `check_auth`；验证成功前不要调用其他邮件工具。
4. 涉及联系人时先读取 `CONTACTS.md`。

## 可用工具

### 只读工具

| 工具 | 用途 |
| --- | --- |
| `list_folders` | 列出所有邮箱文件夹 |
| `list_messages` | 分页列出文件夹中的邮件元数据 |
| `get_message` | 按文件夹和 UID 获取单封邮件 |
| `get_attachment` | 按文件名或索引获取附件 |
| `search_messages` | 按关键词、发件人或日期范围搜索邮件 |
| `check_auth` | 使用当前运行时凭据重新验证 IMAP 和 SMTP 登录 |
| `create_mailbox` | 返回网易/腾讯受支持域名的注册引导 |
| `list_threads` | 增量同步并列出会话线程 |
| `search_threads` | 搜索会话线程 |
| `get_thread` | 获取一个线程中的所有邮件 |
| `get_mailbox_stats` | 获取近期邮箱统计 |

### 写操作工具

| 工具 | 用途 |
| --- | --- |
| `send_message` | 发送带 to/cc/bcc 的纯文本邮件 |
| `reply_message` | 使用正确的线程头回复邮件 |
| `forward_message` | 以 RFC 822 附件形式转发邮件 |
| `mark_messages` | 标记已读/未读/星标/取消星标 |
| `move_message` | 将邮件移动到其他文件夹 |
| `create_folder` | 创建邮箱文件夹 |
| `set_credentials` | 为当前 MCP 进程设置临时内存凭据 |
| `clear_credentials` | 清除临时覆盖并回退到启动时注入的凭据 |
| `update_thread` | 添加或移除线程自定义标签 |

### 破坏性工具

| 工具 | 用途 |
| --- | --- |
| `delete_message` | 永久删除单封邮件 |
| `delete_thread` | 将整个线程移入垃圾箱 |

## 安全性与可靠性注意事项

- 绝不猜测或暴露授权码、密码、手机号、验证码或短信验证码。
- 绝不能把已脱敏的 secret 字段理解为空凭据；应通过 `check_auth` 验证。
- 绝不把 secret 写入 `agent.json`、DriverCard YAML、CONTACTS.md、日志或对话总结。
- 调用 `delete_message` 或 `delete_thread` 前必须向用户确认。
- 邮件 UID 属于具体文件夹且可能变化；操作前立即用 `list_messages` 或 `search_messages` 刷新。
- 通过界面或运行时修改凭据后，必须先调用 `check_auth`。
- 用户希望保留新联系人信息时更新 `CONTACTS.md`，但绝不能在其中保存凭据。
