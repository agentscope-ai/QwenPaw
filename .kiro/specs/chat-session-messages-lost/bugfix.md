# Bugfix 需求文档

## 简介

Web聊天界面中，当用户在LLM正在处理请求（特别是工具调用期间）时切换到其他页面（如MCP、模型配置等），再返回聊天页面后，之前正在进行的聊天消息丢失，且刷新页面也无法恢复。

根本原因分析：`SessionApi.updateSession` 方法在第一行执行了 `session.messages = []`，强制清空了传入会话对象的消息数组。当UI组件在流式响应期间调用 `updateSession` 保存会话状态时，消息被清空并覆盖到 `sessionList` 中。同时，由于流式响应被中断（用户离开页面），后端可能也未完整保存该轮对话的消息，导致消息永久丢失。

## Bug 分析

### 当前行为（缺陷）

1.1 WHEN 用户在LLM正在进行工具调用/流式响应时切换到其他页面再返回 THEN 系统显示的聊天消息不完整，正在进行的对话轮次的消息丢失

1.2 WHEN `updateSession` 被调用时 THEN 系统强制将 `session.messages` 设为空数组 `[]`，导致内存中 `sessionList` 对应会话的消息被清空

1.3 WHEN 用户在消息丢失后刷新页面 THEN 系统无法恢复丢失的消息，因为后端在流式响应中断时也未完整保存该轮对话

### 期望行为（正确）

2.1 WHEN 用户在LLM正在进行工具调用/流式响应时切换到其他页面再返回 THEN 系统 SHALL 显示切换前已接收到的所有聊天消息，包括部分完成的响应

2.2 WHEN `updateSession` 被调用时 THEN 系统 SHALL 不清空已有的消息数据，仅更新会话的元数据（如名称、ID映射等）

2.3 WHEN 用户返回聊天页面时 THEN 系统 SHALL 从后端重新获取该会话的完整聊天历史，确保显示所有已持久化的消息

### 不变行为（回归预防）

3.1 WHEN 用户在非流式响应期间正常切换会话 THEN 系统 SHALL CONTINUE TO 正确加载目标会话的聊天历史

3.2 WHEN 用户创建新会话并发送第一条消息 THEN 系统 SHALL CONTINUE TO 正确解析临时时间戳ID到后端真实UUID

3.3 WHEN 用户删除会话 THEN 系统 SHALL CONTINUE TO 正确从列表中移除会话并清理URL

3.4 WHEN 多个并发的 `getSessionList` 或 `getSession` 请求发生时 THEN 系统 SHALL CONTINUE TO 正确去重请求，保留 `realId` 映射关系

3.5 WHEN `updateSession` 被调用更新会话元数据时 THEN 系统 SHALL CONTINUE TO 正确触发 `realId` 解析流程（对于本地时间戳ID的会话）
