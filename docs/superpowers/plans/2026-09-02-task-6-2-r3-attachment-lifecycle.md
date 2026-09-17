# Task 6.2-R/3 附件生命周期与 Agent 资料 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 本项目按用户要求在当前目录内逐项执行，每项完成后停止并等待人工验收，不创建工作树，不执行 Git 提交。

**Goal:** 将会话上传文件区分为临时附件和当前用户、当前 Agent 的长期资料，提供保存、移动、清理和会话删除联动，并保持公用/仅使用 Agent 的个人运行空间与 Agent 公共工作区严格隔离。

**Architecture:** PostgreSQL `attachments` 表保存生命周期与归属，文件正文保留在受控运行目录。后端以独立附件服务完成路径校验、原子移动和数据库补偿，前端通过附件 ID 调用能力接口并局部刷新。原有消息、工具过程、附件预览和工作区编辑链保持不变。

**Tech Stack:** Python 3.11+、FastAPI、Pydantic、SQLAlchemy AsyncSession、Alembic、PostgreSQL RLS、React 18、TypeScript 5.8、Ant Design、Vitest、pytest。

## Global Constraints

- 仅管理“当前用户 + 当前 Agent”的临时附件和长期资料。
- 跨 Agent 个人资料库属于 Task 6.2-R/4，不在本计划实现。
- Agent 工具产物生命周期属于 Task 6.2-R/5；本计划只初始化并展示 `产物/` 目录。
- 不实现按时间自动过期、后台自动清理或管理员代管用户个人资料。
- 公用或仅使用 Agent 的公共工作区前后端继续只读；用户只能修改自己的个人运行空间。
- owner/collaborator 也不能读取其他用户的个人运行空间。
- 越权的用户、Agent 或附件 ID 统一返回 404，避免泄露资源存在性。
- 保存采用移动而非复制，附件 ID、来源会话和来源消息保持不变。
- 所有相对路径由后端校验，拒绝绝对路径、`..`、Windows 盘符、符号链接逃逸和跨根目录目标。
- 已删除附件保留元数据；物理文件不存在时不再允许下载、保存或移动。
- 不修改原有对话消息和工具执行过程的展示契约。
- 不新增依赖；不创建 Git 分支、工作树或提交。
- 每个任务完成后必须停止，由用户通过 UI 和验收命令确认后才能进入下一任务。
- 应用数据库迁移、删除测试文件或重启服务前，必须再次按危险操作格式取得明确确认。

---

## 文件结构与职责

### 后端新增

- `migrations/versions/0012_attachment_lifecycle.py`：新增生命周期字段、约束、索引及旧数据回填。
- `src/qwenpaw/app/attachments/__init__.py`：导出附件应用服务与 DTO。
- `src/qwenpaw/app/attachments/models.py`：列表、保存、移动、批量操作的请求和响应模型。
- `src/qwenpaw/app/attachments/service.py`：权限内附件查询、受控路径解析、原子移动、删除和补偿。
- `src/qwenpaw/app/routers/attachments.py`：`/console/attachments` 生命周期 API。
- `tests/unit/app/attachments/test_attachment_service.py`：文件事务、路径安全和状态转换测试。
- `tests/unit/app/routers/test_attachments_router.py`：身份、Agent 隔离、HTTP 状态和批量结果测试。
- `tests/integration/test_attachment_lifecycle.py`：真实 PostgreSQL 生命周期、RLS 与文件移动集成测试。

### 后端修改

- `src/qwenpaw/app/chats/repo/conversation.py`：扩展 `AttachmentRecord` 和 Repository 生命周期接口。
- `src/qwenpaw/app/chats/repo/postgres_repo.py`：实现生命周期查询和原子状态更新。
- `src/qwenpaw/app/chats/repo/json_conversation_repo.py`：保持 Legacy/单测 Repository 契约兼容。
- `src/qwenpaw/app/routers/console.py`：上传默认写入 `temporary`，下载拒绝 `deleted`。
- `src/qwenpaw/app/chats/api.py`：历史消息附加附件生命周期展示字段；删除会话联动临时附件清理。
- `src/qwenpaw/app/chats/manager.py`：会话删除与附件清理的应用层编排入口。
- `src/qwenpaw/app/routers/__init__.py`：注册附件路由。
- `src/qwenpaw/app/routers/agent_scoped.py`：在 Agent scoped API 下注册附件路由。
- `src/qwenpaw/workspaces/resolver.py`：集中初始化 `media/`、`资料/`、`产物/` 标准目录。
- `src/qwenpaw/services/workspace_files.py`：解析个人运行空间时确保标准目录存在。
- `tests/integration/test_migrations.py`：验证 `0012` 字段、约束、回填和降级边界。
- `tests/unit/app/chats/test_attachment_scope.py`：扩展附件生命周期和历史消息契约。
- `tests/isolation/test_workspace_resolver.py`：标准目录初始化及路径隔离。

### 前端新增

- `console/src/features/attachments/types.ts`：附件生命周期 DTO 和批量结果类型。
- `console/src/features/attachments/AttachmentLifecycleActions.tsx`：对话附件的状态徽标、保存与删除操作。
- `console/src/features/attachments/AttachmentLifecycleActions.test.tsx`：状态和操作行为测试。
- `console/src/features/files-workspace/TemporaryAttachmentsPanel.tsx`：按会话分组的临时附件列表与批量操作。
- `console/src/features/files-workspace/TemporaryAttachmentsPanel.test.tsx`：临时附件页面交互测试。
- `console/src/features/files-workspace/AgentDocumentsPanel.tsx`：`资料/` 目录树、移动、重命名和删除入口。
- `console/src/features/files-workspace/AgentDocumentsPanel.test.tsx`：资料管理交互与只读边界测试。
- `console/src/features/files-workspace/PersonalWorkspaceNavigator.tsx`：`临时附件 / Agent 资料 / 产物` 导航壳。
- `console/src/features/files-workspace/PersonalWorkspaceNavigator.test.tsx`：导航及局部刷新测试。

### 前端修改

- `console/src/api/modules/chat.ts`：删除会话清理参数及附件展示类型。
- `console/src/api/modules/chat.test.ts`：请求 URL、请求体和兼容行为测试。
- `console/src/api/modules/workspace.ts`：资料目录操作 API。
- `console/src/api/modules/workspace.test.ts`：资料 API 请求测试。
- `console/src/pages/Chat/index.tsx`：将附件生命周期动作接入用户消息附件卡，不改变消息和工具事件结构。
- `console/src/pages/Chat/ChatPage.test.tsx`：上传、保存、状态局部更新回归。
- `console/src/pages/Chat/sessionApi/index.ts`：保留附件 ID 和生命周期展示字段。
- `console/src/pages/Chat/components/ChatSessionDrawer/useSessionListData.ts`：删除确认框增加清理临时附件选项。
- `console/src/pages/Chat/components/ChatSessionDrawer/useSessionListData.test.ts`：默认勾选及参数传递测试。
- `console/src/pages/Chat/components/ChatSessionDrawer/index.tsx`：桌面会话抽屉删除确认交互。
- `console/src/pages/Chat/components/ChatSessionDrawer/ChatSessionDrawer.test.tsx`：抽屉删除验收测试。
- `console/src/pages/Files/index.tsx`：接入个人运行空间导航。
- `console/src/features/files-workspace/FilesWorkspace.tsx`：支持生命周期操作后的局部刷新和资料文件预览。
- `console/src/features/files-workspace/FilesNavigator.tsx`：保留原工作区、档案和记忆功能，不混入附件生命周期逻辑。
- `console/src/features/files-workspace/types.ts`：扩展个人资料文件目标类型。
- `console/src/pages/Files/index.module.less`、`console/src/features/files-workspace/FilesWorkspace.module.less`：新增导航、状态和批量工具栏样式。
- `console/src/locales/zh.json`、`console/src/locales/en.json`：新增附件生命周期与清理文案。

---

### Task R3-1：生命周期数据层、标准目录与临时附件可见列表

**可验收成果：** 登录后进入“文件”，可看到“临时附件 / Agent 资料 / 产物”三个入口；上传附件后能在“临时附件”看到记录，但本任务暂不开放保存、移动或删除。

**Files:**

- Create: `migrations/versions/0012_attachment_lifecycle.py`
- Create: `src/qwenpaw/app/attachments/models.py`
- Create: `src/qwenpaw/app/routers/attachments.py`
- Create: `console/src/features/attachments/types.ts`
- Create: `console/src/features/files-workspace/TemporaryAttachmentsPanel.tsx`
- Create: `console/src/features/files-workspace/PersonalWorkspaceNavigator.tsx`
- Modify: `src/qwenpaw/app/chats/repo/conversation.py`
- Modify: `src/qwenpaw/app/chats/repo/postgres_repo.py`
- Modify: `src/qwenpaw/app/chats/repo/json_conversation_repo.py`
- Modify: `src/qwenpaw/app/routers/console.py`
- Modify: `src/qwenpaw/app/routers/__init__.py`
- Modify: `src/qwenpaw/app/routers/agent_scoped.py`
- Modify: `src/qwenpaw/workspaces/resolver.py`
- Modify: `src/qwenpaw/services/workspace_files.py`
- Modify: `console/src/api/modules/chat.ts`
- Modify: `console/src/pages/Files/index.tsx`
- Modify: `console/src/locales/zh.json`
- Modify: `console/src/locales/en.json`
- Test: `tests/integration/test_migrations.py`
- Test: `tests/unit/app/chats/test_attachment_scope.py`
- Test: `tests/isolation/test_workspace_resolver.py`
- Test: `tests/unit/app/routers/test_attachments_router.py`
- Test: `console/src/api/modules/chat.test.ts`
- Test: `console/src/features/files-workspace/TemporaryAttachmentsPanel.test.tsx`
- Test: `console/src/features/files-workspace/PersonalWorkspaceNavigator.test.tsx`

**Interfaces:**

- Produces: `AttachmentLifecycle = Literal["temporary", "saved", "deleted"]`。
- Produces: `AttachmentRecord.lifecycle`, `saved_path`, `saved_at`, `deleted_at`, `updated_at`。
- Produces: `ConversationRepository.list_owned_attachments(*, owner_user_id: UUID, agent_id: UUID, lifecycle: AttachmentLifecycle | None = None, conversation_id: UUID | None = None) -> list[AttachmentRecord]`。
- Produces: `GET /api/console/attachments?lifecycle=temporary&conversation_id=<uuid>`。
- Produces: `WorkspaceResolver.ensure_standard_directories(resolved) -> Path`。

- [x] **Step 1: 写迁移失败测试**

```python
assert {
    "lifecycle", "saved_path", "saved_at", "deleted_at", "updated_at"
}.issubset(_table_columns(admin, schema, "attachments"))
assert admin.execute(
    f'SELECT lifecycle FROM "{schema}".attachments WHERE id = \'{attachment_id}\''
) == "temporary"
```

- [x] **Step 2: 运行迁移测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/integration/test_migrations.py -k attachment_lifecycle -q`

Expected: FAIL，提示缺少 `0012` 或 `lifecycle` 字段。

- [x] **Step 3: 编写 `0012` 迁移**

迁移必须：

```python
op.add_column("attachments", sa.Column(
    "lifecycle", sa.Text(), nullable=False, server_default="temporary"
))
op.add_column("attachments", sa.Column("saved_path", sa.Text(), nullable=True))
op.add_column("attachments", sa.Column("saved_at", sa.DateTime(timezone=True)))
op.add_column("attachments", sa.Column("deleted_at", sa.DateTime(timezone=True)))
op.add_column("attachments", sa.Column(
    "updated_at", sa.DateTime(timezone=True), nullable=False,
    server_default=sa.text("now()"),
))
op.create_check_constraint(
    "ck_attachments_lifecycle",
    "attachments",
    "lifecycle IN ('temporary', 'saved', 'deleted')",
)
```

同时创建 `(owner_user_id, agent_id, lifecycle, created_at)` 索引。降级前若存在非 `temporary` 记录则抛出 `attachment_lifecycle_prevents_downgrade`，避免静默丢失状态。

- [x] **Step 4: 扩展 Repository 模型和查询契约**

```python
AttachmentLifecycle = Literal["temporary", "saved", "deleted"]

class AttachmentRecord(_Record):
    # 原字段保持不变
    lifecycle: AttachmentLifecycle = "temporary"
    saved_path: str | None = None
    saved_at: datetime | None = None
    deleted_at: datetime | None = None
    updated_at: datetime
```

`PostgresConversationRepository` 与 `JsonConversationRepository` 必须返回同一结构；上传时显式写入 `temporary` 与统一时间戳。

- [x] **Step 5: 写标准目录初始化失败测试**

```python
root = resolver.ensure_standard_directories(runtime)
assert (root / "media").is_dir()
assert (root / "资料").is_dir()
assert (root / "产物").is_dir()
```

测试同时构造根目录外符号链接，确认初始化不会跟随链接写出工作区。

- [x] **Step 6: 实现标准目录初始化**

`ensure_standard_directories()` 先调用现有 `ensure()`，再逐个创建固定目录；仅接受可写的 `USER_RUNTIME`、`DRAFT` 或已登记 Legacy 工作区，拒绝 `PUBLISHED_BASELINE`。

- [x] **Step 7: 写列表 API 失败测试**

覆盖：当前用户当前 Agent 可见、其他用户 404/空列表、其他 Agent 空列表、`deleted` 不默认返回、响应不包含绝对 `storage_key`。

```python
response = client.get(
    "/api/console/attachments?lifecycle=temporary",
    headers={"Authorization": token, "X-Agent-Id": "agent-a"},
)
assert response.status_code == 200
assert response.json()[0]["original_name"] == "report.pdf"
assert "storage_key" not in response.json()[0]
```

- [x] **Step 8: 实现只读列表 API**

响应 DTO 包含：`id`、`agent_id`、`conversation_id`、`message_id`、`original_name`、`media_type`、`size`、`lifecycle`、`saved_path`、`saved_at`、`deleted_at`、`created_at`、`updated_at`、`download_url`、`can_save`、`can_move`、`can_delete`。

- [x] **Step 9: 写并实现前端 API 与三入口导航测试**

```ts
expect(screen.getByRole("tab", { name: "临时附件" })).toBeVisible();
expect(screen.getByRole("tab", { name: "Agent 资料" })).toBeVisible();
expect(screen.getByRole("tab", { name: "产物" })).toBeVisible();
expect(await screen.findByText("report.pdf")).toBeVisible();
```

`TemporaryAttachmentsPanel` 本任务只负责查询和展示，不提供变更操作；`产物` 只显示目录与“产物生命周期将在 Task 6.2-R/5 管理”的说明，不实现额外元数据。

- [ ] **Step 10: 验证 Task R3-1**

Run:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_migrations.py tests/unit/app/chats/test_attachment_scope.py tests/unit/app/routers/test_attachments_router.py tests/isolation/test_workspace_resolver.py -q
Set-Location "console"; npm run test:run -- src/api/modules/chat.test.ts src/features/files-workspace/TemporaryAttachmentsPanel.test.tsx src/features/files-workspace/PersonalWorkspaceNavigator.test.tsx
npm run build
```

人工验收：管理员和普通用户分别选择同一公用 Agent，上传不同文件；两人只能在自己的“临时附件”看到自己的文件。完成后停止，等待用户确认。

> 执行迁移前必须再次请求数据库结构变更确认。

---

### Task R3-2：保存到 Agent 资料与对话附件状态卡

**可验收成果：** 对话中的临时附件显示“临时”与“保存到资料”；点击后文件移动到 `资料/`，卡片变成“已保存”，历史消息仍可下载。

**Files:**

- Create: `src/qwenpaw/app/attachments/service.py`
- Create: `tests/unit/app/attachments/test_attachment_service.py`
- Create: `console/src/features/attachments/AttachmentLifecycleActions.tsx`
- Create: `console/src/features/attachments/AttachmentLifecycleActions.test.tsx`
- Modify: `src/qwenpaw/app/attachments/models.py`
- Modify: `src/qwenpaw/app/routers/attachments.py`
- Modify: `src/qwenpaw/app/chats/repo/conversation.py`
- Modify: `src/qwenpaw/app/chats/repo/postgres_repo.py`
- Modify: `src/qwenpaw/app/chats/repo/json_conversation_repo.py`
- Modify: `src/qwenpaw/app/chats/api.py`
- Modify: `src/qwenpaw/app/routers/console.py`
- Modify: `console/src/api/modules/chat.ts`
- Modify: `console/src/pages/Chat/sessionApi/index.ts`
- Modify: `console/src/pages/Chat/index.tsx`
- Modify: `console/src/pages/Chat/ChatPage.test.tsx`

**Interfaces:**

- Consumes: Task R3-1 生命周期字段、列表 API 和标准目录。
- Produces: `AttachmentLifecycleService.save_to_documents(*, attachment_id: UUID, owner_user_id: UUID, agent_id: UUID, target_path: str | None = None) -> AttachmentRecord`。
- Produces: `POST /api/console/attachments/{id}/save`，请求 `{ "target_path": "子目录/report.pdf" | null }`。
- Produces: `POST /api/console/attachments/batch-save`，请求 `{ "attachment_ids": ["aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"], "target_directory": "项目A" }`；保存到资料根目录时 `target_directory` 为 `null`。

- [ ] **Step 1: 写保存事务失败测试**

覆盖默认目标、子目录、目标冲突、非 `temporary`、源缺失、路径穿越、符号链接逃逸和数据库更新失败回滚。

```python
saved = await service.save_to_documents(
    attachment_id=ATTACHMENT_ID,
    owner_user_id=USER_ID,
    agent_id=AGENT_ID,
    target_path=None,
)
assert saved.lifecycle == "saved"
assert saved.saved_path == "report.pdf"
assert not source.exists()
assert (workspace / "资料" / "report.pdf").read_bytes() == payload
```

- [ ] **Step 2: 运行服务测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/app/attachments/test_attachment_service.py -q`

Expected: FAIL，服务模块或方法不存在。

- [ ] **Step 3: 实现受控路径和原子移动**

服务只接收 Repository、workspace root 和 clock。移动顺序固定为：锁定记录 → 校验状态/源 → 解析目标 → `Path.replace()` → Repository 更新；更新失败时执行反向 `replace()`。补偿失败写入错误日志但不泄露绝对路径给客户端。

- [ ] **Step 4: 实现单个和批量保存 API**

批量响应逐项返回：

```json
{
  "items": [
    {"attachment_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "status": "saved", "attachment": {}},
    {"attachment_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", "status": "failed", "error_code": "target_conflict"}
  ]
}
```

单个冲突返回 409；越权和跨 Agent 返回 404。

- [ ] **Step 5: 扩展历史消息附件展示元数据**

`GET /chats/{id}` 在不改变原消息内容类型的前提下，为受保护附件 URL 对应内容项补入：

```json
{
  "attachment_id": "uuid",
  "attachment_lifecycle": "saved",
  "attachment_saved_path": "report.pdf"
}
```

不得删除或重排原文本、工具调用和工具结果事件。

- [ ] **Step 6: 写前端状态动作失败测试**

```ts
expect(screen.getByText("临时")).toBeVisible();
await user.click(screen.getByRole("button", { name: "保存到资料" }));
expect(api.saveAttachment).toHaveBeenCalledWith(id, undefined);
expect(await screen.findByText("已保存")).toBeVisible();
```

同时测试失败、409 和重复点击禁用状态。

- [ ] **Step 7: 接入 Chat 附件卡并局部更新**

使用 `AttachmentLifecycleActions` 包裹现有附件预览区域；保存成功只更新当前消息内容项，不调用 `window.location.reload()`、不清空 SDK 消息数组、不影响工具过程卡片。

- [ ] **Step 8: 验证 Task R3-2**

Run:

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/app/attachments/test_attachment_service.py tests/unit/app/routers/test_attachments_router.py tests/unit/app/chats/test_attachment_scope.py -q
Set-Location "console"; npm run test:run -- src/features/attachments/AttachmentLifecycleActions.test.tsx src/pages/Chat/ChatPage.test.tsx src/api/modules/chat.test.ts
npm run build
```

人工验收：上传 PDF → 发送消息 → 点击“保存到资料” → 卡片变为“已保存” → 刷新并重新进入会话仍显示已保存且可下载。完成后停止等待确认。

---

### Task R3-3：临时附件单个/批量保存与显式清理

**可验收成果：** “文件 → 临时附件”按会话分组，支持选择、批量保存、单个删除和批量清理；清理后历史消息显示“文件已清理”。

**Files:**

- Modify: `console/src/features/files-workspace/TemporaryAttachmentsPanel.tsx`
- Modify: `console/src/features/files-workspace/TemporaryAttachmentsPanel.test.tsx`
- Modify: `src/qwenpaw/app/attachments/service.py`
- Modify: `src/qwenpaw/app/attachments/models.py`
- Modify: `src/qwenpaw/app/routers/attachments.py`
- Modify: `src/qwenpaw/app/chats/repo/conversation.py`
- Modify: `src/qwenpaw/app/chats/repo/postgres_repo.py`
- Modify: `src/qwenpaw/app/chats/repo/json_conversation_repo.py`
- Modify: `src/qwenpaw/app/chats/api.py`
- Modify: `src/qwenpaw/app/routers/console.py`
- Modify: `console/src/api/modules/chat.ts`
- Modify: `console/src/features/files-workspace/PersonalWorkspaceNavigator.tsx`
- Modify: `console/src/pages/Chat/index.tsx`

**Interfaces:**

- Consumes: R3-2 保存服务与批量结果响应。
- Produces: `AttachmentLifecycleService.delete_attachment(*, attachment_id: UUID, owner_user_id: UUID, agent_id: UUID) -> AttachmentRecord`。
- Produces: `DELETE /api/console/attachments/{id}`。
- Produces: `POST /api/console/attachments/batch-delete`，请求 `{ "attachment_ids": ["aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"] }`。

- [ ] **Step 1: 写删除状态测试**

```python
deleted = await service.delete_attachment(
    attachment_id=ATTACHMENT_ID,
    owner_user_id=USER_ID,
    agent_id=AGENT_ID,
)
assert deleted.lifecycle == "deleted"
assert deleted.deleted_at is not None
assert not source.exists()
deleted_again = await service.delete_attachment(
    attachment_id=ATTACHMENT_ID,
    owner_user_id=USER_ID,
    agent_id=AGENT_ID,
)
assert deleted_again == deleted  # 幂等
```

分别验证由 `temporary` 删除时 `saved_path/saved_at` 为空，由 `saved` 删除时两字段保留。

- [ ] **Step 2: 实现删除与批量删除 API**

物理删除成功后标记 `deleted`；源文件本就不存在时也标记 `deleted` 并返回幂等成功。批量接口逐项报告，任何一项失败不回滚其他成功项。

- [ ] **Step 3: 写临时附件面板失败测试**

测试会话标题分组、无会话待发送分组、选择框、批量保存、批量清理、确认框、部分失败结果和局部刷新。

- [ ] **Step 4: 实现临时附件面板**

列表不显示 `deleted`；删除操作必须二次确认。批量结果通过成功/失败计数反馈，失败项保持选中，成功项从临时列表移除。

- [ ] **Step 5: 更新历史卡片删除状态**

正式字段统一使用 `attachment_lifecycle`。值为 `deleted` 且 `attachment_saved_path` 为空时显示“文件已清理”，有值时显示“资料已删除”，并隐藏下载和预览按钮。

- [ ] **Step 6: 验证 Task R3-3**

Run:

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/app/attachments/test_attachment_service.py tests/unit/app/routers/test_attachments_router.py tests/unit/app/chats/test_attachment_scope.py -q
Set-Location "console"; npm run test:run -- src/features/files-workspace/TemporaryAttachmentsPanel.test.tsx src/features/attachments/AttachmentLifecycleActions.test.tsx src/pages/Chat/ChatPage.test.tsx
npm run build
```

人工验收：同一会话上传三个文件，批量保存两个、清理一个；临时列表变空，资料列表出现两个，历史消息分别显示“已保存”和“文件已清理”。完成后停止等待确认。

---

### Task R3-4：Agent 资料目录管理与后端强制隔离

**可验收成果：** “Agent 资料”展示当前用户、当前 Agent 的 `资料/` 树，支持新建目录、移动/重命名、下载和删除；切换用户或 Agent 后完全隔离。

**Files:**

- Create: `console/src/features/files-workspace/AgentDocumentsPanel.tsx`
- Create: `console/src/features/files-workspace/AgentDocumentsPanel.test.tsx`
- Modify: `src/qwenpaw/app/attachments/service.py`
- Modify: `src/qwenpaw/app/attachments/models.py`
- Modify: `src/qwenpaw/app/routers/attachments.py`
- Modify: `src/qwenpaw/app/routers/workspace.py`
- Modify: `src/qwenpaw/services/workspace_files.py`
- Modify: `console/src/api/modules/workspace.ts`
- Modify: `console/src/api/modules/workspace.test.ts`
- Modify: `console/src/features/files-workspace/PersonalWorkspaceNavigator.tsx`
- Modify: `console/src/features/files-workspace/FilesWorkspace.tsx`
- Modify: `console/src/features/files-workspace/types.ts`

**Interfaces:**

- Consumes: R3-2/R3-3 `saved` 附件记录与删除能力。
- Produces: `POST /api/console/attachments/{id}/move`，请求 `{ "target_path": "客户A/新名称.pdf" }`。
- Produces: `POST /api/workspace/document-directories`，请求 `{ "path": "客户A/资料" }`。
- Produces: 现有 `/workspace/tree`、`/workspace/file-content`、`/workspace/file-download` 在资料根下的受控复用。

- [ ] **Step 1: 写移动、重命名与目录创建失败测试**

覆盖同目录重命名、跨子目录移动、冲突 409、跨 `资料/` 目标 400、跨 Agent 404、符号链接拒绝、数据库失败反向移动。

- [ ] **Step 2: 实现资料移动 API**

`target_path` 必须包含文件名且相对 `资料/`。成功后更新 `storage_key`、`saved_path`、`updated_at`，不改变 ID、`saved_at`、`conversation_id` 或 `message_id`。

- [ ] **Step 3: 实现受控目录创建 API**

仅允许当前用户个人运行空间的 `资料/` 子目录。公用 Agent 的公共 `workspace` root 即使前端伪造请求也必须返回 403/404，不允许创建目录。

- [ ] **Step 4: 写资料面板失败测试**

```ts
await user.click(screen.getByRole("button", { name: "新建文件夹" }));
await user.type(screen.getByLabelText("文件夹名称"), "客户A");
await user.click(screen.getByRole("button", { name: "创建" }));
expect(workspaceApi.createDocumentDirectory).toHaveBeenCalledWith("客户A");
```

继续测试移动、重命名、删除确认、预览、下载及只读公共工作区不出现编辑入口。

- [ ] **Step 5: 实现 Agent 资料面板**

资料树复用现有文件预览和下载能力，不复制 Monaco 或文件读取逻辑。生命周期操作成功后只刷新资料树与受影响卡片。

- [ ] **Step 6: 验证 Task R3-4**

Run:

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/app/attachments/test_attachment_service.py tests/unit/app/routers/test_attachments_router.py tests/isolation/test_workspace_file_api.py tests/unit/app/routers/test_workspace_files_router.py -q
Set-Location "console"; npm run test:run -- src/features/files-workspace/AgentDocumentsPanel.test.tsx src/features/files-workspace/PersonalWorkspaceNavigator.test.tsx src/api/modules/workspace.test.ts
npm run build
```

人工验收：用户 A 在公用 Agent 下新建 `客户A/` 并移动资料；用户 B 使用同一 Agent 看不到该目录；管理员以自己的账号也看不到 A 的个人资料。完成后停止等待确认。

---

### Task R3-5：删除会话时可选清理临时附件

**可验收成果：** 删除会话弹窗默认勾选“同时清理未保存的临时附件”；取消勾选时附件保留；已保存资料始终不受会话删除影响。

**Files:**

- Modify: `src/qwenpaw/app/chats/api.py`
- Modify: `src/qwenpaw/app/chats/manager.py`
- Modify: `src/qwenpaw/app/chats/repo/conversation.py`
- Modify: `src/qwenpaw/app/chats/repo/postgres_repo.py`
- Modify: `src/qwenpaw/app/chats/repo/json_conversation_repo.py`
- Modify: `src/qwenpaw/app/attachments/service.py`
- Modify: `console/src/api/modules/chat.ts`
- Modify: `console/src/api/modules/chat.test.ts`
- Modify: `console/src/pages/Chat/components/ChatSessionDrawer/useSessionListData.ts`
- Modify: `console/src/pages/Chat/components/ChatSessionDrawer/useSessionListData.test.ts`
- Modify: `console/src/pages/Chat/components/ChatSessionDrawer/index.tsx`
- Modify: `console/src/pages/Chat/components/ChatSessionDrawer/ChatSessionDrawer.test.tsx`
- Test: `tests/unit/app/chats/test_manager.py`
- Test: `tests/unit/app/chats/test_conversation_access.py`

**Interfaces:**

- Produces: `DELETE /api/chats/{chat_id}?cleanup_temporary_attachments=true|false`。
- Produces: `ChatManager.delete_chats(chat_ids, cleanup_temporary_attachments=True)`。
- Preserves: 现有 `POST /api/chats/batch-delete` 数组请求兼容；新增对象请求 `{ "chat_ids": ["77777777-7777-4777-8777-777777777777"], "cleanup_temporary_attachments": true }`。

- [ ] **Step 1: 写会话删除联动失败测试**

创建一个 `temporary` 和一个 `saved` 附件，删除会话后断言：临时文件被清理且状态为 `deleted`，保存资料仍为 `saved` 且物理文件存在。

- [ ] **Step 2: 实现后端删除编排**

先验证所有会话均为当前用户可写，再软删除会话，成功后清理选中的临时附件。这样会话删除失败时不会提前丢失文件；附件清理逐项失败时不得谎报全部成功，返回 `temporary_attachments_deleted` 与 `temporary_attachment_failures`。

- [ ] **Step 3: 保持“不清理”行为**

当 `cleanup_temporary_attachments=false` 时，临时附件保留其 `conversation_id` 与下载能力，仍可在文件页按“已删除会话”分组查看、保存或手动清理。

- [ ] **Step 4: 写前端删除确认失败测试**

```ts
expect(screen.getByRole("checkbox", {
  name: "同时清理未保存的临时附件",
})).toBeChecked();
await user.click(screen.getByRole("button", { name: "删除" }));
expect(chatApi.deleteChat).toHaveBeenCalledWith(chatId, {
  cleanupTemporaryAttachments: true,
});
```

- [ ] **Step 5: 实现桌面与列表删除入口**

所有现有会话删除入口共用同一个确认模型，避免一个入口默认清理、另一个静默保留。批量删除也显示相同选项。

- [ ] **Step 6: 验证 Task R3-5**

Run:

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/app/chats/test_manager.py tests/unit/app/chats/test_conversation_access.py tests/unit/app/attachments/test_attachment_service.py -q
Set-Location "console"; npm run test:run -- src/api/modules/chat.test.ts src/pages/Chat/components/ChatSessionDrawer/useSessionListData.test.ts src/pages/Chat/components/ChatSessionDrawer/ChatSessionDrawer.test.tsx
npm run build
```

人工验收执行两轮：第一轮保持默认勾选，确认临时附件清理而资料保留；第二轮取消勾选，确认临时附件仍可在文件页处理。完成后停止等待确认。

---

### Task R3-6：双用户浏览器回归、数据库对账与验收归档

**可验收成果：** 使用 Admin、Member A、Member B 完成真实浏览器隔离验收，并生成可复查的自动化报告；原对话、工具过程、共享/仅使用只读和附件预览无回归。

**Files:**

- Create: `scripts/verify_attachment_lifecycle.py`
- Create: `tests/e2e/test_attachment_lifecycle_browser.py`
- Create: `docs/acceptance/task-6-2-r3-attachment-lifecycle.md`
- Modify: `tests/integration/test_attachment_lifecycle.py`
- Modify: `tests/parity/test_chat_event_contract.py`
- Modify: `console/src/pages/Chat/chatEventContract.test.tsx`
- Modify: `docs/superpowers/plans/2026-09-02-task-6-2-r3-attachment-lifecycle.md`：只勾选实际完成步骤并记录验收结论。

**Interfaces:**

- Consumes: R3-1 至 R3-5 所有 API 和 UI。
- Produces: 只读对账命令 `verify_attachment_lifecycle.py --database-url-env "QWENPAW_DATABASE_URL" --workspace-root "E:/git_project/QwenPaw/tmp"`；实际连接串从受控环境变量读取，不写入报告或命令历史。
- Produces: 验收报告，记录测试账号 ID、Agent ID、附件 ID、生命周期、相对路径和测试结果，但不记录密码、Token、密钥或绝对用户文件内容。

- [ ] **Step 1: 写只读对账脚本测试**

脚本检查：数据库记录对应文件存在性、`temporary` 位于 `media/`、`saved` 位于 `资料/`、`deleted` 无物理文件、路径均处于正确用户和 Agent 根目录。脚本只报告，不修复、不删除。

- [ ] **Step 2: 写浏览器 E2E 场景**

顺序固定：

1. Member A 与 Member B 选择同一公用 Agent；
2. 各自上传同名文件；
3. A 保存并移动，B 无法看到 A 的记录；
4. B 删除临时附件，A 的资料不受影响；
5. Admin 使用自己的普通用户能力上传资料，不能看到 A/B 的个人资料；
6. 刷新页面、切换菜单、切换浏览器 Tab 后状态不丢失且不整页闪烁；
7. 对话历史仍展示文本、工具执行过程和附件状态。

- [ ] **Step 3: 运行完整定向回归**

Run:

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/app/attachments tests/unit/app/chats/test_attachment_scope.py tests/unit/app/routers/test_attachments_router.py tests/isolation/test_workspace_resolver.py tests/isolation/test_workspace_file_api.py tests/integration/test_attachment_lifecycle.py tests/parity/test_chat_event_contract.py -q
Set-Location "console"; npm run test:run -- src/features/attachments src/features/files-workspace src/pages/Chat/ChatPage.test.tsx src/pages/Chat/chatEventContract.test.tsx src/api/modules/chat.test.ts src/api/modules/workspace.test.ts
npm run build
```

- [ ] **Step 4: 运行数据库和磁盘只读对账**

Expected：退出码 0，`violations=0`。任何异常仅写入报告，不自动移动或删除用户数据。

- [ ] **Step 5: 完成人工浏览器验收**

浏览器验收必须保留截图或结构化步骤结果，分别证明：同用户同 Agent 生命周期闭环、跨用户隔离、跨 Agent 隔离、公用 Agent 公共工作区只读、会话删除选项、重启后持久化。

- [ ] **Step 6: 输出验收归档并停止**

报告明确列出：实现范围、未实现的 R/4 与 R/5 项、测试结果、已知环境限制、数据库迁移版本、服务端口和回滚注意事项。不得写“全部完成”除非所有自动化与人工验收均通过并由用户确认。

---

## 执行顺序与确认门

```text
R3-1 生命周期/目录/可见列表
  ↓ 用户验收
R3-2 保存到资料/对话卡
  ↓ 用户验收
R3-3 临时附件批量处理
  ↓ 用户验收
R3-4 Agent 资料目录管理
  ↓ 用户验收
R3-5 会话删除联动
  ↓ 用户验收
R3-6 双用户完整回归与归档
```

每个任务只在前一任务明确验收后开始。R3-1 应用数据库迁移前、任何需要删除验收数据的步骤前、重启服务前，均需独立危险操作确认。
