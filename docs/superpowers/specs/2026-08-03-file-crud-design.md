# /files 路由补齐文件/文件夹管理 API 设计文档

**日期：** 2026-08-03
**状态：** 设计阶段
**作者：** Claude
**类型：** 功能设计

---

## 概述

为 QwenPaw 后端 `/files` 路由补齐文件/文件夹管理操作，支撑前端"文件"页面实现功能丰富的文件管理功能。当前 `/files` 路由仅有 `preview` 端点，本次新增 `list` / `delete` / `mkdir` / `rename` / `upload` / `download` 共 6 个操作，管理全局 `WORKING_DIR`，全部复用现有 FileGuard 安全模型。

> **设计决策**：经过对现有 API 的完整盘点，**不新增** read / write 端点——它们与 `/workspace/code-files` 的读取/写入功能重复。本次只补齐真正缺失的写类与目录操作。

---

## 背景

### 现状盘点

| 能力 | 现有位置 | 作用域 |
|------|----------|--------|
| 预览文件 | `GET/HEAD /files/preview/{path}` | 全局 WORKING_DIR |
| 读写工作区 md | `GET/PUT /workspace/files/{name}` | agent 工作区 |
| 读写任意文件 | `GET/PUT /workspace/code-files/{path}` | agent 工作区 |
| 二进制文件预览 | `GET /workspace/binary-files/{path}` | agent 工作区 |
| 整包 zip 下载 | `GET /workspace/download` | agent 工作区 |
| 整包 zip 上传 | `POST /workspace/upload` | agent 工作区 |
| SSE 文件变更 | `GET /workspace/watch` | agent 工作区 |
| agent 工具 | `read_file`/`write_file`/`edit_file`/`append_file` | agent 侧 |

### 缺口（本次新增）

| 操作 | 现状 |
|------|------|
| **删除文件/文件夹** | ❌ 无任何 delete 端点 |
| **重命名 / 移动** | ❌ 无 |
| **创建文件夹（mkdir）** | ❌ 无 |
| **上传单个文件** | ⚠️ 只有 zip 整包上传，无单文件 |
| **下载单个文件** | ⚠️ 只有 zip 整包下载，无单文件 |
| **目录级列表** | ⚠️ `list_code_files` 返回扁平列表，无按目录递归/分页列表 |

---

## 设计目标

1. **补缺口而非重复：** 只新增缺失操作，读/写复用现有 `/workspace/code-files`
2. **全局作用域：** `/files` 管理全局 `WORKING_DIR`（`~/.qwenpaw`），与 `/workspace`（agent 工作区）清晰分离
3. **安全性：** 写操作始终限制在 WORKING_DIR 内；敏感文件始终拦截
4. **一致性：** 复用现有 `_check_path`、`check_upload_size`、`safe_join` 等基础设施

---

## 架构设计

### 端点表

所有新端点位于 `src/qwenpaw/app/routers/files.py`（`router = APIRouter(prefix="/files")`）。

| 方法 | 端点 | 操作 | 说明 |
|------|------|------|------|
| `GET` | `/files/list` | 目录级列表 | `?path=` 可选，默认 WORKING_DIR；返回 name/path/is_dir/size/modified_time |
| `DELETE` | `/files/delete/{path:path}` | 删除文件/目录 | 目录递归删除需 `?recursive=true` |
| `POST` | `/files/mkdir` | 创建目录 | body `{path}`；已存在返回 409 |
| `POST` | `/files/rename` | 重命名/移动 | body `{source, target}`；target 已存在返回 409 |
| `POST` | `/files/upload` | 上传单文件 | `UploadFile` + `?path=` 目标目录 |
| `GET` | `/files/download/{path:path}` | 下载单文件 | `FileResponse` |

### 安全模型

复用 `_check_path(path)` 作为统一校验入口，返回 `None`（允许）或错误原因字符串：

1. **敏感文件检查**：`FilePathToolGuardian._is_sensitive()` 始终执行
2. **WORKING_DIR 包含检查**：路径解析统一经 `safe_join(_ALLOWED_ROOT, path)`，拒绝任何 `..` / 绝对路径逃逸后再进入文件系统操作（`_check_path` 内的 `is_relative_to` 检查作为纵深防御保留）
   - **写操作**（delete/mkdir/rename/upload）：始终限制在 WORKING_DIR 内
   - **读操作**（list/download）：同样限制在 WORKING_DIR 内（不再跟随 `allow_preview_outside_workspace` 放行外部——该配置仅适用于 `preview_file` 预览工具产生的媒体）
   - **操作分类**：`_check_path` 增加 `for_write: bool = False` 参数

### 错误处理

| 场景 | HTTP 状态 | detail |
|------|-----------|--------|
| 路径被 FileGuard 拦截 | `403` | `SENSITIVE_FILE_BLOCKED` |
| 路径在 WORKING_DIR 外 | `403` | `OUTSIDE_WORKSPACE` |
| 文件/目录不存在 | `404` | `Not found` |
| 目标已存在 | `409` | `Target exists` |
| 删除非空目录未加 `recursive` | `409` | `Directory not empty` |
| 写入无权限 | `500` | `Permission denied` |
| 删除/重命名 WORKING_DIR 根目录 | `400` | `Cannot operate on root` |
| 非法路径（`..` 逃逸、空路径） | `400` | `Path traversal not allowed`（`safe_join` 内置） |

### 边界情况

- **路径归一化**：`expanduser()` → 相对路径拼接到 WORKING_DIR → `resolve()`，再校验
- **删除根目录防护**：`_check_path` 对 WORKING_DIR 根返回允许（preview 需要），因此 `delete` 端点须**显式**拒绝 `target == _ALLOWED_ROOT`（即使 `recursive=true`）——这是独立于 `_check_path` 的额外检查；`rename` 的 source 为 WORKING_DIR 根时同样拒绝
- **删除保护**：目录递归删除需 `recursive=true`；非空目录未加时返回 `409 Directory not empty`
- **上传**：复用 `check_upload_size`（先 `await file.read()` 全部字节再检查，沿用 `skills.py:516` 的 `_read_validated_zip_upload` 模式）；文件名经 `safe_join` 防路径穿越（其内置 `400 Path traversal not allowed`）
- **rename**：source 和 target 都校验；target 已存在时拒绝

---

## 测试策略

- 为每个新端点添加单元测试，用 `tmp_path` 作为 WORKING_DIR（monkeypatch `_ALLOWED_ROOT`）
- 覆盖：正常操作、路径逃逸（`..`）、敏感文件拦截、外部路径写拦截、删除保护、上传大小限制
- 测试目录：`tests/unit/app/...`

---

## 同步与分支工作流

1. `git fetch upstream`
2. 更新 `origin/main` 到 `upstream/main`
3. 从同步后的 `main` 创建新分支：`feather-backend-file-crud`
4. 开发 + 测试 + 提交

---

## 非目标

- 不改动 `/workspace` 路由（agent 级文件操作保持现状）
- 不新增 read/write 端点（与 `/workspace/code-files` 重复）
- 不改动 agent 侧 `file_io.py` 工具
- 不包含前端（console）改动
