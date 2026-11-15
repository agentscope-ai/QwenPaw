# Harness 宿主异步边界收敛方案

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement task-by-task. 功能代码与测试由不同 agent 编写；非核心测试仅作临时探针，验收后删除。

**Goal:** 将公共 Agent 解析中的同步配置读取移出事件循环，保持单 worker 其他请求可继续执行。

**Architecture:** 只在 get_agent_for_request 中使用现有 run_sync_io 加载配置；选择 Agent、准入判断和获取 Workspace 仍在原事件循环。Qoder SDK 内部同步认证文件操作记录为外部依赖已知限制，不修改厂商实现，不作为本分支完成条件。

**Tech Stack:** Python asyncio、现有 QwenPaw IO 工具与宿主核心测试。

**Spec:** 用户 2026-11-10 明确的职责边界，以及本文件“设计”和“Global Constraints”。

## 已确认问题及职责

核查基线：分支提交 388e7b2f4，2026-11-10。

| 路径 | 已确认行为 | 本次处理 |
| --- | --- | --- |
| Harness 管理网关 → get_agent_for_request → load_config | 即使请求指定 Agent，仍在事件循环里同步加载全局配置；缓存命中也会检查文件并获取同步锁 | QwenPaw 自有代码，直接修复 |
| QoderBackend._connect → QoderSDKClient.connect → 默认 Transport | SDK 在异步 connect 内同步创建认证目录、写入文件和设置权限 | 外部依赖限制，保留公开 SDK 调用并如实记录 |

调用方见 [公共 Agent 解析](../../../src/qwenpaw/app/agent_context.py)、[管理网关](../../../src/qwenpaw/plugins/_harness_http.py)、[配置加载](../../../src/qwenpaw/config/utils.py) 和 [Qoder adapter](../../../plugins/harness/qoder/adapter.py)。网关后续读取厂商配置已经使用 load_agent_config_async，不重复改造。

诊断探针在配置加载中注入 150ms 同步延迟，预先排队的事件循环回调延后约 151ms。真实 Qoder SDK 认证 payload 写入注入相同延迟，回调延后约 156ms；SDK 探针在启动 CLI 前停止，没有启动厂商进程。这些数字证明阻塞路径，不代表生产磁盘耗时。

## 设计

保留明确参数、request.state、X-Agent-Id、active_agent 的选择优先级。读完前三种输入后，只读取一次全局配置：

```python
config = await run_sync_io(load_config)
if not target_agent_id:
    target_agent_id = config.agents.active_agent or "default"
```

配置文件读取、缓存、同步锁及既有配置迁移逻辑作为一次完整同步操作在线程中完成，沿用 load_config 原锁与返回值语义。目标选择、启用校验、HTTP 错误映射及 await manager.get_agent(...) 保持在事件循环。

复用 [run_sync_io](../../../src/qwenpaw/utils/io_utils.py) 的取消语义：取消请求后等待线程实际结束，再传播取消。这样不会让配置迁移或缓存更新在线程中继续运行而调用方已经完成退出；等待期间其他请求仍可调度。

相比在 Harness 网关绕过公共解析，修公共入口只需一处改动，所有调用方都能受益，也继续验证 Agent 是否存在和启用。新增 await 后，网关已有的所有权和代次检查保持不变。

本轮验收只要求消除这一公共配置加载边界的阻塞，并保持原有行为。通过验收代表宿主修复完成，不代表调用厂商 SDK 的整条链路已没有同步 I/O。

## Global Constraints

- 仅修改公共 Agent 解析的配置读取边界，不改 Agent 选择优先级、默认值、禁用/不存在校验或现有错误响应。
- 不修改 load_config 的锁、缓存、迁移与返回值语义；完整调用交给现有 run_sync_io，不新增缓存或通用异步框架。
- manager.get_agent、registry 所有权检查和异步资源管理保留原事件循环。
- 不修改 Qoder SDK、安装目录或固定依赖；不复制厂商传输、不 monkeypatch，不将整个 connect 放入线程或另开事件循环。
- 厂商 SDK 的修复、维护、发布和升级不属于本轮任务或验收前置条件；不增加 SDK 内部认证文件及清理行为的测试要求。
- 保留之前审批/模型与实例配置隔离、并发复用、插件忙碌响应、会话保存、可选 aclose、冻结迁移及共享 UI 的正确逻辑。
- 功能与测试由不同 agent 编写；保留原断言，只运行受影响的测试。核心验证归入已有宿主总文件，非核心临时探针验收后删除。

## 文件职责

| 文件 | 改动 |
| --- | --- |
| src/qwenpaw/app/agent_context.py | 导入 run_sync_io，将两处同步配置读取分支合并为一次 await |
| tests/unit/runtime/backends/test_harness_runtime.py | 扩展既有配置 IO 验证，覆盖真实公共 Agent 解析；保留原执行路径和取消断言 |
| 本文档 | 记录修复和验收结果，保留外部依赖限制 |

## Review Focus

1. 明确指定 Agent 时仍须读取一次配置并验证启用状态；不能为减少读取跳过准入检查。
2. 线程内等待磁盘或配置锁时，事件循环能执行其他任务；取消须在线程完成后传播。
3. 配置读取新增 await 后，插件停用或卸载可以穿插执行，管理网关仍须拒绝失效注册项。

## Task 1：修复并验证公共 Agent 解析

**接口：** 保持 `async get_agent_for_request(request, agent_id=None) -> Workspace` 不变。

- [x] 测试作者在改功能前扩展现有核心 IO 测试，验证真实公共解析不会阻塞心跳，取消后等待线程完成，manager 不会在取消后被调用；先记录正确原因的失败结果。
- [x] 临时探针覆盖明确参数、state、header、active_agent 的优先级及禁用/不存在错误语义，确认每次解析只读取一次配置。探针验证后删除。
- [x] 功能作者仅用 await run_sync_io(load_config) 合并配置读取，保留后续校验、manager await 和错误映射。
- [x] 运行既有宿主总测试和受影响的公共上下文/配置测试，原执行路径和所有旧断言保留；不能修改测试以掩盖功能失败。
- [x] 临时验证配置 await 期间停用插件，管理请求明确拒绝且不创建厂商客户端；不修改已有 registry 检查。
- [x] 独立审查 diff，确认厂商插件、依赖和既有修复均未变化，清理临时探针并记录宿主验收结果；宿主修复通过即完成本轮，不等待外部 SDK 修复或发布。

## 外部依赖已知限制

Qoder SDK 认证文件的创建、写入和权限设置本身属于正常工作。问题仅在于已核查版本把这些有限文件操作同步放在异步 connect 内执行；慢磁盘可能影响单 worker 上其他请求，不能据此推论整个 SDK 设计有问题。

本插件固定使用 qoder-agent-sdk 1.0.9。核查的官方 1.0.17 源码仍有同样的同步调用，因此不把升级到该版本视为修复。[Qoder SDK (2026/10), 源码包与校验值](https://pypi.org/project/qoder-agent-sdk/1.0.17/#files)

厂商 SDK 的修复、维护和发布由 Qoder 负责；QwenPaw 继续使用公开 SDK 接口。未来若厂商发布相关修复，可独立评估兼容性后更新依赖。**本次宿主改造完成不依赖厂商修正版发布，也不声称消除了 Qoder SDK 内部的阻塞风险。** 本轮不扩展处理 SDK 的认证取消/清理实现。

## 最终 checklist

- [x] 公共 Agent 配置读取离开事件循环，选择优先级、准入及错误语义不变。
- [x] 慢读取时其他任务仍能调度，取消在线程完成后传播，manager 和异步资源仍属原事件循环。
- [x] 原宿主核心功能和管理网关所有权检查通过验证。
- [x] 厂商源码、公开调用、依赖版本和插件 ZIP 均未修改；已知限制如实保留。
- [x] 非核心探针已删除，长期测试继续使用现有精简框架。

## 实施与验收记录

- get_agent_for_request 只增加 run_sync_io 导入，并将配置读取合并为一次 await；校验起至文件末尾逐字未变，其余模块 AST 不变。1,566 个受保护文件哈希保持一致。
- 独立测试作者先验证 RED：新增公共解析场景因配置读取发生在事件循环线程而失败；原 stream 场景通过。功能作者最小修改后，两场景均通过。永久测试仅扩展既有宿主总文件，原 stream 测试正文逐字保留，没有新增长期测试文件。
- 最终受影响测试 25 项通过：宿主总文件 17 项、公共上下文 3 项、配置加载/保存 5 项。9 项临时语义及真实网关竞态探针通过：配置 await 期间停用插件，返回 409 backend_unavailable，未创建厂商客户端。
- pre-commit 所有适用检查通过；任务独立审查的 spec compliance / code quality 及最终集成审查均通过，无待修问题。临时探针源码及专属字节码已清理；长期测试仅原文件增加 59 行，没有新增测试框架或隐藏 helper。
- 验收证据保存在 `/private/tmp/qwenpaw-host-async-boundaries-evidence-20261110-1q3vvm4y`；厂商 SDK、依赖版本和插件 ZIP 均未修改。本轮宿主改造完成，外部 SDK 限制继续如实保留。
