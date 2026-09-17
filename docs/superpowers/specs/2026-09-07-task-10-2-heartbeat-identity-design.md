# Task 10.2 Heartbeat 安全主体和目标设计

## 1. 目标与范围

Task 10.2 将 Agent 级 Heartbeat 从固定 `main` 用户身份改为受限的后台自动化身份，并保证 `main`、`last`、`inbox` 三种目标均绑定明确的授权用户。

本任务保留现有 Heartbeat 页面、`HEARTBEAT.md`、启停、执行间隔、Cron 表达式、超时、活跃时段、热重载和“立即运行”能力。私人收件箱完整 CRUD、审批页面和管理告警分流属于 Task 10.3，不在本任务扩展。

## 2. 已确认决策

- 在 Agent 的 Heartbeat 配置中保存 `authorized_by_user_id`，不新增数据库表或迁移。
- 用户保存 Heartbeat 配置时，服务端从可信 `ActorContext` 写入授权用户，忽略客户端伪造身份。
- Heartbeat 以 `agent_automation` 受限主体运行，不伪装成普通聊天用户。
- 定时触发和“立即运行”调用同一身份与目标解析服务。
- `main` 使用按 Agent、授权用户隔离的专用自动化会话。
- `last` 只允许解析授权用户自己的、当前仍有效的目标。
- `inbox` 只写入授权用户的私人收件箱。

## 3. 数据模型

在 `HeartbeatConfig` 增加服务端字段：

```text
authorized_by_user_id: UUID | null
```

多用户模式下：

- 新建或修改 Heartbeat 配置时由服务端覆盖为当前用户 ID。
- 客户端读取配置时可获得“已授权/需重新授权”状态，但不需要编辑用户 ID。
- 旧配置没有该字段时保持可读取，但不能启用或执行；有编辑权限的用户保存后完成授权迁移。
- 授权用户被禁用、失去 Agent 访问权或 Agent 被禁用后，执行前校验失败，不回退到 Agent owner、管理员或最后登录用户。

单用户兼容模式下保持原行为，不强制要求用户 UUID。

## 4. 运行主体与专用会话

新增聚焦于 Heartbeat 的身份解析单元，输出不可变运行上下文：

```text
HeartbeatRunIdentity
  authorized_user_id
  actor_type = agent_automation
  agent_id
  session_id
  channel
  request_context
```

多用户模式的专用会话 ID 使用稳定格式：

```text
heartbeat:<agent_id>:<authorized_user_id>:main
```

请求中的 `user_id` 用于数据隔离，值为授权用户 ID；`request_context.actor_type` 明确为 `agent_automation`，并携带 `authorized_by_user_id`、`agent_id` 和来源 `heartbeat`。这样存储仍归属真实用户，而运行权限受自动化主体限制。

## 5. 目标解析

### 5.1 main

始终运行在专用自动化会话，不读取或写入普通用户的 `main` 会话，也不向频道投递事件。

### 5.2 inbox

运行结果、超时和错误事件的 `recipient_user_id` 均取 `authorized_by_user_id`。Trace 使用同一个专用会话与授权用户，因此详情不会引用其他用户的会话内容。

### 5.3 last

现有 Agent 级单值 `last_dispatch` 不能表达多用户最近目标。本任务将最近投递目标改为按平台用户保存，并保留旧字段仅供单用户兼容模式读取。

多用户模式解析 `last` 时必须同时满足：

1. 记录属于 `authorized_by_user_id`；
2. 用户状态有效且仍可访问该 Agent；
3. 频道与会话标识完整；
4. 若目标来自个人频道绑定，该绑定仍启用且归该用户所有；
5. 目标不是另一个用户通过共享 Agent 产生的最近会话。

无有效目标时不发送频道事件。执行应以可诊断的阻断结果结束，并向授权用户私人收件箱写入提示，避免静默回退到 `main` 或其他用户目标。

## 6. 配置与触发流程

### 6.1 保存配置

1. 路由从认证会话构造可信 ActorContext。
2. 校验当前用户至少拥有 Agent owner 或 collaborator 编辑权限。
3. 服务端写入 `authorized_by_user_id`。
4. 保存 Agent 配置并热重载 Heartbeat 调度。

涉及外部投递或高风险工具的长期授权继续使用 Task 10.1 的自动化治理；本任务不新增旁路。

### 6.2 定时执行

1. CronManager 触发 Heartbeat。
2. 身份解析器加载授权用户并复核用户、Agent 和成员状态。
3. 目标解析器解析 `main`、`last` 或 `inbox`。
4. 构造 `agent_automation` 请求并执行。
5. 结果只写入解析后的有效目标或授权用户收件箱。

### 6.3 立即运行

“立即运行”不直接捕获当前 HTTP 用户作为临时运行身份。它先保存或验证配置中的授权用户，再调用与定时执行相同的入口，因此页面测试与无人值守运行具有相同权限语义。

## 7. 错误处理

- 缺少授权用户：拒绝启用或执行，返回 `heartbeat_authorization_required`。
- 授权用户无效：停止执行，记录 `heartbeat_authorization_invalid`。
- 授权用户失去 Agent 权限：停止执行，记录 `heartbeat_agent_access_revoked`。
- `last` 无有效目标：不回退投递，记录 `heartbeat_last_target_unavailable`，并通知授权用户。
- 频道发送失败：保留现有日志并向授权用户收件箱写入失败事件。
- 执行超时或模型异常：Trace 与通知继续绑定授权用户。

错误响应和日志只包含定位所需 ID，不包含其他用户的目标或会话内容。

## 8. 组件边界

- `config/config.py`：声明配置字段及旧配置兼容规则。
- `config/utils.py`：按用户保存和读取最近投递目标。
- `app/crons/heartbeat.py`：解析身份与目标、构造请求、执行和投递。
- `app/crons/manager.py`：仅负责调度并调用统一 Heartbeat 入口。
- `app/routers/config.py`：从可信 ActorContext 写入授权用户，立即运行复用统一入口。
- `runtime/heartbeat.py`：保持 SSE 流心跳职责，不承载 Agent Heartbeat 授权逻辑；若无必要不修改。

该拆分保持单一职责：配置负责持久化，解析器负责授权事实，运行器负责执行，路由只处理可信 Web 主体。

## 9. 验证方案

### 9.1 单元与隔离测试

- 配置保存忽略客户端身份并写入当前用户。
- 多用户模式缺少或失效授权时拒绝执行。
- 请求使用 `agent_automation` 和专用会话。
- `main` 不污染普通 `main` 会话。
- `inbox` 的成功、超时和错误均只写入授权用户。
- `last` 只解析同一授权用户的目标。
- 其他用户后来使用同一 Agent，不改变原授权用户的 Heartbeat 目标。
- 授权用户失去 Agent 权限后目标失效且不回退。
- 单用户模式原有 Heartbeat 行为回归通过。

### 9.2 页面验收

在单个 headless Chromium 内使用两个隔离 context：

1. 用户 A 保存 Heartbeat 并分别验证 `main`、`last`、`inbox`；
2. 用户 B 使用同一 Agent，产生自己的最近会话；
3. 再次运行用户 A 授权的 Heartbeat；
4. 确认结果仍进入用户 A 的专用会话、有效目标或私人收件箱；
5. 用户 B 页面不出现该 Heartbeat 通知和 Trace；
6. 撤销用户 A 的 Agent 权限后运行被阻断，且不投递给用户 B。

验收只启动一个浏览器进程，以多个隔离 context 模拟用户，不要求同时打开多个可见浏览器窗口。

## 10. 非目标

- 不建设新的 Heartbeat 数据库表。
- 不重做 Heartbeat 页面布局。
- 不扩展私人收件箱批量操作或审批功能。
- 不把 Heartbeat 合并成普通 Cron 任务。
- 不允许管理员或 Agent owner 隐式接管其他用户已经授权的 Heartbeat。
