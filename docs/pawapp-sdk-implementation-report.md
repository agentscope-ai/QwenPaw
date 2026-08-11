# PawApp SDK 通用改动实施报告

日期：2026-08-11
分支：`dev/datapaw-app`

## 结论

本分支已经实现 QwenPaw-Data 所需的两组 PawApp SDK 通用能力：原生 App contract，
以及服务依赖状态与受控生命周期 contract。实现保持 additive、opt-in；未启用这些 API 的
现有 plugin / PawApp 不需要升级适配。

SDK core 没有包含 QwenPaw-Data、Neo4j、PostgreSQL、Docker 或某个云厂商的业务逻辑。
QwenPaw-Data 只是验证 App，其本地容器 adapter 位于 App 自身目录。

## 哪些地方需要改动

### Python PawApp SDK

- `PawApp.enable_standard_capabilities()`：显式启用 app-scoped chat、storage、toast、
  notify 以及 durable chat history 路由。
- `GET /chat/history`：复用 QwenPaw 的标准 session loader 和 message converter，按与
  `chat/chat_stream` 相同的 agent、session、channel、user context 恢复消息；不创建第二份
  transcript store，也不返回 model-internal reasoning block 或 AgentScope runtime hint
  block（例如 current-time / environment reminder）。
- `/chat/sessions`：使用现有 `ChatManager` 提供 list/create/rename/archive；新会话由
  Host 生成 `pawapp:{appId}:dialogue:{uuid}`，并通过 `ChatSpec.meta.pawapp`、agent、user、
  channel 共同确认归属。旧 `pawapp:{appId}` transcript 原地注册为 legacy dialogue，不复制
  session 数据。
- `PawApp.managed_service()`：提供动态 loopback port、readiness、受控 shutdown 和
  external endpoint 模式，并可映射为 dependency。
- `PawApp.agent_profile()`：声明 App-owned agent identity，由标准 workspace manager
  启动，卸载时只解绑 profile，保留 session 与 artifact。
- `PawApp.dependency()`：声明 ownership、capability、required、probe 和 optional
  lifecycle adapter。
- `PawApp.enable_dependency_agent_tools()`：显式注册 app-scoped dependency status / action
  tools。
- `DependencyRegistry`：执行缓存 probe、状态聚合、single-flight action、幂等和
  action 后 readiness。
- 标准路由：`/dependencies`、`/capabilities`、dependency detail 和 typed action。

### Frontend PawApp SDK

- `paw.forApp(appId)`：创建永久绑定 app scope 的 handle。
- `paw.api`：统一 authenticated app-relative 请求和 traversal 防护。
- `paw.ui.registerPage()`：注册无 iframe 的原生 App page，并提供 deterministic dispose。
- `paw.chat(..., { agentId, sessionId, skill })`：显式路由到 App-owned agent；
  `paw.api.events()` 提供 authenticated GET/POST SSE 与完整 event frame。
- `paw.getChatHistory({ agentId, sessionId })`：读取同一 Host session 的持久化
  user/assistant transcript、tool call 和 tool output，供 App 重建自己的 trace UI。
- `paw.chatSessions`：提供 list/create/rename/archive；创建结果的 `sessionId` 可直接传给
  `paw.chat()` / `paw.chatStream()`，从而获得独立 context window。
- `paw.dependencies`：提供 `list/get/check/action/subscribe`，复用 Host 的鉴权和 typed
  error。

### QwenPaw-Data App

- Context API 使用 `managed_service()`，不暴露动态端口或 bearer token 给浏览器。
- Graph Store 和启动时发现的数据源注册为 external dependency，只执行脱敏 readiness
  check；本地基础设施 lifecycle 由 `datapaw-cli` 包负责，App 不直接调用 Docker。
- Data sources 页面展示 summary、health、lifecycle、latency、remediation 和可用 action。
- Agent 使用与 UI 相同的 dependency control plane，不猜测命令，也不负责长期 polling。
- Analysis page 在 App 内切换导航时保持 mounted；浏览器 reload 后通过
  `paw.getChatHistory()` 恢复同一 session，并从保存的 tool call/output 重建查询 trace。
- Analysis page 可创建和切换 dialogue；当前 dialogue 存在 app storage，session catalog
  存在 Host `ChatManager`，而消息和模型 context 仍以 Host session store 为 source of
  truth。
- Analysis header 固定在 chat scroll viewport 顶部，滚动后压缩为 conversation/source
  control bar；状态栏按 Core、Business data、Graph、Skills 分类，required 与 optional
  failure 不再混为一个模糊的 Healthy。
- DataPaw 注入给模型的 datasource routing directive 在历史 UI 中被隐藏，用户只看到原始
  问题。QwenPaw session 仍然是 transcript source of truth。

## 为什么需要这些改动

原先的浅层 App health 只能说明 HTTP 进程存在，不能说明图存储、数据源或具体查询能力
可用。数据源出现在选择列表中也只代表已经注册，不代表连接成功。

如果每个 App 自己定义状态 JSON、错误文本和启动命令，会造成协议漂移、安全边界不一致，
Host UI 和 Agent 也无法复用。统一 contract 将确定性的 probe 与 lifecycle 留在 control
plane，把解释、重试和用户沟通留给 Agent。

## 怎么实现

1. App 注册脱敏、bounded probe，返回独立的 health 和 lifecycle 状态。
2. Registry 并发检查依赖，缓存结果，并按 required dependency 聚合 App / capability
   summary。
3. Lifecycle 只接受 App 预注册的 `start/stop/restart/provision` callback，不接受任意命令。
4. Mutating action 按 dependency single-flight，支持 `Idempotency-Key`，执行后必须通过
   readiness probe。
5. HTTP、Frontend SDK 和 optional Agent tools 都读取同一个 registry。
6. Runtime-specific adapter 留在 App 或 Host integration package 中。

## 向后兼容性

- 现有 PawApp 不调用新 API时，原路由、工具和生命周期不变。
- Standard capabilities 和 Agent dependency tools 均为显式 opt-in。
- `managed_service()` 的原有返回值、`status()` 和 startup/shutdown 语义保留；dependency
  projection 是 additive route，不要求旧前端使用。
- `paw.dependencies` 是新增 namespace；现有 `paw.api`、`paw.chat`、`paw.storage`、
  `paw.toast`、`paw.notify` 不变。
- `paw.getChatHistory` 和 `/chat/history` 为 additive API；旧 App 不调用时行为不变，已有
  session JSON 无需迁移。
- `paw.chatSessions` 为 additive namespace；旧 App 显式传入的 custom session ID 不会被
  改写，但只有 Host 生成或 legacy-adopted 的 app session 会出现在 dialogue list。
- 外部依赖默认无 mutation action，不会被 SDK 或 Agent 自动启动/停止。
- 状态响应包含 `schema_version`，后续字段按 additive evolution 扩展。

## Owning team 评审关注点

- HTTP action 是否需要额外接入 Host 的统一 permission challenge UI；
- Agent lifecycle tool 的默认 governance policy；
- 动态 dependency provider 的正式接口；
- Host-wide 标准 status component 是否进入 SDK；
- action audit 是否从结构化日志升级到统一 audit store。
- Permanent delete、archive browsing、auto-title 和 history pagination/cursor contract；
- Cloud 多用户环境下从 authenticated identity 强制派生 app/session/user scope 的规则；

这些评审项不影响 QwenPaw-Data 当前通过 app-owned adapter 运行，但应在 SDK 合并前明确。
