# Harness registry 状态与职责收敛方案

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. 功能代码与测试代码由不同 agent 编写；非核心测试只作为临时探针，完成验证后删除。

**Goal:** 将 Harness 声明、归属和生命周期有效性判断统一到 BackendRegistry，让目录、HTTP 操作和 PawPort 使用同一套宿主状态规则。

**Architecture:** 扩展现有 BackendDescriptor 作为脱离内部对象的状态快照；registry 同时提供实际操作前的有效注册项解析。HTTP 只格式化结果和映射错误，执行桥保留资源、实例及调用管理，厂商插件继续负责 CLI、账户和运行时检查。

**Tech Stack:** Python、dataclasses、现有插件生命周期及资源账本、FastAPI、现有 pytest 核心套件；不新增依赖。

**Spec:** 前述已确认的职责边界，以及本文件“设计边界与状态规则”。下方记录原定实施步骤及完成后的验证结果。

## 设计边界与状态规则

采用现有 registry 内集中判断的方式。仅把私有字段访问改成 getter，不能解决业务规则重复；额外引入通用状态管理器会扩大本次改动范围，因此均不采用。

宿主状态只表达登记和插件生命周期，不表达厂商是否安装、登录。沿用当前目录的 available / disabled / failed；单个查询找不到匹配声明时返回 None，PawPort 继续映射为 missing。

| 条件 | 宿主结果 | 操作行为 |
| --- | --- | --- |
| 没有对应声明或插件 | 单个查询为 None | 保持 backend_unavailable / harness_plugin_required 的现有响应 |
| 有声明，但未注册、未绑定完整上下文或尚未激活 | disabled | 拒绝执行，不创建厂商对象 |
| 当前所属插件加载或清理失败 | failed | 拒绝执行，保留失败状态供展示和重试 |
| 注册有效，所有权、代次和上下文匹配，插件已激活 | available | 允许进入现有调用准入流程 |
| 上述有效后端暂时被生命周期操作阻挡 | 不误报为 failed | 由现有活动账本返回 plugin_busy |
| CLI 缺失或账户未登录 | 不据此改变宿主状态 | 厂商返回 installed / authenticated / error，允许继续登录或修复 |

“available”表示宿主接受对这个插件后端的操作资格；具体调用仍可能因忙碌、厂商错误或参数不合法失败。普通聊天正在进行，不应因此将整个插件视为不可用。

PawPort 保留现有官方插件要求：Codex 来源要求 qwenpaw-harness-codex，Qoder 来源要求 qwenpaw-harness-qoder。其他插件注册同名后端，不能满足该前置条件。

## 全局约束

- 不改 HarnessSpec、run_turn、模型与审批参数隔离、实例复用、会话保存、可选 aclose 和历史分批转换逻辑。
- 不增加状态缓存或第二套活动账本；状态由当前内存数据即时计算。
- 快照查询不调用 factory / status / discovery，不导入厂商模块，不启动子进程，不进行文件或网络 I/O。
- registry 状态读取、所有权校验和生命周期变更保持在事件循环线程；不将这些逻辑搬到 run_sync_io 中。
- 保留已有 SDK guard、PluginActivity、ResourceScope 和取消后清理机制，registry 不重新实现它们。
- 快照不能充当执行凭证：每次执行、跨 await 后使用旧注册项及审批回调仍须重新校验。
- 不调整现有 HTTP 路径和目录 JSON 字段，不增加前端状态枚举，不修改外部插件 ZIP。
- 仅保留与核心契约有关的少量断言，不新建独立回归套件或隐藏大量测试到 helper。

## 文件与接口

| 文件 | 修改责任 |
| --- | --- |
| src/qwenpaw/runtime/backends/registry.py | 状态快照、当前有效注册项解析、归属与代次检查；保留现有注册和释放事务 |
| src/qwenpaw/plugins/registry.py | 为 BackendRegistry 注入现有 manifest 和 harness 状态的内存读取函数 |
| src/qwenpaw/plugins/_harness_http.py | 从快照生成目录；路由保存 ResourceOwner，通过 registry 校验请求归属；统一 HTTP 宿主 available 字段 |
| src/qwenpaw/portability/providers/__init__.py | 用带预期插件归属的快照决定是否准入，不再访问内部实例或生命周期字段 |
| src/qwenpaw/runtime/backends/execution.py | 用 registry 的有效注册项接口替换入口处重复判断，保留必要的运行时桥接 |
| tests/unit/runtime/backends/test_harness_runtime.py | 在现有宿主管理、忙碌和 PawPort 场景补少量核心断言 |

不新增另一套状态 DTO，扩展现有 frozen BackendDescriptor：保留 id、label、plugin_id、capabilities、registered，增加 status 和 config_fields。配置字段及含可变子项的能力数据在快照中脱离原对象，调用方修改快照内容不能影响 registry；不引入递归不可变容器框架。

registry 对调用方提供三个内部接口：

```python
descriptors() -> tuple[BackendDescriptor, ...]
describe(backend_id: str, *, plugin_id: str | None = None) -> BackendDescriptor | None
require(backend_id: str, *, owner: ResourceOwner | None = None) -> _BackendRegistration
```

- descriptors 与 describe 共用同一状态投影；describe 的 plugin_id 约束参与声明和注册项选择，不允许其他插件的同名注册提升预期插件的状态。
- require 返回当前有效项，缺失或失效时沿用 SDKError / StaleContextError；指定 owner 时，须匹配完整 ResourceOwner，而非只比较插件 ID。
- require、状态投影和注册项 assert_active 共用同一有效性校验：当前登记身份、未撤销、上下文和 guard 已绑定、上下文所有权一致、既有 guard 通过。状态投影另外把已知失败状态表达为 failed，不另写一套准入布尔判断。
- 当前 get() 只被执行桥使用，迁移到 require 后删除，不保留无消费者的重复入口。
- 快照不暴露 _BackendRegistration、PluginContext、PluginInstance、factory 或活动任务集合。执行桥使用内部注册项仍属必要桥接，不为消除下划线而增加转发层。

## Review Focus

1. 启用过程中的声明已存在但激活尚未完成：目录不得提前显示 available，挂载路由也不能错误要求“已经激活”。
2. 同一 ID 被新一代插件重新注册：旧路由、旧回调和旧清理不能操作或删除新所有者。
3. 插件清理失败，注册项仍被保留：目录和 PawPort 都应识别 failed，执行不得重新创建实例。
4. 调用正在进行或生命周期暂时阻挡新调用：保留 plugin_busy 及并发复用，不混为激活失败。
5. 没有 CLI 或尚未登录：目录读取无探测；HTTP 宿主 available 与 installed/authenticated 保持不同含义。

## Task 1：在 registry 内建立统一的状态投影

**Files:** registry.py、plugins/registry.py；核心测试使用现有宿主与 SDK 文件。

- [x] 测试 agent 先准备临时探针，覆盖未激活、有效、清理失败、旧代次及预期插件不匹配；记录当前调用方的结果和既有错误响应。
- [x] 扩展 BackendDescriptor；BackendRegistry 构造器增加可选 states 内存回调，由 PluginRegistry 传入 get_harness_states，保持原有按需创建方式。
- [x] 实现 describe/descriptors 的统一投影及 require；把完整有效性规则集中为一个校验实现，让 assert_active 复用它。
- [x] 保留 release 的顺序：忙碌检查、撤销准入、等待 runtime 关闭、最后移除声明；关闭失败时保留可重试资源。私有活动账本的必要访问留在该内部生命周期边界，不复制到查询方。
- [x] 验证无 factory、厂商导入、I/O 和子进程副作用；快照的可变子项不共享 registry 原数据。

## Task 2：迁移 HTTP、PawPort 和执行入口

**Consumes:** Task 1 三个接口；不再从业务模块遍历 _entries 或读取 _context._instance.state。

- [x] HTTP backend_catalog 只序列化 descriptors，移除局部 available/failed 推导和独立状态回退。
- [x] 网关 entries 改为 backend_id -> ResourceOwner。activate_gateway 从 context.resources.owner 记录标识，不调用 require：on_activate 回调执行时 instance.activated 尚未最终提交。
- [x] HTTP 请求使用 require(backend_id, owner=已捕获所有者)；get_agent_for_request 等 await 后继续核验同一所有者，保持未注册 404、已失效 409 和 plugin_busy 响应语义。
- [x] release_gateway 按完整所有者标识移除路由关联，确保旧代次清理不影响新代次。
- [x] PawPort 使用 describe(source, plugin_id=预期官方插件)；None 映射 missing，其余直接读取 status。拒绝必须发生在来源目录扫描和 provider 构造之前。
- [x] BackendExecution._entry 使用 require，删除重复的上下文存在判断。保留 Workspace 关闭检查，以及跨 await、创建实例和审批回调处的当前项校验。
- [x] 删除不再使用的 get() 及业务模块私有字段访问；_harnesses.py 的 SDK 注册、激活和资源账本桥接保持现有机制。

## Task 3：明确 HTTP 状态接口的 available 归属

**Files:** plugins/_harness_http.py；厂商 adapter 和公共 HarnessStatus 字段保持兼容。

- [x] POST /harnesses/{id}/status 成功返回前，用 require 对同一 owner 做最终校验。HTTP available 由这次宿主校验确定，覆盖厂商 DTO 的同名兼容字段。
- [x] installed、authenticated、account、runtime_path、runtime_source、error 仍原样来自厂商结果；不得用“未登录”改写宿主可用性。
- [x] 在接口附近记录 available 的宿主含义；不删除或更改公共 HarnessStatus 构造参数。公共 SDK 直接返回的厂商 DTO 不作为宿主准入依据。
- [x] 临时探针让厂商返回 installed=True、authenticated=True、available=False，确认 HTTP 的 available=True；同时检查缺 CLI、未登录和插件已失效的响应。

这一步解决 Qoder 未设置 DTO available 时的 HTTP 不一致，不要求改 Qoder 插件包，也不把厂商状态探测放进 registry。

## Task 4：验证并清理临时探针

- [x] 在现有宿主管理测试中核对：目录可用状态、操作结果、停用/重启/卸载及旧所有者拒绝行为一致；扩展已有场景，不新增总测试文件。
- [x] 在已有忙碌、并发模型/审批、Console 明确失败及 PawPort 场景中保留原断言；验证无插件时不扫描来源目录，安装正确插件后仍可导入。
- [x] Review Focus 的激活中间态、失败残留、快照隔离和 HTTP DTO 同名字段覆盖使用临时探针验证；完成后删除探针及其 helper，不扩充长期测试框架。
- [x] 只运行受影响核心测试：

```bash
python -m pytest -q tests/unit/plugins/test_sdk_harness.py tests/unit/runtime/backends/test_harness_runtime.py
python -m pytest -q plugins/harness/codex/tests/test_codex_harness.py plugins/harness/qoder/tests/test_qoder_harness.py
```

首条在无厂商 SDK 环境验证按需加载；第二条在独立、已准备固定版本厂商 SDK 的环境验证，不混用测试路径。工作目录、秘密目录和依赖状态目录均隔离到临时路径。

- [x] 对修改文件运行 pre-commit；对 HTTP/PawPort 做静态检查，确认不再穿透 _entries、_context._instance 或活动账本。
- [x] 独立审查：快照与操作确实共用规则，没有只把旧判断搬到两个新 helper；现有生命周期锁、租约和清理顺序保持完整。
- [x] 删除非核心探针，检查 diff；确认没有修改模型/审批隔离、会话持久化、历史批处理和外部 ZIP，再形成独立提交。

## 最终验收 checklist

- [x] 宿主可用性规则只有一个实现来源，目录和 PawPort 不再自行解释内部生命周期。
- [x] 状态查询纯内存、无客户端构造及 I/O；registry 仍按需创建。
- [x] 快照不暴露可修改的运行时句柄，不改变调用准入或持有活动租约。
- [x] 实际调用仍重新校验完整归属和代次；旧句柄及旧路由不得调用新所有者。
- [x] 清理失败保留失败状态和重试能力；暂时忙碌保留 plugin_busy；正常并发不受影响。
- [x] HTTP available 与厂商 installed/authenticated 分工明确，缺 CLI 和未登录仍可进入对应修复流程。
- [x] SDK 与两个厂商插件的核心功能通过，原有正确修复未改变。
- [x] 未新增独立回归套件，所有非核心临时探针已删除。


## 实施记录

- 已完成五个功能文件的职责收敛；原执行层除 `_entry` 外不变，session、迁移、公共 Harness DTO/Protocol、能力解析、注册桥和厂商 adapter 的既有修复未改动。
- 长期测试只在现有宿主场景新增 23 行，没有新建测试文件或 helper，没有删改原断言。
- SDK/宿主核心测试 25 项通过，独立厂商进程 18 项通过；冻结临时探针由旧代码 1/6 通过变为修改后 6/6 通过。最后一处等价排版修改以 PawPort 定向 1 项和 6 组探针复核；没有无故扩跑全量测试。
- 修改文件的 pre-commit 全部通过；独立审查的 spec compliance、code quality 均 PASS，无待修复问题。
- 所有非核心临时探针及其专属字节码已清理。原始日志、源码校验、作者和审查报告保存在 `/private/tmp/qwenpaw-registry-state-evidence-20261109/`。
