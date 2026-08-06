# AG-UI 协议支持设计文档

**日期：** 2026-07-22
**状态：** 设计阶段
**作者：** Claude
**类型：** 功能设计

---

## 概述

为 QwenPaw 添加 AG-UI 协议支持，通过独立的 `/protocol/agui/chat` 端点提供符合 AG-UI 协议规范的流式响应。该端点完全独立于现有的 `/console/chat` 等端点，不影响现有服务。

---

## 背景

- **AgentScope 2.0** 已包含 `AGUIProtocolMiddleware` 实现（位于 `agentscope/app/middleware/_protocol/_agui.py`）
- **QwenPaw** 基于 AgentScope 2.0 构建，但尚未暴露 AG-UI 协议
- **AG-UI 协议** 定义了标准化的事件格式，用于表示 AI Agent 运行时的各种状态

---

## 设计目标

1. **隔离性：** 不影响现有的 `/console/chat` 和其他端点
2. **一致性：** 与 AgentScope 2.0 的目录结构保持一致
3. **完整性：** 支持完整的 AG-UI 协议事件转换
4. **可用性：** 始终启用，无需配置开关

---

## 架构设计

### 目录结构

```
src/qwenpaw/app/
├── protocol/
│   ├── __init__.py
│   ├── agui/
│   │   ├── __init__.py
│   │   ├── router.py          # AG-UI 路由器
│   │   └── converter.py       # 事件转换器
│   └── _base.py               # 协议基础类（可选）
└── routers/
    └── ... (现有路由)
```

### 核心组件

#### 1. `protocol/agui/router.py`

定义 `/protocol/agui/chat` POST 端点：

```python
@router.post(
    "/protocol/agui/chat",
    summary="Chat with AG-UI protocol (streaming)",
    description="Stream agent response in AG-UI protocol format",
)
async def post_agui_chat(
    request_data: Union[AgentRequest, dict],
    request: Request,
) -> StreamingResponse:
    """Stream agent response in AG-UI protocol format."""
```

#### 2. `protocol/agui/converter.py`

封装事件转换逻辑，复用 AgentScope 的 `_to_agui_event` 方法：

```python
def convert_agent_event_to_agui(event: AgentEvent) -> dict:
    """Convert AgentScope event to AG-UI protocol format."""
```

#### 3. 主应用注册

在 `_app.py` 中注册 protocol 路由：

```python
from .protocol.agui import router as agui_router

app.include_router(agui_router)
```

---

## 技术实现

### 请求处理流程

1. **接收请求：** 接收 `AgentRequest` 格式的请求（与 `/console/chat` 相同）
2. **获取 Agent：** 使用 `get_agent_for_request` 获取 agent 实例
3. **流式调用：** 调用 agent 的流式响应方法
4. **事件转换：** 将 AgentScope 事件转换为 AG-UI 协议格式
5. **流式输出：** 通过 `StreamingResponse` 返回，每行一个 JSON 事件

### 事件转换映射

| AgentScope 事件 | AG-UI 事件 |
|----------------|------------|
| `ReplyStartEvent` | `RunStartedEvent` |
| `ReplyEndEvent` | `RunFinishedEvent` |
| `ModelCallStartEvent` | `StepStartedEvent` |
| `ModelCallEndEvent` | `StepFinishedEvent` |
| `TextBlockStartEvent` | `TextMessageStartEvent` |
| `TextBlockDeltaEvent` | `TextMessageContentEvent` |
| `TextBlockEndEvent` | `TextMessageEndEvent` |
| `ThinkingBlockStartEvent` | `ReasoningMessageStartEvent` |
| `ThinkingBlockDeltaEvent` | `ReasoningMessageContentEvent` |
| `ThinkingBlockEndEvent` | `ReasoningMessageEndEvent` |
| `ToolCallStartEvent` | `ToolCallStartEvent` |
| `ToolCallDeltaEvent` | `ToolCallArgsEvent` |
| `ToolCallEndEvent` | `ToolCallEndEvent` |
| `ToolResultEndEvent` | `ToolCallResultEvent` |
| `ExceedMaxItersEvent` | `RunErrorEvent` |
| 其他事件 | `CustomEvent` |

### 错误处理

当 `ag_ui` 包未安装时：

```python
try:
    from ag_ui.core.events import BaseEvent
except ImportError:
    raise HTTPException(
        status_code=500,
        detail="AG-UI protocol requires 'ag-ui-protocol' package. Please install it: pip install ag-ui-protocol"
    )
```

---

## 依赖管理

### pyproject.toml 更新

从 AgentScope 2.0 的依赖推断 `ag_ui` 版本约束：

```toml
dependencies = [
    # ... 现有依赖
    "ag-ui-protocol>=0.1.10,<0.2.0",  # 与 AgentScope 2.0 保持一致
]
```

---

## 配置选项

**始终启用：** AG-UI 端点始终可用，无需配置开关。

**理由：** 作为标准协议端点，应该始终可访问，由使用者决定是否使用。

---

## API 规范

### 端点

```
POST /protocol/agui/chat
```

### 请求格式

与 `/console/chat` 相同，使用 `AgentRequest` 格式：

```json
{
  "agent_id": "default",
  "user_id": "user123",
  "session_id": "session456",
  "input": [
    {
      "content": [
        {"type": "text", "text": "Hello, how are you?"}
      ]
    }
  ]
}
```

### 响应格式

StreamingResponse，每行一个 JSON 对象（AG-UI 协议事件）：

```json
{"type": "run_started", "thread_id": "session456", "run_id": "reply123"}
{"type": "step_started", "step_name": "qwen-plus"}
{"type": "text_message_start", "message_id": "msg456"}
{"type": "text_message_content", "message_id": "msg456", "delta": "Hello"}
{"type": "text_message_content", "message_id": "msg456", "delta": "! I'm"}
{"type": "text_message_content", "message_id": "msg456", "delta": " fine."}
{"type": "text_message_end", "message_id": "msg456"}
{"type": "step_finished", "step_name": "qwen-plus"}
{"type": "run_finished", "thread_id": "session456", "run_id": "reply123"}
```

---

## 与现有服务的关系

### 隔离性保证

1. **独立路由：** `/protocol/agui/chat` 与 `/console/chat` 完全独立
2. **独立实现：** 不修改现有的聊天逻辑
3. **独立测试：** 不影响现有端点的测试覆盖

### 复用现有组件

1. **Agent 获取：** 复用 `get_agent_for_request`
2. **请求解析：** 复用 `AgentRequest` 模型
3. **Agent 调用：** 复用现有的 agent 流式调用逻辑

---

## 后续扩展考虑

### 协议扩展

目前仅实现 AG-UI 协议，未来可扩展：

- **A2A 协议：** 创建 `/protocol/a2a/chat` 端点
- **协议协商：** 添加 `Accept: application/vnd.agui+json` 头支持
- **协议发现：** 添加 `/protocol/` 端点列出支持的协议

### 版本管理

- 支持 AG-UI 协议版本协商
- 向后兼容性保证

**当前阶段：** 仅实现 AG-UI v1.0，不考虑扩展。

---

## 实现清单

- [ ] 创建 `src/qwenpaw/app/protocol/` 目录结构
- [ ] 实现 `protocol/agui/converter.py`（事件转换器）
- [ ] 实现 `protocol/agui/router.py`（路由器）
- [ ] 在 `_app.py` 中注册 AG-UI 路由
- [ ] 在 `pyproject.toml` 中添加 `ag_ui` 依赖
- [ ] 添加错误处理（ag_ui 包未安装时）
- [ ] 验证端点功能（手动测试）

---

## 验证方法

### 功能验证

1. **启动 QwenPaw 服务**
2. **发送请求到 `/protocol/agui/chat`**
3. **验证响应格式符合 AG-UI 协议**
4. **验证不影响 `/console/chat` 等现有端点**

### 错误场景验证

1. **ag_ui 包未安装：** 验证返回明确错误提示
2. **无效请求：** 验证返回 400 错误
3. **Agent 不存在：** 验证返回 404 错误

---

## 风险与限制

### 风险

1. **依赖冲突：** `ag_ui` 包可能与现有依赖冲突
2. **性能影响：** 事件转换可能增加延迟
3. **协议变更：** AgentScope 升级可能导致 AG-UI 协议变更

### 限制

1. **文档缺失：** 本任务不包含 API 文档编写
2. **测试缺失：** 本任务不包含自动化测试
3. **协议版本：** 仅支持 AG-UI v1.0

---

## 参考资料

- AgentScope 2.0 AG-UI 中间件：`agentscope/app/middleware/_protocol/_agui.py`
- AgentScope 协议中间件基类：`agentscope/app/middleware/_protocol/_base.py`
- ag-ui-protocol 包文档：https://github.com/modelscope/ag-ui-protocol
- AgentScope 依赖规范：`ag-ui-protocol>=0.1.10; extra == "service"`

---

**设计版本：** 1.0
**最后更新：** 2026-07-22
