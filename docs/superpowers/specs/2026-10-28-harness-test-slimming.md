# Harness 测试精简方案

状态：已按本文完成测试精简；下方保留取舍依据和原文件清单，最终验证记录见文末。

比较基线：当前分支 `refactor/plugin_harness` 与已合并的本地主分支 `main`。只精简 Harness 相关测试，不清理其他功能的主分支测试。

## 最终结构

保留四个专用测试文件，每个文件包含数个独立的核心场景，不写一个包揽所有行为的长测试，也不把旧文件机械拼接。

| 方向  | 最终文件                                              | 主要职责                                              |
| ----- | ----------------------------------------------------- | ----------------------------------------------------- |
| Codex | `plugins/harness/codex/tests/test_codex_harness.py`   | 真实适配器对 Codex 协议的基本调用、能力和会话行为     |
| Qoder | `plugins/harness/qoder/tests/test_qoder_harness.py`   | 真实适配器对 Qoder SDK 的基本调用、能力和会话行为     |
| SDK   | `tests/unit/plugins/test_sdk_harness.py`              | 开发者能通过公开 HarnessSpec 接口编写、注册和调用插件 |
| 宿主  | `tests/unit/runtime/backends/test_harness_runtime.py` | QwenPaw 对插件的管理、聊天调度、隔离及异步运行        |

两个插件使用不同测试文件名，避免同时收集时出现 pytest 同名模块冲突。

重点套件目前约 9400 行，包含旧测试迁移及前端专用测试，不代表全部是本分支新增代码。四个最终文件目标合计约 1200–1600 行，含 fake 和 fixture；这是规模预算，不通过挤压排版或把代码搬进 helper、conftest、YAML 来达标。插件文件各约 350–400 行、SDK 约 200–250 行、宿主约 400–550 行，实施时优先删掉重复场景。

核心断言优先于行数预算；确有必要时允许略超预算。精简完成前，还必须检查以下三条，不能只看到四个文件通过就认为覆盖完整：

- **真实插件串联**：每个插件至少一次使用其实际 ZIP、manifest、入口和注册逻辑，完成安装/激活到宿主调用；只在第三方传输、进程和账户边界使用替身。不能用“适配器单测通过 + 最小假插件宿主测试通过”代替这条链路。包构建复用 CI 已有步骤，不在每个测试里重复构建。
- **实例替换边界**：宿主保留一次禁用/重新启用或重载后的代表验证：旧实例/旧调用上下文失效，新实例正常工作；不保留所有时序排列。
- **前端真实请求**：已有 Console 测试保留一组参数化的真实 Codex/Qoder 设置组件冒烟，检查状态/登录请求路径、必要设置传递。后端账户测试和前端构建不能代替此项；轮询和卸载窗口的专项回归仍删除。

这三条分别收进插件、宿主及已有 Console 测试，不增加第五个专用测试方向。统计缩减时，也计入已有通用文件里的新增行数，防止只把体积搬到别处。

## 四个方向分别保留什么

### Codex / Qoder：每个插件六组核心场景

1. **发现、账户、模型**：配置的可执行文件或默认 SDK 路径可使用；缺少可执行文件能明确返回不可用；登录/账户状态与模型列表可读取。
2. **一轮完整调用**：模型、审批设置、附件能传给第三方；文本、工具消息和完成/失败事件能转成宿主理解的结果。使用代表性的协议序列，不穷举字段组合。
3. **Skills / MCP**：保留一个 Skill、一个 MCP 的典型发现与投影；验证作用域和凭据处理的必要断言，不测试每一种配置指纹变化。
4. **会话 / 历史**：新实例恢复同一原生会话 ID、读取历史、清空会话；身份不串用。各保留一次旧映射恢复且旧文件不被破坏，覆盖现有升级兼容承诺。
5. **审批**：允许与拒绝能生效。Codex 保留等待审批时其他 RPC 仍可完成；Qoder 验证审批归属于当前调用。删除审批结果的重复枚举。
6. **取消 / 关闭**：取消后可以继续下一轮，旧结果不会进入新一轮，关闭能释放客户端。删除重复取消、各种关闭失败和管道积压的专门回归。

每组可用一两个短测试或少量参数化实现。只替换第三方传输/进程和账户边界，实际插件注册及适配器代码应参与测试，不能直接伪造最终聊天结果。自身插件包保留一次安装/激活串联；通用停用、卸载、忙碌和代次管理不在两个插件中重复测试。

### SDK：四组核心场景

1. 关键公开类型可导入、请求/上下文的基本不可变契约成立；删除完整 DTO 字段清单、逐方法签名和 enum 值穷举。
2. 用公开 `HarnessSpec`、公开上下文和 `PluginTestHost` 编写一个最小插件，完成注册、状态查询和一次调用；列表查询不提前创建后端。
3. 重复 ID 和不兼容的 SDK/能力声明会被拒绝；旧版本普通插件的兼容性沿用已有通用 SDK 测试，不重复整套矩阵。
4. 公开调用上下文中的审批与凭据可以正常使用，凭据不会通过普通展示泄漏。

此文件必须可由 `scripts/check_plugin_sdk_artifacts.py` 复制到仓库外、基于安装后的 wheel 独立运行，不依赖宿主私有模块或其他内部测试文件。

### 宿主：七组核心场景

1. **不用插件的用户正常运行**：隔离子进程导入实际 app，完成 Native 聊天和历史读取；不导入第三方 SDK、不探测 CLI、不启动第三方进程。使用本地模型替身，无需真实模型账户。
2. **管理可用**：目录查询懒加载，创建/修改智能体、停用/启用和卸载可用；一个插件停用不影响另一个，卸载保留已有智能体及用户数据。禁用/重新启用或重载后，旧实例与调用上下文失效，新实例正常工作。
3. **调用与历史可用**：通过真实宿主桥接调用最小 SDK 插件，验证流式结果、附件、历史保存/恢复和清空；不再逐层重复 DTO 转换测试。
4. **正常并发与隔离**：不同审批模式和模型设置可以并发；运行中查询状态不会重建后端；调用参数互不污染，工作区/用户的会话和审批不串用。这是多会话核心能力，不能随小问题回归一起删除。
5. **失败有明确结果**：缺失/停用插件和真正的实例配置变更忙碌，能够通过实际 Console/SSE 或异步任务出口给出失败结果，不静默结束，也不自动切换 Native。
6. **取消与异步活性**：取消释放调用、正在运行时不能强行卸载；保留一个受控同步文件读取场景，验证使用 `run_sync_io()` 时事件循环仍可响应。使用事件同步，不用高精度耗时阈值。
7. **PawPort 前置条件**：缺少对应插件时明确提示安装，且拒绝前不扫描第三方目录；安装后一个代表性历史读取/导入路径可用。

宿主使用公开 SDK 注册的最小后端替身模拟 Codex/Qoder 身份，以保证 Core 测试环境不需要安装两套 vendor SDK；真实协议适配由前两个文件负责。

## 抽取核心断言后删除的文件

以下不是整文件保留。只抽取上面的代表性场景，其余细粒度回归直接删除。

### Codex → `test_codex_harness.py`

- `plugins/harness/codex/tests/test_app_server.py`
- `plugins/harness/codex/tests/test_backend_behavior.py`
- `plugins/harness/codex/tests/test_discovery.py`
- `plugins/harness/codex/tests/test_item_mapping.py`
- `plugins/harness/codex/tests/test_plugin_contract.py`
- `plugins/harness/codex/tests/test_projection.py`
- `plugins/harness/codex/tests/test_state_migration.py`
- `plugins/harness/codex/tests/conftest.py`：精简后的 fake/fixture 就近放入最终文件。

### Qoder → `test_qoder_harness.py`

- `plugins/harness/qoder/tests/test_backend_behavior.py`
- `plugins/harness/qoder/tests/test_discovery.py`
- `plugins/harness/qoder/tests/test_event_mapper.py`
- `plugins/harness/qoder/tests/test_plugin_contract.py`
- `plugins/harness/qoder/tests/test_state_migration.py`
- `plugins/harness/qoder/tests/conftest.py`：同上，不留下复杂 Transport 测试框架。

### SDK → `test_sdk_harness.py`

- `tests/unit/plugins/test_sdk_harness_author.py`：抽取公开作者用法。
- `tests/unit/plugins/test_sdk_harness_contract.py`：抽取公开类型和基本契约。
- `tests/unit/plugins/test_sdk_harness_registration.py`：抽取懒注册、重复 ID、版本门槛。
- `tests/unit/plugins/test_sdk_harness_bridge.py`：核心运行行为转入宿主总测试。
- `tests/unit/plugins/test_sdk_harness_lifecycle.py`：核心生命周期行为转入宿主总测试。
- `tests/unit/plugins/harness_bridge_fixture.py`：删除；只保留最终场景实际需要的短替身。

### 宿主 → `test_harness_runtime.py`

- `tests/unit/app/test_backend_dispatch.py`：抽取管理、调度和数据保留。
- `tests/unit/app/routers/test_backend_catalog.py`：抽取懒目录和插件互不影响；删除旧 handler/代次竞态的专项测试。
- `tests/integration/test_harness_absent.py`：压缩后保留 Native 与第三方隔离的核心验证。
- `tests/integration/test_harness_plugin_http.py`：抽取运行中状态查询和明确失败；删除路由捕获、重新启用窗口等逐项回归。
- `tests/unit/portability/test_harness_plugin_requirement.py`：抽取缺插件拒绝和不扫描；删除多源、home、start/retry 的重复排列。
- `tests/unit/plugins/test_harness_capabilities.py`：抽取 Skills/MCP 作用域代表断言。
- `tests/unit/runtime/backends/test_session_bridge.py`：抽取历史和附件保存。
- `tests/unit/runtime/backends/test_session_gap_paths.py`：抽取恢复和清空，删除空值/未知类型等分支穷举。
- `tests/integration/test_harness_process_restart.py`：取消独立重启脚本；原生会话 ID 的重建恢复放到各插件总测试。
- `tests/integration/test_harness_install_isolation.py`：删除独立文件；由 CI 分别安装一个 vendor SDK，并断言另一套未安装。

`tests/unit/harnesses/test_workspace_routing.py` 是原有宿主路由测试，保留新接口适配；本分支增加的单 worker 文件读取场景合入宿主总测试，不在这里重复保留。

## 直接取消的专项自动化

| 文件                                                   | 决定                                                                                                             |
| ------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------- |
| `tests/unit/harnesses/test_footprint_probe.py`         | 删除。它主要验证测量脚本；保留脚本供按需测量，不作为核心功能门禁。                                               |
| `tests/integration/test_harness_upgrade.py`            | 删除独立迁移测试套件。完整旧版升级流程纳入发布手工验收；自动化保留插件会话旧映射恢复和宿主数据不丢。             |
| `tests/integration/test_harness_distribution.py`       | 删除独立 pytest 文件。实际 wheel 的 vendor 缺失/依赖检查并入已有产物验收脚本；ZIP 条目检查复用已有通用打包测试。 |
| `console/tests/plugins/vendorHarnessSettings.test.tsx` | 抽取一组真实设置组件的状态/登录请求与设置传递冒烟，合入已有 Console 测试后删除；轮询与卸载竞态专项回归不迁移。   |
| `console/src/plugins/harnesses.test.ts`                | 删除专用文件。只把核心“选中插件的设置组件可使用、停用后不可用”断言合入已有控制台测试。                           |

## 已有通用测试的处理

不把下面这些文件的必要适配撤回主分支版本，否则会再次出现测试仍调用旧接口的问题；它们不是额外增加的 Harness 专用测试方向。

- **聊天和任务**：保留 `test_api_project_dirs_and_crud.py` 中的 `agent_id`、异步配置读取、`backend_runtime` 夹具，以及原有历史恢复/恢复失败/旧格式兼容验证；保留 `test_attachment_history.py` 的 SDK DTO 适配。`test_console_chat_task.py` 新增的 Harness 缺失失败场景转入宿主总测试。
- **已有配置/路由/历史解析**：保留 `test_agent_backend_config.py`、`test_workspace_routing.py` 的新接口适配，以及迁移后的 `tests/unit/portability/test_codex_rollout_reader.py`。后者验证已有历史格式解析，不再额外扩展分支回归。
- **已有生命周期**：保留 `test_plugin_failure_recovery.py` 中 `_backend_runtime.close()` 的接口适配及原有清理/重试断言。
- **PawPort**：保留 `tests/unit/portability/conftest.py` 和已有导入测试需要的真实注册夹具；前端 `Import` 测试保留主分支请求隔离用例及新字段适配，把本分支新增的缺失/停用/失败引导缩成一组代表场景。
- **控制台**：已有 `AgentBackendFields` 保留 Native/插件设置两个核心场景；`usePluginLoader` 只补一个启用可加载、停用不可加载的代表场景，删除多条登录/下载窗口竞态回归；已有模型选择、Skills、Chat 等测试保留新组件或 API 的必要适配。官方列表 ID 搜索及安装入口断言并入已有列表/创建场景，不另建测试文件。
- **插件管理**：已有 `InstalledPluginList`、`usePluginManager` 只保留一次主要启停/修复操作验证，不再重复卡片/列表视图、多个相同失败结果的排列。
- **通用 SDK / 打包**：保留已有依赖隔离、宿主桥接、打包元数据、下载目录、PyInstaller 测试和公开作者 typing 文件。Harness 分类使用少量参数/断言覆盖；`test_generate_plugin_metadata.py` 只保留一个真实 Harness ZIP 正常打包场景，删除新增的重复缺失前端场景，因为该行为已有通用测试。
- 其他修改过的 API、locale、样式检查、Chat 及 ACP 测试，只保留必要的接口/路径/契约更新，不为此次精简扩大功能测试范围。

## CI 和验收入口必须一起精简

1. `.github/workflows/harness-plugin-tests.yml` 的 Core job 改为运行最终 SDK、宿主文件及已有通用打包测试，不再引用五个旧 SDK 文件或 distribution 文件。
2. 两个 vendor job 各只运行自身的一个总文件，保留三平台矩阵、真实固定版本 SDK 安装和 `--version` 冒烟检查；Core job 继续不安装 vendor SDK。
3. `scripts/check_plugin_sdk_artifacts.py` 清理已删除文件的 `INTERNAL` 名称，继续自动收集最终 SDK 文件；在既有产物检查中保留精简的 wheel 不含 vendor 载荷/依赖断言，并验证安装后的实际 app 可在无 vendor SDK 时导入。当前 workflow 只是将此脚本列为路径过滤，**没有实际调用它**：删除 distribution 测试时，必须在现有 `core-sdk` job 中显式构建 wheel/sdist，按脚本契约准备仓库外的 wheel 安装环境并执行该脚本；不能只改脚本而没有调用。公开 SDK 作者测试在这个环境运行，既验证接口又验证产物，不新增测试框架或 job。
4. 保留 Console 生产构建和两个插件独立构建；更新删除文件的测试命令和维护文档引用。不把精简后的测试源码移到 ZIP 输出目录。
5. 真实账户登录、真实 CLI 完整对话、旧版完整升级及安装包运行仍按发布手工验收执行；单元测试通过不代表这些项目已验收。

## 后续实施顺序与完成标准

- [x] 先编写四个精简文件，只抽取上述核心断言和最小替身；由独立测试 agent 负责，不修改功能代码来迎合新测试。
- [x] 验证四个文件通过后，删除对应旧文件和无用 helper/conftest；确认剩余测试不再 import 它们。
- [x] 精简已有通用测试中本分支新增的重复场景，保留主分支原有行为断言和必要接口适配。
- [x] 更新 CI、产物验收脚本及维护文档，确认没有失效的测试路径和默认永远跳过的核心检查。
- [x] 验证 Core 环境无 vendor SDK，两个 vendor 环境互相独立；运行 SDK/宿主、两个插件总测试和受影响的通用测试。
- [x] 确认真实插件包到宿主调用、实例替换失效、前端设置实际请求三条覆盖底线均可执行，未被构建成功或最终结果的 mock 替代。
- [x] 验证 Console 生产构建、两个插件独立构建及仓库外 wheel SDK 作者验收。
- [x] 对比文件数/代码行数，复查没有通过隐藏 helper、大量参数组合或超长测试函数把复杂度挪走。

精简后的保证范围是 QwenPaw 基本运行、插件正常管理和第三方 Harness 核心能力；不承诺每个已修复的小问题都有独立回归测试。

## 实施记录（2026-10-28）

- 最终每个插件目录只保留一个测试文件，SDK 和宿主各一个；旧套件没有迁入 helper。
- 两插件分别使用实际 Codex RPC client、Qoder SDK client，只替换第三方传输/进程和账户边界；实际构建的 ZIP 均经过安装、注册与宿主调用。
- Core 测试环境没有 vendor SDK；Console 实际设置组件通过测试内静态 glob 加载，生产 TypeScript 图不追踪插件源码或插件 node_modules。
- 测试入口：Core 运行 `python -m pytest tests/unit/plugins/test_sdk_harness.py tests/unit/runtime/backends/test_harness_runtime.py -q`。两插件分别在只装自身 vendor SDK 的环境运行其最终文件；需先按插件 README 构建 ZIP。
- 生产构建在两个插件均不含 node_modules 的条件下通过，完成后已恢复本地依赖目录。
- 干净构建的 wheel/sdist 已通过仓库外公开 SDK 作者验收，实际导入路径位于外部 venv 的 site-packages。增量 build 中混入的旧 Harness 残留已被产物断言拦截；本次未修改运行功能代码。
- 行数预算为软目标；为保留真实协议传输、隔离子进程、审批/凭据并发及真实 SSE/task 出口，最终文件略超初始预算。实际行数和测试结果随最终提交说明记录，不通过 helper 或压缩排版隐藏体积。
- 本地仅运行受影响测试和构建；Windows/Linux 矩阵由已更新的 CI 执行，真实账户与桌面安装包仍保留原手工验收边界。

最终按仓库 Black 23 / 79 列及 trailing-comma 规范排版后，四个核心文件分别为 Codex 505、Qoder 520、SDK 211、宿主 794 行，共 2030 行。高于初始软预算，原因是保留实际协议客户端、独立 Native 子进程、真实 Console SSE/task 和审批/凭据隔离；没有把测试移入 helper，也没有调整运行功能来缩短测试。

验证记录：两插件各 9 项、SDK/宿主最终 20 项、其他受影响宿主通用测试、Console 149 项以及受影响产物导出/CI Node 检查均通过。Console 在无插件 node_modules 下完成生产构建，两插件独立构建通过；最终 SDK 测试在 wheel 安装后的仓库外环境运行通过。仓库提交 hooks 另作最终门禁。
