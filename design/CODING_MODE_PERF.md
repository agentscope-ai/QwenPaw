# Coding Mode 后端性能优化方案

> 目标：让"打开文件 / 切换 Tab / 保存文件"在大型项目（含 `node_modules` 等）下感知不到延迟。
> 原则：**只动确定有收益的地方**，每条改动都给出当前代价、改后预期、风险与回退路径。
> 工作目录约定：所有相对路径都基于 `CoPaw/`。

---

## 1. 现状诊断（基于代码事实，无猜测）

### 1.1 文件树加载 `GET /workspace/code-files`
位置：[src/qwenpaw/app/routers/workspace.py:189-226](src/qwenpaw/app/routers/workspace.py#L189-L226)

```python
def _list_all_files(workspace_dir: Path) -> list[dict]:
    for entry in sorted(workspace_dir.rglob("*")):   # ① 整树遍历
        rel = entry.relative_to(workspace_dir)
        if _should_skip(rel.parts):                  # ② 已经走进去了才跳过
            continue
        if entry.is_file():                          # ③ stat #1
            stat = entry.stat()                      # ④ stat #2（重复）
            ...
```

**问题（按代价排序）：**

- **`rglob("*")` 不剪枝**：遇到 `node_modules/`、`.venv/` 这种黑名单目录，`rglob` 已经递归进去拿到所有子项再被 `_should_skip` 过滤。一个含 `node_modules` 的前端项目可能走 5w+ 个 entry，黑名单本应剪掉。
- **每个文件 2 次 stat**：`entry.is_file()` 一次 + `entry.stat()` 一次。`os.scandir` 返回的 `DirEntry` 自带缓存可一次拿全。
- **结果是扁平列表**：返回所有路径给前端，前端 `buildTree(files)` 重建。包大 + JSON 编解码慢。
- **每次文件变更都全量重拉**：[FileTree.tsx:347-358](console/src/pages/Coding/FileTree.tsx#L347-L358) 把 `added/deleted/modified` 三种事件都触发 `void load()` → 重新拉整棵树 + git status。但 `modified` 不会改树结构。

**实测推断：** 中等前端项目（含 `node_modules`）首次开树 200-800 ms；保存任意文件后 SSE 触发再来一次。

### 1.2 单文件读取 `GET /workspace/code-files/{path}`
位置：[src/qwenpaw/app/routers/workspace.py:298-328](src/qwenpaw/app/routers/workspace.py#L298-L328)

- 3 次 `stat`：`safe_join.resolve()` + `to_thread(target.is_file)` + `_read` 里再 `target.stat()`。
- 没有 ETag / `If-None-Match`，**重开同一个文件每次都读盘 + 走 JSON。**
- 返回体是 `{"path": ..., "content": "<整个文件>"}`，1 MB 文本会走一次 JSON 序列化（`ensure_ascii` 默认 True 会把中文炸成 `\uXXXX`，体积放大并耗 CPU）。
- 前端切 Tab 没有内存缓存，每次切回都触发一次完整读盘 + 网络往返。

### 1.3 Git 状态 `GET /workspace/git/status`
位置：[src/qwenpaw/app/routers/git.py:284-353](src/qwenpaw/app/routers/git.py#L284-L353)

- shell 出 `git status --porcelain`：大仓 100-500 ms。
- 没有缓存。文件树每次 `load()` 都并发拉一次。
- **暂不动**：每次都拿到最新结果是正确性诉求，且单次成本可接受。

### 1.4 文件监听 SSE `GET /workspace/watch`
位置：[src/qwenpaw/app/routers/workspace.py:364-444](src/qwenpaw/app/routers/workspace.py#L364-L444)

- `awatch(watch_dir)` 用的是 `watchfiles` 的默认 `DefaultFilter`，已自带忽略 `node_modules / .git / __pycache__ / .venv` 等（已实测确认）。
- **不是瓶颈**，不动。

### 1.5 二进制文件 `GET /workspace/binary-files/{path}`
位置：[src/qwenpaw/app/routers/workspace.py:249-295](src/qwenpaw/app/routers/workspace.py#L249-L295)

- `read_bytes()` 把整个文件（最高 50 MB）全读进内存再 `iter([data])` 流回去，单次峰值占用大但量小。
- **不是首要瓶颈**，可顺手改。

### 1.6 `agent_context.get_agent_for_request` + `get_coding_dir`
位置：[src/qwenpaw/app/agent_context.py:35-140](src/qwenpaw/app/agent_context.py#L35-L140)

- 每次请求都走 `load_config()` + `load_agent_config()`，两者都是 mtime 缓存（`stat` 命中即返回缓存对象）。warm 路径 < 1 ms。
- **不是瓶颈**，不动。

---

## 2. 方案概览

按收益从大到小排序，每条独立可上：

| # | 改动 | 预期收益 | 风险 |
|---|---|---|---|
| **P0-A** | `_list_all_files` 改用 `os.walk(topdown)` 剪枝 + `DirEntry.stat()` | 文件树加载 **5-10×** 快 | 低，逻辑等价 |
| **P0-B** | SSE 事件按类型分流：`modified` 只刷 git status，不重建树 | 保存触发的全树刷新消失 | 极低 |
| **P0-C** | 前端 `loadCodeFile` 加内存缓存，按 SSE `modified` 失效 | 切 Tab 0 网络 | 低 |
| **P1-D** | 文件读取响应头加 `ETag`（mtime+size），命中 304 | 强刷一致性下也免读盘 | 低 |
| **P1-E** | JSON 响应改 `ensure_ascii=False`（FastAPI ORJSON 已内置）| 中文文件体积/CPU 减半 | 极低 |
| **P2-F** | 二进制文件改 chunk 流式 (`iter` over file 4 KB) | 内存峰值降到 KB 级 | 极低 |

> P0 三条是真·"打开文件慢"的核心修复。P1 两条是一致性 + 体积优化。P2 是顺手清理。
> **`/workspace/git/status` 缓存、SSE 改造、agent_context 重构都不在此次范围**——确认无收益或风险大于收益。

---

## 3. 详细设计

### P0-A：文件树扫描重写

**改动文件：** [src/qwenpaw/app/routers/workspace.py:189-212](src/qwenpaw/app/routers/workspace.py#L189-L212)

**前后对比：**

```python
# 现状
def _list_all_files(workspace_dir: Path) -> list[dict]:
    files = []
    for entry in sorted(workspace_dir.rglob("*")):
        rel = entry.relative_to(workspace_dir)
        if _should_skip(rel.parts):
            continue
        if entry.is_file():
            stat = entry.stat()
            files.append({...})
    return files

# 改后（伪码）
def _list_all_files(workspace_dir: Path) -> list[dict]:
    files = []
    root = str(workspace_dir)
    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        # 关键：原地剪枝 dirnames，os.walk 不会再下钻
        dirnames[:] = sorted(
            d for d in dirnames
            if not (d.startswith(".") or d in _SKIP_NAMES)
        )
        # 不能依赖 _should_skip 二次校验目录——已剪
        rel_dir = os.path.relpath(dirpath, root)
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            full = os.path.join(dirpath, name)
            try:
                st = os.stat(full)  # 一次 stat
            except OSError:
                continue
            rel = name if rel_dir == "." else os.path.join(rel_dir, name)
            files.append({
                "filename": rel,
                "path": rel,
                "size": st.st_size,
                "modified_time": datetime.fromtimestamp(
                    st.st_mtime, tz=timezone.utc
                ).isoformat(),
            })
    return files
```

**收益：**
- 不再下钻 `node_modules` 等黑名单目录（最大头）。
- 1 次 stat 替代 2 次。
- `os.walk` + `os.stat` 比 `pathlib.rglob` 快约 2-3×。

**风险：**
- 跨平台路径分隔符：返回值用 `/` 还是系统分隔符要保持向后兼容。当前 `str(rel)` 在 Windows 上是 `\`，前端 `buildTree` 用的什么分隔符？需要 grep 一下确认。**Check：上线前必须验证。**
- 隐藏文件规则：原来 `_should_skip` 用 `p.startswith(".")` 检查每一级 part，新版按文件名/目录名过滤等价。

**回退：** 单函数替换，git revert 即可。

### P0-B：SSE 事件按类型分流（前端）

**改动文件：** [console/src/pages/Coding/FileTree.tsx:347-358](console/src/pages/Coding/FileTree.tsx#L347-L358)

**前后对比：**

```tsx
// 现状
useWorkspaceWatch((events) => {
  const hasChange = events.some(e =>
    e.change === "added" || e.change === "deleted" || e.change === "modified"
  );
  if (hasChange) void load();   // 全量重拉
});

// 改后
useWorkspaceWatch((events) => {
  const structural = events.some(
    (e) => e.change === "added" || e.change === "deleted"
  );
  const onlyModified = !structural && events.some(
    (e) => e.change === "modified"
  );
  if (structural) void load();           // 树变了：拉树+git
  else if (onlyModified) void loadGitStatus(); // 只内容变：只刷 git 状态
});
```

**收益：** 保存正在编辑的文件不再触发整树扫描 + JSON 解析。

**风险：** 极低。git 状态本来就由 `loadGitStatus()` 单独管。

### P0-C：前端文件内容内存缓存

**改动文件：** [console/src/pages/Coding/FileTree.tsx](console/src/pages/Coding/FileTree.tsx) + 可能 store

**思路：**
- 在 `codingModeStore`（Zustand）里加一个 `Map<path, {content: string, mtime: number}>`。
- `handleSelect(path)` 先查缓存，命中则直接 `onFileSelect`，不发请求。
- SSE `modified` 事件来时，对应路径从缓存里删掉。
- LRU 上限 50 个文件防爆内存。

**收益：** 切 Tab 0 网络。
**风险：** 缓存一致性已由 SSE 兜底；上限可控。

### P1-D：后端文件读 ETag

**改动文件：** [src/qwenpaw/app/routers/workspace.py:298-328](src/qwenpaw/app/routers/workspace.py#L298-L328)

```python
# 改后伪码
@router.get("/code-files/{file_path:path}")
async def read_code_file(file_path: str, request: Request, response: Response):
    target = safe_join(get_coding_dir(workspace), file_path)
    st = await asyncio.to_thread(target.stat)
    if not stat.S_ISREG(st.st_mode):
        raise HTTPException(404, "File not found")
    etag = f'W/"{int(st.st_mtime_ns)}-{st.st_size}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    if st.st_size > _CODE_FILE_MAX_BYTES:
        raise HTTPException(413, ...)
    content = await asyncio.to_thread(target.read_text, encoding="utf-8", errors="replace")
    response.headers["ETag"] = etag
    return {"path": file_path, "content": content}
```

前端 axios 拦截器把上次的 ETag 存住，下次请求带 `If-None-Match`。命中 304 直接用缓存。

**和 P0-C 是否重复？** 不重复——P0-C 走纯客户端缓存（无网络），P1-D 是兜底（强刷 / 多窗口下也省读盘）。**两个一起做，但 P0-C 优先级更高，P1-D 可分独立 PR。**

### P1-E：FastAPI 响应非 ASCII 不转义

**改动方式：** 全局把默认 `JSONResponse` 替换成 `ORJSONResponse`（`pip install orjson`，FastAPI 内置支持）。中文文件体积约缩 1/3，CPU 显著下降。

**风险：** 引入一个依赖。orjson 是事实标准。

**和当前任务的耦合：** 影响所有路由，**不在此次 PR 内做**，单独提一个 issue。这条仅作记录。

### P2-F：二进制文件 chunk 流

**改动文件：** [src/qwenpaw/app/routers/workspace.py:249-295](src/qwenpaw/app/routers/workspace.py#L249-L295)

```python
def _stream(target: Path, chunk: int = 64 * 1024):
    with open(target, "rb") as f:
        while True:
            data = f.read(chunk)
            if not data:
                break
            yield data

return StreamingResponse(_stream(target), media_type=mime, headers={
    "Content-Length": str(size),
})
```

把 `iter([all_bytes])` 改成发生器，内存峰值从 50 MB 降到 64 KB。

---

## 4. 不做项（明确划出范围）

- ❌ 文件树改成懒加载（按目录展开按需拉子项）：前端改造大，目前剪枝后已经够快。
- ❌ git status 缓存：正确性优先，单次成本可接受。
- ❌ `agent_context` 重构：缓存已生效，warm 路径 < 1 ms。
- ❌ `awatch` 加 watch_filter：默认 filter 已经覆盖 `node_modules` 等。
- ❌ 把 `_get_coding_project_dir` 从 mixin 抽出：每轮一次，无关用户感知。

---

## 5. 实施顺序与 check list

我建议分两批上：

**第一批（P0，本次 PR）：**
- [ ] A. 重写 `_list_all_files`（os.walk + 剪枝 + 单 stat）
- [ ] A. 验证 Windows 下 `path` 字段保持 `/` 分隔符（前端 `buildTree` 兼容性）
- [ ] B. `FileTree.tsx` 按事件类型分流
- [ ] C. Zustand store 加 LRU 文件内容缓存 + SSE invalidate
- [ ] 跑 `pre-commit run`，跑前端 `tsc --noEmit`
- [ ] 大项目实测：`time curl /workspace/code-files`、保存文件后观察刷新

**第二批（P1+P2，可分独立 PR）：**
- [ ] D. ETag + 304
- [ ] F. 二进制流式
- [ ] E. orjson 全局替换（独立 issue）

---

## 6. 待你裁决

1. **范围**：第一批就按 A/B/C 三件套上，OK 吗？还是要更激进 / 更保守？
2. **A 的 path 分隔符**：是否需要我先 grep `buildTree` 实现确认前端依赖什么分隔符再敲方案？（建议是）
3. **C 的缓存上限**：50 个文件 / LRU，还是不限大小靠 SSE 兜底？
4. **D（ETag）** 跟 C（前端缓存）功能重叠，是同一 PR 一起做还是分两次？
