# Task 4.5-A Runtime Config Access Implementation Plan

> **Execution:** Use superpowers:executing-plans to implement this plan task-by-task in the current workspace. Do not use subagents unless the user explicitly requests delegation. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为运行配置补齐 owner/collaborator/user/admin-governance 的前后端访问边界，让仅使用用户只能看到安全摘要且无法通过 API 修改配置。

**Architecture:** 复用现有 `AgentMembershipService` 和 `request.state.agent_access` 作为访问事实；新增运行配置访问上下文与安全摘要接口。完整草稿配置和所有关联写接口在后端统一检查编辑能力，前端先读取能力再选择完整编辑页或只读摘要页。管理员自己的 Agent 仍使用普通资源角色；管理员代管运行配置使用带有明确 Agent ID 的治理上下文，后端仅在运行配置白名单接口上调用 `AgentGovernanceService.require_admin_agent`，并把治理状态回传给前端，避免把管理员身份隐式升级成普通 Agent 所有者。

**Tech Stack:** FastAPI、Pydantic、PostgreSQL-backed Agent membership repository、React、TypeScript、Vitest、pytest。

## Global Constraints

- 不新增或修改数据库表。
- 不改变 `agent.json` 作为运行配置内容源。
- 不改变 Task 4.4-A 的 `If-Match/config_version` 并发控制。
- 不改变 Task 4.4-B 的 `applied/pending_reload` 状态和重试行为。
- 不改变运行配置字段、默认值、校验、Embedding 回滚或原有热重载流程。
- 保留现有 `/config/user-timezone` 行为，不在本任务中迁移其存储语义；Agent 只读状态不得阻断该独立操作。Agent 语言属于 Agent 配置，必须受编辑权限保护。
- 不执行 Git commit、push、reset、分支创建或删除数据。
- 每个生产变更必须先有对应测试并观察到 RED，再实现 GREEN。

---

### Task 1: 后端访问上下文与安全摘要契约

**Files:**
- Modify: `src/qwenpaw/app/routers/workspace.py`
- Modify: `src/qwenpaw/app/agent_context.py`（仅在现有访问角色解析缺少稳定辅助函数时修改）
- Test: `tests/unit/app/routers/test_workspace_router.py`
- Test: `tests/unit/app/test_agent_context.py`（若已有测试文件，否则在 workspace 路由测试中覆盖）

**Interfaces:**
- Produces `GET /api/workspace/access` returning:

```json
{
  "agent_id": "agent-key",
  "access_role": "owner|collaborator|user",
  "can_view": true,
  "can_edit": false,
  "is_governance": false,
  "visibility": "private|public",
  "owner_user_id": "uuid"
}
```

- Produces `GET /api/workspace/running-config/summary` returning only safe effective fields:

```json
{
  "agent_id": "agent-key",
  "name": "Agent name",
  "language": "zh",
  "timezone": "Asia/Shanghai",
  "active_model": {"provider_id": "cpa", "model": "gpt-5.6-sol"},
  "model_switchable": true,
  "access_role": "user",
  "can_edit": false,
  "read_only_reason": "仅使用权限"
}
```

- Existing `GET /api/workspace/running-config` remains the complete draft-config endpoint and rejects `user` access with `403`.

- [x] **Step 1: Write the failing backend tests**

Add tests that construct `request.state.agent_access` with owner, collaborator and user roles and assert:

```python
async def test_user_cannot_read_complete_running_config() -> None:
    request = request_with_access(role=AgentResourceRole.USER)
    with pytest.raises(HTTPException) as exc:
        await get_agents_running_config(request)
    assert exc.value.status_code == 403

async def test_user_can_read_safe_running_config_summary() -> None:
    request = request_with_access(role=AgentResourceRole.USER)
    summary = await get_running_config_summary(request)
    assert summary.can_edit is False
    assert "workspace_dir" not in summary.model_dump()
    assert "api_key" not in str(summary.model_dump())
```

- [x] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
$env:PYTHONPATH="src"
& ".venv/Scripts/python.exe" -m pytest -q `
  "tests/unit/app/routers/test_workspace_router.py" `
  -k "complete_running_config or running_config_summary"
```

Expected: failure because complete-config access is not role-gated and the summary endpoint/model is absent.

- [x] **Step 3: Implement the minimum backend contract**

Implement a Pydantic response model and two handlers in `workspace.py`:

```python
class RunningConfigAccess(BaseModel):
    agent_id: str
  access_role: Literal["owner", "collaborator", "user", "admin_governance"]
    can_view: bool
    can_edit: bool
    is_governance: bool = False
    visibility: AgentVisibility
    owner_user_id: UUID

class RunningConfigSummary(BaseModel):
    agent_id: str
    name: str
    language: str
    timezone: str
    active_model: dict[str, str | None] | None
    model_switchable: bool
  access_role: Literal["owner", "collaborator", "user", "admin_governance"]
    can_edit: bool
    read_only_reason: str | None = None
```

Use the access object already placed on `request.state` by `get_agent_for_request`; do not issue a second independent membership query. For complete config and Agent language GET/PUT, reject `AgentResourceRole.USER` before loading or writing the full config. The summary may load only public profile/model metadata and the existing safe timezone value; it must not read the complete draft config. `model_switchable` is true for the chat-facing model selector in this scope; shared-application default-model locking is a later task.

- [x] **Step 4: Run the focused tests and verify GREEN**

Run the same command. Expected: all new access and summary tests pass, with existing workspace tests unchanged.

---

### Task 2: 后端统一保护运行配置写路径

**Files:**
- Modify: `src/qwenpaw/app/routers/workspace.py`
- Modify: `src/qwenpaw/app/routers/config.py`
- Test: `tests/unit/app/routers/test_workspace_router.py`
- Test: `tests/unit/app/routers/test_config_router.py` or the existing config-router test file

**Interfaces:**
- Consumes `request.state.agent_access.can_edit` from Task 1.
- Keeps `PUT /workspace/running-config`, `PUT /workspace/language`, and Agent-scoped equivalents unchanged for authorized callers.
- Rejects unauthorized Agent-config writes with `HTTPException(status_code=403, detail="forbidden")` before file/database/reload side effects.
- Leaves `PUT /config/user-timezone` as a user preference operation.

- [x] **Step 1: Write failing authorization tests**

Cover owner/collaborator success, user rejection, and no side effects:

```python
async def test_user_running_config_put_is_forbidden_without_persist_or_reload():
    request = request_with_access(role=AgentResourceRole.USER)
    with patch("...update_agent_config_async") as persist, patch(
        "...reload_agent_and_track", new_callable=AsyncMock
    ) as reload:
        with pytest.raises(HTTPException) as exc:
            await put_agents_running_config(AgentsRunningConfig(), request)
    assert exc.value.status_code == 403
    persist.assert_not_awaited()
    reload.assert_not_awaited()
```

- [x] **Step 2: Run tests and verify RED**

Run the focused workspace/config tests. Expected: the user write test fails because the current route permits the request after the generic GET-style access check.

- [x] **Step 3: Add one shared write guard and apply it before side effects**

Add a small helper in `agent_context.py` or `workspace.py` that raises `403` unless the current access role is owner or collaborator. Call it at the top of each Agent-config write handler, before parsing versions, opening path locks, loading secrets, updating files, or scheduling/retrying reloads. Do not use it for user timezone.

- [x] **Step 4: Run focused tests and verify GREEN**

Run workspace/config router tests and confirm owner/collaborator behavior, Task 4.4-A version conflicts, and Task 4.4-B runtime status all remain green.

---

### Task 3: 前端访问能力与只读摘要页面

**Files:**
- Modify: `console/src/api/modules/agent.ts`
- Modify: `console/src/api/modules/agent.test.ts`
- Modify: `console/src/pages/Agent/Config/useAgentConfig.tsx`
- Modify: `console/src/pages/Agent/Config/useAgentConfig.test.tsx`
- Modify: `console/src/pages/Agent/Config/index.tsx`
- Modify: `console/src/pages/Agent/Config/index.module.less`
- Modify: `console/src/locales/zh.json`
- Modify: `console/src/locales/en.json`

**Interfaces:**
- Produces `agentApi.getAgentRunningConfigAccess()`.
- Produces `agentApi.getAgentRunningConfigSummary()`.
- Hook returns `access`, `readOnlySummary`, and `isReadOnly` in addition to existing Task 4.4-B values.

- [x] **Step 1: Write failing API and Hook tests**

Add API path assertions:

```ts
await agentApi.getAgentRunningConfigAccess();
expect(request).toHaveBeenCalledWith("/workspace/access");
await agentApi.getAgentRunningConfigSummary();
expect(request).toHaveBeenCalledWith("/workspace/running-config/summary");
```

Add Hook assertions that a user access response causes summary-only loading and does not call full config/version/runtime APIs.

- [x] **Step 2: Run frontend focused tests and verify RED**

Run:

```powershell
npm run test:run -- src/api/modules/agent.test.ts src/pages/Agent/Config/useAgentConfig.test.tsx
```

Expected: failure because the two API methods and read-only branch do not exist.

- [x] **Step 3: Implement API and Hook branching**

Load access first. For `can_edit=true`, preserve the existing Promise.all for complete config, version, language, timezone, and runtime status. For `can_edit=false`, request only the summary; do not request full config, version, runtime reload status, or any config write metadata. Keep the existing `/config/user-timezone` operation separate from Agent config editing.

- [x] **Step 4: Render the read-only summary view**

In `Agent/Config/index.tsx`, branch before building the full dynamic tabs. Render a safe summary card with a read-only explanation and model/language/timezone values. Do not render Form, Tabs, Save, Reset, pending-reload Alert, or reload retry controls in this branch.

- [x] **Step 5: Run frontend tests and verify GREEN**

Run the focused tests and confirm all existing editable-hook tests still pass.

---

### Task 4: 管理员治理状态与文案

**Files:**
- Modify: `src/qwenpaw/app/agent_context.py`
- Modify: `src/qwenpaw/app/routers/workspace.py`
- Test: `tests/unit/app/test_agent_context_project_dir.py`
- Test: `tests/unit/app/routers/test_workspace_router.py`
- Modify: `console/src/api/modules/agents.ts` only if an explicit governance context endpoint/header is missing
- Modify: `console/src/pages/Settings/Agents/index.tsx` only if the existing admin config entry needs to establish the context
- Modify: `console/src/pages/Settings/Agents/components/AdminAgentsTable.tsx`
- Modify: `console/src/pages/Agent/Config/index.tsx`
- Modify: `console/src/pages/Agent/Config/useAgentConfig.tsx`
- Modify: `console/src/locales/zh.json`
- Modify: `console/src/locales/en.json`
- Test: `console/src/pages/Settings/Agents/components/AdminAgentsTable.test.tsx` and a focused Config page test

**Interfaces:**
- Existing `/admin/agents/{agentId}/config` remains the explicit governance edit path for the profile/config modal.
- Runtime-config governance requests carry an explicit target Agent ID and governance marker from the admin Agent table. The backend accepts that marker only for the allowlisted runtime-config access/read/write/version/status/reload/language handlers, verifies `require_admin_agent`, sets `request.state.agent_governance`, and records the existing governance audit event. Other `/workspace/*` handlers must continue to use membership access and must not accept the marker.
- Any governance indicator must be derived from the server response (`is_governance`), not from the client’s admin role alone.

- [ ] **Step 1: Write a failing test for governance indication**

Assert that an explicit governance context produces the “代管配置” indicator, while an administrator editing an owned Agent does not.

- [ ] **Step 2: Run the focused test and verify RED**

Expected: current runtime config page has no governance state or indicator.

- [ ] **Step 3: Implement the explicit governance context**

Add a shared frontend request option that sends the target Agent ID plus the governance marker only while the administrator opens runtime configuration from the “全部智能体” governance entry. Add a backend dependency/helper with a strict path allowlist; it must call `AgentGovernanceService.require_admin_agent` before any runtime-config read/write/reload side effect and populate `request.state.agent_governance`. Reject the marker on every unrelated workspace endpoint. Do not infer governance from a client-only admin flag.

- [ ] **Step 4: Render and test the governance indicator**

Return `is_governance=true` and `access_role="admin_governance"` for the explicit governance context. Confirm owned admin path has no governance badge, the admin governance path has a visible “管理员代管” badge, and governance writes produce the same audit record used by the existing admin config route.

---

### Task 5: 回归测试、构建与真实验收

**Files:**
- Modify: `docs/project-audit/16-多用户架构分阶段实施计划.md`
- Create: `docs/project-audit/30-任务4.5-A运行配置访问与只读边界验收报告.md`

- [ ] **Step 1: Run backend regression**

```powershell
$env:PYTHONPATH="src"
& ".venv/Scripts/python.exe" -m pytest -q `
  "tests/unit/app/routers/test_workspace_router.py" `
  "tests/unit/app/routers/test_config_router.py"
```

Expected: all focused backend tests pass.

- [ ] **Step 2: Run frontend regression and type check**

```powershell
Set-Location console
npm run test:run -- src/api/modules/agent.test.ts src/pages/Agent/Config/useAgentConfig.test.tsx
npx tsc -b --noEmit
```

Expected: all focused frontend tests and TypeScript pass.

- [ ] **Step 3: Verify API isolation in 18089**

Use the existing administrator and ordinary-user accounts:

1. Owner/admin-owned Agent: `GET /workspace/access` returns `can_edit=true`; complete config loads.
2. Ordinary user on public/only-use Agent: access returns `can_edit=false`; summary loads; complete config and PUT return `403`.
3. Compare config version and `agent.json` hash before/after the forbidden PUT; neither changes.
4. User timezone update still succeeds independently.

- [ ] **Step 4: Verify visible UI**

Confirm editable users see the unchanged configuration form and save flow. Confirm only-use users see the summary card without form/save/reload controls. Confirm existing Task 4.4-A conflict and Task 4.4-B pending reload behavior remain available only on editable paths.

- [ ] **Step 5: Write the acceptance report and stop for confirmation**

Record API responses, screenshots or DOM evidence, test counts, and any known limits in `docs/project-audit/30-任务4.5-A运行配置访问与只读边界验收报告.md`. Mark only the 4.5-A checklist complete and stop before 4.5-B.
