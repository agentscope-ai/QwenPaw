# -*- coding: utf-8 -*-
"""ReMe-backed memory manager for agents.

The public class and registry key keep the historical ``ReMeLight`` naming so
existing agent configs continue to work, but the implementation delegates to
ReMe's application/job framework.
"""

import asyncio
import base64
import hashlib
import logging
import os
import re
from typing import Any, TYPE_CHECKING

import httpx

from agentscope.message import Msg, TextBlock
from agentscope.message import ToolResultState
from agentscope.tool import ToolChunk

from .base_memory_manager import BaseMemoryManager, memory_registry
from .prompts import build_memory_guidance_prompt
from .reme_config import get_reme_app_config
from ..model_factory import create_model_and_formatter
from ...app.inbox_store import append_event as append_inbox_event
from ...config import load_config
from ...config.config import (
    load_agent_config,
    AgentProfileConfig,
    RerankerConfig,
)

if TYPE_CHECKING:
    from reme import ReMe
    from reme.application import Response

logger = logging.getLogger(__name__)

os.environ.setdefault("REME_DISABLE_LOGURU", "true")

NO_MEMORY_RESULTS = "(no memory results)"
INBOX_RESULT_JOB_NAMES = {"auto_memory", "auto_dream", "auto_resource"}
INBOX_RESULT_HOOK_KEY = "qwenpaw_memory_result_hook"
INBOX_EMITTED_METADATA_KEY = "_qwenpaw_inbox_emitted"
MAX_INBOX_BODY_CHARS = 4000
_REME_SESSION_ID_PREFIX = "qpsid_"
_REME_SESSION_ID_B64_PREFIX = f"{_REME_SESSION_ID_PREFIX}b64_"
_REME_SESSION_ID_HASH_PREFIX = f"{_REME_SESSION_ID_PREFIX}sha256_"
_MAX_REME_SESSION_ID_CHARS = 240
_WINDOWS_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED_FILENAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def _to_reme_session_id(session_id: str) -> str:
    """Return a stable Windows-safe session ID for ReMe file storage.

    ReMe 0.4 uses ``session_id`` as a filename component. QwenPaw channel
    IDs deliberately contain separators such as ``telegram:123``, which are
    valid logical identifiers but invalid Windows filenames. Keep ordinary
    IDs unchanged for compatibility and encode only unsafe IDs. IDs beginning
    with our encoding namespace are encoded as well, making the mapping
    unambiguous for existing user-provided IDs.
    """
    filename_stem = session_id.split(".", 1)[0].upper()
    is_safe = (
        bool(session_id)
        and session_id == session_id.strip()
        and session_id not in {".", ".."}
        and not session_id.endswith(".")
        and not _WINDOWS_INVALID_FILENAME_CHARS.search(session_id)
        and filename_stem not in _WINDOWS_RESERVED_FILENAMES
        and not session_id.startswith(_REME_SESSION_ID_PREFIX)
        and len(session_id) <= _MAX_REME_SESSION_ID_CHARS
    )
    if is_safe:
        return session_id

    encoded = (
        base64.urlsafe_b64encode(session_id.encode("utf-8"))
        .decode(
            "ascii",
        )
        .rstrip("=")
    )
    encoded_session_id = f"{_REME_SESSION_ID_B64_PREFIX}{encoded}"
    if len(encoded_session_id) <= _MAX_REME_SESSION_ID_CHARS:
        return encoded_session_id

    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return f"{_REME_SESSION_ID_HASH_PREFIX}{digest}"


def _tool_chunk(text: str, *, ok: bool = True) -> ToolChunk:
    return ToolChunk(
        is_last=True,
        state=ToolResultState.SUCCESS if ok else ToolResultState.ERROR,
        content=[TextBlock(type="text", text=text)],
    )


@memory_registry.register("remelight")
class ReMeLightMemoryManager(BaseMemoryManager):
    """Memory manager backed by ReMe.

    ReMe uses the QwenPaw workspace root as its vault.  Daily memory,
    digest memory, search, auto-memory, and auto-dream are executed through
    ReMe jobs.
    """

    def __init__(self, working_dir: str, agent_id: str):
        super().__init__(working_dir=working_dir, agent_id=agent_id)
        self._reme: "ReMe | None" = None
        self._reindex_lock = asyncio.Lock()
        self._reranker_config_cache: RerankerConfig | None = None
        logger.info(
            "ReMeLightMemoryManager init: agent_id=%s working_dir=%s",
            agent_id,
            working_dir,
        )

        try:
            from reme import ReMe as ReMeApp  # type: ignore

            agent_config: AgentProfileConfig = load_agent_config(self.agent_id)
            global_config = load_config()
            self._reme = ReMeApp(
                **get_reme_app_config(
                    working_dir=self.working_dir,
                    agent_config=agent_config,
                    user_timezone=getattr(
                        global_config,
                        "user_timezone",
                        None,
                    ),
                ),
            )
            self._install_reme_result_hook()
        except Exception as exc:
            logger.warning("ReMe import failed; memory disabled: %s", exc)

    async def start(self) -> None:
        """Start the embedded ReMe application."""
        if self._reme is None:
            return

        await self._update_qwenpaw_model()
        try:
            await self._reme.start()
            logger.info(
                "ReMe memory manager started for agent '%s'",
                self.agent_id,
            )
        except Exception:
            logger.exception("ReMe start failed")
            return

    async def close(self) -> bool:
        """Close ReMe and cleanup background summary worker state."""
        logger.info(
            "ReMeLightMemoryManager closing: agent_id=%s",
            self.agent_id,
        )

        worker_stopped = await self._shutdown_summarize_worker()

        if self._reme is not None:
            try:
                await self._reme.close()
            except Exception:
                logger.exception("ReMe close failed")
                return False

        self._reme = None
        return worker_stopped

    def get_memory_prompt(self) -> str:
        """Return memory guidance for system prompt injection."""
        agent_config = load_agent_config(self.agent_id)
        cfg = agent_config.running.reme_light_memory_config
        return build_memory_guidance_prompt(
            agent_config.language,
            daily_dir=cfg.daily_dir,
        )

    def get_memory_config(self) -> Any:
        """Return ReMe Light memory configuration."""
        agent_config = load_agent_config(self.agent_id)
        return agent_config.running.reme_light_memory_config

    def list_memory_tools(self):
        """Return memory tool functions to register with the agent toolkit."""
        return [self.memory_search]

    def get_auto_memory_interval(self) -> int:
        """Return ReMe light auto-memory cadence from agent config."""
        agent_config = load_agent_config(self.agent_id)
        interval = (
            agent_config.running.reme_light_memory_config.auto_memory_interval
        )
        if interval is None:
            return 0
        return int(interval)

    async def _update_qwenpaw_model(self) -> None:
        """Reuse QwenPaw's active model in ReMe's default LLM component."""
        if self._reme is None:
            return

        model, _formatter = create_model_and_formatter(self.agent_id)
        await self._reme.update_component(
            "as_llm",
            "default",
            model=model,
        )

    async def _run_reme_job(
        self,
        name: str,
        *,
        needs_llm: bool = False,
        **kwargs: Any,
    ) -> "Response | None":
        if self._reme is None or not getattr(self._reme, "is_started", False):
            logger.debug("ReMe job skipped; app not started: %s", name)
            return None
        try:
            if needs_llm:
                await self._update_qwenpaw_model()
            response = await self._reme.run_job(name, **kwargs)
            await self._append_reme_job_result_to_inbox(
                name,
                response=response,
                kwargs=kwargs,
            )
            return response
        except Exception:
            logger.exception("ReMe job failed: %s", name)
            return None

    def _install_reme_result_hook(self) -> None:
        """Expose QwenPaw inbox delivery to ReMe background steps."""
        if self._reme is None:
            return
        context = getattr(self._reme, "context", None)
        metadata = getattr(context, "metadata", None)
        if not isinstance(metadata, dict):
            logger.debug("ReMe result hook skipped; metadata unavailable")
            return
        metadata[INBOX_RESULT_HOOK_KEY] = self._handle_reme_result_hook

    async def _handle_reme_result_hook(
        self,
        *,
        job_name: str,
        response: "Response",
        kwargs: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Handle result notifications emitted from ReMe background steps."""
        del metadata
        await self._append_reme_job_result_to_inbox(
            job_name,
            response=response,
            kwargs=kwargs or {},
        )

    async def _append_reme_job_result_to_inbox(
        self,
        name: str,
        *,
        response: "Response",
        kwargs: dict[str, Any],
    ) -> bool:
        if name not in INBOX_RESULT_JOB_NAMES:
            return False
        memory_config = self.get_memory_config()
        if not memory_config.inbox_push_enabled:
            logger.info(
                "ReMe job result inbox push disabled: "
                "agent_id=%s job_name=%s",
                self.agent_id,
                name,
            )
            return False
        response_metadata = getattr(response, "metadata", None)
        if isinstance(response_metadata, dict) and response_metadata.get(
            INBOX_EMITTED_METADATA_KEY,
        ):
            return False
        if (
            name in {"auto_memory", "auto_resource"}
            and isinstance(response_metadata, dict)
            and response_metadata.get("modified") is False
        ):
            logger.info(
                "ReMe job result inbox push skipped; no memory change: "
                "agent_id=%s job_name=%s modified=False",
                self.agent_id,
                name,
            )
            return False

        answer = str(getattr(response, "answer", "") or "").strip()
        if len(answer) > MAX_INBOX_BODY_CHARS:
            answer = f"{answer[:MAX_INBOX_BODY_CHARS].rstrip()}\n..."
        success = bool(getattr(response, "success", False))
        title = self._inbox_result_title(name)
        body = answer or self._empty_inbox_result_body(name)
        payload: dict[str, Any] = {
            "job_name": name,
            "session_id": str(kwargs.get("session_id") or ""),
            "date": str(kwargs.get("date") or ""),
            "hint": str(
                kwargs.get("memory_hint") or kwargs.get("hint") or "",
            ),
        }
        if name == "auto_resource":
            changes = kwargs.get("changes") or []
            if isinstance(changes, list):
                payload["change_count"] = len(changes)
            if isinstance(response_metadata, dict):
                payload["processed"] = response_metadata.get("processed")

        try:
            event = await append_inbox_event(
                agent_id=self.agent_id,
                source_type="memory",
                source_id=name,
                event_type=f"{name}_result",
                status="success" if success else "error",
                severity="info" if success else "error",
                title=title,
                body=body,
                payload=payload,
            )
            if isinstance(response_metadata, dict):
                response_metadata[INBOX_EMITTED_METADATA_KEY] = True
            logger.info(
                "ReMe job result pushed to inbox: "
                "agent_id=%s job_name=%s event_id=%s status=%s modified=%s",
                self.agent_id,
                name,
                event.get("id"),
                event.get("status"),
                (
                    response_metadata.get("modified")
                    if isinstance(response_metadata, dict)
                    else None
                ),
            )
            return True
        except Exception:  # pylint: disable=broad-except
            logger.exception(
                "failed to push ReMe job result to inbox: "
                "agent_id=%s job_name=%s success=%s",
                self.agent_id,
                name,
                success,
            )
            return False

    @staticmethod
    def _inbox_result_title(name: str) -> str:
        return {
            "auto_memory": "Auto-memory result",
            "auto_dream": "Auto-dream result",
            "auto_resource": "Auto-resource result",
        }.get(name, "Memory job result")

    @staticmethod
    def _empty_inbox_result_body(name: str) -> str:
        return {
            "auto_memory": "Auto-memory completed with no returned content.",
            "auto_dream": "Auto-dream completed with no returned content.",
            "auto_resource": (
                "Auto-resource completed with no returned content."
            ),
        }.get(name, "Memory job completed with no returned content.")

    async def memory_search(
        self,
        query: str,
        max_results: int = 5,
        min_score: float = 0,
    ) -> ToolChunk:
        """Search memory files semantically.

        Use this tool before answering questions about prior work,
        decisions, dates, people, preferences, or todos. Returns top
        relevant snippets with file paths and line numbers.

        When a reranker is configured and enabled, this over-fetches
        (``max_results × candidate_multiplier``), reranks the candidates,
        caps back to ``max_results``, and rebuilds the answer text.

        Args:
            query (`str`):
                The semantic search query to find relevant memory snippets.
            max_results (`int`, optional):
                Maximum number of search results to return. Defaults to 5.
            min_score (`float`, optional):
                Minimum relevance score for results. Defaults to 0; keep this
                at 0 in normal use because ReMe search may mix BM25 and fused
                scores with different scales, and raising it can hide valid
                keyword matches.

        Returns:
            `ToolResponse`:
                Search results formatted with paths, line numbers, and
                content.
        """
        query = query.strip()
        if not query:
            return _tool_chunk("Error: query cannot be empty", ok=False)

        reranker_config = self._get_reranker_config()
        cap = max(1, max_results)

        # Over-fetch when reranker is enabled: take N * multiplier
        # candidates, rerank, then return top-N.
        effective_limit = (
            cap * reranker_config.candidate_multiplier
            if reranker_config
            else cap
        )

        response = await self._run_reme_job(
            "search",
            query=query,
            limit=effective_limit,
            min_score=max(0.0, min_score),
        )
        if response is None:
            return _tool_chunk("ReMe is not started.", ok=False)

        results = (
            response.metadata.get("results") if response.success else None
        )
        if results:
            # Rerank (only reorders results, answer is rebuilt below)
            if reranker_config and len(results) > 1:
                try:
                    await self._rerank_search_results(
                        query,
                        response,
                        reranker_config,
                    )
                    results = response.metadata["results"]
                except Exception:
                    logger.warning(
                        "[rerank] failed, using original order",
                        exc_info=True,
                    )
            # Cap to max_results and rebuild answer when order/count changed
            truncated = len(results) > cap
            if truncated:
                results = results[:cap]
                response.metadata["results"] = results
            if reranker_config or truncated:
                response.answer = self._rebuild_search_answer(results)

        answer = str(response.answer or "").strip()
        if not answer:
            answer = NO_MEMORY_RESULTS
        return _tool_chunk(answer, ok=response.success)

    # ── reranker helpers ──────────────────────────────────────────────

    async def _rerank_search_results(
        self,
        query: str,
        response: "Response",
        config: RerankerConfig,
    ) -> None:
        """Re-order search results using a dedicated reranker API.

        Only reorders ``response.metadata['results']``; the answer text is
        rebuilt by the caller (``memory_search``) after capping.
        """
        results = response.metadata.get("results")
        if not results or len(results) <= 1:
            return

        # Truncate long texts to 500 chars each for the reranker call
        texts: list[str] = [r.get("text", "")[:500] for r in results]

        new_order = await self._call_reranker_api(query, texts, config)
        if not new_order or len(new_order) != len(results):
            return

        reordered: list[dict] = []
        for idx in new_order:
            if 0 <= idx < len(results):
                reordered.append(results[idx])

        if len(reordered) != len(results):
            return

        response.metadata["results"] = reordered
        logger.info(
            "[rerank] reordered %d results with model=%s",
            len(results),
            config.model_name,
        )

    @staticmethod
    def _rebuild_search_answer(results: list[dict]) -> str:
        """Rebuild search answer text from results (search_step format)."""
        answer_lines: list[str] = []
        for r in results:
            path = r.get("path", "")
            start_line = r.get("start_line", 0)
            end_line = r.get("end_line", 0)
            score = r.get("score", 0.0)
            text = r.get("text", "")
            header = (
                f"========== {path}:{start_line}-{end_line} "
                f"[score={score:.4f}] =========="
            )
            answer_lines.append(f"{header}\n{text}")
        return "\n".join(answer_lines)

    def _get_reranker_config(self) -> RerankerConfig | None:
        """Return cached reranker config, or None if not enabled.

        Config is cached on first access and refreshed when the agent
        config is reloaded (via `_refresh_config_cache`).
        """
        if self._reranker_config_cache is not None:
            return self._reranker_config_cache

        try:
            agent_cfg = load_agent_config(self.agent_id)
            cfg = agent_cfg.running.reme_light_memory_config.reranker_config
            if cfg and cfg.enabled and cfg.model_name:
                self._reranker_config_cache = cfg
                return cfg
        except Exception:
            logger.warning("[rerank] failed to load config", exc_info=True)

        self._reranker_config_cache = None
        return None

    def _refresh_config_cache(self) -> None:
        """Invalidate cached reranker config (call after config reload)."""
        self._reranker_config_cache = None

    async def _call_reranker_api(  # pylint: disable=too-many-return-statements
        self,
        query: str,
        documents: list[str],
        config: RerankerConfig,
    ) -> list[int] | None:
        """Call a reranker API to score and reorder documents by relevance.

        Uses the standard OpenAI-compatible reranker endpoint::

            POST {base_url}/rerank
            {
                "model": "...",
                "query": "...",
                "documents": ["...", ...],
                "top_n": N
            }

        Returns a list of indices sorted by relevance (most relevant first),
        or ``None`` on failure.
        """
        if not config.base_url:
            logger.warning("[rerank] base_url not configured")
            return None
        if not query or not documents:
            return None

        base_url = config.base_url.rstrip("/")
        url = f"{base_url}/rerank"

        payload: dict[str, Any] = {
            "model": config.model_name,
            "query": query,
            "documents": documents,
        }

        try:
            async with httpx.AsyncClient(timeout=config.timeout) as client:
                resp = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {config.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()

            if "results" not in data:
                logger.warning(
                    "[rerank] unexpected response format: %s",
                    data,
                )
                return None

            # Sort by score descending, return indices
            scored = [
                (r["index"], r.get("relevance_score", 0.0))
                for r in data["results"]
            ]
            scored.sort(key=lambda x: x[1], reverse=True)
            ordered = [idx for idx, _ in scored]

            logger.info(
                "[rerank] API responded with %d results",
                len(ordered),
            )
            return ordered

        except httpx.TimeoutException:
            logger.warning("[rerank] API timed out after %ss", config.timeout)
            return None
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "[rerank] HTTP error: %s %s",
                exc.response.status_code,
                exc.response.text[:500],
            )
            return None
        except Exception:
            logger.warning("[rerank] unexpected error", exc_info=True)
            return None

    async def summarize(
        self,
        messages: list[Msg],
        **kwargs: Any,
    ) -> str:
        """Persist conversation messages through ReMe auto-memory."""
        if not messages:
            return ""

        session_id = str(kwargs.get("session_id") or "")
        if not session_id:
            logger.warning(
                "ReMe summarize skipped; session_id is empty: "
                "agent_id=%s messages=%s",
                self.agent_id,
                len(messages),
            )
            return ""

        response = await self._run_reme_job(
            "auto_memory",
            needs_llm=True,
            messages=[msg.model_dump(mode="json") for msg in messages],
            session_id=_to_reme_session_id(session_id),
            memory_hint=str(kwargs.get("memory_hint") or ""),
        )
        if response is None:
            return ""
        return str(response.answer or "")

    async def auto_memory_search(
        self,
        messages: list[Msg] | Msg,
        agent_name: str = "",
        **kwargs: Any,
    ) -> dict | None:
        """Auto-search memory and expose it as a completed tool interaction."""
        del agent_name
        del kwargs
        agent_config = load_agent_config(self.agent_id)
        memory_cfg = agent_config.running.reme_light_memory_config
        if not memory_cfg.auto_memory_search_config.enabled:
            return None

        msgs = [messages] if isinstance(messages, Msg) else list(messages)
        query = self._build_query(msgs)
        if not query:
            return None

        search_cfg = memory_cfg.auto_memory_search_config

        max_results = max(1, search_cfg.max_results)
        response = await self._run_reme_job(
            "search",
            query=query,
            limit=max_results,
            min_score=0,
        )
        if response is None or not response.success:
            return None

        text = str(response.answer or "").strip()
        if not text:
            return None

        assistant_msg = self._build_auto_memory_search_msg(
            query=query,
            max_results=max_results,
            text=text,
        )
        return {
            "query": query,
            "text": text,
            "msg": msgs + [assistant_msg],
        }

    async def auto_memory(
        self,
        all_messages: list[Msg],
        **kwargs: Any,
    ) -> None:
        """Auto-extract memory for a prepared reply batch."""
        if not all_messages:
            return
        all_messages = self._messages_without_auto_memory_search(all_messages)
        if not all_messages:
            return
        session_id = str(kwargs.get("session_id") or "")
        if not session_id:
            logger.warning(
                "ReMe auto_memory skipped; session_id is empty: "
                "agent_id=%s messages=%s",
                self.agent_id,
                len(all_messages),
            )
            return

        self.add_summarize_task(
            messages=all_messages,
            session_id=session_id,
        )

    async def dream(self, **kwargs: Any) -> None:
        """Run one ReMe auto-dream pass."""
        response = await self._run_reme_job(
            "auto_dream",
            needs_llm=True,
            date=str(kwargs.get("date") or ""),
            hint=str(kwargs.get("hint") or ""),
        )
        if response is not None and not response.success:
            raise RuntimeError(str(response.answer))

    async def reme_status(self) -> "Response | None":
        """Return embedded ReMe component memory estimates and process RSS."""
        return await self._run_reme_job("status")

    async def rebuild_index(self) -> "Response | None":
        """Clear and rebuild the ReMe search index on explicit request."""
        if self._reindex_lock.locked():
            raise RuntimeError("Memory index rebuild is already running")
        async with self._reindex_lock:
            return await self._run_reme_job("reindex")
