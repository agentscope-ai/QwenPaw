# Task 6.2-R/5 Agent 产物生命周期 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Agent 发送给用户的产物具备用户、Agent、会话来源和删除状态，并保持文件正文在私有运行空间。

**Architecture:** `send_file_to_user` 在受控 `artifacts/` 目录发布文件后调用专用登记服务。PostgreSQL 保存元数据并由 RLS 按创建用户隔离；文件页从登记表读取状态，再通过既有受保护文件接口下载。删除先校验归属、删除物理文件，再保留 tombstone 元数据。

**Tech Stack:** Python/FastAPI, SQLAlchemy/Alembic, PostgreSQL RLS, React/TypeScript.

## Global Constraints

- 新文件写入英文 `artifacts/`，只兼容读取历史 `产物/`。
- 不接受客户端绝对路径；所有文件路径由服务端按用户和 Agent 运行空间解析。
- 管理员不默认读取其他用户的产物。
- 不改变 R/4 个人资料库、公共/个人记忆或 ReMe 的既有权限边界。

### Task 1: 产物登记与迁移

**Files:** `migrations/versions/0014_artifact_lifecycle.py`, `src/qwenpaw/artifacts/models.py`, `src/qwenpaw/artifacts/repository.py`, `tests/unit/artifacts/test_repository.py`, `tests/integration/test_migrations.py`.

- [ ] 先写失败测试：同一用户/Agent/相对路径可登记；另一用户不可读；软删除保留元数据。
- [ ] 新增表 `user_agent_artifacts(id, owner_user_id, agent_id, conversation_id, relative_path, original_name, media_type, size, sha256, source_tool, status, created_at, deleted_at)` 与唯一路径约束、RLS 和索引。
- [ ] 实现仓储的 `register/list/get/mark_deleted`，每个查询设置请求用户以执行 RLS。
- [ ] 运行迁移与仓储测试。

### Task 2: 受控发布与删除服务

**Files:** `src/qwenpaw/artifacts/service.py`, `src/qwenpaw/agents/tools/send_file.py`, `tests/unit/artifacts/test_service.py`.

- [ ] 写失败测试：仅当前用户私有运行空间的文件可发布；复制失败不登记；删除不接受跨用户或路径逃逸。
- [ ] 发布服务复制到 `artifacts/` 后计算摘要并登记；同名冲突用稳定唯一名称，源文件不删除。
- [ ] 删除服务按记录解析相对路径，物理删除成功后标记 `deleted`；重复删除幂等。
- [ ] 让 `send_file_to_user` 使用可信运行上下文调用发布服务；缺少可信用户上下文时保持原文件发送行为而不登记。
- [ ] 运行服务与工具回归。

### Task 3: API、文件页和隔离验证

**Files:** `src/qwenpaw/app/routers/artifacts.py`, `console/src/api/modules/artifacts.ts`, `console/src/features/files-workspace/ArtifactPanel.tsx`, 相关测试与验收报告。

- [ ] 写 API 失败测试：跨用户 ID 返回 404，已删除产物不可下载。
- [ ] 提供当前 Agent 的列表、下载和删除接口；所有接口从认证用户与 `X-Agent-Id` 解析范围。
- [ ] 文件页产物标签改用 `ArtifactPanel`，显示来源、会话、状态，提供删除和复制到个人资料库。
- [ ] 运行后端、前端类型检查、定向构建与双用户手工验收。
