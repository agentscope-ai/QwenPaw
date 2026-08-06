# AG-UI 协议支持实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 为 QwenPaw 添加 AG-UI 协议支持，通过独立的 `/protocol/agui/chat` 端点提供符合 AG-UI 协议规范的流式响应

**架构：** 创建独立的 `protocol/agui` 模块，实现事件转换器和路由器，在主应用中注册，完全隔离现有服务

**技术栈：** FastAPI, AgentScope 2.0, ag-ui-protocol, StreamingResponse

## 全局约束

- **包依赖：** `ag-ui-protocol>=0.1.10,<0.2.0`（与 AgentScope 2.0 保持一致）
- **端点路径：** `/protocol/agui/chat`
- **目录结构：** `src/qwenpaw/app/protocol/agui/`
- **配置：** 始终启用，无需开关
- **错误处理：** ag-ui-protocol 包未安装时返回明确错误提示
- **隔离性：** 不影响现有的 `/console/chat` 等端点
- **请求格式：** 复用 `AgentRequest` 格式（与 `/console/chat` 相同）
- **响应格式：** StreamingResponse，每行一个 JSON 对象（AG-UI 事件）

---

## 文件结构

**新建文件：**
- `src/qwenpaw/app/protocol/__init__.py` - 协议模块初始化
- `src/qwenpaw/app/protocol/agui/__init__.py` - AG-UI 模块初始化
- `src/qwenpaw/app/protocol/agui/converter.py` - AgentScope 到 AG-UI 事件转换器
- `src/qwenpaw/app/protocol/agui/router.py` - AG-UI 路由器

**修改文件：**
- `src/qwenpaw/app/_app.py` - 注册 AG-UI 路由
- `pyproject.toml` - 添加 ag-ui-protocol 依赖

---

## 任务 1：添加依赖到 pyproject.toml

**文件：**
- 修改：`pyproject.toml`

**接口：**
- 无依赖
- 产出：添加 `ag-ui-protocol` 依赖到 dependencies 列表

- [ ] **步骤 1：定位依赖列表**

在 `pyproject.toml` 中找到 `[project.dependencies]` 部分，当前约在第 8 行开始。

- [ ] **步骤 2：添加 ag-ui-protocol 依赖**

在依赖列表中添加（建议在第 48 行 `"agent-client-protocol"` 之后）：

```toml
"ag-ui-protocol>=0.1.10,<0.2.0",
```

添加后应类似于：

```toml
dependencies = [
    "agentscope==2.0.4.post1",
    # ... 其他依赖
    "agent-client-protocol>=0.9.0,<0.11.0",
    "ag-ui-protocol>=0.1.10,<0.2.0",  # <-- 新增
    # ... 其他依赖
]
```

- [ ] **步骤 3：验证语法正确性**

运行：`python3 -c "import tomllib; tomllib.load(open('pyproject.toml', 'rb'))"`
预期：无输出（语法正确）

- [ ] **步骤 4：提交**

```bash
git add pyproject.toml
git commit -m "feat(agui): add ag-ui-protocol dependency"
```

---

## 任务 2：创建协议目录结构和初始化文件

**文件：**
- 创建：`src/qwenpaw/app/protocol/__init__.py`
- 创建：`src/qwenpaw/app/protocol/agui/__init__.py`

**接口：**
- 消费：无
- 产出：protocol 和 agui 模块的命名空间

- [ ] **步骤 1：创建 protocol 目录**

```bash
mkdir -p /Users/zhangsan/github/QwenPaw/src/qwenpaw/app/protocol/agui
```

- [ ] **步骤 2：创建 protocol/__init__.py**

文件内容：

```python
# -*- coding: utf-8 -*-
"""Protocol adapters for QwenPaw.

This package contains protocol-specific endpoints that convert AgentScope
events to standardized protocol formats (e.g., AG-UI).
"""
```

- [ ] **步骤 3：创建 protocol/agui/__init__.py**

文件内容：

```python
# -*- coding: utf-8 -*-
"""AG-UI protocol adapter for QwenPaw.

This module implements the AG-UI protocol endpoint at /protocol/agui/chat,
which converts AgentScope events to AG-UI protocol format.
"""
```

- [ ] **步骤 4：验证模块可导入**

运行：`python3 -c "from qwenpaw.app import protocol; from qwenpaw.app.protocol import agui; print('Import successful')"`
预期：输出 "Import successful"

- [ ] **步骤 5：提交**

```bash
git add src/qwenpaw/app/protocol/
git commit -m "feat(agui): create protocol directory structure"
```

---

## 任务 3：实现事件转换器（converter.py）

**文件：**
- 创建：`src/qwenpaw/app/protocol/agui/converter.py`

**接口：**
- 消费：`agentscope.event.AgentEvent`, `ag_ui.core.events`
- 产出：`convert_agent_event_to_agui(event: AgentEvent) -> dict`

**依赖检查：**
- 需要先安装依赖：`pip install ag-ui-protocol>=0.1.10,<0.2.0`

- [ ] **步骤 1：验证 ag-ui-protocol 可用**

运行：`python3 -c "from ag_ui.core.events import BaseEvent; print('ag-ui-protocol available')"`
预期：输出 "ag-ui-protocol available"
如果失败：运行 `pip install 'ag-ui-protocol>=0.1.10,<0.2.0'`

- [ ] **步骤 2：创建 converter.py 文件骨架**

```python
# -*- coding: utf-8 -*-
"""Convert AgentScope events to AG-UI protocol format.

This module provides event conversion logic, adapting AgentScope's
AgentEvent objects to AG-UI protocol event format.
"""
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ag_ui.core.events import BaseEvent as AGUIBaseEvent
else:
    AGUIBaseEvent = Any

try:
    from ag_ui.core.events import (
        CustomEvent as AGUICustomEvent,
        ReasoningMessageContentEvent as AGUIReasoningMessageContentEvent,
        ReasoningMessageEndEvent as AGUIReasoningMessageEndEvent,
        ReasoningMessageStartEvent as AGUIReasoningMessageStartEvent,
        RunErrorEvent as AGUIRunErrorEvent,
        RunFinishedEvent as AGUIRunFinishedEvent,
        RunStartedEvent as AGUIRunStartedEvent,
        StepFinishedEvent as AGUIStepFinishedEvent,
        StepStartedEvent as AGUIStepStartedEvent,
        TextMessageContentEvent as AGUITextMessageContentEvent,
        TextMessageEndEvent as AGUITextMessageEndEvent,
        TextMessageStartEvent as AGUITextMessageStartEvent,
        ToolCallArgsEvent as AGUIToolCallArgsEvent,
        ToolCallEndEvent as AGUIToolCallEndEvent,
        ToolCallResultEvent as AGUIToolCallResultEvent,
        ToolCallStartEvent as AGUIToolCallStartEvent,
    )
    AG_UI_AVAILABLE = True
except ImportError:
    AG_UI_AVAILABLE = False

from agentscope.event import (
    AgentEvent,
    DataBlockDeltaEvent,
    DataBlockEndEvent,
    DataBlockStartEvent,
    ExceedMaxItersEvent,
    ExternalExecutionResultEvent,
    ModelCallEndEvent,
    ModelCallStartEvent,
    ReplyEndEvent,
    ReplyStartEvent,
    RequireExternalExecutionEvent,
    RequireUserConfirmEvent,
    TextBlockDeltaEvent,
    TextBlockEndEvent,
    TextBlockStartEvent,
    ThinkingBlockDeltaEvent,
    ThinkingBlockEndEvent,
    ThinkingBlockStartEvent,
    ToolCallDeltaEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
    ToolResultDataDeltaEvent,
    ToolResultEndEvent,
    ToolResultTextDeltaEvent,
    UserConfirmResultEvent,
)


class AgentScopeToAGUIConverter:
    """Convert AgentScope events to AG-UI protocol format."""

    def __init__(self) -> None:
        """Initialize the converter."""
        if not AG_UI_AVAILABLE:
            raise ImportError(
                "ag-ui-protocol is required for AG-UI support. "
                "Install it: pip install 'ag-ui-protocol>=0.1.10,<0.2.0'"
            )
        # Per-instance state for tracking message context
        self._last_model_name: str = "model_call"
        self._tool_result_buffers: dict[str, list[str]] = {}

    def convert(self, event: AgentEvent) -> dict:
        """Convert an AgentScope event to AG-UI protocol dict.

        Args:
            event: The AgentScope event to convert.

        Returns:
            Dictionary in AG-UI protocol format.
        """
        agui_event = self._to_agui_event(event)
        return agui_event.model_dump(
            mode="json",
            exclude_none=True,
            by_alias=True,
        )

    def _to_agui_event(self, event: AgentEvent) -> "AGUIBaseEvent":
        """Convert an AgentScope event to an AG-UI event object.

        This method implements the event mapping from AgentScope to AG-UI.
        """
        # TODO: 在任务 4 中实现完整的事件转换逻辑
        pass
```

- [ ] **步骤 3：实现完整的事件转换逻辑**

将 `_to_agui_event` 方法替换为：

```python
    def _to_agui_event(self, event: AgentEvent) -> "AGUIBaseEvent":
        """Convert an AgentScope event to an AG-UI event object.

        This method implements the event mapping from AgentScope to AG-UI.
        """
        if isinstance(event, ReplyStartEvent):
            return AGUIRunStartedEvent(
                thread_id=event.session_id,
                run_id=event.reply_id,
            )

        if isinstance(event, ReplyEndEvent):
            return AGUIRunFinishedEvent(
                thread_id=event.session_id,
                run_id=event.reply_id,
            )

        if isinstance(event, ExceedMaxItersEvent):
            return AGUIRunErrorEvent(
                message=(f"Agent '{event.name}' exceeded max iterations"),
                code="exceed_max_iters",
            )

        if isinstance(event, ModelCallStartEvent):
            self._last_model_name = event.model_name
            return AGUIStepStartedEvent(
                step_name=event.model_name,
            )

        if isinstance(event, ModelCallEndEvent):
            return AGUIStepFinishedEvent(
                step_name=self._last_model_name,
            )

        if isinstance(event, TextBlockStartEvent):
            return AGUITextMessageStartEvent(
                message_id=event.block_id,
            )

        if isinstance(event, TextBlockDeltaEvent):
            return AGUITextMessageContentEvent(
                message_id=event.block_id,
                delta=event.delta,
            )

        if isinstance(event, TextBlockEndEvent):
            return AGUITextMessageEndEvent(
                message_id=event.block_id,
            )

        if isinstance(event, ThinkingBlockStartEvent):
            return AGUIReasoningMessageStartEvent(
                message_id=event.block_id,
                role="reasoning",
            )

        if isinstance(event, ThinkingBlockDeltaEvent):
            return AGUIReasoningMessageContentEvent(
                message_id=event.block_id,
                delta=event.delta,
            )

        if isinstance(event, ThinkingBlockEndEvent):
            return AGUIReasoningMessageEndEvent(
                message_id=event.block_id,
            )

        if isinstance(event, ToolCallStartEvent):
            return AGUIToolCallStartEvent(
                tool_call_id=event.tool_call_id,
                tool_call_name=event.tool_call_name,
                parent_message_id=event.reply_id,
            )

        if isinstance(event, ToolCallDeltaEvent):
            return AGUIToolCallArgsEvent(
                tool_call_id=event.tool_call_id,
                delta=event.delta,
            )

        if isinstance(event, ToolCallEndEvent):
            return AGUIToolCallEndEvent(
                tool_call_id=event.tool_call_id,
            )

        if isinstance(event, ToolResultStartEvent):
            return AGUICustomEvent(
                name="tool_result_start",
                value=event.model_dump(exclude_none=True),
            )

        if isinstance(event, ToolResultTextDeltaEvent):
            self._tool_result_buffers.setdefault(
                event.tool_call_id,
                [],
            ).append(event.delta)
            return AGUICustomEvent(
                name="tool_result_text_delta",
                value=event.model_dump(exclude_none=True),
            )

        if isinstance(event, ToolResultDataDeltaEvent):
            return AGUICustomEvent(
                name="tool_result_data_delta",
                value=event.model_dump(exclude_none=True),
            )

        if isinstance(event, ToolResultEndEvent):
            content = "".join(
                self._tool_result_buffers.pop(event.tool_call_id, []),
            )
            return AGUIToolCallResultEvent(
                tool_call_id=event.tool_call_id,
                message_id=event.reply_id,
                content=content or str(event.state),
            )

        if isinstance(event, DataBlockStartEvent):
            return AGUICustomEvent(
                name="data_block_start",
                value=event.model_dump(exclude_none=True),
            )

        if isinstance(event, DataBlockDeltaEvent):
            return AGUICustomEvent(
                name="data_block_delta",
                value=event.model_dump(exclude_none=True),
            )

        if isinstance(event, DataBlockEndEvent):
            return AGUICustomEvent(
                name="data_block_end",
                value=event.model_dump(exclude_none=True),
            )

        if isinstance(event, RequireUserConfirmEvent):
            return AGUICustomEvent(
                name="require_user_confirm",
                value=event.model_dump(exclude_none=True),
            )

        if isinstance(event, RequireExternalExecutionEvent):
            return AGUICustomEvent(
                name="require_external_execution",
                value=event.model_dump(exclude_none=True),
            )

        if isinstance(event, UserConfirmResultEvent):
            return AGUICustomEvent(
                name="user_confirm_result",
                value=event.model_dump(exclude_none=True),
            )

        if isinstance(event, ExternalExecutionResultEvent):
            return AGUICustomEvent(
                name="external_execution_result",
                value=event.model_dump(exclude_none=True),
            )

        return AGUICustomEvent(
            name="unknown",
            value=event.model_dump(exclude_none=True),
        )
```

- [ ] **步骤 4：创建便捷函数**

在文件末尾添加：

```python
# 创建全局转换器实例
_converter_instance: AgentScopeToAGUIConverter | None = None


def get_converter() -> AgentScopeToAGUIConverter:
    """获取或创建全局转换器实例.

    Returns:
        全局转换器实例

    Raises:
        ImportError: 如果 ag-ui-protocol 未安装
    """
    global _converter_instance
    if _converter_instance is None:
        _converter_instance = AgentScopeToAGUIConverter()
    return _converter_instance


def convert_agent_event_to_agui(event: AgentEvent) -> dict:
    """将 AgentScope 事件转换为 AG-UI 协议格式.

    Args:
        event: 要转换的 AgentScope 事件

    Returns:
        AG-UI 协议格式的字典

    Raises:
        ImportError: 如果 ag-ui-protocol 未安装
    """
    converter = get_converter()
    return converter.convert(event)
```

- [ ] **步骤 5：验证导入**

运行：`python3 -c "from qwenpaw.app.protocol.agui.converter import convert_agent_event_to_agui; print('Converter import successful')"`
预期：输出 "Converter import successful"

- [ ] **步骤 6：提交**

```bash
git add src/qwenpaw/app/protocol/agui/converter.py
git commit -m "feat(agui): implement AgentScope to AG-UI event converter"
```

---

## 任务 4：实现 AG-UI 路由器（router.py）

**文件：**
- 创建：`src/qwenpaw/app/protocol/agui/router.py`

**接口：**
- 消费：`convert_agent_event_to_agui`, `get_agent_for_request`, `AgentRequest`
- 产出：`router` (APIRouter), `/protocol/agui/chat` 端点

- [ ] **步骤 1：创建 router.py 骨架**

```python
# -*- coding: utf-8 -*-
"""AG-UI protocol router for QwenPaw.

This module provides the /protocol/agui/chat endpoint that streams
agent responses in AG-UI protocol format.
"""
import asyncio
import json
import logging
from typing import AsyncGenerator, Union

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from qwenpaw.schemas import AgentRequest
from ...agent_context import get_agent_for_request
from .converter import convert_agent_event_to_agui


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/protocol/agui", tags=["agui-protocol"])


class AGUIErrorResponse(BaseModel):
    """错误响应模型."""

    detail: str
    error_code: str = "agui_error"


@router.post(
    "/chat",
    summary="Chat with AG-UI protocol (streaming)",
    description="Stream agent response in AG-UI protocol format. "
    "Each line is a JSON object representing an AG-UI event.",
    responses={
        500: {"model": AGUIErrorResponse, "description": "ag-ui-protocol not installed"},
    },
)
async def post_agui_chat(
    request_data: Union[AgentRequest, dict],
    request: Request,
) -> StreamingResponse:
    """Stream agent response in AG-UI protocol format.

    Args:
        request_data: Agent request (AgentRequest or dict format)
        request: FastAPI request object

    Returns:
        StreamingResponse with AG-UI protocol events (one JSON per line)

    Raises:
        HTTPException: If ag-ui-protocol is not installed
    """
    # TODO: 在步骤 2-5 中实现完整逻辑
    pass
```

- [ ] **步骤 2：实现依赖检查和 agent 获取**

将 `post_agui_chat` 函数体替换为：

```python
    # 检查 ag-ui-protocol 是否可用
    try:
        from ag_ui.core.events import BaseEvent
    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=(
                "AG-UI protocol requires 'ag-ui-protocol' package. "
                "Install it: pip install 'ag-ui-protocol>=0.1.10,<0.2.0'"
            ),
        ) from e

    # 获取 agent 实例
    agent = await get_agent_for_request(request_data, request)
```

- [ ] **步骤 3：实现流式事件生成器**

在 `post_agui_chat` 函数前添加辅助生成器函数：

```python
async def _stream_agui_events(
    agent,
    request_data: Union[AgentRequest, dict],
) -> AsyncGenerator[str, None]:
    """Generate AG-UI protocol events from agent response.

    Args:
        agent: Agent instance
        request_data: Request data

    Yields:
        JSON-encoded AG-UI events (one per line)
    """
    try:
        # 调用 agent 的流式响应
        async for event in agent.stream_reply(request_data):
            # 转换为 AG-UI 格式
            agui_dict = convert_agent_event_to_agui(event)
            # 输出为 JSON 行
            yield json.dumps(agui_dict, ensure_ascii=False) + "\n"
    except Exception as e:
        logger.exception("Error in AG-UI event streaming")
        # 输出错误事件
        error_event = {
            "type": "error",
            "message": str(e),
        }
        yield json.dumps(error_event, ensure_ascii=False) + "\n"
```

- [ ] **步骤 4：完成 post_agui_chat 实现**

完成函数末尾：

```python
    # 创建流式响应
    return StreamingResponse(
        content=_stream_agui_events(agent, request_data),
        media_type="application/json",
        headers={
            "X-Protocol": "ag-ui",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
```

- [ ] **步骤 5：验证模块可导入**

运行：`python3 -c "from qwenpaw.app.protocol.agui.router import router; print('Router import successful'); print(f'Routes: {[r.path for r in router.routes]}')"`
预期：输出 "Router import successful" 和路由列表（应包含 `/protocol/agui/chat`）

- [ ] **步骤 6：提交**

```bash
git add src/qwenpaw/app/protocol/agui/router.py
git commit -m "feat(agui): implement AG-UI protocol router endpoint"
```

---

## 任务 5：在主应用中注册 AG-UI 路由

**文件：**
- 修改：`src/qwenpaw/app/_app.py`

**接口：**
- 消费：`qwenpaw.app.protocol.agui.router`
- 产出：在 FastAPI 应用中注册 AG-UI 路由

- [ ] **步骤 1：定位路由注册位置**

在 `_app.py` 中找到现有的路由注册代码（约在第 50-60 行）：

```python
from .routers import create_agent_scoped_router
from .routers import router as api_router
```

- [ ] **步骤 2：添加 AG-UI 路由导入**

在现有路由导入后添加：

```python
from .protocol.agui import router as agui_router
```

完成后应类似于：

```python
from .routers import create_agent_scoped_router
from .routers import router as api_router
from .protocol.agui import router as agui_router  # <-- 新增
```

- [ ] **步骤 3：定位应用注册路由的位置**

找到 `app.include_router` 调用（在 `create_app()` 函数中，约在第 250-280 行）：

```python
# Include routers
app.include_router(api_router)
```

- [ ] **步骤 4：注册 AG-UI 路由**

在 `app.include_router(api_router)` 后添加：

```python
# AG-UI protocol endpoint
app.include_router(agui_router)
```

完成后应类似于：

```python
# Include routers
app.include_router(api_router)
# AG-UI protocol endpoint
app.include_router(agui_router)  # <-- 新增
```

- [ ] **步骤 5：验证应用可以启动**

运行：`python3 -c "from qwenpaw.app._app import create_app; app = create_app(); print('App created successfully'); print('Routes:', [r.path for r in app.routes if hasattr(r, 'path') and '/protocol/agui' in r.path])"`
预期：输出 "App created successful" 和 AG-UI 路由（应包含 `/protocol/agui/chat`）

- [ ] **步骤 6：提交**

```bash
git add src/qwenpaw/app/_app.py
git commit -m "feat(agui): register AG-UI protocol router in main app"
```

---

## 任务 6：手动验证功能

**目的：** 确认 AG-UI 端点工作正常且不影响现有服务

**验证步骤：**

- [ ] **步骤 1：安装依赖**

```bash
pip install -e .
```

- [ ] **步骤 2：启动 QwenPaw 服务**

```bash
python3 -m qwenpaw
```

预期：服务正常启动，无错误

- [ ] **步骤 3：测试 AG-UI 端点基本可用性**

在另一个终端运行：

```bash
curl -X POST http://localhost:8000/protocol/agui/chat \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "default",
    "user_id": "test_user",
    "session_id": "test_session",
    "input": [{"content": [{"type": "text", "text": "Hello"}]}]
  }'
```

预期：
- 返回流式响应
- 每行是一个 JSON 对象
- 包含 AG-UI 事件类型（`run_started`, `step_started`, `text_message_start` 等）

- [ ] **步骤 4：验证现有 console/chat 端点未受影响**

```bash
curl -X POST http://localhost:8000/console/chat \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "default",
    "user_id": "test_user",
    "session_id": "test_session",
    "input": [{"content": [{"type": "text", "text": "Hello"}]}]
  }'
```

预期：返回流式响应（格式与之前相同，未变化）

- [ ] **步骤 5：验证依赖缺失时的错误处理**

先卸载 ag-ui-protocol（临时）：

```bash
pip uninstall ag-ui-protocol -y
```

重启服务，再次测试 AG-UI 端点：

```bash
curl -X POST http://localhost:8000/protocol/agui/chat \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "default",
    "user_id": "test_user",
    "session_id": "test_session",
    "input": [{"content": [{"type": "text", "text": "Hello"}]}]
  }'
```

预期：返回 500 错误，错误信息包含 "ag-ui-protocol" 和安装提示

重新安装依赖：

```bash
pip install 'ag-ui-protocol>=0.1.10,<0.2.0'
```

- [ ] **步骤 6：验证完整的事件流**

发送一个会触发工具调用的请求（如果有相关工具配置）：

```bash
curl -X POST http://localhost:8000/protocol/agui/chat \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "default",
    "user_id": "test_user",
    "session_id": "test_session",
    "input": [{"content": [{"type": "text", "text": "What time is it?"}]}]
  }'
```

预期：如果 agent 调用工具，应看到 `tool_call_start`、`tool_call_args`、`tool_call_result` 等事件

- [ ] **步骤 7：提交验证结果**

```bash
# 如果所有测试通过，创建完成标记
git commit --allow-empty -m "feat(agui): verify AG-UI protocol endpoint functionality"
```

---

## 实现完成检查清单

- [ ] 所有任务已完成
- [ ] 所有代码已提交
- [ ] AG-UI 端点工作正常
- [ ] 现有服务未受影响
- [ ] 错误处理正确

## 后续建议

虽然不在本任务范围内，但未来可以考虑：

1. **API 文档：** 为 `/protocol/agui/chat` 端点编写 API 文档
2. **自动化测试：** 添加单元测试和集成测试
3. **协议扩展：** 支持 A2A 协议或其他协议
4. **协议协商：** 支持 `Accept` 头的协议协商
5. **协议发现：** 添加 `/protocol/` 端点列出支持的协议
6. **性能优化：** 优化事件转换性能
7. **监控指标：** 添加 AG-UI 端点的使用监控

---

**实现计划版本：** 1.0
**创建日期：** 2026-07-22
**基于设计文档：** docs/superpowers/specs/2026-07-22-agui-protocol-support-design.md
