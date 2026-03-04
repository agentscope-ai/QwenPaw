---
title: "[Feature]: Daemon 与命令分叉（两阶段实现）"
labels: ["enhancement", "triage"]
---

## Summary

在 Runner 层对「系统/daemon 命令」与「普通对话」做分叉，命令路径不创建 CoPawAgent，走轻量命令管道；新增 daemon 内置命令（status / restart / reload-config / version / logs）并与 `copaw daemon` CLI 共用执行层。分两阶段实现：一阶段完成分叉 + 两个 Mixin + daemon 5 子命令；二阶段为 daemon 增加 F12 模式 Agent 能力（自诊断、自愈、自我进化记录）。

## Component(s) Affected

- [x] Core / Backend (app, agents, config, providers, utils, local_models)
- [ ] Console (frontend web UI)
- [ ] Channels (DingTalk, Feishu, QQ, Discord, iMessage, etc.)
- [ ] Skills
- [x] CLI
- [x] Documentation (website)
- [x] Tests
- [ ] CI/CD
- [ ] Scripts / Deploy

## Problem / Motivation

- 当前命令分叉在 `CoPawAgent.reply()` 内，所有请求都会先走「创建 Agent + 加载 session」重路径，命令类请求也创建完整 CoPawAgent，成本高且语义不清。
- 缺少运维/自检能力：无法在对话或 CLI 中统一执行 restart、看状态、看最近日志、热加载配置等。
- 日后需要 daemon 具备 Agent 能力（F12 模式：不报错、自诊断、自愈、可进化），需先有清晰的命令分叉与 daemon 命令体系作为基础。

## Proposed Solution

**整体**：在 `AgentRunner.query_handler` 入口根据「最后一条用户消息」判断是否为命令；若是命令则走命令管道（不创建 CoPawAgent），否则保持现有 Agent 流程。回复仍经同一套 stream 回到 channel。

**两阶段实现**：

### 一阶段

- **分叉**：在 `query_handler` 入口识别以 `/` 开头的命令（对话类 + daemon 类），走 `run_command_path(request, msgs, runner)`，yield 事件后 return，不创建 Agent。
- **两个 Mixin**：
  - **ConversationCommandHandlerMixin**：对话类命令（现有 `/compact`、`/new`、`/clear`、`/history`、`/compact_str`、`/await_summary`、`/start`）；本次不修改命令集合与行为，仅设计上可迁入 mixin，由命令分发器在轻量路径中调用（需 session/memory/formatter/memory_manager）。
  - **DaemonCommandHandlerMixin**：daemon 类命令，解析 `/daemon <sub>` 或短名（如 `/restart` 等价 `/daemon restart`），调用统一执行层。
- **Daemon 执行层**（新建 `app/runner/daemon_commands.py`）：`run_daemon_status`, `run_daemon_restart`, `run_daemon_reload_config`, `run_daemon_version`, `run_daemon_logs`（控制台最近 N 行日志），供 in-chat 与 CLI 共用；context 注入 `load_config`、`memory_manager` 等。
- **CLI**：新增 `copaw daemon` 子命令组，子命令 `status`、`restart`、`reload-config`、`version`、`logs`（可选 `-n` 行数），内部调用上述执行层。
- **命令分发**：新建 `app/runner/command_dispatch.py`，组合两个 mixin，先判 daemon 再判对话类，分别调用对应 `handle_*`，将结果转 Event 流。
- 会话类命令集合与行为**本次不修改**；仅 daemon 为新增。

### 二阶段

- **DaemonAgent**：基于 ReAct 的简化版 agent，F12 模式（外层 try/except、错误不抛出、返回结构化诊断信息）。
- 受限 tools（只读/白名单）、独立 system prompt（如 `DAEMON_SOUL.md`）。
- 自诊断：失败时自动跑诊断步骤（日志、配置、依赖等）；自愈：重试/回退/建议执行 `/daemon restart` 等。
- 自我进化首版只做「记录结果」（如写入 `DAEMON_RULES.md` 或经验存储），供后续诊断参考。
- 在命令管道中：当子命令为 `diagnose` 或 `agent` 时，创建 DaemonAgent，跑一轮 ReAct，结果转 Event 返回。

**命名**：daemon 统一支持 `/daemon <sub>`，同时支持短名（如 `/restart`）；`/daemon xxx` 形式主要为日后 daemon agent 作为 query 预留。

详细设计见：`docs/design/daemon-and-command-dispatch.md`。

## Alternatives Considered

- 保持分叉在 agent 内：无法避免命令请求也创建完整 Agent，成本与复杂度仍高。
- daemon 仅 CLI、不做 in-chat：会割裂运维入口；统一执行层 + 两处调用更一致。

## Additional Context

- 命令文档：https://copaw.agentscope.io/docs/commands
- 设计文档：`docs/design/daemon-and-command-dispatch.md`

## 实现约定（已定）

- **控制台日志来源**：`/daemon logs` 从 **working_dir 下固定 log 文件** 做 tail。采用 **`WORKING_DIR / "copaw.log"`**；实现时在 app 运行时为 copaw logger 增加写入该路径的 `FileHandler`（如在 `setup_logger` 或 app 启动时），以便 `/daemon logs` 与 `copaw daemon logs` 对该文件做 tail（最近 N 行可配置）。
- **restart 触发方式**：当前应用由 **uvicorn** 启动（`cli/app_cmd.py`）。**单 worker（默认）**：daemon restart 处理函数在返回响应后安排进程退出（如 `os._exit(0)`），由 systemd/supervisor/docker 等进程管理器负责拉起新进程，即“重启 = 本进程退出让管理器重启”。**多 worker**：uvicorn 主进程支持通过 **SIGHUP** 优雅重启 worker；可选在启动时将主进程 PID 写入 `WORKING_DIR / "copaw.pid"`，restart 时对该 PID 发 SIGHUP；若一阶段不实现多 worker 重启，可文档说明“多 worker 下请对 uvicorn 主进程手动发 SIGHUP 或使用单 worker”。

## Willing to Contribute

- [ ] I am willing to open a PR for this feature (after discussion).
