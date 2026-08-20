# qwenpawmail-mcp

[English](README.md) | 中文

让 AI Agent 通过 IMAP/SMTP 读取、搜索、发送和整理邮件的 stdio [MCP](https://modelcontextprotocol.io/)（Model Context Protocol）server。作为 [QwenPaw](../../README_zh.md) 的邮箱子包开发，也可独立配合任何支持 MCP 的客户端（如 Claude Desktop）使用。

## 特性

- **22 个工具**，覆盖文件夹、邮件、附件、搜索、发信、线程、标签和邮箱统计——每个工具都标注了只读 / 写操作 / 破坏性属性，方便 MCP 客户端施加相应的安全防护。
- **服务商自动路由**——内置 12 个邮箱域名（网易、腾讯 QQ、新浪、阿里、Gmail 及主流国内企业邮），仅凭邮箱地址即可解析 IMAP/SMTP 服务器。未知域名也可通过环境变量显式指定 host。
- **本地线程索引**——按 References/In-Reply-To 链聚合邮件为会话线程，支持自定义标签、增量同步和线程全文搜索；索引以 JSON 原子写存储，并按邮箱地址命名空间隔离，多邮箱数据互不污染。
- **稳定性设计**：
  - 所有 IMAP/SMTP 连接均有 30 秒超时
  - 全 async 工具 handler，网络 I/O 不阻塞事件循环
  - SIGTERM/SIGINT 优雅退出
  - 同域名连接节流，避免触发服务商连接数限制
  - 无状态连接模型：每次操作独立建连、用完即断，无连接泄漏
- **灵活设置邮箱凭据**——凭据可在运行时通过 `set_credentials` 工具设置而无需配置环境变量，就算无凭据 server 也能正常启动。

## 支持的服务商

按邮箱域名自动路由 IMAP/SMTP 服务器，以下 12 个域名无需手动配置：

| 域名 | 服务商 | IMAP | SMTP | 凭据类型 |
| --- | --- | --- | --- | --- |
| 163.com | 网易 163 | imap.163.com:993 | smtp.163.com:465 | 授权码 |
| 126.com | 网易 126 | imap.126.com:993 | smtp.126.com:465 | 授权码 |
| yeah.net | 网易 yeah.net | imap.yeah.net:993 | smtp.yeah.net:465 | 授权码 |
| qq.com | 腾讯 QQ 邮箱 | imap.qq.com:993 | smtp.qq.com:465 | 授权码 |
| foxmail.com | 腾讯 QQ 邮箱（别名域） | imap.qq.com:993 | smtp.qq.com:465 | 授权码 |
| sina.com | 新浪邮箱 | imap.sina.com:993 | smtp.sina.com:465 | 授权码 |
| sina.cn | 新浪邮箱（sina.cn） | imap.sina.cn:993 | smtp.sina.cn:465 | 授权码 |
| aliyun.com | 阿里邮箱 | imap.aliyun.com:993 | smtp.aliyun.com:465 | 登录密码 |
| gmail.com | Gmail | imap.gmail.com:993 | smtp.gmail.com:465 | 应用专用密码 |
| exmail.qq.com | 腾讯企业邮 | imap.exmail.qq.com:993 | smtp.exmail.qq.com:465 | 客户端专用密码 |
| qiye.aliyun.com | 阿里企业邮 | imap.qiye.aliyun.com:993 | smtp.qiye.aliyun.com:465 | 登录密码/安全密码 |
| qiye.163.com | 网易企业邮 | imap.qiye.163.com:993 | smtp.qiye.163.com:**994** | 登录密码 |

其他域名（如自定义公司域名的企业邮）可通过显式设置 `QWENPAWMAIL_IMAP_HOST` / `QWENPAWMAIL_SMTP_HOST` 接入——见[配置](#配置)。

## 工作原理

qwenpawmail-mcp 是纯 Python（>= 3.10）实现的 MCP server，基于 FastMCP SDK（`mcp>=1.28`）+ `imap-tools`，通过 **stdio** 传输通信。

在 QwenPaw 中，主进程会以子进程方式自动拉起本 server（`sys.executable -m qwenpawmail_mcp`），并通过环境变量注入凭据与状态目录——用户无需手动启动。在 QwenPaw 之外，任何支持 stdio 传输的 MCP 客户端（Claude Desktop、Cursor 等）都可以用同样的方式启动它。

## 安装

**方式一：随 QwenPaw 一起安装**（主项目 + 本子包）：

```bash
make install-dev
```

**方式二：单独安装本子包**（在仓库根目录执行）：

```bash
make install-mail-mcp
# 或等价的：
pip install -e packages/qwenpawmail-mcp
```

**Docker**：主项目 Dockerfile 已自动 COPY 并安装本包，无需额外步骤。

## 配置

所有配置均通过环境变量完成。凭据在**启动时可选**——也可以在运行时通过 `set_credentials` 工具提供。

| 变量 | 是否必需 | 说明 |
| --- | --- | --- |
| `QWENPAWMAIL_EMAIL` | 邮件操作需要* | 完整邮箱地址，如 `someone@163.com` |
| `QWENPAWMAIL_AUTH_CODE` | 邮件操作需要* | 登录凭据——**语义因服务商而异**（见下） |
| `QWENPAWMAIL_IMAP_HOST` | 未知域名需要 | IMAP host 覆盖（域名不在内置表中时） |
| `QWENPAWMAIL_IMAP_PORT` | 否 | IMAP 端口覆盖（默认取服务商配置或 993） |
| `QWENPAWMAIL_SMTP_HOST` | 未知域名需要 | SMTP host 覆盖（域名不在内置表中时） |
| `QWENPAWMAIL_SMTP_PORT` | 否 | SMTP 端口覆盖（默认取服务商配置或 465） |
| `QWENPAWMAIL_STATE_DIR` | 否 | 线程/标签本地索引的状态目录；默认 `~/.qwenpawmail-mcp/state/<email>/`（QwenPaw 会将其指向 agent workspace 的 `mail_state/` 目录） |
| `QWENPAWMAIL_WORKSPACE_DIR` | 否 | Agent workspace 根目录，用于解析附件保存的相对路径（由 QwenPaw 注入） |

\* server 无凭据也能启动；需要凭据的工具在凭据设置（env 或 `set_credentials`）之前会返回友好的错误提示。

> **关于 `QWENPAWMAIL_AUTH_CODE`**：它*不一定*是登录密码，含义因服务商而异：
> - **网易 / QQ / 新浪**——网页版邮箱设置中生成的 16 位*授权码*（不是账户密码）
> - **Gmail**——16 位*应用专用密码*（需开启两步验证）
> - **阿里邮箱 / 阿里企业邮 / 网易企业邮**——登录密码或安全密码
> - **腾讯企业邮**——客户端专用密码

自定义企业域名接入示例：

```bash
export QWENPAWMAIL_EMAIL="someone@mycompany.com"
export QWENPAWMAIL_AUTH_CODE="your-credential"
export QWENPAWMAIL_IMAP_HOST="imap.mycompany.com"
export QWENPAWMAIL_SMTP_HOST="smtp.mycompany.com"
```

## 可用工具列表（共 22 个工具，分三类）

### 只读（11 个）

| 工具 | 说明 |
| --- | --- |
| `check_auth` | 验证 IMAP 和 SMTP 均可成功登录（建议首次先调用） |
| `list_folders` | 列出全部文件夹（中文名自动从 modified UTF-7 解码） |
| `list_messages` | 分页列出邮件信封元数据（folder / limit ≤ 100 / offset，不拉取正文） |
| `get_message` | 按 UID 获取单封邮件的 text/html 正文与附件元数据 |
| `get_attachment` | 按文件名或序号下载附件（base64 返回或保存到磁盘） |
| `search_messages` | 按关键词、发件人和/或日期范围搜索 |
| `create_mailbox` | 新邮箱注册引导：校验用户名、生成备选名、返回注册链接与分步指引 |
| `list_threads` | 按标签/发件人/收件人/主题/日期过滤会话线程，按最新消息时间倒序 |
| `search_threads` | INBOX + 已发送全文搜索并映射到线程，按命中数 + 新近度排序 |
| `get_thread` | 获取线程内全部消息 envelope（时间正序） |
| `get_mailbox_stats` | 近 N 天邮箱洞察：收发量、top 发件人/收件人、每日趋势、响应时长、待回复邮件、附件统计 |

### 写操作（9 个）

| 工具 | 说明 |
| --- | --- |
| `send_message` | 发送纯文本邮件（to/cc/bcc/subject/body） |
| `reply_message` | 回复邮件（自动 In-Reply-To/References 头与 `Re:` 前缀） |
| `forward_message` | 转发邮件（原信作为 rfc822 附件，`Fwd:` 前缀） |
| `mark_messages` | 批量标记已读/未读/星标/取消星标 |
| `move_message` | 移动邮件到其他文件夹 |
| `create_folder` | 新建文件夹（中文名自动编码为 modified UTF-7） |
| `set_credentials` | 运行时设置/更新邮箱凭据（覆盖 env；未知域名需同时提供 imap_host/smtp_host） |
| `clear_credentials` | 清除运行时凭据（如设置了 env 则回退到 env） |
| `update_thread` | 为线程添加/移除自定义标签（系统标签 `inbox`/`sent`/`spam`/`trash` 只读） |

### 破坏性（2 个）

| 工具 | 说明 |
| --- | --- |
| `delete_message` | 将邮件标记为 `\Deleted`，并在服务商支持时用 RFC 4315 UID EXPUNGE 立即清理；始终仅作用于指定 UID，绝不使用全局 EXPUNGE |
| `delete_thread` | 将线程内所有消息移入已删除文件夹并从索引中移除线程 |

域名不在内置服务商表中时，需在 `env` 中额外添加 `QWENPAWMAIL_IMAP_HOST` 与 `QWENPAWMAIL_SMTP_HOST`。

## 安全须知

- **像保护密码一样保护授权码。** 授权码拥有该邮箱的完整 IMAP/SMTP 访问权限，切勿提交到代码仓库、写入日志或与他人共享。可随时在服务商网页版设置中吊销并重新生成。
- **破坏性工具**（`delete_message`、`delete_thread`）已通过 MCP 工具注解标记为 destructive——客户端应在调用前要求确认。
- QQ 邮箱在修改账户密码后会自动废弃已生成的授权码，认证突然失败时请重新生成。
- 通过 `set_credentials` 设置的凭据仅存在于 server 进程内存中，进程退出即消失。

## 许可证

MIT
