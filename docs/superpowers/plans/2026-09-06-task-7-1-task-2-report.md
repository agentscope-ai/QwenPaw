# Task 7.1 / 2 实施报告

状态：DONE_WITH_CONCERNS，交独立评审；未部署、未执行真实元数据初始化或真实供应商调用。

## 范围与基线

实现 PostgreSQL 模型元数据、用户授权、停用及显式启用治理；安全目录、私人会话覆盖、Console 运行选择及前端消费者。没有新增迁移、Secret 存储、文件授权真源或发布后台。

修改前内容位于 `.superpowers/task-7-1-task-2-baseline/`。最终实际 unified diff 为 `.superpowers/task-7-1-task-2.diff`；比较的是各文件本任务开始前内容，不是 HEAD。新增文件使用空基线。未提交、暂存、创建分支、工作树、reset 或 clean。未修改 18089 服务及其真实数据库、供应商配置或用户数据。

## 后端契约

`ModelGovernanceService(repository, provider_manager)` 提供 brief 中七个方法，另有 `preview_enforcement(actor, defaults)`。全部管理方法先检查 `MODELS_MANAGE`；普通目录要求 `PLATFORM_USE`。SQL 以已验证 Schema 限定，使用既有 `database_session` 事务。

- Provider UUID：`UUIDv5(NAMESPACE_URL, "qwenpaw:model-provider:" + runtime_provider_id)`。
- Model UUID：`UUIDv5(provider_uuid, model_key)`。
- `model_providers.name` 保存稳定运行键，展示名仅保存在 `base_url_metadata.display_name`；不写 URL、密钥、自定义头、生成参数或任意 Provider meta。
- 预览和登记使用同一安全投影，复用 Task1 `project_provider_info`；只登记当前已配置且运行 Provider 存在、模型存在的项目。
- 导入只更新展示名、能力和更新时间；不覆盖 status、不创建或修改 grants。
- `model_governance` 缺行表示 `enforced=false, version=0`。启用操作使用事务 advisory lock、版本检查、`system_setting_revisions`；过期版本返回 409。
- 用户、合法 Agent、platform grant 按 OR 合并；撤销一条不是 deny。Agent grant 额外检查真实 owner/public/未撤销成员关系。停用优先于所有授权，也适用于兼容阶段；管理员固有使用能力不需要 grant。
- 目录每次结合实时 Provider 模型与状态；数据库错误不能转为兼容放行。治理/目录/会话路由数据库故障返回 503 `model_authority_unavailable`。

管理接口均为管理员能力鉴权：

| 方法 | 路径 | 请求/结果 |
| --- | --- | --- |
| GET | `/model-governance/status` | `{enforced,version}` |
| POST | `/model-governance/import/preview` | 无请求体；返回安全模型数组 |
| POST | `/model-governance/import` | 无请求体；幂等登记，返回同一模型投影 |
| GET | `/model-governance/models` | 元数据数组，含 `status`,`provider_status`,`capabilities`,`user_grants` |
| PUT | `/model-governance/models/{id}/users/{user_id}` | `{enabled:boolean}`；目标用户必须存在且 active |
| PATCH | `/model-governance/models/{id}/status` | `{enabled:boolean}` |
| GET | `/model-governance/enforcement/preview` | `{uncovered_users,affected_defaults}`，用户名称及默认模型影响 |
| PUT | `/model-governance/enforcement` | `{enabled,expected_version,reason}` → `{enforced,version}` |

`user_grants` 的项目为 `{user_id,username,enabled}`，包含已撤销条目供管理员核验；界面“已授权用户”列只显示 enabled=true。不接受客户端 `created_by`。

普通消费接口：

- `GET /model-catalog?agent_id=...` → `{enforced,models:[{id,provider_id,provider_name,model,name,supports_image,supports_video,max_input_length,available}]}`。`agent_id` 可省略用于创建 Agent 前的用户目录；有 Agent 时经过现有 Agent 访问检查。
- `GET /model-catalog/default?agent_id=...` → 下面的会话模型响应格式；省略 Agent 表示安全平台继承回显。不存在任何默认时 `active_llm=null`；已配置但不可用的显式默认报错。
- 强制治理后普通用户 `GET /models` 返回 403；管理员原设置管理 API 保留，普通消费者已转安全接口。

## 私人会话与运行

`GET /chats/{chat_id}/model`、`PUT /chats/{chat_id}/model` 先检查当前用户是 owner，并检查 Agent。管理员角色不绕过私人会话边界。PUT 请求为 `{provider_id,model}`，或 JSON `null` 明确清除；空 body/空模型返回 422。

响应：`{active_llm,source,model_override,effective_max_input_length,locked}`，source 为 `conversation` / `agent` / `platform`，受信发布解析接口还支持 `publication`。

- PG：`with_user(actor.user_id).set_model_override(conversation_id, expected_agent_id=..., model_override_id=..., updated_at=...)`；单条 UPDATE RETURNING，WHERE 同时限定 owner、Agent 和非 deleted 状态，设置 RLS 当前用户。
- Legacy：`ChatManager.set_legacy_model_override` 在 Manager 锁内只更新受控 `ChatSpec.meta.model_override`，保留其他 meta；没有扩大公共 ChatUpdate，也没有 PG/JSON 双写。
- 切换规则为下一轮生效。正在执行的一轮保留已捕获槽位；不写 Agent 配置、不 reload Agent。
- 新会话 `requested_model` 是不可信候选，实际会话解析后校验并持久化，再进入 run。旧 `model_slot_override` 和伪造发布字段被拒绝；客户端字段不形成授权。
- 两条 Console 运行入口均调用服务端选择器，将真实 actor/Agent/槽位作为进程内对象交给 ConsoleChannel；builder 在初始化和实际构造模型前再次检查当前授权，并实际使用此槽位。环境模型名称也采用相同槽位。
- 优先级解析函数支持：可信发布 > 私人覆盖 > Agent 显式默认 > 平台默认；非法覆盖不会降级。
- PUBLIC Agent 不再被误认成发布锁定。当前没有实际共享应用发布解析服务；客户端共享应用上下文返回 `authority_unavailable`。`TrustedPublication` 是仅限服务端调用的明确边界，未新增第9阶段发布功能。
- 删除供应商、模型及已下载本地模型前检查平台/Agent 默认、PG 会话覆盖。存在无法解释的 publication 记录时保守 409 `publication_reference_unavailable`，不猜测 manifest 字段。不会删除元数据/历史记录作演示。

## 前端

- ModelSelector 使用安全目录与当前私人会话 GET/PUT；展示供应商区分、模型名称及能力/上下文提示，支持恢复默认。
- 当前用户、Agent、会话/草稿组成选择作用域；旧账号/旧会话异步响应不能覆盖当前状态。未持久化草稿只在首次请求提交候选，离开该作用域清除。
- Chat 的多模态能力、发送预检、限流建议均转当前会话实际模型；限流候选再按安全目录过滤，按钮复用同一私人会话选择路径。
- AgentModal、Settings/Agents 继承回显、Agent/Config 上下文消费转安全 API。普通用户聊天入口不再提供模型设置按钮/OAuth 管理操作。
- Settings/Models 治理面板提供初始化预览/登记、明确用户授予/撤销、已授权用户回显、停用、启用影响预览及明确提交；不会自动创建 platform grant 或自动启用。

## RED / GREEN

主要 RED 记录（均发生在相应实现前）：

```text
.venv/Scripts/python.exe -m pytest tests/unit/models/test_governance.py -q --tb=short
3 failed：缺少模型治理模块；后续2 failed覆盖兼容期停用与引用阻止删除。

.venv/Scripts/python.exe -m pytest tests/unit/models/test_repository.py -q --tb=short
1 failed：缺少数据库Repository。

.venv/Scripts/python.exe -m pytest tests/unit/app/chats/test_conversation_model.py -q --tb=short
1 failed：缺少专用override方法；后续Legacy真Manager用例复现ChatUpdate拒绝meta，再改专用锁方法。

.venv/Scripts/python.exe -m pytest tests/unit/models/test_resolution.py -q --tb=short
2 failed：缺少优先级/候选验证；后续1 failed：缺少构造前复核边界。

.venv/Scripts/python.exe -m pytest tests/isolation/test_model_catalog.py -q --tb=short
2 failed：管理路由不存在、旧覆盖可注入；后续RED验证null误作缺省、强制目录未限权、数据库故障500、本地删除未保护。

npm run test:run -- src/api/modules/modelCatalog.test.ts
1 failed suite：缺少安全API/作用域实现。

npm run test:run -- src/pages/Chat/ModelSelector/ModelSelector.test.tsx
1 failed：旧组件未显示安全目录及清除操作。

npm run test:run -- src/pages/Settings/Agents/components/AgentModal.test.tsx
1 failed,2 passed：普通角色管理读403导致继承默认回显丢失。

npm run test:run -- src/pages/Settings/Models/GovernancePanel.test.tsx
1 failed suite：缺少治理面板。
```

最终通过的验证：

```text
.venv/Scripts/python.exe -m pytest tests/unit/models tests/unit/app/chats/test_conversation_model.py tests/isolation/test_model_catalog.py tests/isolation/test_model_governance.py tests/unit/app/chats/test_manager.py tests/unit/app/routers/test_console_chat_reconnect.py tests/unit/app/channels/test_console_channel.py tests/unit/agents/test_effective_model.py tests/unit/agents/test_create_model_and_formatter_override.py tests/unit/app/routers/test_provider_context_window.py tests/unit/app/routers/test_providers_model_inheritance.py -q --tb=short
111 passed,1 warning,exit0（随后新增本地删除引用用例：HTTP文件6 passed,exit0）。

.venv/Scripts/python.exe .superpowers/task-7-1-task-2-test.py tests/integration/test_model_governance_repository.py -q --tb=short
1 passed,exit0，无Windows异常输出。

npm run test:run -- src/pages/Chat/ModelSelector/ModelSelector.test.tsx src/api/modules/modelCatalog.test.ts src/pages/Settings/Models/GovernancePanel.test.tsx src/pages/Settings/Agents/components/AgentModal.test.tsx
4 files,9 tests passed,exit0。

npx tsc -b --noEmit
exit0。

npm run build
exit0：tsc + 完整Vite生产构建 + verify:monaco-css通过；Vite构建1m19s。

.venv/Scripts/python.exe -m compileall -q <本任务后端模块>
exit0。
```

真实 PG 仅使用 `qwenpaw-pg` 中既有 `qwenpaw_test_migrations` 数据库的 `postgres_test_schema` 一次性 Schema。测试覆盖幂等导入保留授权/停用、审计版本冲突、管理员不能更新他人私人覆盖、Agent错配拒绝、清除、真实Agent grant使用权、无效用户拒绝及授权列表回显。连接信息未输出/持久化。

## 已证明基线失败与未验证项

1. `tests/unit/app/routers/test_console_chat_task.py` 四例失败：
   - `test_forked_task_reports_failed_when_worktree_cannot_be_finalized`
   - `test_forked_task_reports_failed_when_worktree_finalization_raises`
   - `test_forked_task_timeout_during_finalization_waits_for_commit`
   - `test_forked_task_stays_running_until_worktree_is_finalized`
   当前与专属基线均是 `_submit_forked_task → post_console_chat_task(payload,None) → _resolve_personal_library_references → get_actor(request) → request.state` 的 NoneType AttributeError，在模型准备前失败。`.superpowers/task-7-1-task-2-baseline-check.py` 仅受控import基线代码，未覆盖当前文件；复验4 failed,exit1。没有为此改生产容错。
2. `ChatPage.test.tsx` 已被原 `vite.config.ts` 显式exclude。专属配置强制执行后，旧Mock缺少 `useAgentStore.subscribe`，最小补安全API/Store契约后仍因缺 `isAgentHistoricalReadOnly` 导出导致16例未执行到目标行为。没有削弱断言或改公共测试配置；该整页套件未通过。真实ModelSelector组件3例及安全API/作用域2例已通过，不能据此声称整页端到端覆盖完成。
3. 最初PG迁移放在线程/活动测试loop内时出现Windows access violation诊断（早期退出虽为0仍不算清洁）。已改为同步fixture先迁移、仅在测试loop内管理engine，最终真实PG运行无此诊断。未更改系统或全局事件循环配置。旧诊断包括 `asyncio.base_events.call_soon_threadsafe/_do_shutdown`，后续出现 `tests/fixtures/postgres.py:async_url → subprocess`；没有操作真实库。专属测试启动器仅在子进程设置SelectorPolicy。
4. 保留既有Starlette/httpx弃用警告、jsdom伪元素getComputedStyle提示、Vite循环chunk/大chunk及动态静态混合导入告警；没有升级依赖。
5. 未运行真实供应商请求或浏览器实机初始化、未重启服务；实际发布后台/共享应用页面不存在，发布闭环留在阶段9。
6. 私人模型GET也采用owner边界，分享只读会话不会通过此接口读取模型；其页面可能展示模型不可用，但403不触发登录重定向。未扩大到分享会话模型披露。
7. 治理面板当前文案以中文为主，ModelSelector新增提示已加入zh/en资源；治理面板完整英文翻译尚未覆盖。

## 管理员初始化调用顺序

在已认证管理员会话中，对同一 API base 调用：

1. `GET /model-governance/status`，确认尚未启用。
2. `POST /model-governance/import/preview`，检查安全预览模型数组。
3. 明确操作 `POST /model-governance/import`；本实施代理未执行真实初始化。
4. `GET /model-governance/models`，按所需用户对稳定模型UUID提交 `PUT .../users/{user_id}`，body `{"enabled":true}`，刷新核验 `user_grants`。
5. `GET /model-governance/enforcement/preview` 查看未覆盖用户/默认模型影响。
6. 再次读取status版本，管理员明确提交 `PUT /model-governance/enforcement`，例如 `{"enabled":true,"expected_version":0,"reason":"管理员确认授权覆盖"}`。如409须重新读取预览和版本。

实现保持分层职责：records只表达安全数据，repository负责SQL事务，governance集中权限与策略，runtime装配现有Provider/会话运行。未引入额外Registry或第二授权文件，遵循KISS/DRY/YAGNI。

## Fix round 1（2026-09-06）

状态：DONE_WITH_CONCERNS，提交限定复审。本轮基线为 `.superpowers/task-7-1-task-2-fix1-baseline/`；实际 unified diff 为 `.superpowers/task-7-1-task-2-fix1.diff`，不是 HEAD diff。无真实配置、服务、数据库或 git 操作。

修复内容：

- ReMe：真实 AgentBuilder 从 request 的服务端 `_model_authority` 构造轻量请求视图，明确参数穿过私有 runtime、auto_memory 队列和 summarize；dream/daily_paper 接收同一可信参数。每个 needs_llm job 在既有独占生命周期锁内重新校验授权、注入有效槽并完整执行，避免共享 ReMe 并发换槽。未新增 ReMe 独立 LLM 字段：现有配置没有该入口，显式指会话覆盖或 Agent 默认；embedding/reranker 原显式配置保持不变。
- 多用户 needs_llm 无可信 authority 明确 `authority_unavailable`，不退回 Agent 默认。撤销、DB 校验失败等可信 job 异常向上传播，后台 worker 记 failed，不伪报 completed。公共 cron 没有会话身份时也失败关闭；尚未设计额外后台身份策略。启动时原模型组件装配仍保留，但实际 needs_llm 调用不能绕过上述检查。
- AgentModal 对目录和平台默认采用独立 settled 结果：默认 403 不丢弃已授权目录，继承提示仍显示不可用。
- 草稿：selection scope 增加 reset；真实 useCreateNewSession 新建操作清理（包括相同 `/chat`），ModelSelector 离开卸载也清理；已有服务端会话覆盖不变。
- 删除引用：事务局部 `SET LOCAL row_security = off` 不绕过 RLS，而是让过滤查询报错；捕获 DBAPIError 转 `model_reference_authority_unavailable`，既有删除路由映射 HTTP 409。完整可见连接仍返回 conversation_id/agent_id 摘要。真实测试复用现有 qwenpaw_runtime role，只向一次性 fixture schema 临时 GRANT SELECT/USAGE，未创建或修改角色。
- Chat 多模态和限流候选旧请求的失败分支也检查当前模型 scope，避免清空新会话状态。

RED / GREEN：

1. `python .superpowers/task-7-1-task-2-test.py tests/unit/models/test_reme_authority.py -q --tb=short`：最初 4 failed（没有可信绑定、未授权仍尝试原模型创建）；最终 7 passed / exit 0。覆盖双会话并发不串模型、显式会话/Agent 有效槽、撤销不注入、真实视图到复用队列、缺身份后台 failed，以及 Console extraction/prepare → 真实 ConsoleChannel → 真实 AgentBuilder 到模型构造边界；provider 构造边界被测试截断，无实际 LLM 网络调用。
2. PG 同专属测试启动器执行 `tests/integration/test_model_governance_repository.py -q --tb=short`：RED 为受限角色 `DID NOT RAISE ValueError`，GREEN 1 passed / exit 0。fixture 的 DSN 字段改为 repr=False；后续只用 short traceback、不输出 locals。早期失败时默认 pytest fixture repr 曾将测试 DSN 显示到工具输出，未保存该输出、未写入本报告或日志；此处不重复凭据。
3. `cd console; npx vitest run --config ../.superpowers/task-7-1-task-2-fix1-red.config.ts src/pages/Settings/Agents/components/AgentModal.test.tsx --reporter=dot`：使用只读 Vite loader 加载本轮基线而不替换工作文件，准确复现目录被 403 丢弃，1 failed / 3 passed / exit 1。正常实现同文件 GREEN。
4. ModelSelector 新测试真实调用新建 hook：RED 草稿仍为 two；GREEN 新建后为空、离开再返回默认恢复。普通选择/clear/换账号过期响应/目录不可用测试继续通过。
5. 最终综合后端：`python .superpowers/task-7-1-task-2-test.py tests/unit/agents/memory tests/unit/models tests/isolation/test_model_catalog.py tests/unit/app/chats/test_conversation_model.py tests/integration/test_model_governance_repository.py -q --tb=short` → **164 passed / exit 0**，仅已有 Starlette TestClient deprecation，无 Windows access violation。旧 Daily Paper `__new__` fixture 补初始化既有 lifecycle_writer_lock，保留原异常断言。
6. `cd console; npx vitest run src/pages/Chat/ModelSelector/ModelSelector.test.tsx src/pages/Settings/Agents/components/AgentModal.test.tsx src/api/modules/modelCatalog.test.ts src/pages/Settings/Models/GovernancePanel.test.tsx --reporter=dot` → **4 files / 11 tests passed / exit 0**；保留既有 jsdom/act 警告。`npx tsc -b --noEmit` → **exit 0**。

未验证/边界：本轮遵主流程最新指示不重复完整 build，留统一集成构建；未执行实机部署/真实元数据初始化。原 fork/ChatPage 既有失败和治理文案技术债不扩大修复。没有独立 ReMe LLM 选择入口；多用户无会话身份的公共记忆定时 LLM 操作现在明确失败关闭，需未来独立后台授权方案后才可恢复。
