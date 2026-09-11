# -*- coding: utf-8 -*-
"""Session-gated on_reply middleware: delegate turns to the engine.

When a QwenPaw session has data-analysis mode active (``/data on``), the
middleware skips the workspace agent entirely and drives the engine's
ChatRuntime over its SSE API, re-emitting engine frames as AgentScope
events so every configured QwenPaw channel renders them natively.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from copy import deepcopy
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

from agentscope.event import (
    TextBlockDeltaEvent,
    TextBlockEndEvent,
    TextBlockStartEvent,
)
from agentscope.message import Msg, TextBlock
from agentscope.middleware import MiddlewareBase

from .engine_client import (
    EngineClient,
    EngineResponseError,
    EngineUnavailableError,
)
from .events import (
    TurnResult,
    emit_artifacts,
    render_followups_text,
    translate_frames,
)
from .session_store import BridgeSessionState, BridgeSessionStore

logger = logging.getLogger(__name__)

_OPTION_SEPARATORS = {",", "，", "、"}
_ENGINE_UNAVAILABLE_MESSAGE = "⚠️ 分析引擎当前不可用，请稍后重试；可回复 /data off 退出数据分析模式。"
_STALE_SESSION_MESSAGE = "分析会话已失效并已重置，请重新发送刚才的问题。"
_ENGINE_REQUEST_ERROR_MESSAGE = "分析请求未能完成，请稍后重试。"


def parse_option_numbers(text: str, count: int) -> Optional[List[int]]:
    """Parse "1" / "1,3" / "1 3" into 0-based indices within ``count``."""
    indices: List[int] = []
    position = 0
    length = len(text)

    while position < length and text[position].isspace():
        position += 1
    while position < length:
        start = position
        while position < length and text[position].isdecimal():
            position += 1
        if start == position:
            return None

        number = int(text[start:position])
        if number < 1 or number > count:
            return None
        indices.append(number - 1)

        whitespace_start = position
        while position < length and text[position].isspace():
            position += 1
        if position == length:
            return indices
        if text[position] in _OPTION_SEPARATORS:
            position += 1
            while position < length and text[position].isspace():
                position += 1
            if position == length:
                return None
        elif position == whitespace_start:
            return None

    return indices or None


def _extract_user_text(inputs: Any) -> Optional[str]:
    """Return the last user message's text, or None for non-Msg inputs."""
    msgs: List[Any]
    if isinstance(inputs, Msg):
        msgs = [inputs]
    elif (
        isinstance(inputs, list)
        and inputs
        and all(isinstance(m, Msg) for m in inputs)
    ):
        msgs = inputs
    else:
        return None
    for msg in reversed(msgs):
        if msg.role != "user":
            continue
        text = msg.get_text_content()
        if text:
            return text
    return None


class DataBridgeMiddleware(MiddlewareBase):
    """Full-turn takeover: QwenPaw channel message → engine chat."""

    def __init__(
        self,
        *,
        client: EngineClient,
        store: BridgeSessionStore,
        session_key: str,
    ) -> None:
        self._client = client
        self._store = store
        self._session_key = session_key
        self._last_answer = ""

    # ------------------------------------------------------------------
    # pylint: disable=too-many-statements,too-many-branches
    async def on_reply(  # noqa: C901, PLR0912, PLR0915
        self,
        agent: Any,
        input_kwargs: dict,
        next_handler: Callable[..., AsyncGenerator],
    ) -> AsyncGenerator:
        inputs = input_kwargs.get("inputs")
        text = _extract_user_text(inputs)
        if text is None:
            # Confirm/interrupt resumptions belong to the normal agent.
            async for item in next_handler():
                yield item
            return

        reply_id = f"bridge-{uuid.uuid4().hex[:12]}"
        state = self._store.get(self._session_key)

        # --- pending /datasource numeric selection -------------------
        if state.pending_datasource_choice:
            choice = self._resolve_datasource_choice(state, text)
            if choice is not None:
                async for item in self._apply_datasource_choice(
                    reply_id,
                    choice,
                ):
                    yield item
                self._record_turn(agent, inputs, self._last_answer)
                return
            # Not a selection — drop the offer and treat as a question.
            self._store.update(
                self._session_key,
                pending_datasource_choice=None,
            )
            state.pending_datasource_choice = None

        result = TurnResult()
        chat_id = ""
        operation = ""
        try:
            pending = state.pending_clarification
            if pending is not None and not (
                isinstance(pending, dict) and pending
            ):
                state = self._store.update(
                    self._session_key,
                    pending_clarification=None,
                )
                pending = None

            if pending is not None:
                chat_id = str(pending.get("chat_id") or "")
                after_seq = self._sequence_number(pending.get("last_seq"))
                if pending.get("answered") is not True:
                    operation = "answer"
                    await self._client.answer_clarification(
                        state.engine_session_id,
                        chat_id,
                        clarification_id=str(
                            pending.get("clarification_id") or "",
                        ),
                        answers=self._build_clarification_answers(
                            pending,
                            text,
                        ),
                    )
                    pending = {**pending, "answered": True}
                    self._store.update(
                        self._session_key,
                        pending_clarification=pending,
                    )
            else:
                if not state.engine_session_id:
                    operation = "create_session"
                    session = await self._client.create_session(
                        title=text[:64],
                        datasource_id=state.datasource_id,
                    )
                    state = self._store.update(
                        self._session_key,
                        engine_session_id=str(session.get("id") or ""),
                    )
                operation = "create_chat"
                chat = await self._client.create_chat(
                    state.engine_session_id,
                    text,
                    datasource_id=state.datasource_id,
                )
                chat_id = str(chat.get("id") or "")
                after_seq = -1

            operation = "stream"
            frames = self._client.stream_events(
                state.engine_session_id,
                chat_id,
                after_sequence_number=after_seq,
            )
            try:
                async for event in translate_frames(
                    frames,
                    result,
                    reply_id=reply_id,
                ):
                    yield event
            except asyncio.CancelledError:
                await self._best_effort_stop(
                    state.engine_session_id,
                    chat_id,
                )
                raise

            if result.clarification is not None:
                self._store.update(
                    self._session_key,
                    pending_clarification={
                        "chat_id": chat_id,
                        "clarification_id": (
                            result.clarification.clarification_id
                        ),
                        "questions": result.clarification.questions,
                        "last_seq": result.last_seq,
                    },
                )
                self._record_turn(agent, inputs, result.answer)
                return

            if pending is not None:
                self._store.update(
                    self._session_key,
                    pending_clarification=None,
                )

            session_id = state.engine_session_id
            async for event in emit_artifacts(
                result.artifacts,
                reply_id=reply_id,
                fetch=lambda path: self._client.download_artifact(
                    session_id,
                    path,
                ),
            ):
                yield event

            if result.status == "failed":
                message = result.failure_message or "请稍后重试"
                async for event in self._text_block(
                    reply_id,
                    "bridge-error",
                    f"⚠️ 执行失败：{message}",
                ):
                    yield event
            elif result.status == "completed" and result.followups:
                async for event in self._text_block(
                    reply_id,
                    "bridge-followups",
                    render_followups_text(result.followups),
                ):
                    yield event

            self._record_turn(agent, inputs, result.answer)

        except EngineResponseError as exc:
            if exc.status_code == 404 and operation in {
                "create_chat",
                "answer",
                "stream",
            }:
                self._store.update(
                    self._session_key,
                    engine_session_id="",
                    pending_clarification=None,
                )
                message = _STALE_SESSION_MESSAGE
            elif 500 <= exc.status_code < 600:
                message = _ENGINE_UNAVAILABLE_MESSAGE
            else:
                message = _ENGINE_REQUEST_ERROR_MESSAGE
            logger.warning(
                "bridge: engine HTTP failure (session=%s, status=%s)",
                self._session_key,
                exc.status_code,
            )
            async for event in self._text_block(
                reply_id,
                "bridge-error",
                message,
            ):
                yield event
        except EngineUnavailableError:
            logger.warning(
                "bridge: engine unavailable (session=%s)",
                self._session_key,
                exc_info=True,
            )
            async for event in self._text_block(
                reply_id,
                "bridge-error",
                _ENGINE_UNAVAILABLE_MESSAGE,
            ):
                yield event

    # ------------------------------------------------------------------
    def _resolve_datasource_choice(
        self,
        state: BridgeSessionState,
        text: str,
    ) -> Optional[Dict[str, Any]]:
        options = state.pending_datasource_choice or []
        indices = parse_option_numbers(text, len(options))
        if indices is None or len(indices) != 1:
            return None
        return options[indices[0]]

    async def _apply_datasource_choice(
        self,
        reply_id: str,
        choice: Dict[str, Any],
    ) -> AsyncGenerator:
        """Bind the datasource by starting a fresh engine session.

        The engine pins a session to its datasource at creation, so a
        new selection opens a new engine session rather than mutating
        the old one.
        """
        datasource_id = str(choice.get("id") or "")
        name = str(choice.get("name") or datasource_id)
        try:
            session = await self._client.create_session(
                title=f"[{name}]",
                datasource_id=datasource_id,
            )
        except EngineResponseError as exc:
            self._last_answer = ""
            if 500 <= exc.status_code < 600:
                message = "⚠️ 分析引擎当前不可用，数据源未切换。"
            else:
                message = "数据源未能切换，请稍后重试。"
            async for event in self._text_block(
                reply_id,
                "bridge-error",
                message,
            ):
                yield event
            return
        except EngineUnavailableError:
            self._last_answer = ""
            async for event in self._text_block(
                reply_id,
                "bridge-error",
                "⚠️ 分析引擎当前不可用，数据源未切换。",
            ):
                yield event
            return
        self._store.update(
            self._session_key,
            datasource_id=datasource_id,
            engine_session_id=str(session.get("id") or ""),
            pending_datasource_choice=None,
            pending_clarification=None,
        )
        text = f"✅ 已选择数据源：{name}。请直接提问开始分析。"
        self._last_answer = text
        async for event in self._text_block(
            reply_id,
            "bridge-datasource",
            text,
        ):
            yield event

    @staticmethod
    def _sequence_number(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return -1

    @staticmethod
    def _build_clarification_answers(
        pending: Dict[str, Any],
        text: str,
    ) -> List[Dict[str, Any]]:
        raw_questions = pending.get("questions")
        if not isinstance(raw_questions, list):
            return []

        answers: List[Dict[str, Any]] = []
        for raw_question in raw_questions:
            question = raw_question if isinstance(raw_question, dict) else {}
            question_text = question.get("question")
            if not isinstance(question_text, str):
                question_text = ""
            raw_options = question.get("options")
            options = raw_options if isinstance(raw_options, list) else []
            indices = parse_option_numbers(text, len(options))
            selected: List[str] = []
            if indices is not None:
                for index in indices:
                    option = options[index]
                    label = (
                        option.get("label")
                        if isinstance(option, dict)
                        else None
                    )
                    if not isinstance(label, str):
                        selected = []
                        indices = None
                        break
                    selected.append(label)

            if indices is not None:
                if not question.get("multi_select") and len(selected) > 1:
                    selected = selected[:1]
                answers.append(
                    {
                        "question": question_text,
                        "selected_options": selected,
                        "custom_text": None,
                    },
                )
            else:
                answers.append(
                    {
                        "question": question_text,
                        "selected_options": [],
                        "custom_text": text,
                    },
                )
        return answers

    async def _best_effort_stop(self, session_id: str, chat_id: str) -> None:
        if not chat_id:
            return
        try:
            await self._client.stop(session_id, chat_id)
        except Exception:
            logger.warning(
                "bridge: stop failed for chat %s",
                chat_id,
                exc_info=True,
            )

    @staticmethod
    async def _text_block(
        reply_id: str,
        block_id: str,
        text: str,
    ) -> AsyncGenerator:
        yield TextBlockStartEvent(reply_id=reply_id, block_id=block_id)
        yield TextBlockDeltaEvent(
            reply_id=reply_id,
            block_id=block_id,
            delta=text,
        )
        yield TextBlockEndEvent(reply_id=reply_id, block_id=block_id)

    def _record_turn(self, agent: Any, inputs: Any, answer: str) -> None:
        """Keep QwenPaw session history coherent for post-takeover turns.

        Skipping ``next_handler`` bypasses agentscope's own context
        bookkeeping, so append the user message(s) and the bridged
        answer directly.
        """
        try:
            context = agent.state.context
        except AttributeError:
            return
        try:
            msgs = [inputs] if isinstance(inputs, Msg) else list(inputs)
            for msg in msgs:
                if isinstance(msg, Msg):
                    context.append(deepcopy(msg))
            if answer:
                context.append(
                    Msg(
                        name=getattr(agent, "name", "assistant"),
                        role="assistant",
                        content=[TextBlock(text=answer)],
                    ),
                )
        except Exception:
            logger.warning(
                "bridge: failed to record turn in agent context",
                exc_info=True,
            )


def make_bridge_middleware_factory(
    *,
    client: EngineClient,
    store: BridgeSessionStore,
) -> Callable[[Any, Any], Optional[DataBridgeMiddleware]]:
    """Per-request factory: activate only for bridged channel sessions."""

    def factory(ctx: Any, agent_config: Any) -> Optional[DataBridgeMiddleware]:
        _ = agent_config
        session_id = getattr(ctx, "session_id", "") or ""
        if not session_id or session_id.startswith("pawapp:"):
            return None
        request = getattr(ctx, "request", None)
        channel = (getattr(request, "channel", None) or "") if request else ""
        if not channel:
            return None
        if not store.get(session_id).active:
            return None
        return DataBridgeMiddleware(
            client=client,
            store=store,
            session_key=session_id,
        )

    return factory
