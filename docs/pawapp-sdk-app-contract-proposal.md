# PawApp SDK 原生应用、对话与服务依赖统一 Proposal

> 本文是 PawApp SDK 团队的统一评审材料，合并了原生 App contract、对话与 Session
> contract、服务依赖与生命周期 contract，以及 `dev/datapaw-app` 的实施报告。

- 状态：Draft，待 PawApp SDK owning team 评审
- 日期：2026-08-11
- 验证分支：`dev/datapaw-app`
- 验证应用：QwenPaw-Data / DataPaw
- 适用范围：需要原生页面、App-owned Agent、持久对话、私有 backend/sidecar 或外部依赖的 PawApp

## 1. 执行摘要

本 Proposal 建议把已由 DataPaw 验证的通用能力沉淀到 PawApp SDK：

1. **原生 App contract**：App 获得永久绑定的 API scope、原生页面注册、Host 鉴权和统一
   SSE，不再直接组合低层 Plugin globals、固定端口或第二套 request client。
2. **对话 contract**：App 可以恢复 Host transcript、创建和切换独立 dialogue，并继续复用
   QwenPaw 现有 `ChatManager` 与 Session Store。
3. **服务 contract**：App 可以声明由 Host 管理的私有服务，SDK 负责动态 loopback 端口、
   readiness、受控 shutdown 和 external mode。
4. **依赖 contract**：App 可以声明 dependency、capability、probe 和有限 lifecycle action，
   让 App UI、Host UI 和 Agent 读取同一份结构化、脱敏状态。

所有能力都是 **additive、opt-in、app-scoped**。未采用新 API 的现有 PawApp 和 Plugin
不需要迁移，也不会获得额外路由、后台 probe 或 Agent tools。

SDK Core 不包含 DataPaw、Neo4j、PostgreSQL、Docker、Hologres 或特定云厂商逻辑。
DataPaw 只是第一个验证案例，领域 adapter 仍属于 App、Host integration package 或部署控制面。

核心职责原则：

> Host control plane 负责确定性的 scope、Session、probe、lifecycle、permission 和 audit；
> App 负责业务体验；Agent 负责理解状态、请求已允许的动作并向用户解释，不负责长期监督服务。

## 2. 希望 PawApp 团队确认的决策

### 2.1 建议本次接受

- `paw.forApp(appId)` 作为原生 App 的推荐入口；
- `paw.api`、`paw.ui.registerPage()` 和 authenticated SSE 的 app-scoped 语义；
- `paw.getChatHistory()` 与 `paw.chatSessions` 的公共 contract；
- Python `enable_standard_capabilities()`、`managed_service()` 和 `agent_profile()`；
- dependency/capability 状态模型、只读 API 和 `paw.dependencies`；
- typed lifecycle action 的接口形状与安全约束。

### 2.2 需要 owning team 明确

1. Mutating lifecycle action 是否必须统一接入 Host permission challenge；
2. Action audit 是先使用结构化日志，还是直接进入统一 audit store；
3. 通用 dependency Agent tools 的默认 governance policy；
4. Dynamic dependency provider 是否进入 v1；
5. Host 是否提供标准 status component，还是只提供 contract 与可选组件；
6. Cloud 多用户环境如何从 authenticated identity 强制派生 user/channel scope；
7. Dialogue delete、archive browsing、pagination/cursor 是否进入首个正式版本。

这些问题不阻塞 DataPaw 通过 app-owned adapter 运行，但在 SDK 正式发布前应确定。

## 3. 问题与目标

### 3.1 当前问题

缺少统一 contract 时，原生 App 往往需要自行处理：

- API 前缀、鉴权、路径校验和页面卸载；
- Agent 选择、Session ID、History 恢复和 Dialogue 列表；
- sidecar 动态端口、Token、readiness 和 shutdown；
- dependency 状态、错误码、重试、操作按钮和 Agent tool；
- Host、App UI 与 Agent 之间的状态同步。

这会导致协议漂移和安全边界不一致。例如服务进程已经存活，并不表示 Graph Store 或业务数据源
可用；数据源已经注册，也不表示能够执行查询；Agent 也不应临时猜测 `docker`、`systemctl`
或 Kubernetes 命令来恢复基础设施。

### 3.2 设计目标

- 一个 App 只能访问和注册自己的 Host surface；
- Chat、History 和 Dialogue 使用同一套 Host Session 基础设施；
- Liveness、Readiness、Dependency health 和 Capability health 可以分别表达；
- App UI、Host UI 和 Agent 使用同一份状态；
- Service URL、Token、Credential、PID 和内部异常默认不出现在公共响应中；
- Lifecycle action 必须 typed、bounded、可授权、可审计、幂等并有 readiness；
- API additive evolution，现有应用无强制迁移。

### 3.3 非目标

- 不创建 PawApp 专用的第二套 Transcript 或 Conversation Database；
- 不让 LLM 持续 polling、管理 PID 或拼接任意 shell command；
- 不自动 provision 或重启企业外部共享服务；
- 不把 Docker 设为 SDK 唯一运行时；
- 不让 health API 取代正式 observability/metrics；
- 不在 SDK Core 中引入任何 DataPaw 领域对象。

## 4. 总体架构与责任边界

```text
Native PawApp UI
  -> paw.forApp(appId)
  -> authenticated /api/{appId}/*
  -> PawApp backend
       -> Host ChatManager + Session Store
       -> ManagedService / External Service Gateway
       -> DependencyRegistry
            -> Host/App managed dependency
            -> External dependency
```

| 层                | 责任                                                                    |
| ----------------- | ----------------------------------------------------------------------- |
| Host / PawApp SDK | Scope、鉴权、Session、标准路由、service lifecycle、probe、action policy |
| PawApp            | 页面布局、业务术语、业务 tools、领域 adapter、remediation 文案          |
| Agent             | 读取状态、请求已注册动作、最多一次恢复/重试、解释结果                   |
| Deployment / CLI  | Docker、systemd、Kubernetes、云资源和长期基础设施生命周期               |

## 5. Frontend SDK Contract

### 5.1 永久 App scope

```ts
const paw = window.QwenPaw.paw.forApp("example-app");
```

`forApp(appId)` 返回永久绑定到一个 App 的 handle：

- `paw.api` 自动添加 `/api/{appId}` 前缀并复用 Host 鉴权；
- `paw.ui` 只能注册 `/apps/{appId}` 下的页面和扩展；
- Chat、Storage、Dependencies 和 Toast 均使用同一个 App scope；
- 两个 App handle 不能 cross-call 或 cross-register。

永久 scope 拒绝：

- 绝对 URL；
- query/hash 混入 path；
- 反斜杠；
- decoded 或 double-encoded dot segment；
- App scope 外的页面或 API path。

Query 参数必须通过专门的 `query` option 传递。Legacy dynamic API 在独立 deprecation 周期前
保持旧行为。

### 5.2 统一 App API 与 SSE

`paw.api` 支持：

- GET、POST、PUT、PATCH、DELETE；
- JSON、下载和 `FormData` 等 native body；
- authenticated GET/POST SSE；
- named event、multiline data、event ID 和 cancellation；
- Host 标准 typed error。

```ts
const result = await paw.api.post("/query", { question: "..." });

for await (const event of paw.api.events("/tasks/session/dag/events")) {
  console.log(event.event, event.data);
}
```

### 5.3 原生页面

```ts
const page = paw.ui.registerPage({
  label: "Example",
  mount(container) {
    const root = createRoot(container);
    root.render(<ExampleApp paw={paw} />);
    return () => root.unmount();
  },
});
```

- 支持 Host-compatible React component 或独立 mount callback；
- 不要求 iframe；
- 返回 deterministic disposable；
- dispose 只能执行一次完整 cleanup；
- App navigation 可以选择保持业务页面 mounted。

## 6. Chat、History 与 Dialogue Contract

### 6.1 Chat 调用

```ts
const scope = {
  agentId: "example-agent",
  sessionId: "pawapp:example-app",
};

await paw.chat("Analyze last week's conversion rate", scope);

for await (const event of paw.chatStream("Analyze it", scope)) {
  render(event);
}
```

`paw.chat()` 和 `paw.chatStream()` 支持显式 `agentId`、`sessionId` 和 `skill`，不依赖可变的
Host 当前选中 Agent。Streaming 保留 assistant delta、tool call、tool output 和错误事件。
当 Runtime 以 `response.status = "failed"` 结束，SDK 必须抛出 `PawChatStreamError`，
并保留 Runtime 返回的 `code`、`message` 和 `detail`。App 不应自行解析失败 envelope，
也不应将已知失败降级为“无文本回复”。旧版 `{ type: "error" }` 事件保持兼容。

### 6.2 History 恢复

```ts
const history = await paw.getChatHistory(scope);
```

`GET /chat/history` 必须复用与 Chat 相同的：

- App context；
- Agent；
- Session ID；
- User identity；
- Channel；
- Host Session loader 和 message converter。

History 返回 user/assistant message 及结构化 tool activity，供 App 重建自己的 trace UI；
不返回模型内部 reasoning、hidden chain-of-thought 或 AgentScope runtime hint。App 注入给模型的
routing directive 也不应被重新显示成用户消息。

### 6.3 Dialogue lifecycle

```ts
const dialogues = await paw.chatSessions.list({
  agentId: "example-agent",
});

const next = await paw.chatSessions.create({
  agentId: "example-agent",
  name: "New analysis",
});

await paw.chatStream("Start with a clean context", {
  agentId: "example-agent",
  sessionId: next.sessionId,
});

await paw.chatSessions.rename(next.id, "Revenue analysis", {
  agentId: "example-agent",
});

await paw.chatSessions.archive(next.id, {
  agentId: "example-agent",
});
```

当前 contract 实现：`list/create/rename/archive`。

新 Dialogue 由 Host 生成：

```text
pawapp:{appId}:dialogue:{uuid}
```

Dialogue 只有同时满足以下条件才属于当前 App scope：

- Session ID 位于 `pawapp:{appId}` namespace；
- `ChatSpec.meta.pawapp.app_id` 匹配；
- `ChatSpec.meta.pawapp.agent_id` 匹配；
- `ChatSpec.user_id` 匹配；
- `ChatSpec.channel` 匹配。

`ChatManager` 保存 Dialogue Catalog；Host Session Store 继续保存 Transcript 和模型 Context。
当前活跃 Dialogue 可以存入 app-scoped storage，但 app storage 不是 Transcript source of truth。

旧 `pawapp:{appId}` Session 原地注册为第一个 legacy dialogue，不复制、移动或重写 Session 数据。
旧 App 仍可传递 custom Session ID；这些 ID 不被改写，但未由 Host 创建或 legacy-adopted 的
Session 不出现在 Dialogue list。

### 6.4 标准 Backend 路由

App 必须显式调用 `enable_standard_capabilities()` 才注册：

```text
POST  /api/{appId}/chat
POST  /api/{appId}/chat/stream
GET   /api/{appId}/chat/history
GET   /api/{appId}/chat/sessions
POST  /api/{appId}/chat/sessions
PATCH /api/{appId}/chat/sessions/{chatId}
POST  /api/{appId}/chat/sessions/{chatId}/archive
GET/PUT/DELETE /api/{appId}/storage/*
POST  /api/{appId}/toast
POST  /api/{appId}/notify
```

## 7. Python PawApp Contract

### 7.1 标准能力与 App-owned Agent

```python
app = PawApp("Example", app_id="example-app")
app.enable_standard_capabilities()

app.agent_profile(
    "example-agent",
    name="Example Agent",
    persona_dir=persona_dir,
)
```

`agent_profile()`：

- 幂等 provision App-owned Agent identity；
- 交给标准 Workspace Manager 启动；
- 卸载时解绑 Profile；
- 不删除用户 Session、History 或 Artifact。

### 7.2 Managed service

```python
service = app.managed_service(
    "context",
    command=(python, "-m", "example_service", "--port", "{port}"),
    health_path="/health",
    external_url_env="EXAMPLE_SERVICE_URL",
    mode_env="EXAMPLE_SERVICE_MODE",
)
```

Managed mode：

- 分配动态 loopback port；
- 在 App route 使用前启动并等待 readiness；
- 启动失败时清理子进程；
- Host shutdown 时受控停止；
- 捕获 bounded diagnostics；
- 不在公共 `status()` 返回 URL、Token、PID 或 Environment。

External mode：

- 必须显式提供 endpoint；
- 不启动本地进程；
- lifecycle 显示为 external/unmanaged；
- Credential 仍只存在于 backend。

App backend 可以通过 allowlisted gateway 向 UI 暴露有限业务路径；浏览器不应知道私有服务端口
或 bearer token。

### 7.3 PluginApi delegation

Skill provider、prompt section、workspace callback、runtime hook 和 tool registration 继续委托给
现有 `PluginApi`。PawApp 不直接获得或绕过 Plugin registry，也不创建第二套 Extension 系统。

## 8. Dependency 与 Capability Contract

### 8.1 概念模型

```text
PawApp
  -> Capabilities
       -> Dependencies
            -> Health Probe
            -> Optional Lifecycle Adapter
  -> DependencyRegistry
       -> Structured Status
       -> Typed Action
       -> App UI / Host UI / Agent tools
```

- **Service**：Host/App 明确管理的运行单元；
- **Dependency**：App 使用的下游资源；
- **Capability**：面向用户的功能，可以依赖多个 dependency；
- **Probe**：确定性、bounded、脱敏的健康检查；
- **Lifecycle adapter**：预注册的有限操作；
- **DependencyRegistry**：probe、聚合、缓存、single-flight 和 readiness 的控制面。

### 8.2 状态维度

不要用一个枚举同时表达 ownership、lifecycle 和 health。

```text
Ownership: host_managed | app_managed | external
Lifecycle: unknown | not_installed | stopped | starting | running |
           stopping | failed | unmanaged
Health:    unknown | checking | healthy | degraded | unavailable
```

具体故障使用稳定 `error_code`：

```text
AUTHENTICATION_FAILED
CONFIGURATION_INVALID
CONNECTION_REFUSED
PROBE_TIMEOUT
START_FAILED
READINESS_TIMEOUT
ACTION_NOT_ALLOWED
NOT_MANAGED
```

状态响应包含 `schema_version`，同一 major 版本只允许 additive optional fields。

### 8.3 Backend API

```python
graph = app.dependency(
    "graph-store",
    display_name="Graph Store",
    ownership="external",
    capabilities=("context-graph", "context-search"),
    required=False,
    probe=DependencyProbe(
        callback=check_graph,
        timeout_seconds=3,
        cache_seconds=10,
    ),
)
```

Probe 返回结构化结果，不把 driver exception 暴露给浏览器：

```python
return DependencyHealth(
    health="unavailable",
    lifecycle="unmanaged",
    error_code="CONNECTION_REFUSED",
    message="Graph store is not accepting connections",
    remediation="Contact the configured service owner",
)
```

标准路由位于当前 App namespace：

```text
GET  /api/{appId}/dependencies
GET  /api/{appId}/capabilities
GET  /api/{appId}/dependencies/{dependencyId}
POST /api/{appId}/dependencies/{dependencyId}/actions/{action}
```

Frontend：

```ts
const snapshot = await paw.dependencies.list();
const graph = await paw.dependencies.get("graph-store");

await paw.dependencies.check("graph-store");
await paw.dependencies.action("local-worker", "start", {
  idempotencyKey: "local-worker:start:request-123",
});

const subscription = paw.dependencies.subscribe(renderStatus);
```

### 8.4 状态聚合

- Required dependency 失败可以使 App `unavailable`；
- Optional dependency 失败只降低受影响 capability；
- Graph 离线不应自动让健康的 SQL query capability 不可用；
- 数据源“已注册”不等于“已连接”；
- UI 可以自定义布局，但必须保留状态、影响、时间、延迟、remediation 和允许动作的语义。

### 8.5 Lifecycle action

允许的 action enum 可以包括：

```text
check | start | stop | restart | provision | open_settings
```

要求：

- 不接受任意 executable、shell、environment 或 command string；
- 可用动作由 ownership、adapter 和 Host policy 共同决定；
- mutating action 按 dependency single-flight；
- 支持 `Idempotency-Key`、timeout 和 rate limit；
- `start/restart` 后必须执行 readiness probe；
- readiness 失败返回 typed error，不能假装成功；
- external dependency 默认只有 `check` 或 `open_settings`；
- `provision` 与 `start` 分离；
- User 点击和 Agent 调用使用相同 permission/audit 模型。

SDK Core 只定义 contract，不实现 Docker、systemd、Kubernetes 或云厂商 adapter。

### 8.6 Probe 与性能

- 默认短 timeout 和缓存，不在每个业务请求前同步探测；
- UI 打开时读取 snapshot，之后 subscription/polling 更新；
- 业务调用失败时允许 bypass cache recheck；
- Probe 使用 bounded worker/queue，不阻塞 App event loop；
- 持续失败采用 backoff；
- Host 记录 latency、timeout、failure 和 saturation。

### 8.7 Agent integration

App 可显式调用：

```python
app.enable_dependency_agent_tools()
```

通用 tools 自动 scope 到当前 App。Agent 可以：

1. 在依赖敏感操作前读取缓存状态；
2. 遇到 typed dependency error 后即时 recheck；
3. 在 policy 允许时请求已注册的 start/restart；
4. 等待 readiness；
5. 对原业务操作最多自动重试一次；
6. 解释恢复结果和 capability impact。

Agent 不可以持续 polling、猜测端口/密码、拼接基础设施命令、重启 external dependency、
无限重试或静默 provision。

### 8.8 Dynamic dependency

当前 SDK 实现静态 `app.dependency()`。DataPaw 在 startup 后发现并注册已配置数据源，验证了
动态来源的需求，但正式 `dependency_provider()` contract 仍待评审：

```python
app.dependency_provider(
    "data-sources",
    list_dependencies=list_registered_sources,
    probe=probe_registered_source,
)
```

Provider 只返回稳定 ID 与脱敏显示信息，Host 不持久化领域 Credential，也不理解 datasource
schema。

## 9. 错误与安全模型

### 9.1 Typed error

依赖故障不应统一返回 HTTP 500：

- `503 Service Unavailable`：依赖临时不可用；
- `424 Failed Dependency`：当前操作明确依赖失败能力；
- `409 Conflict`：Lifecycle 状态冲突；
- `403 Forbidden`：Actor 无权执行；
- `404 Not Found`：Dependency/action 未注册。

```json
{
  "code": "DEPENDENCY_UNAVAILABLE",
  "message": "The graph capability is temporarily unavailable",
  "dependency_id": "graph-store",
  "capability": "context-graph",
  "retryable": true,
  "allowed_actions": ["check"],
  "remediation": "Contact the configured service owner"
}
```

### 9.2 公共响应禁止内容

- Password、Token 或 API key；
- 完整 DSN 或带 Credential 的 URL；
- 内部 Service URL/Port；
- 原始 Stack Trace；
- 不必要的 PID；
- 未授权日志和 Environment。

原始异常只能进入受权限控制的 diagnostics。

### 9.3 Governance

- 只读状态默认不需要基础设施管理权限；
- start/stop/restart/provision 分别定义风险等级；
- Lifecycle callback 只能来自已安装、受信任 App/adapter；
- External shared service 默认禁止 mutation；
- Chat Session scope 在 Cloud 必须从 authenticated identity 派生，不能信任 caller 自选身份。

## 10. DataPaw 验证结果

DataPaw 使用同一套通用 contract 实现：

```text
DataPaw UI
  -> app-scoped PawApp SDK
  -> /api/datapaw/*
  -> DataPaw PawApp backend
  -> private managed Context API
  -> Graph Store + business data sources
```

### 10.1 Runtime

- Context API 使用 `managed_service()`；浏览器不知道动态端口和 bearer token；
- 支持 `DATAPAW_CONTEXT_MODE=external` 交给生产 service manager；
- Graph Store 和数据源声明为 external dependency，只执行 readiness check；
- Docker、本地数据库和图服务生命周期属于 `datapaw-cli` 或部署 owner；
- `datapaw-context`、`datapaw-host-core`、`datapaw-cli`、`datapaw-skills` 使用独立环境，
  不污染 QwenPaw Python environment。

### 10.2 App UI

- 原生页面：Analysis、Semantic model、Context graph、Data sources；
- Analysis 文本和 tool trace 实时 streaming；
- Governed SQL tool output 渲染成结构化结果；
- 页面内导航保持 Analysis mounted；浏览器 reload 后从 Host History 恢复；
- 支持创建和切换 Dialogue，每个 Dialogue 使用独立模型 Context；
- Analysis header 固定在滚动视口顶部，并在滚动后压缩；
- 状态按 Core、Business Data、Graph、Skills 分类；
- Required 与 Optional failure 不再合并成模糊的 `Healthy`；
- Semantic model 页面通过 Context API 读取 CLI CRUD 后的实时配置状态。

### 10.3 Agent

- App-owned `datapaw` Agent 通过标准 Workspace Manager 启动；
- UI 和 Agent 使用同一个 dependency control plane；
- Agent 只调用 read-only context/search/SQL tools 和已注册 dependency action；
- Datasource routing directive 保留在模型 Context 中，但不作为用户 History 展示。

### 10.4 已验证场景

- Managed Context service 启停和 readiness；
- Context、Graph Store、PostgreSQL data source 分别显示真实状态；
- Graph optional failure 不错误覆盖健康的 business data capability；
- Streaming assistant text、tool trace 和 SQL result；
- UI navigation 与 reload 后恢复 History；
- Legacy Session 原地采用；
- New Chat、Dialogue switch、独立 Context、reload persistence 和 archive；
- App scope/path traversal 防护；
- 浏览器公共响应不含 private service 信息。

## 11. 向后兼容与迁移

### 11.1 未采用新 contract 的 App

- 不增加标准路由；
- 不增加后台 probe；
- 不改变 startup/shutdown；
- 不新增 Agent tools；
- 不要求修改 manifest 或重建 UI。

### 11.2 现有 PawApp API

- `paw.api`、`paw.chat`、`paw.storage`、`paw.toast`、`paw.notify` 和 task API 保持；
- `paw.dependencies`、`paw.getChatHistory` 和 `paw.chatSessions` 是新增 namespace/API；
- `managed_service()` 原有 startup/shutdown 与 status 语义保留；
- Dependency projection 不自动改变 restart/auto-start policy。

### 11.3 建议迁移顺序

1. 使用 `forApp()` 建立永久 scope；
2. Opt in standard capabilities；
3. 使用 History 恢复现有 Session；
4. 启用 Dialogue Catalog；
5. 为已有 health endpoint 注册只读 probe；
6. 验证 UI 的 capability degradation；
7. 最后决定是否注册 lifecycle adapter 和 Agent recovery。

不要求一次完成，也不要求迁移已有 Transcript 数据。

## 12. 验收标准与现有测试

### 12.1 SDK 验收标准

- 两个 App handle 不能互相调用 backend 或注册 scope 外页面；
- Encoded traversal 和 malformed permanent path 被拒绝；
- 未 opt-in App 不获得标准 capability routes；
- Page dispose 完整且只执行一次；
- Chat generation、History 和 Dialogue 使用同一 agent/session/user/channel；
- History 包含结构化 tool activity，但排除内部 reasoning/hint；
- Legacy Session 原地 adopted；新 Dialogue 获得独立 Context；
- Managed service 使用动态 loopback port，通过 readiness 并在失败/关机时停止；
- External mode 不启动子进程；
- Dependency status 默认脱敏；
- External dependency 默认不能 start/restart；
- Lifecycle action 具备 permission、audit、idempotency、timeout 和 readiness；
- 同一状态可被 Frontend SDK、Backend API 和 Agent tools 使用。

### 12.2 当前验证证据

- PawApp Python contract、managed service、dependency registry、gateway 和 Session 单元测试；
- Frontend SDK app scope、API、SSE、page dispose、dependencies、History 和 Dialogue 测试；
- DataPaw UI streaming、History、Status model、Graph layout 和 API tests；
- DataPaw 与 Console TypeScript check 和 production build；
- 本地 `8089` 集成验证，包括 service readiness、Graph/SQL、Session lifecycle 和零浏览器错误。

## 13. 分阶段落地建议

1. **Native App + Scope**：`forApp`、`paw.api`、`registerPage`、标准 capability opt-in；
2. **Chat lifecycle**：Streaming、History、Dialogue list/create/rename/archive；
3. **Read-only dependencies**：状态模型、probe、capability aggregation、typed error；
4. **Controlled lifecycle**：Permission、audit、idempotency、readiness；
5. **Agent integration**：Scoped tools、一次恢复与一次业务重试；
6. **Dynamic providers**：Runtime datasource/tenant discovery、批量 probe、分页和并发限制。

每个阶段都保持 additive，并允许 SDK owning team 将当前验证实现拆分成独立 PR/Release。

## 14. 已知后续项

- Permanent Dialogue delete；
- Archived Dialogue 浏览与恢复；
- History pagination/cursor；
- 可选 global Console chat sidebar 集成；
- Auto-title 的 Host 统一策略；
- Dynamic dependency provider 正式接口；
- Host-wide status component；
- 统一 permission challenge 和 audit store；
- Task graph、Artifact 和 Tool renderer adapter；
- Cloud 多用户 authenticated scope enforcement。
