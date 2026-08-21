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

import httpx

from agentscope.message import Msg, TextBlock, ToolResultState
from agentscope.tool import ToolChunk

from .base_memory_manager import BaseMemoryManager, memory_registry
from .embedding_model import (
    EmbeddingTestResult,
    embedding_config_fingerprint,
    embedding_vector_space_fingerprint,
    test_embedding_model,
)
from .prompts import build_memory_guidance_prompt
from .reme_config import get_reme_app_config
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
from ...utils.io_utils import (
    run_sync_io,
    unlink_async,
)

if TYPE_CHECKING:
    from reme import ReMe
    from reme.application import Response

logger = logging.getLogger(__name__)

os.environ.setdefault("REME_DISABLE_LOGURU", "true")

NO_MEMORY_RESULTS = "(no memory results)"
INBOX_RESULT_JOB_NAMES = {"auto_memory", "auto_dream", "daily_paper"}
INBOX_NOTIFICATION_FIELDS = {
    "auto_memory": "auto_memory_inbox_push_enabled",
    "auto_dream": "auto_dream_inbox_push_enabled",
    "daily_paper": "daily_paper_inbox_push_enabled",
}
INBOX_RESULT_HOOK_KEY = "qwenpaw_memory_result_hook"
INBOX_EMITTED_METADATA_KEY = "_qwenpaw_inbox_emitted"
MAX_INBOX_BODY_CHARS = 4000
_REME_SESSION_ID_HASH_PREFIX = "qpsid_sha256_"


def _is_successful_noop_inbox_result(name: str, response: Any) -> bool:
    """Return whether a successful memory job made no meaningful change.

    Unknown or incomplete metadata deliberately fails open so notification
    behavior stays compatible across ReMe versions.  Failures are never
    treated as no-ops because they remain useful to surface to the user.
    """
    if not bool(getattr(response, "success", False)):
        return False

    metadata = getattr(response, "metadata", None)
    if not isinstance(metadata, dict):
        return False

    if name == "auto_memory":
        return metadata.get("modified") is False

    if name == "auto_dream":
        dream = metadata.get("dream")
        if not isinstance(dream, dict):
            return False
        # Require both fields to be present as empty lists.  This suppresses
        # only a definitive no-op and avoids hiding results from older ReMe
        # versions whose metadata contract may be less detailed.
        return (
            dream.get("changed_paths") == []
            and dream.get("deleted_paths") == []
        )

    return False


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
            from reme import ReMe as ReMeApp  # type: ignore

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
        """Test and retain the exact model object for the next save."""
        model, result = await test_embedding_model(config)
        if result.success and model is not None:
            self._tested_embedding = (
                embedding_config_fingerprint(config),
                model,
            )
        else:
            self._tested_embedding = None
        return result

    async def apply_tested_embedding(
        self,
        config: EmbeddingModelConfig,
    ) -> bool:
        """Hot-apply the last successfully tested embedding object.

        Returns ``False`` when a normal workspace reload is required, such as
        first-time enablement or when the submitted config was not tested.
        """
        if self._reme is None or not getattr(self._reme, "is_started", False):
            return False
        staged = self._tested_embedding
        if staged is None or staged[0] != embedding_config_fingerprint(config):
            return False

        async with self._exclusive_reme_lifecycle("embedding-update"):
            tested_model = staged[1]
            if hasattr(tested_model, "context_size"):
                tested_model.context_size = config.max_input_length
            try:
                await self._reme.update_component(
                    "as_embedding",
                    "default",
                    model=tested_model,
                )
                store = await self._reme.update_component(
                    "embedding_store",
                    "default",
                    enable_cache=config.enable_cache,
                    max_cache_size=config.max_cache_size,
                    max_input_length=config.max_input_length,
                    max_batch_size=config.max_batch_size,
                )
            except KeyError:
                # ReMe 0.4 cannot add/remove components after initialization.
                return False

            old_config = self._active_embedding_config
            vector_space_changed = old_config is None or (
                embedding_vector_space_fingerprint(old_config)
                != embedding_vector_space_fingerprint(config)
            )
            if vector_space_changed:
                # LocalEmbeddingStore cache keys only include dimensions, so a
                # same-dimension model switch must explicitly invalidate it.
                cache = getattr(store, "_cache", None)
                if cache is not None:
                    cache.clear()
                if hasattr(store, "_key_suffix"):
                    setattr(
                        store,
                        "_key_suffix",
                        f"|{config.dimensions}".encode(),
                    )
                cache_path = getattr(store, "cache_path", None)
                if cache_path is not None:
                    await unlink_async(cache_path, missing_ok=True)

            self._active_embedding_config = config.model_copy(deep=True)
            self._tested_embedding = None
            return True

    async def reload_embedding_config(self) -> bool:
        """Recreate ReMe when embedding components cannot be hot-updated.

        Workspace reloads reuse this manager, so first-time enablement and
        disabling must rebuild only the embedded ReMe application instead of
        replacing the whole memory service on every workspace reload.
        """
        async with self._exclusive_reme_lifecycle("embedding-reload"):
            await self._close_reme_unlocked()
            self._worker_stopping = False
            await run_sync_io(self._initialize_reme)
            await self.start()
            self._tested_embedding = None
            return self._reme is not None and bool(
                getattr(self._reme, "is_started", False),
            )

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
        if name not in INBOX_RESULT_JOB_NAMES:
            return False
        memory_config = await run_sync_io(self.get_memory_config)
        if not getattr(memory_config, INBOX_NOTIFICATION_FIELDS[name]):
            logger.info(
                "ReMe job result inbox push disabled: agent_id=%s job_name=%s",
                self.agent_id,
                name,
            )
            return False
        response_metadata = getattr(response, "metadata", None)
        if isinstance(response_metadata, dict) and response_metadata.get(
            INBOX_EMITTED_METADATA_KEY,
        ):
            return False
        if _is_successful_noop_inbox_result(name, response):
            logger.info(
                "ReMe job result inbox push skipped; successful no-op: "
                "agent_id=%s job_name=%s",
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
        if name == "daily_paper":
            payload["force"] = bool(kwargs.get("force", False))
            payload["topics"] = str(kwargs.get("topics") or "")
            if isinstance(response_metadata, dict):
                for key in (
                    "digest_path",
                    "selected_arxiv_ids",
                    "note_paths",
                    "pdf_paths",
                    "skipped",
                ):
                    if key in response_metadata:
                        payload[key] = response_metadata[key]

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
            "daily_paper": "Daily Paper result",
        }.get(name, "Memory job result")

    @staticmethod
    def _empty_inbox_result_body(name: str) -> str:
        return {
            "auto_memory": "Auto-memory completed with no returned content.",
            "auto_dream": "Auto-dream completed with no returned content.",
            "daily_paper": "Daily Paper completed with no returned content.",
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
        """Over-fetch, rerank, cap, and rebuild answer on **response**.

        Shared by ``memory_search()`` and ``auto_memory_search()``.
        Mutates ``response.metadata["results"]`` and ``response.answer``
        in place.  Does nothing when ``reranker_config`` is ``None`` or
        results are empty or already short enough (no truncation).
        """
        metadata = getattr(response, "metadata", None)
        results = (
            metadata.get("results") if response.success and metadata else None
        )
        if not results:
            return

        # Save original metadata for fallback reconstruction.
        original_link_expansion = (
            metadata.get("link_expansion", {}) if response.success else {}
        )
        # Parse the original ReMe answer into sections keyed by
        # "path:line-line" so we can reorder + cap them while preserving
        # link expansions and hybrid score details.
        original_answer = str(response.answer or "")
        answer_sections = (
            self._parse_answer_into_sections(original_answer)
            if original_answer
            else {}
        )

        # Rerank (only reorders results, answer sections are reordered
        # below)
        reranker_did_reorder = False
        if reranker_config and len(results) > 1:
            try:
                before = list(results)
                await self._rerank_search_results(
                    query,
                    response,
                    reranker_config,
                )
                results = response.metadata["results"]
                reranker_did_reorder = results != before
            except Exception:
                logger.warning(
                    "[rerank] failed, using original order",
                    exc_info=True,
                )
        # Cap to max_results
        truncated = len(results) > cap
        if truncated:
            results = results[:cap]
            response.metadata["results"] = results
        # Reconstruct answer from sections when order or count changed,
        # preserving the original ReMe answer (including link expansions
        # and hybrid score details) whenever possible.
        if reranker_did_reorder or truncated:
            if answer_sections:
                response.answer = self._reconstruct_answer_from_sections(
                    answer_sections,
                    results,
                )
            else:
                # Fallback: answer format was unexpected; rebuild from
                # raw metadata (results + link_expansion) so link
                # expansions are still preserved.
                response.answer = self._rebuild_search_answer_with_expansions(
                    results,
                    original_link_expansion,
                )

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

        # Validate that the response is a permutation of 0..n-1
        # (duplicate indices would silently drop results)
        if set(new_order) != set(range(len(results))):
            logger.warning(
                "[rerank] API returned invalid indices (not a permutation): "
                "%s for %d results — using original order",
                new_order,
                len(results),
            )
            return

        # All indices are validated as a permutation of 0..n-1 above,
        # so no bounds check is needed here.
        reordered = [results[idx] for idx in new_order]

        response.metadata["results"] = reordered
        logger.info(
            "[rerank] reordered %d results with model=%s",
            len(results),
            config.model_name,
        )

    @staticmethod
    def _format_scores_for_header(
        score: float,
        scores: dict[str, float],
    ) -> str:
        """Format scores as ``score=0.9000 [vector=0.8500 keyword=0.6500]``.

        Mirrors ReMe's ``_format_scores`` so the rebuilt header matches the
        original answer format.  Returns a space-separated string suitable
        for use inside the ``[...]`` bracket of a section header.
        """
        hybrid = "vector" in scores and "keyword" in scores
        parts = [f"score={score:.4f}"]
        if hybrid:
            for k in ("vector", "keyword"):
                v = scores.get(k)
                if v is not None:
                    parts.append(f"{k}={v:.4f}")
        return " ".join(parts)

    @staticmethod
    def _extract_score(result: dict) -> float:
        """Extract the fused score from a ReMe search result dict.

        ReMe's ``FileChunk.score`` is a regular property backed by
        ``self.scores["score"]``.  When results are serialized with
        ``model_dump(exclude_none=True, exclude={"embedding"})``, the
        top-level ``score`` key is **not** included.  Always prefer the
        nested ``scores["score"]`` first, then fall back to a top-level
        ``score`` key for backward compatibility with test fixtures.
        """
        scores = result.get("scores", {})
        if isinstance(scores, dict) and "score" in scores:
            return scores["score"]
        return result.get("score", 0.0)

    @staticmethod
    def _rebuild_search_answer_with_expansions(
        results: list[dict],
        link_expansion: dict[str, dict],
    ) -> str:
        """Rebuild search answer from results + link_expansion metadata.

        Preserves link expansions and hybrid score details by reading them
        from the raw ReMe metadata (``response.metadata["link_expansion"]``
        and each result's ``scores`` dict).  Used as the fallback path when
        the answer text does not match the expected section-header format.
        """
        # pylint: disable=import-outside-toplevel
        from reme.utils import render_expansion_lines

        answer_lines: list[str] = []
        for r in results:
            path = r.get("path", "")
            start_line = r.get("start_line", 0)
            end_line = r.get("end_line", 0)
            score = ReMeLightMemoryManager._extract_score(r)
            scores = r.get("scores", {})
            text = r.get("text", "")

            score_str = ReMeLightMemoryManager._format_scores_for_header(
                score,
                scores,
            )
            header = (
                f"========== {path}:{start_line}-{end_line} "
                f"[{score_str}] =========="
            )
            answer_lines.append(f"{header}\n{text}")

            # Add link expansions for this path
            expansion = link_expansion.get(path, {})
            if expansion:
                answer_lines.extend(render_expansion_lines(expansion))

        return "\n".join(answer_lines)

    @staticmethod
    def _parse_answer_into_sections(answer: str) -> dict[str, str]:
        """Parse ReMe search answer into sections keyed by ``path:line-line``.

        Each section starts with a header line like::

            ========== path:line-line [scores] ==========

        and includes everything up to the next such header (or end of string).

        Uses line-by-line iteration (not regex) so it's tolerant of format
        variations inside the score brackets — only the ``==========``
        prefix matters.  Returns an empty dict when the answer has no
        ``==========`` lines at all.
        """
        sections: dict[str, str] = {}
        current_key: str | None = None
        current_lines: list[str] = []

        for line in answer.split("\n"):
            if line.startswith("=========="):
                if current_key is not None:
                    sections[current_key] = "\n".join(current_lines)
                # Extract key: the substring before the first ``[`` bracket,
                # which separates the ``path:line-line`` key from the scores.
                rest = line.removeprefix("==========").strip()
                bracket_idx = rest.find("[")
                if bracket_idx > 0:
                    current_key = rest[:bracket_idx].strip()
                else:
                    current_key = rest.split()[0] if rest else None
                current_lines = [line]
            elif current_key is not None:
                current_lines.append(line)

        if current_key is not None:
            sections[current_key] = "\n".join(current_lines)

        return sections

    @staticmethod
    def _reconstruct_answer_from_sections(
        sections: dict[str, str],
        results: list[dict],
    ) -> str:
        """Reconstruct search answer from pre-parsed sections in result order.

        Each result's ``path:start_line-end_line`` key is looked up in the
        *sections* dict.  If a matching section is found, it is used verbatim
        (preserving link expansions, hybrid score details, etc.).  If not
        found, a fallback section is built from the result dict fields.
        """
        lines: list[str] = []
        for r in results:
            path = r.get("path", "")
            start_line = r.get("start_line", 0)
            end_line = r.get("end_line", 0)
            key = f"{path}:{start_line}-{end_line}"
            section = sections.get(key)
            if section is not None:
                lines.append(section)
            else:
                # Fallback — should not happen in normal operation.
                # Use the shared score formatter for consistency with
                # ``_rebuild_search_answer_with_expansions``.
                text = r.get("text", "")
                score = ReMeLightMemoryManager._extract_score(r)
                scores = r.get("scores", {})
                score_str = ReMeLightMemoryManager._format_scores_for_header(
                    score,
                    scores,
                )
                header = f"========== {key} [{score_str}] =========="
                lines.append(f"{header}\n{text}")
        return "\n".join(lines)

    async def _get_reranker_config(self) -> RerankerConfig | None:
        """Return the reranker config, or None if not enabled.

        Config is read fresh on every call — ``load_agent_config()``
        already provides its own mtime-based caching, so an additional
        layer here would risk stale values (the user may change the
        API key, base URL, model, or disable reranking without restarting
        the agent process).
        """
        try:
            agent_cfg = await load_agent_config_async(self.agent_id)
            cfg = getattr(
                agent_cfg.running.reme_light_memory_config,
                "reranker_config",
                None,
            )
            if cfg is not None and cfg.enabled and cfg.model_name:
                return cfg
        except Exception:
            logger.warning("[rerank] failed to load config", exc_info=True)

        return None

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

    async def reme_status(self) -> "Response | None":
        """Return embedded ReMe component memory estimates and process RSS."""
        return await self._run_reme_job("status")

    async def graph_snapshot(self) -> "Response | None":
        """Return the complete indexed wikilink graph for the console."""
        return await self._run_reme_job("graph_snapshot")

    async def rebuild_index(self) -> "Response | None":
        """Clear and rebuild the ReMe search index on explicit request."""
        if self.is_reindexing:
            raise RuntimeError("Memory index rebuild is already running")
        async with self._reindex_lock:
            async with self._exclusive_reme_lifecycle("reindex"):
                reindex_fingerprint = (
                    embedding_vector_space_fingerprint(
                        self._active_embedding_config,
                    )
                    if self._active_embedding_config is not None
                    else None
                )
                response = await self._run_reme_job(
                    "reindex",
                    lifecycle_locked=True,
                )
            if response is not None and response.success:

                def clear_requirement(
                    agent_config: AgentProfileConfig,
                ) -> None:
                    memory_config = (
                        agent_config.running.reme_light_memory_config
                    )
                    persisted_fingerprint = embedding_vector_space_fingerprint(
                        memory_config.embedding_model_config,
                    )
                    active_fingerprint = (
                        embedding_vector_space_fingerprint(
                            self._active_embedding_config,
                        )
                        if self._active_embedding_config is not None
                        else None
                    )
                    if (
                        persisted_fingerprint == reindex_fingerprint
                        and active_fingerprint == reindex_fingerprint
                    ):
                        memory_config.needs_reindex = False

                await update_agent_config_async(
                    self.agent_id,
                    clear_requirement,
                )
        return response

    @property
    def is_reindexing(self) -> bool:
        """Whether an explicit index rebuild is active."""
        return self._reindex_lock.locked()
