# -*- coding: utf-8 -*-
"""ReMe-backed memory manager for agents.

The public class and registry key keep the historical ``ReMeLight`` naming so
existing agent configs continue to work, but the implementation delegates to
ReMe's application/job framework.
"""

import asyncio
import hashlib
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, TYPE_CHECKING

from agentscope.message import Msg, TextBlock, ToolResultState
from agentscope.tool import ToolChunk

from .base_memory_manager import BaseMemoryManager, memory_registry
from .embedding_model import EmbeddingTestResult
from .prompts import build_memory_guidance_prompt
from .reme_config import get_reme_app_config
from .reme_embedding import (
    EmbeddingReindexUnavailableError,
    ReMeEmbedding,
)
from .reme_inbox import (
    RESULT_JOB_NAMES,
    empty_result_body,
    emit_job_result,
    result_title,
)
from .reme_reranker import (
    call_reranker_api,
    extract_score,
    format_scores_for_header,
    load_reranker_config,
    parse_answer_into_sections,
    rebuild_search_answer_with_expansions,
    reconstruct_answer_from_sections,
    rerank_and_cap_response,
    rerank_search_results,
)
from ..model_factory import create_model_and_formatter_async
from ...app.inbox_store import append_event as append_inbox_event
from ...app.crons.contracts import ServiceCronJob
from ...config import load_config
from ...config.config import (
    load_agent_config,
    load_agent_config_async,
    update_agent_config_async,
    AgentProfileConfig,
    EmbeddingModelConfig,
    RerankerConfig,
)
from ...exceptions import ProviderError
from ...utils.io_utils import run_sync_io

if TYPE_CHECKING:
    from reme import ReMe
    from reme.application import Response

logger = logging.getLogger(__name__)

__all__ = [
    "EmbeddingReindexUnavailableError",
    "ReMeLightMemoryManager",
]

os.environ.setdefault("REME_DISABLE_LOGURU", "true")

NO_MEMORY_RESULTS = "(no memory results)"
INBOX_RESULT_HOOK_KEY = "qwenpaw_memory_result_hook"
_REME_SESSION_ID_HASH_PREFIX = "qpsid_sha256_"
_REQUIRED_REME_VERSION = "0.4.1.11"


class _ReMeContractError(RuntimeError):
    """Installed ReMe does not implement QwenPaw's pinned integration API."""


def _load_validated_reme_app() -> type:
    """Load the single supported ReMe contract or fail with one clear error."""
    import reme  # type: ignore
    from reme import ReMe as ReMeApp  # type: ignore
    from reme.components.file_store import LocalFileStore  # type: ignore

    if reme.__version__ != _REQUIRED_REME_VERSION:
        raise _ReMeContractError(
            "QwenPaw requires "
            f"reme-ai=={_REQUIRED_REME_VERSION}, found {reme.__version__}",
        )
    required = {
        "ReMe.run_job": getattr(ReMeApp, "run_job", None),
        "ReMe.update_component": getattr(ReMeApp, "update_component", None),
        "LocalFileStore.require_embedding_rebuild": getattr(
            LocalFileStore,
            "require_embedding_rebuild",
            None,
        ),
        "LocalFileStore.reindex": getattr(LocalFileStore, "reindex", None),
        "LocalFileStore.resume_embedding": getattr(
            LocalFileStore,
            "resume_embedding",
            None,
        ),
    }
    missing = [name for name, value in required.items() if not callable(value)]
    if missing:
        raise _ReMeContractError(
            "Installed ReMe is missing required integration APIs: "
            + ", ".join(missing),
        )
    return ReMeApp


def _to_reme_session_id(session_id: str) -> str:
    """Return a fixed-length, cross-platform ReMe storage identifier.

    ReMe uses the value as a filename component. Hashing the exact UTF-8 bytes
    avoids case-folding and Unicode-normalization collisions on Windows and
    default macOS filesystems, while leaving a stable budget for directories
    and ReMe's filename suffixes.

    Legacy dialog files are intentionally not migrated: upgraded sessions
    start a new hashed dialog, leaving old JSONL files untouched and orphaned.
    Previously extracted long-term memories may remain available through the
    existing memory store or index.
    """
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return f"{_REME_SESSION_ID_HASH_PREFIX}{digest}"


def _tool_chunk(text: str, *, ok: bool = True) -> ToolChunk:
    return ToolChunk(
        is_last=True,
        state=ToolResultState.SUCCESS if ok else ToolResultState.ERROR,
        content=[TextBlock(type="text", text=text)],
    )


@memory_registry.register("remelight")
# pylint: disable-next=too-many-public-methods
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
        self._lifecycle_writer_lock = asyncio.Lock()
        self._lifecycle_condition = asyncio.Condition()
        self._active_reme_jobs = 0
        self._lifecycle_operation: str | None = None
        self._tested_embedding: tuple[tuple[Any, ...], Any] | None = None
        self._active_embedding_config: EmbeddingModelConfig | None = None
        # Reranker config is not cached here; load_agent_config() already
        # provides mtime-based caching, so every call reads fresh data.
        logger.info(
            "ReMeLightMemoryManager init: agent_id=%s working_dir=%s",
            agent_id,
            working_dir,
        )

        self._initialize_reme()

    def _initialize_reme(self) -> None:
        """Build the embedded ReMe application from persisted config."""

        try:
            ReMeApp = _load_validated_reme_app()

            agent_config: AgentProfileConfig = load_agent_config(self.agent_id)
            memory_config = agent_config.running.reme_light_memory_config
            self._active_embedding_config = (
                memory_config.embedding_model_config.model_copy(deep=True)
            )
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
        except _ReMeContractError:
            raise
        except Exception as exc:
            logger.warning("ReMe import failed; memory disabled: %s", exc)

    async def start(self) -> None:
        """Start the embedded ReMe application."""
        if self._reme is None:
            return

        try:
            await self._update_qwenpaw_model()
        except ProviderError as exc:
            # A fresh installation has no active model until onboarding is
            # complete.  ReMe's provider-free jobs (for example BM25 reindex)
            # must still be available in that state.  Jobs that require an
            # LLM refresh the injected model immediately before execution.
            logger.info(
                "ReMe starting without an active QwenPaw model for agent "
                "'%s': %s",
                self.agent_id,
                exc,
            )
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
        """Close ReMe and clean up background summary worker state."""
        async with self._exclusive_reme_lifecycle("close"):
            return await self._close_reme_unlocked()

    async def _close_reme_unlocked(self) -> bool:
        """Close ReMe after the caller has quiesced all ReMe jobs."""
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

    @asynccontextmanager
    async def _reme_job_lease(self):
        """Keep the current ReMe generation alive for one complete job."""
        async with self._lifecycle_condition:
            await self._lifecycle_condition.wait_for(
                lambda: self._lifecycle_operation is None,
            )
            self._active_reme_jobs += 1
        try:
            yield
        finally:
            async with self._lifecycle_condition:
                self._active_reme_jobs -= 1
                if self._active_reme_jobs == 0:
                    self._lifecycle_condition.notify_all()

    @asynccontextmanager
    async def _exclusive_reme_lifecycle(self, operation: str):
        """Quiesce jobs and exclusively mutate the shared ReMe generation."""
        async with self._lifecycle_writer_lock:
            async with self._lifecycle_condition:
                self._lifecycle_operation = operation
            try:
                async with self._lifecycle_condition:
                    await self._lifecycle_condition.wait_for(
                        lambda: self._active_reme_jobs == 0,
                    )
                yield
            finally:
                async with self._lifecycle_condition:
                    self._lifecycle_operation = None
                    self._lifecycle_condition.notify_all()

    def get_memory_prompt(self) -> str:
        """Return memory guidance for system prompt injection."""
        agent_config = load_agent_config(self.agent_id)
        cfg = agent_config.running.reme_light_memory_config
        return build_memory_guidance_prompt(
            agent_config.language,
            memory_search_enabled=cfg.memory_search_enabled,
            daily_dir=getattr(cfg, "daily_dir", "memory"),
            digest_dir=getattr(cfg, "digest_dir", "digest"),
        )

    def get_memory_config(self) -> Any:
        """Return ReMe Light memory configuration."""
        agent_config = load_agent_config(self.agent_id)
        return agent_config.running.reme_light_memory_config

    def list_cron_jobs(self) -> list[ServiceCronJob]:
        """Declare the scheduled maintenance jobs supported by ReMe."""
        if self._reme is None or not getattr(self._reme, "is_started", False):
            return []

        cfg = self.get_memory_config()
        jobs: list[ServiceCronJob] = []
        if cfg.dream_cron_enabled and cfg.dream_cron:
            jobs.append(
                ServiceCronJob(
                    key="dream",
                    cron=cfg.dream_cron,
                    callback=self.dream,
                    misfire_grace_seconds=600,
                    jitter_seconds=60,
                ),
            )

        if cfg.daily_paper_cron_enabled and cfg.daily_paper_cron:
            jobs.append(
                ServiceCronJob(
                    key="daily-paper",
                    cron=cfg.daily_paper_cron,
                    callback=self.daily_paper,
                    misfire_grace_seconds=600,
                ),
            )
        if cfg.auto_fin_cron_enabled and cfg.auto_fin_cron:
            jobs.append(
                ServiceCronJob(
                    key="auto-fin",
                    cron=cfg.auto_fin_cron,
                    callback=self.auto_fin,
                    misfire_grace_seconds=600,
                ),
            )
        return jobs

    def list_memory_tools(self):
        """Return memory tool functions to register with the agent toolkit."""
        if not self.get_memory_config().memory_search_enabled:
            return []
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

        model, _formatter = await create_model_and_formatter_async(
            self.agent_id,
        )
        await self._reme.update_component(
            "as_llm",
            "default",
            model=model,
        )

    async def test_and_stage_embedding(
        self,
        config: EmbeddingModelConfig,
    ) -> EmbeddingTestResult:
        return await self._embedding_service().test_and_stage(config)

    def _embedding_service(self) -> ReMeEmbedding:
        return ReMeEmbedding(
            self,
            load_agent_config=load_agent_config_async,
            update_agent_config=update_agent_config_async,
        )

    async def _reload_embedding_config_unlocked(self) -> bool:
        """Recreate embedded ReMe while the caller owns the lifecycle lock."""
        await self._close_reme_unlocked()
        self._worker_stopping = False
        await run_sync_io(self._initialize_reme)
        await self.start()
        self._tested_embedding = None
        return self._reme is not None and bool(
            getattr(self._reme, "is_started", False),
        )

    async def apply_tested_embedding(
        self,
        config: EmbeddingModelConfig,
    ) -> bool:
        return await self._embedding_service().apply_staged(config)

    async def reload_embedding_config(self) -> bool:
        """Recreate ReMe when embedding components cannot be hot-updated.

        Workspace reloads reuse this manager, so first-time enablement and
        disabling must rebuild only the embedded ReMe application instead of
        replacing the whole memory service on every workspace reload.
        """
        async with self._exclusive_reme_lifecycle("embedding-reload"):
            return await self._reload_embedding_config_unlocked()

    async def _require_embedding_rebuild(self) -> None:
        """Keep vector search disabled in the active ReMe instance."""
        file_store = await self._reme.update_component(
            "file_store",
            "default",
        )
        await file_store.require_embedding_rebuild()

    async def _run_reme_job(
        self,
        name: str,
        *,
        needs_llm: bool = False,
        raise_on_error: bool = False,
        lifecycle_locked: bool = False,
        **kwargs: Any,
    ) -> "Response | None":
        """Run one embedded ReMe job.

        Args:
            name: Job name registered in the embedded ReMe config.
            needs_llm: Refresh the injected QwenPaw model before running.
            raise_on_error: Propagate an execution failure instead of
                flattening it into ``None``.  Callers that report failures to
                the user should set this, so that ``None`` keeps its single
                remaining meaning of "ReMe is not started".

        Returns:
            The job response, or ``None`` when ReMe is not started -- and,
            unless ``raise_on_error`` is set, also when the job raised.
        """
        if lifecycle_locked:
            return await self._run_reme_job_unlocked(
                name,
                needs_llm=needs_llm,
                raise_on_error=raise_on_error,
                **kwargs,
            )
        async with self._reme_job_lease():
            return await self._run_reme_job_unlocked(
                name,
                needs_llm=needs_llm,
                raise_on_error=raise_on_error,
                **kwargs,
            )

    async def _run_reme_job_unlocked(
        self,
        name: str,
        *,
        needs_llm: bool = False,
        raise_on_error: bool = False,
        **kwargs: Any,
    ) -> "Response | None":
        """Run a job while the caller holds a lifecycle lease."""
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
            if raise_on_error:
                raise
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
        if name not in RESULT_JOB_NAMES:
            return False
        memory_config = await run_sync_io(self.get_memory_config)
        return await emit_job_result(
            agent_id=self.agent_id,
            memory_config=memory_config,
            name=name,
            response=response,
            kwargs=kwargs,
            append_event=append_inbox_event,
        )

    @staticmethod
    def _inbox_result_title(name: str) -> str:
        return result_title(name)

    @staticmethod
    def _empty_inbox_result_body(name: str) -> str:
        return empty_result_body(name)

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

        reranker_config = await self._get_reranker_config()
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

        await self._rerank_and_cap_response(
            query,
            response,
            cap,
            reranker_config,
        )

        answer = str(response.answer or "").strip()
        if not answer:
            answer = NO_MEMORY_RESULTS
        return _tool_chunk(answer, ok=response.success)

    # ── reranker helpers ──────────────────────────────────────────────

    async def _rerank_and_cap_response(
        self,
        query: str,
        response: "Response",
        cap: int,
        reranker_config: RerankerConfig | None,
    ) -> None:
        await rerank_and_cap_response(
            query,
            response,
            cap,
            reranker_config,
            self._rerank_search_results,
        )

    async def _rerank_search_results(
        self,
        query: str,
        response: "Response",
        config: RerankerConfig,
    ) -> None:
        await rerank_search_results(
            query,
            response,
            config,
            self._call_reranker_api,
        )

    @staticmethod
    def _format_scores_for_header(
        score: float,
        scores: dict[str, float],
    ) -> str:
        return format_scores_for_header(score, scores)

    @staticmethod
    def _extract_score(result: dict) -> float:
        return extract_score(result)

    @staticmethod
    def _rebuild_search_answer_with_expansions(
        results: list[dict],
        link_expansion: dict[str, dict],
    ) -> str:
        return rebuild_search_answer_with_expansions(results, link_expansion)

    @staticmethod
    def _parse_answer_into_sections(answer: str) -> dict[str, str]:
        return parse_answer_into_sections(answer)

    @staticmethod
    def _reconstruct_answer_from_sections(
        sections: dict[str, str],
        results: list[dict],
    ) -> str:
        return reconstruct_answer_from_sections(sections, results)

    async def _get_reranker_config(self) -> RerankerConfig | None:
        return await load_reranker_config(self.agent_id)

    async def _call_reranker_api(  # pylint: disable=too-many-return-statements
        self,
        query: str,
        documents: list[str],
        config: RerankerConfig,
    ) -> list[int] | None:
        return await call_reranker_api(query, documents, config)

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
            messages=[message.model_dump(mode="json") for message in messages],
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
        agent_config = await load_agent_config_async(self.agent_id)
        memory_cfg = agent_config.running.reme_light_memory_config
        if not memory_cfg.auto_memory_search_config.enabled:
            return None

        msgs = [messages] if isinstance(messages, Msg) else list(messages)
        query = self._build_query(msgs)
        if not query:
            return None

        search_cfg = memory_cfg.auto_memory_search_config

        cap = max(1, search_cfg.max_results)
        reranker_config = await self._get_reranker_config()
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
            min_score=0,
        )
        if response is None or not response.success:
            return None

        await self._rerank_and_cap_response(
            query,
            response,
            cap,
            reranker_config,
        )

        text = str(response.answer or "").strip()
        if not text:
            return None

        assistant_msg = self._build_auto_memory_search_msg(
            query=query,
            max_results=cap,
            text=text,
            estimate_divisor=self._resolve_token_estimate_divisor(
                agent_config,
            ),
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

    async def daily_paper(self, **kwargs: Any) -> None:
        """Build one Daily Paper brief and publish its result to inbox."""
        cfg = await run_sync_io(self.get_memory_config)
        response = await self._run_reme_job(
            "daily_paper",
            needs_llm=True,
            raise_on_error=True,
            date=str(kwargs.get("date") or ""),
            force=bool(kwargs.get("force", False)),
            use_hf_mirror=bool(
                kwargs.get(
                    "use_hf_mirror",
                    cfg.daily_paper_use_hf_mirror,
                ),
            ),
            topics=str(kwargs.get("topics", cfg.daily_paper_topics) or ""),
        )
        if response is None:
            raise RuntimeError("ReMe is not started; Daily Paper did not run")
        if not response.success:
            raise RuntimeError(str(response.answer))

    async def auto_fin(self, **kwargs: Any) -> None:
        """Build one Auto Fin report and publish its result to inbox."""
        cfg = await run_sync_io(self.get_memory_config)
        response = await self._run_reme_job(
            "auto_fin",
            needs_llm=True,
            raise_on_error=True,
            date=str(kwargs.get("date") or ""),
            topics=str(kwargs.get("topics", cfg.auto_fin_topics) or ""),
            window_hours=float(
                kwargs.get("window_hours", cfg.auto_fin_window_hours),
            ),
        )
        if response is None:
            raise RuntimeError("ReMe is not started; Auto Fin did not run")
        if not response.success:
            raise RuntimeError(str(response.answer))

    async def reme_status(self) -> "Response | None":
        """Return embedded ReMe component memory estimates and process RSS."""
        return await self._run_reme_job("status")

    async def graph_snapshot(self) -> "Response | None":
        """Return the complete indexed wikilink graph for the console."""
        return await self._run_reme_job("graph_snapshot")

    async def rebuild_index(self, scope: str = "all") -> "Response | None":
        return await self._embedding_service().rebuild_index(scope)

    async def undo_embedding_reindex(self) -> EmbeddingModelConfig:
        return await self._embedding_service().undo_reindex()

    @property
    def is_reindexing(self) -> bool:
        """Whether an explicit index rebuild is active."""
        return self._reindex_lock.locked()
