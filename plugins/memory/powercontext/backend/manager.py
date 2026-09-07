# -*- coding: utf-8 -*-
"""PowerContext memory backend plugin implementation."""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Any

from agentscope.message import Msg, TextBlock, ToolResultState
from agentscope.tool import ToolChunk

from qwenpaw.memory import (
    AutoMemorySearchOptions,
    BaseMemoryManager,
    MemoryBackendContext,
    NO_RELEVANT_MEMORIES,
)
from .client import (
    MAX_MEMORY_TEXT_BYTES,
    TRUNCATION_MARKER,
    PowerContextConfig,
    PowerContextMemoryClient,
    safe_powercontext_exception_summary,
    truncate_utf8_text,
)
from .config import PowerContextMemoryConfig
from .prompts import (
    POWERCONTEXT_MEMORY_GUIDANCE_EN,
    POWERCONTEXT_MEMORY_GUIDANCE_ZH,
    POWERCONTEXT_UNTRUSTED_HISTORY_NOTICE,
)

logger = logging.getLogger(__name__)

DEFAULT_MAX_CONTEXT_BYTES = 12000


def get_or_create_installation_id(working_dir: str) -> str:
    """Persist a plugin-owned installation scope beside agent workspaces."""
    path = Path(working_dir).resolve().parent / ".powercontext-installation-id"
    try:
        existing = path.read_text(encoding="utf-8").strip()
        if len(existing) == 32:
            return existing
    except FileNotFoundError:
        pass
    generated = uuid.uuid4().hex
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return path.read_text(encoding="utf-8").strip()
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(generated)
    return generated


class PowerContextMemoryManager(BaseMemoryManager):
    def __init__(self, context: MemoryBackendContext) -> None:
        super().__init__(context=context)
        self._client: PowerContextMemoryClient | None = None
        self._config: PowerContextMemoryConfig | None = None
        self._resolved_scope_id = ""

    async def start(self) -> None:
        cfg = PowerContextMemoryConfig.model_validate(
            self.context.backend_config,
        )
        self._config = cfg
        if cfg is None or not cfg.base_url.strip():
            logger.warning("PowerContext is not configured; backend disabled")
            return
        try:
            scope_id = cfg.scope_id.strip()
            if not scope_id:
                installation_id = self._get_installation_id()
                scope_id = f"qwenpaw:{installation_id}:agent:{self.agent_id}"
            self._client = PowerContextMemoryClient(
                PowerContextConfig(
                    base_url=cfg.base_url.strip(),
                    token=cfg.token.strip(),
                    scope_id=scope_id,
                    timeout=cfg.timeout,
                ),
            )
            self._resolved_scope_id = scope_id
        except Exception as exc:
            summary = safe_powercontext_exception_summary(
                exc,
                token=cfg.token.strip(),
            )
            logger.warning("PowerContext initialization failed: %s", summary)
            self._client = None
            self._resolved_scope_id = ""

    def _get_installation_id(self) -> str:
        return get_or_create_installation_id(self.working_dir)

    async def _close_backend(self) -> bool:
        """Close the remote client after shared auto-memory work stops."""
        client, self._client = self._client, None
        self._resolved_scope_id = ""
        if client is None:
            return True
        try:
            await client.close()
            return True
        except Exception as exc:
            logger.warning(
                "PowerContext close failed: %s",
                safe_powercontext_exception_summary(
                    exc,
                    token=str(
                        getattr(getattr(client, "config", None), "token", ""),
                    ),
                ),
            )
            return False

    def get_memory_prompt(self) -> str:
        if self._client is None:
            return ""
        language = self.context.language
        return (
            POWERCONTEXT_MEMORY_GUIDANCE_ZH
            if language == "zh"
            else POWERCONTEXT_MEMORY_GUIDANCE_EN
        )

    def list_memory_tools(self) -> list[Callable[..., ToolChunk]]:
        if self._client is None:
            return []

        @wraps(self.memory_search)
        async def powercontext_memory_search(
            query: str,
            max_results: int = 5,
            min_score: float = 0.0,
        ) -> ToolChunk:
            return await self.memory_search(query, max_results, min_score)

        # The public function name remains ``memory_search`` for agent and
        # prompt compatibility. Governance must nevertheless classify this
        # remote implementation as network I/O rather than local lookup.
        setattr(
            powercontext_memory_search,
            "_qwenpaw_policy_name",
            "PowerContextMemorySearch",
        )

        setattr(
            self.memory_remember.__func__,
            "_qwenpaw_policy_name",
            "PowerContextMemoryRemember",
        )
        return [powercontext_memory_search, self.memory_remember]

    def get_auto_memory_interval(self) -> int:
        return 1 if self._client is not None else 0

    async def get_auto_memory_search_options(
        self,
    ) -> AutoMemorySearchOptions | None:
        """Return configured PowerContext automatic recall settings."""
        config = self._config
        if (
            self._client is None
            or config is None
            or not getattr(
                config.auto_memory_search_config,
                "enabled",
                True,
            )
        ):
            return None
        search_config = config.auto_memory_search_config
        return AutoMemorySearchOptions(
            max_results=max(
                1,
                int(getattr(search_config, "max_results", 3)),
            ),
            estimate_divisor=self.context.token_estimate_divisor,
        )

    async def _search_for_auto_memory(
        self,
        *,
        query: str,
        options: AutoMemorySearchOptions,
    ) -> ToolChunk | None:
        """Search within PowerContext's complete synthetic-message budget."""
        max_results = max(1, int(options.max_results))
        max_context_bytes = self._config.auto_memory_search_config.max_context_bytes
        result = await self._search_memories(
            query,
            max_results,
            max_context_bytes=self._auto_search_result_budget(
                query=query,
                max_results=max_results,
                max_context_bytes=max_context_bytes,
                estimate_divisor=options.estimate_divisor,
            ),
        )
        if self._tool_chunk_text(result).strip() == NO_RELEVANT_MEMORIES:
            return None
        return result

    async def auto_memory(
        self,
        messages: list[Msg],
        **kwargs: Any,
    ) -> str:
        del kwargs
        if self._client is None:
            return ""
        messages = self._messages_without_auto_memory_search(messages)
        user = [
            m.get_text_content().strip()
            for m in messages
            if m.role == "user" and m.get_text_content().strip()
        ]
        assistant = [
            m.get_text_content().strip()
            for m in messages
            if m.role == "assistant" and m.get_text_content().strip()
        ]
        if not user:
            return ""
        text = "用户目标/输入:\n" + "\n".join(user[-3:])
        if assistant:
            text += "\n\nAgent结果:\n" + "\n".join(assistant[-2:])
        try:
            await self._client.remember(
                kind="task_state",
                text=truncate_utf8_text(text, marker=TRUNCATION_MARKER),
            )
        except Exception as exc:
            # The shared worker records and logs the raised exception. Ensure
            # backend credentials cannot be copied into either surface.
            raise RuntimeError(self._safe_exception_summary(exc)) from exc
        return "Saved auto-memory to PowerContext."

    async def memory_search(
        self,
        query: str,
        max_results: int = 5,
        min_score: float = 0.0,
        **kwargs: Any,
    ) -> ToolChunk:
        """Search PowerContext memories and include their exact Citation."""
        del kwargs
        return await self._search_memories(
            query,
            max_results,
            min_score,
            max_context_bytes=getattr(
                getattr(self._config, "auto_memory_search_config", None),
                "max_context_bytes",
                DEFAULT_MAX_CONTEXT_BYTES,
            ),
        )

    async def _search_memories(
        self,
        query: str,
        max_results: int,
        min_score: float = 0.0,
        *,
        max_context_bytes: int,
    ) -> ToolChunk:
        """Search and bound the complete rendered result before injection."""
        if self._client is None:
            return self._tool_error("PowerContext is not configured.")

        parts: list[str] = []
        notice_bytes = len(
            POWERCONTEXT_UNTRUSTED_HISTORY_NOTICE.encode("utf-8"),
        )
        used_bytes = notice_bytes
        was_truncated = False
        try:
            for hit in await self._client.search(
                query=query,
                limit=max_results,
            ):
                score = float(hit.get("score", 0.0))
                text = hit.get("text", "")
                citation = self._memory_citation(hit)
                if text and score >= min_score:
                    separator = "\n\n"
                    remaining = (
                        max_context_bytes
                        - used_bytes
                        - len(separator.encode("utf-8"))
                    )
                    if remaining <= 0:
                        was_truncated = True
                        break
                    rendered = self._format_memory_hit(
                        index=len(parts) + 1,
                        score=score,
                        text=text,
                        citation=citation,
                    )
                    bounded = truncate_utf8_text(
                        rendered,
                        max_bytes=remaining,
                        marker=TRUNCATION_MARKER,
                    )
                    if not bounded:
                        break
                    parts.append(bounded)
                    used_bytes += len(separator.encode("utf-8")) + len(
                        bounded.encode("utf-8"),
                    )
                    if len(bounded.encode("utf-8")) < len(
                        rendered.encode("utf-8"),
                    ):
                        was_truncated = True
                        break
        except Exception as exc:
            summary = self._safe_exception_summary(exc)
            logger.warning("PowerContext memory search failed: %s", summary)
            return self._tool_error(
                f"PowerContext memory search failed: {summary}",
            )
        rendered_result = (
            POWERCONTEXT_UNTRUSTED_HISTORY_NOTICE + "\n\n" + "\n\n".join(parts)
            if parts
            else NO_RELEVANT_MEMORIES
        )
        if (
            was_truncated
            and parts
            and not rendered_result.endswith(TRUNCATION_MARKER)
        ):
            rendered_result = truncate_utf8_text(
                rendered_result + ("x" * max_context_bytes),
                max_bytes=max_context_bytes,
                marker=TRUNCATION_MARKER,
            )
        return ToolChunk(
            is_last=True,
            state=ToolResultState.SUCCESS,
            content=[
                TextBlock(
                    type="text",
                    text=rendered_result,
                ),
            ],
        )

    async def memory_remember(self, kind: str, text: str) -> ToolChunk:
        """Explicitly persist one important memory in PowerContext."""
        if self._client is None:
            return self._tool_error("PowerContext is not configured.")
        if not kind.strip() or not text.strip():
            return self._tool_error("Both kind and text are required.")
        normalized_text = text.strip()
        if len(normalized_text.encode("utf-8")) > MAX_MEMORY_TEXT_BYTES:
            return self._tool_error(
                "PowerContext memory text must not exceed "
                "8000 UTF-8 bytes.",
            )
        try:
            await self._client.remember(
                kind=kind.strip(),
                text=normalized_text,
            )
        except Exception as exc:
            summary = self._safe_exception_summary(exc)
            logger.warning(
                "PowerContext explicit memory write failed: %s",
                summary,
            )
            return self._tool_error(
                f"PowerContext memory write failed: {summary}",
            )
        return self._tool_success("Memory saved to PowerContext.")

    def _scope_id(self) -> str:
        return self._resolved_scope_id or (
            getattr(self._config, "scope_id", None) or f"agent:{self.agent_id}"
        )

    @staticmethod
    def _memory_citation(hit: dict[str, Any]) -> dict[str, Any] | None:
        citation = hit.get("citation") or {}
        memory_ref = citation.get("memory_ref") or {}
        entry_id = citation.get("entry_id")
        entry_version_id = citation.get("entry_version_id")
        family = memory_ref.get("family")
        artifact_id = memory_ref.get("artifact_id")
        revision = memory_ref.get("revision")
        if not entry_id or not entry_version_id:
            return None
        if not family or not artifact_id or not revision:
            return None
        return {
            "memory_ref": {
                "family": family,
                "artifact_id": artifact_id,
                "revision": revision,
            },
            "entry_id": entry_id,
            "entry_version_id": entry_version_id,
        }

    def _format_memory_hit(
        self,
        *,
        index: int,
        score: float,
        text: str,
        citation: dict[str, Any] | None,
    ) -> str:
        if citation is None:
            citation_text = "citation: unavailable"
        else:
            memory_ref = citation["memory_ref"]
            citation_text = (
                f"family: {memory_ref['family']}, "
                f"artifact_id: {memory_ref['artifact_id']}, "
                f"revision: {memory_ref['revision']}, "
                f"entry_id: {citation['entry_id']}, "
                f"entry_version_id: {citation['entry_version_id']}, "
                f"scope: {self._scope_id()}"
            )
        return (
            f"[{index}] (powercontext, score: {score:.2f}, "
            f"{citation_text})\n{text}"
        )

    @staticmethod
    def _tool_success(text: str) -> ToolChunk:
        return ToolChunk(
            is_last=True,
            state=ToolResultState.SUCCESS,
            content=[TextBlock(type="text", text=text)],
        )

    @staticmethod
    def _tool_error(text: str) -> ToolChunk:
        return ToolChunk(
            is_last=True,
            state=ToolResultState.ERROR,
            content=[TextBlock(type="text", text=text)],
        )

    def _safe_exception_summary(self, exc: BaseException) -> str:
        token = str(
            getattr(getattr(self._client, "config", None), "token", ""),
        )
        return safe_powercontext_exception_summary(exc, token=token)

    def _auto_search_result_budget(
        self,
        *,
        query: str,
        max_results: int,
        max_context_bytes: int,
        estimate_divisor: float = 4.0,
    ) -> int:
        """Reserve bytes for synthetic tool metadata before retrieval text."""
        message = self._build_auto_memory_search_msg(
            query=query,
            max_results=max_results,
            text="",
            estimate_divisor=estimate_divisor,
        )
        overhead = 0
        for block in message.content:
            overhead += len(str(getattr(block, "text", "")).encode("utf-8"))
            overhead += len(
                str(getattr(block, "thinking", "")).encode("utf-8"),
            )
            block_name = str(getattr(block, "name", ""))
            block_input = str(getattr(block, "input", ""))
            overhead += len((block_name + block_input).encode("utf-8"))
        return max(0, max_context_bytes - overhead)
