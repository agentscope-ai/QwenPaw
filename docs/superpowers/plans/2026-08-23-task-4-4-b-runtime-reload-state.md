# Task 4.4-B Runtime Reload State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在运行配置已经持久化但 Agent 热重载失败时，向前端稳定暴露“已保存、待重载”，并允许用户重试。

**Architecture:** 保持运行配置响应体兼容；在 FastAPI `app.state` 保存当前进程内的 Agent 重载状态。运行配置保存后同步重载并更新状态，新增查询与重试端点，前端通过状态接口展示警告和重试动作。

**Tech Stack:** FastAPI、Pydantic、Python asyncio、React、TypeScript、Vitest、pytest。

## Global Constraints

- 不修改数据库结构，不搬移 `agent.json` 或 workspace Markdown。
- 不改变 Embedding 配置现有的测试应用与失败回滚语义。
- 不修改其他路由继续使用的通用后台重载行为。
- 不执行 Git commit、push、reset 或创建分支。
- 每个生产变更前必须先看到对应测试按预期失败。

---

### Task 1: 后端重载状态契约

**Files:**
- Modify: `src/qwenpaw/app/utils.py`
- Modify: `src/qwenpaw/app/routers/workspace.py`
- Test: `tests/unit/app/routers/test_workspace_router.py`

**Interfaces:**
- Produces: `reload_agent_and_track(request, agent_id) -> RunningConfigRuntimeStatus`
- Produces: `get_agent_reload_status(request, agent_id) -> RunningConfigRuntimeStatus`
- Produces: `GET /workspace/running-config/runtime-status`
- Produces: `POST /workspace/running-config/reload`

- [ ] 写失败测试：保存后重载异常时配置仍持久化且状态为 `pending_reload`。
- [ ] 运行单测，确认因缺少同步状态跟踪而失败。
- [ ] 写失败测试：重试成功后状态为 `applied`。
- [ ] 运行单测，确认因缺少重试端点而失败。
- [ ] 在 `app.state` 上实现最小二态状态表和同步重载函数。
- [ ] 将运行配置保存路径改为持久化后调用同步重载；保持响应体不变。
- [ ] 增加状态查询和重试端点。
- [ ] 运行 workspace 路由测试，确认全部通过。

### Task 2: 前端待重载提示与重试

**Files:**
- Modify: `console/src/api/modules/agent.ts`
- Modify: `console/src/api/modules/agent.test.ts`
- Modify: `console/src/pages/Agent/Config/useAgentConfig.tsx`
- Modify: `console/src/pages/Agent/Config/useAgentConfig.test.tsx`
- Modify: `console/src/locales/zh.json`
- Modify: `console/src/locales/en.json`

**Interfaces:**
- Consumes: `{ state: "applied" | "pending_reload" }`
- Produces: `getAgentRunningConfigRuntimeStatus()`
- Produces: `retryAgentRunningConfigReload()`
- Produces: Hook 返回 `runtimeState`、`retryReloading`、`handleRetryReload`

- [ ] 写失败 API 测试，要求查询和重试端点路径正确。
- [ ] 写失败 Hook 测试，要求保存已持久化但待重载时显示警告而非保存失败。
- [ ] 写失败 Hook 测试，要求重试成功后清除待重载状态。
- [ ] 运行前端定向测试并确认按预期失败。
- [ ] 实现 API 类型与方法。
- [ ] 实现页面加载、保存后状态刷新及手动重试。
- [ ] 增加中英文“已保存、待重载”和重试结果文案。
- [ ] 运行前端定向测试并确认全部通过。

### Task 3: 回归与可见验收

**Files:**
- Modify: `docs/project-audit/16-多用户架构分阶段实施计划.md`
- Create: `docs/project-audit/29-任务4.4-B热重载待处理状态验收报告.md`

- [ ] 运行后端 workspace 路由、配置修订集成测试。
- [ ] 运行前端配置页面测试、TypeScript 检查和生产构建。
- [ ] 在 `18089` 验收实例验证正常保存状态。
- [ ] 通过受控测试故障验证“已保存、待重载”和重试成功，不修改真实业务配置。
- [ ] 归档测试证据并停止在用户确认点。
