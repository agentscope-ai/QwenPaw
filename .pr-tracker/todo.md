# Contribution Todo List

> 按优先级排序，标记预估工作量和成功概率
> 最后更新: 2026-07-28

## ✅ Completed (已提交 PR)

### [Issue #6374] token usage persistence does not retry after a transient write failure
- **PR**: [#6522](https://github.com/agentscope-ai/QwenPaw/pull/6522)
- **分支**: fix/issue-6374-token-usage-retry
- **状态**: ✅ PR 已提交，CI 通过 (Real behavior proof 因 integration 权限失败，非代码问题)
- **核心修复**: save_data_sync 返回 bool；_flush_once 仅在写入成功后清除 _dirty 标志

### [Issue #6355] Mission parser splits quoted --verify commands
- **PR**: [#6523](https://github.com/agentscope-ai/QwenPaw/pull/6523)
- **分支**: fix/issue-6355-mission-quoted-args
- **状态**: ✅ PR 已提交，CI 通过 (Real behavior proof 因 integration 权限失败，非代码问题)
- **核心修复**: 使用 shlex.split() 替代 str.split() 实现引用感知的参数解析

## 🔥 High Priority (高潜力) - 执行队列

### [Issue #6372] idle cleanup can remove a newly recreated queue state
- **预估工作量**: 3-5h
- **成功概率**: ⭐⭐⭐⭐
- **理由**:
  - 明确的并发 Bug，有详细的复现步骤
  - 涉及 `unified_queue_manager.py`，需要理解并发流程
  - 需要修复 `_run_consumer` 中 `pop` 的逻辑，确保只在 QueueState 匹配时才移除
  - 已有 PR #6373 做了类似的 fix，但此 issue 的场景不同
  - 属于 Channels 相关模块
- **相关文件**:
  - `src/qwenpaw/app/channels/unified_queue_manager.py`
  - `tests/unit/app/channels/test_unified_queue_manager.py`
- **状态**: 🔄 执行中 (PR #3)
- **筛选维度**: 可理解性✅ | 与专长匹配部分✅ | 工作量中等✅ | 社区反应一般(只有1条评论) | 无标签 | 无依赖✅ | 需要理解并发逻辑

### [Issue #6407] ReAct agent context gets corrupted by orphan tool_result messages
- **预估工作量**: 3-5h
- **成功概率**: ⭐⭐⭐⭐⭐
- **理由**:
  - 明确的 Bug：tool_result 消息与 role:assistant 混合，导致 API 400 错误
  - 已有 `_sanitize_tool_messages()` 工具函数，但可能在某些路径下未被调用
  - 需要在 ReAct Agent 的消息处理路径中添加防御性清理
  - 涉及 Agent 核心逻辑，对所有用户有益
  - Assignee 是 @yuanxs21 (项目核心开发者)
- **相关文件**:
  - `src/qwenpaw/agents/react_agent.py` (compress_context, _sanitize_loaded_context)
  - `src/qwenpaw/agents/utils/tool_message_utils.py` (_sanitize_tool_messages)
  - 需要添加测试
- **状态**: ⚪ 待开始 (PR #4)

### [Issue #6524] MCP server restart causes session termination without auto-reconnect
- **预估工作量**: 4-6h
- **成功概率**: ⭐⭐⭐⭐
- **理由**:
  - 明确的 Bug：MCP server 重启后客户端不会自动重连
  - 涉及 MCP 客户端连接管理
  - 需要添加重连机制
  - 与 MCP/Tool 相关，符合技术栈
  - Assignee 是 @leoliu0 (项目核心开发者)
- **相关文件**: 需要进一步分析 MCP 相关代码
- **状态**: ⚪ 待开始 (PR #5)

## 🔵 Medium Priority (中等潜力)

### [Issue #6454] 会话中鼠标选定任何内容建议都有个"复制"菜单项
- **预估工作量**: 4-8h
- **成功概率**: ⭐⭐⭐⭐
- **理由**:
  - 前端 enhancement，涉及 Console 前端代码
  - 需要了解 React/Next.js 前端结构
  - 与 Coding Mode / Web IDE 优先级 #2 相关
  - 需要在 chat 消息渲染中添加右键菜单
- **相关文件**:
  - `console/src/pages/Chat/index.tsx`
  - `console/src/pages/Chat/utils.ts`
- **状态**: ⚪ 待开始

### [Issue #6386] 重复调用工具
- **预估工作量**: 3-6h
- **成功概率**: ⭐⭐⭐
- **理由**:
  - Bug 描述不够详细，只有截图，没有代码层面的分析
  - 需要深入 ReAct Agent 逻辑排查
  - 可能涉及多文件和复杂流程
- **相关文件**: 需要进一步分析
- **状态**: ⚪ 待开始

## ❌ Rejected (排除项)

### [Issue #6506] Session-level approval_level not inherited by spawn_subagent
- **原因**: 已有对应 PR #6508 正在处理

### [Issue #6496] Legacy plugins silently disabled on QwenPaw 2.0+
- **原因**: 已有对应 PR #6497 正在处理

### [Issue #6474] view_video returns "Video loaded" but video DataBlock is silently dropped
- **原因**: 已有对应 PR #6495 正在处理

### [Issue #6470] MCP driver ignoring transport config
- **原因**: 已有对应 PR #6483 (test) 和其他相关改动

### [Issue #6520] agent.json systematic corruption: BOM, missing quotes, double-encoding
- **原因**: Issue 描述较复杂，可能涉及多层 JSON 处理逻辑，且刚提交还未有足够讨论

### [Issue #6408] 支持撤销/重新编辑上一轮对话
- **原因**: 较大的功能新增，涉及 history.db、scroll 策略、CLI 交互等多个模块，工作量大(预估 2-3 天)

### [Issue #6475] 希望可以添加 notice_after_complete 工具
- **原因**: Enhancement 需求，需要设计新工具接口和 Agent 行为变更，工作量大

### [Issue #6461] 希望能实现智能体完全隔离的功能
- **原因**: 涉及架构层面，已有多个 PR 在讨论隔离机制，此 issue 可能需要更多讨论
