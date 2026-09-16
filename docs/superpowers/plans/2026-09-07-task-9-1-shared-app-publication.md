# Task 9.1 共享应用发布与用户运行实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现共享应用从 Agent 草稿、不可变提交、管理员审核发布到普通用户隔离运行和私人会话的完整闭环。

**Architecture:** 在现有四张共享应用表上增加必要约束和会话版本外键，以 `SharedAppRepository` 持久化事实、`PublicationSnapshotBuilder` 固化工作区、`PublicationDependencyValidator` 校验依赖、`SharedAppService` 执行状态机。用户启动时由服务端解析当前发布版本，创建每用户每版本运行空间和私人会话，并把可信发布模型传入现有模型与聊天事件链；前端在现有应用中心增加共享应用视图，并提供独立管理员审核页。

**Tech Stack:** Python 3.11–3.13、FastAPI、Pydantic v2、SQLAlchemy 2.x async、asyncpg、Alembic、PostgreSQL、React 18、TypeScript 5.8、Ant Design、Vitest、Playwright、pytest。

## Global Constraints

- 草稿可变；提交后的 `version`、`immutable_manifest`、`baseline_workspace_key`、`submitted_by` 和 `shared_app_id` 不可变。
- 审核和发布是两个独立动作，只有 `approved` 版本能成为当前版本。
- 新会话固定启动时的 publication；发布、下架和回滚不重写旧会话。
- 发布运行模型只能由服务端数据库事实构造 `TrustedPublication`，客户端无法覆盖。
- 工作区按 `user_id + shared_app_id + publication_id` 隔离；发布基线保持只读。
- 下架后历史会话可读但不可续聊，新会话拒绝创建。
- 依赖失效必须明确失败，不允许静默换模型、凭据、技能、MCP 或插件。
- 不修改现有 PawApp 安装、市场和插件治理语义；插件安装与授权留在 Task 9.2。
- 不建立双写、灰度发布、组织商店、计费或分布式制品系统。
- 不执行 Git 分支、提交、推送、硬重置或清理用户改动。
- 增量迁移先仅在独立测试 schema 验证；不迁移原数据库，不重启 `127.0.0.1:18089` 原服务。

## 文件结构

```text
migrations/versions/0016_shared_app_publications.py
    增加发布审核字段、会话 publication 外键、约束、索引和不可变触发器。
src/qwenpaw/publications/models.py
    冻结的领域记录、manifest 模型、状态字面量和稳定错误类型。
src/qwenpaw/publications/repository.py
    PostgreSQL 查询、行锁、幂等写入和原子当前指针切换。
src/qwenpaw/publications/snapshot.py
    安全工作区复制、过滤、规范化哈希和基线原子落位。
src/qwenpaw/publications/dependencies.py
    模型、技能、MCP、插件和 credential binding 校验与脱敏报告。
src/qwenpaw/publications/service.py
    草稿、提交、审核、发布、下架、回滚和用户启动状态机。
src/qwenpaw/app/routers/shared_apps.py
    owner、catalog 和管理员 HTTP API；只做 DTO、依赖注入和错误映射。
src/qwenpaw/app/chats/repo/conversation.py
src/qwenpaw/app/chats/repo/postgres_repo.py
    ConversationRecord 的共享应用版本绑定与持久化。
src/qwenpaw/models/runtime.py
    从可信会话 publication 解析锁定模型，普通会话逻辑保持不变。
src/qwenpaw/workspaces/resolver.py
    新增共享应用用户运行空间的安全逻辑键。
console/src/api/modules/sharedApps.ts
    共享应用所有者、目录和管理员请求与类型。
console/src/pages/AppCenter/SharedApps.tsx
console/src/pages/AppCenter/MyPublications.tsx
    可用应用、详情启动、草稿提交和发布状态。
console/src/pages/Admin/Publications/index.tsx
    管理员审核、发布、下架和回滚页面。
console/src/pages/Chat/components/PublicationModelLock.tsx
    共享应用会话版本及模型锁定提示。
```

---

### Task 1: 数据约束、领域模型和 PostgreSQL Repository

**Files:**
- Create: `migrations/versions/0016_shared_app_publications.py`
- Create: `src/qwenpaw/publications/__init__.py`
- Create: `src/qwenpaw/publications/models.py`
- Create: `src/qwenpaw/publications/repository.py`
- Modify: `src/qwenpaw/app/chats/repo/conversation.py`
- Modify: `src/qwenpaw/app/chats/repo/postgres_repo.py`
- Test: `tests/integration/test_shared_app_repository.py`
- Test: `tests/integration/test_migrations.py`
- Test: `tests/parity/test_conversation_repository_contract.py`

**Interfaces:**
- Consumes: `database_session()`、`set_request_user()`、现有 `ConversationRepository` 契约、0003 中四张共享应用表。
- Produces: `SharedAppRecord`、`SharedAppDraftRecord`、`SharedAppPublicationRecord`、`SharedAppUserWorkspaceRecord`、`DependencyReport`；`PostgresSharedAppRepository(schema, session_factory)`；扩展后的 `ConversationRecord.shared_app_id` 与 `publication_id`。

- [ ] **Step 1: 编写迁移与 Repository 失败测试**

```python
async def test_publication_manifest_is_immutable(repository, seeded_publication):
    with pytest.raises(PublicationImmutableError):
        await repository.replace_manifest(
            seeded_publication.id,
            {"display": {"name": "tampered"}},
        )

async def test_conversation_requires_both_shared_app_keys(conversations, record):
    invalid = record.model_copy(update={"shared_app_id": uuid4(), "publication_id": None})
    with pytest.raises(Exception):
        await conversations.create_conversation(invalid)
```

同时断言迁移新增 `review_note`、`reviewed_at`、会话两个外键、成对为空 check、发布不可变触发器及运行角色表权限。

- [ ] **Step 2: 运行失败测试并记录缺失接口**

Run: `python -m pytest "tests/integration/test_shared_app_repository.py" "tests/parity/test_conversation_repository_contract.py" -q`

Expected: 因 `qwenpaw.publications` 和会话新字段尚不存在而失败。

- [ ] **Step 3: 编写 0016 增量迁移**

迁移执行以下最小变化：

```sql
ALTER TABLE shared_app_publications
  ADD COLUMN review_note text,
  ADD COLUMN reviewed_at timestamptz;
ALTER TABLE conversations
  ADD COLUMN shared_app_id uuid REFERENCES shared_apps(id),
  ADD COLUMN publication_id uuid REFERENCES shared_app_publications(id),
  ADD CONSTRAINT ck_conversations_shared_publication_pair
    CHECK ((shared_app_id IS NULL) = (publication_id IS NULL));
CREATE INDEX ix_conversations_owner_publication_updated
  ON conversations(owner_user_id, publication_id, updated_at DESC);
```

创建 `BEFORE UPDATE` 触发器，仅当不可变列发生变化时抛出 `shared_app_publication_immutable`。downgrade 在共享应用会话、审核数据或发布数据存在时拒绝破坏性回退。

- [ ] **Step 4: 实现冻结领域模型和 Repository**

```python
class SharedAppPublicationRecord(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: UUID
    shared_app_id: UUID
    version: str
    immutable_manifest: dict[str, Any]
    baseline_workspace_key: str
    review_status: Literal["pending", "approved", "rejected"]
    submitted_by: UUID
    reviewed_by: UUID | None = None
    review_note: str | None = None
    reviewed_at: datetime | None = None
    published_at: datetime | None = None
    retired_at: datetime | None = None
```

Repository 提供明确方法，不公开任意更新入口：

```python
async def create_draft(self, record: SharedAppDraftRecord) -> SharedAppDraftRecord: ...
async def create_submission(self, record: SharedAppPublicationRecord) -> SharedAppPublicationRecord: ...
async def review(self, publication_id: UUID, reviewer_id: UUID, decision: ReviewStatus, note: str, reviewed_at: datetime) -> SharedAppPublicationRecord: ...
async def switch_current(self, app_id: UUID, publication_id: UUID, expected_current_id: UUID | None, actor_id: UUID, changed_at: datetime) -> SharedAppRecord: ...
async def retire(self, app_id: UUID, expected_current_id: UUID, actor_id: UUID, changed_at: datetime) -> SharedAppRecord: ...
async def get_user_workspace(self, app_id: UUID, publication_id: UUID, user_id: UUID) -> SharedAppUserWorkspaceRecord | None: ...
async def create_user_workspace(self, record: SharedAppUserWorkspaceRecord) -> SharedAppUserWorkspaceRecord: ...
```

- [ ] **Step 5: 扩展 ConversationRecord 与 PostgreSQL 映射**

给 `ConversationRecord` 增加默认 `None` 的两个字段，保留所有旧构造调用兼容性。插入语句显式写入两个新列；`set_model_override()` 对 `publication_id IS NOT NULL` 的记录返回 `None`，阻止共享应用会话修改模型。

- [ ] **Step 6: 在独立 schema 运行迁移与目标测试**

Run: `python -m pytest "tests/integration/test_shared_app_repository.py" "tests/integration/test_migrations.py" "tests/parity/test_conversation_repository_contract.py" -q`

Expected: PASS；直接 SQL 修改 manifest 被触发器拒绝；普通会话兼容测试不变。

### Task 2: 安全快照和依赖校验

**Files:**
- Create: `src/qwenpaw/publications/snapshot.py`
- Create: `src/qwenpaw/publications/dependencies.py`
- Test: `tests/isolation/test_shared_app_snapshot.py`
- Test: `tests/isolation/test_shared_app_dependencies.py`
- Modify: `src/qwenpaw/workspaces/resolver.py`
- Test: `tests/isolation/test_workspace_resolver.py`

**Interfaces:**
- Consumes: `WorkspaceResolver.resolve()`、模型治理 Repository、技能治理表、MCP/credential binding 表和插件注册状态。
- Produces: `PublicationSnapshotBuilder.build(source, publication_id) -> SnapshotResult`；`PublicationDependencyValidator.validate(manifest, mode) -> DependencyReport`；`WorkspaceKind.SHARED_APP_RUNTIME`。

- [ ] **Step 1: 编写路径、哈希和依赖失败测试**

```python
def test_snapshot_rejects_symlink(builder, source_with_symlink):
    with pytest.raises(SnapshotBuildError, match="snapshot_symlink_denied"):
        builder.build(source_with_symlink, uuid4())

async def test_revoked_credential_blocks_strong_validation(validator, manifest):
    report = await validator.validate(manifest, mode="strong")
    assert report.ok is False
    assert report.items[0].code == "PUBLICATION_CREDENTIAL_REVOKED"
```

覆盖路径逃逸、临时文件过滤、两次构建哈希一致、技能哈希变化、MCP revision 变化、插件停用和模型停用。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest "tests/isolation/test_shared_app_snapshot.py" "tests/isolation/test_shared_app_dependencies.py" "tests/isolation/test_workspace_resolver.py" -q`

Expected: 新类型和 `SHARED_APP_RUNTIME` 不存在。

- [ ] **Step 3: 扩展 WorkspaceResolver**

新增专用方法，避免把两个 UUID 拼成客户端可控 resource ID：

```python
def resolve_shared_app_runtime(
    self, *, user_id: UUID, shared_app_id: UUID, publication_id: UUID,
    workspace_key: str | None = None,
) -> ResolvedWorkspace:
    expected = f"user_workspaces/{user_id}/apps/{shared_app_id}/{publication_id}"
```

返回 `WorkspaceKind.SHARED_APP_RUNTIME`、`read_only=False`，继续复用现有父目录 symlink 和根目录逃逸校验。

- [ ] **Step 4: 实现规范化快照**

`PublicationSnapshotBuilder` 使用同一文件排序、UTF-8 相对路径和逐文件 SHA-256 生成文件树哈希；过滤 `.git`、运行锁、缓存、会话、临时附件和 Secret 文件；拒绝 symlink。先写入 `published_workspaces/.staging/<publication_id>.<nonce>`，成功后以原子 rename 落位 `published_workspaces/<publication_id>`。

- [ ] **Step 5: 实现依赖校验器**

定义五个职责清晰的私有校验方法：`_validate_model`、`_validate_skills`、`_validate_mcp`、`_validate_plugins`、`_validate_credentials`。结果统一为：

```python
class DependencyCheck(BaseModel):
    kind: Literal["model", "skill", "mcp", "plugin", "credential"]
    reference: str
    ok: bool
    code: str | None = None
    message: str | None = None
```

错误消息只含脱敏标签，不包含 Secret、token、绝对路径或连接串。

- [ ] **Step 6: 运行目标测试**

Run: `python -m pytest "tests/isolation/test_shared_app_snapshot.py" "tests/isolation/test_shared_app_dependencies.py" "tests/isolation/test_workspace_resolver.py" -q`

Expected: PASS。

### Task 3: 发布状态机、权限、审计和 HTTP API

**Files:**
- Create: `src/qwenpaw/publications/service.py`
- Create: `src/qwenpaw/app/routers/shared_apps.py`
- Modify: `src/qwenpaw/access/capabilities.py`
- Modify: `src/qwenpaw/access/service.py`
- Modify: `src/qwenpaw/app/routers/__init__.py`
- Modify: `src/qwenpaw/app/_app.py`
- Test: `tests/isolation/test_shared_app_permissions.py`
- Test: `tests/integration/test_shared_app_lifecycle.py`
- Test: `tests/unit/app/routers/test_shared_apps_router.py`

**Interfaces:**
- Consumes: Task 1 Repository、Task 2 builder/validator、`ActorContext`、`AuthorizationService` 和 PostgreSQL `audit_logs`。
- Produces: `SharedAppService.save_draft()`、`submit()`、`review()`、`publish()`、`retire()`、`rollback()`、`list_catalog()`；三组 `/api/shared-*` 路由。

- [ ] **Step 1: 编写角色矩阵与状态机失败测试**

```python
async def test_owner_cannot_approve(service, owner, publication):
    with pytest.raises(PublicationAccessError, match="publications_review_required"):
        await service.review(owner, publication.id, "approved", "ok")

async def test_publish_requires_approved(service, admin, pending):
    with pytest.raises(PublicationStateError, match="publication_not_approved"):
        await service.publish(admin, pending.shared_app_id, pending.id, None)
```

覆盖 owner 提交、collaborator 提交拒绝、普通用户提交拒绝、管理员审核、重复审核、ETag 冲突、下架和回滚。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest "tests/isolation/test_shared_app_permissions.py" "tests/integration/test_shared_app_lifecycle.py" "tests/unit/app/routers/test_shared_apps_router.py" -q`

Expected: service、router 和 capability 不存在。

- [ ] **Step 3: 增加 capability 与统一鉴权**

后端增加 `Capability.PUBLICATIONS_REVIEW = "publications.review"`，`AuthorizationService` 只允许 active admin。owner 操作调用既有 Agent owner 解析，不把 admin 当作隐式 owner；管理员代管必须走显式 admin 路由并写审计。

- [ ] **Step 4: 实现 SharedAppService 状态机**

`submit()` 顺序固定为 owner/ETag 校验、生成服务端 manifest、强依赖校验、构建快照、插入 pending 版本。`review()` 只修改审核字段。`publish()` 与 `rollback()` 先强校验，再调用带行锁和 expected current 的 Repository 指针事务。`retire()` 原子清空指针。

- [ ] **Step 5: 实现 DTO 和路由错误映射**

Pydantic 请求模型 `extra="forbid"`。将领域错误稳定映射：权限 403、资源不存在 404、状态/ETag 冲突 409、依赖不可用 422、数据库 authority 不可用 503。目录 DTO 排除内部路径和 credential binding ID。

- [ ] **Step 6: 写入 PostgreSQL 审计记录**

服务成功和关键拒绝通过同一帮助函数写 `audit_logs`，字段包含 actor、action、resource type/id、publication id、result、error code、request id；审计失败按现有平台策略明确处理，不能静默把状态机写一半。

- [ ] **Step 7: 运行目标测试**

Run: `python -m pytest "tests/isolation/test_shared_app_permissions.py" "tests/integration/test_shared_app_lifecycle.py" "tests/unit/app/routers/test_shared_apps_router.py" -q`

Expected: PASS。

### Task 4: 用户运行空间、私人会话和可信模型锁定

**Files:**
- Modify: `src/qwenpaw/publications/service.py`
- Modify: `src/qwenpaw/app/chats/run_persistence.py`
- Modify: `src/qwenpaw/models/runtime.py`
- Modify: `src/qwenpaw/app/routers/console.py`
- Test: `tests/isolation/test_shared_app_runtime.py`
- Test: `tests/isolation/test_shared_app_conversation_isolation.py`
- Test: `tests/unit/models/test_resolution.py`
- Test: `tests/unit/app/routers/test_console_publication_model.py`

**Interfaces:**
- Consumes: `SharedAppService.start_conversation(actor, app_id)`、会话 publication 外键、`TrustedPublication(provider_id, model)`、既有 Run/Event/SSE。
- Produces: `SharedAppRuntimeContext`；共享应用会话启动返回 `conversation_id`、`publication_id`、`version`、`locked_model`。

- [ ] **Step 1: 编写两用户隔离和模型覆盖失败测试**

```python
async def test_two_users_receive_distinct_runtime_workspaces(service, app, a, b):
    left = await service.start_conversation(a, app.id)
    right = await service.start_conversation(b, app.id)
    assert left.workspace_key != right.workspace_key
    assert left.conversation.owner_user_id == a.user_id
    assert right.conversation.owner_user_id == b.user_id

async def test_client_model_override_cannot_replace_publication_model(client, token, chat):
    response = await client.post(
        f"/api/console/chat/{chat.id}",
        headers=token,
        json={"requested_model": {"provider_id": "evil", "model": "other"}},
    )
    assert response.status_code == 403
```

覆盖同一用户同一版本 workspace 幂等、新版创建新 workspace、下架后续聊 409、越权访问他人会话 404、SSE 事件不串流。

- [ ] **Step 2: 运行失败测试**

Run: `python -m pytest "tests/isolation/test_shared_app_runtime.py" "tests/isolation/test_shared_app_conversation_isolation.py" "tests/unit/models/test_resolution.py" "tests/unit/app/routers/test_console_publication_model.py" -q`

Expected: 启动接口和可信会话解析不存在。

- [ ] **Step 3: 实现幂等运行空间初始化**

`start_conversation()` 读取带 current pointer 的 active 应用，轻量依赖校验后按用户和版本加事务锁。不存在时把基线复制到 runtime staging，原子落位并插入 workspace 记录；已存在时校验数据库 key 与 resolver 结果一致。目录和数据库任一步失败都不返回可运行会话。

- [ ] **Step 4: 创建固定 publication 的私人会话**

新建 `ConversationRecord` 时写 `shared_app_id` 和 `publication_id`，owner 为当前用户。会话不能加入公共成员、不能修改模型覆盖；列表和历史继续使用现有 owner/RLS 过滤。

- [ ] **Step 5: 从会话构造可信发布上下文**

增加仅服务端调用的解析器：

```python
async def trusted_publication_for_conversation(
    repository: SharedAppRepository,
    conversation: ConversationRecord,
) -> TrustedPublication | None:
    ...
```

`prepare_console_model()` 在 `publication_id` 非空时忽略普通 conversation override 分支，从不可变 manifest 读取 provider/model 并传给 `resolve_selection(..., publication=trusted)`。用户请求中出现共享应用 authority 字段继续由 `validate_candidate()` 拒绝。

- [ ] **Step 6: 增加下架运行门禁**

每次创建 Run 前检查会话 publication 是否仍是该应用当前版本且应用 active。不是当前版本或已下架时返回 `409 PUBLICATION_RETIRED`；历史查询、附件下载和事件回放保持可用。

- [ ] **Step 7: 运行目标与聊天事件回归**

Run: `python -m pytest "tests/isolation/test_shared_app_runtime.py" "tests/isolation/test_shared_app_conversation_isolation.py" "tests/unit/models/test_resolution.py" "tests/unit/app/routers/test_console_publication_model.py" "tests/parity/test_chat_event_contract.py" -q`

Expected: PASS；普通 Agent 模型切换契约仍通过。

### Task 5: 共享应用前端、管理员审核页和聊天锁定状态

**Files:**
- Create: `console/src/api/modules/sharedApps.ts`
- Create: `console/src/api/modules/sharedApps.test.ts`
- Create: `console/src/pages/AppCenter/SharedApps.tsx`
- Create: `console/src/pages/AppCenter/SharedApps.test.tsx`
- Create: `console/src/pages/AppCenter/MyPublications.tsx`
- Create: `console/src/pages/AppCenter/MyPublications.test.tsx`
- Create: `console/src/pages/Admin/Publications/index.tsx`
- Create: `console/src/pages/Admin/Publications/index.test.tsx`
- Create: `console/src/pages/Chat/components/PublicationModelLock.tsx`
- Create: `console/src/pages/Chat/components/PublicationModelLock.test.tsx`
- Modify: `console/src/pages/AppCenter/index.tsx`
- Modify: `console/src/pages/Chat/index.tsx`
- Modify: `console/src/pages/Chat/ModelSelector/index.tsx`
- Modify: `console/src/access/capabilities.ts`
- Modify: `console/src/layouts/registry/builtinRoutes.tsx`
- Modify: `console/src/layouts/registry/builtinMenu.ts`
- Modify: `console/src/api/index.ts`
- Test: `console/src/pages/AppCenter/index.test.tsx`
- Test: `console/src/layouts/registry/builtinRoutes.contract.test.tsx`

**Interfaces:**
- Consumes: Task 3/4 API DTO、现有 AppCenter URL `view` 状态、Chat 会话元数据和 capability 过滤。
- Produces: `sharedAppsApi`、`AppCenterView = "shared" | "mine" | "installed" | "official" | "market"`、管理员 `/admin/publications` 路由和聊天只读模型提示。

- [ ] **Step 1: 编写 API、页面和 capability 失败测试**

```tsx
it("starts a shared app and navigates to its private conversation", async () => {
  render(<SharedApps />);
  await userEvent.click(await screen.findByRole("button", { name: "开始使用" }));
  expect(sharedAppsApi.startConversation).toHaveBeenCalledWith("app-1");
  expect(mockNavigate).toHaveBeenCalledWith("/chat/conversation-1");
});

it("shows the locked publication model without an editable selector", () => {
  render(<PublicationModelLock version="r2" model="qwen-max" />);
  expect(screen.getByText(/r2/)).toBeInTheDocument();
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
});
```

覆盖 owner 拒绝理由、管理员 dependency errors、普通用户无审核菜单、PawApp 已安装页仍加载。

- [ ] **Step 2: 运行前端测试确认失败**

Run: `npm --prefix "console" run test:run -- src/api/modules/sharedApps.test.ts src/pages/AppCenter/SharedApps.test.tsx src/pages/AppCenter/MyPublications.test.tsx src/pages/Admin/Publications/index.test.tsx src/pages/Chat/components/PublicationModelLock.test.tsx`

Expected: 新模块不存在。

- [ ] **Step 3: 实现共享应用 API 客户端**

使用现有 `request` 封装，集中定义 `SharedAppSummary`、`SharedAppDraft`、`PublicationSummary`、`DependencyCheck` 和 `StartConversationResult`；请求体不包含 workspace、credential binding 或可信模型字段。

- [ ] **Step 4: 扩展应用中心页签**

增加“共享应用”和“我的发布”，URL 用 `?view=shared`、`?view=mine` 保持刷新与后退状态。PawApp 的 installed/official/market 数据获取只在对应页签触发，避免共享应用失败破坏现有插件应用展示。

- [ ] **Step 5: 实现 owner 发布视图**

页面支持保存草稿、选择最新 revision 提交、展示 pending/approved/rejected、审核意见和当前线上版本。提交完成后刷新服务端状态，不乐观伪造审核结果。

- [ ] **Step 6: 实现管理员审核页和 capability**

前端增加 `Capability.PublicationsReview = "publications.review"`，只允许 multi-user admin；路由和菜单共享同一 capability。审核详情展示脱敏依赖结果，拒绝必须填写理由；发布、下架和回滚传 expected current ETag，409 后提示刷新。

- [ ] **Step 7: 实现聊天模型锁定呈现**

共享应用会话显示应用名、publication version 和锁定模型，隐藏可编辑 ModelSelector；普通 Agent 会话继续渲染原选择器。前端不自行判断是否下架，续聊错误直接展示后端稳定消息。

- [ ] **Step 8: 运行前端目标测试和构建**

Run: `npm --prefix "console" run test:run -- src/api/modules/sharedApps.test.ts src/pages/AppCenter/SharedApps.test.tsx src/pages/AppCenter/MyPublications.test.tsx src/pages/Admin/Publications/index.test.tsx src/pages/Chat/components/PublicationModelLock.test.tsx src/pages/AppCenter/index.test.tsx src/layouts/registry/builtinRoutes.contract.test.tsx`

Run: `npm --prefix "console" run build`

Expected: 全部 PASS，生产构建成功。

### Task 6: 完整隔离、越权和原功能回归

**Files:**
- Create: `tests/isolation/test_shared_app_full_matrix.py`
- Create: `e2e/tests/test_shared_app_publication.py`
- Modify: `docs/project-audit/12-原功能保真与页面验收契约.md`

**Interfaces:**
- Consumes: Task 1–5 的完整前后端能力。
- Produces: 四角色 API 矩阵、真实 PostgreSQL 浏览器场景和原功能零新增失败证据。

- [ ] **Step 1: 编写后端完整矩阵**

用 admin、owner、member A、member B 创建独立 Actor/token。测试 owner 提交、admin 审核发布、两用户运行、客户端模型覆盖拒绝、跨用户会话/文件/SSE 拒绝、下架历史只读和回滚版本固定。

- [ ] **Step 2: 运行后端目标回归**

Run: `python -m pytest "tests/integration/test_shared_app_repository.py" "tests/integration/test_shared_app_lifecycle.py" "tests/isolation/test_shared_app_snapshot.py" "tests/isolation/test_shared_app_dependencies.py" "tests/isolation/test_shared_app_permissions.py" "tests/isolation/test_shared_app_runtime.py" "tests/isolation/test_shared_app_conversation_isolation.py" "tests/isolation/test_shared_app_full_matrix.py" -q`

Expected: PASS。

- [ ] **Step 3: 运行受影响原功能后端回归**

Run: `python -m pytest "tests/parity/test_conversation_repository_contract.py" "tests/parity/test_chat_event_contract.py" "tests/isolation/test_model_governance.py" "tests/isolation/test_workspace_resolver.py" "tests/integration/test_conversation_sharing.py" -q`

Expected: PASS，新增失败为 0。

- [ ] **Step 4: 运行受影响前端回归和构建**

Run: `npm --prefix "console" run test:run -- src/pages/AppCenter src/pages/Chat/ChatPage.test.tsx src/pages/Chat/ModelSelector/ModelSelector.test.tsx src/access/capabilities.test.ts src/access/filterMenu.test.ts src/layouts/registry/builtinRoutes.contract.test.tsx`

Run: `npm --prefix "console" run build`

Expected: PASS，原 PawApp 和普通聊天行为不变。

- [ ] **Step 5: 启动隔离 Multi-user 验收实例**

使用独立端口、独立 PostgreSQL schema 和独立 `QWENPAW_WORKING_DIR`。记录原服务 `127.0.0.1:18089` 的 PID、健康状态和原数据哈希，验收期间不停止或写入原实例。

- [ ] **Step 6: 执行真实浏览器场景**

Playwright 使用四个独立 browser context，不为每个用户常驻启动一个浏览器进程；同一 Chromium 进程中的隔离 context 分别保存 cookie/local storage。依次完成设计规格 13.2 的十项操作，并保存页面截图、请求 ID、publication/conversation/workspace 归属查询和 Secret 扫描结果。

- [ ] **Step 7: 验证 Legacy 对照实例**

只读检查原服务健康、应用中心 PawApp、普通 Agent 对话入口和丰富事件契约；原 PID、配置、数据库表计数和受保护文件哈希保持不变。

### Task 7: 验收记录和任务确认门

**Files:**
- Create: `docs/superpowers/plans/2026-09-07-task-9-1-acceptance.md`
- Modify: `docs/project-audit/16-多用户架构分阶段实施计划.md`
- Create: `.superpowers/sdd/2026-09-07-task-9-1-shared-app-publication/progress.md`

**Interfaces:**
- Consumes: Task 1–6 的差异、测试、API、数据库和浏览器证据。
- Produces: 可由用户逐项复验的 Task 9.1 验收文档；Task 9.2 在用户确认前保持未开始。

- [ ] **Step 1: 汇总变更与原则说明**

逐文件说明职责和必要性：状态机、快照、依赖校验、运行空间、模型锁定和页面各自保持单一职责；标明复用既有聊天事件链与 capability 机制，避免重复实现。

- [ ] **Step 2: 记录数据库和原数据影响**

列出 0016 upgrade/downgrade、独立 schema 名称、表/约束/触发器检查结果；明确原数据库未迁移、原工作目录未写入、原服务未重启。

- [ ] **Step 3: 记录自动化与浏览器证据**

保存每组命令的通过数量、运行时间、构建结果、四角色检查项、截图路径、请求 ID 和数据库归属摘要；既有警告单独列出，不把未运行项目写为通过。

- [ ] **Step 4: 更新总计划当前确认门**

把 Task 9.1 标记为“实现与技术验收完成，等待用户确认”，保持 Task 9.2 未开始。只有用户明确确认 Task 9.1 后才进入插件治理与应用授权。

## 计划自检

- 规格覆盖：状态机、不可变快照、依赖校验、权限、模型锁定、每用户运行空间、会话版本、下架/回滚、API、页面、审计、失败补偿和四账户验收均有对应任务。
- 类型一致：`SharedAppPublicationRecord`、`DependencyReport`、`SnapshotResult`、`SharedAppRuntimeContext` 和 `TrustedPublication` 的生产/消费顺序明确。
- 原功能边界：普通 ConversationRecord 通过可空默认字段兼容；PawApp 页签和聊天事件链只做条件接入。
- 风险边界：原数据库迁移、Git 操作、文件删除和原服务重启均不在自动执行范围。
- 占位扫描：计划不含 TBD、待定或“稍后实现”步骤；每一阶段都有明确文件、接口、失败测试和验证命令。
