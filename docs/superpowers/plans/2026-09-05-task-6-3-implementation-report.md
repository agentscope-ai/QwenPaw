# Task 6.3 检查点归属和恢复权限实现报告

## 结论与边界

已实现用户确认的多用户恢复语义：恢复创建新会话，原会话保持不变；文件只恢复明确勾选范围。新 ChatSpec 和 PostgreSQL conversation 归属元数据通过现有 `ChatManager.create_chat` 回调创建，不复制或伪造旧 run/events，也不修改、删除旧会话或迁移数据库结构。

页面历史的真实消费路径是 `GET /chats/{id}`（`src/qwenpaw/app/chats/api.py`）读取 SafeJSONSession 的 `AgentState.context`，前端 `sessionApi` 调用 `chatApi.getChat` 并转换消息。PG run persistence 是事件/审计旁路，并非当前页面历史读取源。因此新会话的运行状态和页面丰富回放都来自检查点中的完整 SafeJSONSession JSON。

本报告只覆盖实现与自动验证。独立评审、双角色浏览器验收由主流程完成，未经该验收不能标记 Task 6.3 全部完成。

## 已实现行为

- 多用户 `user_id` 只取认证 Actor，不信任客户端请求体。
- 所有多用户角色的会话检查点列表和恢复都绑定本人创建者身份；owner/collaborator 的 Agent 草稿权限不会扩大为其他用户私人会话读取权。
- 权限同时匹配可信 `agent_id`、commit、源 `session_id`、channel 和创建者。
- 个人快照只从 Agent session 根注入当前用户当前会话 JSON，不扫描其他 session、资料库或文档。
- 共享 Agent 根先排除整个 `sessions/`，再仅注入可信当前会话；图谱先按创建者过滤再分页，GC 也仅处理可信创建者的 refs。
- 共享仓库 reset 只允许完整管理者 owner；collaborator 无权清空共享检查点，个人运行仓库仍可重置本人数据。
- 多用户应用恢复生成新 session/chat UUID，将检查点 JSON 写到新 SafeJSONSession 路径，再通过现有 ChatManager 创建 ChatSpec 和 PG conversation 归属元数据。
- 原 session JSON、原 ChatSpec、原 PG conversation/runs/events 均保持不变。
- 预览只读取检查点并计算文件/记忆范围，不创建 session 或 ChatSpec。
- ChatManager 元数据 callback 失败时，补偿删除本次新建 ChatSpec 和 session JSON，不暴露可继续的半成品。
- 文件恢复使用独立路径，不生成伪旧 session；仅恢复勾选文件。记忆勾选仍恢复 `MEMORY.md`/`memory/`。
- 成功响应返回 `new_session_id` 和 `new_chat_id`，前端导航到 `/chat/{new_chat_id}`；Legacy 无新标识时保持原行为。
- `/status` 以独立 `restore_mode` 明确声明 `new_chat`/`in_place`；前端不再从文件 `scope` 猜测恢复语义，旧后端缺字段时安全回退为原位提示。
- 旧无可信归属或缺失/损坏 session blob 的检查点明确拒绝，不假成功；单用户 Legacy 保留原就地恢复语义。
- 多用户损坏 blob、非法文件选择等 `CheckpointError` 统一映射为 HTTP 400，不泄漏为 500。

## TDD 记录

- 初始恢复授权 RED：3 个用例因未绑定 `session_id/channel` 失败；增加联合授权后转绿。
- 私人会话 RED：owner 可恢复 collaborator 创建的会话检查点；改为所有多用户角色均匹配本人创建者后转绿。
- 跨根恢复 RED：缺少 `restore_session_copy`；实现 shadow Git 额外 session blob 和新 session 原子写入后转绿。
- query RED：跨根图谱 query 为 `None`；改从可信 Agent session 根读取后转绿。
- 文件范围 RED：旧路径在个人目录生成伪旧 session；改为仅文件/记忆恢复事务后转绿。
- 真实 JsonChatRepository + ChatManager 验证预览零写入，以及 callback 失败清理新 JSON/ChatSpec。
- 共享根隔离 RED：快照树包含另一用户 session；统一排除 `sessions/` 后仅注入当前会话，转绿。
- 分页隔离覆盖“其他用户较新记录不能挤掉本人结果”；HTTP 层覆盖损坏 session 返回 400；reset 覆盖 collaborator 前置拒绝。

## 最终验证

```powershell
.venv/Scripts/python.exe -m pytest "tests/isolation/test_checkpoint_permissions.py" "tests/unit/checkpoints" "tests/unit/app/routers/test_checkpoints_router.py" -q
```

结果：`112 passed, 3 skipped in 45.49s`，退出码 0。

```powershell
npm --prefix "console" run test:run -- "src/api/modules/checkpoints.test.ts" "src/pages/Agent/Checkpoints/graphLayout.test.ts" "src/pages/Agent/Checkpoints/RestoreModal.test.tsx"
```

结果：3 个测试文件、9 个测试通过，包含成功导航、失败不跳转及 Legacy 无新 ID 保持原行为，退出码 0。

第 2 轮恢复模式定向回归：后端 router `12 passed`；前端 `restoreMode.test.ts` 与 `RestoreModal.test.tsx` 共 `5 passed`。覆盖 Legacy `agent_workspace` 仍返回 `in_place`、多用户明确返回 `new_chat`，以及未知字段不误导为新会话。

```powershell
npm --prefix "console" run build
```

结果：TypeScript、Vite 构建和 Monaco CSS 校验通过，退出码 0；存在项目既有 circular chunk、动态/静态 import 和大 chunk 警告。

Ruff 未运行：当前 `.venv` 未安装 Ruff，未改变环境进行全局安装。

## 本轮实际修改

- `src/qwenpaw/app/routers/checkpoints.py`：联合授权、全角色私人创建者隔离、新会话编排、失败补偿、新标识。
- `src/qwenpaw/checkpoints/repository.py`：受控外部 session blob 写入 shadow Git tree，Git stdin 支持 bytes。
- `src/qwenpaw/checkpoints/policy.py`：快照统一排除共享根下整个 `sessions/`。
- `src/qwenpaw/checkpoints/service.py`：可信 conversation 根、跨根 session 快照/复制、仅文件与记忆恢复。
- `src/qwenpaw/checkpoints/models.py`：恢复结果增加新 session/chat 标识。
- `src/qwenpaw/checkpoints/runtime.py`：个人自动快照绑定 Agent session 根。
- `src/qwenpaw/checkpoints/hooks.py`：query gate 与个人自动快照使用同一 service（上一轮本任务改动）。
- `tests/isolation/test_checkpoint_permissions.py`：真实 Git/session/ChatSpec 隔离、分页、HTTP 映射与补偿测试。
- `tests/unit/app/routers/test_checkpoints_router.py`、`tests/unit/checkpoints/test_checkpoint_basic.py`、`tests/unit/checkpoints/test_checkpoint_hooks.py`：权限、Git bytes 和 gate 回归。
- `console/src/api/types/checkpoints.ts`、`console/src/pages/Agent/Checkpoints/index.tsx`、`console/src/pages/Agent/Checkpoints/restoreMode.ts`、`restoreMode.test.ts`、`console/src/pages/Agent/Checkpoints/RestoreModal.tsx`、`RestoreModal.test.tsx`、中英文 locale：明确恢复模式、新标识类型、新会话提示、成功/失败/Legacy 导航行为测试。

`src/qwenpaw/checkpoints/restore.py` 在当前 Git 工作树中无差异；本轮复用了其中既有恢复事务实现，没有把它列为本轮代码修改。若审查包此前显示该文件有变化，应以审查包相对基线为准单独纳入复审。

接手前已有的初步归属、个人目录、作用域和页面作用域展示不归功于本轮新增实现。

## 剩余风险与未验收项

1. 浏览器双角色验收由主流程执行，本报告不宣称页面验收完成。
2. `record_chat_created` 先注册 PG conversation，再记录 Agent 历史；第二步失败时补偿会移除 ChatSpec/session，使新会话不可继续，但 PG 可能留下本次新 conversation 元数据孤儿。现有 callback 没有跨 JSON/PG 事务或仅删除本次新记录的接口；本轮未新增数据库删除路径。需独立评审决定是否接受不可见孤儿或另行设计事务 outbox。
3. RestoreModal 已有组件点击行为测试和 TypeScript 构建覆盖，仍需浏览器验收确认实际页面切换。
4. 工作树存在大量既有脏修改。本轮未创建分支、未 stage/commit/reset、未重启 18089 服务；所有真实恢复仅发生在 pytest `tmp_path` 新数据。

## 2026-09-06 最终评审修复波

本节覆盖最后四项评审意见及其直接回归，取代上文对应的旧验证结果。四项代码修复和自动验证已完成；浏览器双角色验收仍由主流程执行，18089 服务未由本实现者重启。

### 修复结果

1. 每次构建快照树都从 shadow Git 索引移除旧 `sessions/` 缓存条目，然后仅注入本次可信源会话；不删除工作区 session 文件。A→B→A 连续快照的三棵树均只含各自会话。新会话文件恢复和 Legacy 文件恢复构造安全快照时都显式捕获恢复前的可信源 session，不再依赖残留索引。
2. RestoreModal 预览/应用和页面手动 snapshot 请求重新携带所选节点的 `user_id`；请求类型保留可选字段以兼容旧调用。多用户服务端仍只信任认证 Actor；Legacy 的非空会话身份贯穿真实 snapshot、preview、原位 restore。前端用真实 `checkpointsApi` 序列化，在 request 边界校验身份，不再 mock 整个模块返回成功。
3. `restore_copy_transaction` 由当前 asyncio 任务持有，嵌套会话复制、文件恢复、ChatManager 元数据 callback 和失败补偿共享同一维护锁。事务关闭 query gate，复用 WorkspaceMutationGuard 暂停 cron、等活动任务完成，在补偿结束后恢复 cron 和 gate。真实 TaskTracker 回归证明回调挂起期间第二次恢复及 gate 协作写入均不能执行；回调失败或取消后并发写入不会被回滚覆盖。同步文件线程执行期间取消也会等待结果并回滚后才释放 gate。
4. 新会话恢复要求 `agent`/`state` 为对象，显式存在 `context`，并通过页面同款 `AgentState.model_validate` 验证完整运行状态。合法 `context: []` 仍可恢复；丰富 tool_result 历史按原始完整 JSON 保留并通过真实消费者模型读取。缺 agent/state/context、非法 context、非法嵌套 tool_context 均拒绝，且不生成目标文件。仅含旧 `agent.memory` 而无有效 `agent.state.context` 的检查点不支持多用户新会话复制，会明确返回缺失/无效状态；本波未迁移格式，Legacy 原位恢复路径保持原语义。

### TDD 与自查证据

- 后端首轮定向 RED：`10 failed`，分别为持久索引夹带另一用户 session、8 种非法状态未拒绝、cron 未暂停；对应修改后 `10 passed`。
- 前端 RED：RestoreModal 真实请求缺 user_id 导致 3 个点击流程失败；页面 snapshot 请求体缺 `legacy-user` 导致 1 个失败。修复后两文件 `4 passed`。
- 清索引后的关联回归：安全快照参数测试先出现 Legacy 分支 `1 failed, 1 passed`（安全 ref 无 session blob），显式注入可信源会话后通过。
- 事务取消自查 RED：同步文件恢复中取消后文件残留 `checkpoint` 而非恢复前 `current`；保留线程结果并锁内补偿后，取消/回调并发定向 `3 passed`。
- 原先两处成功恢复 fixture 实际不符合 AgentState（缺 Msg.name、使用不存在的 tool_use、context 直接放字符串）；已修为真实模型结构，保留对原会话不变、丰富历史、选择文件范围的断言，未放宽生产校验。

### 最终自动验证

```powershell
.venv/Scripts/python.exe -m pytest "tests/isolation/test_checkpoint_permissions.py" "tests/unit/checkpoints" "tests/unit/app/routers/test_checkpoints_router.py" -q
```

结果：`128 passed, 3 skipped in 69.30s`，退出码 0。所有真实 Git/session/文件恢复均使用 pytest 临时目录。

```powershell
npm --prefix "console" run test:run -- "src/api/modules/checkpoints.test.ts" "src/pages/Agent/Checkpoints/graphLayout.test.ts" "src/pages/Agent/Checkpoints/RestoreModal.test.tsx" "src/pages/Agent/Checkpoints/restoreMode.test.ts" "src/pages/Agent/Checkpoints/index.test.tsx"
npm --prefix "console" run build
```

前端 `5 files / 12 tests passed`，退出码 0；测试环境有既有 jsdom pseudo-element getComputedStyle 提示。TypeScript、Vite build 和 Monaco CSS 校验通过，退出码 0；Vite 构建 52.13s，仍有既有 circular chunk、动态/静态 import、大 chunk 警告。代码范围 `git diff --check` 通过。

### 本修复波实际修改路径

- `src/qwenpaw/checkpoints/repository.py`：清除旧 session 索引缓存。
- `src/qwenpaw/checkpoints/service.py`：维护事务、AgentState 校验、安全快照 session 捕获、取消时文件补偿。
- `src/qwenpaw/checkpoints/restore.py`：Legacy 文件恢复安全树显式纳入可信当前 session。本波开始修改此文件，上文“无差异”仅适用于此前轮次。
- `src/qwenpaw/app/routers/checkpoints.py`：新会话完整编排置于维护事务，异常及取消时执行补偿。
- `tests/isolation/test_checkpoint_permissions.py`：连续快照、结构校验、真实 Legacy 请求链、安全快照、真实 TaskTracker 与并发/取消回归，修正真实状态 fixture。
- `console/src/api/types/checkpoints.ts`：恢复和快照类型保留 Legacy user_id。
- `console/src/pages/Agent/Checkpoints/RestoreModal.tsx`：保留节点身份。
- `console/src/pages/Agent/Checkpoints/index.tsx`：保留所选会话身份。
- `console/src/pages/Agent/Checkpoints/RestoreModal.test.tsx`：真实 API 序列化契约与恢复导航测试。
- `console/src/pages/Agent/Checkpoints/index.test.tsx`：新增手动快照请求身份测试。
- `docs/superpowers/plans/2026-09-05-task-6-3-implementation-report.md`：本节报告。

实现采用现有维护锁、WorkspaceMutationGuard 和 AgentState 消费模型，避免重复调度/校验机制；事务封装仅覆盖本任务，未扩展通用文件工具沙箱。没有新增依赖、DB 删除/迁移/outbox，也没有修改、删除既有用户数据。

剩余风险仍为既定 Minor：元数据 callback 第二步失败可能留下不可见 PG conversation 孤儿。浏览器双角色验收及服务更新待主流程执行；不能据本报告宣称全部产品验收完成。

## 2026-09-06 浏览器集成门控修复

主流程真实浏览器验收发现普通成员自己的 snapshot 在进入检查点路由前即收到 403。原因是 `allowed_agent_roles_for_request` 把 `/workspace/checkpoints` 写请求归入通用 `/workspace` 配置写权限，只允许 owner/collaborator，阻断了 USER 已有的个人检查点策略。

本波只增加八个明确 `(method, path)` 入口例外：POST snapshot、restore/preview、restore、gc/preview、gc；PATCH auto、gc/settings；DELETE 检查点根。例外在正常 Agent 成员授权内允许可使用角色进入检查点路由，最终仍由可信角色选择私人/共享根、认证 Actor 限定创建者。没有按路径前缀泛放宽 workspace 写入；未知检查点路径、错误 HTTP 方法及其他工作区配置写入仍不允许 USER。

真实 HTTP 测试同时发现 `/api` 旧别名 reset 在载入 `agent_access` 之前按默认 owner 判断，导致协作者实际可重置共享仓库。现在该别名缺少可信角色时先调用现有 `get_agent_for_request` 授权，再执行既有共享 reset 限制；已具备角色的 scoped 入口不重复解析。两个别名都拒绝 collaborator reset，并验证 owner 检查点 ref 保持不变。

### 测试证据与边界

- RED：新集成文件 `3 failed, 13 passed`；两个别名 USER snapshot 返回 403，旧 `/api` 别名 collaborator reset 返回 200。
- GREEN：`tests/isolation/test_checkpoint_http_access.py` 最终 `16 passed in 5.01s`，退出码 0。
- 集成测试挂载真实 `create_agent_scoped_router`、AgentContextMiddleware 和检查点路由，执行真实 `authorize_agent_request`、AgentMembershipService、scope resolver、service、Git、JsonChatRepository；仅替换身份/配置与 PostgreSQL 数据访问边界，未 monkeypatch `_service`、授权门控或检查点业务处理返回成功。
- 两个别名 `/api` 和 `/api/agents/{id}` 都覆盖普通成员伪造 user_id 创建本人快照、仅本人图谱、本人 preview/restore、auto/GC/settings/reset，以及 owner 检查点不受个人 reset 影响。恢复校验源会话仍为 after、新会话为检查点 before。
- 他人 preview 返回 403，并核实该请求已经获得真实 USER Agent 角色，拒绝来自下游检查点归属策略。撤销及仅有历史只读访问的成员都不能进入检查点 GET/write/reset；配置写权限没有扩大。
- Windows Git 对深层临时 ref 路径有限制，测试使用 pytest `tmp_path_factory` 分配短临时目录和短 Agent ID；所有真实恢复仍只发生在新建临时数据，没有修改 Git 配置、系统环境或生产数据。

```powershell
.venv/Scripts/python.exe -m pytest "tests/isolation/test_checkpoint_permissions.py" "tests/isolation/test_checkpoint_http_access.py" "tests/isolation/test_agent_scoped_routes.py" "tests/unit/checkpoints" "tests/unit/app/routers/test_checkpoints_router.py" "tests/unit/app/routers/test_memory_files_scope.py" "tests/unit/app/test_agent_context_project_dir.py" -q --tb=short
```

完整检查点及相关 Agent 前置门控回归：`193 passed, 3 skipped, 1 warning in 63.61s`，退出码 0。警告为现有 Starlette TestClient 的 httpx 弃用提示。随后补强新会话 before 状态断言并定向重跑集成文件，16 项全部通过。代码 `git diff --check` 通过。本波无前端变化，沿用上一修复波 12 项前端测试及完整 build 成功结果。

本波实际修改仅为：`src/qwenpaw/app/agent_context.py`、`src/qwenpaw/app/routers/checkpoints.py`、新增 `tests/isolation/test_checkpoint_http_access.py`，以及本报告。复用现有 Agent 授权和检查点策略，保持职责边界，未扩大通用沙箱、数据库或其他功能范围。

服务未由本实现者重启，未提交/创建分支，未恢复或删除既有用户数据。独立只读复审与重启后的普通成员浏览器验收仍待主流程执行；既定 PG 不可见孤儿 Minor 保留。

## 主流程部署与浏览器实测（2026-09-06）

- 主流程复跑完整后端命令：193 passed、3 skipped、1 warning，64.62 秒，退出码 0；复跑五个前端检查点测试文件：12 passed，退出码 0。前端既有 jsdom pseudo-elements 提示仍存在。
- 最终四项修复和 HTTP 入口修复均已通过独立限定评审。
- 管理员真实 Chrome：原会话 `0a01774d-e392-45c8-a7ad-5479c47b548a`，检查点 `8a7505d69840bfac2ad40c60350894aa39948e22`，恢复新会话 `7850895d-4174-4e28-ab49-a24ef928dbcb`。新会话消息、持久化 original_id 和元数据与检查点一致，原会话保留后续回复；实际 DOM 与刷新后内容均通过。历史适配器每次读取会生成新的顶层传输 id，因此比较只忽略该字段，不忽略其他内容。
- 服务于 02:03 在原目录加载 HTTP 修复，端口仍为 18089，PID 36812。重启前管理员和普通用户均无运行中会话。
- 普通用户真实 Chrome：管理员检查点不在其图谱中，伪造管理员 user_id 预览返回 403。新建测试会话 `52dad802-a0dd-4d05-bf55-8cbe72b10588` 后，本人 snapshot 已通过授权门控，但 Git update-ref 深目录失败，故普通用户恢复尚未验收通过。
- 根因继续隔离到本机默认 Git for Windows 2.49.0 的长路径重命名问题；仅启用 longpaths 仍失败。已发现本机现有 Git 2.53.0.windows.3，尚未变更服务的 Git 选择或系统环境。Task 6.3 不标记完成。
- 所有真实测试只创建 TASK63 标记的新会话和快照，均保留供核对，没有恢复、删除或迁移既有用户数据。测试脚本位于 `tmp/task-6-3-browser-restore.py` 和 `tmp/task-6-3-browser-inspect.py`。

本任务不包含通用聊天切换、个人资料库泄漏或文件工具沙箱修复；不能用本轮检查点测试结果替代这些功能的验收。

## Windows 深目录兼容修复与隔离验证（2026-09-06）

使用 systematic-debugging、test-driven-development 与 verification-before-completion 技能，先定位 Git ref 创建和重命名的实际失败层，再进行 RED/GREEN 验证。默认 Git 仍为 `D:/developer/Git/cmd/git.exe`（2.49.0.windows.1）；只在测试命令中显式选择已安装的 2.53.0.windows.3，没有下载依赖、更改 PATH、系统配置、服务启动脚本或服务进程环境。

### 本波改动范围

- `src/qwenpaw/checkpoints/repository.py`：共享 Git 子进程命令增加 `-c core.longpaths=true`，init 也复用该命令构造；默认可执行文件仍为 `git`。reset 仅在 Windows 将原绝对 `state_dir` 转为扩展路径表示后传给既有 `shutil.rmtree`，保持删除整个 checkpoints 状态目录的原语义，不改成 shadow.git，不增加删除入口，不改变角色或路径验证。非 Windows 保持原 Path 入参。
- `tests/conftest.py`：增加显式 `--checkpoint-test-git` 选项及 opt-in fixture；仅对引用该 fixture 的测试，通过真实 `subprocess.Popen` 启动入口替换 Git 可执行文件。`subprocess.run` 与 GitBlobBatch 因而使用同一指定二进制，未模拟 Git 成功，也未更改 PATH；原 run spy 仍兼容。测试代码不硬编码本机用户名或 Git 安装目录。
- `tests/unit/checkpoints/test_checkpoint_long_paths.py`：新增真实 ref 路径超过 260 字符的 snapshot、graph/read、文件恢复、会话复制、reset 闭环，以及非 Windows reset 分支回归。源会话持续保留 after，新会话为 before；删除入口用 samefile 验证仍是原 state_dir，且 workspace 相邻普通文档保留。
- `tests/isolation/test_checkpoint_http_access.py`：撤除上一节短临时目录 workaround，恢复自然 pytest tmp_path，并显式引用测试 Git fixture；两个真实 HTTP 路由别名继续覆盖成员自己的完整检查点操作、他人归属拒绝、collaborator 共享 reset 拒绝及撤销成员拒绝。
- 本报告追加上述记录。隔离诊断脚本 `tmp/checkpoint-longpath-probe.py` 保留用于核对；其写实验仅发生于 pytest 临时目录。

### TDD 与最终验证

1. 新版 Git 未加 longpaths 时，深目录用例 RED：snapshot 无法创建 ref。
2. 命令级 longpaths 后，真实 snapshot/read/restore 通过；恢复自然深 HTTP 目录又暴露 Python reset 无法遍历 Git 已创建的长 ref，HTTP 中两项 reset 失败。
3. 扩充深目录 reset 及相邻数据保留测试后，RED 为 1 failed、1 passed；加入仅改变路径表示的修复后，深目录与 HTTP 定向 18 passed。
4. 统一 Popen 测试入口后，下列最终全套结果为 **195 passed、3 skipped、1 warning，65.37 秒，退出码 0**。warning 仍是既有 Starlette/httpx 弃用提示。

```powershell
.venv/Scripts/python.exe -m pytest "tests/isolation/test_checkpoint_permissions.py" "tests/isolation/test_checkpoint_http_access.py" "tests/isolation/test_agent_scoped_routes.py" "tests/unit/checkpoints" "tests/unit/app/routers/test_checkpoints_router.py" "tests/unit/app/routers/test_memory_files_scope.py" "tests/unit/app/test_agent_context_project_dir.py" --checkpoint-test-git "C:/Users/nidi/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe" -q --tb=short
```

随后故意不传该选项运行同一深目录用例，默认旧 Git 仍返回 update-ref `couldn't set`：**1 failed、1 deselected，退出码 1**。此负向验证明确说明代码修复不等于旧 Git 已兼容；没有跳过或缩短目录掩盖问题。Git for Windows 的相关修复见 [PR 5550](https://github.com/git-for-windows/git/pull/5550)，其重命名缓冲区由 MAX_PATH 改为 MAX_LONG_PATH。本机旧版与新版的实际测试结果是本次部署判断依据。

本波没有前端改动，沿用上节已复跑的 5 文件 12 项前端测试，以及此前 build 成功证据。限定代码 `git diff --check` 通过。生产代码保持 KISS：仅共享命令选项及既有删除入口的路径表示，没有自动选择 Git、迁移、短路径映射或新兼容层。

### 未完成的部署条件

实现者未重启服务、未修改真实服务数据、未提交或创建分支。服务仍使用旧 Git，普通成员真实浏览器恢复尚未通过；需要用户明确授权服务进程改用已有新版 Git，再由主流程独立复审、部署与真实浏览器复验。非 Windows 分支在本机通过模拟平台分支验证，未声称完成 Linux/macOS 实机测试；UNC 长路径未进行真实网络共享验证。既定 PG 不可见孤儿 Minor 继续延后。

## 最终授权部署与验收结果（2026-09-06）

以上部署待办已完成。用户明确确认仅调整服务级 Git 选择并重启；主流程检查管理员/普通用户无运行中会话后，重启原服务。`tmp/start-18089.ps1` 仅在 Start-Process 期间前置已安装 Git 2.53 cmd 目录，通过 finally 还原调用进程 PATH；不修改系统或用户持久环境变量。默认终端 Git 仍为 `D:/developer/Git/cmd/git.exe`。端口 18089、原数据根保持不变，服务 PID 30476，最终登录页 HTTP 200。

本轮新鲜验证：

- 深目录与真实 HTTP 检查点集成：18 passed in 8.48s，退出码 0，显式测试 Git 2.53。此前完整 195 passed、3 skipped 及前端 12 passed 记录仍保留；本轮没有前端源代码改动。
- 普通用户真实 Chrome 全流程 PASS：源会话 `786580e7-9b49-4137-9010-0d0168d6c397`，快照 `b75bdef3826da552b02627a181e71082fc431dd6`，新会话 `d659b2b5-bc65-48b7-8321-4a5abe3babac`。原会话保留 AFTER，新会话仅包含快照 BEFORE，实际页面和刷新后均一致，完整回放比较通过。管理员检查点不出现在普通用户图谱中，伪造管理员身份预览返回 403。
- 管理员真实 Chrome 全流程 PASS：源会话 `b0e171d6-79b2-4dd1-bbe8-40aecdf9df45`，快照 `4f816edae3be6196450c3e3b8477ff470bc53c27`，新会话 `7370bd4a-ca84-4ca6-9b17-0f423921c780`。同样验证原会话不变、新会话回放一致、跳转正确、刷新后保持。
- 浏览器未勾选文件恢复，避免影响原有文档；明确选择文件及相邻文件保留由真实临时目录 Git 测试验证。所有 TASK63 测试会话和快照保留，没有删除或迁移既有用户资料。

结论：Task 6.3 已完成实现与本轮验收验证，交付用户验收，不推进阶段 7。已知非阻塞限制仍是 callback 第二步失败可能留下不可见 PG conversation 元数据孤儿；JSON/PG 交集读路径不暴露可继续的半成品，未新增数据库删除/迁移机制。本结论不覆盖通用聊天切换或个人资料库泄漏问题。
