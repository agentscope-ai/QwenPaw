# 第三方 Harness 插件化设计

**目标：**将 Codex、Qoder 的运行集成移出 QwenPaw 默认安装与加载链，并为插件作者提供正式的 `HarnessSpec`，使新增 Harness 无需修改核心代码。

**基线：**`refactor/plugin_harness`，`0db9a8e62`，插件重构 #7565 已合并。本文所有接口、文件迁移和行为均为本次改造的设计约束；“当前事实”另列来源。执行步骤见[实施计划](../plans/2026-10-22-harness-plugins.md)。

## 1. 两个任务及范围

| 总任务 | 交付内容 | 完成条件 |
| --- | --- | --- |
| A：拆出第三方 Harness | 独立 Codex/Qoder 插件；解除核心、前端、迁移和发行包的运行集成依赖 | 无插件环境中原生功能完整，厂商运行模块、SDK、CLI 和 UI 不进入默认安装/加载链 |
| B：增加 Harness SDK | `HarnessSpec`、公开 DTO/Protocol、宿主桥接、注册生命周期、前端契约与独立作者测试 | 仓库外插件仅使用公开 SDK 即可注册后端并完成运行、审批、恢复和注销 |

实现顺序是 **B1 公共契约 → B2 宿主桥接 → B3 SDK 作者验证 → A1 PawPort 插件依赖检查 → A2 Codex → A3 Qoder → A4 前端 → A5 分发 → A6 升级与整体验收**。不把两个总任务拆成互不依赖的并行改造。

本次收益来自功能缺席时移除的成本。以下工作不纳入本次验收收益：账户探测改为短生命周期客户端、探测实例与执行实例分离、空闲进程回收、进程池重设计、状态缓存和新 TTL。启用后的厂商运行语义先按现有实现迁移；列表读取注册元数据属于插件发现所必需的架构行为。

本次也不重构 ACP、`delegate_external_agent`、PawPort 整体架构或原生 Agent Runtime。PawPort 是低频功能，使用某个来源的迁移功能须先安装并启用对应 Harness 插件；不为“未安装插件仍可导入”建立独立历史层或降级路径。不能按 `codex`/`qoder` 字符串全局删除代码。

## 2. 当前事实与迁移约束

- Web 路由及 Agent 管理直接导入 Harness；包入口又加载 Runtime，注册表顶层加载 Codex adapter。[本地源码 (2026/10), 路由入口](../../../src/qwenpaw/app/routers/__init__.py)、[本地源码 (2026/10), 包入口](../../../src/qwenpaw/harnesses/__init__.py)、[本地源码 (2026/10), 注册表](../../../src/qwenpaw/harnesses/registry.py)
- Workspace 负责第三方分发与关闭，Chat 历史读取会请求 Harness 补全。[本地源码 (2026/10), Workspace](../../../src/qwenpaw/app/workspace/workspace.py)、[本地源码 (2026/10), Chat](../../../src/qwenpaw/app/chats/api.py)
- PawPort 使用 Harness 历史类型、写入桥接和 Codex rollout 读取器；Codex 在线迁移还直接取得 adapter，调用外部线程与 Skill 读取方法。[本地源码 (2026/10), 历史导入](../../../src/qwenpaw/portability/import_conversations.py)、[本地源码 (2026/10), Codex 迁移](../../../src/qwenpaw/portability/providers/codex.py)
- `ProviderSpec` 是模型接口，当前 SDK 为 `1.0.0`，公开能力列表没有 `harnesses`。[本地源码 (2026/10), Provider 契约](../../../src/qwenpaw/plugins/providers.py)、[本地源码 (2026/10), SDK 版本](../../../src/qwenpaw/plugins/sdk_version.py)
- 厂商 SDK 已是 extras，但 `full` 包含它们；桌面 spec 强制收集两个厂商的 CLI/元数据。[本地源码 (2026/10), 依赖](../../../pyproject.toml)、[本地源码 (2026/10), 桌面打包](../../../scripts/pack-tauri/qwenpaw.spec)
- SDK 已有 `Registration`、`ResourceScope`、代次校验、活动门禁和卸载账本；前端加载列表仍需验证 enabled/active 的一致性。[本地源码 (2026/10), SDK](../../../src/qwenpaw/plugins/sdk.py)、[本地源码 (2026/10), 资源](../../../src/qwenpaw/plugins/resources.py)、[本地源码 (2026/10), 活动](../../../src/qwenpaw/plugins/activity.py)、[本地源码 (2026/10), 前端加载](../../../console/src/plugins/usePluginLoader.ts)

上述链接锚定改造前路径。文件迁移后保留本文基线 SHA；执行者可用 `git show 0db9a8e62:<path>` 回查。

## 3. 目标边界

### 3.1 核心与插件各自负责什么

| 核心/SDK 宿主保留 | 第三方插件承担 |
| --- | --- |
| 轻量后端注册表、身份和可用性判断 | 厂商后端描述、配置字段、支持能力与原生命令 |
| 原生 Agent 原有路径及第三方通用调用入口 | Codex app-server、Qoder SDK、CLI 发现和厂商版本兼容 |
| 标准请求、流事件及通用历史格式的桥接，按第三方请求加载 | 账户、登录、模型、附件格式、原生会话恢复和厂商事件转换 |
| 宿主审批、有效 Skill/MCP/策略与凭据的受限公开服务 | 将有效能力投影到厂商配置，厂商工具/Skill/MCP 发现 |
| 插件代次、工作区、会话资源和停止行为 | 厂商客户端、子进程、后台读写、登录资源的实现 |
| 通用后端选择及扩展挂载点 | 厂商配置、认证文案、账号状态和专属 UI |
| PawPort 的插件依赖检查和现有迁移流程，检查通过后按需加载 | 对应来源迁移所需的运行读取能力 |

通用桥接保留于宿主，以免每个作者重写消息协议、会话持久化和治理逻辑；它不引用厂商 ID、SDK 或内部实现。注册表和目录访问不加载桥接实现。`__init__.py` 不执行 Runtime 的聚合导入。

### 3.2 安装状态的硬约束

| 状态 | 后端 | 前端 | 分发 |
| --- | --- | --- | --- |
| 未安装 | 仅通用注册/缺失提示；无厂商导入、扫描、进程 | 无厂商入口请求/执行 | 核心 wheel/最小桌面包不携带厂商插件与依赖 |
| 已安装但禁用 | 最多读取 manifest；不执行插件入口或工厂 | 不请求/执行厂商 JS/CSS，热禁用清除注册贡献 | 已安装文件仍占磁盘，不计为体积节省 |
| 已启用 | 声明注册后可按既有操作调用；注册本身不启动运行资源 | 加载该插件贡献，原生页面走通用扩展点 | 仅准备该插件声明的依赖 |
| 启用失败/不兼容 | Agent 保留，后端不可用；原生 Agent 不受影响 | 显示安装/修复/版本问题，不能挂载不可调用控件 | 遵守现有依赖门禁，启动阶段不联网补装 |

冷启动未加载和停用后没有活跃资源可以作为硬指标；热卸载后的 Python RSS 全部归还不作保证。浏览器已缓存文件不自动删除，但不得继续执行其组件或保留注册贡献。

### 3.3 目标文件布局

```text
src/qwenpaw/plugins/
  harnesses.py                  # 新的公开契约，无厂商/Workspace/Runtime 导入
  _harnesses.py                 # 注册、公开上下文与内部服务的适配
  _harness_http.py              # 首个有效贡献激活时挂载的通用管理网关
  _harness_capabilities.py      # 从宿主解析有效 Skill/MCP，按调用加载
src/qwenpaw/runtime/backends/
  __init__.py                   # 无副作用
  registry.py                   # 轻量目录、所有权和代次
  execution.py                  # 按需执行、标准流转换、恢复和资源释放
  streaming.py                  # 通用流转换，来自旧 harnesses/streaming.py
  session.py                    # 原会话写入桥接，执行/迁移时加载
src/qwenpaw/portability/providers/
  codex_rollout_reader.py       # 保留现有算法，插件检查通过后加载
plugins/harness/codex/
  plugin.json
  main.py                      # 只声明 HarnessSpec；工厂内导入 adapter
  adapter.py
  app_server.py
  discovery.py
  projection.py
  frontend/                    # 厂商配置/认证 UI 和构建产物
  requirements.txt
  requirements-test.txt
  tests/
plugins/harness/qoder/          # 同样独立，另含 event_mapper.py
```

`plugins/harness` 是发行目录分类。首版 manifest 仍使用 `type: "general"`，通过 `sdk.capabilities: ["harnesses"]` 声明贡献；不为分类额外增加一套插件生命周期。

## 4. HarnessSpec 公开契约

### 4.1 版本与声明

SDK 升到 `1.1.0`，新增能力 `harnesses`；旧 `1.0.x` 插件继续兼容，新插件要求 `sdk.version >= 1.1.0`。后端与前端 SDK 的版本、声明和检查快照同步更新，`API_EXPORTS` 的新增符号标记 `since="1.1.0"`，不能把旧符号的起始版本一起重写。

公开入口：`qwenpaw.plugins.harnesses`，由 `PluginContext.register_harness(spec: HarnessSpec) -> Registration` 接入现有生命周期。插件不得导入 `qwenpaw.harnesses`、`app`、`runtime`、`drivers` 或下划线宿主模块。

```python
@dataclass(frozen=True)
class HarnessSpec:
    id: str
    label: str
    create: Callable[
        [HarnessContext, dict[str, Any]],
        HarnessBackend | Awaitable[HarnessBackend],
    ]
    capabilities: HarnessCapabilities
    config_fields: tuple[ConfigField, ...] = ()
    description: str = ""
    icon: str = ""
    doc_url: str = ""
    instance_settings_keys: tuple[str, ...] = ()
```

`create` 只在实际调用该后端时运行。声明阶段禁止运行工厂、解析 binary、查询账户或生成投影文件。实例按 `(plugin_id, generation, context_identity, workspace_id, backend_id, instance_settings_revision)` 归属；工厂只接收 `instance_settings_keys` 声明且实际存在的配置值的独立深拷贝。Codex、Qoder 只声明 `("binary",)`。模型、推理和审批等每轮参数从独立的 `HarnessCallContext.settings` 读取，不触发整个后端重建。真正的实例配置变化在空闲时先关闭再重建，运行中拒绝并明确返回 `plugin_busy`；不新增跨工作区共享或空闲回收。

后端 ID 使用 `[a-z][a-z0-9_-]*`，`qwenpaw` 为保留 ID。不同插件同 ID 注册失败并显示占用者；旧注册句柄不能注销新代同名后端。

manifest 可声明只读发现元数据 `meta.harnesses: [{"id": "codex", "label": "Codex"}]`。此字段仅用于停用/缺失插件提示；调用资格始终取决于 ACTIVE 且 activated 的实时注册。加载时验证元数据 ID 与实际注册一致。

### 4.2 上下文、事件和执行接口

以下对象均从公开模块导出，使用冻结 dataclass 或 Protocol，不返回内部 manager、原始请求或 `Workspace`。可复用现有公开 `PluginStorage`、`ResourceScope`、`ConfigField` 和日志服务。

| 类型 | 精确职责/字段 |
| --- | --- |
| `HarnessContext` | `plugin_id, generation, workspace_id, workspace_dir, state_dir, storage, resources, logger`；工厂实例的生命周期上下文 |
| `HarnessCallContext` | `request_id, session_id, user_id, channel, cwd, settings, runtime_capabilities, resources, deadline, cancelled`；每次调用重新创建，不能缓存用户身份；管理调用的 `runtime_capabilities=None`，只有运行调用解析有效能力 |
| `HarnessCallContext.request_approval(summary, *, timeout: float) -> Awaitable[Literal["approved", "rejected", "cancelled", "timeout"]]` | 宿主注入调用，不接受作者覆盖工作区/用户/会话；`summary` 是公开 `HarnessApprovalSummary` |
| `HarnessApprovalSummary` | `tool_name, title, description, parameters, severity`；参数仅 JSON，不含宿主对象 |
| `HarnessRunRequest` | `prompt: str, attachments: tuple[HarnessAttachment, ...]`；模型/推理/审批选项来自 `context.settings` |
| `HarnessEvent` | 沿现有 `kind, text, item_id, tool_name, data` 语义；kind 固定为正文/推理增量、工具开始/进度/完成、完成、取消、错误 |
| `HarnessHistoryItem` / `HarnessHistoryKind` | 直接在公开 SDK 中定义原历史字段和类型；无须另建通用 history 包，不加载厂商实现 |
| `HarnessStatus` | 安装、认证、公开账号、runtime 路径/来源、错误；只在显式状态调用返回，不在目录枚举时生成 |
| 其余 DTO | `HarnessAttachment, HarnessCapabilities, HarnessCommand, HarnessApprovalPreset, HarnessModel, HarnessLogin, HarnessDiscoveredSkill, HarnessDiscoveredMCPServer`；沿当前对应字段迁移并冻结公开语义 |

`HarnessCapabilities` 保留当前 UI/执行能力布尔值、`commands` 和 `approval_presets`，新增 `external_history: bool = False`，用于声明厂商在线历史读取。PawPort 的来源可用性先取决于对应插件是否已安装并启用，不由这个能力位替代。其他不支持的能力由元数据和 `HarnessOperationNotSupportedError` 表达。

`HarnessBackend` 的方法签名固定为：

```python
async def status(context: HarnessCallContext) -> HarnessStatus
async def start_login(context: HarnessCallContext, *, device_code: bool = False) -> HarnessLogin
async def logout(context: HarnessCallContext) -> None
async def models(context: HarnessCallContext) -> tuple[HarnessModel, ...]
async def discover_skills(context: HarnessCallContext) -> tuple[HarnessDiscoveredSkill, ...]
async def discover_mcp(context: HarnessCallContext) -> tuple[HarnessDiscoveredMCPServer, ...]
def run_turn(context: HarnessCallContext, request: HarnessRunRequest) -> AsyncIterator[HarnessEvent]
async def run_command(context: HarnessCallContext, command: str, arguments: str) -> tuple[HarnessEvent, ...]
async def history(context: HarnessCallContext) -> tuple[HarnessHistoryItem, ...]
async def reset_session(context: HarnessCallContext) -> None
async def close() -> None
```

这些是 Protocol 方法，代码实现均带 `self`。管理操作中没有会话时 `session_id=""`，运行/历史/清空操作要求非空且由宿主校验。取消沿异步任务和生成器关闭传播，adapter 将其映射到厂商 interrupt/disconnect；首版不新增第二套取消 API。`close()` 必须幂等并等待真实资源结束。

### 4.3 有效能力与历史迁移

`HarnessRuntimeCapabilities` 包含 `skills: tuple[HarnessSkillDefinition, ...]`、`mcp_servers: tuple[HarnessMCPServerDefinition, ...]` 与非明文凭据指纹。Skill 字段保留 `name, description, directory, revision`；MCP 字段保留当前 transport、endpoint、环境/请求头、工具白名单、策略和 revision。秘密值的 repr/日志/通用序列化必须脱敏，只在运行边界通过显式访问函数揭示。

解析逻辑留在 `_harness_capabilities.py`，每次运行由宿主按真实 workspace/user/channel 计算，随后作为 DTO 交给插件。插件的 projection 负责厂商格式转换，不能自行导入内部 DriverConfigService 或凭据提供器。审批复用原服务与原决策语义，不增加新的认证体系。

PawPort 的 Codex 在线迁移不能取得裸 adapter。新增可选公开 `HarnessArchiveBackend` Protocol，`external_history=True` 的实现还提供：

```python
async def list_external_threads(context: HarnessCallContext, *, limit: int, archived: bool) -> tuple[dict[str, Any], ...]
async def read_external_thread(context: HarnessCallContext, thread_id: str) -> tuple[HarnessHistoryItem, ...]
async def external_skill_records(context: HarnessCallContext) -> tuple[dict[str, Any], ...]
async def external_mcp_records(context: HarnessCallContext) -> tuple[dict[str, Any], ...]
```

字典为保留当前迁移元数据的 JSON 快照，拒绝函数、客户端和秘密对象。线程/Skill/MCP 记录沿现有返回结构，宿主不增加厂商字段判断。内部 `BackendExecution.archive(backend_id)` 提供带活动门禁的调用 facade；后端缺失、禁用或激活失败时明确拒绝，不返回 None 触发无插件降级。此接口仅承接现有 Codex 在线读取，不扩展 A1 的迁移架构。

A1 仅做依赖门禁和必要的加载调整：

1. `GET /portability/imports/sources` 展示每个来源所需插件及状态；不可用来源不解析本地路径、不检测 CLI。
2. 创建、开始和重试导入任务时，在扫描/实例化来源 provider 前检查对应插件已安装、启用且激活成功；多来源请求先检查全部来源，失败时不启动任何来源的扫描。
3. 不满足条件返回 HTTP 409，`detail.code="harness_plugin_required"`，附 `source, plugin_id, state`，state 为 `missing|disabled|failed`。界面提供安装/启用入口，不自动安装。
4. 检查通过后执行现有迁移算法，包括已有本地文件读取、在线读取和 local-only 规则；显式 source-home 也不能绕过插件依赖检查。
5. 只调整旧 Harness 导入路径：历史 DTO 用公开 SDK 类型，原会话桥接放入 `runtime/backends/session.py`，rollout reader 随迁移操作加载。不新建中立历史子系统，不重写序列化或迁移算法。
6. 路由/来源目录不得提前导入 provider、运行 adapter 或会话桥接；只读已完成任务报告和已导入的 QwenPaw 聊天历史不要求插件。

### 4.4 注册生命周期

`register_harness` 在 `_harnesses.py` 实现现有 SDK 的 guard、admission、资源账本适配；不要求插件作者使用 legacy `PluginApi`。

1. register 只登记 spec 和释放句柄；调用需等插件完成激活。
2. 工厂和后续调用均计入 owner/代次/工作区；长流的活动计数持续到生成器、后台 producer 和终态持久化全部结束。
3. 普通 disable/reload/uninstall 在活跃任务存在时沿既有 `plugin_busy` 返回；显式中断沿现有入口处理。
4. 停止时先关闭新调用门禁，传播取消、等待受管资源关闭，再撤销注册/HTTP/UI 贡献。
5. 无法 quiesce 时保留失败资源所有权，阻止新代接管；重试和回滚沿 #7565 的现有规则。
6. 工作区关闭只关闭该工作区实例；插件停用关闭其所有工作区实例；绝不重建全部原生工作区。

## 5. API 和前端

### 5.1 API

- 新增通用 `GET /api/agents/backends`，始终可用，路由顺序置于 `/agents/{agentId}` 前；返回内置 qwenpaw 和已激活注册的静态描述，附已安装但禁用/失败的纯 manifest 元数据。目录不调用工厂/`status()`。条目固定包含 `id, label, plugin_id, status, capabilities, config_fields`，其中 `status=available|disabled|failed`；完全未安装的后端由插件目录或已保存 Agent 的 missing 状态提示，不凭空加入注册表。
- 管理网关保留 `/api/harnesses` 及 `/{provider_id}/status|login|logout|models|skills|mcp` 的现有相对路径。由 SDK 协调器在首个 Harness 激活时挂载，最后一个注销后卸载；不是两个插件分别抢占同一 prefix。调用继承原认证、X-Agent-Id 和访问检查。
- `/api/harnesses` 在有网关时返回静态目录；无有效插件时路径可为 404，新 UI 只用 `/agents/backends` 做发现，不依赖该 404 判别安装状态。
- 通用执行和 Agent CRUD 不引用厂商 ID。未知/禁用 backend 的执行返回 `backend_unavailable`，已有 Agent 的列表、读取、重命名、删除仍可用；创建和真正切换 backend 必须验证实时注册，禁止静默 fallback 到 qwenpaw。
- 后端同 ID 重新启用后重新求值可用性；既有已装配 HTTP handler 也必须每次验证 owner/代次，不持有可绕过门禁的旧 adapter。

### 5.2 前端

核心保留通用后端选择器、`BackendModelSelector` 和 `BackendApprovalToggle`。后两者是现有共享控件的泛化，使用能力描述和通用 API，不包含厂商 SDK、名称分支或厂商文案。厂商设置、认证和连接说明移到对应插件。

前端 SDK 新增 `window.QwenPaw.harnesses.register(pluginId, extension) -> Disposable`：

```typescript
interface HarnessFrontendExtension {
  backendId: string;
  SettingsComponent?: React.ComponentType<HarnessSettingsProps>;
}
interface HarnessSettingsProps {
  backendId: string;
  value: Record<string, unknown>;
  onChange(value: Record<string, unknown>): void;
  open: boolean;
}
```

`SettingsComponent` 接入创建和编辑 Agent 表单，保存前提交给后端校验；缺少插件前端时按 `config_fields` 渲染，主 Chat 仍可运行。无需另增模型/审批插槽，首版复用泛化控件。扩展对象只替换所属后端的设置区域，不能接管整个 Agent 创建页。

frontend_plugin 服务仅返回可执行的 enabled+ACTIVE+activated 入口；无 loader 的磁盘回退只返回元数据且不能执行脚本。前端 loader 同时过滤状态，启停事件触发加载/卸载，插件清理调用新增 harness registry 的 `disposeAll(pluginId)`。不修改无关插件的认证页扩展约定。

## 6. 插件迁移、分发与旧用户

### 6.1 两个独立插件

| 插件 ID | backend ID | 初版依赖 | 原实现来源 |
| --- | --- | --- | --- |
| `qwenpaw-harness-codex` | `codex` | `openai-codex==0.144.4` | `harnesses/codex/{adapter,app_server,discovery,projection}.py` |
| `qwenpaw-harness-qoder` | `qoder` | `qoder-agent-sdk==1.0.9` | `harnesses/qoder/{adapter,discovery,event_mapper,projection}.py` |

版本固定沿基线，不在本次顺便升级。依赖和平台可执行文件随插件显式安装准备，使用现有 DependencyGate/桌面 Python runtime；不得在宿主启动时自动 pip 安装。Codex 用户无需安装 Qoder，反之亦然。

### 6.2 数据兼容

- `agent.json` 的 backend ID 与 backend_settings 原样保留；模型、推理强度和审批设置不重置。
- 新状态目录为 `<workspace>/plugin-data/<plugin_id>`，与插件代码安装目录分离。宿主通过 `HarnessContext.state_dir` 提供。
- 各插件首次实际打开时，若新状态不存在，从 `context.workspace_dir/harnesses/codex_sessions.json` 或 `qoder_sessions.json` 原子复制自身映射；旧文件保留。目标已存在时不覆盖；校验失败时报可恢复错误，不能以空映射覆盖。
- 可再生的 Skill/MCP 投影缓存使用新状态目录重新生成；不移动厂商原生账户和原生会话目录。
- 读取已物化的 QwenPaw 历史无需运行插件；只有恢复未物化的厂商历史依赖已启用的后端。
- disabled/uninstall 保留工作区状态、Agent、QwenPaw 聊天历史和厂商登录；数据删除走另外的显式功能。

### 6.3 发行和升级

新安装不默认安装/启用两个 Harness 插件，下载目录只提供可选插件。插件框架缺省启用的语义不改；通过“不预装”实现 opt-in，不能把文件放入默认 bundle 后依赖缺省行为。

从 `full` 和最小桌面打包中移除两个 SDK/CLI；root test extra 不再要求 Qoder，厂商测试依赖移到各插件测试环境。`codex`/`qoder` extras 暂保留一个兼容发布周期，仅准备依赖，不代表插件已安装；原安装提示和文档同步调整。测试需明确验证这个区别。

增加 `plugins/harness` 到 metadata、前端构建、上传和下载分类，并同步主 `release.yml` 与 legacy `plugins-release.yml`。插件 zip 与主包可独立版本化，最小宿主版本要求通过 SDK/manifest 声明。

旧用户升级由升级器的迁移步骤处理：读已有 Agent backend，只为确实使用的后端预备插件包和依赖，并在新宿主启动前完成；没有第三方 Agent 的用户不增加插件。新增 `scripts/pack/migrate_legacy_harnesses.py`，提供 dry-run/apply，输入已验证的本地插件包和依赖准备结果，沿正式安装事务安装；插件显式禁用记录优先，重复执行幂等。CLI 发布提供同一迁移命令的操作说明。

无法离线准备的升级不能宣称无缝完成：保留 Agent 和全部数据，显示所需插件及安装动作；宿主启动不自动联网。官方升级验收必须覆盖提前准备成功和缺包提示两个分支。

## 单 worker I/O 约束

所有 Harness 的新调用路径按操作边界检查阻塞 I/O。目录/metadata/binary 发现、状态文件读写、Skill 哈希和投影文件复制使用现有异步文件 helper 或有界 `run_sync_io()`；纯注册和元数据读取不能顺带扫描磁盘。不要在 adapter 构造函数中读状态文件，应在异步准备步骤完成。

异步工厂、asyncio 客户端/锁/队列和资源归属保持在事件循环；线程只处理输入/输出清晰的同步 I/O，不执行完整模块、生命周期或整个能力 resolver。共享文件的原子读改写仍由宿主协程持有域锁；取消等待不能让底层线程越过锁的释放边界。

用少量事件协调测试覆盖实际阻塞操作时无关 API/heartbeat 可推进，以及取消时资源/文件归属不提前释放。功能和测试分别由不同 agent 编写，断言不能被实现者调整为“通过”。

## 7. 接受标准

### 两个任务的完成 checklist

- [ ] A：`src/qwenpaw/harnesses` 的厂商运行实现移出核心，旧硬编码工厂和常驻路由引用移除。
- [ ] A：无插件冷启动不导入厂商运行模块/SDK、不中断原生聊天、不扫描 CLI、不启动厂商进程。
- [ ] A：已安装但禁用时同样不执行插件后端/前端入口。
- [ ] A：创建/编辑、模型、推理、工具/推理流、附件、审批、命令、续接和历史恢复逐项迁移。
- [ ] A：PawPort 使用某来源前要求对应插件已安装并启用；缺失/禁用/失败有明确提示，检查前不扫描或导入运行实现；已导入聊天仍可正常读取。
- [ ] A：最小 wheel/桌面包、默认前端不携带厂商运行代码或 CLI，单插件环境无另一厂商依赖。
- [ ] A：旧 Agent/设置/会话映射保留，升级、停用、重新启用、卸载和失败恢复可重复验证。
- [ ] B：`HarnessSpec` 和所有作者需要的 DTO/Protocol 在公开白名单、类型和 SDK 1.1 中可用。
- [ ] B：注册、生命周期、长流、审批、资源失败与配置更新沿现有 SDK 规则工作。
- [ ] B：独立作者 fixture 从 wheel 安装后只用公开 SDK 完成全链路，不能依赖仓库 conftest。
- [ ] B：一个第三种 fake Harness 无核心改动即可注册、创建 Agent、聊天和注销。

### 减负归因与测量

对照 `0db9a8e62` 与本分支完成版本，在同硬件、Python、配置和依赖环境中测原生 Agent 场景。对照组不要叠加探测/空闲进程优化。

记录至少 5 次独立进程启动的中位数、最大值与原始记录：ready 时间、主进程及子进程 RSS、导入模块集、厂商进程/探测次数、默认页面加载字节、wheel/桌面包文件清单与大小。无插件与禁用状态的导入/进程/探测/入口执行计数必须为 0；耗时和 RSS 如实报告，不预设没有测量依据的节省百分比。

验收报告区分“未安装减少的磁盘/依赖”“禁用减少的加载/活动资源”“启用后的功能兼容”。本次不使用启用后新增运行优化证明插件化收益。
