# 第三方 Harness 插件化 Implementation Plan

> 测试维护更新（2026-10-28）：本文保留历史实施/验收记录；旧测试路径、行号和命令不再是当前入口。当前四个核心测试、构建及手工验收边界以[精简方案](../specs/2026-10-28-harness-test-slimming.md)为准。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 2026-10-23 用户已授权执行；功能代码与测试代码由不同子 agent 编写，主 agent 协调集成与独立验证。

**Goal:** 让不使用第三方 Harness 的用户不再安装、加载或装配其厂商运行集成，同时让开发者通过公开 `HarnessSpec` 独立实现新后端。

**Architecture:** 核心保留轻量后端注册/分发和按需加载的 SDK 宿主桥接；Codex、Qoder 各自成为可选插件。PawPort 使用某来源前检查对应插件已安装并启用，检查通过后执行现有迁移流程；不建立无插件导入降级或独立历史子系统。

**Tech Stack:** Python、dataclass/Protocol、现有 QwenPaw Plugin SDK/lifecycle、FastAPI、React/TypeScript、pytest、Vitest、setuptools、PyInstaller。

**Spec:** [第三方 Harness 插件化设计](../specs/2026-10-22-harness-plugins-design.md)。接口签名、状态语义、兼容与分发策略以该文档为准；按 2026-10-23 的执行授权推进，并采用下面新增的单 worker I/O 约束。

**Baseline:** `refactor/plugin_harness` / `0db9a8e62`。#7565 已合并，不再对未合并 PR 打补丁，不创建新分支或新 worktree。

## Global Constraints

- 两个总任务：A 拆出运行集成；B 增加 Harness SDK。执行先 B 后 A，最终一次核对共同验收。
- SDK `1.1.0`；新增 capability `harnesses`；旧 `1.0.x` 插件兼容，新导出 `since="1.1.0"`。
- 插件 ID 固定为 `qwenpaw-harness-codex`、`qwenpaw-harness-qoder`；backend ID 保持 `codex`、`qoder`；`qwenpaw` 为保留 ID。
- 初版依赖固定 `openai-codex==0.144.4` 与 `qoder-agent-sdk==1.0.9`，本次不升级厂商运行版本。
- 插件只导入公开 SDK，禁止使用 `qwenpaw.harnesses`、内部 Workspace/approval/Driver 服务或 monkeypatch。
- 未安装/禁用时无厂商模块导入、CLI 探测、进程和前端入口执行；metadata 读取不得调用工厂。
- 不引入空闲 TTL、进程池、短生命周期账户探测、新缓存或探测/执行实例隔离；这些另立运行优化任务。
- 数据不丢失：Agent/backend_settings、已物化历史、旧会话映射保留；不自动切换 Agent backend，不注销厂商账号。
- 启动时不联网补装；依赖替换仍走现有重启门禁。PyInstaller/桌面依赖准备必须验收。
- 原生 Runtime、ACP 和外部委派工具保持各自原有执行路径；PawPort 仅增加对应插件的依赖检查、提示和必要延迟导入，不建设无插件迁移能力。
- 测试用临时工作目录和模拟引擎，不读真实账号或调用付费模型；真实厂商/平台验收单列。
- 功能 agent 不编辑测试；测试 agent 不编辑功能代码，测试变更必须对应需求或真实回归，不能为了迎合实现而削弱断言。
- 单 worker 下，目录遍历、可执行文件/分发包发现、状态读写、Skill 文件哈希与拷贝等阻塞 I/O 按操作边界异步化；使用现有 async helper 或 `run_sync_io()`，不得把整个模块/生命周期/异步工厂放进线程。
- asyncio 客户端、锁、队列、注册表变更和资源所有权状态只在事件循环操作；取消必须等真实线程 I/O 完成后才释放相应路径/域锁。
- 保持功能集中、实现精炼；只为实际边界和回归编写必要测试，不堆叠防御性分支或镜像实现的测试。


## Review Focus

以下五项必须有对应任务测试，不能只靠“主链路可聊天”判定完成。

1. 已保存第三方 Agent，但插件缺失/禁用/激活失败：能查看历史、重命名和删除；运行明确不可用，重新启用可续接。归 A6。
2. 卸载与长流/审批/终态保存并发：资源未结束时不能报告卸载成功或让新代接管。归 B2。
3. 两个工作区、不同用户/渠道、同名会话并发：身份、凭据、审批和状态目录隔离。归 B2、A3。
4. PawPort 来源插件缺失/禁用/失败、显式 source-home 和多来源请求：先检查依赖，不满足时不扫描；已装插件后仍沿现有迁移流程。归 A1、A2。
5. 最小冻结桌面包先不带厂商 SDK，再显式安装插件：可执行权限、资源目录、依赖解析和重启要求正确。归 A5。

---

## 总任务与提交顺序

| 顺序 | 任务 | 可独立评审的交付 |
| --- | --- | --- |
| 0 | P0 基线与功能清单 | 当前行为、边界证据和可重跑测量工具 |
| 1 | B1 公共契约与注册 | HarnessSpec/DTO、轻量注册表、版本与所有权规则 |
| 2 | B2 宿主桥接与生命周期 | 假 Harness 能在真实 Workspace/Chat/审批/资源门禁中运行 |
| 3 | B3 作者测试和 SDK 文档 | 仓库外 wheel 作者测试与前端契约通过 |
| 4 | A1 PawPort 插件依赖检查 | 使用某来源前要求对应插件已安装并启用，提示安装/启用，检查前不加载运行实现 |
| 5 | A2 Codex 插件 | 通过 SDK 提供现有 Codex 功能与在线 archive |
| 6 | A3 Qoder 插件与后端切换 | 通过 SDK 提供现有 Qoder 功能，移除硬编码厂商工厂 |
| 7 | A4 前端和路由清理 | 厂商 UI 出主包，按插件启用状态加载，管理网关按贡献挂载 |
| 8 | A5 包与发行链 | 可选插件 zip，最小包不含 SDK/CLI，单插件独立安装 |
| 9 | A6 升级、删除旧实现和验收 | 数据兼容、完整功能矩阵、减负证据与文档 |

迁移中间提交可暂保留旧入口，必须明确 SDK/插件测试与旧入口分别验证；A6 才删除最后兼容入口。不得让同一 backend ID 同时存在两条可被实际选择的实现。P0 记录 baseline commit，不能在代码已改后再测“改造前”。

## P0 基线与功能清单

**Files**

- Create: `scripts/measure_harness_footprint.py`
- Create: `tests/unit/harnesses/test_footprint_probe.py`
- Create: `docs/research/harness-plugin-footprint-baseline.json`（仅脱敏环境和测量结果）
- Read: `tests/unit/harnesses/`、`tests/unit/app/routers/test_harnesses_router.py`、`tests/integration/test_harnesses_router.py`

**Interfaces**

- Produces: `python scripts/measure_harness_footprint.py --scenario native-startup --output <json>`。
- 场景固定为 `native-startup`、`native-agent-list`、`native-chat`、`frontend-native`；一次运行使用一个全新进程/临时配置。工具不得创建真实厂商客户端。
- 报告包含 commit、Python/平台、场景、ready_ms、process_rss_bytes、children_rss_bytes、modules、vendor_process_count、vendor_probe_count；前端网络字节和包清单附在最终报告，不伪造为 Python 指标。

- [x] **Step 1：锁定现有功能矩阵。** 将 A6 表格中的每项映射到现有测试和模拟客户端；补全缺口清单，特别是在线 archive、取消与能力投影。
- [x] **Step 2：先测工具而非产品。** 为模块集合、计数、commit 记录和禁止真实厂商进程的行为写失败测试 `test_probe_records_modules_without_vendor_execution`。
- [x] **Step 3：实现测量工具。** 使用新进程和临时工作目录，拦截厂商启动边界记录调用；绝不将整条 import 用时当作可节省的边际时间。
- [x] **Step 4：验证工具。** Run: `python -m pytest tests/unit/harnesses/test_footprint_probe.py -q`；预期 PASS 且测试期间真实厂商进程数为 0。
- [x] **Step 5：在 `0db9a8e62` 保存基线。** 原始 archive 在同一固定环境完成 startup/list/native-chat 各5次，浏览器原生设置场景另有5次；[最终CLI原始记录与median/max](../../research/harness-plugin-final-footprint.json)、[浏览器对照](../../research/harness-plugin-frontend-comparison.json)保留来源与范围。fresh process 不表示 OS 冷缓存。
- [x] **Step 6：提交基线和测量工具。** 建议提交：`test: record harness extraction baseline`。

**执行证据（2026-10-23）：** 工具与隔离回归 13 项通过；原始基线见 `docs/research/harness-plugin-baseline-raw/`，功能映射见 `harness-feature-test-inventory.json`。已冻结原始源码并完成 5 次模块导入、5 次真实 ASGI 就绪和 5 次 Agent 列表请求。该阶段的模拟聊天、浏览器及发行物尚未补齐，早期 CLI 明确返回不可用。最终 A6 已用同一生命周期驱动对原始 archive 和当前源码补齐 Step 5，早期记录仅作历史，不与最终环境混算。

## 总任务 B：给插件 SDK 增加 HarnessSpec

### B1 公共契约、注册表与版本

**Files**

- Create: `src/qwenpaw/plugins/harnesses.py`
- Create: `src/qwenpaw/plugins/_harnesses.py`
- Create: `src/qwenpaw/runtime/backends/__init__.py`
- Create: `src/qwenpaw/runtime/backends/registry.py`
- Modify: `src/qwenpaw/plugins/sdk.py`、`sdk_version.py`、`compliance.py`、`registry.py`
- Modify: `src/qwenpaw/plugins/frontend/index.js`、`index.d.ts`、`package.json`
- Test: `tests/unit/plugins/test_sdk_harness_contract.py`
- Test: `tests/unit/plugins/test_sdk_harness_registration.py`
- Modify: `tests/typing/plugin_sdk_author.py`、SDK 版本/公开导出快照测试

**Interfaces**

- Consumes: 设计 §4 的所有公开 DTO/Protocol 与现有 `Registration`。
- Produces: `PluginContext.register_harness(spec: HarnessSpec) -> Registration`。
- 宿主内部 `BackendRegistry.register(owner, spec) -> Registration`、`get(backend_id)`、`descriptors()`、`unregister_owner(owner)`。owner 包含 plugin_id/generation/context identity，返回的调用对象不对作者公开。
- `descriptors()` 为纯内存/manifest 读取，不创建实例；`get()` 仅用于分发，调用时仍验证实时状态。

- [x] **Step 1：写公开契约失败测试。** `test_sdk_harness_contract.py` 验证公开导出、冻结 DTO、保留 ID/ID 格式、capability 校验、旧 1.0 插件可加载、新 1.1 插件在旧宿主明确拒绝。
- [x] **Step 2：写注册所有权失败测试。** 测试名固定为 `test_register_does_not_call_factory`、`test_duplicate_backend_names_occupant`、`test_stale_handle_cannot_remove_replacement`、`test_descriptor_matches_manifest_ids`。
- [x] **Step 3：运行红灯。** Run: `python -m pytest tests/unit/plugins/test_sdk_harness_contract.py tests/unit/plugins/test_sdk_harness_registration.py -q`；预期因新契约/注册尚未实现而 FAIL。
- [x] **Step 4：实现 DTO 和公开 Protocol。** 沿设计 §4 的字段和方法，在 `plugins/harnesses.py` 直接定义 HarnessHistoryItem/HarnessHistoryKind；不新建 history 包，不返回内部 Workspace/AgentRequest/厂商客户端；秘密值默认脱敏。
- [x] **Step 5：实现轻量注册和 SDK 入口。** `_harnesses.register(context, spec)` 对接账本，工厂只保存不调用；声明 metadata 不能成为可调用资格。
- [x] **Step 6：更新版本与白名单。** SDK 1.1.0、`harnesses` capability、新导出 since；同步前端版本和打包声明，不更改旧导出 since。
- [x] **Step 7：验证并提交。** 重跑 Step 3，另跑 `python -m pytest tests/unit/plugins/test_sdk_compliance_contract.py tests/unit/plugins/test_sdk_entry_contract.py -q`；预期全 PASS。建议提交：`feat(sdk): add HarnessSpec and owned backend registration`。

### B2 宿主执行、能力、历史和生命周期桥接

**Files**

- Create: `src/qwenpaw/runtime/backends/execution.py`、`streaming.py`
- Create: `src/qwenpaw/runtime/backends/session.py`（原会话桥接按需使用，不另建历史子系统）
- Create: `src/qwenpaw/plugins/_harness_capabilities.py`、`_harness_http.py`
- Modify: `src/qwenpaw/plugins/_harnesses.py`、`activity.py`、`workspace_projector.py`（仅必要接线）
- Modify: `src/qwenpaw/app/workspace/workspace.py`、`src/qwenpaw/app/chats/api.py`
- Modify: `src/qwenpaw/app/routers/agents.py`、`src/qwenpaw/app/_app.py`
- Test: `tests/unit/plugins/test_sdk_harness_bridge.py`
- Test: `tests/unit/plugins/test_sdk_harness_lifecycle.py`
- Test: `tests/unit/app/routers/test_backend_catalog.py`

**Interfaces**

- Consumes: B1 注册表和设计 §4 的 `HarnessBackend`/`HarnessArchiveBackend`。
- Produces: 内部 `BackendExecution.stream(backend_id, request, settings)`、`hydrate_session(backend_id, *, session_id, user_id, channel, settings)`、`archive(backend_id)`、`close()`；`archive()` 为异步上下文管理器，返回受管 facade，后端不可用时明确拒绝，不提供无插件 fallback。
- Workspace 增加懒属性 `backend_runtime`，原生路径不访问它；API 目录为 `GET /api/agents/backends`，置于动态 Agent 路由前，字段与状态值按设计 §5.1。
- 管理网关首个 active contribution 激活时挂载、最后一个释放时移除；沿旧 `/api/harnesses` 路径。期间旧路由只在旧内置路径有效时存在，测试应用不能同时挂两套相同 URL。

- [x] **Step 1：写假后端运行失败测试。** 覆盖正文/推理/工具流、附件、命令、清空、已物化历史与补全、错误/取消终态；断言与当前 QwenPaw AgentResponse/ChatHistory 协议一致。
- [x] **Step 2：写身份与能力失败测试。** `test_call_context_uses_host_identity`、`test_same_session_id_isolated_by_workspace_and_user`、`test_capability_snapshot_respects_channel_and_policy`；插件提交伪造身份不能改变审批归属，秘密不进入日志/目录 DTO。
- [x] **Step 3：写并发生命周期失败测试。** `test_unload_busy_during_stream`、`test_cancel_waits_for_terminal_save`、`test_failed_close_blocks_new_generation`、`test_workspace_close_only_closes_own_backend`、`test_config_rebuild_revokes_old_context`。
- [x] **Step 4：写目录/路由失败测试。** `test_catalog_does_not_create_backends`、`test_gateway_removed_after_last_owner`、`test_gateway_preserves_other_owner`、`test_matched_old_handler_cannot_bypass_generation`；保留原鉴权和 Agent 访问规则。
- [x] **Step 5：运行红灯。** Run: `python -m pytest tests/unit/plugins/test_sdk_harness_bridge.py tests/unit/plugins/test_sdk_harness_lifecycle.py tests/unit/app/routers/test_backend_catalog.py -q`。
- [x] **Step 6：实现按需桥接和受限上下文。** 将现有会话桥接接入新的后端执行模块，不新增独立历史层；旧内置路径暂保留。只在运行调用解析有效能力，管理调用传 None；所有客户端和 producer 归受管资源，整个消费流到终态保存前保持活动门禁。
- [x] **Step 7：实现注册激活、按需路由和工作区关闭。** 注册声明与 activated 分开；所有操作复查 owner；普通忙碌返回既有 plugin_busy；失败资源保留到可重试清理完成。
- [x] **Step 8：验证并提交。** 重跑 Step 5，再跑 `python -m pytest tests/unit/plugins/test_sdk_context_lifecycle.py tests/unit/plugins/test_plugin_lifecycle_unload.py tests/unit/harnesses/test_workspace_routing.py -q`；预期 PASS，原生路径未改变。建议提交：`feat(sdk): bridge harness execution and lifecycle`。

### B3 前端公开契约、作者测试与文档

**Files**

- Create: `console/src/plugins/harnesses.ts`、`harnesses.test.ts`
- Modify: `console/src/plugins/hostSdk/install.ts`、`pluginRuntimeCleanup.ts`
- Modify: `src/qwenpaw/plugins/frontend/host.d.ts`、`globals.d.ts`、`index.d.ts`
- Modify: `src/qwenpaw/plugins/testing.py`、`compliance.py`
- Create: `tests/unit/plugins/test_sdk_harness_author.py`
- Modify: `scripts/check_plugin_sdk_artifacts.py`、`scripts/check_plugin_sdk_frontend.py`
- Modify: `website/public/docs/plugins.zh.md`、`plugins.en.md`

**Interfaces**

- Produces: 设计 §5.2 的 `window.QwenPaw.harnesses.register(pluginId, extension) -> Disposable` 及 `disposeAll(pluginId)`。
- 作者测试宿主新增 `list_harnesses()`、`harness_status(backend_id, *, workspace_id)`、`run_harness(backend_id, request, *, workspace_id, session_id, user_id="test", channel="console")`；运行返回标准 ChatEvent 异步流，使用真实注册/生命周期桥接。
- 新增 `test_sdk_harness_bridge.py`/`test_sdk_harness_registration.py`/`test_sdk_harness_lifecycle.py` 到 artifact checker 的 INTERNAL 集合；公开 author/contract 测试要能被复制到仓库外执行。

- [x] **Step 1：写前端注册失败测试。** 覆盖 backendId 归属、重复注册、dispose、旧句柄、配置 props 与缺省 schema 回退；只允许所选 backend 的 SettingsComponent 出现。
- [x] **Step 2：写仓库外作者测试。** fake 第三种 Harness 使用且仅使用公开 SDK，注册后通过测试宿主运行、审批、恢复、停用和重新启用；源码合规检查不得依赖白名单外的 qwenpaw 导入。
- [x] **Step 3：运行红灯。** Run: `python -m pytest tests/unit/plugins/test_sdk_harness_author.py -q`；Run from console: `npm run test:run -- src/plugins/harnesses.test.ts`。
- [x] **Step 4：实现前端 namespace/类型和测试宿主方法。** 前端清理纳入已有 removePluginRuntime，不复制一个插件 loader；测试宿主调用生产桥接。
- [x] **Step 5：同步 SDK 说明。** 新增完整 `HarnessSpec` 作者示例、manifest、能力/方法表、受管资源/取消/秘密值约束，明确 ProviderSpec 与 HarnessSpec 的职责。
- [x] **Step 6：验证本地与外部产物。** 重跑 Step 3；构建 wheel/sdist，在仓库外新环境安装后使用 `check_plugin_sdk_artifacts.py --wheel <wheel> --sdist <sdist> --python <external-python> --source-root <repo> --output <new-output>`；前端 checker 使用 `--package <extracted-sdk> --dependencies <node_modules> --output <new-output>`。预期检查全 PASS、无 checkout/PYTHONPATH/conftest 依赖。
- [x] **Step 7：提交 SDK 完整入口。** 建议提交：`feat(sdk): expose harness author and frontend contracts`。此时 B 可以用 fake Harness 独立验收，A 尚未完成不能宣称减负。

**执行证据（2026-10-23）：** 独立源码快照构建 wheel/sdist；仓库外新环境从非 editable wheel 导入，严格作者类型、228 项作者测试、模板真实运行及从 wheel 导出的 SDK 前端 NodeNext/bundler/runtime 全通过。详见 `docs/research/harness-sdk-acceptance.json`。B 以第三种 fake Harness 独立验收；A 尚未迁出厂商代码，未宣称默认运行减负。

## 总任务 A：拆出第三方 Harness 运行集成

### A1 PawPort 增加对应 Harness 插件依赖检查

**Files**

- Modify: `src/qwenpaw/app/routers/portability_imports.py`、`src/qwenpaw/portability/import_jobs.py`
- Move: `src/qwenpaw/harnesses/codex/rollout_reader.py` → `src/qwenpaw/portability/providers/codex_rollout_reader.py`
- Modify: `src/qwenpaw/portability/models.py`、`import_conversations.py`、`providers/codex.py`、`providers/qoder_sessions.py`、`providers/__init__.py`
- Modify: `src/qwenpaw/harnesses/events.py`、`session.py`（迁移期间临时转发）
- Modify: `console/src/api/types/import.ts`、`console/src/pages/Import/index.tsx`、`console/src/pages/Import/useImportJob.ts`
- Test: `tests/unit/portability/test_harness_plugin_requirement.py`
- Move/update: `tests/unit/harnesses/test_codex_rollout_reader.py` → `tests/unit/portability/test_codex_rollout_reader.py`

**Interfaces**

- Produces: 在 `portability/providers/__init__.py` 增加内部 `require_harness_plugin(source: str) -> None`；检查实时注册表与插件状态，不满足时抛同文件的 `HarnessPluginRequiredError(RuntimeError)`，携带设计 §4.3 的结构化 detail（`code="harness_plugin_required"`），路由映射为 HTTP 409。API 和 job manager 都调用此检查，防止绕过 HTTP 或重试入口。
- 来源响应新增 `plugin_id`、`plugin_state: available|missing|disabled|failed`；不可用时显示安装/启用操作，不执行路径或 CLI 探测。
- 历史 DTO 改为公开 SDK 类型、原写入桥接使用 B2 的 `runtime/backends/session.py`。这些仅为删除旧运行包所需的路径调整，不扩展迁移架构。
- 对应插件可用后保留原来的本地/在线迁移算法；已完成任务报告、已导入聊天的读取不加此门禁。

- [x] **Step 1：写依赖门禁失败测试。** `test_missing_or_disabled_plugin_blocks_import_before_scan`、`test_explicit_source_home_cannot_bypass_plugin_requirement`、`test_multi_source_request_checks_all_plugins_before_scan`、`test_start_and_retry_recheck_plugin_state`、`test_source_listing_does_not_load_provider_or_probe_cli`；失败时断言 provider 工厂/扫描调用数为 0。
- [x] **Step 2：运行红灯。** Run: `python -m pytest tests/unit/portability/test_harness_plugin_requirement.py -q`。
- [x] **Step 3：增加检查与界面提示。** 创建/开始/重试前检查已安装且激活；缺失、禁用或失败返回 HTTP 409 和 plugin_id/state，前端提供对应安装/启用入口。多来源先完整检查，不启动部分扫描；不自动安装。
- [x] **Step 4：只调整必要导入路径。** provider 由工厂在检查后按需导入，原会话桥接在写入函数中导入；将 rollout reader 移到迁移目录并保留算法。SDK 历史 DTO 本身无厂商副作用，允许作为轻量类型导入；不建立独立 history 包或无插件降级。
- [x] **Step 5：验证并提交。** 重跑 Step 2 及 `python -m pytest tests/unit/portability tests/unit/harnesses/test_session.py tests/unit/harnesses/test_session_gap_paths.py -q`；原迁移功能测试先注册 fake 对应插件，再验证原算法。建议提交：`refactor(portability): require matching harness plugin for imports`。

### A2 迁出 Codex

**Files**

- Create: `plugins/harness/codex/{plugin.json,main.py,requirements.txt,requirements-test.txt,README.md}`
- Extract/adapt: `src/qwenpaw/harnesses/codex/{adapter,app_server,discovery,projection}.py` → 同名插件文件；内置路径暂保留到 A3 切换、A6 删除
- Create: `plugins/harness/codex/tests/test_plugin_contract.py`、`test_state_migration.py`
- Move/adapt: 当前 Codex adapter/app_server/discovery/projection 测试 → `plugins/harness/codex/tests/`
- Modify: `src/qwenpaw/portability/providers/codex.py`（接 archive facade）

**Interfaces**

- Consumes: B 的公开 HarnessSpec/上下文及历史 DTO；A1 检查通过后才允许进入该来源的迁移。
- Produces: `qwenpaw-harness-codex` 提供 `codex`，`external_history=True`；main.py 的工厂内导入 adapter，外部依赖仅在该插件环境准备。
- `CodexBackend.close()` 管理所有 runtime clients、读取任务、未完成 RPC、审批与登录；不删除用户账户或原生线程。

- [x] **Step 1：写插件加载失败测试。** 移除旧模块导入可用性，正式 loader 加载插件后仅出现 codex；未加载插件时 fake 二进制和 SDK 即使存在也不被检测；`check_plugin` 无内部宿主导入违规。
- [x] **Step 2：写兼容失败测试。** `test_resume_existing_thread_mapping`、`test_state_copy_keeps_legacy_and_existing_target`、`test_corrupt_legacy_state_is_not_replaced_with_empty`、`test_archive_preserves_external_thread_metadata`。
- [x] **Step 3：运行红灯。** Run: `python -m pytest plugins/harness/codex/tests -q`（插件测试依赖已显式安装）。
- [x] **Step 4：移动并适配厂商实现。** 替换 approvals/security/io_utils 的内部导入：审批走 call context；文件写入用公开 storage 或插件自有普通 Python I/O，保留原子写语义；投影接受公开 DTO。
- [x] **Step 5：实现状态目录兼容。** 仅插件激活后的实际打开执行原子复制；旧文件保留，新目标优先；缓存再生不移动原生 Codex 数据。
- [x] **Step 6：验证已有功能。** 文本/推理/工具流、模型/effort、图片/文件、OAuth/API key 状态、审批、compact/review/skills/status/new/clear、取消、续接、历史恢复和 archive 均有模拟引擎测试。
- [x] **Step 7：验证并提交。** 重跑 Step 3 和 B2/B3 的假 Harness 契约；建议提交：`refactor(harness): extract Codex into SDK plugin`。本步在独立测试宿主验证新插件，主应用仍走旧内置路径，不在同一应用同时激活两套实现；A3 统一切换，A6 删除旧源码，此步不宣称默认启动已减负。

### A3 迁出 Qoder 并完成通用后端分发

**Files**

- Create: `plugins/harness/qoder/{plugin.json,main.py,requirements.txt,requirements-test.txt,README.md}`
- Extract/adapt: `src/qwenpaw/harnesses/qoder/{adapter,discovery,event_mapper,projection}.py` → 同名插件文件；本步切换后旧源码待 A6 删除
- Move/adapt: 当前 Qoder 测试 → `plugins/harness/qoder/tests/`
- Modify: `src/qwenpaw/app/workspace/workspace.py`、`src/qwenpaw/app/routers/agents.py`、`src/qwenpaw/app/chats/api.py`
- Remove after switch: `src/qwenpaw/harnesses/registry.py` 的 PROVIDER_CATALOG/create_adapter 分支
- Test: `tests/unit/app/test_backend_dispatch.py`

**Interfaces**

- Produces: `qwenpaw-harness-qoder` 提供 `qoder`；所有非 qwenpaw 调用通过 B2 注册表，添加第三个 fake ID 无需修改 Workspace/Agent CRUD。
- Agent 列表补充 `backend_status: available|missing|disabled|failed` 与 `backend_plugin_id: str|null`；已保存未知 backend 可读取，真正运行返回 `backend_unavailable`。
- 保留 Qoder 无非交互 logout、无 provider MCP discovery 的现有能力限制；不伪造 API 成功。

- [x] **Step 1：写 Qoder/分发失败测试。** 覆盖 SDK 不存在时原生启动成功、Codex/Qoder 可独立加载、第三个 fake backend 可用、未知 backend 无原生 fallback。
- [x] **Step 2：写隔离与数据失败测试。** `test_qoder_sessions_scoped_to_workspace`、`test_qoder_policy_and_skill_projection_preserved`、`test_qoder_mapping_migration_is_idempotent`；不同用户/渠道的审批和凭据不得串用。
- [x] **Step 3：运行红灯。** Run: `python -m pytest plugins/harness/qoder/tests tests/unit/app/test_backend_dispatch.py -q`。
- [x] **Step 4：迁出 Qoder 并替换内部服务依赖。** 与 Codex 同一公开接口，不为 Qoder 额外开放 Workspace 私有属性；保留 SDK/事件/权限语义。
- [x] **Step 5：切换 Workspace、Agent CRUD 和 Chat 恢复。** 去掉 get_provider/厂商枚举；原生仍走现有 Runtime；已禁用后端的 Agent 可管理、物化历史可读，调用明确失败。
- [x] **Step 6：删除旧硬编码工厂。** 后端配置变化由通用 settings revision 管理，不在核心判断 `if provider_id in {codex,qoder}`。
- [x] **Step 7：验证并提交。** 重跑 Step 3、B2 与 A1 测试；建议提交：`refactor(harness): extract Qoder and use backend registry`。

**执行证据（2026-10-23）：** Qoder 独立环境 27 项通过；核心/SDK/PawPort 回归 749 项通过，3 个旧 Qoder 测试模块因核心环境无 SDK 跳过，其迁出版本已单独运行。新增阻塞配置读取回归 3 项通过。独立审查发现并修复 reset/rebuild 取消事务及测试隔离问题，两轮定向复审最终 SPEC/QUALITY PASS；所有适用提交 hooks 通过后形成阶段提交。A4–A6 和真实账户/平台验收仍未完成。

### A4 厂商前端、API 路由和启停装配清理

**Files**

- Modify: `console/src/pages/Settings/Agents/components/AgentBackendFields.tsx`
- Move/generalize: `HarnessModelSelector.tsx/.module.less` → `BackendModelSelector.tsx/.module.less`
- Move/generalize: `HarnessApprovalToggle.tsx/.module.less` → `BackendApprovalToggle.tsx/.module.less`
- Modify: `console/src/pages/Chat/index.tsx`、`console/src/api/modules/harness.ts`、`console/src/api/types/agents.ts`
- Modify: `console/src/pages/Agent/Skills/useSkills.ts`、`console/src/pages/Agent/MCP/useMCP.ts`、`console/src/utils/agentBackend.ts`
- Create: `plugins/harness/codex/frontend/`、`plugins/harness/qoder/frontend/` 的构建、组件、测试和插件本地文案
- Modify: `console/src/plugins/usePluginLoader.ts`、`pluginRuntimeCleanup.ts`
- Modify: `src/qwenpaw/app/routers/frontend_plugin.py`、`src/qwenpaw/plugins/_harness_http.py`、`src/qwenpaw/app/routers/__init__.py`
- Remove after migration: `src/qwenpaw/app/routers/harnesses.py`
- Test: `console/src/pages/Settings/Agents/components/AgentBackendFields.test.tsx`
- Test: `tests/integration/test_harness_plugin_http.py`

**Interfaces**

- Consumes: `/api/agents/backends`、B3 的前端 namespace 和 B2 的动态管理网关。
- Produces: 仅使用静态能力的通用选择/模型/审批控件；厂商账号和设置 UI 由对应插件注册。
- frontend_plugin 的可执行入口需 enabled+ACTIVE+activated；对仅前端的已有合法插件保留其既有激活语义，不以“没有后端”误判为不可加载。

- [x] **Step 1：写原生界面失败测试。** 无插件时只有原生可用选项和安装入口，不请求 `/harnesses/*`，不加载厂商脚本；编辑缺失后端显示状态且保留设置。
- [x] **Step 2：写单插件和热启停失败测试。** `test_only_selected_backend_settings_render`、`test_disabled_script_never_executes`、`test_failed_plugin_not_executable_from_disk_fallback`、`test_disable_disposes_harness_extensions`；对原有仅前端插件增加兼容用例。
- [x] **Step 3：写 HTTP 失败测试。** 验证不启用时网关缺席、两个插件共存、禁用其一不影响另一个、旧路径/响应功能与鉴权可用、停用后匹配中的请求无法绕过门禁。
- [x] **Step 4：实现 UI 分离与泛化。** 删除 ProviderId 联合类型和厂商数组；移动认证逻辑/文案；通用控件只认 capabilities；Skill/MCP 通过已注册能力取数。
- [x] **Step 5：实现前后端加载状态一致。** 禁用/失败不下发可执行入口，loader 双重校验；启用与停用的事件沿现有插件事件接线，不要求整页重载才能生效。
- [x] **Step 6：移除旧常驻路由。** 只保留 SDK 动态网关；`/agents/backends` 是轻量发现入口；不把 router 放回聚合 `__init__.py`。
- [x] **Step 7：验证并提交。** Run: `python -m pytest tests/integration/test_harness_plugin_http.py tests/integration/test_frontend_plugin_router.py -q`。Run from console: `npm run test:run -- src/plugins/harnesses.test.ts src/plugins/usePluginLoader.test.ts src/pages/Settings/Agents/components/AgentBackendFields.test.tsx`，再 `npm run build`。建议提交：`refactor(console): load harness contributions from plugins`。

**执行证据（2026-10-24）：** 核心设置/模型/审批由静态能力驱动，厂商界面和七种文案已迁入独立插件；两个前端实际构建通过。最终受影响前端 123 项、聊天与文案 236 项、HTTP/目录 12 项、真实本地服务 11 项通过，类型与适用 hooks 通过。认证事件补载和下载并发经两轮定向修复，独立复审 SPEC/QUALITY PASS；实际浏览器无插件表单仅显示安装入口。完整 Console 构建通过，核心产物未包含检查的厂商认证文案。A5/A6 发行物和最终对照仍未完成。

### A5 可选插件产物、依赖和桌面分发

**Files**

- Modify: `pyproject.toml`、`scripts/pack-tauri/qwenpaw.spec`、`scripts/pack/build_common.py`
- Modify: `scripts/pack/generate_plugin_metadata.py`、`.github/workflows/release.yml`、`.github/workflows/plugins-release.yml`
- Modify: `src/qwenpaw/plugins/download_catalog.py`、`website/src/pages/Downloads/types.ts`、`constants.ts`、`components/PluginsSection.tsx`（加入 harness 下载分类）
- Create: `.github/workflows/harness-plugin-tests.yml`
- Modify: `tests/unit/plugins/test_generate_plugin_metadata.py`、`tests/unit/plugins/test_download_catalog.py`
- Create: `tests/integration/test_harness_distribution.py`

**Interfaces**

- Produces: `dist/plugins/harness/<plugin-id>/<plugin-id>-<version>.zip` 与现有 metadata 格式兼容的 index；包含已构建 frontend，缺失 entry/必要产物必须失败。
- 默认 `full` 不再包含 codex/qoder extras；默认冻结包不收集其 SDK/CLI/hiddenimports/metadata。旧 extras 暂保留一周期且明确只准备依赖。
- 插件专属 CI 显式安装各自 requirements-test，core SDK 测试在无两家 SDK 的环境也运行。

- [x] **Step 1：写产物失败测试。** `test_core_wheel_has_no_vendor_runtime`、`test_minimal_build_without_vendor_sdks`、`test_harness_zip_contains_entries_and_no_other_vendor`、`test_missing_frontend_fails_pack`。
- [x] **Step 2：写安装隔离失败测试。** 无厂商依赖环境装 core 后可启动；显式装 Codex 插件后 Qoder 仍缺席；反之同样；依赖版本冲突返回现有重启要求，不修改活跃宿主包。
- [x] **Step 3：运行红灯。** Run: `python -m pytest tests/integration/test_harness_distribution.py tests/unit/plugins/test_generate_plugin_metadata.py tests/unit/plugins/test_download_catalog.py -q`。
- [x] **Step 4：修改 Python 和冻结打包。** 移除强制 get_package_paths、binary 收集及缺包 SystemExit；root test extra 移除 Qoder。修改后必须能在两家 SDK 均未安装的构建环境运行到真实构建完成。
- [x] **Step 5：打通独立插件发布。** KIND_DIRS/上传循环加入 harness；主/legacy release 构建两个前端；下载目录支持新分类。此步骤只改代码和本地产物，不实际上传或发布。
- [ ] **Step 6：验收冻结平台安装。** 在 macOS 与 Windows 最小宿主中，沿现有桌面 Python runtime 显式安装插件和平台 wheel；验证 CLI 权限、相邻资源、Qoder SDK 导入、卸载/重启门禁。Linux 验证 Python wheel 安装/运行；不以纯 Python 单测替代冻结包验收。
- [x] **Step 7：验证并提交。** 重跑 Step 3，检查 wheel/桌面/zip 具体文件清单，保存无厂商默认包与各插件依赖报告。建议提交：`build: ship harness integrations as optional plugins`。

**A5 代码检查点（2026-10-24）：** 独立产物/规范检查58项、核心SDK91项、实际ZIP插件Codex36项/Qoder27项通过，前端与网站构建、hooks通过。真实无厂商SDK的full环境完成macOS PyInstaller后端/CLI、helper Python与Node准备；实际包/PYZ未发现旧运行包和厂商SDK/CLI。代码审查发现的PyInstaller测试依赖已补齐并复审通过。Step 6仍未通过：本机冻结可执行文件即使在工具沙箱外也被SIGKILL，签名验证有效，原因仍待定位；Windows/Linux执行及真实账户验收无可用环境，不能由构建成功或模拟测试推断。保留这些缺口，继续独立的A6迁移和缺席验收。

**A5 安装器后续修复：** 真实 helper 事务复现了 pip target 计划包含宿主同版本依赖而被误判重启的问题，现仅安装经 URL/SHA256 校验的缺失产物，保留非 target 的替换保护。冻结规范递归保留宿主依赖元数据。独立真实 wheel/ZIP + staged helper 的 Codex、Qoder 事务与 CLI 版本验证通过；该验证显式模拟了桌面路由，不等同于冻结可执行宿主验收。最终已在修复后重建并审计：10,437文件、每个PYZ32,587模块、六项必需元数据和1746个Console文件齐全，厂商/旧包根为0；实际隔离CLI仍SIGKILL -9无输出，各Mach-O签名验证有效，不推断OS原因或改security。Step 6运行验收继续未完成。

### A6 旧用户迁移、旧包删除和最终验收

**Files**

- Create: `scripts/pack/migrate_legacy_harnesses.py`
- Create: `tests/integration/test_harness_upgrade.py`、`tests/integration/test_harness_absent.py`
- Remove: `src/qwenpaw/harnesses/` 下全部已迁移运行实现及临时兼容转发
- Move remaining tests: 通用执行/历史 → 对应 core 目录；厂商 → 各插件 tests；依赖/缺席 → distribution/absent 测试
- Modify: SDK/插件 README、`website/public/docs/plugins.zh.md`、`plugins.en.md`、相关安装说明
- Create: `docs/research/harness-plugin-acceptance.md`

**Interfaces**

- 迁移命令：`python scripts/pack/migrate_legacy_harnesses.py --working-dir <dir> --plugin-dir <verified-local-packages> --dry-run`，确认离线依赖已准备后使用 `--apply`。
- 输出 JSON 含需要的 plugin IDs、已有启停状态、可用包/版本、缺失依赖和执行结果；没有第三方 Agent 时计划为空。apply 走正式安装事务，不能通过复制目录绕开版本/依赖检查。
- 运维步骤先 dry-run/准备产物，再 apply，完成后启动新宿主；缺包场景保留数据并提供明确安装动作。本轮不改自动升级器协议；已安装 wheel/冻结 CLI 使用预先设置 `QWENPAW_WORKING_DIR` 的 `qwenpaw plugin migrate-legacy-harnesses`，与脚本共用一个实现。

- [x] **Step 1：写升级失败测试。** `test_native_only_upgrade_installs_nothing`、`test_upgrade_prepares_only_used_backend`、`test_upgrade_respects_explicit_disable`、`test_upgrade_missing_bundle_preserves_agents`、`test_upgrade_apply_is_idempotent`。
- [x] **Step 2：写数据/缺席失败测试。** `test_saved_agent_manageable_without_plugin`、`test_materialized_history_readable_without_plugin`、`test_reenable_resumes_original_provider_session`、`test_uninstall_keeps_account_and_data`；禁止静默 fallback。
- [x] **Step 3：写冷启动硬门禁。** 在新进程中禁止导入 `qwenpaw.harnesses`、两家厂商包和插件入口；拦截 binary 扫描/厂商进程启动，完成原生启动/Agent 列表/模拟聊天。禁用插件的 manifest 在场时也要通过；CI 安装了厂商 SDK 也不能掩盖这个门禁。
- [x] **Step 4：运行红灯。** Run: `python -m pytest tests/integration/test_harness_upgrade.py tests/integration/test_harness_absent.py -q`。
- [x] **Step 5：实现升级工具并删除旧包。** 只保留安装器迁移表和 PawPort 中属于迁移的厂商识别；生产运行注册表/Workspace/核心 UI 不得残留内置厂商工厂或 fallback。
- [ ] **Step 6：运行完整功能 checklist。** 使用下表逐项链接测试或真实验收记录；未经验证的项目保持未完成。
- [x] **Step 7：重跑减负对照。** 用 P0 工具和相同原生场景，对比无插件/禁用/仅 Codex/仅 Qoder；保存原始记录、文件清单、环境和中位数，不把运行优化混入结果。
- [ ] **Step 8：验证并提交。** 重跑 Step 4、两个插件测试、B 契约、PawPort、前端构建、外部 wheel 作者验收和 A5 平台验收。建议提交：`refactor(harness): finish migration and verify optional footprint`。

**A6 当前证据（2026-10-24）：** 升级/缺席先记录独立 RED，再通过真实离线 ZIP 安装、幂等、显式禁用、缺包/缺依赖保留数据；最终依赖门禁为 check-only。missing-owner Agent 可读/改名/删除但运行明确拒绝；两家真实插件在无真实厂商进程的正式 disable→enable 生命周期中均续接同一原生 session，卸载保留 Agent/account 字节。21 个旧运行文件及兼容别名已物理移除。Step 1 的缺包保护折入 `test_upgrade_prepares_only_used_backend`，Step 2 的具体测试归属见[验收矩阵](../../research/harness-plugin-acceptance.md)。

[最终 SDK receipt](../../research/harness-sdk-final-acceptance.json)验证最终重产物的全新外部 wheel：strict mypy、228 作者测试（171s）、导出模板真实运行以及 wheel 前端 NodeNext/bundler/runtime 全通过；两个 unknown-marker 警告明确记录。源码复审与定向修复已通过质量审查。Step 6/8 保持未勾选，因为真实账户与冻结/其他平台运行仍未验收；更新产物文件审计已通过。Step 7 已完成15组×5次，共75个fresh-process样本；中断旧批次不计入。原始记录、环境、source origin/hash及median/max见[最终CLI对照](../../research/harness-plugin-final-footprint.json)。

**最终定向回归：** vendor-free核心140通过（2项条件性apply另在双SDK组执行），双SDK显式迁移/缺席5通过，实际ZIP首轮Codex58/Qoder28通过；本地协议补齐后clean release-tree完整套件Codex66/Qoder36、shared bridge11及两进程restart每家1通过，HTTP7、ACP22、三种目录变体及每家正式ZIP安装各1通过。完整命令、包SHA与限制见[验收记录](../../research/harness-plugin-acceptance.md)。最终五次浏览器after已重新采集：body bytes中位数/最大值11,547,780→11,529,598，差18,182B（约17.8KiB）；不含API/headers，不表示wire、延迟或RSS节省。

**最终采样：** 75样本里25次native chat均实际保存user/assistant历史，原16个old-runtime模块降为0；absent/disabled厂商entry为0，单插件仅执行自己的main声明。所有current state厂商SDK/adapter/probe/process为0。无插件startup ready中位数5512.7ms对5682.5ms，list/chat无统一耗时优势；RSS仅是本机live snapshot。独立完整default-core无SDK环境的[native-chat验收](../../research/harness-plugin-final-vendor-free-native.json)也通过，未混入双SDK同环境数值。Step 6/8仍等待真实账户与平台；最小无QwenPaw hello也复现SIGKILL，仅证明症状不限本程序，不推断根因。

**真实验收增补（2026-10-26）：** 用户提供的 9099 普通 Python 服务已验证两家插件继承现有登录、模型列表、真实文本/图片/文件、原生工具流、取消后继续对话与原生会话 ID 保持；Qoder 另通过真实工具审批。独立临时 ASGI 服务验证两家正式 ZIP 安装、停用/启用、卸载/重装和宿主进程重启后的真实会话续接，未重启或干扰用户的 9099。

真实取消暴露的 Qoder 旧响应队列复用问题已修复（`4d7c19901`）；中断后关闭客户端并保留原生会话映射，独立干净插件树 38 测试及 9099 重测通过。停用后公开接口误报空 completed 的宿主问题已修复（`f4c2240ce`）；独立 SSE/Task 回归、相关 92 测试、新 wheel 的两条回归及真实独立 ASGI 停用场景通过。两个修复均经独立源码复核及实际提交 hooks。新增 Qoder ZIP 仅更新在用户指定目录；两个 ZIP 的 22 个载荷均与当前源码逐字节一致。

本次新 wheel/sdist 已构建，1,544 个输入文件与当前源码匹配，相对 10 月 24 日核心仅 ConsoleChannel 改变。前述 10 月 24 日性能、完整 SDK 作者测试和冻结包记录保留其快照归属，不当作新包的完整运行证明。详细操作、当前 ZIP/wheel SHA 和剩余步骤见本地[真实验收记录](../../research/harness-plugin-live-acceptance-20261026.md)；按用户要求，验收报告与原始数据留在本地，不纳入 Git。Codex 真实单次命令审批已分别拒绝/允许，文件副作用、历史与原生 ID 均核对通过，现有只读权限和持久规则未改变。

**9099 重启后验收：** 用户重启后，新进程上的两家独立 QA 智能体均通过正式停用 → SSE/Task 明确 `failed/backend_unavailable` → 重新启用 → 同一原生 ID 真实续接；Agent、原成功历史与映射字节保留，最终两家均 available。原临时目录的旧 QA 配置/映射已不在，因此此项不声称旧 QA 会话跨该次用户重启续接，也不将其消失原因归给插件。当前制品和新 QA 数据已存入仓库忽略目录；重建 wheel 的两条仓库外回归通过，529 个已导入 qwenpaw 模块均来自实际 wheel。桌面实际 Python 3.13.14 的最小冻结控制现已启动通过，完整冻结宿主仍在独立环境验收；新登录各入口和其他平台也仍待验，A6 Step 6/8 保持未勾选。


**macOS 完整冻结验收进展：** 原规范在无厂商 SDK 的独立环境完整构建，真实 CLI、后端启动/健康检查/关闭通过，1,746 个 Console 文件逐字节一致。两家正式 ZIP 安装仅增加匹配 SDK/CLI，helper 本身仍无厂商 SDK。Qoder 真实回复、停启后明确不可用、配置/历史/映射保留及宿主进程重启后同原生 ID 续接均通过。Codex 安装/CLI/现有认证通过，生成失败日志明确包含 `invalid peer certificate: Other > OtherError > UnsupportedCertVersion`；普通同 CLI 对照曾通过，现有 CA 配置对照未解决冻结失败，未改产品代码或降低证书校验。现有 CA 文件均为 v3，独立 Python 验证握手另报 self-signed，不能据此确定原生失败链来源。Codex 冻结生成/生命周期、新登录与 Windows/Linux 仍待真实可用环境验收，A5/A6 总步骤保持未勾选。详见本地[当前验收记录](../../research/harness-plugin-live-acceptance-20261026.md)。

## 整体功能 checklist

本表的 `[x]` 仅表示所链接的**协议/源码集成测试**满足该行要求，不代替真实账户或平台专行。两家独立勾选；共享宿主测试只证明共同桥接/归属边界。含未测子项的行保留 `[ ]`，同时列明已完成部分及缺口，不把部分证据当作整行通过。

| 能力 | Codex | Qoder | 验证要求 |
| --- | --- | --- | --- |
| 插件安装/启用/禁用/重启后状态 | [x] [正式启停](../../../plugins/harness/codex/tests/test_plugin_contract.py#L96)、[两进程重启](../../../tests/integration/test_harness_process_restart.py#L108)（Codex选定环境1通过） | [x] [正式启停](../../../plugins/harness/qoder/tests/test_plugin_contract.py#L56)、[两进程重启](../../../tests/integration/test_harness_process_restart.py#L108)（Qoder选定环境1通过） | 各自两个不同Python进程，安装/禁用持久化→installed discovery→启用续接；fake厂商客户端，不代替冻结宿主 |
| CLI 自动发现与手动路径 | [x] [test_reads_official_sdk_bundled_cli_path](../../../plugins/harness/codex/tests/test_discovery.py#L26)、[test_resolves_explicit_binary](../../../plugins/harness/codex/tests/test_discovery.py#L41) | [x] [test_prefers_python_sdk_bundled_cli](../../../plugins/harness/qoder/tests/test_discovery.py#L54)、[test_prefers_explicit_qoder_binary](../../../plugins/harness/qoder/tests/test_discovery.py#L23) | 文件/平台分支为受控发现测试，不表示 Windows/Linux 实机验收 |
| 真实账户与登录 | [ ] [test_status_login_and_models_use_app_server](../../../plugins/harness/codex/tests/test_backend_behavior.py#L112) 已测协议；真实 OAuth/API key 未运行 | [ ] [test_status_token_and_read_only_vendor_skills](../../../plugins/harness/qoder/tests/test_backend_behavior.py#L79)及登录清理已测；真实 browser/PAT 未运行 | 真实账户专行保持未完成 |
| 模型与推理强度 | [x] [test_status_login_and_models_use_app_server](../../../plugins/harness/codex/tests/test_backend_behavior.py#L112)、[test_turn_preserves_settings_and_attachments](../../../plugins/harness/codex/tests/test_backend_behavior.py#L280) | [x] [test_models_commands_and_explicit_unsupported_operations](../../../plugins/harness/qoder/tests/test_backend_behavior.py#L52)、[test_qoder_projects_scoped_skills_mcp_and_attachments](../../../plugins/harness/qoder/tests/test_backend_behavior.py#L127) | 模型/default/effort 协议；[共同选择器持久化请求](../../../console/src/pages/Chat/components/BackendModelSelector.test.tsx#L180) |
| 文本、推理和工具流 | [x] [test_notification_conversion_keeps_reasoning_and_tool_outcome](../../../plugins/harness/codex/tests/test_backend_behavior.py#L30)、[test_failed_codex_turn_reaches_public_failed_stream](../../../plugins/harness/codex/tests/test_plugin_contract.py#L159)、[test_cancelling_turn_interrupts_native_turn](../../../plugins/harness/codex/tests/test_backend_behavior.py#L605) | [x] [test_maps_incremental_text_and_reasoning_without_duplicates](../../../plugins/harness/qoder/tests/test_event_mapper.py#L28)、[test_maps_terminal_results](../../../plugins/harness/qoder/tests/test_event_mapper.py#L98)、[test_live_approval_is_scoped_to_call_and_cancelled_with_turn](../../../plugins/harness/qoder/tests/test_backend_behavior.py#L355) | 开始/增量/结束、失败和取消；Codex失败RPC经真实adapter到公开failed事件 |
| 图片/文件等既有附件能力 | [x] [test_turn_preserves_settings_and_attachments](../../../plugins/harness/codex/tests/test_backend_behavior.py#L280) | [x] [test_qoder_projects_scoped_skills_mcp_and_attachments](../../../plugins/harness/qoder/tests/test_backend_behavior.py#L127) | 类型/路径/厂商格式；Qoder 另测附件单独输入，非真实模型识图质量验收 |
| 宿主审批与厂商权限预设 | [x] [test_codex_permission_presets_reach_vendor_turn](../../../plugins/harness/codex/tests/test_backend_behavior.py#L345)、[test_approval_uses_public_call_context](../../../plugins/harness/codex/tests/test_backend_behavior.py#L526) | [x] [test_qoder_permission_presets_reach_vendor_client](../../../plugins/harness/qoder/tests/test_backend_behavior.py#L497)、[test_qoder_permission_decisions_use_live_public_call](../../../plugins/harness/qoder/tests/test_backend_behavior.py#L439) | 各自权限预设、approved/rejected/cancelled/timeout厂商响应类型；[共同宿主身份与四种结果](../../../tests/unit/plugins/test_sdk_harness_bridge.py#L510) |
| 厂商原生 Skill/工具/MCP 能力 | [x] [test_provider_discovery_keeps_read_only_skill_and_mcp_metadata](../../../plugins/harness/codex/tests/test_backend_behavior.py#L206) | [x] [test_status_token_and_read_only_vendor_skills](../../../plugins/harness/qoder/tests/test_backend_behavior.py#L79)、[test_models_commands_and_explicit_unsupported_operations](../../../plugins/harness/qoder/tests/test_backend_behavior.py#L52) | 按各自 capability；Qoder 原生 MCP discovery 明确 unsupported |
| QwenPaw Skill/MCP 投影 | [x] [test_turn_preserves_settings_and_attachments](../../../plugins/harness/codex/tests/test_backend_behavior.py#L280)、[projection tests](../../../plugins/harness/codex/tests/test_projection.py) | [x] [test_qoder_projects_scoped_skills_mcp_and_attachments](../../../plugins/harness/qoder/tests/test_backend_behavior.py#L127) | 工作区/渠道/工具过滤、秘密/revision 的共同宿主证据：[test_harness_capabilities.py](../../../tests/unit/plugins/test_harness_capabilities.py)、[fresh capability context](../../../tests/unit/plugins/test_sdk_harness_bridge.py#L136) |
| 命令与 new/clear | [x] [test_commands_and_session_reset_use_the_same_native_thread](../../../plugins/harness/codex/tests/test_backend_behavior.py#L455) | [x] [test_models_commands_and_explicit_unsupported_operations](../../../plugins/harness/qoder/tests/test_backend_behavior.py#L52)、[test_history_reset_and_capability_change_resume_the_same_identity](../../../plugins/harness/qoder/tests/test_backend_behavior.py#L226) | [共同公开桥接](../../../tests/unit/plugins/test_sdk_harness_bridge.py#L20)分别参数化`/new`、`/clear`，断言reset和保存历史；各自adapter验证native reset |
| 原生会话续接与旧映射升级 | [x] [test_resume_existing_thread_mapping](../../../plugins/harness/codex/tests/test_state_migration.py#L38)、[两进程续接](../../../tests/integration/test_harness_process_restart.py#L108)（Codex） | [x] [test_qoder_mapping_migration_is_idempotent](../../../plugins/harness/qoder/tests/test_state_migration.py#L119)、[两进程续接](../../../tests/integration/test_harness_process_restart.py#L108)（Qoder） | 旧文件保护、映射升级与重启后原生ID续接；无真实厂商进程/账户 |
| 已保存历史与未物化历史恢复 | [x] [test_archive_preserves_external_thread_metadata](../../../plugins/harness/codex/tests/test_state_migration.py#L198) | [x] [test_history_reset_and_capability_change_resume_the_same_identity](../../../plugins/harness/qoder/tests/test_backend_behavior.py#L226) | [materialized history 无插件可读](../../../tests/unit/plugins/test_sdk_harness_bridge.py#L418)，未物化经各自公开 history/reader 协议 |
| 多工作区/用户/渠道隔离 | [x] [test_resume_existing_thread_mapping](../../../plugins/harness/codex/tests/test_state_migration.py#L38)、[test_approval_uses_public_call_context](../../../plugins/harness/codex/tests/test_backend_behavior.py#L526) | [x] [test_qoder_sessions_scoped_to_workspace_and_identity](../../../plugins/harness/qoder/tests/test_state_migration.py#L53)、[test_qoder_permission_decisions_use_live_public_call](../../../plugins/harness/qoder/tests/test_backend_behavior.py#L439) | [共同并发用例](../../../tests/unit/plugins/test_sdk_harness_bridge.py#L297)同时保持同session-ID双身份turn，检查独立MCP秘密/审批、拒绝错误actor；厂商用例另证公开结果转换 |
| 禁用/重载/卸载并发 | [x] [test_force_unload_interrupts_live_codex_turn](../../../plugins/harness/codex/tests/test_plugin_contract.py#L208)、[turn cancellation](../../../plugins/harness/codex/tests/test_backend_behavior.py#L605) | [x] [test_force_unload_interrupts_live_qoder_turn](../../../plugins/harness/qoder/tests/test_plugin_contract.py#L107)、[turn cancellation](../../../plugins/harness/qoder/tests/test_backend_behavior.py#L355) | 活动真实插件turn经`interrupt_tasks=True`卸载，确认停止/断连和目录不可用；[busy stream](../../../tests/unit/plugins/test_sdk_harness_lifecycle.py#L24)、[failed close](../../../tests/unit/plugins/test_sdk_harness_lifecycle.py#L123)保留独立边界 |
| PawPort 插件依赖与原迁移能力 | [x] [test_missing_or_disabled_plugin_blocks_import_before_scan](../../../tests/unit/portability/test_harness_plugin_requirement.py#L76)、[test_codex_provider_reuses_runtime_and_normalizes_inventory](../../../tests/unit/portability/test_migration_providers.py#L104) | [x] [相同前置门禁](../../../tests/unit/portability/test_harness_plugin_requirement.py#L76)、[test_qoder_archive_task_ids_are_mapped_to_execution_sessions](../../../tests/unit/portability/test_qoder_sessions.py#L134)、[test_qoder_custom_skill_plugin_uses_native_adapter](../../../tests/unit/portability/test_importer.py#L1634) | 本地/受控在线 archive、导入与缺失提示；无插件降级不存在，非 live-account 迁移验收 |
| macOS/Windows 最小冻结宿主安装 | [ ] [当前真实验收](../../research/harness-plugin-live-acceptance-20261026.md)：macOS 正式安装/匹配 SDK 和 CLI/认证通过；真实 turn 连接失败待定位，Windows 待验 | [ ] macOS 正式安装、真实回复、停启及宿主进程重启同原生 ID 续接通过；Windows/Linux 仍无实际运行证据 | 原规范在无厂商 SDK 环境真实构建，CLI/health/shutdown 通过。Codex 普通进程同 CLI 对照成功，冻结复测仍连接失败，未判根因；平台整体仍未完成 |

本地协议补齐的完整命令与限制见[最终协议记录](../../research/harness-plugin-protocol-checklist.md)：clean release-tree Codex66、Qoder36，shared bridge11，两进程restart每家1通过。独立协议复审PASS，无Critical/Important问题。此表真实账户及冻结平台专行仍未完成，因此A6 Step 6/8不勾选。

## 最终减负 checklist

- [x] 无插件 core 环境可完成启动、原生 Agent CRUD 和模拟聊天。证据：[缺席硬门禁](../../../tests/integration/test_harness_absent.py)、[Agent 管理](../../../tests/unit/app/test_backend_dispatch.py)与实际工具 native-chat-persisted smoke。
- [x] 无插件/已禁用新进程：厂商 adapter/SDK/插件入口导入数为 0。证据：缺席子进程在无 SDK/双 SDK 环境通过，禁用入口另有独立执行标记断言。
- [x] 同场景 CLI 探测和厂商子进程数为 0。证据：[工具缺席/禁用/单插件目录回归](../../../tests/unit/harnesses/test_footprint_probe.py)；最终75样本各current state的厂商SDK/adapter/probe/process均为0，详见Step 7 receipt。
- [x] 无有效贡献时未挂载第三方管理网关，核心只提供轻量目录和不可用状态。证据：[实际 HTTP](../../../tests/integration/test_harness_plugin_http.py)、[目录](../../../tests/unit/app/routers/test_backend_catalog.py)。
- [x] 核心前端不静态打包厂商配置/认证组件和厂商文案资源。证据：A4 构建审计、[五次实际浏览器场景](../../research/harness-plugin-frontend-comparison.json)，[最终冻结包清单](../../research/harness-plugin-final-frozen-inventory.json)中的1746个Console文件与最终Console构建逐字节相同；不是与pre-final A4资产相同。
- [x] 禁用插件不请求/执行其前端入口，启停后无遗留组件贡献。证据：[实际 Provider/loader](../../../console/src/plugins/usePluginLoader.test.ts)、[Harness 前端归属](../../../console/src/plugins/harnesses.test.ts)。
- [x] core wheel 与最小桌面包不包含厂商运行实现/SDK/CLI；仅指文件清单，不代表运行验收。证据：[最终 wheel/sdist receipt](../../research/harness-sdk-final-acceptance.json)、[最终冻结清单](../../research/harness-plugin-final-frozen-inventory.json)。实际冻结CLI仍[未通过运行验收](../../research/harness-plugin-final-frozen-runtime.json)。
- [x] 仅安装 Codex 时无 Qoder 依赖，反向同样成立。证据：[正式 ZIP 安装隔离](../../../tests/integration/test_harness_install_isolation.py)及两家独立 SDK 环境的插件契约。
- [x] 已用过再停用时受管进程/任务/连接结束；不把 RSS 全释放作为承诺。证据：两家插件 cleanup/取消及正式启停协议测试；真实账户进程仍未验收。
- [x] 相同基线场景有至少5次测量、中位数、最大值、原始记录与环境。证据：[最终15组×5对照](../../research/harness-plugin-final-footprint.json)与[数值表/限制](../../research/harness-plugin-acceptance.md#native-absence-and-footprint-evidence)。无插件RSS中位数本机降低3.55–4.66MiB；不表示普遍加速，无OS冷cache保证。

## 单 worker I/O 验收 checklist

- [x] 工厂声明与初始化不在事件循环执行状态文件读写或扫描；异步客户端和锁在原循环创建。 证据：[注册/工厂契约](../../../tests/unit/plugins/test_sdk_harness_registration.py)及两家 state/contract 测试。
- [x] Codex/Qoder binary 发现、metadata 查找在明确异步调用边界运行，无顶层扫描。 证据：两家 discovery/contract 测试与 SDK-preinstalled 缺席/目录门禁。
- [x] 会话映射读写使用异步 helper；原子读改写受同一锁保护，取消后真实写入结束再释放。 证据：两家 state_migration 测试（含 Qoder 重复取消 reset/rebuild）。
- [x] Skill/MCP 文件枚举、内容读取/哈希和投影复制采用有界 I/O helper；不把 Driver/凭据服务或整个 resolver 移到线程。 证据：[能力解析](../../../tests/unit/plugins/test_harness_capabilities.py)、两家投影/行为测试与代码审查。
- [x] 管理目录、Agent CRUD、PawPort 前置检查没有新增同步磁盘扫描；确需读取时使用异步入口。 证据：[PawPort 前置门禁](../../../tests/unit/portability/test_harness_plugin_requirement.py)、异步配置快照回归与 A3/A6 I/O 审查。
- [x] 所选 I/O 操作被有控制地阻塞时，事件循环 heartbeat/无关 API 仍能推进；用事件协调的少量回归测试证明，不使用不稳定耗时阈值。 证据：公共 bridge 能力读取及两家 state 中的受控阻塞/重复取消用例。

## 完成定义与交付物

只有 B 的仓库外作者验收、A 的功能矩阵与缺席门禁、发行物清单、升级场景及平台验收都有结果，两个总任务才完成。若平台构建或真实登录条件尚未具备，明确列为未验收项目，不能用模拟测试宣布完整交付。

最终交付：SDK 1.1 文档和示例、两个可独立安装的插件 zip、核心最小发行物、迁移工具与说明、功能/生命周期测试、减负对照报告。执行中每个提交更新本计划 checklist，实际发布仍按仓库发布流程单独操作。
