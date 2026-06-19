"""Cap oversized tool results in-context; write the full output through."""
from __future__ import annotations

import logging
from typing import Any, AsyncGenerator, Callable

from agentscope.message import Msg, TextBlock
from agentscope.middleware import MiddlewareBase
from agentscope.tool import ToolResponse

from ..types import LogEntry
from .history import HistoryStore
from .serialize import flatten_output

logger = logging.getLogger(__name__)


class ToolResultCapMiddleware(MiddlewareBase):
    """An ``on_acting`` middleware that caps a single oversized tool result.

    After a tool produces its final ``ToolResponse``, if the flattened text
    exceeds ``token_cap`` (the model's own estimator), the *full* output is
    written through to ``conversation_history`` and the in-context content is
    replaced by a token-bounded preview plus a recall pointer keyed by
    ``tool_call_id``. AgentScope's own truncation is disabled upstream, so this
    is the only capping path and it never loses data.
    """

    def __init__(
        self,
        *,
        history: HistoryStore,
        model: Any,
        session_id: str,
        run_id: str | None,
        task_id: str | None,
        agent_id: str | None = None,
        token_cap: int = 3000,
    ) -> None:
        self._history = history
        self._model = model
        self._session_id = session_id
        self._run_id = run_id
        self._task_id = task_id
        self._agent_id = agent_id
        self._token_cap = token_cap

    async def on_acting(
        self,
        agent: Any,  # pylint: disable=unused-argument
        input_kwargs: dict[str, Any],
        next_handler: Callable[..., AsyncGenerator[Any, None]],
    ) -> AsyncGenerator[Any, None]:
        tool_call = input_kwargs.get("tool_call")
        async for item in next_handler(**input_kwargs):
            if isinstance(item, ToolResponse):
                try:
                    item = await self._cap(item, tool_call)
                except Exception:  # noqa: BLE001
                    logger.exception("ToolResultCapMiddleware failed")
            yield item

    async def _cap(self, resp: ToolResponse, tool_call: Any) -> ToolResponse:
        text = flatten_output(resp.content)
        if not text:
            return resp
        n_tokens = await self._model.count_tokens(
            [Msg(name="scroll", role="assistant",
                 content=[TextBlock(text=text)])],
            None,
        )
        if n_tokens <= self._token_cap:
            return resp
        tcid = getattr(tool_call, "id", None)
        self._history.append(
            session_id=self._session_id,
            run_id=self._run_id,
            task_id=self._task_id,
            agent_id=self._agent_id,
            entry=LogEntry(
                kind="tool_result",
                role="tool",
                name=getattr(tool_call, "name", None),
                content=text,
                tool_call_id=tcid,
                metadata={"capped": True, "full_tokens": n_tokens},
            ),
        )
        keep = max(1, int(len(text) * self._token_cap / n_tokens))
        resp.content = [TextBlock(text=(
            f"{text[:keep]}\n"
            f"<<<TRUNCATED ~{n_tokens - self._token_cap} tokens>>>\n"
            "<system-info>Full output preserved durably. Recall it inside "
            'execute_python via ms.sql_query("SELECT content FROM '
            f"hist.conversation_history WHERE tool_call_id='{tcid}'\")."
            "</system-info>"
        ))]
        return resp
