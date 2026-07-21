# PR #6270 Review：User Editable Agent Mode

- PR: [agentscope-ai/QwenPaw#6270](https://github.com/agentscope-ai/QwenPaw/pull/6270)
- Reviewed head: `f4f66ec9463652d80046cfab3ff5f854e4b295b2`
- Base: `872c8158bb58ecd33efe8c67caaccf5e3119a67a`
- Review date: 2026-07-21
- Original recommendation: **Request changes**
- Current branch recommendation: **Approve after CI**

## Review checklist

- [x] 检查 PR metadata、92 个变更文件及关键运行时 diff
- [x] 检查 Custom Loop CRUD、Catalog、Compiler、Mode lifecycle 和 Console 表单
- [x] 检查同步 I/O 是否阻塞事件循环
- [x] 检查 Windows、macOS 路径和文件系统兼容性
- [x] 逐条核对 14 个 GitHub inline review threads
- [x] 执行目标后端与前端单测
- [x] 检查当前 GitHub checks 和失败日志

## Fix status（当前分支）

- [x] Finding 1：render tests 改为确定性的 `fireEvent` 与语义查询；完整 Vitest 已通过
- [x] Finding 2：前后端 create/duplicate 均限制字段长度，后端复制后重新执行 Pydantic 校验
- [x] Finding 3：后端统一使用 `strip().casefold()`；前端同步拦截常见 Unicode 大小写折叠冲突
- [x] Finding 4：Loop CRUD 通过 `asyncio.to_thread()` 持久化；`agent.json` 使用带锁的同目录原子替换
- [x] Finding 5：CommandHandler 在有无 prompt context 时都兜底清理 pending gate state
- [x] Finding 6：日志边界统一转义 CR/LF，并覆盖相关输入路径
- [x] 扩展项：Mission JSON/文本状态写入复用原子 I/O，状态查询、目录扫描及初始化写入移出事件循环

## Findings

### 1. [P1] PR 当前新增的两个 render tests 在完整 Vitest job 中超时

位置：

- [`AgentLoopCard.render.test.tsx:42`](https://github.com/agentscope-ai/QwenPaw/blob/f4f66ec9463652d80046cfab3ff5f854e4b295b2/console/src/pages/Agent/Config/components/AgentLoopCard.render.test.tsx#L42)
- [`AgentLoopCard.render.test.tsx:69`](https://github.com/agentscope-ai/QwenPaw/blob/f4f66ec9463652d80046cfab3ff5f854e4b295b2/console/src/pages/Agent/Config/components/AgentLoopCard.render.test.tsx#L69)
- [失败的 Vitest Unit Tests job](https://github.com/agentscope-ai/QwenPaw/actions/runs/29800560550/job/88540668903)

完整 CI 中两个测试均超过默认 5 秒，导致 `Vitest Unit Tests` 失败（132 个 test files
通过，1 个失败；1171 个 tests 通过，2 个超时）。目标文件单独在本地执行会通过，说明更像是
完整测试负载下的时序/性能不稳定，而不是稳定断言失败，但它仍然是当前 merge blocker。

建议减少 UI 交互等待和不必要渲染，或为确实需要的异步渲染使用确定性等待；只有证明测试本身
稳定且合理地需要更久时，才局部提高 timeout，不建议全局放宽。

### 2. [P1] duplicate/create 可以构造超过后端上限的 Mode，reload 时会被静默丢弃

位置：

- [`loops.py:229-238`](https://github.com/agentscope-ai/QwenPaw/blob/f4f66ec9463652d80046cfab3ff5f854e4b295b2/src/qwenpaw/app/routers/loops.py#L229)
- [`AgentLoopCard.tsx:1509-1525`](https://github.com/agentscope-ai/QwenPaw/blob/f4f66ec9463652d80046cfab3ff5f854e4b295b2/console/src/pages/Agent/Config/components/AgentLoopCard.tsx#L1509)
- [`AgentLoopCard.tsx:1637-1662`](https://github.com/agentscope-ai/QwenPaw/blob/f4f66ec9463652d80046cfab3ff5f854e4b295b2/console/src/pages/Agent/Config/components/AgentLoopCard.tsx#L1637)
- 相关 threads：[`duplicate_custom_mode`](https://github.com/agentscope-ai/QwenPaw/pull/6270#discussion_r3612487994)、[创建弹窗长度](https://github.com/agentscope-ai/QwenPaw/pull/6270#discussion_r3612488048)

`CustomLoopModeConfig` 限制 `id/slash_command <= 64`、`name <= 80`，但 backend duplicate
直接修改已创建的 Pydantic 实例，默认不会执行 assignment validation；frontend duplicate
也直接拼接 `-copy` / ` Copy`。创建弹窗则没有 `maxLength`。边界值可被扩展到 69/85/69，
`model_dump()` 仍成功，写入后 `_sanitize_custom_loop_modes()` 会在 reload 时跳过该 Mode。

这不是单纯的表单报错：用户可能看到保存成功，随后 Mode 消失。backend duplicate 应生成满足
长度限制且唯一的值，并用 `CustomLoopModeConfig.model_validate()` 对完整副本重新校验后再持久化；
frontend 的创建、复制路径也应执行同一约束并显示明确错误。

### 3. [P1] 保存时与 reload 时使用不同的名称归一化，会静默删除合法保存的 Mode

位置：

- [`config.py:1292`](https://github.com/agentscope-ai/QwenPaw/blob/f4f66ec9463652d80046cfab3ff5f854e4b295b2/src/qwenpaw/config/config.py#L1292)
- [`config.py:1360-1375`](https://github.com/agentscope-ai/QwenPaw/blob/f4f66ec9463652d80046cfab3ff5f854e4b295b2/src/qwenpaw/config/config.py#L1360)
- [`loops.py:256-258`](https://github.com/agentscope-ai/QwenPaw/blob/f4f66ec9463652d80046cfab3ff5f854e4b295b2/src/qwenpaw/app/routers/loops.py#L256)

API/`LoopConfig` 用 `lower()` 判断重名，加载清洗却用 `casefold()`。例如 `Straße` 和
`STRASSE` 能通过保存校验，但 reload 时两者都 casefold 为 `strasse`，第二个 Mode 会被
静默跳过。已用当前 HEAD 复现：`LoopConfig` 接受两个 Mode，随后 sanitizer 只保留第一个。

建议定义唯一的名称规范化 helper（推荐 `strip().casefold()`），在 API、Pydantic validator、
sanitizer 和前端预检查中保持一致。至少 backend 的“接受保存”和“接受加载”必须完全相同。

### 4. [P1] async CRUD 路由直接做同步且非原子的配置文件写入

位置：

- [`loops.py:266-275`](https://github.com/agentscope-ai/QwenPaw/blob/f4f66ec9463652d80046cfab3ff5f854e4b295b2/src/qwenpaw/app/routers/loops.py#L266)
- [`config.py:2734-2773`](https://github.com/agentscope-ai/QwenPaw/blob/f4f66ec9463652d80046cfab3ff5f854e4b295b2/src/qwenpaw/config/config.py#L2734)

四个 async 写接口在 event-loop thread 内调用同步 `save_agent_config()`。该函数会同步加载配置、
创建目录、打开文件并执行格式化 JSON dump；在慢盘、网络盘、杀毒扫描或桌面端文件争用时，
会阻塞同一 worker 的所有请求。

同时它用 `open(..., "w")` 先截断现有 `agent.json` 再写入。设计文档称这里是“原子写入”，
实际并非原子；config watcher、另一个进程或异常退出可能观察到空文件/半个 JSON。该风险在
Windows 的文件占用/杀毒扫描场景和 macOS 桌面端文件监听场景都值得关注。

建议：

1. 在同目录写临时文件并 flush/close，使用 `os.replace()` 提交；处理 Windows 上可预期的
   replace/文件占用错误，失败时保留旧文件。
2. 为同一 agent 的写入加锁，避免多写者覆盖。
3. async endpoint 通过 `asyncio.to_thread()`/线程池调用完整的同步持久化事务，或提供真正的
   async persistence API；只把 reload 放后台不足以解决写文件阻塞。

### 5. [P2] `/new`、`/clear` 清理 deferred gate state 依赖 DefaultMode 成功执行

位置：

- [`command_handler.py:211-233`](https://github.com/agentscope-ai/QwenPaw/blob/f4f66ec9463652d80046cfab3ff5f854e4b295b2/src/qwenpaw/agents/command_handler.py#L211)
- 相关 thread：[`pending gate fallback`](https://github.com/agentscope-ai/QwenPaw/pull/6270#discussion_r3612488024)

当前正常 workspace 会注册 `DefaultMode`，它会调用 `clear_pending_gate_state()`，因此主路径
通常工作。但 `_reset_modes()` 在 `ctx is None` 时直接返回，而且任意 mode reset 失败都会被
吞掉并继续；CommandHandler 自身不再保证清理 `_gate_pending_stop`。这使 conversation reset
的核心不变量依赖插件/bootstrap 状态。

建议在遍历 mode 的 `finally`/兜底路径中由 CommandHandler 对当前 agent 直接清理 deferred
gate decision。Mode 仍负责自己的 session state，pending decision 则由持有它的 Agent/handler
负责收口。

### 6. [P2] 当前未解决的 CodeQL log-injection threads 有实际输入路径

位置：

- [`loops.py:146-150`](https://github.com/agentscope-ai/QwenPaw/blob/f4f66ec9463652d80046cfab3ff5f854e4b295b2/src/qwenpaw/app/routers/loops.py#L146)
- [`config.py:1323-1403`](https://github.com/agentscope-ai/QwenPaw/blob/f4f66ec9463652d80046cfab3ff5f854e4b295b2/src/qwenpaw/config/config.py#L1323)
- 相关 threads：[`loops.py`](https://github.com/agentscope-ai/QwenPaw/pull/6270#discussion_r3613049964)、[`config.py #355`](https://github.com/agentscope-ai/QwenPaw/pull/6270#discussion_r3619285338)、[`#356`](https://github.com/agentscope-ai/QwenPaw/pull/6270#discussion_r3619285341)、[`#357`](https://github.com/agentscope-ai/QwenPaw/pull/6270#discussion_r3619285345)、[`#358`](https://github.com/agentscope-ai/QwenPaw/pull/6270#discussion_r3619285350)、[`#359`](https://github.com/agentscope-ai/QwenPaw/pull/6270#discussion_r3619285355)、[`#360`](https://github.com/agentscope-ai/QwenPaw/pull/6270#discussion_r3619285361)

`/loops/status` 可把请求中的 `session_id` 写入 warning；配置清洗日志还会写入包含原始输入的
Pydantic error。参数化 logging 只避免字符串格式化问题，不会自动删除 CR/LF，因此攻击者
可伪造多行日志或污染日志分析字段。

建议在日志边界统一转义 `\r`/`\n`（或使用结构化日志字段并由 formatter 保证单行编码），
不要只在这七个 call site 各自截断。

## Review threads 取舍

| Thread | 结论 | 处理 |
| --- | --- | --- |
| `duplicate_custom_mode` 超长 | 有效，HEAD 仍可复现 | 合并到 Finding 2 |
| 创建弹窗缺少长度约束 | 有效，HEAD 仍存在 | 合并到 Finding 2 |
| `/new`/`/clear` pending state | 主路径部分缓解，但缺少不变量兜底 | Finding 5 |
| CodeQL log injection | 有效；一个旧 thread 已 resolved，但当前 7 个仍 unresolved | Finding 6 |
| `_validate_mode()` 未捕获 `ValidationError` | 不成立 | Pydantic `ValidationError` 继承 `ValueError`，当前 catch 能覆盖 |
| completion rubric criteria description | 已过时 | 当前 HEAD 已移除该 criteria schema |
| completion rubric criteria ID 重复 | 已过时 | 当前 HEAD 已移除该 criteria list |

## 同步 I/O 审计

Finding 4 已修复：Loop CRUD 的完整同步持久化事务由 `asyncio.to_thread()` 执行，避免在
event-loop thread 中创建目录、序列化 JSON 和写文件。`save_agent_config()` 在现有配置锁内，
通过同目录临时文件、`flush()`、`fsync()`、关闭文件和 `os.replace()` 提交；replace 失败时旧文件
保持不变，临时文件会清理。

Mission 也在本 PR 一并收口：`task.md`、`progress.txt`、`prd.json` 和 `loop_config.json` 使用相同
原子写入 helper；任务初始化和 loop config 写入通过 `asyncio.to_thread()` 执行，`status`/`list`
涉及的目录扫描与同步读取也移出事件循环。原有 `MissionGate.check()` 和
`persistence_snapshot()` 继续使用线程边界。

## Windows / macOS 兼容性结论

- 生产代码新增路径未发现硬编码 `/` 或手工拼接本地文件路径；`pathlib.Path` 用法总体正确。
- Git/subprocess 探测继续使用 argument list 和 async command runner，未新增 shell quoting 或
  `cmd.exe`/POSIX shell 分歧。
- Mission 默认 verify command 当前只是写入状态并注入 prompt，不在此代码中直接启动 shell，
  因而本 PR 没有新增平台相关执行器问题。
- 原子临时文件与目标文件位于同一目录，避免跨卷 rename；临时文件在 replace 前已关闭，兼容
  Windows 的打开文件替换限制，也适用于 Linux/macOS。
- replace 或 Windows 文件占用错误会向上返回，旧目标文件不被截断，残留临时文件由 `finally`
  清理。
- 仓库 CI 已包含 Windows/macOS Python matrix；本地审查环境为 macOS，未在本机执行 Windows。

## Verification

后端目标测试（conda 环境 `QwenPaw`）：

```text
94 passed in 0.97s
```

覆盖：atomic I/O、logging sanitizer、loops router、custom loop modes、mode lifecycle、runner、
mission settings、command handler。

前端目标测试：

```text
133 test files passed
1174 tests passed
```

完整 Vitest suite 通过；原先 Finding 1 的两个 5 秒超时未再出现。TypeScript `tsc -b --noEmit`
和本次变更文件的 ESLint 检查也通过。

Python 变更文件的 pre-commit（AST、mypy、Black、flake8、pylint 等）全部通过。仓库全量
`pytest -q` 在收集既有 contract test 时被缺失的
`qwenpaw.app.runner.control_commands.base` 模块阻断；该路径不在本次 diff 中，目标测试不受影响。
完整 `tests/unit` 另有 4992 passed、6 skipped，3 个失败全部来自工作树中既有的未跟踪测试
`test_goal_stale_session.py`，其断言的旧 API（`GoalMode.on_conversation_reset(workspace=...)` 和
`StopHandler.reset()`）与当前生产代码不匹配，也不属于本次变更。

## Final recommendation

当前工作树已处理 Findings 1-6，并额外完成 Mission 原子异步 I/O。待 CI 在 Linux、Windows、
macOS 上复验通过后，建议 **Approve**。
