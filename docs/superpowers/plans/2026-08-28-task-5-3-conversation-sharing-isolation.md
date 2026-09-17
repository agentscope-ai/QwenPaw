# Task 5.3 Conversation Sharing and Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Each task is a separate user confirmation gate and must leave the application runnable.

**Goal:** 在保持现有富消息与工具执行过程展示不变的前提下，实现会话所有权、显式只读分享、服务端查询隔离和 PostgreSQL RLS。

**Architecture:** PostgreSQL `conversations` 与 `conversation_members` 是所有权和分享权限的唯一权威；现有 `ChatManager`/`SafeJSONSession` 暂时继续提供完整消息及工具事件内容投影。按纵向功能切片推进，每项同时交付数据库/后端和可见前端效果；Task 5.4 处理实时流隔离，Task 5.5 处理完整数据库历史回放。

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy async/asyncpg, Alembic, PostgreSQL, Pydantic, React 18, TypeScript, Vitest, pytest。

## Global Constraints

- 不改变 SSE wire envelope、富消息、Thinking、工具调用、工具输出、审批、文件、图片、错误和最终回答渲染协议。
- PostgreSQL 是所有权、分享关系和查询授权的唯一权威；不能回退到 JSON-only 授权。
- 分享角色仅为 `viewer`；管理员不自动读取其他用户私人会话。
- viewer 的所有写操作必须由后端拒绝，不能只隐藏前端控件。
- 无权访问统一返回 `404`；数据库或权限元数据不可用时失败关闭并返回明确 `503`。
- 旧会话文件不删除、不移动、不批量改写；补录必须幂等并报告异常。
- 使用非超级用户 `qwenpaw_runtime` 验证 RLS；连接池不得泄漏 `qwenpaw.user_id`。
- 不执行 Git 提交、推送、分支或物理删除，除非用户另行明确要求。
- 运行 Alembic `0009` 前必须按项目危险操作格式再次请求用户明确确认。
- 每项结束提供变更文件、测试结果、界面验收步骤和下一任务名称，等待确认。

---

## 文件与职责映射

| 文件 | 单一职责 |
| --- | --- |
| `migrations/versions/0009_conversation_sharing_rls.py` | 分享约束、数据库权限函数和 RLS 策略 |
| `src/qwenpaw/persistence/database.py` | 事务级请求用户上下文 |
| `src/qwenpaw/app/chats/repo/conversation.py` | 访问角色、成员和 Repository 契约 |
| `src/qwenpaw/app/chats/repo/postgres_repo.py` | PostgreSQL 会话范围查询和成员持久化 |
| `src/qwenpaw/app/chats/access.py` | owner/viewer 读取与写入判定 |
| `src/qwenpaw/app/chats/backfill.py` | 现有 `chats.json` 幂等补录及报告 |
| `src/qwenpaw/app/chats/api.py` | 范围查询、分享 API 和会话写授权 |
| `src/qwenpaw/app/routers/console.py` | 发送、停止、上传等 Console 写入口保护 |
| `src/qwenpaw/app/routers/approval.py` | 审批决定的会话所有者校验 |
| `src/qwenpaw/app/workspace/service_factories.py` | 新会话即时登记与补录服务装配 |
| `console/src/api/types/chat.ts` | owner/viewer、成员和候选人类型 |
| `console/src/api/modules/chat.ts` | scope 与分享接口客户端 |
| `console/src/pages/Chat/components/ChatSessionDrawer/*` | 会话范围筛选、只读标识和菜单控制 |
| `console/src/pages/Chat/components/ConversationShareDialog.tsx` | 所有者分享成员管理 |
| `console/src/pages/Chat/index.tsx` | 详情页统一只读状态 |
| `console/src/pages/Control/Sessions/*` | 会话管理页筛选、标识和分享入口 |
| `tests/integration/test_conversation_rls.py` | 真实 PostgreSQL RLS 与连接池隔离 |
| `tests/integration/test_conversation_sharing.py` | 分享完整生命周期 |
| `tests/integration/test_conversation_backfill.py` | 旧会话补录和幂等性 |
| `tests/isolation/test_chat_user_isolation.py` | HTTP/Console 跨用户隔离 |

---

### Task 5.3-A：所有者会话权威与“我的会话”可视化基线

**Visible deliverable:** 管理员和普通用户登录后，在会话抽屉及“会话”管理页看到“我的会话”；列表仅显示本人会话，原内容和操作保持正常。

**Files:**
- Create: `migrations/versions/0009_conversation_sharing_rls.py`
- Create: `src/qwenpaw/app/chats/backfill.py`
- Create: `tests/integration/test_conversation_rls.py`
- Create: `tests/integration/test_conversation_backfill.py`
- Create: `tests/unit/app/chats/test_conversation_access.py`
- Modify: `src/qwenpaw/persistence/database.py`
- Modify: `src/qwenpaw/persistence/repository_provider.py`
- Modify: `src/qwenpaw/app/chats/repo/conversation.py`
- Modify: `src/qwenpaw/app/chats/repo/postgres_repo.py`
- Modify: `src/qwenpaw/app/chats/access.py`
- Modify: `src/qwenpaw/app/chats/models.py`
- Modify: `src/qwenpaw/app/chats/api.py`
- Modify: `src/qwenpaw/app/workspace/service_factories.py`
- Modify: `console/src/api/types/chat.ts`
- Modify: `console/src/api/modules/chat.ts`
- Modify: `console/src/pages/Chat/components/ChatSessionDrawer/useSessionListData.ts`
- Modify: `console/src/pages/Chat/components/ChatSessionDrawer/index.tsx`
- Modify: `console/src/pages/Control/Sessions/useSessions.ts`
- Modify: `console/src/pages/Control/Sessions/index.tsx`
- Modify: `console/src/locales/zh.json`
- Modify: `console/src/locales/en.json`

**Interfaces:**
- Produces `ConversationAccessRole = Literal["owner", "viewer"]`。
- Produces `ConversationAccessRecord(conversation, access_role, shared_by_username)`。
- Produces `list_conversations_for_user(*, user_id: UUID, scope: Literal["all", "owned", "shared"])`。
- Produces `set_request_user(session: AsyncSession, user_id: UUID) -> None`。
- Produces `BackfillReport(scanned, inserted, updated, skipped, ambiguous)`。
- DTO 增加 `access_role`、`read_only`、`shared_by`。

- [ ] **Step 1: Write failing RLS, ownership and backfill tests**

```python
async def test_owner_sees_only_owned_conversations(repository):
    rows = await repository.list_conversations_for_user(
        user_id=user_a.id,
        scope="owned",
    )
    assert all(row.conversation.owner_user_id == user_a.id for row in rows)
    assert all(row.access_role == "owner" for row in rows)
```

同时验证：RLS 隐藏其他用户会话、连接复用不继承身份、补录重复执行无重复、`default` 仅映射到可明确识别的 Agent 所有者、歧义记录不改写且进入报告。

- [ ] **Step 2: Run RED tests**

Run:

```powershell
pytest tests/integration/test_conversation_rls.py tests/integration/test_conversation_backfill.py tests/unit/app/chats/test_conversation_access.py -v
```

Expected: FAIL because revision `0009`, access records, RLS context and backfill do not exist.

- [ ] **Step 3: Implement migration and request identity without applying it**

Migration must restrict member roles to `viewer`, add lookup indexes, define fail-closed current-user helpers, and force RLS on conversations, runs, messages, run_events, tool_calls, attachments and approval_requests. Owner reads/writes; currently valid viewer only reads. Viewer validity requires active user and current Agent owner/member/public access，且排除 `historical_read_only`。

`set_request_user` uses parameterized `set_config('qwenpaw.user_id', ..., true)` inside the current transaction, with no process-global state.

- [ ] **Step 4: Request dangerous-operation confirmation**

Before `alembic upgrade head`, use the project warning format. State that the operation changes the `qwenpaw` schema and can block application queries if policies are wrong. Stop until explicit confirmation.

- [ ] **Step 5: Apply migration and verify runtime role**

Run after confirmation:

```powershell
alembic upgrade head
pytest tests/integration/test_conversation_rls.py -v
```

Expected: current revision is `0009_conversation_sharing_rls`; `qwenpaw_runtime` cannot cross-read or cross-write.

- [ ] **Step 6: Implement owner Repository, backfill and immediate registration**

Backfill existing ChatSpecs without altering files. New empty chats register PostgreSQL metadata before the API returns. Missing PostgreSQL authority cannot fall back to an unfiltered JSON list. Update `EXPECTED_SCHEMA_REVISION` only after migration tests pass.

- [ ] **Step 7: Add `scope=owned` and visible owner filters**

Expose “全部/我的” in both session surfaces. Before sharing exists both counts may be equal. Preserve active/archived tabs and owner menus.

- [ ] **Step 8: Run backend and frontend verification**

```powershell
pytest tests/unit/app/chats tests/integration/test_conversation_rls.py tests/integration/test_conversation_backfill.py tests/integration/test_chats_agent_scoped.py -v
Set-Location console
npm run test:run -- src/pages/Chat/components/ChatSessionDrawer src/pages/Control/Sessions
npm run build
```

**User acceptance:** 管理员与普通用户分别确认“我的会话”只显示本人数据；旧会话的消息和工具过程仍完整；新建空会话无需发送消息也立即出现。

---

### Task 5.3-B：所有者分享管理 API 与分享对话框

**Visible deliverable:** 所有者可从抽屉和“会话”管理页打开“分享会话”，选择当前有 Agent 使用权限的用户并撤销分享。

**Files:**
- Create: `console/src/pages/Chat/components/ConversationShareDialog.tsx`
- Create: `console/src/pages/Chat/components/ConversationShareDialog.test.tsx`
- Create: `tests/unit/app/chats/test_sharing_api.py`
- Create: `tests/integration/test_conversation_sharing.py`
- Modify: `src/qwenpaw/app/chats/repo/conversation.py`
- Modify: `src/qwenpaw/app/chats/repo/postgres_repo.py`
- Modify: `src/qwenpaw/app/chats/api.py`
- Modify: `console/src/api/types/chat.ts`
- Modify: `console/src/api/modules/chat.ts`
- Modify: `console/src/pages/Chat/components/ChatSessionDrawer/index.tsx`
- Modify: `console/src/pages/Control/Sessions/components/columns.tsx`
- Modify: `console/src/pages/Control/Sessions/index.tsx`
- Modify: `console/src/locales/zh.json`
- Modify: `console/src/locales/en.json`

**Interfaces:**
- Produces `ConversationMemberRecord`、`ShareCandidate`。
- Produces `list_members`、`list_share_candidates`、`add_viewer`、`remove_viewer`。
- Produces:

```http
GET    /api/chats/{chat_id}/members
GET    /api/chats/{chat_id}/share-candidates
POST   /api/chats/{chat_id}/members
DELETE /api/chats/{chat_id}/members/{user_id}
```

- [ ] **Step 1: Write failing API and component tests**

Test inclusion of eligible active users; exclusion of owner, disabled user, existing member and user lacking Agent access; duplicate add idempotency; immediate revoke; non-owner member management returns `404`.

```tsx
expect(screen.getByText("仅查看")).toBeInTheDocument();
await user.click(screen.getByRole("button", { name: "添加成员" }));
expect(chatApi.addViewer).toHaveBeenCalledWith(chatId, candidate.user_id);
```

- [ ] **Step 2: Run RED tests**

```powershell
pytest tests/unit/app/chats/test_sharing_api.py tests/integration/test_conversation_sharing.py -v
Set-Location console
npm run test:run -- src/pages/Chat/components/ConversationShareDialog.test.tsx
```

- [ ] **Step 3: Implement member Repository and API**

Recheck owner, recipient active state and current Agent permission in the mutation transaction. Sharing never creates Agent membership. Viewer cannot enumerate other members.

- [ ] **Step 4: Implement owner-only dialog and row actions**

Load members/candidates when opened; label role “仅查看”; refresh after add/remove; do not grant optimistic access. Owner rows gain “分享会话”; viewer rows never show it.

- [ ] **Step 5: Run verification**

```powershell
pytest tests/unit/app/chats/test_sharing_api.py tests/integration/test_conversation_sharing.py -v
Set-Location console
npm run test:run -- src/pages/Chat/components/ConversationShareDialog.test.tsx src/pages/Chat/components/ChatSessionDrawer src/pages/Control/Sessions
npm run build
```

**User acceptance:** A 的候选人只出现符合资格的 B；添加后显示 B/仅查看；重复添加无重复；撤销后立即消失。

---

### Task 5.3-C：分享会话列表与完整只读历史

**Visible deliverable:** B 在“分享给我的”看到“只读分享”，能查看原始消息、Thinking、工具过程、审批历史、文件、图片、错误和最终回答，但没有所有者操作。

**Files:**
- Modify: `src/qwenpaw/app/chats/repo/postgres_repo.py`
- Modify: `src/qwenpaw/app/chats/api.py`
- Modify: `src/qwenpaw/app/chats/models.py`
- Modify: `console/src/api/types/chat.ts`
- Modify: `console/src/api/modules/chat.ts`
- Modify: `console/src/pages/Chat/components/ChatSessionDrawer/useSessionListData.ts`
- Modify: `console/src/pages/Chat/components/ChatSessionDrawer/index.tsx`
- Modify: `console/src/pages/Chat/index.tsx`
- Modify: `console/src/pages/Control/Sessions/useSessions.ts`
- Modify: `console/src/pages/Control/Sessions/index.tsx`
- Modify: `console/src/pages/Control/Sessions/components/columns.tsx`
- Modify: `console/src/locales/zh.json`
- Modify: `console/src/locales/en.json`
- Modify: `tests/integration/test_conversation_sharing.py`
- Modify: `console/src/pages/Chat/ChatPage.test.tsx`
- Modify: `console/src/pages/Chat/chatEventContract.test.tsx`

**Interfaces:**
- Completes `GET /api/chats?scope=all|owned|shared`。
- Chat DTO exposes `access_role`、`read_only`、`shared_by`。
- Produces `isConversationReadOnly(chat) -> boolean` as the single frontend derivation.

- [ ] **Step 1: Write failing list and rich-history tests**

Backend asserts `all = owned ∪ shared`, unshared B/C/admin get `404`, and viewer receives the same rich history projection. Frontend asserts the read-only badge and original tool cards render while owner menus do not.

- [ ] **Step 2: Run RED tests**

```powershell
pytest tests/integration/test_conversation_sharing.py -v
Set-Location console
npm run test:run -- src/pages/Chat/ChatPage.test.tsx src/pages/Chat/chatEventContract.test.tsx src/pages/Chat/components/ChatSessionDrawer src/pages/Control/Sessions
```

- [ ] **Step 3: Implement authorized content projection and scopes**

PostgreSQL first determines visible ChatSpecs. Only after access succeeds, reuse existing `SafeJSONSession`/history parsing. Do not create another message renderer or alter event payloads.

- [ ] **Step 4: Add filters, labels and read-only presentation**

Both surfaces show “全部/我的/分享给我的”. Viewer rows show “只读分享”和分享来源. Detail page displays a banner and removes owner menus; sender is visibly disabled. Exhaustive backend mutation guards are completed in 5.3-D.

- [ ] **Step 5: Verify event fidelity and build**

```powershell
pytest tests/parity/test_chat_event_contract.py tests/integration/test_conversation_sharing.py -v
Set-Location console
npm run test:run -- src/pages/Chat/ChatPage.test.tsx src/pages/Chat/chatEventContract.test.tsx src/pages/Chat/components/ChatSessionDrawer src/pages/Control/Sessions
npm run build
```

**User acceptance:** B 查看 A 的完整工具执行会话；输入区不可用，重命名、置顶、归档、删除、分享不可见；C 与未分享的管理员无法看到或打开。

---

### Task 5.3-D：所有写入口后端封锁与 Agent 权限联动

**Visible deliverable:** viewer 即使构造请求也不能发送、停止、审批、上传或修改；撤销 Agent 权限后共享会话立即失效，恢复后原分享恢复只读。

**Files:**
- Modify: `src/qwenpaw/app/chats/access.py`
- Modify: `src/qwenpaw/app/chats/api.py`
- Modify: `src/qwenpaw/app/routers/console.py`
- Modify: `src/qwenpaw/app/routers/approval.py`
- Modify: `console/src/pages/Chat/index.tsx`
- Modify: `console/src/pages/Chat/components/ChatActionGroup/index.tsx`
- Modify: `console/src/pages/Chat/ModelSelector/index.tsx`
- Modify: `console/src/pages/Chat/components/WhisperSpeechButton/index.tsx`
- Modify: `console/src/features/project-directory/SessionProjectDirectory.tsx`
- Modify: `tests/isolation/test_chat_user_isolation.py`
- Modify: `tests/unit/app/routers/test_console_chat_task.py`
- Modify: `tests/unit/app/routers/test_console_chat_reconnect.py`
- Modify: `tests/integration/test_conversation_sharing.py`

**Interfaces:**
- All mutation routes call `require_chat_access(..., write=True)` with authenticated actor and explicit conversation ID.
- Console request context carries `conversation_id`; request `user_id` never establishes ownership.

- [ ] **Step 1: Write failing direct-request tests**

For B attempt update/delete/archive/send/stop/approve/deny/upload/model/project-directory operations and assert `404` plus no state change to A’s conversation.

- [ ] **Step 2: Run RED tests**

```powershell
pytest tests/isolation/test_chat_user_isolation.py tests/unit/app/routers/test_console_chat_task.py tests/unit/app/routers/test_console_chat_reconnect.py tests/integration/test_conversation_sharing.py -v
```

- [ ] **Step 3: Protect every backend mutation path**

Stop fallback from session ID to chat UUID must recheck the resolved UUID. Approval endpoints derive conversation from the pending request. Uploads tied to an existing conversation require owner access. Never trust body `user_id`.

- [ ] **Step 4: Complete frontend control isolation**

Drive sender, attachment, voice, model, project directory, stop and approval controls from the same `read_only` value; do not duplicate ownership calculations.

- [ ] **Step 5: Add dynamic Agent access revalidation**

Every read rechecks current Agent access. Revoking membership/unpublishing invalidates the share without deleting `conversation_members`; restoring access reactivates it.

- [ ] **Step 6: Run verification**

```powershell
pytest tests/isolation/test_chat_user_isolation.py tests/integration/test_conversation_sharing.py tests/integration/test_console.py -v
Set-Location console
npm run test:run -- src/pages/Chat/ChatPage.test.tsx src/pages/Chat/components/ChatActionGroup src/pages/Chat/ModelSelector src/features/project-directory
npm run build
```

**User acceptance:** B 的所有写控件不可用，直接 API 请求仍被拒绝；撤销 B 的 Agent 权限后页面失效，恢复后重新只读可见，分享记录未自动删除。

---

### Task 5.3-E：撤销即时失效、综合回归与验收报告

**Visible deliverable:** A 撤销分享后，B 的列表和已打开详情立即失效；所有者原对话功能、富事件渲染和 PostgreSQL 持久化保持正常。

**Files:**
- Modify: `tests/integration/test_conversation_sharing.py`
- Modify: `tests/integration/test_conversation_rls.py`
- Modify: `tests/isolation/test_chat_user_isolation.py`
- Modify: viewer revocation handling in Chat drawer and Chat page files from 5.3-C
- Create: `docs/project-audit/43-任务5.3-会话分享与查询隔离验收报告.md`

**Interfaces:**
- Consumes Tasks 5.3-A through 5.3-D.
- Produces reproducible migration/backfill results, test evidence and two-user acceptance record.

- [ ] **Step 1: Add revoke-while-open tests**

Simulate B loading a shared chat, A revoking membership, and B refreshing list/detail. Assert UI removes the session, redirects or closes the invalid detail, clears stale messages, and never leaves an editable cached copy.

- [ ] **Step 2: Run complete affected backend suite**

```powershell
pytest tests/unit/app/chats tests/isolation/test_chat_user_isolation.py tests/integration/test_conversation_sharing.py tests/integration/test_conversation_rls.py tests/integration/test_conversation_backfill.py tests/integration/test_postgres_chat_events.py tests/contract/channels/test_console_contract.py tests/parity/test_chat_event_contract.py -v
```

- [ ] **Step 3: Run frontend suite and production build**

```powershell
Set-Location console
npm run test:run
npm run build:prod
```

- [ ] **Step 4: Execute two-user visual acceptance**

1. A creates a conversation containing a tool call.
2. A shares it with B.
3. B sees complete read-only history under “分享给我的”.
4. C and unshared admin cannot see/open it.
5. B cannot write through UI or direct API.
6. A revokes B; B’s list and open page immediately lose access.
7. A re-shares, then Agent access is revoked/restored to verify linkage.
8. A’s send/stop/approve/rename/pin/archive/delete/model/project-directory flows remain normal.

- [ ] **Step 5: Write acceptance report and stop**

Record migration revision, runtime role, backfill counts, tests, UI steps, known limits and rollback considerations. State explicitly: viewer live SSE belongs to Task 5.4; full PostgreSQL history replay belongs to Task 5.5. Do not start either without confirmation.

**User acceptance:** 用户按报告完成流程并确认 Task 5.3 后，才进入 Task 5.4。

---

## Execution order and confirmation gates

严格按 `5.3-A -> 5.3-B -> 5.3-C -> 5.3-D -> 5.3-E` 执行。

每项结束必须汇报修改文件、测试结果、可观察界面效果、数据库/兼容性风险和下一项准确名称。任何任务不得越过用户确认门自动继续。
