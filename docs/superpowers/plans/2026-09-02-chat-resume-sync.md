# Chat Resume Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 避免空闲聊天在浏览器恢复焦点时被无条件重建，同时保留后台消息同步。

**Architecture:** 将刷新条件提取为纯函数，由 Chat 页面恢复同步逻辑调用。浏览器事件只负责触发同步，是否重建由前后端状态差异决定。

**Tech Stack:** React 18、TypeScript、Vitest、Vite

## Global Constraints

- 不改变现有路由、会话 API 和数据库结构。
- 普通空闲会话恢复焦点不得重建聊天组件。
- 后端新增消息或后台任务刚结束时仍需同步。
- 不执行 Git 提交。

---

### Task 1: 恢复同步判定

**Files:**
- Create: `console/src/pages/Chat/chatResumeSync.ts`
- Create: `console/src/pages/Chat/chatResumeSync.test.ts`
- Modify: `console/src/pages/Chat/index.tsx`

**Interfaces:**
- Produces: `shouldRefreshChatAfterResume(input): boolean`
- Consumes: 后端状态、前后端消息数量和前端运行状态。

- [x] 写入四类状态的失败测试。
- [x] 运行测试并确认旧代码缺少判定函数而失败。
- [x] 实现最小纯函数并接入 `syncCurrentChatAfterResume`。
- [x] 运行单元测试确认通过。
- [x] 执行聊天页相关测试、TypeScript 编译和生产构建。
- [x] 使用真实浏览器验证恢复焦点不再闪动。
