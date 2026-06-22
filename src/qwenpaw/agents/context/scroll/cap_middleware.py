# -*- coding: utf-8 -*-
"""Cap oversized tool results in-context; write the full output through."""
from __future__ import annotations

import logging
import sqlite3
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
        agent_id: str | None = None,
        token_cap: int = 3000,
        capped_results: dict[str, int] | None = None,
    ) -> None:
        self._history = history
        self._model = model
        self._session_id = session_id
        self._agent_id = agent_id
        self._token_cap = token_cap
        # Shared with the manager: tool_call_id -> seq of the full output we
        # persisted, so the manager skips re-writing the truncated stub.
        self._capped_results = (
            capped_results if capped_results is not None else {}
        )

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
                except (sqlite3.Error, OSError) as exc:
                    # The durable write failed: don't truncate (that would
                    # lose data we couldn't store) — yield the full output and
                    # record degraded durability instead of hiding it.
                    self._history.note_write_failure(exc)
                    logger.exception("ToolResultCapMiddleware write failed")
            yield item

    async def _cap(self, resp: ToolResponse, tool_call: Any) -> ToolResponse:
        text = flatten_output(resp.content)
        if not text:
            return resp
        n_tokens = await self._model.count_tokens(
            [
                Msg(
                    name="scroll",
                    role="assistant",
                    content=[TextBlock(text=text)],
                ),
            ],
            None,
        )
        if n_tokens <= self._token_cap:
            return resp
        tcid = getattr(tool_call, "id", None)
        seq = self._history.append(
            session_id=self._session_id,
            agent_id=self._agent_id,
            dedup_key=tcid,
            entry=LogEntry(
                kind="tool_result",
                role="tool",
                name=getattr(tool_call, "name", None),
                content=text,
                tool_call_id=tcid,
                metadata={"capped": True, "full_tokens": n_tokens},
            ),
        )
        # Tell the manager this result is already durable (in full) so it
        # won't re-persist the truncated stub it sees in-context. Keyed by
        # tcid, which the manager uses as the result's dedup key.
        if tcid is not None:
            self._capped_results[tcid] = seq
        keep = max(1, int(len(text) * self._token_cap / n_tokens))
        resp.content = [
            TextBlock(
                text=(
                    f"{text[:keep]}\n"
                    f"<<<TRUNCATED ~{n_tokens - self._token_cap} tokens>>>\n"
                    "<system-info>Full output preserved durably. Recall it "
                    "inside recall_history_python via "
                    f"ms.recall_tool({tcid!r}).</system-info>"
                ),
            ),
        ]
        return resp
