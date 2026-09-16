# Unified File Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将临时附件、个人资料库、产物、Agent 配置和记忆收敛到同一文件中心，使独立文件页、对话预览和收件箱使用一致的文件定位与权限结果。

**Architecture:** 在前端增加一个只表达业务分类的 `FileLocator` 和 `UnifiedFileCenter`，复用现有四类文件 API，并以独立 `MemoryPanel` 接入现有公共/私有记忆 API。对话侧边栏只负责预览单个文件，展开时嵌入相同的文件中心；ReMe 通知补充受控相对记忆路径，使收件箱可以生成文件中心深链接。

**Tech Stack:** React 18、TypeScript 5.8、Ant Design 5、React Router 7、Vitest 4、FastAPI、Python 3.11+、pytest、ReMe Light 0.4.1.5。

## Global Constraints

- 保留现有 `WORKING_DIR/user_workspaces/<user>/<agent>`、公共 Agent workspace 和 PostgreSQL 归属关系，不迁移文件正文。
- 普通界面不得返回或显示物理绝对路径、其他用户 ID、凭据文件和 ReMe 内部目录。
- 私有记忆只能由当前认证用户在当前 Agent 下读取；管理员代管不得读取其他用户私有记忆。
- 本任务中的记忆正文全部只读；不得通过旧 `writeMemoryFile`、`createMemoryFile` UI 暴露编辑或删除操作。
- 索引状态不影响 Markdown 文件列表；索引失败时仍允许读取已经存在的记忆正文。
- 产物列表继续以登记记录为事实源；会话源文件与 `.registered` 快照只能显示为一个逻辑产物。
- 普通对话文件预览不显示原始“工作区、档案、日记、知识库”导航。
- 不新增前端或后端依赖。
- 未经用户明确要求，不执行或计划 `git commit`、`git push`、分支创建或历史重写。

---

## File Structure

### 新增文件

- `console/src/features/files-workspace/fileLocator.ts`：五类业务文件定位、查询参数解析和深链接生成。
- `console/src/features/files-workspace/fileLocator.test.ts`：定位对象和 URL 往返测试。
- `console/src/features/files-workspace/MemoryPanel.tsx`：只读公共/私有记忆浏览器。
- `console/src/features/files-workspace/MemoryPanel.test.tsx`：私有默认值、嵌套文件、权限和索引状态测试。
- `console/src/features/files-workspace/AgentConfigPanel.tsx`：明确封装受管理 Agent 配置文件视图。
- `console/src/features/files-workspace/UnifiedFileCenter.tsx`：五类一级页签、受控选中项和深链接状态。
- `console/src/features/files-workspace/UnifiedFileCenter.test.tsx`：五类导航与选中定位测试。
- `console/src/features/files-workspace/FilePreviewPane.tsx`：独立文件页和聊天共用的单文件预览。
- `console/src/features/files-workspace/FilePreviewPane.test.tsx`：各类文件读取、下载和错误状态测试。
- `console/src/pages/Inbox/memoryEventLocator.ts`：从收件箱 payload 安全解析记忆定位。
- `console/src/pages/Inbox/memoryEventLocator.test.ts`：新旧通知和非法 payload 测试。
- `tests/unit/agents/memory/test_reme_inbox_memory_paths.py`：ReMe 写入结果到收件箱定位字段测试。

### 修改文件

- `console/src/features/files-workspace/PersonalWorkspaceNavigator.tsx`：保留兼容导出，内部委托统一文件中心。
- `console/src/features/files-workspace/PersonalWorkspaceNavigator.module.less`：五页签、记忆列表和预览布局。
- `console/src/features/files-workspace/ArtifactPanel.tsx`：增加查看动作并传递 artifact locator。
- `console/src/features/files-workspace/PersonalLibraryPanel.tsx`：增加查看动作并传递 library locator。
- `console/src/features/files-workspace/TemporaryAttachmentsPanel.tsx`：增加查看动作并传递 attachment locator。
- `console/src/features/files-workspace/FilesWorkspace.tsx`：只保留项目/高级工作区与 Agent 配置用途，不再承担普通文件中心记忆入口。
- `console/src/features/files-workspace/FilesNavigator.tsx`：profile-only 继续工作；普通用户路径不再由聊天入口调用。
- `console/src/features/files-workspace/filesWorkspaceScope.ts`：记忆作用域默认选择 private，保留 public 回退。
- `console/src/features/files-workspace/FilesDrawer.tsx`：预览使用 `FilePreviewPane`，展开使用 `UnifiedFileCenter`。
- `console/src/features/files-workspace/FilesDrawer.test.tsx`：验证不再显示原始工作区并能打开统一中心。
- `console/src/features/files-workspace/types.ts`：聊天旧 `FileTarget` 与业务 `FileLocator` 的桥接字段。
- `console/src/features/files-workspace/filesDrawerState.ts`：展开时保留 locator，不改变目标身份。
- `console/src/features/files-workspace/filesDrawerState.test.ts`：预览/展开/收起定位一致性。
- `console/src/pages/Files/index.tsx`：解析 URL 并渲染 `UnifiedFileCenter`。
- `console/src/pages/Chat/index.tsx`：产物链接转换为 artifact locator；项目文件继续保留只读预览兼容。
- `console/src/pages/Chat/artifactDownloadLink.ts`：导出产物 ID 解析函数，避免重复 URL 正则。
- `console/src/pages/Chat/artifactDownloadLink.test.tsx`：产物 URL 解析与外部 URL 拒绝测试。
- `console/src/pages/Inbox/index.tsx`：详情弹窗增加“查看记忆”和“打开来源对话”。
- `console/src/pages/Inbox/hooks/useInboxData.ts`：保留并类型化记忆 payload。
- `console/src/pages/Inbox/hooks/useInboxData.test.ts`：事件字段映射测试。
- `console/src/pages/Inbox/types.ts`：增加记忆事件 payload 类型。
- `console/src/locales/zh.json`、`en.json`、`ja.json`、`ru.json`、`vi.json`、`pt-BR.json`、`id.json`：五类文件和错误状态文案。
- `src/qwenpaw/agents/memory/reme_light_memory_manager.py`：捕获一次记忆任务新增/修改的受控相对路径并写入 inbox payload。
- `src/qwenpaw/runtime/builtin_commands.py`：把可信请求上下文中的来源对话 ID 传入斜杠命令处理器。
- `src/qwenpaw/agents/command_handler.py`：让 `/memorize` 将来源对话 ID 传给记忆任务。
- `src/qwenpaw/agents/middlewares.py`：让自动记忆携带服务端来源对话 ID。
- `tests/unit/runtime/test_builtin_commands.py`、`tests/unit/agents/test_command_handler.py`、`tests/unit/agents/test_middlewares.py`：验证来源对话 ID 只取自可信请求上下文。
- `tests/unit/app/routers/test_memory_files_scope.py`：真实嵌套 private daily 文件列举测试。
- `e2e/tests/test_memory_scope_full.py`：两用户可见性和 `/memorize` 文件显示契约。
- `e2e/tests/test_files_multi_user.py`：文件中心分类和产物单逻辑条目契约。
- `docs/file-storage.md`：由四类文件说明升级为五类统一文件中心说明，并链接设计文档。

---

### Task 1: 建立统一文件定位与深链接协议

**Files:**
- Create: `console/src/features/files-workspace/fileLocator.ts`
- Create: `console/src/features/files-workspace/fileLocator.test.ts`
- Modify: `console/src/features/files-workspace/types.ts`
- Modify: `console/src/pages/Chat/artifactDownloadLink.ts`
- Test: `console/src/pages/Chat/artifactDownloadLink.test.tsx`

**Interfaces:**
- Consumes: 现有 `MemoryScope = "public" | "private"`、`AgentArtifact.id` 和 `/api/console/artifacts/{id}/download` URL。
- Produces: `FileCategory`、`FileLocator`、`parseFileCenterLocation(search)`、`buildFileCenterPath(locator)`、`artifactIdFromDownloadUrl(rawUrl)`。

- [ ] **Step 1: 写定位对象往返失败测试**

```ts
it("round-trips a private daily memory locator", () => {
  const locator: FileLocator = {
    category: "memory",
    agentId: "agent-a",
    relativePath: "2026-09-15/topic.md",
    memoryScope: "private",
    memorySection: "daily",
  };
  expect(parseFileCenterLocation(buildFileCenterPath(locator))).toEqual(locator);
});

it("rejects invalid memory scope instead of falling back", () => {
  expect(
    parseFileCenterLocation(
      "/files?agentId=agent-a&category=memory&memoryScope=user-b",
    ),
  ).toBeNull();
});
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `npm --prefix console run test:run -- src/features/files-workspace/fileLocator.test.ts`  
Expected: FAIL，提示 `fileLocator` 模块不存在。

- [ ] **Step 3: 实现严格的业务定位联合类型**

```ts
export type FileCategory =
  | "attachment"
  | "library"
  | "artifact"
  | "agent_config"
  | "memory";

export type FileLocator = {
  category: FileCategory;
  agentId: string;
  stableId?: string;
  relativePath: string;
  conversationId?: string;
  memoryScope?: "public" | "private";
  memorySection?: "daily" | "digest";
};
```

实现要求：

- 使用 `URL`/`URLSearchParams` 编解码，不手工拼接 query。
- `category === "memory"` 时必须同时具有合法的 `memoryScope`、`memorySection` 和非空 `relativePath`。
- `category === "artifact"` 时必须具有 UUID 格式 `stableId`。
- 不接受 `userId`、绝对路径或 `..` 路径段。
- 导出 `artifactIdFromDownloadUrl`，只解析同源 `/api/console/artifacts/<uuid>/download`。

- [ ] **Step 4: 增加外部产物 URL 和路径穿越测试**

```ts
expect(
  artifactIdFromDownloadUrl(
    "https://evil.example/api/console/artifacts/bd20d801-5fa2-4dd0-8d5e-691806601b5b/download",
  ),
).toBeNull();
expect(parseFileCenterLocation("/files?agentId=a&category=memory&item=../x.md&memoryScope=private&memorySection=daily")).toBeNull();
```

- [ ] **Step 5: 运行定位与下载链接测试**

Run: `npm --prefix console run test:run -- src/features/files-workspace/fileLocator.test.ts src/pages/Chat/artifactDownloadLink.test.tsx`  
Expected: PASS。

### Task 2: 实现只读记忆面板并修复私有记忆空列表

**Files:**
- Create: `console/src/features/files-workspace/MemoryPanel.tsx`
- Create: `console/src/features/files-workspace/MemoryPanel.test.tsx`
- Modify: `console/src/features/files-workspace/filesWorkspaceScope.ts`
- Modify: `console/src/features/files-workspace/memoryScope.test.ts`
- Modify: `tests/unit/app/routers/test_memory_files_scope.py`

**Interfaces:**
- Consumes: `agentApi.getMemoryScopes(agentId, requestContext)`、`workspaceApi.listMemoryFiles(section, scope, requestContext)`、`workspaceApi.loadMemoryFile(path, section, scope, requestContext)`。
- Produces: `MemoryPanel({agentId, requestContext, initialLocator?, onOpen})` 和默认 private 的 `resolveMemoryScopeSelection`。

- [ ] **Step 1: 写“private 优先”和嵌套文件可见测试**

```ts
it("defaults to my private memory and lists nested daily notes", async () => {
  getMemoryScopes.mockResolvedValue({ scopes: [publicScope, privateScope] });
  listMemoryFiles.mockResolvedValue([
    { filename: "2026-09-15/topic.md", size: 12, modified_time: "2026-09-15T23:21:19Z" },
  ]);
  render(<MemoryPanel agentId="agent-a" requestContext={{ agentId: "agent-a" }} onOpen={vi.fn()} />);
  expect(await screen.findByText("topic.md")).toBeVisible();
  expect(listMemoryFiles).toHaveBeenCalledWith("daily", "private", { agentId: "agent-a" });
});
```

- [ ] **Step 2: 运行测试并确认当前 public 默认行为失败**

Run: `npm --prefix console run test:run -- src/features/files-workspace/MemoryPanel.test.tsx src/features/files-workspace/memoryScope.test.ts`  
Expected: FAIL，尚无 `MemoryPanel`，且当前作用域测试期望 public。

- [ ] **Step 3: 将作用域选择规则改为 private 优先**

```ts
export function resolveMemoryScopeSelection(scopes, current) {
  if (current && scopes.some((item) => item.scope === current)) return current;
  return scopes.some((item) => item.scope === "private") ? "private" : "public";
}
```

不存在任何可读 scope 时，面板显示权限错误，不自行构造 public/private 请求。

- [ ] **Step 4: 实现只读 `MemoryPanel`**

面板行为：

- 一级切换“我的记忆/公共记忆”，二级切换“会话记忆/记忆沉淀”。
- 将 `filename` 按 `/` 构造成日期/目录树，但打开时保留完整相对路径。
- 只显示“查看”和“下载”；不得渲染创建、保存、删除、重建索引按钮。
- `index_state !== ready` 时单独显示状态条，仍调用文件列表接口。
- 403 时清空上一个 scope 的文件和预览缓存。
- `initialLocator` 存在时自动选择其 scope/section 并打开对应文件。

- [ ] **Step 5: 增加后端真实嵌套目录测试**

在 `test_memory_files_scope.py` 中使用真实临时目录创建：

```text
user_workspaces/user-a/agent-a/memory/2026-09-15/topic.md
```

调用 `list_memory_files(section="daily", scope=PRIVATE)`，断言返回 `2026-09-15/topic.md`，并断言响应没有 `workspace_path` 和 `user_id`。

- [ ] **Step 6: 运行前后端记忆测试**

Run: `npm --prefix console run test:run -- src/features/files-workspace/MemoryPanel.test.tsx src/features/files-workspace/memoryScope.test.ts`  
Expected: PASS。  
Run: `python -m pytest tests/unit/app/routers/test_memory_files_scope.py tests/unit/app/routers/test_memory_scope_router.py -q`  
Expected: PASS。

### Task 3: 构建五类统一文件中心

**Files:**
- Create: `console/src/features/files-workspace/AgentConfigPanel.tsx`
- Create: `console/src/features/files-workspace/UnifiedFileCenter.tsx`
- Create: `console/src/features/files-workspace/UnifiedFileCenter.test.tsx`
- Modify: `console/src/features/files-workspace/PersonalWorkspaceNavigator.tsx`
- Modify: `console/src/features/files-workspace/PersonalWorkspaceNavigator.test.tsx`
- Modify: `console/src/features/files-workspace/PersonalWorkspaceNavigator.module.less`
- Modify: `console/src/features/files-workspace/ArtifactPanel.tsx`
- Modify: `console/src/features/files-workspace/PersonalLibraryPanel.tsx`
- Modify: `console/src/features/files-workspace/TemporaryAttachmentsPanel.tsx`
- Modify: `console/src/pages/Files/index.tsx`

**Interfaces:**
- Consumes: Task 1 的 `FileLocator`/URL helpers、Task 2 的 `MemoryPanel`、现有三类 panel 和 `FilesWorkspace profileOnly`。
- Produces: `UnifiedFileCenter({agentId, requestContext, initialLocator?, onOpen?})`，所有列表组件统一通过 `onOpen(locator)` 打开文件。

- [ ] **Step 1: 写五个一级页签和深链接选中测试**

```ts
expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
  "临时附件", "个人资料库", "产物", "Agent 配置", "记忆",
]);
expect(screen.queryByRole("tab", { name: "档案" })).not.toBeInTheDocument();
expect(screen.queryByRole("tab", { name: "知识库" })).not.toBeInTheDocument();
```

另写 `initialLocator.category === "memory"` 时自动激活“记忆”的测试。

- [ ] **Step 2: 运行测试并确认失败**

Run: `npm --prefix console run test:run -- src/features/files-workspace/UnifiedFileCenter.test.tsx src/features/files-workspace/PersonalWorkspaceNavigator.test.tsx`  
Expected: FAIL，当前只有四类且名称为“Agent 资料”。

- [ ] **Step 3: 实现 `AgentConfigPanel`**

仅封装：

```tsx
<FilesWorkspace
  scope={{ kind: "agent", agentId }}
  requestContext={requestContext}
  profileOnly
/>
```

标题和说明明确为“Agent 配置”，普通使用者由现有 `can_edit_workspace_files` 结果进入只读模式。

- [ ] **Step 4: 实现 `UnifiedFileCenter`**

- 固定五个页签及顺序。
- 受控状态由 `initialLocator` 初始化；用户点击列表项时更新预览和 URL。
- 切换 Agent 时清空 locator、列表缓存和打开文件，回到“临时附件”。
- `PersonalWorkspaceNavigator.tsx` 暂时改为重新导出 `UnifiedFileCenter`，兼容现有 Files 页面与测试的分阶段迁移；新代码直接引用 `UnifiedFileCenter`。
- 文件页面用 `parseFileCenterLocation(location)` 初始化，非法参数显示默认页而不抛错。

- [ ] **Step 5: 给现有三类列表补充 `onOpen`**

```ts
onOpen?: (locator: FileLocator) => void;
```

- Artifact: `stableId=item.id`、`conversationId=item.conversation_id`。
- Library/Temporary: 使用各自数据库 ID；不得把 `storage_key` 放入 locator。
- 列表仍保留原下载、删除和保存操作。

- [ ] **Step 6: 运行统一中心测试**

Run: `npm --prefix console run test:run -- src/features/files-workspace/UnifiedFileCenter.test.tsx src/features/files-workspace/PersonalWorkspaceNavigator.test.tsx src/features/files-workspace/ArtifactPanel.test.tsx src/features/files-workspace/PersonalLibraryPanel.test.tsx src/features/files-workspace/TemporaryAttachmentsPanel.test.tsx`  
Expected: PASS。

### Task 4: 统一独立文件页与对话预览

**Files:**
- Create: `console/src/features/files-workspace/FilePreviewPane.tsx`
- Create: `console/src/features/files-workspace/FilePreviewPane.test.tsx`
- Modify: `console/src/features/files-workspace/FilesDrawer.tsx`
- Modify: `console/src/features/files-workspace/FilesDrawer.test.tsx`
- Modify: `console/src/features/files-workspace/types.ts`
- Modify: `console/src/features/files-workspace/filesDrawerState.ts`
- Modify: `console/src/features/files-workspace/filesDrawerState.test.ts`
- Modify: `console/src/pages/Chat/index.tsx`
- Modify: `console/src/pages/Chat/artifactDownloadLink.ts`
- Modify: `console/src/pages/Files/index.tsx`

**Interfaces:**
- Consumes: Task 1 的 `FileLocator`、Task 3 的 `UnifiedFileCenter`、现有 `FilePreview` 和各领域下载/读取 API。
- Produces: `FilePreviewPane({locator, requestContext, onClose, onOpenInCenter})`；聊天 `FilesDrawerState` 在 preview/workspace 间保留同一 locator。

- [ ] **Step 1: 写预览展开一致性测试**

```tsx
it("expands an artifact preview into the same unified file center item", async () => {
  renderWithProviders(
    <FilesDrawer
      state={{ kind: "preview", locator: artifactLocator, trigger: null }}
      dispatch={vi.fn()}
      scope={{
        kind: "session",
        agentId: "agent-a",
        sessionId: "session-a",
      }}
    />,
  );
  await user.click(screen.getByRole("button", { name: "在文件中心打开" }));
  expect(screen.getByTestId("unified-file-center")).toHaveAttribute(
    "data-selected-item",
    artifactLocator.stableId,
  );
  expect(screen.queryByRole("tab", { name: "工作区" })).not.toBeInTheDocument();
});
```

- [ ] **Step 2: 运行测试并确认当前展开行为失败**

Run: `npm --prefix console run test:run -- src/features/files-workspace/FilesDrawer.test.tsx src/features/files-workspace/filesDrawerState.test.ts`  
Expected: FAIL，当前 `EXPAND_WORKSPACE` 渲染原始 `FilesWorkspace`。

- [ ] **Step 3: 抽取 `FilePreviewPane`**

按 locator 分类调用已有 API：

- `artifact`：`/api/console/artifacts/{stableId}/download`，使用认证头。
- `memory`：`loadMemoryFile(relativePath, section, scope, context)`。
- `agent_config`：现有 workspace Markdown 读取接口。
- `library`、`attachment`：各自 owner-scoped preview/download 接口。

统一显示 loading、403、404、不可预览和下载失败状态。HTML 继续使用已有安全预览策略，不直接执行来自文件的页面脚本。

- [ ] **Step 4: 改造聊天文件目标**

- 产物下载 URL 通过 `artifactIdFromDownloadUrl` 解析为 artifact locator。
- 当前聊天和 Agent ID 进入 locator 的 `conversationId`/`agentId`。
- 未登记的历史相对路径、代码项目文件继续用旧 `FileTarget` 做单文件预览，但不提供“展开工作区”；不得把它们伪装为产物。
- 已登记产物不再通过相对工作区路径读取，始终使用 artifact ID。

- [ ] **Step 5: 将展开态替换为统一文件中心**

`FilesDrawer` 在已有 locator 时渲染：

```tsx
<UnifiedFileCenter
  agentId={scope.agentId}
  requestContext={{ agentId: scope.agentId }}
  initialLocator={locator}
/>
```

移除普通聊天入口中的 `<FilesWorkspace initialTarget={target} scope={scope} />`。按钮文案统一为“在文件中心打开”；收起后恢复同一 locator 的预览。

- [ ] **Step 6: 运行预览、HTML 和聊天目标测试**

Run: `npm --prefix console run test:run -- src/features/files-workspace/FilePreviewPane.test.tsx src/features/files-workspace/FilesDrawer.test.tsx src/features/files-workspace/filesDrawerState.test.ts src/pages/Chat/artifactDownloadLink.test.tsx src/pages/Chat/ChatPage.test.tsx`  
Expected: PASS。

### Task 5: 为 ReMe 收件箱事件增加记忆定位并提供跳转

**Files:**
- Modify: `src/qwenpaw/runtime/builtin_commands.py`
- Modify: `src/qwenpaw/agents/command_handler.py`
- Modify: `src/qwenpaw/agents/middlewares.py`
- Modify: `src/qwenpaw/agents/memory/reme_light_memory_manager.py`
- Modify: `tests/unit/runtime/test_builtin_commands.py`
- Modify: `tests/unit/agents/test_command_handler.py`
- Modify: `tests/unit/agents/test_middlewares.py`
- Create: `tests/unit/agents/memory/test_reme_inbox_memory_paths.py`
- Create: `console/src/pages/Inbox/memoryEventLocator.ts`
- Create: `console/src/pages/Inbox/memoryEventLocator.test.ts`
- Modify: `console/src/pages/Inbox/types.ts`
- Modify: `console/src/pages/Inbox/hooks/useInboxData.ts`
- Modify: `console/src/pages/Inbox/hooks/useInboxData.test.ts`
- Modify: `console/src/pages/Inbox/index.tsx`

**Interfaces:**
- Consumes: 服务端 `request_context.conversation_id`、ReMe `response.metadata`、当前 memory config 的 `daily_dir`/`digest_dir`、Task 1 的 `buildFileCenterPath`。
- Produces: inbox payload `memory_files: Array<{scope, section, path}>` 与 `source_conversation_id`；前端 `memoryLocatorFromInboxPayload(payload, agentId)`。

- [ ] **Step 1: 写后端 payload 失败测试**

测试在临时私有 workspace 中执行一次模拟 `auto_memory`：运行前无文件，运行后创建 `memory/2026-09-15/topic.md`，断言 `append_inbox_event` 收到：

```python
{
    "job_name": "auto_memory",
    "memory_files": [
        {"scope": "private", "section": "daily", "path": "2026-09-15/topic.md"}
    ],
    "source_conversation_id": "bd20d801-5fa2-4dd0-8d5e-691806601b5b",
}
```

同时断言 payload 不含绝对路径和 user ID。

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m pytest tests/unit/agents/memory/test_reme_inbox_memory_paths.py -q`  
Expected: FAIL，当前 payload 只有 `job_name/session_id/date/hint`。

- [ ] **Step 3: 在 ReMe job 周围捕获记忆文件差异**

增加私有 helper `_snapshot_memory_markdown()` 和 `_changed_memory_files(before)`；前者返回以 `(section, relative_path)` 为键、以 `(mtime_ns, size)` 为值的快照，后者返回经过根目录约束验证的 `scope/section/path` 列表。

实现约束：

- 只扫描配置的 `daily_dir` 和 `digest_dir` 下的 `*.md`。
- key 是 `(section, relative_posix_path)`，value 使用 `mtime_ns` 和大小。
- 路径解析后必须仍位于对应 root，忽略符号链接。
- 只为 `auto_memory`、`auto_dream` 捕获；显式 `/memorize` 复用 `auto_memory` 路径。
- 传给 inbox 的仅是 `scope/section/path`；scope 从当前运行时上下文取得，不从客户端参数猜测。
- 没有检测到变更时不构造文件跳转，保留现有通知行为。

`_run_reme_job_unlocked` 在调用 ReMe 前保存快照，在调用完成后计算差异，再把结果作为内部参数交给 inbox 组装；不得把内部差异参数传给 ReMe。由该方法管理的同步 job 只在差异计算完成后发送一次通知，结果 hook 继续负责真正的后台 job，避免 hook 先发通知导致路径丢失或重复通知。

- [ ] **Step 4: 贯通可信来源对话 ID**

- `runtime/builtin_commands.py` 从 `ctx.request.request_context["conversation_id"]` 读取服务端已经校验过的 UUID，并传给 `CommandHandler`；不接受斜杠命令文本中的 ID。
- `CommandHandler` 的 `/memorize` 调用把该值作为内部 `_source_conversation_id` 传给 memory manager。
- `MemoryMiddleware._scope_identity()` 同样加入服务端 `conversation_id`，供自动记忆使用。
- 记忆管理器在调用 ReMe 前移除 `_source_conversation_id`，仅用于构造 inbox payload；空值和非 UUID 值不写入 payload。
- 补充测试，证明普通自动记忆和 `/memorize` 都使用请求上下文中的 conversation ID，并拒绝用户输入伪造。

- [ ] **Step 5: 将结构化路径写入 inbox payload**

扩展 `_append_reme_job_result_to_inbox`，从内部 kwargs 中提取 `memory_files` 和可信来源会话 ID。写 payload 前再次过滤字段和相对路径。不要从 `response.answer` 正则提取文件名。

- [ ] **Step 6: 写前端安全解析测试**

```ts
expect(memoryLocatorFromInboxPayload(validPayload, "agent-a")).toEqual({
  category: "memory",
  agentId: "agent-a",
  relativePath: "2026-09-15/topic.md",
  memoryScope: "private",
  memorySection: "daily",
});
expect(memoryLocatorFromInboxPayload({ memory_files: [{ path: "../secret" }] }, "agent-a")).toBeNull();
```

- [ ] **Step 7: 在收件箱详情增加动作**

- 有合法记忆 locator：显示“查看记忆”，导航到 `buildFileCenterPath(locator)`。
- 有合法 `source_conversation_id`：显示“打开来源对话”，导航到 `/chat/<id>`。
- 旧通知或非法 payload：只显示正文，不显示灰色无效按钮。
- 点击跳转前关闭详情弹窗并保持通知已读状态。

- [ ] **Step 8: 运行 ReMe 和收件箱测试**

Run: `python -m pytest tests/unit/runtime/test_builtin_commands.py tests/unit/agents/test_command_handler.py tests/unit/agents/test_middlewares.py tests/unit/agents/memory/test_reme_inbox_memory_paths.py tests/unit/agents/memory/test_reme_daily_paper.py tests/unit/app/inbox/test_inbox_store.py -q`  
Expected: PASS。  
Run: `npm --prefix console run test:run -- src/pages/Inbox/memoryEventLocator.test.ts src/pages/Inbox/hooks/useInboxData.test.ts src/features/files-workspace/fileLocator.test.ts`  
Expected: PASS。

### Task 6: 收敛文案、完成跨用户与真实页面验收

**Files:**
- Modify: `console/src/locales/zh.json`
- Modify: `console/src/locales/en.json`
- Modify: `console/src/locales/ja.json`
- Modify: `console/src/locales/ru.json`
- Modify: `console/src/locales/vi.json`
- Modify: `console/src/locales/pt-BR.json`
- Modify: `console/src/locales/id.json`
- Modify: `e2e/tests/test_memory_scope_full.py`
- Modify: `e2e/tests/test_files_multi_user.py`
- Modify: `docs/file-storage.md`

**Interfaces:**
- Consumes: Tasks 1-5 的五类导航、深链接、记忆 payload 和预览组件。
- Produces: 完整本地化文案、端到端隔离证据和更新后的用户文档。

- [ ] **Step 1: 增加文案契约测试或更新现有组件测试**

至少验证中文环境中存在：

```text
临时附件
个人资料库
产物
Agent 配置
记忆
我的记忆
公共记忆
会话记忆
记忆沉淀
在文件中心打开
查看记忆
打开来源对话
```

并断言普通文件中心不再显示“档案”和作为记忆分类的“知识库”。其他语言使用明确英文基线，不保留缺失 key。

- [ ] **Step 2: 扩展多用户记忆端到端测试**

场景：

1. 用户 A 与用户 B 都可使用 Agent X。
2. 用户 A 的 private daily 目录创建唯一 `a-private.md`。
3. 用户 B 的 private daily 目录创建唯一 `b-private.md`。
4. 用户 A 的文件中心返回 A 和记忆公共文件，不返回 B。
5. 用户 B 返回 B 和记忆公共文件，不返回 A。
6. 管理员 governance 请求只有 public scope。

- [ ] **Step 3: 扩展五类文件与产物端到端测试**

- 同一产物源文件和登记快照只返回一条 artifact API 记录。
- 产物响应包含 artifact ID、Agent 和来源会话，不包含物理绝对路径。
- 用户 B 使用用户 A 的 artifact ID 下载返回 404/403。
- 临时附件、个人资料库和 Agent 配置继续使用各自权限边界。

- [ ] **Step 4: 更新文件存储文档**

将标题改为“统一文件中心的五类内容”，保留现有四类物理存储说明，新增：

- 记忆不是个人资料库。
- private/public 与 daily/digest 的页面名称映射。
- Agent 配置只是工作区受管理子集。
- 对话预览和独立文件页使用相同逻辑文件身份。
- `.registered` 是产物快照，不是重复产物。

- [ ] **Step 5: 运行针对性测试集**

Run: `python -m pytest tests/unit/app/routers/test_memory_files_scope.py tests/unit/app/routers/test_memory_scope_router.py tests/unit/agents/memory/test_reme_inbox_memory_paths.py tests/unit/app/inbox/test_inbox_store.py -q`  
Expected: PASS。  
Run: `npm --prefix console run test:run -- src/features/files-workspace src/pages/Inbox src/pages/Chat/artifactDownloadLink.test.tsx`  
Expected: PASS。

- [ ] **Step 6: 运行构建和端到端隔离测试**

Run: `npm --prefix console run build`  
Expected: TypeScript、Vite 构建和 Monaco CSS 检查全部通过。  
Run: `python -m pytest e2e/tests/test_memory_scope_full.py e2e/tests/test_files_multi_user.py -q`  
Expected: PASS；如测试需要 PostgreSQL，使用当前验收服务配置，不创建或修改生产数据。

- [ ] **Step 7: 真实页面验收**

使用两个验收账号完成：

1. 打开 `/files`，确认五类页签顺序和名称。
2. 在 QA Agent 中执行一次 `/memorize`，确认新文件出现在“记忆 → 我的记忆 → 会话记忆”。
3. 从收件箱点击“查看记忆”，一次跳转并打开该文件。
4. 在对话 `de307e1e-a799-4323-8fbb-4699dea2990c` 打开“青岛旅游总结文档.html”，确认预览成功。
5. 点击“在文件中心打开”，确认定位到产物中的同一个逻辑条目。
6. 确认预览中不出现“工作区、档案、日记、知识库”和内部目录。
7. 切换到第二个用户，确认无法看到第一个用户的产物与私有记忆。

- [ ] **Step 8: 保存验收证据并停止**

记录测试命令、通过数量、实际页面路径、测试账号角色和产生的临时记忆/产物 ID。删除测试生成的临时业务数据需要按项目危险操作规则单独取得明确确认；未获确认时保留并标记为验收数据。
