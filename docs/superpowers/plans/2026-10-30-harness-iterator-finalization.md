# Harness 异步迭代器收尾修复方案

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. 遵守用户要求：功能代码和测试代码由不同子 agent 编写。

**Goal:** SDK 允许的普通异步迭代器能够正常执行；事件流关闭失败时，宿主仍完成本轮终态处理与会话保存。

**Architecture:** 保持 `run_turn() -> AsyncIterator[HarnessEvent]` 公共协议不变。仅在执行层按能力调用可选的 `aclose()`，就地处理关闭异常，再进入统一的终态与保存流程；保留原有取消传播和资源所有权。

**Tech Stack:** Python asyncio、现有 Harness SDK、pytest、PluginTestHost、真实会话保存接口。

**Spec:** 本轮 P1-1 审查反馈；[Harness SDK 设计](/Users/luohh/Documents/Qwenpaw/QwenPaw-main_plugin/docs/superpowers/specs/2026-10-22-harness-plugins-design.md)、[四方向测试精简约束](/Users/luohh/Documents/Qwenpaw/QwenPaw-main_plugin/docs/superpowers/specs/2026-10-28-harness-test-slimming.md)。核验基线为 `9158f382b`，2026-10-30。

## 问题判断

**问题确实存在，建议按 P1 在本版本修复，阻塞当前 PR 合并；不应归为可以忽略的 corner case。**

通俗地说，SDK 告诉开发者：“只要能一条条异步返回事件，就能接入。”宿主却在最后额外要求：“还必须有一个关闭方法。”开发者完全按 SDK 写了插件，回答已经输出，宿主仍会在收尾时报错，跳过“告诉前端这一轮结束”和“把这一轮存入历史”。用户可能看到回答输出后没有正常结束，刷新后本轮内容不在历史里。已有历史不会因此被删除。

触发条件是具体的合法实现方式，不需要并发、特殊系统或竞态：返回的对象实现 `__aiter__()`、`__anext__()`，但没有 `aclose()`。异步生成器只是异步迭代器的一种实现，前者有关闭方法，后者的协议不要求它。

这里应准确限定范围：不是“所有合法第三方插件都会失败”，而是“所有采用无 `aclose()` 迭代器的合法实现，都会在该收尾路径失败”。官方 Codex/Qoder 当前使用异步生成器，正常完成时不会触发“缺少方法”；关闭方法本身抛错是同一处收尾隔离缺陷的另一个入口。

## 代码依据与实际复现

| 位置 | 核验结果 |
| --- | --- |
| [harnesses.py:421](/Users/luohh/Documents/Qwenpaw/QwenPaw-main_plugin/src/qwenpaw/plugins/harnesses.py:421) | 公共返回类型是 `AsyncIterator[HarnessEvent]`，未要求 `aclose()`。 |
| [SDK 文档:322](/Users/luohh/Documents/Qwenpaw/QwenPaw-main_plugin/website/public/docs/plugins.en.md:322) | 文档同样承诺异步迭代器。 |
| [execution.py:574](/Users/luohh/Documents/Qwenpaw/QwenPaw-main_plugin/src/qwenpaw/runtime/backends/execution.py:574) | `finally` 第一项直接 `await event_stream.aclose()`；它抛出的异常不会回到前面的 `except Exception`。 |
| [execution.py:577](/Users/luohh/Documents/Qwenpaw/QwenPaw-main_plugin/src/qwenpaw/runtime/backends/execution.py:577) | 关闭之后才完成正文、计算 response 终态并调用会话保存；因此被一起跳过。 |
| [execution.py:615](/Users/luohh/Documents/Qwenpaw/QwenPaw-main_plugin/src/qwenpaw/runtime/backends/execution.py:615) | 最终消息和 response 的输出同样无法执行。 |
| [ConsoleChannel:558](/Users/luohh/Documents/Qwenpaw/QwenPaw-main_plugin/src/qwenpaw/app/channels/console/channel.py:558) | 外层只为 `SDKError`/`PluginBusyError` 补失败响应，不能依赖它修复这里的原始 `AttributeError`/`RuntimeError`，也不能补回历史。 |

已通过实际 `PluginTestHost` 安装插件、创建 workspace，调用真实 `BackendExecution.stream()`，并读取真实会话接口。仅替换插件 `run_turn()` 的返回对象，记录会话桥接调用；未替换执行层或保存实现。

| 返回对象 | 收到的 response 状态 | 外抛异常 | `append_turn()` 次数 | 已保存消息 |
| --- | --- | --- | --- | --- |
| 原有异步生成器，对照组 | Created → InProgress → Completed | 无 | 1 | 4，含工具消息 |
| 普通异步迭代器，无关闭方法 | Created → InProgress | `AttributeError: ... no attribute 'aclose'` | 0 | 0 |
| 异步迭代器，关闭方法抛错 | Created → InProgress | `RuntimeError: cleanup failed` | 0 | 0 |

两种异常迭代器都已成功产出正文和 `COMPLETED` 事件。问题发生在宿主处理完事件后的收尾阶段，不是插件没有完成回答。前面可以已有文本增量输出，不能把影响说成“整轮没有任何流事件”。

本地诊断结果：[复现日志](/private/tmp/qwenpaw-harness-p1-iterator-repro.log)。诊断脚本用后删除，后续自动化验收以仓库测试为准。

## Global Constraints

- 当前执行要求：最小功能修改；主测试只保留核心协议覆盖，非核心组合使用临时探针，用后删除。
- 功能与测试分开编写；保留现有断言，不通过改变 SDK 返回类型或放宽测试规避问题。
- 修改集中在执行层和现有宿主总测试；不增加新测试框架、helper 套件、依赖或错误码。
- 不改 Codex/Qoder 插件包、安装流程或公共依赖管理；不操作用户的 9099 服务和真实账户。
- 单 worker：异步迭代、关闭、资源操作留在事件循环。不得将整个执行函数或异步关闭放入 `run_sync_io()`；保存继续使用既有异步接口及 `run_async_to_completion()`。

## 修复后的明确行为

1. 无关闭方法：正常跳过关闭，正文、Completed 终态、本轮历史都完整保留。
2. 有可调用的关闭方法：仍 `await` 它，不能为了兼容普通迭代器而取消异步生成器的清理。
3. 正常执行后关闭抛出普通异常：捕获并记录关闭错误；建议本轮以 `failed`、现有 `harness_error` 结束，错误说明“事件流关闭失败”，已产出的正文仍保存。不能让关闭异常直接越过终态与保存流程。
4. 执行已经失败后关闭再次失败：保留原执行错误作为主要错误，关闭错误只记日志。
5. 已发生取消或消费端提前关闭：保留原取消/`GeneratorExit` 语义；关闭普通异常不得覆盖它。收尾完成后继续传播原中断，不输出伪成功。若取消发生在 `await close()` 本身，也要进入取消收尾，再传播取消。

普通异常使用 `except Exception`；取消与 `GeneratorExit` 按现有 `interrupted/cancelled` 机制单独处理。不要笼统吞掉 `BaseException`，不要重试关闭，不要引入实例重建或自动停用插件。

## Review Focus

- 无 `aclose()` 的合法迭代器：正常终态和真实历史都应存在。
- 有 `aclose()` 且关闭正常：清理仍执行，已有异步生成器路径不退化。
- 关闭普通异常：有明确失败终态，已输出内容保存一次。
- 主要执行错误与关闭错误同时出现：主要错误不被覆盖。
- 取消或消费端提前退出遇到关闭错误：中断语义、保存和资源释放保持一致。

## 文件范围

| 文件 | 计划修改 |
| --- | --- |
| [execution.py](/Users/luohh/Documents/Qwenpaw/QwenPaw-main_plugin/src/qwenpaw/runtime/backends/execution.py:574) | 将可选关闭及异常处理集中放在 `_produce()` 原收尾位置，保留后续统一终态与保存流程。 |
| [test_harness_runtime.py](/Users/luohh/Documents/Qwenpaw/QwenPaw-main_plugin/tests/unit/runtime/backends/test_harness_runtime.py) | 仅补一个参数化测试，覆盖普通迭代器与关闭抛错两种核心情况；复用现有 Host、请求和真实历史读取，不扩展原取消测试。 |
| [plugins.en.md](/Users/luohh/Documents/Qwenpaw/QwenPaw-main_plugin/website/public/docs/plugins.en.md:322)、[plugins.zh.md](/Users/luohh/Documents/Qwenpaw/QwenPaw-main_plugin/website/public/docs/plugins.zh.md:294) | 各补一句：普通异步迭代器合法；如提供异步关闭方法，宿主会调用。无需改变 SDK 签名或版本。 |

## 执行步骤与 checklist

### Task 1：先锁定协议与失败结果，完成最小修复

**Interfaces:** 输入仍为 `HarnessBackend.run_turn(context, request) -> AsyncIterator[HarnessEvent]`；输出仍为现有 `BackendExecution.stream()` 的消息和 response。使用既有 `HarnessSessionBridge.append_turn()`，不新增接口。

- [x] **步骤 1：测试 agent 补充普通迭代器场景。** 在 `test_iterator_cleanup_finalizes_response_and_history` 的无关闭方法参数中，断言最终 response 为 `completed`，正文完整，真实保存中同时存在用户输入与回答，`append_turn()` 被等待恰好一次。
- [x] **步骤 2：同一测试补充关闭失败场景。** 关闭被调用一次；无关闭异常逃出流；最终为 `failed/harness_error`；真实历史保留已产出正文，保存恰好一次。主框架仅保留这两个参数。
- [x] **步骤 3：只运行新增两个场景，取得 RED。** 预期当前实现分别因 `AttributeError` 和 `RuntimeError` 失败；不能通过 mock 掉事件流关闭或真实保存来让测试通过。
- [x] **步骤 4：功能 agent 修改 `_produce()`。** 用 `getattr(event_stream, "aclose", None)` 和 `callable()` 判断；将查询、调用和等待放入同一个局部异常处理范围。依照上文的错误优先级更新 `error_text/interrupted/cancelled`，随后继续原有终态与保存流程。记录关闭异常使用宿主日志，不依赖可能已失效的插件回调。
- [x] **步骤 5：功能 agent 补充中英文协议说明。** 不把 `AsyncIterator` 强制改为 `AsyncGenerator`，不要求第三方为规避宿主问题添加空关闭方法。
- [x] **步骤 6：测试 agent 用临时探针验证错误优先级和取消。** 原执行错误与关闭错误并存时保留原错误；运行中取消遇到关闭错误时仍传播取消并保存正文、释放资源。使用真实宿主的临时脚本，验收后删除，不放入主测试框架。

### Task 2：验证与收尾

**Interfaces:** 消费 Task 1 的现有接口；验收终态、真实历史和资源所有权，不新增跨模块功能。

执行目录：`/Users/luohh/Documents/Qwenpaw/QwenPaw-main_plugin`。隔离测试状态：

```bash
export QWENPAW_WORKING_DIR=/private/tmp/qwenpaw-iterator-tests-work
export QWENPAW_SECRET_DIR=/private/tmp/qwenpaw-iterator-tests-secrets
export QWENPAW_DEPENDENCY_STATE_DIR=/private/tmp/qwenpaw-iterator-tests-dependencies
.venv-test/bin/python -m pytest -q tests/unit/runtime/backends/test_harness_runtime.py tests/unit/plugins/test_sdk_harness.py
```

- [x] **步骤 7：上述两个受影响总测试文件全部通过。** 普通迭代器、关闭失败、原异步生成器、取消和并发基本路径均保留；不运行全仓套件。
- [x] **步骤 8：临时探针检查关闭期间新发生取消和消费端提前退出。** 确认中断不会被普通异常分支误吞，会话保存仍执行、调用所有权释放。完成后删除这些探针及前期复现脚本，只保留验收结果。
- [x] **步骤 9：独立复核与静态检查。** 检查原错误优先级、关闭失败不会跳过保存、现有 `run_async_to_completion()` 未删除；确认无同步磁盘/进程操作进入事件循环；运行受影响文件的格式、lint 及 `git diff --check`。
- [x] **步骤 10：记录结果并提交修复。** 记录 RED/GREEN 和受影响测试结果；功能与测试变更一起提交。没有独立发布厂商插件 ZIP 的需要。

## 合并验收标准

无关闭方法的合法 SDK 实现能够正常完成；关闭普通异常不会使本轮无终态、无历史；原执行错误与取消语义得到保留；原异步生成器清理和插件资源释放没有回退。上述条件通过后，P1-1 才可关闭。

## 实施验收记录

已完成最小收尾修复，公共 SDK 签名不变，异步关闭仍在原事件循环中执行。新增主测试仅为一个两例参数化测试；已有测试和夹具的 AST 保持不变。

- 修复前：新增两例均 RED，分别复现缺少关闭方法和关闭抛错。
- 修复后：宿主与 SDK 两个受影响总测试文件共 **25 passed**。
- 额外错误优先级、运行中取消、关闭中取消、消费端提前关闭：临时探针 **4 passed**，探针源码与对应字节码用后删除，未进入主测试框架。前期复现脚本亦已删除。
- 独立复查：规格与代码质量均通过，无 findings。
- 仅提交本次执行层、核心测试、协议说明与本方案文档；不更新插件 ZIP、不推送、不操作 9099 服务。
