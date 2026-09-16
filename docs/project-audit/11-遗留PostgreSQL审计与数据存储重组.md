# 遗留 PostgreSQL 审计与数据存储重组

> **确认状态（2026-08-20）**：用户已确认重新设计数据库及数据库/文件/内容存储/Secret Store/临时状态的总体划分。同时补充硬性要求：多用户设计不得简化原有功能，对话中的推理、工具执行过程、审批、结果和多媒体必须完整保存与重放。

## 1. 审计范围与安全说明

2026-08-20 对本机遗留容器 `qwenpaw-pg` 进行了只读审计。审计只读取数据库版本、Schema、表、字段、约束、索引、RLS 策略和行数估计，没有查询消息正文、用户凭据、Secret 密文或其他业务内容，也没有修改数据库。

数据库现状：

- PostgreSQL 16.14。
- 数据库：`qwenpaw_test_single_node`。
- Alembic 版本：`20260814_0047`。
- 55 张业务/迁移表。
- 39 张表启用且强制 RLS。
- 56 条 RLS 策略。
- 160 个索引。
- 103 个外键、54 个唯一约束和 586 个 CHECK 约束。
- 已有约 2 个用户、5 个 Agent、13 个会话、23 条消息、15 次运行、14 个技能包及相关安全事件。

现有数据不能直接丢弃，但旧 Schema 不应继续作为新设计的增量基础。

## 2. 遗留表分类

### 2.1 值得保留的设计思想

- `users`、`password_credentials`、`auth_sessions`、`login_attempts`：稳定用户身份、密码和设备会话分离。
- `agents`、`agent_grants`、`agent_config_revisions`：Agent 归属、授权和配置版本。
- `conversations`、`messages`、`attachments`：结构化会话、消息和附件元数据。
- `approval_requests`、`user_input_requests`、`security_events`：实际用户审批和审计。
- `encrypted_secrets`、`resource_secret_bindings`：密钥密文与业务引用分离。
- `automation_schedules`、`automation_executions`：自动化定义和执行历史分离。
- `mcp_oauth_sessions`：OAuth state 不应只存在内存。
- `session_snapshots` 的“元数据 + storage_key”思路：大快照可外置内容存储。

### 2.2 需要合并或重写的部分

- `agent_grants` 与 `agent_capability_assignments` 同时表达 Agent 使用/管理关系，语义重复，应合并为清晰的 `agent_members.role`。
- `organization_resources` 与 Agent、技能包、项目等领域表重复建立通用资源注册，增加双写和一致性风险。
- `roles`、`permissions`、`role_permissions`、`membership_roles` 与大量 `system_capability` RLS 同时存在，权限来源过多。
- `configuration_revisions`、`system_settings`、`user_preferences`、`agent_config_revisions` 的边界不够直观，需要按领域明确事实来源。
- `memory_entries` 把所有记忆正文直接塞入表，但原运行时仍依赖 Markdown、目录和 `history.db`，没有解决双事实来源。
- `skill_packages` 保存包元数据是合理的，但需要补充技能池版本、Agent 载入副本、脱离和发布申请语义。
- 旧表缺少已确认的公共共享应用草稿、审核、发布版本和用户私有运行 workspace 模型。

### 2.3 当前需求之外的过度设计

- `organizations`、`organization_memberships` 及所有表的 `organization_id`：用户需要的是单部署多用户，目前没有多组织需求。
- `quotas`、`quota_reservations`：已确认第一阶段不建设计费、余额和配额产品。
- `agent_runtime_leases`、`coding_worktrees` 的跨 Worker 租约设计：当前部署没有确认分布式 Worker 调度目标。
- `outbox_events`：在没有确定外部消息总线和跨服务事务前提前引入。
- 通用自定义 RBAC 和复杂 RLS capability 上下文：首期只需要管理员/成员和资源角色。
- 大量运行尝试、事件和快照结构在原功能未完成兼容前一次性切换，扩大了回归面。

这些能力并非永远无用，但不应进入第一阶段必需范围。

## 3. 为什么不能把所有内容都放进 PostgreSQL

适合数据库的数据通常具备以下特征：需要关系查询、事务、唯一约束、权限过滤、状态流转、分页检索或审计。

不适合直接塞入普通业务表的数据包括：

- 任意 workspace 文件和目录树。
- 用户上传的大附件、图片、音频、视频和生成结果。
- 技能包、插件代码、前端静态资源和 Python 依赖。
- 本地模型权重。
- Browser Profile。
- Git checkpoint 对象。
- 备份 ZIP。
- 大量可轮转调试日志。
- 可重建缓存、索引和临时流式状态。

把这些内容全部转成 `bytea` 或 JSONB 会破坏原工具的文件语义，增加数据库膨胀、备份时长、VACUUM 压力和恢复复杂度，也迫使现有运行时全面重写。

## 4. 重新划分后的五类存储

### 4.1 PostgreSQL：结构化业务事实

应进入 PostgreSQL：

- 用户、密码哈希、登录会话、账户状态和平台角色。
- Agent 身份、所有者、成员角色、状态、默认模型和配置修订。
- 会话、消息、会话分享、当前会话模型和用户在 Agent 下的最近会话/草稿状态。
- 每轮请求的 Run、按顺序的结构化运行事件、工具调用生命周期、审批关联和断线重放游标。
- 定时任务、执行摘要、心跳设置和收件箱通知。
- 模型供应商非敏感元数据、模型目录、授权和引用关系。
- 技能池条目/版本、Agent 技能元数据、载入来源、脱离状态和发布申请。
- MCP 配置、工具白名单、访问策略、配置版本、OAuth 会话和 Secret 引用。
- Channel Connection 元数据、Agent 绑定、外部身份绑定和访问规则。
- 公共共享应用、草稿、审核、不可变发布版本和用户运行空间登记。
- 工具启停、Agent 工具非敏感配置和安全策略修订。
- Token 用量事件或聚合、运行摘要、审批和只追加审计。
- 文件/附件/checkpoint/备份的逻辑定位、所有权、哈希、大小、状态和版本，不保存其大正文。

聊天消息适合进入 PostgreSQL：它是需要顺序、分页、搜索、所有权和事务一致性的结构化记录。但消息不能简化成 `role + text`。必须保留消息类型、内容块、状态、工具调用 ID、运行 ID和事件顺序；图片、音频、附件和超大工具输出应外置，只在内容块中保存引用。

为了支持当前页面的实时过程展示和断线回放，还需要持久化：

- `runs`：一次用户请求到 Agent 完成/失败/取消的运行实例。
- `run_events`：按序保存 reasoning、progress、message delta、工具调用、审批、工具输出、错误和结果等结构化事件。
- `tool_calls`：保存工具名、类型、调用 ID、状态、审批状态、开始/结束时间、脱敏输入摘要和输出引用。

这三类表属于已被原功能证明必要的运行事实，不属于上一版的无依据过度设计。首期仍不需要 `run_attempts`、跨节点 Lease 和 Outbox。

### 4.2 文件系统：需要真实路径和工具读写的内容

首期保留在本地文件系统：

- Agent 草稿 workspace。
- 用户在私有 Agent 或共享应用下的运行 workspace。
- `SOUL.md`、`PROFILE.md`、`MEMORY.md`、`HEARTBEAT.md`、`AGENTS.md` 等可直接编辑内容。
- 用户项目文件、代码、报告和其他任意产物。
- 技能目录和脚本。
- 插件/PawApp 安装包、展开目录、静态资源和依赖环境。
- Checkpoint shadow Git 仓库。
- 本地模型二进制和 Browser Profile。
- 轮转日志和备份归档。

数据库保存逻辑 `storage_key`，前端和 API 不接收可信绝对路径。所有真实路径由 `WorkspaceResolver` 在授权后生成。

### 4.3 对象内容存储：可选扩展，不作为首期强依赖

适合对象存储的内容：

- 聊天附件和媒体。
- 大型工具输出。
- 不可变技能版本包和公共应用发布基线归档。
- 备份文件。
- 跨节点需要共享的用户文件。

首期单机部署可用本地 Content Store 实现同一接口，后续再切换 S3/MinIO。不能为了未来可能的分布式部署在首期强制引入 MinIO。

### 4.4 Secret Store：加密密文和密钥生命周期

Secret Store 是逻辑边界，不要求首期部署独立服务。推荐默认实现：

- 加密后的 Secret 密文可以存 PostgreSQL。
- 主密钥保存在数据库之外的系统 Keyring、受保护文件或部署 Secret 中。
- 数据库保存作用域、用途、版本、状态、创建者和轮换时间。
- 业务表只保存 `secret_ref`。

适用数据：

- 模型供应商 API Key 和 OAuth Token。
- MCP 环境变量、请求头和 OAuth Token。
- Channel Bot Token、App Secret 和签名密钥。
- 用户或 Agent Secret。
- 环境变量管理页面中的敏感值。

密码哈希仍放用户凭据表；它不可逆，不需要作为可解密 Secret 管理。

### 4.5 临时状态与可重建数据

不作为 PostgreSQL 长期事实保存：

- SSE/WebSocket 当前连接。
- 正在生成的 Token 缓冲。
- Agent 进程对象、MCP 客户端连接和 Provider 客户端。
- 短期能力缓存和文件监听状态。
- 可重建的全文索引、Embedding 索引和统计缓存。
- 下载进度、安装进度和短时锁。

单机首期使用进程内状态和文件锁即可；确有多进程协调需求时再引入 Redis。OAuth state、审批请求和必须跨重启恢复的任务状态不属于纯临时数据，应进入 PostgreSQL。

## 5. 关键领域的混合存储决策

| 领域 | PostgreSQL | 文件/内容存储 | 说明 |
|---|---|---|---|
| Agent | 身份、ACL、状态、默认模型、结构化配置和修订 | 人格 Markdown、workspace 内容、运行产物 | 不再让 `agent.json` 同时承担身份、权限和全部配置事实 |
| 会话 | 会话、消息、分享、模型覆盖、状态 | 附件、媒体、超大输出；旧 session JSON 只作迁移 | 消息顺序和权限必须数据库化 |
| 对话运行过程 | Run、顺序事件、工具调用状态、审批关联、重放游标 | 超大工具输出和生成文件 | 用于实时 UI、断线续传和历史会话完整重放，不能压扁为最终文本 |
| 记忆 | 记忆条目元数据、归属、索引状态 | 人类可编辑 Markdown、原始材料、可重建索引 | 不把整个 workspace 记忆系统粗暴压成一张 `memory_entries` 表 |
| 技能 | 池条目、版本、审核、Agent 绑定和来源 | 技能目录、脚本、资源包 | 运行时需要真实文件目录 |
| MCP | 配置、策略、工具摘要、版本和 Secret 引用 | 迁移期可物化 DriverCard YAML 作为运行缓存 | 目标事实来源应统一，解决斜杠命令旧链路 |
| 模型 | 目录、能力、状态、授权、参数和引用 | 本地模型权重 | Key/Token 进 Secret Store |
| 频道 | Agent 绑定、频道类型、外部身份和访问规则 | 媒体与协议缓存 | 绑定直接归属 Agent，由所有者/协作者管理；Bot Secret 进 Secret Store；保留同一 Bot 身份冲突约束 |
| 插件/PawApp | 安装记录、版本、能力、授权和小型 KV | 代码、依赖、静态资源和大型 App 数据 | 上传插件属于执行代码，必须管理员治理 |
| Checkpoint | 索引、归属、提交哈希和状态 | shadow Git 对象 | PostgreSQL 不替代 Git 对象库 |
| 备份 | 清单、范围、状态、校验和审计 | ZIP/归档 | 完整恢复需要数据库和内容一致性清单 |
| 日志与审计 | 安全审计和必要运行摘要 | 可轮转调试日志 | 不把全量 debug 日志塞数据库 |

## 6. 推荐的新数据库范围

新 Schema 第一版按领域建设，不复制旧库的 55 张表。建议核心集合：

### 身份与审计

- `users`
- `user_sessions`
- `external_identities`
- `audit_logs`

### Agent 与对话

- `agents`
- `agent_members`
- `agent_config_revisions`
- `conversations`
- `conversation_members`
- `messages`
- `runs`
- `run_events`
- `tool_calls`
- `attachments`
- `user_agent_preferences`

### 自动化与交互

- `automation_schedules`
- `automation_grants`
- `automation_executions`
- `notifications`
- `notification_receipts`
- `approval_requests`
- `usage_records`

### 模型、技能和 MCP

- `model_providers`
- `models`
- `model_grants`
- `skill_pool_items`
- `skill_pool_versions`
- `agent_skills`
- `skill_publish_requests`
- `agent_drivers`
- `driver_revisions`
- `credential_records`
- `credential_bindings`
- `mcp_oauth_sessions`

### 共享应用与频道

- `shared_apps`
- `shared_app_drafts`
- `shared_app_publications`
- `shared_app_user_workspaces`
- `plugin_installations`
- `plugin_capabilities`
- `app_grants`
- `agent_plugin_settings`
- `app_user_data`
- `channel_bindings`
- `channel_external_identities`
- `channel_access_rules`

### 平台设置、安全与备份

- `system_settings`
- `system_setting_revisions`
- `user_preferences`
- `security_policies`
- `security_events`
- `backup_artifacts`
- `backup_operations`

最终数量应以功能实现需要为准，不以“表越少越好”或“覆盖未来所有需求”为目标。第一阶段不创建组织、配额、通用资源注册、分布式 Lease 和 Outbox 表。

## 7. RLS 与权限重新设计

旧库在 39 张表上强制 RLS，并依赖 `current_setting('app.*')` 传递组织、主体和 system capability。该方式可以提供纵深防御，但当前策略数量和复杂度已经超过可安全评审范围。

新方案：

1. 统一 `AuthorizationService` 是业务权限事实来源。
2. 路由、后台任务、工具和渠道都通过同一 ActorContext 调用；ACP 产品能力关闭，不进入新调用链。
3. 第一阶段只在 `conversations`、`messages`、`attachments`、`approval_requests` 等高敏感用户数据表上考虑简单 RLS。
4. 管理员能力不通过任意字符串 capability 绕过，而是显式服务方法和审计上下文。
5. RLS 策略必须有独立测试，且连接池每个事务都要安全设置并清除会话变量。

## 8. 遗留数据迁移原则

不在旧 Schema 上直接改表。推荐：

1. 将旧数据库标记为只读迁移源。
2. 在独立数据库或独立 Schema 创建重新设计后的结构。
3. 编写幂等迁移器，按用户、Agent、会话、消息、技能包、Secret 引用和安全事件转换。
4. 每类数据生成数量、哈希、拒绝项和映射报告。
5. Secret 只迁移密文及密钥版本，不在日志中解密输出。
6. 对旧库中没有目标语义的表保留归档，不盲目映射到新表。
7. 新系统完成逐功能验收前，不删除 `qwenpaw-pg` 容器、卷或旧数据库。

当前旧库中已有数据，任何清理、重建、DROP、迁移写入或卷操作都属于高风险操作，必须再次取得用户明确确认。

## 9. 已同步到总体架构的修正

以下调整已同步到 `09-多用户目标架构方案.md`：

- 明确消息正文进入 PostgreSQL，二进制和超大内容外置。
- 明确 Agent 配置采用“结构化数据库配置 + 文件内容”的混合模型。
- 明确 MCP 的 PostgreSQL 事实来源与 DriverCard 运行物化关系。
- Secret Store 默认可以使用 PostgreSQL 加密密文，但主密钥必须在库外。
- 增加频道、自动化、插件、备份、统计和安全菜单的数据模型。
- 移除首期组织、通用 RBAC、配额、Outbox 和分布式 Lease 假设。
- 把旧数据库定义为只读迁移源，而不是继续升级的目标 Schema。

## 10. 本专项确认结果

用户已确认：

1. 不继续沿用旧 55 表 Schema，在新数据库/Schema 中重新设计。
2. 旧库保留为只读迁移源，已有用户、Agent、会话、消息、技能和 Secret 引用尽量迁移。
3. 会话与消息正文进入 PostgreSQL；附件、媒体和超大输出保留文件/内容存储。
4. Agent 使用结构化数据库配置与 workspace 文件混合存储。
5. 技能、插件、模型权重、checkpoint、备份和任意用户文件不存入普通数据库字段。
6. Secret 密文可进入 PostgreSQL 的 Secret Store 表，但主密钥必须保存在数据库之外。
7. 首期不建设组织、配额、通用资源注册、Outbox 和分布式 Worker Lease。
