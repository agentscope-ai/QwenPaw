# QwenPaw 社区集成：开发配置与平台契约

更新日期：2026-09-09。对应上游基线 `a403b243`、开发分支 `asp-dev`，完整范围及交付状态见 [Issue #7583 开发计划](issue-7583-community-integration-plan.zh.md)。

本说明区分三类证据：已经查证的生产公开路由与第一方客户端协议、当前 QwenPaw 代码实现、尚待正式授权的联调能力。P0 的精确资源关联已实现；P1 的本地协议与收件箱测试已通过，消息同步能力默认可用，用户可以暂停；P2 支持报告填入站内发帖表单，经用户确认后发布。

## 查证范围

生产固定域名为 [AgentScope Platform](https://platform.agentscope.io)，社区首页为 [QwenPaw 社区](https://platform.agentscope.io/community)。2026-09-08 的只读调研使用了公开 HTTP 响应、部署中的第一方前端 `0.1.8` 与已安装的官方 CLI `@agentscope-ai/platform-cli@1.0.3` 源码。公开查询确认了插件、App 与 Skill 的实体映射；登录、通知和草稿协议还参考了第一方客户端代码。

调研没有执行生产登录授权、刷新、发帖、创建草稿或标记通知已读。已有过期凭据的只读请求返回 `ASP.AUTH.ACCESS_TOKEN_EXPIRED`，不能据此推断一个有效 CLI token 已获准访问社区 Web API。本地模拟响应测试与真实 QwenPaw 服务测试均不等于生产授权链路通过。

## 本地后端补充证据与边界

2026-09-09 在本机另一份 `agentscope-platform` 后端仓库完成有界只读核查，HEAD 为 `3a29945f3e9ba1008a166186839b0f66d6f99da7`（2026-08-17）。以下路径相对该后端仓库，不是当前 QwenPaw 仓库中的文件：

| 证据                                                                                                                                                                       | 已确认内容                                                                                                   |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `agentscope-platform-admin/src/main/java/io/agentscope/platform/admin/config/CliProperties.java:29`；`cli/service/CliOAuthService.java:141`（同一 admin Java 包下）        | 默认 client 仍为 `agentscope-platform-cli`；服务端校验配置中的单一 ID，没有发现 QwenPaw 社区客户端的批准记录 |
| `agentscope-platform-admin/src/main/java/io/agentscope/platform/admin/service/auth/AuthService.java:234`、`:520`；`config/SecurityConfig.java:252`（同一 admin Java 包下） | CLI OAuth 与 Web 登录共用用户 JWT 签发；消息请求使用已认证用户身份，没有在这些入口观察到独立消息 scope 检查  |
| `agentscope-platform-admin/src/main/java/io/agentscope/platform/admin/controller/message/MessageCenterController.java:45`                                                  | 评论流明确包含 `comment_on_my_resource` 和 `reply_to_my_comment`                                             |
| `agentscope-platform-core/src/main/java/io/agentscope/platform/core/mapper/MessageCenterCommentReplyMapper.java:88`、`:110`                                                | 按 Skill/Plugin 的 `author_user_id` 查询他人在资源详情页的评论                                               |
| `agentscope-platform-admin/src/main/java/io/agentscope/platform/admin/cli/common/CliPkceSupport.java:17`                                                                   | 旧后端仅接受 HTTP loopback 回调，没有 Hub 远程授权能力                                                       |

已保存的生产消息页面代码 `index21.js` 短片段也直接读取 `e.event_type`，并出现 `reply_to_my_comment` 与 `comment_on_my_resource`。QwenPaw 仅将精确的远端资源评论类型映射为 `resource_feedback`，不照搬页面根据评论正文推测类型的兼容逻辑。

该 HEAD 尚无 mentions/community 控制器；进一步检查本地缓存的 `origin/dev/pre`（`bd9ef4d0`，2026-08-18）发现两者已经存在，但不能将缓存分支当作当前部署版本。该分支的评论聚合也将社区文章和问题的评论标为 `comment_on_my_resource`，因此 QwenPaw 同时校验资源类型，仅把插件、应用和 Skill 的评论归为资源反馈；文章、问题、未知或缺省资源类型仍归为回复。默认 OAuth client 仍为 CLI。它补充了 JWT 兼容性和资源详情评论的实现证据，没有证明当前生产批准了 QwenPaw client，也没有证明“社区新问题关联维护资源”已经向作者派发完整通知。plaza 的相关文档仍是评审设计稿，静态原型不补足这些依赖。

## 最新 dev 源码复核（2026-09-09）

通过仓库页面的 SSH 地址实时读取后端 `dev/dev`：`1bd8a17fed5d7b67751ffbb183cda7ef89604b8e`。前端远端没有 dev 分支，核对 master `aa58cd13cdf9f3984311d22568b7d414933f3c61` 与 community `11f7301a7669f9a77f572cecca4e31a60b50058c`。本节替代上面旧快照对缺失能力的推断。

- `CliProperties` 和 dev 配置已有 `agentscope-platform-cli`、`platform:control`；`CliOAuthService` 校验单一 client ID 并签发用户登录 token。前端 `src/constant.ts`、`src/lib/cliOAuthParams.ts` 同样限定 CLI ID。没有发现独立 QwenPaw 社区 OAuth client；按用户最新确认复用现有 client。
- `CliPkceSupport` 要求 S256，以及 `http://127.0.0.1:<port>/callback/<nonce>` 或 localhost 回调，返回 `code`、`state`。
- **关联资源新问题通知已经实现**：`MessageCenterController.listMentions`、`MessageCenterMentionMapper` 将已发布社区内容的关联资源与资源作者匹配，排除作者自关联。事件为 `mention_my_resource`，问题的 `content_type=question`，返回 `mentioned_resource_id` 和 `created_at`。此前称此接口缺失的结论撤回。
- QwenPaw 已将上述问题映射为 `resource_feedback`，其他内容关联仍为 `mention`；修正时间字段和资源 ID，保留去重标识及已读状态。
- dev 的 `QwenPawRelayDeviceAuthorizationService` / `QwenPawRelayProperties` 已有 `client_id=qwenpaw-selfhost` 和 RFC 8628 设备授权；签发 `token_type=RelayEnrollment`、`enrollment_token`，用于 Relay 节点注册，不是社区用户 access token。

## 本地开发预览

在 `console` 目录完成 `npm run build` 后，从仓库根目录启动后端时显式指定 `QWENPAW_CONSOLE_STATIC_DIR`。当前 [静态资源解析](../src/qwenpaw/app/_app.py) 优先使用环境变量，其次使用包内 `src/qwenpaw/console`，最后才查找仓库 `console/dist`；不指定时可能仍加载旧包页面或旧 i18n 文案，不能据此判断最新前端是否生效。

以下示例使用已配置好项目依赖的 Python 环境和独立预览状态目录：

```bash
QWENPAW_WORKING_DIR=/tmp/qwenpaw-community-preview \
QWENPAW_SECRET_DIR=/tmp/qwenpaw-community-preview-secrets \
QWENPAW_CONSOLE_STATIC_DIR="$PWD/console/dist" \
python -m qwenpaw app --host 127.0.0.1 --port 8088
```

重新构建或修改该配置后，重启预览服务并确认加载的是最新构建产物。

## 安装来源与资源关联

来源模型见 [installation_origin.py](../src/qwenpaw/installation_origin.py)。已安装插件、应用、Skill 的 API 显式返回 `installation_origin`；没有可靠记录时为 `null`。

```json
{
  "provider": "agentscope-platform",
  "resource_id": "@owner/resource-name",
  "resource_type": "skill",
  "installed_version": "1.2.3",
  "source_url": "https://platform.agentscope.io/skills/@owner/resource-name"
}
```

| 字段                | 当前要求                                                                              |
| ------------------- | ------------------------------------------------------------------------------------- |
| `provider`          | 固定为 `agentscope-platform`；历史 Skill 市场 provider `qwenpaw` 在可信安装路径中映射 |
| `resource_id`       | 平台完整稳定 ID；通常是 `@owner/name`，支持可信资源 URL 中的 UUID；不使用本地名称猜测 |
| `resource_type`     | `plugin`、`app` 或 `skill`                                                            |
| `installed_version` | 可选，取实际安装包中的版本；未知时省略或为 null                                       |
| `source_url`        | 必填，规范的 HTTPS 平台资源地址，且必须与类型和资源 ID 一致                           |

来源由安装器建立。插件/应用安装接口继续接收实际 `source` URL 或路径，不增加一个可任意声明的平台 provider 安装参数。插件/应用记录保存在插件目录下的 `.installation-origins/<local-id-sha256>.json`，位于下载包目录之外；Skill 记录保存在安装清单中，贯通工作区、技能池和同步操作。实现见 [插件加载器](../src/qwenpaw/plugins/loader.py)、[插件路由](../src/qwenpaw/app/routers/plugins.py)、[应用路由](../src/qwenpaw/app/routers/pawapps.py)、[Skill Hub](../src/qwenpaw/agents/skill_system/hub.py) 和 [Skill registry](../src/qwenpaw/agents/skill_system/registry.py)。

当前可信 URL 解析覆盖平台 `/plugins`、`/skills` 的 `@owner/name` 资源地址及对应 `archive/zip/<version>` 下载地址，以及 UUID 详情地址。不接受其他主机、附加查询/片段、路径穿越或不匹配的 ID；也不因为一个包 manifest 自称来自平台而生成来源。平台升级、重启保留记录，本地或其他来源覆盖清除旧记录。历史数据没有可信来源与稳定 ID 时保持未知。

### 反馈链接接口

QwenPaw 的 `POST /api/community/feedback-link` 接收：

```json
{
  "origin": {
    "provider": "agentscope-platform",
    "resource_id": "@agentscope/qwenpaw-creator",
    "resource_type": "app",
    "installed_version": "1.2.0",
    "source_url": "https://platform.agentscope.io/plugins/@agentscope/qwenpaw-creator"
  }
}
```

成功返回 `{"url":"https://platform.agentscope.io/community/ask?relatedPluginId=qwenpaw-creator"}`。前端应传已安装 API 返回的来源记录，并继续校验返回 URL 的域名、路径和对应资源关联参数。输入错误、资源不存在、类型不符或平台不可用时显示错误，不降级为同名关联。

| 本地资源 | 平台反馈页参数                | 映射约束                                                 |
| -------- | ----------------------------- | -------------------------------------------------------- |
| plugin   | `relatedPluginId=<plugin_id>` | 使用平台插件 ID                                          |
| app      | `relatedPluginId=<plugin_id>` | 平台仍是 plugin 实体；详情 `tech_type.code` 必须为 `app` |
| skill    | `relatedSkillId=<skill_uuid>` | 使用平台 Skill UUID，不直接传 `@owner/name`              |

当前解析流程见 [community_feedback.py](../src/qwenpaw/app/community_feedback.py)：

1. 验证来源记录；若为 `@owner/name`，用最后一段名称请求 `GET /openapi/v1/plugins` 或 `/openapi/v1/skills`，参数为 `search`、`page_size=100`、`page_number`。
2. 响应结构为 `{success,data:{total,plugins:[...]}}` 或 `skills`。只接受完整 `item.id` 精确匹配，并验证 `details_url` 的平台域名与路径。最多检索 10 页；没有确切记录时失败。完整 `@owner/name` 搜索曾返回空结果，因此检索词不等于最终身份判断。
3. 当前代码再读取 `/api/v1/plugins/{id}` 或 `/api/v1/skills/{id}` 校验实体 ID 和 App 类型，然后构造反馈 URL。该详情读取与 OpenAPI 列表是两组接口，不假设存在未确认的 OpenAPI 详情路由。

问题编辑页已观察到 `relatedPluginId`、`relatedSkillId`、`draftId` 和 `articleId` 的处理。没有 `relatedAppId`、版本、标题或正文的 URL 预填能力；不要自行添加这些查询参数。安装版本由 P2 的可审阅正文携带。生产登录后的回跳、关联保留及提交行为仍需授权账号验收。

## 社区账号开发配置

配置读取自 [ConnectionConfig](../src/qwenpaw/app/community_connection.py)，在运行实例启动时加载：

| 环境变量                             | 默认值                  | 含义                                                            |
| ------------------------------------ | ----------------------- | --------------------------------------------------------------- |
| `QWENPAW_COMMUNITY_CLIENT_ID`        | agentscope-platform-cli | 平台批准供本集成使用的客户端 ID                                 |
| `QWENPAW_COMMUNITY_SCOPES`           | platform:control        | 平台批准的 scope 字符串，按协议原样传递                         |
| `QWENPAW_COMMUNITY_MESSAGES_ENABLED` | true                    | 部署者可以关闭消息同步适配；仅 `true`、`1`、`yes`（不区分大小写）为真 |

客户端 ID 与 scopes 均非空时，本地 `configured` 才为 true；这表示已填写配置，不证明平台接受该身份或授予消息权限。默认复用现有 CLI client；显式将 client ID 设为空字符串可禁用连接，P0 外链与 P2 手工复制流程仍可使用。

配置如下；使用已有 Java 授权接口；平台前端补丁仅区分授权文案，无需新增后端 client：

```dotenv
QWENPAW_COMMUNITY_CLIENT_ID=agentscope-platform-cli
QWENPAW_COMMUNITY_SCOPES=platform:control
QWENPAW_COMMUNITY_MESSAGES_ENABLED=true
```

获得 token 与消息 API 兼容性确认后，才将消息开关设为 true 并重启实例。已连接账号还需要在设置中打开自己的「消息同步」。当前生产页面只确认接受官方 CLI 的 `agentscope-platform-cli` 与 `platform:control`；代码默认复用该身份，也不会导入已安装 CLI 的凭据或抓取浏览器登录 Cookie。

正常轮询基准间隔为 120 秒，失败指数退避至最多 1800 秒后附加少量随机延迟。该值是 `ConnectionConfig.interval`，当前没有对应环境变量。平台域名固定，HTTP 超时 15 秒且不跟随重定向。

### 已知平台 PKCE 协议

公开 `GET /api/cli/v1/meta` 确认 `browser_pkce_login=true`、`device_login=false`。现有 `/cli/login` 要求 `response_type=code`、`code_challenge_method=S256`、state、challenge、scope 和 loopback 回调：

```text
http(s)://127.0.0.1[:port]/callback/<single-segment>
http(s)://localhost[:port]/callback/<single-segment>
```

QwenPaw 当前为每次流程监听 `127.0.0.1` 随机端口和随机回调路径，生成一次性 state 与 verifier，五分钟过期。取消、过期或完成后关闭监听；错误 state 和重复回调不能交换授权码。浏览器在平台页面完成登录与授权，本地只接收该次流程的回调。

| 操作       | 已知平台接口与关键字段                                                                                                                        |
| ---------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| 浏览器授权 | `POST /api/cli/v1/oauth/authorize`，平台页面使用自身登录会话；传 client_id、redirect_uri、state、code_challenge、code_challenge_method、scope |
| 换取 token | `POST /api/cli/v1/oauth/token`；JSON 含 grant_type=authorization_code、client_id、code、code_verifier、redirect_uri                           |
| 刷新       | `POST /api/cli/v1/auth/refresh`，JSON `{refresh_token}`；不是 `/oauth/refresh`                                                                |
| 查验账号   | `GET /api/cli/v1/me`，Bearer token                                                                                                            |
| 撤销       | `POST /api/cli/v1/oauth/revoke`，Bearer token，JSON 含 token、token_type_hint                                                                 |

CLI token 响应为顶层 `access_token`、可选 `refresh_token`、`token_type`、`expires_in`、`scope`、`user`；不同于 Web API 的 `.data` 包装。QwenPaw 通过 `/me` 再查账号，不仅依赖 token 响应的 user。刷新必须保持原账号与连接代次，避免解绑、换号或暂停期间的旧结果覆盖新状态。

### 本地与远程边界

发起连接接口同时检查请求来源、Host 与 Origin，只接受支持的本机访问；Hub 内部运行标识存在时不开放该 loopback 流程。远程浏览器中的 localhost 指向浏览器电脑，不指向 QwenPaw 服务器。当前社区连接未实现设备码或 Hub 远程回调；dev 的 Relay 设备授权仅用于节点注册。

已有连接的状态读取和管理不因远程访问而伪装成断开；`local_login_supported` / `connection_available` 表明当前访问能否重新发起连接。完整的 Hub/远程授权仍需平台提供正式协议。

### QwenPaw 本地账号 API

路由见 [community_connection.py](../src/qwenpaw/app/routers/community_connection.py)：

| 方法与路径                                                 | 行为                                                                    |
| ---------------------------------------------------------- | ----------------------------------------------------------------------- |
| `GET /api/community/connection`                            | 返回配置、连接、账号、同步及可用性状态，不返回 token                    |
| `POST /api/community/connection/start`                     | 启动本机授权，返回 flow_id、authorize_url、expires_at                   |
| `GET /api/community/connection/authorization/{flow_id}`    | 读取流程状态与脱敏错误                                                  |
| `DELETE /api/community/connection/authorization/{flow_id}` | 取消流程                                                                |
| `DELETE /api/community/connection`                         | 先清除本地连接与消息，再尽力远端撤销；返回 disconnected、remote_revoked |
| `PATCH /api/community/connection/sync`                     | `{"enabled":true或false}`；更新当前账号同步开关                         |
| `POST /api/community/connection/sync`                      | 立即执行一次有界同步，返回 status、inserted，完成时可含 catching_up     |

状态为 `not_configured`、`disconnected`、`authorizing`、`connected`、`expired` 或 `unsupported_remote`。附带 `configured`、`connected`、`local_login_supported`、`connection_available`、`messages_enabled`、`messages_available`、不可用原因、`supported_notifications`、可空账号与授权信息，以及 `sync_enabled`、`last_success_at`、`last_error`。时间戳采用 Unix 秒。账号仅包含 ID、显示名称和可选头像。

## 消息同步与原生收件箱

当前实现 Platform“我的消息”的五种远端列表，均带 `page`、`page_size`、`mark_read=false`：

| 已适配接口                             | 稳定 ID 与主要字段                                                                                                       |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `GET /api/v1/messages/comment-replies` | reply_id、event_type、resource_type/id/name/link、reply_content、replier_display_name/avatar_url、created_at、has_unread |
| `GET /api/v1/messages/mentions`        | mention_id、actor_display_name、source_title/summary/link、mentioned_resource_type/id/name/link、created_at              |

列表响应为 `{data:{items,total,page,page_size}}`。每个来源一次最多读取 5 页，每页 50 条；未完成时持久化页码与检查点，后续继续。此检查点是 QwenPaw 自己的状态，不是平台提供的 cursor。收到 401 最多刷新并重试一次；403 返回权限不足，保留已有消息。

本地事件 `source_type="community"`，生成 `event_type="reply"|"mention"|"resource_feedback"|"interaction"|"platform_feedback"|"notification"`。仅评论流中精确的 `event_type="comment_on_my_resource"` 且 `resource_type` 为 `plugin`、`app` 或 `skill` 时映射为 `resource_feedback`；其他或缺省评论类型仍映射为 `reply`，社区问题关联我的 Skill/Plugin 的 `mention_my_resource` 事件同样映射为 `resource_feedback`；其他关联保留为 `mention`。`supported_notifications` 返回 `replies`、`mentions`、`resource_comments`、`resource_questions`，后两项分别表示资源评论与关联资源的问题。仍使用 `comments:<reply_id>` 或 `mentions:<mention_id>` 作为远端去重标识，类型区分不会生成重复消息。payload 包含：

```json
{
  "sender": { "name": "Sender", "avatar_url": null },
  "discussion_url": "https://platform.agentscope.io/community/articles/example",
  "resource_type": "question",
  "resource_id": "example",
  "resource_name": "Discussion title",
  "received_at": 1788800000
}
```

字段可能为空；关联接口使用 `mentioned_resource_id`，缺省时不猜测补齐。正文按纯文本显示，讨论链接限定 HTTPS 平台域名。远端有 `has_unread` 时尊重其值；无该字段的首次历史回填视为已读，后续新增事件视为未读。本地已读与删除状态不会被重复同步覆盖。

合并后的收件箱继续使用既有 API，详见 [console.py](../src/qwenpaw/app/routers/console.py)：

- `GET /api/console/inbox/events?source_type=community&offset=250&limit=10`：服务端合并后筛选和分页；返回 events、total、unread_count。
- `POST /api/console/inbox/read`，`{"all":true,"source_types":["community"]}`：只操作社区来源；按 event_ids 可标记选中消息。
- `DELETE /api/console/inbox/events/{event_id}`：仅删除本地通知，持久化 tombstone；不删除讨论、不标记平台消息已读。
- 社区历史读取异常时混合列表保留本地结果并返回 `source_errors.community`；不会把社区文件内容或 token 放入响应。

当请求范围包含社区且状态可读取时，列表响应同时返回 `community_scope`：已连接时为由账号与连接代次派生的不透明标识，未连接时为 null。消息与 scope 来自同一次存储快照，前端用它清理换号或解绑前的通知；历史损坏或请求不涉及社区时省略该字段，不能把省略误判成解绑。

平台另有 unread-summary、interactions、notifications、urgent-notifications，以及按整个 Tab 的 mark-read API，当前轮询没有接入这些流，也不调用远端 mark-read。没有查证到 cursor 或单条已读接口。`GET /api/v1/messages/feedback` 表示用户提交给平台的反馈，不能冒充「维护资源收到的新问题」。

### 存储与用户归属

[community_store.py](../src/qwenpaw/app/community_store.py) 将账号凭据、同步状态、消息和删除标记写入当前 `QWENPAW_WORKING_DIR/community/state.json`，原子更新，目录按 0700、文件按 0600 创建。它是受文件权限保护的本地状态文件，不是系统钥匙串或加密凭据库；不得将该文件作为日志、报告附件或公开测试产物。

Standalone 按运行实例所有者归属；Hub 依赖每位用户独立运行实例、独立 working dir 与现有访问控制。连接 ID 与账号 ID 共同校验异步写回，换号清理旧账号状态，解绑立即清空本地记录。可见社区消息最多保留 5000 条，超出部分保留 ID 删除标记以防重复导入。此隔离实现已有本地测试，生产 Hub 登录尚未验证。

## 辅助报告与草稿交接

当前 `POST /api/community/report/generate` 接收资源名称/类型/安装版本、用户正文、选择的日志、截图、材料确认和语言，返回 `{"report":"Markdown"}`。见 [报告模型](../src/qwenpaw/app/community_report.py)、[生成路由](../src/qwenpaw/app/routers/community_report.py) 与 [报告弹窗](../console/src/pages/CommunityFeedback/ResourceReportModal.tsx)。

- 使用已配置模型的单次调用，不创建 Agent 会话、工具、记忆，也不读取应用日志或工作区上下文。生成超时 120 秒，取消或失败保留前端原稿。
- 正文上限 32000 字符；日志仅由用户粘贴或选文件，内容上限 24000 字符。文本尽力脱敏，材料发送前要求用户确认。
- 最多两张用户选定图片，可预览、手工遮盖和下载；没有自动截屏或上传社区附件。图片理解依赖所配置模型的能力。
- 初始报告带入实际安装版本；QwenPaw 版本、操作系统及缺失复现事实仍需用户补齐。正文与日志仅在页面内存暂存，刷新不保留，重新打开时不恢复截图。
- 用户审阅并复制报告，随后打开精确关联资源的社区反馈页，自行粘贴、附图和提交。剪贴板失败支持手工复制确认。

第一方社区编辑器已经有以下草稿协议，但本次没有调用：

| 方法与路径                                             | 平台客户端中的用途 |
| ------------------------------------------------------ | ------------------ |
| `PUT /api/v1/community/questions/drafts`               | 创建草稿           |
| `PUT /api/v1/community/questions/drafts/{id}`          | 更新草稿           |
| `POST /api/v1/community/questions/drafts/{id}/publish` | 发布草稿           |
| `POST /api/v1/community/questions`                     | 直接发布问题       |

载荷包含 title、body_text、article_type=question、tags、related_skill_ids、related_plugin_ids、media_ids；保存结果读取 `.data.id` 并使用 `/community/ask?draftId=...`。这只是已观察到的社区客户端契约，QwenPaw token 的调用权限与跨站草稿交接仍待确认。当前采用复制方案，不调用社区发帖接口，也不将本地报告生成视为发布成功。社区内容翻译由社区独立实现。

## 验证与仍待确认事项

真实浏览器已验三类平台安装来源与反馈角标、390px 移动端隐藏入口、Desktop OS 社区设置复用和公开登录回跳参数。原生 Tauri/pywebview 系统浏览器跳转尚未完成：macOS QA 因 `NSScreen.mainScreen=None` 终止，CUA 也超时；这是环境限制，不能计为原生验证通过。生产账号登录与提交、实际模型生成仍保持单独待验。

来源广泛回归 709 通过、来源针对性测试 104 通过、连接测试 13 通过。最终修复后，6 个新增单元测试文件共 72 项通过（3.85 秒），真实本地服务收件箱集成 11 项通过（33.17 秒）；测试集存在重叠。完整前端 `npm run build` 已通过。

本次 tracked 与 untracked 的 28 个 src/tests Python 文件已通过仓库 pre-commit 的全部适用检查，退出码为 0，含 mypy、Black、Flake8、Pylint。此次明确跳过不相关的 actionlint 和 Prettier hook。全仓 `--all-files` 检查曾停在 actionlint 环境初始化阶段，未形成全仓通过结果；本次没有工作流改动。证据和测试文件见 [开发计划](issue-7583-community-integration-plan.zh.md#7-已有验证与发布前要求)。

待部署和验收：社区来源授权文案前端补丁；token 对 messages API 的授权；Hub/远程授权方式；后续草稿写入权限。具备这些条件后，使用授权账号验证真实登录、回复、提及与资源评论同步，再开展社区关联问题通知与远程联调。当前未声称生产端到端完成，尚未执行 git commit、push 或发布。

## 复用现有 CLI client（无需 Java 改动）

按用户最新确认，撤回独立 client 的 Java 代码和测试，后端工作副本已恢复至原基线。QwenPaw 使用 `agentscope-platform-cli`、`platform:control` 以及现有 PKCE、刷新和撤销接口，凭据由自身授权获取并存放，不读取 CLI 凭据。

QwenPaw 登录链接附加 `source=qwenpaw-community`。平台前端仅在 client ID 为既有 CLI 且 source 精确匹配时显示社区文案；此参数不进入 OAuth 授权请求体，不改变身份、scope 或校验规则。登录回跳保留 source，未知来源显示原 CLI 文案。旧平台前端不识别 source 时仍能完成原 CLI 授权，仅文案不区分来源。

平台只需部署可选的授权文案前端补丁，不需要部署 Java 后端。消息同步能力默认启用，用户可在设置中独立暂停并选择消息类型。代码、补丁与验证见 [交付说明](platform-community-client/README.md)。

## 直接调用 platform-cli 使用的授权接口

根据官方仓库 commit `1f34df47039801eaae11af3e6dd2b50c0c2f39d8` 的 [browser-login.ts](https://github.com/agentscope-ai/platform-cli/blob/1f34df47039801eaae11af3e6dd2b50c0c2f39d8/src/auth/browser-login.ts)、[session.ts](https://github.com/agentscope-ai/platform-cli/blob/1f34df47039801eaae11af3e6dd2b50c0c2f39d8/src/auth/session.ts) 与 [cli-api.ts](https://github.com/agentscope-ai/platform-cli/blob/1f34df47039801eaae11af3e6dd2b50c0c2f39d8/src/api/cli-api.ts) 对齐 HTTP 协议：

1. 浏览器访问 `/cli/login` 完成 PKCE 授权；这是网页路由，不是 CLI 命令。
2. QwenPaw 直接 POST `/api/cli/v1/oauth/token` 交换授权码。
3. 按 `finalizeLogin` 逻辑，有 refresh token 时先 POST `/api/cli/v1/auth/refresh`，再 GET `/api/cli/v1/me`。刷新请求失败时回退原 token，但必须通过 `/me` 校验才能建立连接。
4. 后续刷新与解绑使用 `/api/cli/v1/auth/refresh`、`/api/cli/v1/oauth/revoke`。

运行时不安装、启动或调用 `asp` / `platform-cli` 可执行程序，不读取其凭据文件；平台 Java 保持无改动。`client_id=agentscope-platform-cli` 是协议中既有的客户端标识，不代表调用 CLI 程序。新增登录后刷新、刷新失败回退和无 refresh token 分支验证，社区连接测试最新 32 条通过（2.33 秒）。

## 真实账号授权与同步验收（2026-09-09）

用户明确确认授权后，已在生产平台网页完成 PKCE 授权，本地 QwenPaw 返回 `connected=true`；通过直接 HTTP 接口完成授权码交换、登录后刷新与 `/me` 账号验证，没有执行 CLI 命令或修改 Java。

在本次 localhost:18891 测试实例启用消息同步，首次同步返回 `inserted=32`、`catching_up=false`；原生收件箱共 32 条唯一消息，其中回复 27 条、提及 1 条、资源反馈 4 条。再次同步返回 `inserted=0`，没有重复项；`last_error=null`。此次远端已有消息均为已读，不将其算作真实新增未读通知测试。

真实浏览器已确认社区设置显示账号与开启的同步开关，收件箱列表和详情可查看，点击“查看讨论”打开对应社区文章。授权后的浏览器回跳页出现 `ERR_BLOCKED_BY_CLIENT`，但本地流程状态为 completed、账号验证成功；未绕过浏览器拦截。凭据仅保存在该本地测试实例中，文档不包含 token 或消息正文。

本次不包含真实发帖、删除远端通知、第二账号切换、Hub 远程授权或原生桌面回跳验收；未提交、推送或部署代码。同步目前保留开启，可在社区设置中暂停或解除连接。


## 页内帖子与 My Messages 全量分类

- `GET /api/community/posts?page=1&keyword=&post_type=all|article|question` 代理 Platform 社区列表（每页 20 条）。
- `GET /api/community/posts/{id}` 获取正文；`GET /api/community/posts/{id}/comments?page=1` 获取评论及嵌套回复。
- `POST /api/community/posts/{id}/comments` 接收 `content`、可空 `parent_id`、当前 `account_id`；仅使用本地已连接账号令牌。正文最长 65536 字符且不能全空白，ID 限制为字母数字、下划线和短横线。账号变化拒绝写入；写请求不自动重试。
- 阅读允许未连接账号；令牌存在时用于个性化读取。前端不接收令牌。
- 消息新增 `/messages/interactions`、`/messages/feedback`、`/messages/notifications`。分别映射 `interaction`、`platform_feedback`、`notification`，以类别前缀隔离 ID。反馈工单使用 `id:last_comment_at`（缺省回退更新时间）识别新回复。
- 无单条远端已读或删除调用，也不调用紧急通知确认接口。反馈工单链接回 Platform 消息中心；该平台页面当前不支持精确定位某工单的 URL 参数。

运行时证据：2026-09-09 社区列表返回 total=73，已连接账号同步到 83 条消息。阿里云 qwen3.8-max 使用合成输入完成一次报告生成（HTTP 200）；此前模型为空的记录仅描述旧运行状态。

### 收件箱关联资源字段修正（2026-09-09）

帖子消息详情通过 `GET /api/community/posts/{post_id}/resources` 读取帖子当前 `related_skill_ids` 与 `related_plugin_ids`，按类型和 ID 去重，显示全部 Skill/Plugin 的名称和详情链接，不再将帖子自身的标题或 ID 当作关联资源。历史消息无需重新同步。资源名称查询失败时保留准确 ID 和链接；帖子读取失败提供重试，无关联时显示明确空状态。直接针对 Skill/Plugin 的评论仍链接到该资源。

### 消息类型偏好

设置入口改为“社区与消息”，采用消息气泡图标。`PATCH /api/community/connection/sync` 支持可选 `enabled` 和 `message_types`（comments、mentions、interactions、feedback、notifications）；省略类型保持原选择，空数组表示不接收任何类型，旧配置默认全选。偏好保存在当前连接中，刷新令牌不会覆盖它。轮询只请求选中类型，落库再次核验类型，拒绝关闭开关前已发出的迟到响应；已有消息保留，重新开启后从原位置补齐。

### 登录与本地发布表单（新增）

资源入口更名“问题与建议”，直接打开 QwenPaw 发帖表单；Agent 报告确认后自动填入表单标题和正文，不再依赖剪贴板或外部网页预填。普通社区页也提供发帖入口。表单显示当前授权账号，必须确认公开内容后才能提交。

`POST /api/community/posts` 接收 title、content、article_type（question/discussion）、account_id 与可选 origin。后端核验当前账号，通过安装来源解析真实资源 ID，填入 related_skill_ids / related_plugin_ids；调用 Platform 原有文章发布接口，无 Java 改动。文本 HTML 转义，禁止使用任意 HTML 输入。读帖子和评论使用公开请求；发布和评论写请求必须有有效 Platform 授权，失败不自动重试。

Platform 浏览器 Cookie 与 QwenPaw OAuth 连接为独立登录状态。QwenPaw 中的发布使用设置里已连接的 Platform 账号，不要求外部浏览器重复登录；未连接账号显示授权入口并阻止发布表单提交。当前发布流程不上传报告截图附件。


## 2026-09-20 社区浏览与桌面授权修正

- 根据生产 `/api/v1/community/meta` 和前端发布包核对分类：开发分享、应用案例、新手教程、交流讨论、问题求助；官方公告仅用于筛选。
- 帖子列表支持 `recommended` / `latest`，排序、分类、搜索及返回列表状态保存在 URL 中。普通发帖分别打开 Platform `/community/write` 和 `/community/ask`，完整编辑器管理登录、图片与草稿。资源反馈与 Agent 报告保留站内确认发布及自动资源关联。
- `QWENPAW_COMMUNITY_MESSAGES_ENABLED` 默认值改为 `true`；显式关闭仍生效，已有用户暂停同步的选择不变。本地部署关闭提示与授权不足、网络断开、服务异常分开。
- Settings 和报告发帖表单复用授权窗口工具：浏览器同步预留窗口，Tauri / pywebview 使用系统浏览器，后端仍使用 PKCE loopback 回调。系统浏览器的 Platform 登录与 QwenPaw OAuth 连接相互独立。
- Platform 401 映射为社区连接冲突提示，避免误清除 QwenPaw 本地登录。正文和评论外链使用桌面外链接口。
