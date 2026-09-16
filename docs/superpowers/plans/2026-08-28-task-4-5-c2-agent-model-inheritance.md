# Task 4.5-C/2 Agent 初始化与默认模型继承实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. 每个任务完成后必须等待用户确认。

**Goal:** 让未指定模型的 Agent 自动跟随全局默认模型，让显式指定模型的 Agent 固定使用指定模型，并保证聊天、ReMe 和后台记忆使用同一有效模型解析结果。

**Architecture:** `agent.json.active_model=null` 是继承全局默认的唯一配置事实；非空值是显式固定模型。新增无副作用的 `resolve_effective_model()` 解析器，统一校验 Agent 模型或当前全局模型；PostgreSQL `default_model_mode` 只作为治理摘要，不反向覆盖历史 `agent.json`。

**Tech Stack:** Python 3.10+、Pydantic、FastAPI、PostgreSQL Repository、ReMe 0.4.1.5、React/TypeScript、Vitest、pytest、Playwright。

## Global Constraints

- 不修改聊天事件、ToolCards、Reasoning、审批、进度、文件和图片展示。
- 不改变管理员配置供应商/模型、普通用户只能使用模型的权限边界。
- 不把 Embedding 配置接入聊天模型继承解析器；Embedding 继续使用独立配置。
- 不批量覆盖历史 Agent 的 `agent.json`；以现有 `active_model` 有无作为历史迁移依据。
- 不删除 Agent、会话、模型供应商或记忆文件；临时数据清理由用户确认后执行。
- 创建失败不得遗留数据库草稿、Agent 目录、`agent.json` 或半初始化运行时。
- 全部生产代码变更必须先有失败测试；不执行 Git commit、push、reset 或分支操作。

---

### Task 1：统一有效模型解析器（C/2-B-1）

**Files:**

- Create: `src/qwenpaw/agents/effective_model.py`
- Modify: `src/qwenpaw/agents/model_factory.py`
- Modify: `src/qwenpaw/runtime/builder.py`
- Modify: `src/qwenpaw/agents/memory/reme_light_memory_manager.py`
- Create: `tests/unit/agents/test_effective_model.py`
- Create: `tests/unit/agents/test_model_factory_effective_model.py`

**Interfaces:**

- Produces: `resolve_effective_model(agent_config, provider_manager=None) -> ModelSlotConfig`。
- Raises: 全局模型缺失、供应商不存在、模型不存在的可操作错误。
- Side effects: 不写文件、不更新 PostgreSQL、不调度 reload。

- [x] **Step 1：写失败测试**

```python
def test_explicit_agent_model_wins_over_global(): ...
def test_inherited_agent_uses_current_global_model(): ...
def test_missing_global_model_returns_actionable_error(): ...
def test_unknown_explicit_provider_is_rejected(): ...
```

使用真实 `ModelSlotConfig` 和最小 fake ProviderManager，断言有效 provider/model 及错误文本，不断言内部调用次数。

- [x] **Step 2：运行 RED**

```powershell
.venv/Scripts/python.exe -m pytest "tests/unit/agents/test_effective_model.py" -q
```

Expected: 解析器尚不存在或行为未统一导致 FAIL。

- [x] **Step 3：实现最小解析器并接入模型工厂、RuntimeBuilder 和 ReMe**

解析顺序固定为显式 `active_model` 后当前全局默认，每一步都校验 provider 和 model 存在。

- [x] **Step 4：运行 GREEN 与既有模型回归**

```powershell
.venv/Scripts/python.exe -m pytest "tests/unit/agents/test_effective_model.py" "tests/unit/agents/test_model_factory_effective_model.py" "tests/unit/agents/memory" -q
```

- [x] **Step 5：停止并等待用户确认**

验收：同一份 Agent 配置在聊天和 ReMe 中解析出相同 provider/model；无默认模型时错误一致。

---

### Task 2：创建与编辑的继承/显式语义（C/2-B-2）

**Files:**

- Modify: `src/qwenpaw/app/routers/agents.py`
- Modify: `src/qwenpaw/access/agent_repository.py`
- Modify: `src/qwenpaw/app/routers/providers.py`
- Test: `tests/unit/app/routers/test_agents_router.py`
- Create: `tests/unit/app/routers/test_providers_model_inheritance.py`
- Create: `tests/integration/test_agent_model_inheritance.py`

**Interfaces:**

- `POST /api/agents`: 未指定模型保存 `active_model=null` 和 `inherited`；指定模型保存显式值和 `explicit`。
- `PUT /api/agents/{agentId}`: 清空模型恢复继承，指定模型固定。
- `PUT /api/models/active`: 只更新全局模型，不把空 Agent 配置写成显式模型。

- [x] **Step 1：写失败测试**

```python
async def test_create_without_model_persists_inherited_without_snapshot(...): ...
async def test_create_with_model_persists_explicit_mode(...): ...
async def test_clear_agent_model_restores_inherited_mode(...): ...
async def test_global_model_change_does_not_materialize_inherited_agent(...): ...
async def test_missing_global_model_rejects_create_without_residue(...): ...
```

每个测试同时检查 `agent.json`、数据库摘要、目录和草稿状态。

- [x] **Step 2：运行 RED**

```powershell
.venv/Scripts/python.exe -m pytest "tests/unit/app/routers/test_agents_router.py" -k "model or inherited" -q
```

- [x] **Step 3：实现创建/编辑/全局模型写入的事务边界**

在目录创建和 owner 登记前完成模型校验；移除全局模型接口中“同步当前空 Agent 配置”的写入。数据库模式根据最终 `active_model` 同步。

- [x] **Step 4：运行 GREEN 与集成测试**

```powershell
.venv/Scripts/python.exe -m pytest "tests/unit/app/routers/test_agents_router.py" "tests/unit/app/routers/test_providers_model_inheritance.py" "tests/integration/test_agent_model_inheritance.py" -q
```

- [x] **Step 5：停止并等待用户确认**

验收：展示 API 响应、`agent.json` 差异、数据库模式和失败无残留证据。

---

### Task 3：复制语义与历史数据库摘要校正（C/2-B-3）

**Files:**

- Modify: `src/qwenpaw/app/routers/agents.py`
- Modify: `src/qwenpaw/access/agent_repository.py`
- Create: `src/qwenpaw/migrations/agent_model_mode_migration.py`
- Modify: `src/qwenpaw/app/migration.py`
- Test: `tests/unit/app/routers/test_agents_router.py`
- Test: `tests/integration/test_agent_model_inheritance.py`
- Create: `tests/integration/test_agent_model_mode_migration.py`

**Interfaces:**

- 继承型源 Agent 复制后仍为 `null/inherited`。
- 显式型源 Agent 复制后保留 provider/model 和 `explicit`。
- 历史校正只从 `agent.json` 更新 `default_model_mode`，不修改 Agent 文件。
- 迁移可重复执行，第二次无数据变化。

- [x] **Step 1：写失败测试**

```python
async def test_copy_inherited_agent_keeps_null_active_model(...): ...
async def test_copy_explicit_agent_keeps_model_and_explicit_mode(...): ...
async def test_copy_rejects_deleted_explicit_provider_without_residue(...): ...
async def test_mode_migration_uses_agent_json_and_is_idempotent(...): ...
```

- [x] **Step 2：运行 RED**

```powershell
.venv/Scripts/python.exe -m pytest "tests/unit/app/routers/test_agents_router.py" -k "copy and model" -q
.venv/Scripts/python.exe -m pytest "tests/integration/test_agent_model_mode_migration.py" -q
```

- [x] **Step 3：实现复制语义与幂等摘要校正**

复用统一模型校验，不复制会话、ReMe/ADBPG 索引、用户私有目录或频道绑定。

- [x] **Step 4：运行 GREEN 与复制/迁移回归**

```powershell
.venv/Scripts/python.exe -m pytest "tests/unit/app/routers/test_agents_router.py" "tests/integration/test_agent_model_inheritance.py" "tests/integration/test_agent_model_mode_migration.py" "tests/integration/test_multi_agent_lifecycle.py" -q
```

- [ ] **Step 5：停止并等待用户确认**

验收：展示继承型/显式型副本的配置、数据库摘要、目录内容和历史 Agent 哈希不变证据。

---

### Task 4：全局模型变更的受控重载（C/2-B-4）

**Files:**

- Modify: `src/qwenpaw/app/routers/providers.py`
- Modify: `src/qwenpaw/app/utils.py`
- Modify: `tests/unit/app/routers/test_providers_model_inheritance.py`
- Create: `tests/integration/test_inherited_agent_model_reload.py`

**Interfaces:**

- 全局模型变更后只 reload 已加载的继承型 Agent。
- 显式型 Agent 不 reload，`agent.json` 不改变。
- 部分 reload 失败不回滚全局模型，返回 `applied_agent_ids` 和 `pending_reload_agent_ids`。

- [x] **Step 1：写失败测试**

```python
async def test_global_model_change_reloads_only_inherited_agents(...): ...
async def test_partial_reload_failure_returns_retryable_agent_ids(...): ...
async def test_global_change_never_writes_inherited_agent_json(...): ...
```

- [x] **Step 2：运行 RED**

```powershell
.venv/Scripts/python.exe -m pytest "tests/unit/app/routers/test_providers_model_inheritance.py" -k "inherited or reload" -q
```

- [x] **Step 3：实现受控 reload 与待重试摘要**

加载 Agent 列表来自 MultiAgentManager；是否继承以当前 `agent.json.active_model` 为准。不并行修改 Agent 文件。

- [x] **Step 4：运行 GREEN 与真实运行时集成测试**

```powershell
.venv/Scripts/python.exe -m pytest "tests/unit/app/routers/test_providers_model_inheritance.py" "tests/integration/test_inherited_agent_model_reload.py" -q
```

- [ ] **Step 5：停止并等待用户确认**

验收：切换全局模型后，继承型 Agent 的聊天和 ReMe 使用新模型，显式 Agent 不变，两者配置哈希符合预期。

---

### Task 5：前端模型语义与只读边界（C/2-C）

**Files:**

- Modify: `console/src/pages/Settings/Agents/index.tsx`
- Modify: `console/src/pages/Settings/Agents/components/AgentModal.tsx`
- Modify: `console/src/pages/Settings/Agents/components/AgentTable.tsx`
- Modify: `console/src/api/modules/agents.ts`
- Modify: `console/src/api/types/agents.ts`
- Modify: `console/src/locales/zh.json`
- Modify: `console/src/locales/en.json`
- Create: `console/src/pages/Settings/Agents/components/AgentModal.test.tsx`
- Modify: `console/src/pages/Settings/Agents/components/AgentTable.test.tsx`

**Interfaces:**

- 空模型显示“使用全局默认（当前：provider/model）”。
- 选择模型显示“指定模型”；清空选择恢复继承。
- 普通用户、平台公用/仅使用 Agent 继续只读或只能使用，不显示供应商配置入口。

- [x] **Step 1：写前端失败测试**

断言：`active_model=null` 时表单字段为空且显示全局摘要；显式模型回填 provider/model；清空后 payload 为 `active_model: null`。

- [x] **Step 2：运行 RED**

```powershell
Set-Location "console"
npm run test:run -- "src/pages/Settings/Agents/components/AgentModal.test.tsx" "src/pages/Settings/Agents/components/AgentTable.test.tsx"
```

- [x] **Step 3：实现最小页面语义**

不在前端生成模型快照；全局摘要来自后端有效模型接口。保留已有角色、共享 Agent 和模型锁定判断。

- [x] **Step 4：运行 GREEN、类型检查和生产构建**

```powershell
npm run test:run -- "src/pages/Settings/Agents/components/AgentModal.test.tsx" "src/pages/Settings/Agents/components/AgentTable.test.tsx"
npm exec -- tsc -b --noEmit
npm run build
```

- [ ] **Step 5：停止并等待用户确认**

页面验收：创建继承型、创建显式型、编辑清空、刷新回读、普通用户只读边界。

---

### Task 6：真实运行、阶段回归与确认门（C/2-D/E）

**Files:**

- Create: `e2e/tests/test_agent_model_inheritance.py`
- Modify: `docs/project-audit/16-多用户架构分阶段实施计划.md`
- Create: `docs/project-audit/40-任务4.5-C2-Agent模型继承验收报告.md`

- [x] **Step 1：记录验收基线**

记录全局默认模型、现有 Agent `agent.json` 哈希、数据库摘要和当前运行状态。

- [x] **Step 2：真实页面/API 验证继承型 Agent**

创建不指定模型的 Agent，确认 `null/inherited`，启动聊天、ReMe 和记忆检索；切换全局模型后确认有效模型变化但 `agent.json` 哈希不变。

- [x] **Step 3：真实页面/API 验证显式型 Agent**

创建指定模型 Agent，切换全局默认后确认有效模型保持原值；清空模型后恢复跟随。

- [x] **Step 4：验证复制、失败无残留和权限**

复制继承型/显式型 Agent；在无全局默认模型的隔离环境中确认创建被拒绝且无目录、数据库草稿或 `agent.json` 残留；普通用户不能修改全局模型。

- [x] **Step 5：恢复验收环境**

恢复全局模型。删除临时会话或临时 Agent 前，分别输出危险操作确认；未获确认则保留并标注临时用途。

- [x] **Step 6：运行阶段回归**

```powershell
.venv/Scripts/python.exe -m pytest "tests/unit/agents" "tests/unit/app/routers/test_agents_router.py" "tests/unit/app/routers/test_providers_model_inheritance.py" "tests/integration/test_agent_model_inheritance.py" "tests/integration/test_agent_model_mode_migration.py" "tests/integration/test_inherited_agent_model_reload.py" "tests/isolation" -q
Set-Location "console"
npm run test:run -- "src/pages/Settings/Agents" "src/pages/Agent/Config" "src/pages/Chat"
npm exec -- tsc -b --noEmit
npm run build
```

- [x] **Step 7：生成报告并更新阶段确认门**

报告记录模型解析矩阵、创建/编辑/复制 API、配置哈希、数据库模式、ReMe 与聊天运行状态、普通用户权限、无默认模型失败无残留、前端截图和所有警告。

- [ ] **Step 8：停止等待用户验收 C/2**

明确 Task 5.1 尚未开始，不自动进入下一阶段。
