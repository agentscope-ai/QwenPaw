# Task 6.2-R/4 用户个人资料库 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为每位用户提供跨会话、跨 Agent 的私有资料库，并允许用户显式授权可使用的 Agent 按需只读检索和读取。

**Architecture:** 文件正文存于 `user_libraries/{user_id}/`，PostgreSQL 只保存文档元数据和用户到 Agent 的整库只读授权。个人资料库由独立服务和 API 管理，不复用 Agent 工作区写权限；运行时工具每次调用重新校验用户、Agent、文档归属和实时授权，避免前端隐藏或旧文档 ID 绕过权限。

**Tech Stack:** Python 3.11、FastAPI、Pydantic、SQLAlchemy Async、Alembic、PostgreSQL RLS、React、TypeScript、Ant Design、Vitest、pytest、Playwright。

## Global Constraints

- 文件正文只存文件系统，PostgreSQL 不保存文件正文。
- 新资料库物理根固定为 `user_libraries/{user_id}/`；目录名保持英文。
- 所有 API 路径必须为 POSIX 相对路径，拒绝绝对路径、`..`、空段、反斜杠与符号链接逃逸。
- 用户仅管理自己的资料；管理员不自动获得其他用户私人资料的读取或修改权限。
- 授权粒度固定为“用户资料库 → 当前可使用 Agent → 整库只读”；不实现单文件 ACL。
- Agent 不得创建、编辑、移动或删除资料；未授权时不得注册资料库工具。
- 文件进入资料库必须由用户显式发起，复制不删除来源文件。
- 仅文本扩展名 `.md`、`.txt`、`.json`、`.yaml`、`.yml`、`.csv` 支持 Agent 检索与分页读取；二进制文件仅上传、预览或下载。
- 所有新行为遵循 TDD：先运行失败测试，再写最小实现；每个 R/4 子任务完成后必须等待用户 UI 验收。
- 不创建分支、不执行 `git commit`、不删除历史文件或数据；执行数据库迁移、重启服务前需另行取得用户明确确认。

---

## 文件结构和责任边界

| 文件 | 责任 |
| --- | --- |
| `src/qwenpaw/personal_library/models.py` | 资料文档、授权记录、DTO、文本类型和分页读取常量。 |
| `src/qwenpaw/personal_library/paths.py` | 用户资料库根解析、相对路径规范化、符号链接与目录边界检查。 |
| `src/qwenpaw/personal_library/repository.py` | PostgreSQL 文档元数据、授权记录、所有权查询和原子状态变更。 |
| `src/qwenpaw/personal_library/service.py` | 文件系统与元数据一致性、上传/编辑/移动/删除/复制、授权决策和文本搜索。 |
| `src/qwenpaw/app/routers/personal_library.py` | 认证后的 HTTP 资源接口，统一错误映射。 |
| `migrations/versions/0013_user_personal_library.py` | 两张表、索引、外键与 RLS 策略。 |
| `console/src/api/modules/personalLibrary.ts` | 个人资料库 API 客户端与 DTO。 |
| `console/src/features/files-workspace/PersonalLibraryPanel.tsx` | 资料库文件树、文件操作、保存来源和授权入口。 |
| `console/src/features/files-workspace/PersonalLibraryGrantDialog.tsx` | 可使用 Agent 列表和授权开关。 |
| `src/qwenpaw/agents/tools/personal_library.py` | Agent 的只读搜索、分页读取工具。 |
| `src/qwenpaw/runtime/builder.py` | 基于可信请求身份决定是否注册资料库工具。 |

现有组件复用方式：

- `resolve_workspace_path` 的路径约束语义必须复用于资料库路径解析，不能另写弱校验；
- `WorkspaceResolver` 的逐级非符号链接建目录策略复用于资料库根创建；
- `workspace.py` 的临时文件加 `os.replace` 上传策略复用于资料库写入；
- `AgentMembershipService.list_accessible` 作为“当前用户可授权 Agent”唯一事实来源；
- `AttachmentRecord` 和附件仓储只作为 R/4-B 的复制来源，不扩展附件权限为资料库权限；
- `PersonalWorkspaceNavigator` 保持临时附件、Agent 资料、产物既有行为，新增资料库一级标签而不改变其权限模型；
- `RuntimeBuilder.build_toolkit` 的 `extra_tools` 参数负责装配授权后的只读工具。

---

### Task 1: R/4-A 个人资料库基础纵向切片

**Files:**

- Create: `src/qwenpaw/personal_library/__init__.py`
- Create: `src/qwenpaw/personal_library/models.py`
- Create: `src/qwenpaw/personal_library/paths.py`
- Create: `src/qwenpaw/personal_library/repository.py`
- Create: `src/qwenpaw/personal_library/service.py`
- Create: `src/qwenpaw/app/routers/personal_library.py`
- Create: `migrations/versions/0013_user_personal_library.py`
- Modify: `src/qwenpaw/app/routers/__init__.py`
- Create: `tests/unit/personal_library/test_paths.py`
- Create: `tests/unit/personal_library/test_service.py`
- Create: `tests/unit/app/routers/test_personal_library_router.py`
- Create: `tests/integration/test_personal_library_repository.py`
- Create: `tests/integration/test_personal_library_migration.py`
- Create: `console/src/api/modules/personalLibrary.ts`
- Create: `console/src/api/modules/personalLibrary.test.ts`
- Create: `console/src/features/files-workspace/PersonalLibraryPanel.tsx`
- Create: `console/src/features/files-workspace/PersonalLibraryPanel.test.tsx`
- Modify: `console/src/features/files-workspace/PersonalWorkspaceNavigator.tsx`
- Modify: `console/src/features/files-workspace/PersonalWorkspaceNavigator.test.tsx`
- Modify: `console/src/api/index.ts`
- Modify: `console/src/locales/zh.json`
- Modify: `console/src/locales/en.json`

**Interfaces:**

- Consumes: `ActorContext.user_id`, `AgentMembershipService.list_accessible`, `resolve_workspace_path`, `check_upload_size`, `buildAuthHeaders`。
- Produces:

```python
@dataclass(frozen=True, slots=True)
class PersonalLibraryDocument:
    id: UUID
    owner_user_id: UUID
    relative_path: str
    name: str
    media_type: str
    size: int
    sha256: str
    created_at: datetime
    updated_at: datetime

class PersonalLibraryService:
    async def list_directory(self, *, owner_user_id: UUID, path: str) -> list[PersonalLibraryDocument]:
        """返回 owner_user_id 在 path 下的直接子项。"""
    async def read_text(self, *, owner_user_id: UUID, document_id: UUID, offset: int = 0, limit: int = 65536) -> PersonalLibraryDocumentContent:
        """读取资料所有者自己的文本文件分页。"""
    async def create_text(self, *, owner_user_id: UUID, relative_path: str, content: str, overwrite: bool = False) -> PersonalLibraryDocument:
        """原子创建或覆盖一个文本资料文件。"""
    async def upload(self, *, owner_user_id: UUID, relative_path: str, source: BinaryIO, media_type: str, overwrite: bool = False) -> PersonalLibraryDocument:
        """原子上传一个资料文件。"""
    async def move(self, *, owner_user_id: UUID, document_id: UUID, destination_path: str, overwrite: bool = False) -> PersonalLibraryDocument:
        """原子移动一个已登记资料文件。"""
    async def delete(self, *, owner_user_id: UUID, document_id: UUID) -> None:
        """删除一个已登记资料文件。"""
```

```ts
export interface PersonalLibraryDocument {
  id: string;
  relativePath: string;
  name: string;
  mediaType: string;
  size: number;
  sha256: string;
  createdAt: string;
  updatedAt: string;
}

export const personalLibraryApi: {
  list(path?: string): Promise<PersonalLibraryDocument[]>;
  createText(input: { path: string; content: string; overwrite?: boolean }): Promise<PersonalLibraryDocument>;
  upload(input: { path: string; file: File; overwrite?: boolean }): Promise<PersonalLibraryDocument>;
  readText(id: string, offset?: number, limit?: number): Promise<PersonalLibraryDocumentContent>;
  move(input: { id: string; destinationPath: string; overwrite?: boolean }): Promise<PersonalLibraryDocument>;
  remove(id: string): Promise<void>;
};
```

- [ ] **Step 1: 写入路径边界、所有权和持久化迁移的失败测试。**

```python
def test_library_path_rejects_escape_and_symlink(tmp_path: Path, user_id: UUID) -> None:
    resolver = PersonalLibraryPathResolver(working_dir=tmp_path)
    root = resolver.ensure_root(user_id)
    (root / "link").symlink_to(tmp_path, target_is_directory=True)

    with pytest.raises(PersonalLibraryPathDenied, match="invalid_library_path"):
        resolver.resolve(user_id=user_id, relative_path="../secret.md")
    with pytest.raises(PersonalLibraryPathDenied, match="library_symlink_denied"):
        resolver.resolve(user_id=user_id, relative_path="link/secret.md")

@pytest.mark.asyncio
async def test_repository_hides_other_users_document(repository, user_a, user_b):
    document = await repository.insert_document(
        owner_user_id=user_a,
        relative_path="notes/a.md",
        name="a.md",
        media_type="text/markdown",
        size=3,
        sha256="a" * 64,
    )
    assert await repository.get_document(owner_user_id=user_b, document_id=document.id) is None

def test_migration_creates_document_and_grant_tables(alembic_upgrade) -> None:
    tables = alembic_upgrade("0013_user_personal_library")
    assert {"user_library_documents", "user_library_agent_grants"} <= tables
```

- [ ] **Step 2: 运行测试，确认因模块、迁移与仓储尚不存在而失败。**

Run:

```powershell
pytest "tests/unit/personal_library/test_paths.py" "tests/integration/test_personal_library_repository.py" "tests/integration/test_personal_library_migration.py" -v
```

Expected: `ModuleNotFoundError` 或缺少 `0013_user_personal_library`；不得以测试夹具错误作为通过条件。

- [ ] **Step 3: 建立受控路径、数据模型和数据库迁移。**

实现以下不变量：

```python
class PersonalLibraryPathResolver:
    def root_key(self, user_id: UUID) -> str:
        return f"user_libraries/{user_id}"

    def resolve(self, *, user_id: UUID, relative_path: str, allow_root: bool = False) -> Path:
        root = self.ensure_root(user_id)
        return resolve_workspace_path(root, relative_path, allow_root=allow_root, portable=True)
```

迁移 `0013_user_personal_library` 必须：

- 创建 `user_library_documents`，含 `id UUID PRIMARY KEY`、`owner_user_id UUID REFERENCES users(id)`、`relative_path TEXT`、`name TEXT`、`media_type TEXT`、`size BIGINT CHECK (size >= 0)`、`sha256 TEXT`、时间戳；
- 以 `(owner_user_id, relative_path)` 创建唯一约束，以 `owner_user_id, updated_at DESC` 创建索引；
- 创建 `user_library_agent_grants`，含 `owner_user_id UUID REFERENCES users(id)`、`agent_id UUID REFERENCES agents(id)`、`status TEXT CHECK (status IN ('active','revoked'))`、三类时间戳，并以 `(owner_user_id, agent_id)` 唯一；
- 为两表启用 RLS：资料文档仅在 `owner_user_id = current_setting('app.user_id', true)::uuid` 时允许 SELECT/INSERT/UPDATE/DELETE；授权表同样仅允许所有者访问；
- downgrade 仅在两表均为空时删除，存在业务记录时抛出明确的 `personal_library_data_prevents_downgrade`。

- [ ] **Step 4: 先实现服务端最小文件 CRUD，保证文件与元数据一致。**

`PersonalLibraryService` 对创建、上传、编辑和复制均执行：

1. 规范化路径并拒绝越界；
2. 写入同目录临时文件；
3. 计算 SHA-256 与大小；
4. 使用 `os.replace` 原子替换目标；
5. 写入或更新元数据；
6. 元数据写入失败时删除新落盘文件或恢复被替换文件。

移动执行“先保留原文件，完成目标原子写入和元数据路径更新后再删除原文件”。删除只允许元数据所有者执行，元数据不一致、目标缺失或目标为符号链接时返回受控错误，不重建文件。

- [ ] **Step 5: 为基础 API 写失败测试，并确认其他用户得到 404。**

```python
@pytest.mark.asyncio
async def test_router_returns_404_for_another_users_document(client_as_user_b, user_a_document):
    response = await client_as_user_b.get(f"/api/console/personal-library/documents/{user_a_document.id}")
    assert response.status_code == 404

@pytest.mark.asyncio
async def test_router_creates_and_reads_own_markdown(client_as_user_a):
    created = await client_as_user_a.post(
        "/api/console/personal-library/documents/text",
        json={"path": "notes/hello.md", "content": "# hello"},
    )
    assert created.status_code == 201
    loaded = await client_as_user_a.get(f"/api/console/personal-library/documents/{created.json()['id']}/text")
    assert loaded.json()["content"] == "# hello"
```

- [ ] **Step 6: 实现 FastAPI 路由并挂载到全局 API。**

实现以下接口，均从 `get_actor(request).user_id` 得到唯一可访问的用户，不接受浏览器传入的 `owner_user_id`：

```text
GET    /api/console/personal-library/documents?path={relative_path}
POST   /api/console/personal-library/documents/text
POST   /api/console/personal-library/documents/upload
GET    /api/console/personal-library/documents/{document_id}/text?offset=0&limit=65536
GET    /api/console/personal-library/documents/{document_id}/download
PATCH  /api/console/personal-library/documents/{document_id}/move
DELETE /api/console/personal-library/documents/{document_id}
```

错误映射固定为：路径非法 400、认证缺失 401、其他用户文档 404、同路径但未声明覆盖 409、版本或文件状态不一致 409、超限上传 413。

- [ ] **Step 7: 为前端 API 和资料库面板写失败测试。**

```tsx
it("shows Personal Library and creates a Markdown document", async () => {
  mocks.list.mockResolvedValue([]);
  mocks.createText.mockResolvedValue({
    id: "doc-a", name: "hello.md", relativePath: "notes/hello.md",
    mediaType: "text/markdown", size: 0, sha256: "a".repeat(64),
    createdAt: "2026-09-04T00:00:00Z", updatedAt: "2026-09-04T00:00:00Z",
  });
  const user = userEvent.setup();
  render(<PersonalWorkspaceNavigator />);

  await user.click(screen.getByRole("tab", { name: "个人资料库" }));
  await user.click(screen.getByRole("button", { name: "新建 Markdown" }));
  await user.type(screen.getByLabelText("路径"), "notes/hello.md");
  await user.click(screen.getByRole("button", { name: "保存" }));

  expect(mocks.createText).toHaveBeenCalledWith({ path: "notes/hello.md", content: "", overwrite: false });
});
```

- [ ] **Step 8: 实现前端 API、资料库面板和文件页入口。**

`PersonalLibraryPanel` 必须是独立组件，不向 `FilesWorkspace` 注入 Agent workspace 路径。实现：

- “个人资料库”标签；
- 资料目录和文件列表；
- 新建 Markdown、新建文件夹、上传、预览、编辑、下载、重命名、移动和删除；
- 删除和非空目录删除使用 Ant Design `Modal.confirm`；
- 409 冲突先展示“重命名 / 覆盖 / 取消”选择，默认不覆盖；
- 在所有数据请求中通过现有 `request` 客户端自动携带当前身份令牌。

保持原有“临时附件 / Agent 资料 / 产物”标签和内容不变；新增资料库标签不随当前 Agent 更换而清空。

- [ ] **Step 9: 运行基础前后端回归，确认通过。**

Run:

```powershell
pytest "tests/unit/personal_library" "tests/unit/app/routers/test_personal_library_router.py" "tests/integration/test_personal_library_repository.py" "tests/integration/test_personal_library_migration.py" -v
Set-Location "console"; npx vitest run src/api/modules/personalLibrary.test.ts src/features/files-workspace/PersonalLibraryPanel.test.tsx src/features/files-workspace/PersonalWorkspaceNavigator.test.tsx
Set-Location ".."; Set-Location "console"; npx tsc -b --noEmit
```

Expected: 全部通过；TypeScript 无错误。

- [ ] **Step 10: R/4-A 用户验收门。**

启动服务前必须单独询问用户确认，因为启动或重启会影响当前 18089 进程。用户验收：

1. 用户 A 打开“文件 → 个人资料库”，新建并编辑 `notes/hello.md`；
2. 刷新页面后内容、修改时间和下载仍可用；
3. 用户 B 登录后看不到用户 A 的文件；直接访问用户 A 文档 ID 必须为 404；
4. 管理员登录后也只能看到自己的资料库；
5. 验收确认前不得进入 R/4-B。

---

### Task 2: R/4-B 显式保存来源文件

**Files:**

- Modify: `src/qwenpaw/personal_library/service.py`
- Modify: `src/qwenpaw/app/routers/personal_library.py`
- Modify: `src/qwenpaw/app/chats/repo/conversation.py`
- Modify: `src/qwenpaw/app/chats/repo/json_conversation_repo.py`
- Modify: `src/qwenpaw/app/chats/repo/postgres_repo.py`
- Modify: `console/src/api/modules/personalLibrary.ts`
- Modify: `console/src/features/files-workspace/TemporaryAttachmentsPanel.tsx`
- Modify: `console/src/features/files-workspace/PersonalLibraryPanel.tsx`
- Create: `tests/unit/personal_library/test_source_copy.py`
- Modify: `tests/unit/app/routers/test_personal_library_router.py`
- Modify: `console/src/features/files-workspace/TemporaryAttachmentsPanel.test.tsx`
- Modify: `console/src/features/files-workspace/PersonalLibraryPanel.test.tsx`

**Interfaces:**

- Consumes: Task 1 `PersonalLibraryService`、`AttachmentRecord`、当前用户个人运行空间 `FilesWorkspaceAccess.project`。
- Produces:

```python
class PersonalLibraryService:
    async def copy_from_attachment(self, *, owner_user_id: UUID, attachment_id: UUID, destination_path: str, overwrite: bool = False) -> PersonalLibraryDocument:
        """复制当前用户自己的附件，不改变附件记录。"""
    async def copy_from_runtime_file(self, *, owner_user_id: UUID, agent_id: str, source_path: str, destination_path: str, overwrite: bool = False) -> PersonalLibraryDocument:
        """复制当前用户在 agent_id 下的个人运行文件。"""
    async def copy_from_artifact(self, *, owner_user_id: UUID, agent_id: str, source_path: str, destination_path: str, overwrite: bool = False) -> PersonalLibraryDocument:
        """复制当前用户在 agent_id 下的产物文件。"""
```

- [ ] **Step 1: 写入三种来源复制的失败测试。**

```python
@pytest.mark.asyncio
async def test_copy_attachment_preserves_source_and_sets_library_metadata(service, owned_attachment, attachment_file):
    document = await service.copy_from_attachment(
        owner_user_id=owned_attachment.owner_user_id,
        attachment_id=owned_attachment.id,
        destination_path="references/source.pdf",
    )
    assert attachment_file.exists()
    assert document.relative_path == "references/source.pdf"

@pytest.mark.asyncio
async def test_copy_runtime_file_requires_current_users_runtime_root(service, user_a, user_b, user_a_runtime_file):
    with pytest.raises(PersonalLibrarySourceDenied):
        await service.copy_from_runtime_file(
            owner_user_id=user_b,
            agent_id="default",
            source_path=str(user_a_runtime_file),
            destination_path="stolen.md",
        )
```

- [ ] **Step 2: 运行来源复制测试，确认对应方法不存在。**

Run:

```powershell
pytest "tests/unit/personal_library/test_source_copy.py" -v
```

Expected: FAIL，缺少复制方法或来源授权逻辑。

- [ ] **Step 3: 实现后端来源解析和复制。**

实现原则：

- 附件：通过 `repository.with_user(owner_user_id).get_attachment` 获取，验证附件归属当前用户；只允许非 deleted 附件；使用登记的 `storage_key` 解析，不接受客户端绝对路径。
- 个人运行空间：通过 `resolve_files_workspace_access(agent_id=agent_id, agent_workspace=agent_workspace, agent_project=agent_project, actor_user_id=owner_user_id, access_role=AgentResourceRole.USER)` 解析，`source_path` 仅接受该根下的相对 POSIX 路径。
- 产物：在当前用户的个人运行空间根下仅允许 `artifacts/{relative_path}`；兼容历史 `产物/` 的现有 `resolve_workspace_path` 别名，但新目标固定写英文目录。
- 每种来源调用 Task 1 的同一原子复制实现；不修改附件记录的生命周期、`saved_path` 或源文件。

- [ ] **Step 4: 为来源复制 HTTP 接口写失败测试。**

```python
@pytest.mark.asyncio
async def test_attachment_copy_endpoint_rejects_another_users_id(client_as_user_b, user_a_attachment):
    response = await client_as_user_b.post(
        "/api/console/personal-library/imports/attachment",
        json={"attachment_id": str(user_a_attachment.id), "destination_path": "x.md"},
    )
    assert response.status_code == 404
```

- [ ] **Step 5: 实现三条显式复制 API。**

```text
POST /api/console/personal-library/imports/attachment
POST /api/console/personal-library/imports/runtime-file
POST /api/console/personal-library/imports/artifact
```

请求体只接受来源稳定 ID 或相对路径、目标相对路径和 `overwrite`。任一来源校验失败时不创建资料库文件；跨用户来源返回 404，非法路径返回 400，同路径冲突返回 409。

- [ ] **Step 6: 为按钮行为写失败测试。**

```tsx
it("copies a temporary attachment only after the user chooses a library destination", async () => {
  const user = userEvent.setup();
  render(<TemporaryAttachmentsPanel />);
  await user.click(await screen.findByRole("button", { name: "保存到个人资料库" }));
  await user.type(screen.getByLabelText("保存路径"), "references/invoice.pdf");
  await user.click(screen.getByRole("button", { name: "确认保存" }));
  expect(mocks.copyAttachment).toHaveBeenCalledWith({ attachmentId: ATTACHMENT_ID, destinationPath: "references/invoice.pdf", overwrite: false });
});
```

- [ ] **Step 7: 实现“保存到个人资料库”交互。**

- 临时附件列表每项增加“保存到个人资料库”；
- 个人运行空间文件和产物文件的操作菜单增加“复制到个人资料库”；
- 所有入口都显示目标路径输入框和冲突反馈；
- 成功后显示资料库目标路径和“源文件未修改”；
- Agent 资料、公共/仅使用 Agent 的只读档案不显示来源复制入口。

- [ ] **Step 8: 运行来源复制回归。**

Run:

```powershell
pytest "tests/unit/personal_library/test_source_copy.py" "tests/unit/app/routers/test_personal_library_router.py" -v
Set-Location "console"; npx vitest run src/features/files-workspace/TemporaryAttachmentsPanel.test.tsx src/features/files-workspace/PersonalLibraryPanel.test.tsx src/api/modules/personalLibrary.test.ts
```

Expected: 全部通过。

- [ ] **Step 9: R/4-B 用户验收门。**

1. 上传一个临时附件，显式保存到个人资料库，确认附件仍能在原对话下载；
2. 在个人运行空间创建一个文件，复制到资料库，确认源文件未消失；
3. 选择 `artifacts/` 下的文件复制，确认目标显示在资料库；
4. 使用第二个用户猜测附件或资料路径，确认无法复制；
5. 验收确认前不得进入 R/4-C。

---

### Task 3: R/4-C Agent 授权管理

**Files:**

- Modify: `src/qwenpaw/personal_library/models.py`
- Modify: `src/qwenpaw/personal_library/repository.py`
- Modify: `src/qwenpaw/personal_library/service.py`
- Modify: `src/qwenpaw/app/routers/personal_library.py`
- Create: `console/src/features/files-workspace/PersonalLibraryGrantDialog.tsx`
- Create: `console/src/features/files-workspace/PersonalLibraryGrantDialog.test.tsx`
- Modify: `console/src/api/modules/personalLibrary.ts`
- Modify: `console/src/api/modules/personalLibrary.test.ts`
- Modify: `console/src/features/files-workspace/PersonalLibraryPanel.tsx`
- Modify: `tests/unit/personal_library/test_service.py`
- Modify: `tests/unit/app/routers/test_personal_library_router.py`
- Modify: `tests/integration/test_personal_library_repository.py`

**Interfaces:**

- Consumes: `AgentMembershipService.list_accessible(actor, legacy_agents)`；Task 1 资料库仓储。
- Produces:

```python
@dataclass(frozen=True, slots=True)
class PersonalLibraryGrant:
    owner_user_id: UUID
    agent_id: UUID
    agent_key: str
    status: Literal["active", "revoked"]
    granted_at: datetime | None
    revoked_at: datetime | None

class PersonalLibraryService:
    async def list_grant_candidates(self, *, actor: ActorContext, legacy_agents: list[LegacyAgentRecord]) -> list[GrantCandidate]:
        """返回当前用户可授权、且非历史只读的 Agent。"""
    async def set_agent_grant(self, *, owner_user_id: UUID, agent_key: str, enabled: bool) -> PersonalLibraryGrant:
        """幂等启用或撤销整库只读授权。"""
    async def has_active_grant(self, *, owner_user_id: UUID, agent_key: str) -> bool:
        """实时查询当前授权状态，不使用进程缓存。"""
```

- [ ] **Step 1: 写入授权候选过滤和撤销即时生效的失败测试。**

```python
@pytest.mark.asyncio
async def test_grant_candidates_exclude_inaccessible_and_historical_agents(service, member_actor, agents):
    candidates = await service.list_grant_candidates(actor=member_actor, legacy_agents=agents)
    assert {candidate.agent_key for candidate in candidates} == {"owned", "shared", "public", "use-only"}
    assert "historical-read-only" not in {candidate.agent_key for candidate in candidates}

@pytest.mark.asyncio
async def test_revoked_grant_is_not_active(repository, user_id, agent_id):
    await repository.set_grant(owner_user_id=user_id, agent_id=agent_id, enabled=True)
    await repository.set_grant(owner_user_id=user_id, agent_id=agent_id, enabled=False)
    assert not await repository.has_active_grant(owner_user_id=user_id, agent_id=agent_id)
```

- [ ] **Step 2: 运行授权测试，确认服务和仓储方法尚不存在。**

Run:

```powershell
pytest "tests/unit/personal_library/test_service.py" "tests/integration/test_personal_library_repository.py" -v
```

Expected: FAIL，缺少候选过滤或授权状态实现。

- [ ] **Step 3: 实现授权仓储和服务。**

- 候选列表仅使用 `AgentMembershipService.list_accessible` 返回的非 `historical_read_only` Agent；
- 使用 `agent_database_id(agent_key)` 保存授权关系；
- `enabled=True` 使用 UPSERT 写入 `active`、设置 `granted_at`、清空 `revoked_at`；
- `enabled=False` 仅更新已有记录为 `revoked` 并设置 `revoked_at`；不存在授权记录的撤销保持幂等，不创建伪授权；
- `has_active_grant` 必须以 `owner_user_id + agent_id + status = 'active'` 查询，不缓存结果；
- 管理员调用时也只使用其自己的 `actor.user_id`，不允许 `owner_user_id` 参数替换当前用户。

- [ ] **Step 4: 为授权 API 写失败测试。**

```python
@pytest.mark.asyncio
async def test_admin_cannot_list_or_change_another_users_grants(client_as_admin, user_a_document):
    response = await client_as_admin.get("/api/console/personal-library/grants", params={"owner_user_id": str(user_a_document.owner_user_id)})
    assert response.status_code == 422

@pytest.mark.asyncio
async def test_member_can_revoke_own_use_only_agent_grant(client_as_member, use_only_agent):
    response = await client_as_member.put(
        f"/api/console/personal-library/grants/{use_only_agent.key}",
        json={"enabled": False},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "revoked"
```

- [ ] **Step 5: 实现授权 API。**

```text
GET /api/console/personal-library/grants/candidates
GET /api/console/personal-library/grants
PUT /api/console/personal-library/grants/{agent_key}
```

路由不暴露任意用户 ID 筛选；不可使用 Agent 返回 404；写操作的审计日志记录用户、Agent、启用或撤销结果，不记录资料内容。

- [ ] **Step 6: 为授权对话框写失败测试。**

```tsx
it("shows only the current users accessible agents and revokes one grant", async () => {
  mocks.listCandidates.mockResolvedValue([
    { agentKey: "public", name: "公共助手", source: "公用", enabled: true },
    { agentKey: "private", name: "我的助手", source: "我的", enabled: false },
  ]);
  const user = userEvent.setup();
  render(<PersonalLibraryGrantDialog open onClose={vi.fn()} />);
  await user.click(await screen.findByRole("switch", { name: "公共助手" }));
  expect(mocks.setGrant).toHaveBeenCalledWith("public", false);
  expect(screen.queryByText("其他用户的助手")).not.toBeInTheDocument();
});
```

- [ ] **Step 7: 实现资料库的“Agent 授权”对话框。**

- 由资料库页面打开；
- 显示名称、来源（我的 / 协作 / 公用 / 仅使用）和当前状态；
- 开关操作等待服务端返回后更新，失败则回滚 UI 并显示错误；
- 明确提示“已授权 Agent 仅可读取你的资料库，不能修改”；
- 管理员界面不出现“查看其他用户资料库或授权”的入口。

- [ ] **Step 8: 运行授权回归。**

Run:

```powershell
pytest "tests/unit/personal_library/test_service.py" "tests/unit/app/routers/test_personal_library_router.py" "tests/integration/test_personal_library_repository.py" -v
Set-Location "console"; npx vitest run src/api/modules/personalLibrary.test.ts src/features/files-workspace/PersonalLibraryGrantDialog.test.tsx src/features/files-workspace/PersonalLibraryPanel.test.tsx
```

Expected: 全部通过。

- [ ] **Step 9: R/4-C 用户验收门。**

1. 使用普通用户打开“个人资料库 → Agent 授权”；
2. 确认仅列出该用户当前可使用的 Agent，并显示来源；
3. 授权一个公用或仅使用 Agent，再撤销它；
4. 重新打开对话框，确认状态保持；
5. 管理员登录确认没有他人资料库管理入口；
6. 验收确认前不得进入 R/4-D。

---

### Task 4: R/4-D Agent 按需搜索与分页读取

**Files:**

- Create: `src/qwenpaw/agents/tools/personal_library.py`
- Modify: `src/qwenpaw/personal_library/service.py`
- Modify: `src/qwenpaw/runtime/builder.py`
- Modify: `src/qwenpaw/app/runner/runner.py`
- Create: `tests/unit/agents/tools/test_personal_library.py`
- Create: `tests/unit/personal_library/test_runtime_access.py`
- Modify: `tests/unit/agents/test_effective_model.py`
- Modify: `tests/unit/agents/test_memory_middleware.py`
- Create: `tests/integration/test_personal_library_runtime.py`

**Interfaces:**

- Consumes: Task 3 `PersonalLibraryService.has_active_grant`、可信 `request_context["user_id"]` 和 `request_context["agent_id"]`。
- Produces:

```python
async def personal_library_search(query: str, max_results: int = 5) -> list[dict[str, object]]:
    """搜索已授权资料库中的文本文件，返回安全摘要。"""
async def personal_library_read(document_id: str, offset: int = 0, limit: int = 65536) -> dict[str, object]:
    """读取一个已授权文本文件的安全分页。"""

class PersonalLibraryService:
    async def search_text(self, *, owner_user_id: UUID, query: str, max_results: int) -> list[PersonalLibrarySearchHit]:
        """搜索当前用户已登记的文本资料。"""
    async def read_text_for_agent(self, *, owner_user_id: UUID, agent_key: str, document_id: UUID, offset: int, limit: int) -> PersonalLibraryDocumentContent:
        """确认有效授权后读取资料文本分页。"""
```

- [ ] **Step 1: 写入“未授权不注册工具”和“撤销立即拒绝”的失败测试。**

```python
@pytest.mark.asyncio
async def test_builder_omits_personal_library_tools_without_active_grant(builder, member_request):
    toolkit = await builder.build_toolkit(request_context=member_request)
    assert "personal_library_search" not in {tool.name for tool in toolkit.tool_groups[0].tools}

@pytest.mark.asyncio
async def test_read_rechecks_grant_after_toolkit_was_created(tool_context, grant_repository, user_id, agent_id, document):
    await grant_repository.set_grant(owner_user_id=user_id, agent_id=agent_id, enabled=False)
    with pytest.raises(PersonalLibraryGrantRevoked):
        await tool_context.personal_library_read(str(document.id))
```

- [ ] **Step 2: 运行运行时访问测试，确认因工具尚未注册或授权校验缺失而失败。**

Run:

```powershell
pytest "tests/unit/agents/tools/test_personal_library.py" "tests/unit/personal_library/test_runtime_access.py" -v
```

Expected: FAIL，工具缺失或未发生授权拒绝。

- [ ] **Step 3: 实现受限文本搜索与分页读取服务。**

- 搜索仅遍历当前用户资料库已登记的文本扩展名文件；
- 查询长度限制为 1–256 个字符，`max_results` 限制为 1–20；
- 返回 `document_id`、`relative_path`、最多 512 字符摘要和相关度；
- `read_text_for_agent` 先查有效授权，再查所有者文档，再读文本；
- `offset >= 0`，`limit` 限制为 1–65536；返回内容、是否截断和下一 offset；
- 非文本文件不进入搜索，读取返回明确的 `unsupported_library_document_type`；
- 权限撤销时返回专用异常，在工具层映射成安全的 `forbidden`，不泄露其他用户文档信息。

- [ ] **Step 4: 实现只读 Agent 工具。**

工具闭包只从由 `RuntimeBuilder` 传入的可信上下文取得 `user_id` 和 `agent_id`，不得接受模型提供的用户 ID 或 Agent ID：

```python
def build_personal_library_tools(
    *,
    service: PersonalLibraryService,
    owner_user_id: UUID,
    agent_key: str,
) -> list[Callable[..., Awaitable[dict[str, object]]]]:
    async def personal_library_search(query: str, max_results: int = 5) -> list[dict[str, object]]:
        return [hit.as_tool_payload() for hit in await service.search_text(
            owner_user_id=owner_user_id, query=query, max_results=max_results,
        )]

    async def personal_library_read(document_id: str, offset: int = 0, limit: int = 65536) -> dict[str, object]:
        content = await service.read_text_for_agent(
            owner_user_id=owner_user_id, agent_key=agent_key,
            document_id=UUID(document_id), offset=offset, limit=limit,
        )
        return content.as_tool_payload()

    return [personal_library_search, personal_library_read]
```

在每次 `personal_library_read` 和 `personal_library_search` 调用中执行 `has_active_grant`。工具 docstring 必须说明：资料只读、先搜索再读取、不可修改资料。

- [ ] **Step 5: 在 RuntimeBuilder 中按授权注册工具，且不干扰记忆工具。**

- 从可信请求上下文解析当前登录用户和当前 Agent；
- 仅在用户存在且 `has_active_grant` 为真时，将资料库工具加入 `extra_tools`；
- 公共记忆、个人记忆、ReMe 的 `memory_tools` 与 `MemoryMiddleware` 保持既有装配路径；
- 资料库服务不可用时只省略资料库工具并记录错误，不能阻断对话、公共记忆或个人记忆。

- [ ] **Step 6: 写入公共/个人记忆不回归的测试。**

```python
@pytest.mark.asyncio
async def test_authorized_library_tools_do_not_replace_scoped_memory_tools(builder, authorized_request):
    toolkit = await builder.build_toolkit(request_context=authorized_request)
    names = {tool.name for tool in toolkit.tool_groups[0].tools}
    assert {"memory_search", "personal_library_search", "personal_library_read"} <= names
```

- [ ] **Step 7: 运行运行时与记忆回归。**

Run:

```powershell
pytest "tests/unit/agents/tools/test_personal_library.py" "tests/unit/personal_library/test_runtime_access.py" "tests/unit/agents/test_memory_middleware.py" "tests/integration/test_personal_library_runtime.py" -v
```

Expected: 全部通过；未授权、已撤销、跨用户和非文本文件用例均有明确断言。

- [ ] **Step 8: R/4-D 用户验收门。**

1. 用户向公用 Agent 授权并在资料库创建含唯一关键词的 Markdown；
2. 在该 Agent 对话中要求“搜索我的个人资料库中的唯一关键词并读取文件”；确认仅获得自己的内容；
3. 撤销授权后在相同对话中再次请求读取，确认后端拒绝而非继续返回文件；
4. 确认公共记忆和当前用户个人 ReMe 记忆仍能通过正常对话检索；
5. 验收确认前不得进入 R/4-E。

---

### Task 5: R/4-E 双用户端到端隔离与验收归档

**Files:**

- Create: `e2e/tests/test_personal_library_multi_user.py`
- Modify: `e2e/conftest.py`
- Modify: `e2e/tests/test_files_multi_user.py`
- Create: `docs/project-audit/54-任务6.2-R4-个人资料库验收报告.md`
- Modify: `docs/project-audit/16-多用户架构分阶段实施计划.md`

**Interfaces:**

- Consumes: R/4-A 至 R/4-D 的 UI/API、两个普通用户、同一公用 Agent。
- Produces: 可复跑的双用户浏览器证据和准确的任务状态记录；不将 R/4-E 的成功误标为 R/5 完成。

- [ ] **Step 1: 写入双用户 E2E 失败测试。**

```python
def test_two_users_keep_personal_libraries_and_agent_reads_isolated(browser, user_a, user_b, public_agent):
    page_a = login(browser.new_page(), user_a)
    create_library_text(page_a, "notes/private.md", "A-ONLY-KEYWORD")
    grant_agent(page_a, public_agent)

    page_b = login(browser.new_page(), user_b)
    create_library_text(page_b, "notes/private.md", "B-ONLY-KEYWORD")
    grant_agent(page_b, public_agent)

    assert run_agent_search(page_a, public_agent, "A-ONLY-KEYWORD").contains("A-ONLY-KEYWORD")
    assert not run_agent_search(page_a, public_agent, "B-ONLY-KEYWORD").contains("B-ONLY-KEYWORD")
    revoke_agent(page_a, public_agent)
    assert run_agent_read(page_a, public_agent, "notes/private.md").is_forbidden()
```

- [ ] **Step 2: 运行 E2E，确认尚未满足完整浏览器流程。**

Run:

```powershell
pytest "e2e/tests/test_personal_library_multi_user.py" -v
```

Expected: 在 R/4-A 至 R/4-D 尚未全部实现时失败；不得通过跳过核心断言伪造通过。

- [ ] **Step 3: 完善浏览器辅助函数和 E2E 用例。**

覆盖以下场景：

- 两个用户在同一路径创建同名资料，内容互不覆盖；
- 用户 B 猜测或复用用户 A 文档 ID 得到 404；
- 两人对同一公用 Agent 的授权状态独立；
- 用户 A 撤销后不能继续由 Agent 读取，用户 B 的授权仍有效；
- 浏览器刷新、切换 Agent、重新登录后文件归属和授权状态保持；
- 附件复制进资料库后，原附件和资料副本都可访问；
- 管理员不会出现其他用户资料入口。

- [ ] **Step 4: 运行完整定向验证。**

Run:

```powershell
pytest "tests/unit/personal_library" "tests/unit/agents/tools/test_personal_library.py" "tests/unit/app/routers/test_personal_library_router.py" "tests/integration/test_personal_library_repository.py" "tests/integration/test_personal_library_migration.py" "tests/integration/test_personal_library_runtime.py" "e2e/tests/test_personal_library_multi_user.py" -v
Set-Location "console"; npx vitest run src/api/modules/personalLibrary.test.ts src/features/files-workspace/PersonalLibraryPanel.test.tsx src/features/files-workspace/PersonalLibraryGrantDialog.test.tsx src/features/files-workspace/PersonalWorkspaceNavigator.test.tsx
npx tsc -b --noEmit
npm run build
```

Expected: 所有定向测试、类型检查与生产构建通过；仅可保留项目已有、无新增失败的构建告警。

- [ ] **Step 5: 编写验收报告和更新阶段计划状态。**

报告必须明确：

- 本任务实际变更的表、迁移版本和未迁移时的限制；
- 文件正文与元数据的存储边界；
- 双用户真实浏览器证据；
- 管理员无默认读取权限；
- 公共/个人记忆和 ReMe 的回归结果；
- R/4 明确未实现的版本历史、OCR、单文件 ACL 和 R/5 产物生命周期；
- 未经用户确认不得把 `6.2-R/4` 标记为完成。

- [ ] **Step 6: R/4-E 用户最终验收门。**

请用户按以下步骤验收：

1. 两个普通用户分别创建同名 Markdown，确认互不可见；
2. 两人都授权同一个公用 Agent，分别让 Agent 搜索自己的唯一关键词；
3. 用户 A 撤销授权后验证 A 被拒绝、B 仍可读取；
4. 将临时附件和产物分别复制至资料库，确认源文件还在；
5. 管理员登录确认没有其他用户资料入口；
6. 刷新、切换页面和重新登录后重复检查一次；
7. 用户明确确认后，才将 Task 6.2-R/4 标记完成并讨论 Task 6.2-R/5。

---

## 计划自检

### 规格覆盖

- 私有文件存储、相对路径、元数据、授权记录与 RLS：Task 1；
- 用户主动新建、上传、编辑、移动、删除：Task 1；
- 临时附件、运行空间、产物的显式复制：Task 2；
- 可使用 Agent 的整库授权、即时撤销和管理员边界：Task 3；
- 按需搜索、分页读取、工具动态注册和四层上下文共存：Task 4；
- 双用户同公用 Agent 的真实浏览器隔离、报告与用户确认：Task 5。

### 占位符检查

已检查本计划，未使用 `TBD`、`TODO`、`implement later` 或不含具体断言的“补充测试”类占位语句。

### 接口一致性检查

- 文档主键均为 `UUID`；前端只以字符串传输 UUID；
- 授权外部标识为 `agent_key`，持久化时统一经 `agent_database_id(agent_key)` 转成 UUID；
- 所有文件定位均使用 `relative_path` / `destination_path`，不从客户端接受绝对路径；
- 所有运行时工具均使用可信 `owner_user_id` 与 `agent_key` 闭包，不接受模型传入的身份。
