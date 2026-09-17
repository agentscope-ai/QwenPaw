# Task 4.5-C/1-H 根 MEMORY.md 索引与自动记忆检索默认值实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让新 Agent 默认开启自动记忆检索，并让公共及当前用户私有工作区根目录的 `MEMORY.md` 成为 ReMe 可持续索引、可检索且严格隔离的长期记忆来源。

**Architecture:** 保留 `MEMORY.md` 原路径和唯一事实来源，在 QwenPaw 内注册两个最小 ReMe Step：一个负责把根 `MEMORY.md` 与 `file_store` 状态做差异同步，另一个只监听该固定文件并把变化派发给 ReMe 原生 `update_index_step`。现有 `memory/`、`digest/` 索引任务和 `ScopedMemoryManagerView` 公共+私有合并检索保持不变。

**Tech Stack:** Python 3.10+、Pydantic、ReMe 0.4.1.5、watchfiles、pytest/pytest-asyncio、React/TypeScript、Vitest。

## Global Constraints

- 不移动、复制、覆盖或删除现有 `MEMORY.md`、`memory/`、`digest/` 文件。
- 只允许根目录固定文件 `MEMORY.md` 进入桥接索引；禁止扫描根目录其他 Markdown。
- 新配置默认 `auto_memory_search_config.enabled=true`；已有显式 `false` 必须保持 `false`。
- 公共 ReMe 与每个用户私有 ReMe 使用独立 workspace、metadata 和索引。
- 管理员代管只能访问公共 ReMe，不能读取用户私有记忆。
- 不修改数据库结构、Agent Loop、聊天事件模型、模型选择或工具执行展示。
- 全程使用 UTF-8，不执行 Git commit、push、reset 或分支操作。
- 每个生产代码变更必须先运行对应失败测试，再做最小实现。

## 文件职责映射

- Create: `src/qwenpaw/agents/memory/reme_root_memory.py`：注册根 `MEMORY.md` 初始同步和单文件监听 Step。
- Modify: `src/qwenpaw/agents/memory/reme_config.py`：加载自定义 Step，并把同步/监听接入启动与 `reindex` 任务。
- Modify: `src/qwenpaw/config/config.py`：调整自动记忆检索缺省值，不覆盖显式配置。
- Modify: `tests/unit/config/test_memory_config.py`：覆盖默认开启和显式关闭往返。
- Modify: `tests/unit/agents/memory/test_reme_config.py`：覆盖任务配置、Step 注册和根目录白名单。
- Create: `tests/unit/agents/memory/test_reme_root_memory.py`：覆盖单文件差异识别、过滤和派发行为。
- Modify: `tests/integration/test_reme_lifecycle.py`：覆盖根文件创建、修改、删除、重启与非目标 Markdown 排除。
- Modify: `tests/unit/agents/memory/test_scoped_memory_runtime.py`：覆盖公共/用户 A/用户 B 根文件的运行时目录隔离。
- Modify: `console/src/pages/Agent/Config/components/ReMeLightMemoryCard.test.tsx`：覆盖后端返回默认开启与显式关闭时页面状态保真。
- Modify: `docs/project-audit/16-多用户架构分阶段实施计划.md`：记录 C/1-H 确认门。
- Create: `docs/project-audit/39-任务4.5-C1-H根MEMORY索引验收报告.md`：保存自动化、真实运行和页面验收证据。

---

### Task 1：自动记忆检索缺省值兼容

**Files:**
- Modify: `src/qwenpaw/config/config.py:623-639`
- Modify: `tests/unit/config/test_memory_config.py`
- Modify: `console/src/pages/Agent/Config/components/ReMeLightMemoryCard.test.tsx`

**Interfaces:**
- Consumes: `AutoMemorySearchConfig(enabled: bool, max_results: int)`。
- Produces: 缺失 `enabled` 时解析为 `true`；显式 `false` 时保持 `false`。

- [x] **Step 1：增加后端失败测试**

在 `tests/unit/config/test_memory_config.py` 增加：

```python
def test_reme_auto_memory_search_defaults_to_enabled():
    cfg = ReMeLightMemoryConfig()
    assert cfg.auto_memory_search_config.enabled is True
    assert cfg.auto_memory_search_config.max_results == 2


def test_reme_auto_memory_search_preserves_explicit_disabled_roundtrip():
    source = {
        "auto_memory_search_config": {
            "enabled": False,
            "max_results": 7,
        },
    }
    cfg = ReMeLightMemoryConfig.model_validate(source)
    assert cfg.auto_memory_search_config.enabled is False
    assert cfg.model_dump()["auto_memory_search_config"] == source[
        "auto_memory_search_config"
    ]
```

- [x] **Step 2：运行 RED 测试**

Run:

```powershell
.venv/Scripts/python.exe -m pytest "tests/unit/config/test_memory_config.py" -k "reme_auto_memory_search" -q
```

Expected: 默认值测试 FAIL，实际值为 `False`；显式关闭测试 PASS。

- [x] **Step 3：最小修改 Pydantic 默认值**

将 `AutoMemorySearchConfig.enabled` 改为：

```python
enabled: bool = Field(
    default=True,
    description="Whether to auto search memory on every turn",
)
```

不得增加读取时强制覆盖或迁移所有 Agent 配置的逻辑。

- [x] **Step 4：运行 GREEN 与配置回归**

Run:

```powershell
.venv/Scripts/python.exe -m pytest "tests/unit/config/test_memory_config.py" "tests/unit/config/test_running_config_validation.py" -q
```

Expected: 全部 PASS。

- [x] **Step 5：增加前端保真测试**

在 `ReMeLightMemoryCard.test.tsx` 增加两个表单 fixture：

```tsx
function AutoSearchForm({ enabled }: { enabled: boolean }) {
  const [form] = Form.useForm();
  return (
    <StaticMemoryProvider>
      <Form
        form={form}
        initialValues={{
          reme_light_memory_config: {
            auto_memory_search_config: { enabled, max_results: 2 },
          },
        }}
      >
        <ReMeLightMemoryCard />
      </Form>
    </StaticMemoryProvider>
  );
}
```

断言后端传入 `true` 时开关选中，传入 `false` 时开关未选中；前端不得用本地默认值覆盖响应。

- [x] **Step 6：运行前端测试**

Run:

```powershell
npm --prefix "console" test -- --run "src/pages/Agent/Config/components/ReMeLightMemoryCard.test.tsx"
```

Expected: PASS。

**Task 1 验收效果：** 新建或缺省 Agent 配置展示自动记忆检索开启；已有显式关闭配置刷新后仍关闭。完成后停止汇报结果，等待用户确认再执行 Task 2。

---

### Task 2：根 MEMORY.md 差异同步 Step

**Files:**
- Create: `src/qwenpaw/agents/memory/reme_root_memory.py`
- Create: `tests/unit/agents/memory/test_reme_root_memory.py`
- Modify: `src/qwenpaw/agents/memory/reme_config.py`
- Modify: `tests/unit/agents/memory/test_reme_config.py`

**Interfaces:**
- Produces: `RootMemorySyncStep`, registry backend `qwenpaw_root_memory_sync_step`。
- Consumes: ReMe `BaseStep.context`、`file_store.get_nodes()`、原生 `update_index_step`。
- Event shape: `{"change": "added|modified|deleted", "path": <absolute path>}`。

- [x] **Step 1：增加配置 RED 测试**

在 `test_reme_config.py` 修改索引配置断言：

```python
def test_root_memory_sync_is_wired_without_watching_other_root_markdown():
    cfg = _config_for_embedding(EmbeddingModelConfig())
    assert cfg["jobs"]["index_update_loop"]["watch_dirs"] == [
        "daily_dir",
        "digest_dir",
    ]
    assert cfg["jobs"]["index_update_loop"]["steps"][1] == {
        "backend": "qwenpaw_root_memory_sync_step",
        "dispatch_steps": ["update_index_step"],
    }
    assert cfg["jobs"]["reindex"]["steps"][-1] == {
        "backend": "qwenpaw_root_memory_sync_step",
        "dispatch_steps": ["update_index_step"],
    }
```

- [x] **Step 2：运行配置 RED 测试**

Run:

```powershell
.venv/Scripts/python.exe -m pytest "tests/unit/agents/memory/test_reme_config.py" -k "root_memory_sync" -q
```

Expected: FAIL，配置中尚无自定义 Step。

- [x] **Step 3：增加 Step 行为 RED 测试**

在新测试文件使用真实临时路径和轻量 fake file store，分别覆盖：

```python
@pytest.mark.asyncio
async def test_sync_emits_added_only_for_root_memory(tmp_path): ...

@pytest.mark.asyncio
async def test_sync_emits_modified_when_root_memory_mtime_changes(tmp_path): ...

@pytest.mark.asyncio
async def test_sync_emits_deleted_when_indexed_root_memory_is_removed(tmp_path): ...

@pytest.mark.asyncio
async def test_sync_ignores_other_root_markdown(tmp_path): ...
```

Fake nodes 使用 `FileNode(path="MEMORY.md", st_mtime=...)`；捕获派发给 `update_index_step` 的 `changes`，禁止只断言内部私有字段。

- [x] **Step 4：运行 Step RED 测试**

Run:

```powershell
.venv/Scripts/python.exe -m pytest "tests/unit/agents/memory/test_reme_root_memory.py" -q
```

Expected: collection FAIL 或 backend/class 不存在。

- [x] **Step 5：实现最小同步 Step**

`reme_root_memory.py` 定义：

```python
from reme.components import R
from reme.schema import FileNode
from reme.steps import BaseStep

ROOT_MEMORY_FILENAME = "MEMORY.md"


@R.register("qwenpaw_root_memory_sync_step")
class RootMemorySyncStep(BaseStep):
    async def execute(self):
        assert self.context is not None
        target = self.workspace_path / ROOT_MEMORY_FILENAME
        nodes = await self.file_store.get_nodes()
        indexed = next(
            (node for node in nodes if node.path == ROOT_MEMORY_FILENAME),
            None,
        )
        changes = _root_memory_changes(target, indexed)
        self.context["changes"] = changes
        if changes:
            await self.dispatch_steps(self.dispatch_step_specs, changes=changes)
        self.context.response.metadata["root_memory_changes"] = len(changes)
        return self.context.response
```

`_root_memory_changes(path: Path, indexed: FileNode | None) -> list[dict[str, str]]` 只处理固定文件；mtime 相等时返回空列表。

- [x] **Step 6：将同步 Step 接入 ReMe 配置**

在 `reme_config.py` 顶部导入注册模块，并调整任务顺序：

```python
from . import reme_root_memory as _reme_root_memory  # noqa: F401
```

`index_update_loop.steps`：目录 `init_changes_step` 后增加根文件同步，再进入 watcher。  
`reindex.steps`：`clear_store_step`、目录 `init_changes_step` 后增加根文件同步。

- [x] **Step 7：运行 GREEN 测试**

Run:

```powershell
.venv/Scripts/python.exe -m pytest "tests/unit/agents/memory/test_reme_root_memory.py" "tests/unit/agents/memory/test_reme_config.py" -q
```

Expected: PASS；`test_all_configured_reme_steps_are_registered` 同时证明注册完整。

**Task 2 验收效果：** 启动和手动重建索引能纳入根 `MEMORY.md`，其他根 Markdown 不进入索引；尚不承诺运行中即时监听。完成后等待用户确认再执行 Task 3。

---

### Task 3：根 MEMORY.md 单文件实时监听

**Files:**
- Modify: `src/qwenpaw/agents/memory/reme_root_memory.py`
- Modify: `src/qwenpaw/agents/memory/reme_config.py`
- Modify: `tests/unit/agents/memory/test_reme_root_memory.py`
- Modify: `tests/unit/agents/memory/test_reme_config.py`

**Interfaces:**
- Produces: `RootMemoryWatchStep`，registry backend `qwenpaw_root_memory_watch_step`。
- Consumes: `watchfiles.awatch`、ReMe background job `stop_event`、原生 `update_index_step`。

- [x] **Step 1：增加精确过滤 RED 测试**

测试公开纯函数：

```python
def test_is_root_memory_path_matches_only_exact_workspace_file(tmp_path):
    assert is_root_memory_path(tmp_path / "MEMORY.md", tmp_path)
    assert not is_root_memory_path(tmp_path / "PROFILE.md", tmp_path)
    assert not is_root_memory_path(
        tmp_path / "nested" / "MEMORY.md",
        tmp_path,
    )
```

增加异步 watcher 测试，注入 fake `awatch_factory`，输入 `MEMORY.md` 和 `PROFILE.md` 两个事件，只允许前者被派发。

- [x] **Step 2：运行 watcher RED 测试**

Run:

```powershell
.venv/Scripts/python.exe -m pytest "tests/unit/agents/memory/test_reme_root_memory.py" -k "watch or exact" -q
```

Expected: FAIL，监听 Step/过滤函数不存在。

- [x] **Step 3：实现最小单文件 watcher**

新增：

```python
@R.register("qwenpaw_root_memory_watch_step")
class RootMemoryWatchStep(BaseStep):
    async def execute(self):
        if self.context is None or self.context.stop_event is None:
            raise RuntimeError(
                "qwenpaw_root_memory_watch_step requires stop_event",
            )
        async for raw_changes in awatch(
            self.workspace_path,
            watch_filter=self._filter,
            recursive=False,
            force_polling=True,
            debounce=5_000,
            step=1_000,
            poll_delay_ms=5_000,
            stop_event=self.context.stop_event,
        ):
            changes = root_memory_events(raw_changes, self.workspace_path)
            if changes:
                await self.dispatch_steps(
                    self.dispatch_step_specs,
                    changes=changes,
                )
        return self.context.response
```

`root_memory_events()` 必须只保留绝对路径等于 `<workspace>/MEMORY.md` 的 added/modified/deleted 事件。

- [x] **Step 4：配置独立后台任务**

在 `_base_config()` 增加：

```python
"root_memory_update_loop": {
    "backend": "background",
    "max_file_bytes": _MAX_FILE_BYTES,
    "steps": [
        {
            "backend": "qwenpaw_root_memory_watch_step",
            "dispatch_steps": [
                {"backend": "update_index_step", "persist": True},
            ],
        },
    ],
},
```

初始同步仍只放在主 `index_update_loop`，避免两个后台任务同时执行首次 dump；新后台任务只负责后续固定文件事件。

- [x] **Step 5：运行 GREEN 与关闭生命周期测试**

Run:

```powershell
.venv/Scripts/python.exe -m pytest "tests/unit/agents/memory/test_reme_root_memory.py" "tests/unit/agents/memory/test_reme_config.py" "tests/unit/agents/memory/test_reme_startup.py" -q
```

Expected: PASS，停止事件能让 watcher 退出且无残留任务警告。

**Task 3 验收效果：** 服务运行期间直接修改或删除根 `MEMORY.md` 后，ReMe 索引自动更新，不需要手动重建；其他根文件变化不会触发索引。完成后等待用户确认再执行 Task 4。

---

### Task 4：真实 ReMe 生命周期与根文件检索

**Files:**
- Modify: `tests/integration/test_reme_lifecycle.py`

**Interfaces:**
- Consumes: `get_reme_app_config()`、ReMe `start/run_job/close`。
- Produces: 可重复的根文件创建、修改、删除、重启持久化证据。

- [x] **Step 1：扩展生命周期 RED 测试**

在临时 workspace 写入：

```python
(tmp_path / "MEMORY.md").write_text(
    "root-memory-unique-token",
    encoding="utf-8",
)
(tmp_path / "PROFILE.md").write_text(
    "profile-must-not-be-indexed-token",
    encoding="utf-8",
)
```

启动并 `reindex` 后断言：

```python
root_result = await app.run_job("search", query="root-memory-unique-token")
profile_result = await app.run_job(
    "search",
    query="profile-must-not-be-indexed-token",
)
assert "MEMORY.md" in str(root_result.answer)
assert "PROFILE.md" not in str(profile_result.answer)
```

随后修改根文件为新唯一词，等待有界轮询至新词可检索；删除文件后等待结果消失。关闭并重启，断言删除状态保持。

- [x] **Step 2：运行集成 RED 测试**

Run:

```powershell
.venv/Scripts/python.exe -m pytest "tests/integration/test_reme_lifecycle.py" -q
```

Expected: 在 Task 2/3 完成前根文件检索断言 FAIL；完成后转为 PASS。

- [x] **Step 3：仅修复集成暴露的最小生产缺陷**

允许修改 `reme_root_memory.py` 或 `reme_config.py`，但不得降低精确过滤边界，也不得通过扩大 `watch_dirs` 到整个 workspace 让测试通过。

- [x] **Step 4：运行 GREEN 与扩大 ReMe 回归**

Run:

```powershell
.venv/Scripts/python.exe -m pytest "tests/integration/test_reme_lifecycle.py" "tests/unit/agents/memory" -q
```

Expected: PASS，无 watcher 未关闭、文件句柄或 ReMe 后台任务警告。

**Task 4 验收效果：** 真实 ReMe 能检索根 `MEMORY.md`，实时修改和删除同步，关闭/重启不复活已删除内容。完成后等待用户确认再执行 Task 5。

---

### Task 5：公共/个人根 MEMORY.md 隔离与合并检索

**Files:**
- Modify: `tests/unit/agents/memory/test_scoped_memory_runtime.py`
- Modify: `tests/unit/agents/memory/test_memory_search_merge.py`
- Modify: `tests/isolation/test_adbpg_memory_scope.py`（只做跨后端身份回归，不改变 ADBPG 实现）
- Create: `tests/integration/test_reme_root_memory_scope.py`

**Interfaces:**
- Consumes: `ScopedMemoryRuntimePool.get_private()`、`ReMeLightMemoryManager.scoped_memory_search()`。
- Produces: 公共+当前用户合并且不包含其他用户的真实检索证据。

- [x] **Step 1：增加目录隔离 RED 测试**

断言公共、用户 A、用户 B 的根文件路径分别为：

```text
<agent-workspace>/MEMORY.md
<working-dir>/user_workspaces/<user-a>/<agent-id>/MEMORY.md
<working-dir>/user_workspaces/<user-b>/<agent-id>/MEMORY.md
```

并断言三个 `mem_metadata` 目录互不相同。

- [x] **Step 2：增加真实三运行时检索测试**

在三个 workspace 分别写入唯一词：`public-root-token`、`user-a-root-token`、`user-b-root-token`。启动三个 ReMe manager 后：

```python
result_a = await public_manager.scoped_memory_search(
    query="root-token",
    max_results=10,
    actor_user_id=str(user_a),
)
assert "public-root-token" in text(result_a)
assert "user-a-root-token" in text(result_a)
assert "user-b-root-token" not in text(result_a)
```

用户 B 做对称断言；管理员治理上下文只调用公共 manager，不构造任意私有 runtime。

- [x] **Step 3：运行 RED 测试**

Run:

```powershell
.venv/Scripts/python.exe -m pytest "tests/integration/test_reme_root_memory_scope.py" "tests/unit/agents/memory/test_scoped_memory_runtime.py" -q
```

Expected: 若根文件桥接未进入私有 runtime 或路径错误则 FAIL。

- [x] **Step 4：修复最小作用域接线缺陷**

现有作用域接线直接通过新增真实测试，无需修改生产代码；本步骤以“确认无缺陷、不做无效改动”完成。

只允许调整现有 `ScopedMemoryRuntimePool`/`ReMeLightMemoryManager._create_scoped_runtime()` 的根路径接线；不得接受客户端用户 ID，不得让公共 manager 复用私有 metadata。

- [x] **Step 5：运行 GREEN 与隔离回归**

Run:

```powershell
.venv/Scripts/python.exe -m pytest "tests/integration/test_reme_root_memory_scope.py" "tests/isolation" "tests/unit/agents/memory/test_memory_search_merge.py" "tests/unit/agents/memory/test_memory_job_scope_routing.py" -q
```

Expected: PASS。

**Task 5 验收效果：** 同一个 Agent 下，用户只会检索到公共根记忆和自己的根记忆；管理员代管看不到任何用户根记忆。完成后等待用户确认再执行 Task 6。

---

### Task 6：阶段回归、真实页面与验收归档

**Files:**
- Modify: `docs/project-audit/16-多用户架构分阶段实施计划.md`
- Create: `docs/project-audit/39-任务4.5-C1-H根MEMORY索引验收报告.md`
- Optional evidence: `docs/project-audit/evidence/task-4-5-c1-h-*.png`

**Interfaces:**
- Consumes: Tasks 1–5 的测试、API 和页面行为。
- Produces: C/1-H 可审计验收报告；不进入 C/2。

- [x] **Step 1：运行完整专项后端回归**

Run:

```powershell
.venv/Scripts/python.exe -m pytest "tests/unit/agents/memory" "tests/unit/agents/test_memory_middleware.py" "tests/unit/config/test_memory_config.py" "tests/isolation" "tests/integration/test_memory_scope_migration.py" "tests/integration/test_reme_lifecycle.py" "tests/integration/test_reme_root_memory_scope.py" -q
```

Expected: 0 failed。

- [x] **Step 2：运行前端测试、类型检查和生产构建**

Run:

```powershell
npm --prefix "console" test -- --run "src/pages/Agent/Config/components/ReMeLightMemoryCard.test.tsx" "src/features/files-workspace/FilesWorkspace.test.tsx" "src/features/files-workspace/FilesNavigator.test.tsx"
npm --prefix "console" exec -- tsc -b --noEmit
npm --prefix "console" run build
```

Expected: 0 failed，TypeScript 和 build exit 0。

- [x] **Step 3：重启 18089 验收服务并检查运行状态**

Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "tmp/start-18089.ps1"
```

若端口已有旧进程，先只读确认 PID 和命令行；停止旧验收进程属于服务状态变更，应在执行时向用户说明后再操作。启动后验证 `/api/auth/status`、管理员登录、Agent 列表、默认 Agent ReMe status/graph。

- [x] **Step 4：真实页面验证默认开关**

使用隔离的临时测试 Agent 验证：

1. 创建后配置页自动记忆检索默认开启；
2. 关闭并保存、刷新后仍关闭；
3. 恢复开启。

不得污染长期验收数据。若需要删除临时 Agent，删除前按 AGENTS.md 输出危险操作确认并等待用户明确同意；未获同意则保留并清楚标记测试用途。

- [x] **Step 5：真实页面/API 验证根记忆作用域**

用唯一验收词分别写入公共和当前用户根 `MEMORY.md`，等待索引更新后通过 `memory_search` 验证；第二个用户不得看到第一个用户私有验收词。测试内容写入前记录原内容，验收后恢复原内容；恢复属于覆盖文件，执行前按危险操作确认机制请求用户确认。

- [x] **Step 6：生成报告并更新阶段确认门**

报告必须记录：

- 修改文件及职责；
- RED/GREEN 命令和通过数量；
- ReMe 版本；
- 自动默认值及显式关闭证据；
- 根 `MEMORY.md` 创建/修改/删除/重启证据；
- 公共、用户 A、用户 B 和管理员代管矩阵；
- 未索引 `PROFILE.md` 等反证；
- 是否创建/保留临时验收 Agent；
- 已知非阻塞警告；
- 明确 Task 4.5-C/2 尚未开始。

**Task 6 验收效果：** 用户可以从配置页和对话/记忆结果感知功能，后端身份与索引隔离同时成立。完成后停止等待用户验收 C/1-H。

---

## 计划自检结果

- 规格覆盖：默认值、显式关闭、单文件索引、实时变化、公共/私有隔离、管理员代管、前端保真、失败恢复均有对应任务。
- 边界检查：没有监听整个工作区、没有复制正文、没有数据库迁移、没有进入 Agent Loop。
- 类型一致：自定义 backend 固定为 `qwenpaw_root_memory_sync_step` 和 `qwenpaw_root_memory_watch_step`；所有下游配置与测试使用相同名称。
- 危险操作：计划不自动删除 Agent 或覆盖验收记忆；真实验收如需恢复/删除，必须单独确认。
- Git：按用户规则移除所有 commit 步骤。
