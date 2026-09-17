# Task 4.5-C/1 记忆运行效果与用户隔离实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 每个子任务完成后必须等待用户确认，不得自动进入下一子任务。

**Goal:** 保留原有 Markdown、ReMe 和 ADBPG 能力，实现 Agent 公共记忆与用户私有记忆的运行时隔离、合并检索、后台任务路由和可验收文件页。

**Architecture:** Agent workspace 使用公共记忆运行时；每个 user_id + agent_id 按需创建独立私有运行时和目录。统一 MemoryScopeContext 负责身份与作用域，ReMe 和 ADBPG 只消费该上下文；检索并行查询公共与当前用户私有记忆后统一去重、排序和标记。

**Tech Stack:** Python、FastAPI、Pydantic、PostgreSQL/Alembic、ReMe、ADBPG REST、React/TypeScript、Vitest、pytest、Playwright。

## Global Constraints

- 公共记忆在 Agent workspace；私有记忆在 user_workspaces/{user_id}/{agent_id}/，正文不迁入 PostgreSQL。
- 旧 Agent 记忆原地保留并登记为公共记忆，不猜测历史用户归属。
- 私有 ADBPG 操作必须使用真实 user_id + agent_id，禁止 shared 回退。
- 管理员代管只能管理公共记忆，不能读取其他用户私有记忆。
- 自动记忆、自动搜索、/memorize、手动 /dream 使用当前用户私有作用域；定时梦境和 Daily Paper 使用公共作用域。
- 前端隐藏不是权限边界；文件、状态、搜索、重建和删除 API 必须后端授权。
- 记忆失败不得阻断对话，也不得把私有失败降级为公共写入。
- 每项必须测试先行并观察 RED/GREEN；完成后停在用户确认门。
- 不执行 Git commit、push、reset 或分支操作。

## 文件责任地图

| 单元 | 责任 |
|---|---|
| src/qwenpaw/memory_scope/ | 认证用户、Agent、作用域与路径解析 |
| src/qwenpaw/persistence/ | agent_user_workspaces 登记、状态和索引版本 |
| src/qwenpaw/agents/memory/ | 运行时池、ReMe/ADBPG、搜索合并和任务路由 |
| src/qwenpaw/app/routers/ | 文件、状态、搜索和重建 API 授权 |
| console/src/features/files-workspace/ | 公共记忆/我的记忆、状态和文件树 |
| tests/ 与 e2e/ | 单元、隔离、集成及真实页面验证 |

---

### Task 4.5-C/1-A：作用域解析、目录与数据库登记

**可验收成果：** 两个用户在同一 Agent 下得到不同私有目录；公共目录固定；API 返回安全的作用域与索引状态；用户不能提交任意路径或读取他人目录。

**Files:**

- Create: src/qwenpaw/memory_scope/__init__.py
- Create: src/qwenpaw/memory_scope/models.py
- Create: src/qwenpaw/memory_scope/resolver.py
- Create: src/qwenpaw/persistence/agent_user_workspaces.py
- Create: migrations/versions/0008_agent_user_workspaces.py
- Modify: src/qwenpaw/app/agent_context.py
- Modify: src/qwenpaw/app/routers/agents.py
- Create: tests/unit/memory_scope/test_resolver.py
- Create: tests/unit/persistence/test_agent_user_workspaces.py
- Create: tests/isolation/test_memory_scope_isolation.py
- Modify: tests/integration/test_migrations.py

**Produces:** MemoryScope、MemoryScopeContext、MemoryScopeResolver.resolve_private/resolve_public/workspace_path，以及 AgentUserWorkspaceRepository。

- [ ] Step 1：写失败测试，证明同 Agent 两用户 private 路径不同、public 路径固定、缺少 actor 的 private 解析被拒绝。
- [ ] Step 2：运行 pytest tests/unit/memory_scope/test_resolver.py -q，确认因接口不存在而失败。
- [ ] Step 3：写失败测试，证明 agent_user_workspaces 可幂等登记 user_id + agent_id + scope，且能更新生命周期与索引状态。
- [ ] Step 4：运行 pytest tests/unit/persistence/test_agent_user_workspaces.py -q，确认预期失败。
- [ ] Step 5：实现作用域模型、受控路径 resolver、数据库迁移和 repository；请求不得传入物理路径。
- [ ] Step 6：运行两个单测和 tests/isolation/test_memory_scope_isolation.py，确认通过。
- [ ] Step 7：增加 /api/agents/{agentId}/memory/scopes 安全摘要接口，不返回绝对路径或其他用户 ID。
- [ ] Step 8：运行 API 角色矩阵与迁移测试，确认 owner、collaborator、使用者和管理员代管符合设计。
- [ ] Step 9：生成 docs/project-audit/32-任务4.5-C1-A作用域解析验收报告.md，展示目录、数据库和 403 证据；停止等待确认。

### Task 4.5-C/1-B：ReMe 公共/私有运行时与检索合并

**可验收成果：** 用户 A 的私有标记只能由 A 搜到；用户 B 只能搜到公共标记和 B 自己的标记；搜索结果正确标记来源。

**Files:**

- Create: src/qwenpaw/agents/memory/scope_runtime.py
- Create: src/qwenpaw/agents/memory/scoped_memory_pool.py
- Modify: src/qwenpaw/agents/memory/reme_config.py
- Modify: src/qwenpaw/agents/memory/reme_light_memory_manager.py
- Modify: src/qwenpaw/agents/middlewares.py
- Create: tests/unit/agents/memory/test_scoped_memory_runtime.py
- Create: tests/unit/agents/memory/test_memory_search_merge.py
- Create: tests/isolation/test_memory_runtime_user_isolation.py
- Modify: tests/unit/agents/memory/test_reme_config.py

**Produces:** ScopedMemoryRuntimePool.get/close/close_user 和 search_scopes(public_manager, private_manager, query, max_results)。

- [ ] Step 1：写失败测试，证明两个 private runtime 使用不同 working_dir、metadata 和索引目录，pool 不跨用户复用。
- [ ] Step 2：运行 test_scoped_memory_runtime.py，确认 RED。
- [ ] Step 3：写失败测试，覆盖公共命中、私有命中、重复内容和单一作用域失败的合并结果。
- [ ] Step 4：运行 test_memory_search_merge.py，确认 RED。
- [ ] Step 5：实现运行时池、ReMe 路径注入和带作用域标签的结果合并。
- [ ] Step 6：让 MemoryMiddleware 传递可信 user/session/run 上下文，不再只传 session_id。
- [ ] Step 7：运行新单测、隔离测试和既有 test_memory_middleware.py，确认通过。
- [ ] Step 8：用两个隔离用户写入唯一标记，保存 API、文件和索引快照证据。
- [ ] Step 9：生成 docs/project-audit/33-任务4.5-C1-B运行时隔离验收报告.md；停止等待确认。

### Task 4.5-C/1-C：ADBPG 真实用户隔离

**可验收成果：** add/search 请求包含真实 user_id + agent_id + run_id；无身份请求拒绝；私有操作不存在 shared 回退。

**Files:**

- Modify: src/qwenpaw/agents/memory/adbpg_memory_manager.py
- Modify: src/qwenpaw/agents/memory/adbpg_client.py
- Modify: src/qwenpaw/app/agent_context.py
- Create: tests/unit/agents/memory/test_adbpg_scope_identity.py
- Modify: tests/unit/agents/memory/test_adbpg_memory_manager.py
- Create: tests/isolation/test_adbpg_memory_scope.py

- [ ] Step 1：写失败测试，验证 u1 与 u2 的 add/search payload 分别使用自己的用户、Agent 和 run；缺少 user 抛 MemoryScopeDenied。
- [ ] Step 2：运行 test_adbpg_scope_identity.py，确认 RED。
- [ ] Step 3：写失败测试，证明 legacy shared 数据不进入普通用户私有搜索。
- [ ] Step 4：运行 test_adbpg_memory_scope.py，确认 RED。
- [ ] Step 5：实现 manager 的显式 scope 注入、client 参数校验和审计字段，删除私有 shared fallback。
- [ ] Step 6：运行 ADBPG 单元、隔离及原有 manager 测试，确认通过。
- [ ] Step 7：使用隔离 HTTP mock 验证实际 JSON payload；不连接生产 ADBPG，不记录密钥。
- [ ] Step 8：生成 docs/project-audit/34-任务4.5-C1-CADBPG用户隔离验收报告.md；停止等待确认。

### Task 4.5-C/1-D：自动记忆与后台任务路由

**可验收成果：** 自动记忆、/memorize、手动 /dream 写当前用户私有记忆；定时梦境和 Daily Paper 写公共记忆；通知接收人不串用户。

**Files:**

- Modify: src/qwenpaw/agents/command_handler.py
- Modify: src/qwenpaw/agents/memory/reme_light_memory_manager.py
- Modify: src/qwenpaw/app/crons/manager.py
- Modify: src/qwenpaw/app/inbox_store.py
- Modify: src/qwenpaw/app/routers/agents.py
- Create: tests/unit/agents/memory/test_memory_job_scope_routing.py
- Modify: tests/unit/agents/test_command_handler.py
- Modify: tests/unit/agents/memory/test_reme_daily_paper.py
- Create: tests/isolation/test_memory_job_user_isolation.py
- Modify: tests/integration/test_inbox.py

- [ ] Step 1：写失败测试，证明 /memorize 与手动 /dream 使用 private context，cron dream/Daily Paper 使用 public context。
- [ ] Step 2：运行定向测试，确认 RED。
- [ ] Step 3：写失败测试，证明私有任务只给当前用户创建 receipt，公共 Daily Paper 只通知 Agent owner，无可靠收件人时不广播。
- [ ] Step 4：运行 inbox 隔离测试，确认 RED。
- [ ] Step 5：实现任务路由和最终写入前二次权限检查；自动化主体不得继承任意请求用户上下文。
- [ ] Step 6：运行 unit、isolation 和 integration 相关测试，确认通过。
- [ ] Step 7：在隔离实例执行每类任务，检查私有/公共文件、任务记录和收件人；恢复测试配置与文件。
- [ ] Step 8：生成 docs/project-audit/35-任务4.5-C1-D后台任务作用域验收报告.md；停止等待确认。

### Task 4.5-C/1-E：文件页“公共记忆/我的记忆”、状态与重建入口

**可验收成果：** 页面切换两个作用域；普通使用者维护自己的私有记忆但不能写公共记忆；owner、collaborator 和管理员代管可管理公共记忆；直接 API 无法绕过。

**Files:**

- Modify: src/qwenpaw/app/routers/agents.py
- Modify: src/qwenpaw/app/routers/workspace.py
- Modify: console/src/features/files-workspace/filesWorkspaceScope.ts
- Modify: console/src/features/files-workspace/FilesWorkspace.tsx
- Modify: console/src/features/files-workspace/FilesNavigator.tsx
- Modify: console/src/features/files-workspace/memoryTree.ts
- Modify: console/src/features/files-workspace/FilesWorkspace.module.less
- Modify: console/src/api/modules/agent.ts
- Create: console/src/features/files-workspace/memoryScope.test.ts
- Modify: console/src/features/files-workspace/FilesWorkspace.test.tsx
- Create: tests/unit/app/routers/test_memory_scope_router.py
- Create: e2e/tests/test_memory_scope.py

- [ ] Step 1：写前端失败测试，验证作用域切换、状态显示和重建按钮随 can_edit 变化。
- [ ] Step 2：运行 Vitest 定向测试，确认 RED。
- [ ] Step 3：写后端失败测试，覆盖公共写入、私有写入、跨用户读取和索引重建角色矩阵。
- [ ] Step 4：运行 pytest 定向测试，确认 RED。
- [ ] Step 5：实现 scope-aware API、文件树数据源、标签、状态和错误清理；响应不得包含物理路径。
- [ ] Step 6：运行前后端定向测试与既有 FilesWorkspace 测试，确认通过。
- [ ] Step 7：用 Playwright 验证公共只读、私有可写、跨用户 403、重建状态和权限撤销后缓存清空。
- [ ] Step 8：生成 docs/project-audit/36-任务4.5-C1-E记忆文件页验收报告.md；停止等待确认。

### Task 4.5-C/1-F：迁移、全角色回归与 C/1 确认门

**可验收成果：** 旧记忆原地变为公共记忆；迁移可重复；全角色页面/API/文件/数据库证据齐全；所有临时数据恢复。

**Files:**

- Create: src/qwenpaw/migrations/memory_scope_migration.py
- Create: scripts/verify_memory_scope_migration.py
- Modify: src/qwenpaw/app/migration.py
- Create: tests/integration/test_memory_scope_migration.py
- Create: tests/isolation/test_memory_scope_full_matrix.py
- Create: e2e/tests/test_memory_scope_full.py
- Modify: docs/project-audit/17-运行配置卡片保真矩阵.md
- Modify: docs/project-audit/16-多用户架构分阶段实施计划.md
- Create: docs/superpowers/verification/2026-08-25-task-4-5-c1-memory-runtime-isolation.md

- [ ] Step 1：写失败测试，证明旧公共 Markdown 内容和哈希不变、重复迁移不重复登记、旧 shared ADBPG 不进入用户私有搜索。
- [ ] Step 2：运行迁移集成测试，确认 RED。
- [ ] Step 3：写失败测试，覆盖 owner、collaborator、管理员普通路径、管理员代管、公用使用者和无授权用户矩阵。
- [ ] Step 4：运行隔离矩阵测试，确认 RED。
- [ ] Step 5：实现幂等扫描、公共登记、公共索引重建标记和 cleanup_pending 生命周期，不删除旧文件。
- [ ] Step 6：运行迁移、隔离和既有记忆测试，确认通过。
- [ ] Step 7：在隔离验收实例执行全角色真实页面回归，记录 API、文件哈希、数据库、索引和收件箱证据，并在 finally 中恢复。
- [ ] Step 8：运行前端测试、类型检查、生产构建和后端相关全量测试。
- [ ] Step 9：更新矩阵与阶段计划，生成最终报告，明确 Task 4.5-C/2 尚未开始。
- [ ] Step 10：停止等待用户确认，不自动进入 C/2。

## 总体验收命令

```powershell
Set-Location "E:/git_project/QwenPaw"
$env:PYTHONPATH="src"
& ".venv/Scripts/python.exe" -m pytest -q `
  "tests/unit/memory_scope" `
  "tests/unit/persistence/test_agent_user_workspaces.py" `
  "tests/unit/agents/memory" `
  "tests/isolation/test_memory_scope_isolation.py" `
  "tests/isolation/test_memory_runtime_user_isolation.py" `
  "tests/isolation/test_adbpg_memory_scope.py" `
  "tests/isolation/test_memory_job_user_isolation.py" `
  "tests/isolation/test_memory_scope_full_matrix.py" `
  "tests/integration/test_memory_scope_migration.py"

Set-Location "E:/git_project/QwenPaw/console"
npm run test:run -- src/features/files-workspace src/api/modules/agent.test.ts
npx tsc -b --noEmit
npm run build
```

## 计划自检

- 公共/私有目录、独立运行时、ADBPG 身份、后台任务、文件页、迁移和失败处理均映射到 C/1-A 至 C/1-F。
- 每个子任务都有前端或 API 可见成果，并设置独立用户确认门。
- 未引入 Redis、记忆正文数据库化或共享应用发布版本改造。
- shared_app_user_workspaces 未被误用；普通 Agent 私有空间使用 agent_user_workspaces。
- 计划不包含 Git 操作，符合项目 AGENTS 指令。
