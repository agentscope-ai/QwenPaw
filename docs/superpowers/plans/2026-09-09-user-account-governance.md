# 用户账户资料与治理实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为多用户模式增加企业基础用户资料、自助修改用户名和密码、管理员编辑资料与重置密码，并将账户入口固定在侧栏左下角。

**Architecture:** PostgreSQL `users` 表保存固定的一对一企业资料，身份 Repository 统一读写公开用户记录和内部密码凭据。当前用户能力放在 `/api/me`，管理员治理能力放在 `/api/admin/users`；前端用独立账户浮层和弹窗复用认证状态，管理员页面维护其他用户。

**Tech Stack:** Python 3.11+、FastAPI、Pydantic、SQLAlchemy async、PostgreSQL、Alembic、pwdlib/Argon2id、React 18、TypeScript、Ant Design 5、Zustand、Vitest、pytest。

## Global Constraints

- 资料字段只包含 `username`、`display_name`、`email`、`phone`、`department`、`job_title`、`remark`。
- 不增加工号、头像、直属上级和办公地点，不引入附件存储。
- 密码、密码哈希和会话令牌不得出现在公开响应、日志或审计详情中。
- 当前用户修改密码必须验证旧密码；管理员重置密码不要求旧密码。
- 两类改密成功后都撤销目标用户全部会话。
- Legacy 单用户模式保持现有更新逻辑。
- 遵循现有中英文代码注释风格和 UTF-8 编码。
- 按用户要求不创建分支、不执行 `git commit` 或 `git push`。

---

### Task 1: 用户资料数据库迁移和公开领域模型

**Files:**
- Create: `migrations/versions/0019_user_account_profiles.py`
- Modify: `src/qwenpaw/persistence/repository_provider.py`
- Modify: `src/qwenpaw/identity/models.py`
- Modify: `src/qwenpaw/identity/repository.py`
- Modify: `tests/unit/persistence/test_repository_provider_revision.py`
- Modify: `tests/unit/identity/test_user_service.py`
- Modify: `tests/integration/test_migrations.py`

**Interfaces:**
- Consumes: 现有 `users` 表、`UserRecord`、`CredentialRecord`、`PostgresUserRepository`。
- Produces: `UserProfileUpdate`；扩展后的 `UserRecord`；`PostgresUserRepository.update_profile(user_id, profile)`；Schema revision `0019_user_account_profiles`。

- [ ] **Step 1: 写迁移和 Repository 失败测试**

新增测试，明确以下可观察行为：迁移头版本为 `0019_user_account_profiles`；从完整数据库行构造 `UserRecord` 时保留六个资料字段和三个时间字段；`update_profile()` 把空字符串规范化为 `None`；重复用户名映射为 `DuplicateUsernameError`。

```python
profile = UserProfileUpdate(
    username=" alice ",
    display_name=" Alice Chen ",
    email=" ALICE@EXAMPLE.COM ",
    phone=" +86 138-0000-0000 ",
    department=" 研发部 ",
    job_title=" 平台工程师 ",
    remark=" 维护账户平台 ",
)
updated = await repository.update_profile(user_id, profile)
assert updated.username == "alice"
assert updated.email == "alice@example.com"
assert updated.display_name == "Alice Chen"
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/identity/test_user_service.py tests/unit/persistence/test_repository_provider_revision.py tests/integration/test_migrations.py -q`

Expected: 因 `UserProfileUpdate`、资料列和 `0019_user_account_profiles` 尚不存在而失败。

- [ ] **Step 3: 实现迁移和模型**

迁移增加六个可空列：`display_name varchar(128)`、`email varchar(254)`、`phone varchar(32)`、`department varchar(128)`、`job_title varchar(128)`、`remark varchar(500)`；downgrade 仅删除这六列。将 `EXPECTED_SCHEMA_REVISION` 更新为 `0019_user_account_profiles`。

`UserRecord` 增加六个可空资料字段和 `created_at`、`updated_at`、`last_login_at`，为兼容现有测试构造器均提供 `None` 默认值。新增冻结数据类：

```python
@dataclass(frozen=True, slots=True)
class UserProfileUpdate:
    username: str
    display_name: str | None = None
    email: str | None = None
    phone: str | None = None
    department: str | None = None
    job_title: str | None = None
    remark: str | None = None
```

Repository 的所有 SELECT/RETURNING 使用同一列常量，避免新增字段遗漏；`update_profile()` 只更新资料列和 `updated_at`。

- [ ] **Step 4: 运行定向测试确认 GREEN**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/identity/test_user_service.py tests/unit/persistence/test_repository_provider_revision.py tests/integration/test_migrations.py -q`

Expected: 全部通过。

---

### Task 2: 资料校验和密码变更领域服务

**Files:**
- Modify: `src/qwenpaw/identity/service.py`
- Modify: `src/qwenpaw/identity/governance.py`
- Modify: `src/qwenpaw/identity/repository.py`
- Modify: `tests/unit/identity/test_user_service.py`
- Modify: `tests/unit/identity/test_user_governance.py`

**Interfaces:**
- Consumes: Task 1 的 `UserProfileUpdate`、Repository `update_profile()` 和 `update_password_hash()`。
- Produces: `UserService.update_profile()`、`UserService.change_password()`、`UserService.reset_password()`；`CurrentPasswordIncorrectError`；`UserGovernanceService.update_profile()`、`reset_password()`。

- [ ] **Step 1: 写领域行为失败测试**

测试这些真实行为：用户名去空白且不能为空；邮箱小写并校验；手机号只允许数字、空格、`+()-`；各字段长度受限；自助改密旧密码错误不写库；成功改密生成新哈希；管理员重置不读取旧凭据；治理服务改密后调用 `revoke_all(user_id)`。

```python
with pytest.raises(CurrentPasswordIncorrectError):
    await service.change_password(user_id, "wrong", "NewPass!2026")
assert repository.password_updates == []

revoked = await governance.reset_password(member.id, "NewPass!2026")
assert revoked == 2
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/identity/test_user_service.py tests/unit/identity/test_user_governance.py -q`

Expected: 新服务方法和错误类型不存在而失败。

- [ ] **Step 3: 实现最小领域逻辑**

集中实现 `_normalize_profile()`，空字符串转 `None`，邮箱使用保守正则 `^[^\s@]+@[^\s@]+\.[^\s@]+$`，手机号使用 `^[0-9+()\-\s]+$`。`change_password()` 按用户 ID 读取凭据、验证旧密码、写入新 Argon2id 哈希；`reset_password()` 仅验证新密码非空并写哈希。治理服务在密码写入成功后撤销全部会话。

- [ ] **Step 4: 运行定向测试确认 GREEN**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/identity/test_user_service.py tests/unit/identity/test_user_governance.py -q`

Expected: 全部通过。

---

### Task 3: 当前用户和管理员 HTTP API

**Files:**
- Modify: `src/qwenpaw/app/routers/me.py`
- Modify: `src/qwenpaw/app/routers/admin_users.py`
- Modify: `src/qwenpaw/app/routers/auth.py`
- Modify: `tests/unit/app/routers/test_multi_user_auth.py`
- Modify: `tests/unit/app/routers/test_admin_users.py`

**Interfaces:**
- Consumes: Task 2 的资料和密码服务。
- Produces: `PATCH /api/me/profile`、`POST /api/me/change-password`、`PATCH /api/admin/users/{id}/profile`、`POST /api/admin/users/{id}/reset-password`；所有用户响应包含资料和时间字段。

- [ ] **Step 1: 写路由失败测试**

覆盖本人资料更新、用户名冲突、错误旧密码、成功改密撤销会话、管理员资料编辑、管理员重置密码、普通用户访问管理员接口返回 403，以及请求体额外传入 `platform_role/status/password_hash` 时返回 422。

```python
response = client.patch("/api/me/profile", json={"username": "alice", "department": "研发部"})
assert response.status_code == 200
assert response.json()["user"]["department"] == "研发部"
assert "password_hash" not in response.text

response = client.post(
    f"/api/admin/users/{member_id}/reset-password",
    json={"new_password": "NewPass!2026"},
)
assert response.json() == {"revoked_sessions": 2}
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/app/routers/test_multi_user_auth.py tests/unit/app/routers/test_admin_users.py -q`

Expected: 新端点返回 404 或响应缺字段。

- [ ] **Step 3: 实现 Pydantic 契约和错误映射**

定义 `ProfileUpdateRequest`、`ChangePasswordRequest`、`AdminResetPasswordRequest`，统一使用 `extra="forbid"`。资料更新响应为 `{ "user": UserResponse }`；两类改密响应为 `{ "revoked_sessions": int }`。将 `DuplicateUsernameError` 映射为 409、`CurrentPasswordIncorrectError` 映射为 400、用户不存在映射为 404。

保留 Legacy `/auth/update-profile`；多用户页面只调用 `/me` 新接口。

- [ ] **Step 4: 运行路由与鉴权测试确认 GREEN**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/app/routers/test_multi_user_auth.py tests/unit/app/routers/test_admin_users.py tests/unit/access -q`

Expected: 全部通过，响应中无密码或哈希。

---

### Task 4: 前端认证状态、API 和账户弹窗

**Files:**
- Modify: `console/src/api/modules/auth.ts`
- Modify: `console/src/api/modules/adminUsers.ts`
- Modify: `console/src/stores/authStore.ts`
- Modify: `console/src/stores/authStore.test.ts`
- Create: `console/src/layouts/AccountProfileModal.tsx`
- Create: `console/src/layouts/AccountProfileModal.test.tsx`
- Modify: `console/src/layouts/SidebarAccountSummary.tsx`
- Modify: `console/src/layouts/SidebarAccountSummary.test.tsx`
- Modify: `console/src/locales/zh.json`
- Modify: `console/src/locales/en.json`

**Interfaces:**
- Consumes: Task 3 的 HTTP 接口。
- Produces: 扩展 `AuthUser`/`AdminUser`；`authApi.updateProfile()`、`changePassword()`；`adminUsersApi.updateProfile()`、`resetPassword()`；`authStore.updateUser()`；`AccountProfileModal`。

- [ ] **Step 1: 写 API、Store 和弹窗失败测试**

测试 API 使用正确路径与请求体；资料保存后 Zustand 中的用户同步更新；两次新密码不一致时不发请求；改密成功清除认证状态；账户弹窗显示全部六个资料字段且不显示排除字段。

```tsx
await user.click(screen.getByRole("button", { name: "保存资料" }));
await waitFor(() => expect(authApi.updateProfile).toHaveBeenCalledWith({
  username: "alice",
  display_name: "Alice Chen",
  email: "alice@example.com",
  phone: "",
  department: "研发部",
  job_title: "平台工程师",
  remark: "",
}));
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `npm run test:run -- src/stores/authStore.test.ts src/layouts/AccountProfileModal.test.tsx src/layouts/SidebarAccountSummary.test.tsx`

Workdir: `console`

Expected: 新 API、Store 方法和组件不存在而失败。

- [ ] **Step 3: 实现账户资料和改密 UI**

`AccountProfileModal` 使用 Ant Design `Modal + Tabs + Form`。基本资料页包含用户名、显示名、邮箱、手机号、部门、职位、备注；密码页包含旧密码、新密码和确认新密码。保存资料后调用 `updateUser()`；改密成功调用现有登出清理流程并导航 `/login`。错误通过表单或 message 展示，不记录输入值。

`SidebarAccountSummary` 显示 `display_name || username`，保留角色标签。

- [ ] **Step 4: 运行前端定向测试确认 GREEN**

Run: `npm run test:run -- src/stores/authStore.test.ts src/layouts/AccountProfileModal.test.tsx src/layouts/SidebarAccountSummary.test.tsx`

Workdir: `console`

Expected: 全部通过。

---

### Task 5: 固定侧栏账户入口、退出确认和菜单顺序

**Files:**
- Modify: `console/src/layouts/Sidebar.tsx`
- Modify: `console/src/layouts/index.module.less`
- Modify: `console/src/layouts/registry/builtinMenu.ts`
- Create: `console/src/layouts/Sidebar.account.test.tsx`
- Modify: `console/src/layouts/registry/builtinRoutes.contract.test.tsx`

**Interfaces:**
- Consumes: Task 4 的 `AccountProfileModal` 和 `SidebarAccountSummary`。
- Produces: 固定底部 `AccountPopover` 行为；退出确认；用户管理菜单排在插件管理之后。

- [ ] **Step 1: 写布局和交互失败测试**

使用真实 Sidebar 组件断言：账户区拥有固定底部布局类；悬停显示“账户信息/退出登录”；账户信息打开居中弹窗；点击退出登录先显示确认框且未调用 `logout`，确认后才调用；折叠模式仍有可访问名称；菜单适配结果中 `core.admin-users` 位于 `core.plugin-manager` 后。

- [ ] **Step 2: 运行测试确认 RED**

Run: `npm run test:run -- src/layouts/Sidebar.account.test.tsx src/layouts/registry/builtinRoutes.contract.test.tsx`

Workdir: `console`

Expected: 当前账户区直接展示操作、没有确认弹窗，菜单顺序错误。

- [ ] **Step 3: 实现固定布局和交互**

侧栏根容器设为 `display:flex; flex-direction:column; height:100%`；菜单容器使用 `flex:1; min-height:0; overflow-y:auto`；账户区使用 `flex:none`。Popover 在桌面 `hover` 触发、移动端 `click` 触发。退出用 `Modal.confirm({ centered: true })`，确认后才调用 store `logout()`。

将 `core.admin-users.order` 改为 `120`，插件管理保持 `110`。

- [ ] **Step 4: 运行前端定向测试确认 GREEN**

Run: `npm run test:run -- src/layouts/Sidebar.account.test.tsx src/layouts/registry/builtinRoutes.contract.test.tsx`

Workdir: `console`

Expected: 全部通过。

---

### Task 6: 管理员用户资料和密码重置界面

**Files:**
- Modify: `console/src/pages/Admin/Users/index.tsx`
- Modify: `console/src/pages/Admin/Users/index.test.tsx`
- Modify: `console/src/pages/Admin/Users/errors.ts`
- Modify: `console/src/pages/Admin/Users/errors.test.ts`
- Modify: `console/src/locales/zh.json`
- Modify: `console/src/locales/en.json`

**Interfaces:**
- Consumes: Task 4 的扩展 `AdminUser` 和管理员 API。
- Produces: 用户列表企业字段、编辑资料弹窗、重置密码弹窗和本人重置后的登出行为。

- [ ] **Step 1: 写管理员页面失败测试**

测试显示名、部门、职位和最后登录时间；编辑资料提交完整字段；密码与确认密码不一致时阻止提交；重置其他用户后刷新列表且不退出；重置当前管理员后清除认证并导航登录页。

- [ ] **Step 2: 运行测试确认 RED**

Run: `npm run test:run -- src/pages/Admin/Users/index.test.tsx src/pages/Admin/Users/errors.test.ts`

Workdir: `console`

Expected: 页面没有编辑资料和重置密码动作。

- [ ] **Step 3: 实现管理员弹窗和响应式列表**

列表加入显示名、部门、职位、最后登录列，设置横向滚动。操作区加入“编辑资料”和“重置密码”。资料弹窗复用相同字段规则；密码弹窗提示所有登录会话将被撤销。通过 `authStore.user.id === target.id` 判断是否重置本人。

- [ ] **Step 4: 运行管理员页面测试确认 GREEN**

Run: `npm run test:run -- src/pages/Admin/Users/index.test.tsx src/pages/Admin/Users/errors.test.ts`

Workdir: `console`

Expected: 全部通过。

---

### Task 7: 全量验证、真实迁移和双用户验收

**Files:**
- Modify: `docs/accoun.md`（仅当验收密码被临时改变时恢复并校对）
- Create: `docs/project-audit/58-用户账户资料与治理验收报告.md`

**Interfaces:**
- Consumes: Tasks 1–6 的完整实现。
- Produces: 已迁移的本地验收 Schema、更新后的 18089 服务、自动化与浏览器验收证据。

- [ ] **Step 1: 运行后端相关回归**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/identity tests/unit/app/routers/test_multi_user_auth.py tests/unit/app/routers/test_admin_users.py tests/unit/persistence tests/integration/test_migrations.py -q`

Expected: 0 failed。

- [ ] **Step 2: 运行前端相关回归、类型检查和生产构建**

Run: `npm run test:run -- src/stores/authStore.test.ts src/layouts/SidebarAccountSummary.test.tsx src/layouts/AccountProfileModal.test.tsx src/layouts/Sidebar.account.test.tsx src/layouts/registry/builtinRoutes.contract.test.tsx src/pages/Admin/Users/index.test.tsx src/pages/Admin/Users/errors.test.ts`

Run: `npm run build`

Workdir: `console`

Expected: 测试 0 failed，TypeScript 和 Vite 构建成功。

- [ ] **Step 3: 备份并迁移验收 Schema**

在 `tmp/` 建立带时间戳的 `pg_dump` 备份并用 `pg_restore --list` 验证可读，然后使用现有 Alembic 配置将 `qwenpaw_test_migrations.qwenpaw_task21_acceptance` 从 `0018_automation_authorization` 升级到 `0019_user_account_profiles`。命令从 Docker 环境读取数据库凭据，不输出完整 DSN。

- [ ] **Step 4: 重启 18089 多用户服务并验证状态**

停止当前 PID `22520` 后使用 `tmp/start-18089.ps1` 启动，确认：

```json
{
  "mode": "multi_user",
  "has_users": true,
  "storage_status": "ready",
  "schema_version": "0019_user_account_profiles"
}
```

- [ ] **Step 5: 执行真实双用户浏览器验收**

使用管理员 `admin-task21` 和普通用户 `task42-user` 两个隔离上下文：

1. 账户入口在不同窗口高度下固定左下角。
2. 悬停显示账户信息和退出登录。
3. 普通用户修改资料后左下角立即更新，管理员账户不受影响。
4. 普通用户错误旧密码被拒绝；正确改密后所有会话失效。
5. 管理员重置普通用户密码后旧密码无法登录、新密码可登录。
6. 退出按钮取消不退出，确认后退出。
7. 用户管理位于插件管理下方，普通用户不可见。

验收结束后恢复 `docs/accoun.md` 记录的测试密码和原资料值，再次验证三组已知账号可登录。

- [ ] **Step 6: 生成验收报告并检查工作区**

报告记录迁移版本、测试数量、浏览器步骤、账号恢复结果和已知限制，不记录密码、密码哈希、Token 或数据库 DSN。运行 `git diff --check`，确认无空白错误；不提交任何文件。
