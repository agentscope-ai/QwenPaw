# 聊天历史接口测试迁移：核验结论与修复计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 2026-10-27 用户已授权执行；本地修复已完成，验证结果与剩余 CI 门禁见末尾。执行时遵守用户要求：测试由测试 agent 编写；如发现功能缺陷，由另一位功能 agent 修改，不能通过削弱测试掩盖问题。

**Goal:** 将聊天历史路由的既有测试迁移到新的配置读取与后端执行接口，保留历史恢复、失败降级、原生后端和旧格式兼容验证，恢复单元测试门禁。

**Architecture:** 默认只修改 `tests/unit/app/chats/test_api_project_dirs_and_crud.py`。使用具名字段明确的 Workspace 替身和测试内的异步配置 mock；保留生产接口的 `load_agent_config_async()` 与 `backend_runtime`。不为过期测试重新引入旧接口。

**Tech Stack:** Python、pytest、pytest-asyncio、unittest.mock.AsyncMock、FastAPI。

**Spec:** 用户本轮提供的 P2 审查条目及下文核验结论；历史兼容与异步 I/O 要求沿用 [Harness 插件化计划](2026-10-22-harness-plugins.md)。

**核验版本：** `37d562f21e3725a0eab516acbcd93ec2d838677f`；对照版本为本分支原始基线 `0db9a8e625e73917a0d113e255b3147134022db8`。

## 通俗解释和合并判断

聊天历史接口改用了新的工作方式，但测试仍在给它提供旧版“模拟工作区”。新接口先读取工作区的 `agent_id`，再异步获取配置，并通过 `backend_runtime` 恢复第三方历史；旧替身没有 `agent_id`，只有 `config` 和 `harness_runtime`。因此，测试还没有检查消息内容，就因缺少字段中断。

**问题确实存在，应在合并前修复，P2 定级合理。** 这次证据证明了测试迁移遗漏和确定的测试失败，尚不能据此宣称真实用户读取历史也会触发同一个 AttributeError。生产 Workspace 已定义 `agent_id` 和 `backend_runtime`，其位置分别为 `workspace.py:170` 和 `workspace.py:288`。

`.github/workflows/tests.yml:144` 的单元测试步骤执行 `pytest tests/unit -v`，没有排除这份测试；Python 3.11、3.13 均在矩阵内。正常代码 PR 进入该步骤后，这些失败会使 unit tier 失败，`Test Summary` 在约第 469 行也明确拒绝失败的 tier。不能以“只是旧测试”为由忽略。本次未读取远端分支保护配置，因此不声称已核实 GitHub 合并按钮的实际限制。

## 已完成的证据核验

- [x] 工作区 HEAD 与反馈链接的提交一致，排查开始时没有未提交改动。
- [x] 阅读 `src/qwenpaw/app/chats/api.py:908`、旧夹具所在测试文件、真实 Workspace、异步配置函数、BackendExecution 的调用签名及 CI 配置。
- [x] 本地 Python 3.13.10，以独立 `QWENPAW_WORKING_DIR` 运行 `tests/unit/app/chats`：**352 passed / 7 failed，exit 1**；七项均首先报缺少 `agent_id`。
- [x] 对照实验：只在独立测试进程内替换为基线 `get_chat` 函数，未修改源码或测试文件；目标文件 **38 passed，exit 0**。出现一条 pytest 模块预导入警告，不影响对照结论。
- [x] 对比基线 diff：配置读取方式、runtime 属性以及 backend 参数传递方式均发生变化，旧测试没有同步。

本地原始日志（工作区临时产物，不要求提交）：

- `tmp/chat-history-review-20261027/chats-baseline.log`
- `tmp/chat-history-review-20261027/base-control.log`

诊断阶段没有执行全部 `tests/unit` 或远端 CI；修复阶段的全量尝试见末尾，全量通过不是当前结论。对照实验只用于定位，不是修复后的验收方式。

## Global Constraints

- 保留现有 38 项测试，不删除、skip、xfail 或降低消息、状态、调用次数等原有断言。
- `SimpleNamespace` 继续只提供明确声明的字段，不改成可以自动生成任意属性的宽松 MagicMock。
- 所有进入配置读取路径的用例使用 AsyncMock，禁止依赖真实用户的 agent 配置或已安装 Harness 插件。
- 默认不改 `api.py`、Workspace、SDK、插件 ZIP 或 CI；若独立测试揭示真实功能缺陷，交由功能 agent 单独修复并记录原因。
- 保持 `await load_agent_config_async(workspace.agent_id)`。该 helper 已通过 `run_sync_io()` 读取配置；不能退回同步 `workspace.config` 来迁就测试，也不把整个路由放进线程。
- 不新增厂商登录、网络请求或进程启动；本任务是路由契约测试迁移。

## Review Focus

以下检查直接补到已有用例，不另建重复测试文件：

1. 配置按当前 agent ID 异步读取，并将 backend 和非空 settings 传给正确 runtime。
2. 第三方恢复成功后重新读取 session，返回恢复后的消息。
3. 恢复失败时确认恢复函数确实执行并抛错，随后返回已有结果，避免“缺少 runtime 属性也被 except 吞掉”的假通过。
4. 原生后端不恢复；已有消息的投影、状态和旧格式 fallback 的断言全部保留。
5. 聊天不存在的 404 早于配置读取；邻近的 PawApp 所有权和附件历史测试不受影响。

## Task 1：迁移同一文件内的夹具与七项历史测试

**Files:**
- Modify: `tests/unit/app/chats/test_api_project_dirs_and_crud.py`，约第 650 行开始的聊天历史区域。
- Reference only: `src/qwenpaw/app/chats/api.py`、`src/qwenpaw/config/config.py`、`src/qwenpaw/runtime/backends/execution.py`。

**Interfaces:**
- 配置读取：`await qwenpaw.config.config.load_agent_config_async(agent_id)`，返回具有 `backend` 和 `backend_settings` 的对象。
- 恢复调用：`await workspace.backend_runtime.hydrate_session(backend_id, *, session_id, user_id, channel, settings=None)`；当前路由将 backend ID 作为第一个位置参数传递。
- 新的局部 fixture：`chat_config_loader(monkeypatch) -> AsyncMock`，默认返回 `SimpleNamespace(backend="qwenpaw", backend_settings={})`。
- 工作区 helper：`_chat_workspace(*, agent_id="agent-x", status="idle")`，只提供 `agent_id`、`task_tracker.get_status` 和 `backend_runtime.hydrate_session`，不再接收 backend 参数或提供旧 config/runtime 字段。

- [x] **步骤 1：确认 RED 基线。** 若 HEAD 仍为核验版本，可使用已保存的失败结果；若已变化，重新运行目标文件，确认仍为 31 通过、7 失败，不把其他失败混入本任务。
- [x] **步骤 2：新增局部配置 fixture 并迁移 helper。** 使用 `monkeypatch.setattr("qwenpaw.config.config.load_agent_config_async", mock)`。路由在函数内部导入该函数，不能 patch 一个路由模块上不存在的同名全局。fixture 只由需要它的历史测试显式请求，不影响整个文件的其他路由。
- [x] **步骤 3：七项失败测试均接入 fixture。** 原生后端用默认配置；两项第三方恢复用例通过 mock 返回的配置设置 `backend="claude_code"`。该 ID 继续作为通用第三方后端测试值，不需要安装实际插件。删除 `_chat_workspace(backend=...)` 的旧用法。
- [x] **步骤 4：迁移全部 runtime 引用和调用断言。** 将该区域内的 `harness_runtime` 改为 `backend_runtime`，包括异常 side_effect。恢复调用断言首参改为位置参数 `"claude_code"`，其余身份字段保持原值。
- [x] **步骤 5：在原用例中补足接口证据。** 七项进入配置读取的用例均断言 `chat_config_loader.assert_awaited_once_with(workspace.agent_id)`。第三方成功用例用非空 settings（如 `{"binary_path": "/test/bin/harness"}`）验证透传；保留原 session 两次读取和消息断言。失败用例断言恢复确实 await 一次、session 仅读取一次，并保留空消息断言。404 用例接入 fixture 后断言配置未读取。
- [x] **步骤 6：核对下表中的原行为全部保留。** 不用修改生产函数或将其换回基线来获得 GREEN。

| 现有测试后缀（均以 `test_get_chat_` 开头） | 必须保留的行为 |
| --- | --- |
| `projects_context_messages` | 正确读取 session 身份、返回 user 消息、状态 running、不调用恢复 |
| `without_state_returns_empty_history` | 原生空 session 返回空消息和 idle |
| `hydrates_third_party_backend_sessions` | 参数透传、恢复一次、重新读取 session、返回恢复后的消息 |
| `swallows_failed_third_party_recovery` | 模拟真实恢复调用抛错，接口仍返回空消息 |
| `skips_hydration_for_native_backend` | 原生后端不调用恢复，session 只读取一次 |
| `falls_back_to_legacy_memory` | 2.x state 无法解析时仍从 1.x memory 恢复消息 |
| `ignores_empty_legacy_memory` | 空旧格式 memory 返回空消息 |

## Task 2：验证、独立检查与关闭清单

**Files:** 同一测试文件及本计划的完成记录；默认没有功能文件变更。

- [x] **步骤 1：运行目标文件。** `python -m pytest tests/unit/app/chats/test_api_project_dirs_and_crud.py -q`，预期 **38 passed，exit 0**。
- [x] **步骤 2：运行聊天模块。** `python -m pytest tests/unit/app/chats -q`，在当前用例集合下预期 **359 passed，exit 0**；包含 PawApp 所有权及附件历史测试。
- [x] **步骤 3：独立检查测试差异。** 由未编写测试的功能 agent 或 reviewer 对照生产调用链检查：断言未削弱、异步配置 mock 的位置正确、恢复失败不会假通过、没有真实配置 I/O；无功能缺陷就不修改生产代码。
- [x] **步骤 4：运行仓库对该文件适用的格式/lint 检查和 `git diff --check`。** 不绕过提交钩子，也不修改测试发现配置。
- [ ] **步骤 5：完成合并前 CI 门禁。** 本地可运行 `python -m pytest tests/unit -v`；最终以 PR 的 Python 3.11、3.13 unit jobs 和 Test Summary 成功为准。若本地受环境限制，明确记录未运行或失败原因，不能把聊天模块通过写成全量通过。远端推送或触发 workflow 按用户授权执行。
- [ ] **步骤 6：记录最终差异、命令结果及提交号。** 只有修复后的当前生产代码与迁移测试共同通过，且 PR 门禁成功，才关闭此合并阻塞项。

运行本地测试时，将 `QWENPAW_WORKING_DIR` 指向独立临时目录。本次复现使用 `.venv-test/bin/python`；CI 使用其已安装项目测试依赖的 `python`。本任务不要求安装 Codex/Qoder SDK。


## 执行记录（2026-10-27）

- 测试子 agent 独立完成夹具与断言迁移；另一位子 agent 对照真实生产接口审查，规格通过、质量通过，无需要修改功能代码的问题。
- 所有 38 项原测试保留。独立 AST 检查确认：30 项非历史测试未变，原有 81 项 assertion/assert_* 检查在对应接口迁移后全部保留，新增 10 项配置与恢复调用检查。
- 目标文件：38 passed，exit 0。聊天模块：359 passed，exit 0。实际 pre-commit 格式及静态检查全部通过；fixture 使用显式公开名和不同的 Python 函数名，未禁用 lint。
- 全量 `tests/unit -v` 已尝试，exit 2，收集阶段出现 38 个错误、5 个跳过。当前本地环境缺少 acp、nio、slack_bolt、questionary、textual、audioop 兼容包，并存在 reme.config.parse_action 导入不兼容。没有通过排除测试或宽松 mock 绕过这些错误。
- 本地日志：`tmp/chat-history-review-20261027/task1-target.log`、`task1-chats.log`、`final-chats.log`、`hooks.log`、`full-unit.log`。`final-chats.log` 对应最后一次自动格式化后的版本。
- 本次只修改测试文件与本计划，生产异步配置读取和后端执行逻辑保持原状。最终提交号在交付消息和本地执行记录中记录。
- **剩余合并门禁：** PR 的 Python 3.11、3.13 全量单测及 Test Summary 尚待远端验证；未推送或触发远端 workflow。因此步骤 5、6 的合并关闭条件保留未勾选，不能将本地局部修复通过等同于整条分支已可合并。
