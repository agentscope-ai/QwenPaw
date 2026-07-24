# 设计：NocoBase 作为唯一用户权威源

- **日期**：2026-07-24
- **状态**：待实现（spec 已获批，待写实现计划）
- **范围**：让 NocoBase 成为用户与权限的唯一权威源；QwenPaw 对 console/API 不再存储任何用户信息；删除本地账户与用户镜像缓存。

---

## 1. 背景与动机

QwenPaw 当前**没有传统多用户数据库**，其"用户体系"由三层拼成：

1. **本地单用户账户**（`auth.json`，stdlib 哈希）——无外部 IdP 时登录 Web 控制台用。
2. **外部身份提供方钩子**（NocoBase 插件注入 resolver / authenticator）——真正的多用户来源。
3. **身份下游消费**——把解析出的身份字符串用于 channel ACL 与 per-user token 用量归属。

启用 NocoBase 插件后，本地 token 校验已被完全关闭，认证事实上已委托给 NocoBase。但 QwenPaw 侧仍残留几处"用户相关状态"，带来维护负担：

- **`nocobase_permissions.json`**：NocoBase 用户/角色的**本地只读镜像**，由 `SyncEngine` + webhook + 手动同步维护。NocoBase 侧改/删用户就得再同步一遍——这是"同步非常麻烦"的根源。
- 该镜像还引出一类隐蔽故障：`enabled=true` 但管理员 `api_token` 未配置 → 同步被跳过 → 用户表为空 → console fail-closed **全拒**（"能连上却谁都进不来"）。

**目标**：NocoBase = 唯一权威源。QwenPaw 用**用户自己的 token 实时查询** NocoBase 判断"用户是否存在、有哪些角色"，不再维护任何本地用户副本，并删除本地账户代码路径。

## 2. 目标与非目标

### 目标
- 删除 `SyncEngine` 与 `nocobase_permissions.json` 镜像（含 sync/webhook 端点）。
- console/API 的身份与角色改为**实时查询** NocoBase（复用现有 60s TTL 缓存）。
- console channel 的访问控制完全由 NocoBase 治理（身份 + `role_channel_map`）。
- 删除主包内的本地账户实现，NocoBase 强制。
- 管理员 `api_token` 移出鉴权关键路径（仅后台"看用户/角色列表"才用）。
- 保留 per-user token 用量归属。
- 保留外部聊天渠道（钉钉/飞书/QQ/…）的本地 ACL 审批流程，本次不动。

### 非目标
- **不**把外部聊天渠道的 ACL 迁到 NocoBase（平台 sender_id 与 NocoBase 用户的映射问题本次不解决）。
- **不**保留"不用 NocoBase"的登录能力（本地账户彻底移除）。
- **不**为 NocoBase 不可用建设"宽限缓存/落盘副本"——容错止步于现有短 TTL 缓存。
- **不**改动 token 用量的存储结构。

## 3. 采用方案

**方案 A —— 全量移除，纯实时。** 删镜像 + 删本地账户 + 实时查询。备选方案 B（保留本地账户作休眠兜底）、C（保留镜像但自动刷新）均被否决：B 未达"彻底去掉"，C 仍在本地存用户副本、未解决根本诉求。

## 4. 架构总览

| 组件 | 职责 | 变化 |
|---|---|---|
| 核心 `app/auth.py` | 可插拔外部认证中间件骨架 | **删**本地账户实现；中间件永远委托外部 resolver |
| 插件 · 身份解析 | token → `(sender_id, roles)`，实时查 `auth:check`，60s 缓存 | **扩展**：连角色一起解析并缓存 |
| 插件 · console 门禁 | 决定某 NocoBase 用户能否用 console | **改**：不再查镜像 `is_known_user`；改为"身份已验证 + 实时角色比 `role_channel_map`" |
| 插件 · 管理列表 | `/nocobase-auth/users`、`/roles` | **改**：实时透传查 NocoBase |
| `SyncEngine` + `nocobase_permissions.json` | 用户/角色本地镜像 | **整体删除**（含 sync/webhook 端点） |
| `role_channel_map` | 角色→channel 授权规则 | **保留**（集成*配置*，非用户副本） |
| 本地 ACL `access_control.json` | 外部聊天渠道白/黑/待审批 | **不动** |
| token 用量 by_user | 按身份字符串归属统计 | **不动** |

核心思路：把"用户是否存在、有哪些角色"的判断，从**查本地镜像**改为**用用户自己的 token 当场问 NocoBase**；镜像与本地账户全部拿掉。

## 5. 运行时数据流

### console 一次请求（登录后聊天）
```
① 浏览器带 NocoBase token 打 /api/...
② AuthMiddleware → 外部 resolver
     → NocoBase GET /api/auth:check（用「用户自己」的 token, appends=roles）
     → 拿到 {sender_id, roles}；60s 缓存；失败=未认证→拒
③ request.state.user       = sender_id
   request.state.user_roles = roles          ← 新增
④ console channel 注入 payload:
     acl_sender_id = sender_id                （可信身份，永不信客户端传的 user_id）
     acl_roles     = roles                    ← 新增
⑤ console 门禁（fail-closed, 集合 {"console"}）:
     无 acl_sender_id                → 拒（未认证）
     有身份 + role_channel_map 为空   → 放行（凡合法 NocoBase 用户皆可）
     有身份 + 命中 denied 角色        → 拒
     有身份 + 存在 allow 列表但角色不在内 → 拒
⑥ 用量按 acl_sender_id 记 by_user
```

### 登录（用户名/密码）
`POST /api/auth/login` 直接走外部认证器 → NocoBase `auth:signIn` → 把 NocoBase 的 token 原样回给前端（端到端由 NocoBase 持有 token，与现状一致）。删除"本地 authenticate 先行"那一步。

### 关键不变量
- **"用户是否已知" = `auth:check` 成功与否**（用用户自己的 token），不依赖管理员 `api_token`，也不依赖镜像——"空镜像全拒"类故障随之消失。
- 管理员 `api_token` **只**用于 `/nocobase-auth/users`/`roles` 后台列表；移出鉴权关键路径。
- fail-closed 语义保持：无有效 NocoBase token → 无 `acl_sender_id` → 拒。
- `role_channel_map` 为空的默认语义：**放行所有合法 NocoBase 用户**（已确认）。

## 6. 详细改动（文件级）

### 主包 `src/qwenpaw/app/auth.py`
- **删**：`register_user`、密码哈希/校验、`auth.json` 读写、`create_token`/`verify_token`（自制 HMAC）、撤销名单及其 meta、`auto_register_from_env`。
- **改** `AuthMiddleware`：去掉"无外部认证器时校验本地 token"分支；永远走 `_resolve_external_identity`。resolver 返回 `(sender_id, roles)`，中间件写 `request.state.user` + `request.state.user_roles`。
- **改** `_should_skip_auth`：删除"无本地用户"的 bootstrap 逃逸；**新增安全兜底**——`QWENPAW_AUTH_ENABLED=true` 但无任何外部 resolver 注册（插件未加载/加载失败）→ **拒绝所有 /api（fail-closed）**并在启动时大声告警，杜绝插件挂了导致的静默 fail-open。
- **保留**：`is_auth_enabled`/`QWENPAW_AUTH_ENABLED`、`_PUBLIC_PATHS`/`_PUBLIC_PREFIXES`、外部 resolver/authenticator 注册表、`allow_no_auth_hosts`（默认空，仅作显式逃生口，**不**再当 bootstrap 手段）。

### 主包 `src/qwenpaw/app/routers/auth.py`
- **删端点**：`POST /register`、`POST /update-profile`、`POST /revoke-token`、`POST /revoke-all-tokens`。
- **改** `POST /login`：直接走外部认证器（删本地 authenticate 先行）。
- **改** `GET /status`、`GET /verify`：反映"NocoBase 模式"，不再暴露本地账户状态（`/status` 语义见 §9 契约）。

### 插件 `plugins/bundle/nocobase_auth/`
- **删**：`sync_engine.py`、`nocobase_permissions.json` 落盘；`routers.py` 里的 `POST /sync`、`POST /webhook`。
- **改** `identity_resolver.py` + `nocobase_client.py`：`auth:check` 带 `appends=roles`，返回 `(sender_id, roles)`；`identity_cache` 缓存二元组（60s + 负缓存不变）。
- **改** `channel_gate.py`：fail-closed 集合仍 `{"console"}`；判定改为"`acl_sender_id` 存在 + `acl_roles` 比 `role_channel_map`"，不再调 `is_known_user`。
- **改** `permission_store.py`：瘦身为只承载 `role_channel_map` 的评估——`is_channel_allowed(roles, channel)` 变为纯函数（输入角色列表而非查表）；删掉 `users`/`update_from_sync`/`is_known_user`/落盘。
- **改** `routers.py`：`GET /users`、`GET /roles` 改为实时透传 `nocobase_client.list_users/list_roles`（用管理员 api_token）；`GET/PUT /config`、`test-connection` 保留。

### console channel `src/qwenpaw/app/channels/console/channel.py`
- 注入 payload 时，除 `acl_sender_id` 外**新增** `acl_roles`（来自 `request.state.user_roles`）。

### 前端 `console/`
- `src/api/modules/auth.ts`：删 `register`、`updateProfile`；保留 `login`、`getStatus`、`/auth/verify`（App.tsx）；`AuthStatusResponse` 调整为 `{enabled, mode: "nocobase"}`，去掉 `has_users`（见 §9）。
- `src/pages/Login/index.tsx`：删除"注册"分支/切换，只留登录表单（NocoBase 账号密码）。
- `src/layouts/Sidebar.tsx`：删除改用户名/密码（`updateProfile`）入口——改密在 NocoBase 侧完成。
- `src/api/modules/auth.test.ts`：随之更新。
- i18n：`login.register*`、改密相关文案变为未用（清理或留存，实现时定）。

### 不动
- `app/channels/access_control.py`（外部渠道本地 ACL）。
- `token_usage/*`（by_user 保留；`SYSTEM_USER_ID`/`UNKNOWN_USER_ID` 保留）。
- `app/agent_context.resolve_request_user_id`（仍优先 `acl_sender_id`）。

## 7. Bootstrap / 配置（环境变量注入）

无本地登录后，需保证**开机即接好 NocoBase**，否则"没登录配不了、要配又得先登录"死锁。

- 插件启动时，若 `nocobase_auth_config.json` 缺失/为空，则从环境变量**种子化**配置：
  - `QWENPAW_NOCOBASE_ENABLED`
  - `QWENPAW_NOCOBASE_BASE_URL`
  - `QWENPAW_NOCOBASE_API_TOKEN`（可选——仅后台列表需要；缺失不影响登录与门禁）
  - `QWENPAW_NOCOBASE_USER_ID_FIELD`（默认 `email`）
  - `QWENPAW_NOCOBASE_AUTHENTICATOR`
- 容器启动后，管理员直接用 NocoBase 账号从 console 登录即可，无需环回放行。
- **已存在** `nocobase_auth_config.json` 时以文件为准（env 只做首次种子，不覆盖），避免每次重启回滚管理员在 UI 上的改动。
- `allow_no_auth_hosts` 默认保持空；作为显式逃生口存在，**不是**首次配置的正道。

## 8. 错误处理 & 容错

- **`auth:check` 失败/超时**（NocoBase 不可达、token 失效）→ 视为未认证 → fail-closed 拒。60s 缓存吸收瞬断，过期即拒（已接受）。
- **负缓存保留**：坏 token 短期不反复打 NocoBase。
- **后台列表端点** `/users`、`/roles`：NocoBase 不可达或 `api_token` 缺失 → 返回**明确错误**给前端，**绝不**静默返回"0 个用户"（避免被误读为"权威地没有用户"）。
- **启动自检**：auth 启用 + 插件启用但 `base_url` 不可达 → 大声 warning；鉴权仍 fail-closed（安全）。
- **失败带上下文**：解析失败日志带原因（网络 / 401 / 字段缺失），便于排障。

## 9. 接口契约变更

| 端点 | 变化 |
|---|---|
| `POST /api/auth/register` | **删除**（外部 provider 拥有用户系统） |
| `POST /api/auth/update-profile` | **删除**（改密在 NocoBase） |
| `POST /api/auth/revoke-token` / `revoke-all-tokens` | **删除**（token 由 NocoBase 管理） |
| `POST /api/auth/login` | 保留；直接走外部认证器；成功回 NocoBase token |
| `GET /api/auth/status` | 保留；响应改为 `{enabled, mode: "nocobase"}`（去掉 `has_users`） |
| `GET /api/auth/verify` | 保留；基于外部身份解析 |
| `POST /nocobase-auth/sync` / `webhook` | **删除** |
| `GET /nocobase-auth/users` / `roles` | 保留；改为实时透传查询 |
| `GET/PUT /nocobase-auth/config`、`POST /test-connection` | 保留 |

## 10. 数据迁移 / 清理

- 部署升级后，遗留的 `nocobase_permissions.json`、`auth.json` 不再被读取。**不自动删除**（避免误删用户数据）；在升级文档中说明可手动删除这两个文件。绝不触碰 `access_control.json`、`nocobase_auth_config.json`、token 用量数据。
- 无数据结构迁移（无新表/新格式）。

## 11. 测试影响

- **删/替**：本地 register/login/token/revoke/update-profile 的后端与前端测试。
- **改**：`AuthMiddleware` 测试改为"纯外部路径"；新增"auth 启用但无 resolver → 全拒"的 fail-closed 测试。
- **插件新增**：`auth:check` 带回角色并缓存；门禁按 `acl_roles` 判定；`role_channel_map` 空→放行、命中 denied / 不在 allow 列表→拒；列表端点实时透传；NocoBase 不可达时列表端点**报错而非空**。
- **回归绿**：外部渠道本地 ACL、token 用量 by_user。
- **前端**：`auth.test.ts` 更新；Login 页无注册分支；Sidebar 无改密入口。

## 12. 风险与验证点

1. **`auth:check` 能否用「用户自己的」token 返回角色**（`appends=roles`）——若不支持，需在实现时确定替代取角色方式，但必须保持"管理员 api_token 不进鉴权关键路径"的目标。**实现前先验证此点。**
2. **删本地账户是核心大改**：`auth.py` 体量大、被广泛引用，需逐一梳理引用点与测试。
3. **NocoBase 硬依赖**：无 NocoBase 即无法鉴权登录——本部署接受（插件随镜像自包含，见 memory `qwenpaw-prod-server`）。
4. **fail-closed 兜底**：务必确保"auth 启用但 resolver 缺失 → 全拒"，杜绝插件加载失败导致的静默 fail-open。

## 13. 实现分阶段（供后续 writing-plans 细化）

1. **插件实时化**：`auth:check` 取角色 + 缓存二元组；门禁改用 `acl_roles`；`permission_store` 瘦身；删 `SyncEngine`/sync/webhook；列表端点实时透传。
2. **主包去本地账户**：删 `auth.py` 本地实现与相关端点；中间件纯外部路径；`_should_skip_auth` 安全兜底。
3. **Bootstrap**：env 种子化 NocoBase 配置；启动自检与告警。
4. **前端**：Login 去注册、Sidebar 去改密、`auth.ts`/`status` 契约调整、测试更新。
5. **清理与文档**：遗留文件清理；更新 `website/public/docs/*` 用户文档。
