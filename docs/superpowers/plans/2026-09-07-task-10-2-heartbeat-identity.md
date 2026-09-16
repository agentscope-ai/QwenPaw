# Heartbeat 安全主体和目标 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Heartbeat 使用配置中可信保存的授权用户与 `agent_automation` 主体运行，并将 `main`、`last`、`inbox` 全部限制在该用户范围内。

**Architecture:** Agent 配置保存 Heartbeat 授权用户和按用户区分的最近投递目标。`app/crons/heartbeat.py` 负责把配置事实解析成不可变运行身份，定时调度与立即运行复用该入口；执行前同时复核用户状态与 Agent 访问权。

**Tech Stack:** Python 3.11、Pydantic、FastAPI、SQLAlchemy async、APScheduler、pytest/pytest-asyncio、React/Vitest（仅回归）

## Global Constraints

- 不新增数据库表或迁移。
- 多用户模式不读取旧的 Agent 级单值 `last_dispatch` 作为投递目标。
- 单用户兼容模式保留现有行为。
- 客户端不能指定 `authorized_by_user_id`。
- 不重做 Heartbeat 页面，不扩展 Task 10.3 的收件箱和审批范围。
- 不执行 Git 提交或分支操作。

---

### Task 1: 配置中的可信授权用户与分用户最近目标

**Files:**
- Modify: `src/qwenpaw/config/config.py:598-616,2023-2028`
- Modify: `src/qwenpaw/config/utils.py:743-777`
- Test: `tests/unit/config/test_heartbeat_identity_config.py`

**Interfaces:**
- Produces: `HeartbeatConfig.authorized_by_user_id: UUID | None`
- Produces: `AgentConfig.last_dispatch_by_user: dict[str, LastDispatchConfig]`
- Produces: `update_last_dispatch(..., platform_user_id: str | None = None)`
- Produces: `get_last_dispatch_for_user(*, agent_id: str, platform_user_id: str) -> LastDispatchConfig | None`

- [x] **Step 1: 写入失败测试**

覆盖 UUID 字段 JSON 往返、按用户保存两个不同 `last_dispatch`、读取时不串用户，以及旧单值字段只作为单用户兼容数据保留。

- [x] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/unit/config/test_heartbeat_identity_config.py -q`

Expected: FAIL，原因是字段和按用户 API 尚不存在。

- [x] **Step 3: 实现最小配置模型**

在 `HeartbeatConfig` 添加别名为 `authorizedByUserId` 的可空 UUID；在 Agent 配置添加 `last_dispatch_by_user`。扩展 `update_last_dispatch`，只有收到可信平台用户 ID 时才写入用户映射，同时保留现有单值写入供兼容模式使用。新增严格按键读取函数，不做跨用户回退。

- [x] **Step 4: 运行配置测试**

Run: `python -m pytest tests/unit/config/test_heartbeat_identity_config.py tests/unit/config/test_running_config_validation.py -q`

Expected: PASS。

### Task 2: Heartbeat 运行身份与目标解析

**Files:**
- Modify: `src/qwenpaw/app/crons/heartbeat.py:187-409`
- Modify: `src/qwenpaw/access/agent_repository.py:379-399`
- Test: `tests/isolation/test_heartbeat_identity.py`

**Interfaces:**
- Produces: `HeartbeatIdentityError(code: str)`
- Produces: `HeartbeatRunIdentity(authorized_user_id, session_id, request_context)`
- Produces: `resolve_heartbeat_identity(agent_id: str | None) -> HeartbeatRunIdentity`
- Consumes: `PostgresUserRepository.get_user(UUID)`、`PostgresAgentRepository.get_accessible(...)`
- Consumes: `get_last_dispatch_for_user(...)`

- [x] **Step 1: 写入失败的身份隔离测试**

覆盖缺少授权、用户禁用、Agent 权限撤销、`agent_automation` 上下文、专用会话 ID、A/B 两用户最近目标互不覆盖、`last` 无目标不回退和 `inbox` recipient 归属。

- [x] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/isolation/test_heartbeat_identity.py -q`

Expected: FAIL，现有请求仍使用 `user_id=main`、`session_id=main`。

- [x] **Step 3: 实现不可变身份解析**

在多用户模式读取 `authorized_by_user_id`，验证用户为 active 且仍能访问 active Agent。构造：

```python
request_context = {
    "source": "heartbeat",
    "actor_type": "agent_automation",
    "authorized_by_user_id": str(user_id),
    "agent_id": agent_id,
}
session_id = f"heartbeat:{agent_id}:{user_id}:main"
```

单用户模式继续使用原 `main` 身份。

- [x] **Step 4: 收口目标与通知**

`last` 在多用户模式只读取授权用户映射并校验字段；无目标时写入该用户的 `heartbeat_last_target_unavailable` 事件后返回。`inbox`、超时和错误全部使用解析出的授权用户。Trace 与 session delta 使用专用会话。

- [x] **Step 5: 运行身份隔离测试**

Run: `python -m pytest tests/isolation/test_heartbeat_identity.py tests/unit/app/routers/test_config_router.py -q`

Expected: PASS。

### Task 3: 路由可信写入与统一立即运行

**Files:**
- Modify: `src/qwenpaw/app/routers/config.py:670-758`
- Modify: `src/qwenpaw/app/workspace/service_factories.py:271-277`
- Test: `tests/unit/app/routers/test_heartbeat_authorization.py`

**Interfaces:**
- Consumes: `get_actor(request) -> ActorContext`
- Consumes: `run_heartbeat_once(...)`
- Produces: PUT `/api/config/heartbeat` 始终以可信 ActorContext 覆盖授权用户

- [x] **Step 1: 写入失败的路由测试**

验证多用户 PUT 保存当前 Actor 用户、请求体不能伪造授权用户、缺少可信用户时拒绝启用，以及立即运行复用已保存授权。

- [x] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/unit/app/routers/test_heartbeat_authorization.py -q`

Expected: FAIL，当前路由没有写入授权用户。

- [x] **Step 3: 实现可信写入**

PUT 路由通过 `Depends(get_actor)` 获取 ActorContext；多用户模式要求 `actor.user_id`，并在构造 HeartbeatConfig 时服务端写入。个人频道回调将平台用户 ID 传给 `update_last_dispatch`，Agent 共享 ChannelManager 仅在已有可信平台用户上下文时写入映射。

- [x] **Step 4: 统一立即运行错误语义**

立即运行仍异步返回 `{started: true}`；后台入口使用配置中的授权用户。缺少授权时记录明确错误，不捕获当前请求用户作为另一个运行身份。

- [x] **Step 5: 运行路由与频道回归**

Run: `python -m pytest tests/unit/app/routers/test_heartbeat_authorization.py tests/unit/app/routers/test_config_router.py tests/unit/app/channels/test_user_binding_runtime.py -q`

Expected: PASS。

### Task 4: 全量相关回归与台账

**Files:**
- Modify: `docs/project-audit/16-多用户架构分阶段实施计划.md:942-953`
- Modify: `.superpowers/sdd/2026-09-07-task-10-2-heartbeat-identity/progress.md`
- Create: `docs/superpowers/plans/2026-09-07-task-10-2-acceptance.md`

**Interfaces:**
- Consumes: Tasks 1-3 的最终行为与测试证据。

- [x] **Step 1: 运行后端相关测试**

Run: `python -m pytest tests/isolation/test_heartbeat_identity.py tests/unit/app/routers/test_heartbeat_authorization.py tests/unit/app/routers/test_config_router.py tests/unit/app/crons tests/unit/config/test_heartbeat_identity_config.py -q`

Expected: PASS。

- [x] **Step 2: 运行静态检查**

Run: `python -m ruff check src/qwenpaw/app/crons/heartbeat.py src/qwenpaw/app/routers/config.py src/qwenpaw/config/config.py src/qwenpaw/config/utils.py tests/isolation/test_heartbeat_identity.py tests/unit/app/routers/test_heartbeat_authorization.py tests/unit/config/test_heartbeat_identity_config.py`

Expected: PASS。

- [x] **Step 3: 前端回归**

Run: `pnpm --dir console exec vitest run src/api/modules/heartbeat.test.ts src/pages/Control/Heartbeat`

Run: `pnpm --dir console exec tsc --noEmit`

Expected: PASS。

- [x] **Step 4: 单浏览器双用户验收**

启动隔离测试服务和一个 headless Chromium，用两个 context 验证 A 授权后 B 使用同一 Agent 不改变 A 的 `last`，A 的 inbox 事件对 B 不可见，撤销 A 权限后不向 B 投递。保存 JSON 结果和关键截图到 `tmp/task102-browser-<timestamp>/`。

- [x] **Step 5: 更新验收记录**

记录自动化测试、单浏览器证据、原环境是否需要重启，以及剩余任务数量。若没有数据库迁移，不触发数据库危险操作确认。
