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
from pathlib import Path
from typing import Any, TYPE_CHECKING

import httpx

from agentscope.message import Msg, TextBlock, ToolResultState
from agentscope.tool import ToolChunk

from .base_memory_manager import BaseMemoryManager, memory_registry
from .prompts import build_memory_guidance_prompt
from .reme_config import get_reme_app_config
from ..agent_types import agent_type_has_knowledge_base, agent_type_to_domain
from ..knowledge.dream import (
    MergeCandidate,
    knowledge_claim_similarity,
    MAX_SYNAPSE_LINKS,
)
from ..knowledge.store import (
    PUBLISHED_BUCKETS,
    knowledge_bucket_choices,
    knowledge_published_path_prefixes,
    knowledge_scope_path_prefixes,
)
from ..model_factory import create_model_and_formatter
from ...app.inbox_store import append_event as append_inbox_event
from ...config import load_config
from ...config.config import (
    load_agent_config,
    AgentProfileConfig,
    RerankerConfig,
)
from ...utils.model_response import consume_model_response

if TYPE_CHECKING:
    from reme import ReMe
    from reme.application import Response

    from ...config.config import ReMeLightMemoryConfig

logger = logging.getLogger(__name__)

os.environ.setdefault("REME_DISABLE_LOGURU", "true")

NO_MEMORY_RESULTS = "(no memory results)"
_INDEX_SYNC_ATTEMPTS = 3
_INDEX_SYNC_RETRY_DELAY = 0.2
# Reranker APIs are short-context; keep path + enough body that test
# steps / procedure details are not cut off at 500 CJK/Latin chars.
_RERANK_TEXT_CHARS = 1500
_NODE_SURVEY_FIELDS = ("bucket", "priority", "requirement_id", "status")
_EXPANSION_HEADER_RE = re.compile(r"^\s+(outlinks|inlinks) \(\d+\):\s*$")
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
        self._knowledge_mount_warning: str | None = None
        # Reranker config is not cached here; load_agent_config() already
        # provides mtime-based caching, so every call reads fresh data.
        logger.info(
            "ReMeLightMemoryManager init: agent_id=%s working_dir=%s",
            agent_id,
            working_dir,
        )

        try:
            from reme import ReMe as ReMeApp  # type: ignore

            agent_config: AgentProfileConfig = load_agent_config(self.agent_id)
            self._ensure_knowledge_mount(agent_config)
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

    def _ensure_knowledge_mount(self, agent_config: AgentProfileConfig) -> None:
        """Remount shared KB for KB-capable agents (idempotent).

        A dangling mount (link present but KB target deleted by a human)
        is captured into ``self._knowledge_mount_warning`` and surfaced to
        the user rather than silently recreating an empty KB.
        """
        if not agent_type_has_knowledge_base(agent_config.agent_type):
            return
        try:
            from ..knowledge.binding import bind_knowledge_base

            before = agent_config.running.reme_light_memory_config.knowledge_base_id
            bound = bind_knowledge_base(agent_config)
            after = agent_config.running.reme_light_memory_config.knowledge_base_id
            if bound and before != after:
                from ...config.config import save_agent_config

                save_agent_config(agent_config.id, agent_config)
        except Exception as exc:
            from ..knowledge.mount import KnowledgeMountError

            if isinstance(exc, KnowledgeMountError):
                self._knowledge_mount_warning = str(exc)
                logger.warning(
                    "Dangling knowledge mount for agent %s: %s",
                    agent_config.id,
                    exc,
                )
                return
            logger.exception(
                "Failed to mount knowledge base for agent %s",
                agent_config.id,
            )

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
        kb_enabled = agent_type_has_knowledge_base(agent_config.agent_type)
        return build_memory_guidance_prompt(
            agent_config.language,
            daily_dir=cfg.daily_dir,
            knowledge_enabled=kb_enabled,
            knowledge_dir=cfg.knowledge_dir_name or "knowledge",
        )

    def get_memory_config(self) -> Any:
        """Return ReMe Light memory configuration."""
        agent_config = load_agent_config(self.agent_id)
        return agent_config.running.reme_light_memory_config

    def _kb_enabled(self) -> bool:
        agent_config = load_agent_config(self.agent_id)
        return agent_type_has_knowledge_base(agent_config.agent_type)

    def list_memory_tools(self):
        """Return memory tool functions to register with the agent toolkit."""
        tools = [self.memory_search]
        if self._kb_enabled():
            tools.append(self.save_to_knowledge)
        return tools

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
        scope: str = "knowledge",
        recall: str = "chunk",
        bucket: str = "",
    ) -> ToolChunk:
        """Search memory files semantically.

        Use this tool before answering questions about prior work,
        decisions, dates, people, preferences, or todos.

        Choose the recall mode by intent, not by habit — they answer
        different questions:

        - ``recall="chunk"`` (default): passage-level snippets with file
          paths and line numbers. Use this to **ground an answer** in the
          actual text — i.e. when you need to quote, paraphrase, or verify
          specific content. This is the right choice for most "what does the
          memory say about X" questions.
        - ``recall="node"``: entity-level results — one row per memory node
          (name + one-line description + path + score, plus bucket /
          priority / requirement_id when present). Use this to
          **survey what knowledge entities exist** about a topic before
          reading any of them, e.g. "what concepts do we have around
          refund?", "list the business entities we've captured". It returns
          no body text; once you know which path matters, open it with
          ``read_file`` (more precise than a second ``recall="chunk"``
          search).

        Rule of thumb: if you'd answer with "here is what it says" →
        ``chunk``; if you'd answer with "here is what we have" → ``node``
        then ``read_file``. When unsure, start with ``chunk``.

        When a reranker is configured and enabled, ``chunk`` recall
        over-fetches (``max_results × candidate_multiplier``), reranks the
        candidates, caps back to ``max_results``, and rebuilds the answer
        text. ``node`` recall bypasses the reranker (entities, not
        passages).

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
            scope (`str`, optional):
                For knowledge-base agents only: ``knowledge`` (default;
                shared KB), ``all`` (private digest/daily + shared KB),
                or ``agent`` (private digest/daily). Ignored for default
                agents. Both recall modes honor scope. Business-analysis
                agents default to ``knowledge`` so digest notes do not
                crowd published nodes.
            recall (`str`, optional):
                ``"chunk"`` (default) for passage-level grounding, or
                ``"node"`` for entity-level survey. See the guidance above.
            bucket (`str`, optional):
                Knowledge-base agents only: narrow shared-KB recall to a
                domain (``business``, ``test``) or a published bucket
                (``business/wiki``, ``test/test_cases``, …). Empty means
                all published knowledge, except business-analysis agents
                default to ``business`` (pass ``all`` to search every
                published domain). Ignored when ``scope="agent"``.

        Returns:
            `ToolResponse`:
                Search results formatted with paths, line numbers, and
                content (``chunk``), or one row per entity with name +
                description (``node``).
        """
        query = query.strip()
        if not query:
            return _tool_chunk("Error: query cannot be empty", ok=False)

        agent_config = load_agent_config(self.agent_id)
        mem_cfg = agent_config.running.reme_light_memory_config
        kb_enabled = agent_type_has_knowledge_base(agent_config.agent_type)
        if not kb_enabled:
            scope = "agent"
            bucket = ""
        else:
            scope, bucket = self._resolve_kb_search_defaults(
                scope=scope,
                bucket=bucket,
                mem_cfg=mem_cfg,
                agent_type=agent_config.agent_type,
            )
            if bucket:
                kd = mem_cfg.knowledge_dir_name or "knowledge"
                if not knowledge_scope_path_prefixes(kd, bucket):
                    choices = ", ".join(knowledge_bucket_choices())
                    return _tool_chunk(
                        f"Error: unknown bucket {bucket!r}. "
                        f"Use one of: {choices}.",
                        ok=False,
                    )

        recall_mode = (recall or "chunk").strip().lower()
        if recall_mode not in ("chunk", "node"):
            recall_mode = "chunk"
        if recall_mode == "node":
            return await self._memory_search_nodes(
                query=query,
                max_results=max_results,
                scope=scope,
                kb_enabled=kb_enabled,
                mem_cfg=mem_cfg,
                bucket=bucket,
            )

        reranker_config = self._get_reranker_config()
        cap = max(1, max_results)

        # Over-fetch when reranker is enabled: take N * multiplier
        # candidates, rerank, then return top-N.
        effective_limit = (
            cap * reranker_config.candidate_multiplier
            if reranker_config
            else cap
        )

        if kb_enabled and scope == "all":
            response = await self._dual_chunk_search(
                query=query,
                cap=cap,
                effective_limit=effective_limit,
                min_score=max(0.0, min_score),
                mem_cfg=mem_cfg,
                reranker_config=reranker_config,
                bucket=bucket,
            )
        else:
            prefixes = self._chunk_search_prefixes(
                scope=scope,
                kb_enabled=kb_enabled,
                mem_cfg=mem_cfg,
                bucket=bucket,
            )
            response = await self._run_chunk_search(
                query=query,
                limit=effective_limit,
                min_score=max(0.0, min_score),
                prefixes=prefixes,
            )
            if response is None:
                return _tool_chunk("ReMe is not started.", ok=False)
            if kb_enabled:
                self._filter_search_response_by_scope(
                    response,
                    scope=scope,
                    knowledge_dir=mem_cfg.knowledge_dir_name or "knowledge",
                    daily_dir=mem_cfg.daily_dir,
                    digest_dir=mem_cfg.digest_dir,
                    tag=False,
                )
            await self._rerank_and_cap_response(
                query,
                response,
                cap,
                reranker_config,
            )

        if response is None:
            return _tool_chunk("ReMe is not started.", ok=False)

        if kb_enabled:
            if agent_type_to_domain(agent_config.agent_type) == "business":
                self._drop_link_expansions(response)
            answer = str(response.answer or "")
            if answer:
                response.answer = self._tag_answer_by_scope(
                    answer,
                    scope=scope,
                    knowledge_dir=mem_cfg.knowledge_dir_name or "knowledge",
                    daily_dir=mem_cfg.daily_dir,
                    digest_dir=mem_cfg.digest_dir,
                )

        answer = str(response.answer or "").strip()
        if not answer:
            answer = NO_MEMORY_RESULTS
        if kb_enabled and scope != "agent" and answer == NO_MEMORY_RESULTS:
            answer = self._with_inbox_empty_hint(answer, mem_cfg)
        return _tool_chunk(answer, ok=response.success)

    def _with_inbox_empty_hint(
        self,
        answer: str,
        mem_cfg: "ReMeLightMemoryConfig",
    ) -> str:
        """Append a pending-_inbox count when published recall is empty.

        ``_inbox`` drafts are excluded from search; an empty hit list can
        still mean knowledge is waiting for review. Failures listing inbox
        must not change the empty-result contract.
        """
        if answer != NO_MEMORY_RESULTS:
            return answer
        kb_id = (getattr(mem_cfg, "knowledge_base_id", None) or "").strip()
        if not kb_id:
            try:
                from ..knowledge.store import resolve_kb_id

                kb_id = resolve_kb_id(
                    agent_id=self.agent_id, knowledge_base_id=None,
                )
            except Exception:
                return answer
        try:
            from ..knowledge.dream import list_inbox_items

            pending = list_inbox_items(kb_id)
        except Exception:
            logger.debug("empty-recall inbox hint failed for kb=%s", kb_id)
            return answer
        count = len(pending)
        if count <= 0:
            return answer
        return (
            f"{answer}\n"
            f"({count} pending _inbox draft(s) are not recalled by default; "
            f"review them in the knowledge-base inbox.)"
        )

    def _resolve_kb_search_defaults(
        self,
        *,
        scope: str,
        bucket: str,
        mem_cfg: "ReMeLightMemoryConfig",
        agent_type: str,
    ) -> tuple[str, str]:
        """Apply KB-agent search defaults that keep published nodes uncrowded.

        Empty ``scope`` falls back to ``knowledge_search_default`` (now
        ``knowledge``). Business-analysis agents with an empty bucket
        default to ``business`` so test artifacts and personal notes do
        not mix into the hit list; pass ``bucket=all`` for every
        published domain. ``scope=agent`` always clears the bucket.
        """
        domain = agent_type_to_domain(agent_type)
        resolved_scope = (
            scope or mem_cfg.knowledge_search_default or "knowledge"
        ).strip().lower()
        if resolved_scope not in ("all", "knowledge", "agent"):
            resolved_scope = "knowledge"
        resolved_bucket = (bucket or "").strip()
        explicit_all_buckets = resolved_bucket.lower() in ("all", "*")
        if explicit_all_buckets:
            resolved_bucket = ""
        if resolved_scope == "agent":
            resolved_bucket = ""
        elif not resolved_bucket and not explicit_all_buckets and domain == "business":
            resolved_bucket = "business"
        return resolved_scope, resolved_bucket

    def _agent_search_prefixes(
        self,
        mem_cfg: "ReMeLightMemoryConfig",
    ) -> list[str]:
        """Path prefixes for this agent's private digest + daily notes."""
        dd = (mem_cfg.digest_dir or "digest").replace("\\", "/").strip("/")
        daily = (mem_cfg.daily_dir or "memory").replace("\\", "/").strip("/")
        prefixes = [dd + "/"]
        if daily and daily != dd:
            prefixes.append(daily + "/")
        return prefixes

    def _chunk_search_prefixes(
        self,
        *,
        scope: str,
        kb_enabled: bool,
        mem_cfg: "ReMeLightMemoryConfig",
        bucket: str = "",
    ) -> list[str] | None:
        """Prefixes for a single-scope chunk search, or None for unfiltered."""
        if not kb_enabled:
            return None
        kd = mem_cfg.knowledge_dir_name or "knowledge"
        if scope == "knowledge":
            return knowledge_scope_path_prefixes(kd, bucket)
        if scope == "agent":
            return self._agent_search_prefixes(mem_cfg)
        return None

    async def _run_chunk_search(
        self,
        *,
        query: str,
        limit: int,
        min_score: float,
        prefixes: list[str] | None,
    ) -> "Response | None":
        kwargs: dict[str, Any] = {
            "query": query,
            "limit": limit,
            "min_score": min_score,
        }
        if prefixes:
            kwargs["search_filter"] = {"prefixes": list(prefixes)}
        return await self._run_reme_job("search", **kwargs)

    @staticmethod
    def _merge_dual_quota(
        knowledge_results: list,
        agent_results: list,
        cap: int,
    ) -> list:
        """Keep both sides of a dual search with a knowledge-floor quota.

        Knowledge gets ``max(ceil(cap/2), min(cap, 2))`` seats when both
        sides have hits — a floor of 2 when ``cap >= 2`` — so digest/daily
        cannot crowd out published KB passages. Leftovers fill from
        whichever side still has results.
        """
        cap = max(1, cap)
        if not knowledge_results:
            return list(agent_results[:cap])
        if not agent_results:
            return list(knowledge_results[:cap])
        k_quota = max((cap + 1) // 2, min(cap, 2))
        a_quota = cap - k_quota
        taken = list(knowledge_results[:k_quota]) + list(agent_results[:a_quota])
        if len(taken) < cap:
            extras = list(knowledge_results[k_quota:]) + list(
                agent_results[a_quota:],
            )
            taken.extend(extras[: cap - len(taken)])
        return taken

    def _combine_search_responses(
        self,
        knowledge_resp: "Response",
        agent_resp: "Response",
        ordered_results: list,
    ) -> "Response":
        """Rebuild ``knowledge_resp`` around ``ordered_results``."""
        sections: dict[str, str] = {}
        for resp in (knowledge_resp, agent_resp):
            answer = str(getattr(resp, "answer", "") or "")
            if answer:
                sections.update(self._parse_answer_into_sections(answer))
        expansions: dict[str, dict] = {}
        for resp in (knowledge_resp, agent_resp):
            meta = getattr(resp, "metadata", None) or {}
            extra = meta.get("link_expansion") or {}
            if isinstance(extra, dict):
                expansions.update(extra)
        knowledge_resp.metadata = knowledge_resp.metadata or {}
        knowledge_resp.metadata["results"] = ordered_results
        knowledge_resp.metadata["link_expansion"] = expansions
        knowledge_resp.success = True
        if sections:
            knowledge_resp.answer = self._reconstruct_answer_from_sections(
                sections, ordered_results,
            )
        else:
            knowledge_resp.answer = self._rebuild_search_answer_with_expansions(
                ordered_results, expansions,
            )
        return knowledge_resp

    async def _dual_chunk_search(
        self,
        *,
        query: str,
        cap: int,
        effective_limit: int,
        min_score: float,
        mem_cfg: "ReMeLightMemoryConfig",
        reranker_config: RerankerConfig | None,
        bucket: str = "",
    ) -> "Response | None":
        """Search published KB and private memory separately, then quota-merge."""
        kd = mem_cfg.knowledge_dir_name or "knowledge"
        k_prefixes = knowledge_scope_path_prefixes(kd, bucket)
        a_prefixes = self._agent_search_prefixes(mem_cfg)
        k_resp, a_resp = await asyncio.gather(
            self._run_chunk_search(
                query=query,
                limit=effective_limit,
                min_score=min_score,
                prefixes=k_prefixes,
            ),
            self._run_chunk_search(
                query=query,
                limit=effective_limit,
                min_score=min_score,
                prefixes=a_prefixes,
            ),
        )
        if k_resp is None and a_resp is None:
            return None

        kd_name = kd
        if k_resp is not None:
            self._filter_search_response_by_scope(
                k_resp,
                scope="knowledge",
                knowledge_dir=kd_name,
                daily_dir=mem_cfg.daily_dir,
                digest_dir=mem_cfg.digest_dir,
                tag=False,
            )
        if a_resp is not None:
            self._filter_search_response_by_scope(
                a_resp,
                scope="agent",
                knowledge_dir=kd_name,
                daily_dir=mem_cfg.daily_dir,
                digest_dir=mem_cfg.digest_dir,
                tag=False,
            )

        if k_resp is None:
            await self._rerank_and_cap_response(
                query, a_resp, cap, reranker_config,
            )
            return a_resp
        if a_resp is None:
            await self._rerank_and_cap_response(
                query, k_resp, cap, reranker_config,
            )
            return k_resp

        # Rerank each side to ``cap`` (not the per-side quota) so
        # ``_merge_dual_quota`` can still fill leftover seats when one
        # side is short.
        await self._rerank_and_cap_response(
            query, k_resp, cap, reranker_config,
        )
        await self._rerank_and_cap_response(
            query, a_resp, cap, reranker_config,
        )
        k_results = list(
            (k_resp.metadata or {}).get("results") or [],
        ) if k_resp.success else []
        a_results = list(
            (a_resp.metadata or {}).get("results") or [],
        ) if a_resp.success else []
        merged = self._merge_dual_quota(k_results, a_results, cap)
        return self._combine_search_responses(k_resp, a_resp, merged)

    def _node_search_prefixes(
        self,
        *,
        scope: str,
        kb_enabled: bool,
        mem_cfg: "ReMeLightMemoryConfig",
        bucket: str = "",
    ) -> list[str]:
        """Map a recall scope to ``node_search`` path prefixes.

        ``node_search`` filters candidates by path prefix; we translate the
        scope into the vault directories it should cover:
        - ``knowledge`` → published KB (optionally narrowed by ``bucket``).
        - ``agent`` → the agent's private digest.
        - ``all`` → both (KB agents) or just digest (default agents).
        """
        kd = mem_cfg.knowledge_dir_name or "knowledge"
        dd = (mem_cfg.digest_dir or "digest").replace("\\", "/").strip("/")
        k_prefixes = knowledge_scope_path_prefixes(kd, bucket)
        if scope == "knowledge" and kb_enabled:
            return k_prefixes
        if scope == "agent":
            return [dd + "/"]
        # all
        if kb_enabled:
            return [dd + "/", *k_prefixes]
        return [dd + "/"]

    async def _memory_search_nodes(
        self,
        *,
        query: str,
        max_results: int,
        scope: str,
        kb_enabled: bool,
        mem_cfg: "ReMeLightMemoryConfig",
        bucket: str = "",
    ) -> ToolChunk:
        """Node-level recall via ReMe ``node_search`` scoped by prefix.

        Returns one row per matching memory entity (name + description +
        path + score), excluding ``_inbox`` drafts. Complements chunk-level
        recall: use it to survey which knowledge entities exist about a
        topic rather than to ground an answer in passage text.
        """
        cap = max(1, max_results)
        kd = (mem_cfg.knowledge_dir_name or "knowledge").replace("\\", "/").strip("/")
        k_prefixes = knowledge_scope_path_prefixes(kd, bucket)
        a_prefixes = [
            (mem_cfg.digest_dir or "digest").replace("\\", "/").strip("/") + "/",
        ]

        if kb_enabled and scope == "all":
            k_hits, a_hits = await asyncio.gather(
                self._node_search_hits(
                    query, limit=max(cap * 8, 40), prefixes=k_prefixes,
                ),
                self._node_search_hits(
                    query, limit=cap, prefixes=a_prefixes,
                ),
            )
            if k_hits is None and a_hits is None:
                return _tool_chunk("ReMe is not started.", ok=False)
            k_hits = self._filter_node_hits(
                k_hits or [], knowledge_dir=kd, mem_cfg=mem_cfg,
            )
            a_hits = self._filter_node_hits(
                a_hits or [], knowledge_dir=kd, mem_cfg=mem_cfg,
            )
            hits = self._merge_dual_quota(k_hits, a_hits, cap)
        else:
            prefixes = self._node_search_prefixes(
                scope=scope,
                kb_enabled=kb_enabled,
                mem_cfg=mem_cfg,
                bucket=bucket,
            )
            # Over-fetch when prefix-filtering knowledge out of a mixed
            # index: ReMe node_search_step filters *after* a bounded
            # candidate pool.
            internal_limit = (
                max(cap * 8, 40) if kb_enabled and scope == "knowledge" else cap
            )
            raw = await self._node_search_hits(
                query, limit=internal_limit, prefixes=prefixes,
            )
            if raw is None:
                return _tool_chunk("ReMe is not started.", ok=False)
            hits = self._filter_node_hits(
                raw, knowledge_dir=kd, mem_cfg=mem_cfg,
            )[:cap]

        if not hits:
            answer = NO_MEMORY_RESULTS
            if kb_enabled and scope != "agent":
                answer = self._with_inbox_empty_hint(answer, mem_cfg)
            return _tool_chunk(answer)
        hits = [self._enrich_node_hit(hit) for hit in hits if isinstance(hit, dict)]
        lines = [
            self._format_node_hit(hit, knowledge_dir=kd, mem_cfg=mem_cfg)
            for hit in hits
        ]
        if any(
            self._path_scope_tag(
                str(hit.get("path") or ""),
                knowledge_dir=kd,
                daily_dir=mem_cfg.daily_dir,
                digest_dir=mem_cfg.digest_dir,
            ) == "knowledge"
            for hit in hits
        ):
            lines.append(
                "To read a node in full, call read_file on its path.",
            )
        answer = "\n".join(line for line in lines if line).strip() or NO_MEMORY_RESULTS
        if kb_enabled and scope != "agent" and answer == NO_MEMORY_RESULTS:
            answer = self._with_inbox_empty_hint(answer, mem_cfg)
        return _tool_chunk(answer, ok=True)

    async def _node_search_hits(
        self,
        query: str,
        *,
        limit: int,
        prefixes: list[str],
    ) -> list | None:
        """Run node_search and return hits, or None if ReMe is down."""
        response = await self._run_reme_job(
            "node_search",
            query=query,
            limit=limit,
            prefixes=prefixes,
        )
        if response is None:
            return None
        if not response.success:
            return []
        hits = response.metadata.get("hits") if response.metadata else None
        return list(hits) if hits else []

    def _filter_node_hits(
        self,
        hits: list,
        *,
        knowledge_dir: str,
        mem_cfg: "ReMeLightMemoryConfig",
    ) -> list[dict]:
        kept: list[dict] = []
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            path = str(hit.get("path") or "").replace("\\", "/").lstrip("./")
            tag = self._path_scope_tag(
                path,
                knowledge_dir=knowledge_dir,
                daily_dir=mem_cfg.daily_dir,
                digest_dir=mem_cfg.digest_dir,
            )
            if tag in ("inbox", "excluded"):
                continue
            kept.append(hit)
        return kept

    def _format_node_hit(
        self,
        hit: dict,
        *,
        knowledge_dir: str,
        mem_cfg: "ReMeLightMemoryConfig",
    ) -> str:
        path = str(hit.get("path") or "").replace("\\", "/").lstrip("./")
        name = str(hit.get("name") or "").strip()
        desc = str(hit.get("description") or "").strip()
        score = hit.get("score")
        score_str = f"{float(score):.4f}" if isinstance(score, (int, float)) else "-"
        tag = self._path_scope_tag(
            path,
            knowledge_dir=knowledge_dir,
            daily_dir=mem_cfg.daily_dir,
            digest_dir=mem_cfg.digest_dir,
        )
        header = f"========== {path} [{score_str}] (source: {tag}) =========="
        lines = [f"name: {name}"]
        if desc:
            lines.append(f"description: {desc}")
        for key in _NODE_SURVEY_FIELDS:
            value = str(hit.get(key) or "").strip().strip('"').strip("'")
            if value:
                lines.append(f"{key}: {value}")
        return f"{header}\n" + "\n".join(lines)

    def _enrich_node_hit(self, hit: dict) -> dict:
        """Fill survey fields from on-disk frontmatter when ReMe omitted them."""
        if any(str(hit.get(key) or "").strip() for key in _NODE_SURVEY_FIELDS):
            return hit
        path = str(hit.get("path") or "").replace("\\", "/").lstrip("./")
        ws = getattr(self, "working_dir", "") or ""
        if not path or not ws:
            return hit
        file_path = Path(ws).expanduser() / path
        try:
            text = file_path.read_text(encoding="utf-8")
        except OSError:
            return hit
        from ..knowledge.dream import _parse_frontmatter

        fm, _body = _parse_frontmatter(text)
        enriched = dict(hit)
        for key in _NODE_SURVEY_FIELDS:
            raw = str(fm.get(key) or "").strip().strip('"').strip("'")
            if raw:
                enriched[key] = raw
        if not str(enriched.get("name") or "").strip():
            name = str(fm.get("name") or "").strip().strip('"').strip("'")
            if name:
                enriched["name"] = name
        return enriched

    def _path_scope_tag(
        self,
        path: str,
        *,
        knowledge_dir: str,
        daily_dir: str,
        digest_dir: str,
    ) -> str:
        """Classify a result path as knowledge or agent (digest/daily)."""
        del daily_dir, digest_dir
        normalized = path.replace("\\", "/").lstrip("./")
        kd = knowledge_dir.replace("\\", "/").strip("/")
        if normalized == kd or normalized.startswith(kd + "/"):
            rest = normalized[len(kd) :].lstrip("/")
            if rest == "_inbox" or rest.startswith("_inbox/"):
                return "inbox"
            if rest == "_audit" or rest.startswith("_audit/"):
                return "excluded"
            if rest.lower() == "kb.md":
                return "excluded"
            return "knowledge"
        if "/_inbox/" in f"/{normalized}/" or normalized.startswith("_inbox/"):
            return "inbox"
        if "/_audit/" in f"/{normalized}/" or normalized.startswith("_audit/"):
            return "excluded"
        return "agent"

    def _filter_search_response_by_scope(
        self,
        response: "Response",
        *,
        scope: str,
        knowledge_dir: str,
        daily_dir: str,
        digest_dir: str,
        tag: bool = False,
    ) -> None:
        """Filter search results by knowledge vs agent scope.

        When ``tag`` is True, also rewrite ``response.answer`` with source
        labels. Prefer tagging *after* rerank/cap so section headers remain
        parseable.
        """
        if not response.success:
            return
        results = response.metadata.get("results") if response.metadata else None
        if results:
            filtered = []
            for item in results:
                path = ""
                if isinstance(item, dict):
                    path = str(item.get("path") or item.get("file") or "")
                else:
                    path = str(getattr(item, "path", "") or "")
                path_tag = self._path_scope_tag(
                    path,
                    knowledge_dir=knowledge_dir,
                    daily_dir=daily_dir,
                    digest_dir=digest_dir,
                )
                if path_tag in ("inbox", "excluded"):
                    continue
                if scope == "knowledge" and path_tag != "knowledge":
                    continue
                if scope == "agent" and path_tag != "agent":
                    continue
                if isinstance(item, dict):
                    item = dict(item)
                    item["_scope_tag"] = path_tag
                filtered.append(item)
            response.metadata["results"] = filtered

        original = str(response.answer or "")
        if not original:
            return
        # Always drop out-of-scope / inbox sections from the answer text.
        response.answer = self._tag_answer_by_scope(
            original,
            scope=scope,
            knowledge_dir=knowledge_dir,
            daily_dir=daily_dir,
            digest_dir=digest_dir,
            add_labels=tag,
        )

    def _tag_answer_by_scope(
        self,
        answer: str,
        *,
        scope: str,
        knowledge_dir: str,
        daily_dir: str,
        digest_dir: str,
        add_labels: bool = True,
    ) -> str:
        """Keep answer sections matching scope; optionally add source labels.

        Labels are inserted *after* the ``==========`` header line so
        ``_parse_answer_into_sections`` still works if called again.
        """
        sections = self._parse_answer_into_sections(answer)
        if not sections:
            return answer
        kept: list[str] = []
        for key, body in sections.items():
            path = key.split(":")[0] if ":" in key else key
            path_tag = self._path_scope_tag(
                path,
                knowledge_dir=knowledge_dir,
                daily_dir=daily_dir,
                digest_dir=digest_dir,
            )
            if path_tag in ("inbox", "excluded"):
                continue
            if scope == "knowledge" and path_tag != "knowledge":
                continue
            if scope == "agent" and path_tag != "agent":
                continue
            lines = body.splitlines()
            if add_labels and lines:
                label = "[knowledge]" if path_tag == "knowledge" else "[digest]"
                if lines[0].startswith("=========="):
                    lines.insert(1, f"source: {label}")
                elif not lines[0].startswith("source:"):
                    lines[0] = f"{label} {lines[0]}"
            kept.append("\n".join(lines) if lines else body)
        return "\n\n".join(kept) if kept else ""

    def _drop_link_expansions(self, response: "Response | None") -> None:
        """Strip ReMe ``expand_links`` neighbor bodies from a search response.

        Neighbor outlinks/inlinks are useful for test-domain traceability
        on an explicit ``memory_search``, but they dominate auto-injected
        context and business chunk recall. Clears ``link_expansion``
        metadata and rebuilds the answer from hit text only.
        """
        if response is None or not getattr(response, "success", False):
            return
        meta = response.metadata if isinstance(response.metadata, dict) else {}
        results = list(meta.get("results") or [])
        meta["link_expansion"] = {}
        response.metadata = meta
        if results and any(
            str(r.get("text") or "").strip()
            for r in results
            if isinstance(r, dict)
        ):
            response.answer = self._rebuild_search_answer_with_expansions(
                results, {},
            )
            return
        answer = str(response.answer or "")
        if not answer:
            return
        stripped = self._strip_expansion_lines(answer)
        if stripped != answer:
            response.answer = stripped

    @staticmethod
    def _strip_expansion_lines(answer: str) -> str:
        """Drop ``outlinks`` / ``inlinks`` blocks from a ReMe search answer."""
        kept: list[str] = []
        skipping = False
        for line in answer.split("\n"):
            if _EXPANSION_HEADER_RE.match(line):
                skipping = True
                continue
            if skipping:
                if line.startswith(" ") or line.startswith("\t"):
                    continue
                skipping = False
            kept.append(line)
        return "\n".join(kept)

    async def save_to_knowledge(
        self,
        title: str,
        content: str,
        bucket: str = "wiki",
        preconditions: str = "",
        steps: list[str] | None = None,
        expected: str = "",
        priority: str = "",
        requirement_id: str = "",
        links: list[str] | None = None,
    ) -> ToolChunk:
        """Explicitly write a published node into the shared knowledge base.

        Only available for knowledge-base-capable agent types. Confidence
        is 1.0. When a published node with the same title already exists,
        the save refines (or corroborates if the content is already in
        the body) instead of skipping. New titles are published as CREATE.

        Test-domain agents pass structured test fields
        (``preconditions``/``steps``/``expected``/``priority``/
        ``requirement_id``) and ``links`` (titles of related KB nodes);
        these are serialized into frontmatter and rendered as body
        sections plus ``[[wikilink]]`` lines so ReMe's ``expand_links``
        surfaces the requirement↔case↔defect traceability graph on recall.
        Business-domain agents leave them empty.

        Args:
            title (`str`): Short node title.
            content (`str`): Markdown body / summary to store.
            bucket (`str`, optional): Domain-namespaced bucket, e.g.
                ``business/wiki``, ``business/procedure``,
                ``test/test_design``, ``test/test_cases``,
                ``test/test_data``, ``test/defects``. Legacy flat
                ``personal``/``procedure``/``wiki`` are accepted and
                normalized to ``business/`` for backward compat.
            preconditions (`str`, optional): Test case preconditions.
            steps (`list[str]`, optional): Ordered test steps.
            expected (`str`, optional): Expected result.
            priority (`str`, optional): P0 / P1 / P2 / P3.
            requirement_id (`str`, optional): Linked requirement id.
            links (`list[str]`, optional): Titles of related KB nodes.
        """
        if not self._kb_enabled():
            return _tool_chunk(
                "save_to_knowledge is only available for knowledge-base agents.",
                ok=False,
            )
        title = (title or "").strip()
        content = (content or "").strip()
        if not title or not content:
            return _tool_chunk(
                "Error: title and content are required.",
                ok=False,
            )
        bucket = (bucket or "").strip().lower()
        # Accept legacy flat buckets and normalize to business/ for
        # backward compat with existing callers.
        legacy_flat = {"personal", "procedure", "wiki"}
        if bucket in legacy_flat:
            bucket = f"business/{bucket}"
        if bucket not in PUBLISHED_BUCKETS:
            # Fall back to a domain-appropriate default rather than a
            # hardcoded business bucket so a test agent that passes a
            # wrong bucket still lands in the test domain.
            domain = agent_type_to_domain(
                load_agent_config(self.agent_id).agent_type,
            )
            bucket = "test/test_cases" if domain.startswith("test") else "business/wiki"

        agent_config = load_agent_config(self.agent_id)
        mem_cfg = agent_config.running.reme_light_memory_config
        kb_id = mem_cfg.knowledge_base_id
        if not kb_id:
            from ..knowledge.store import resolve_kb_id

            kb_id = resolve_kb_id(agent_id=self.agent_id, knowledge_base_id=None)

        from ..knowledge.dream import (
            KnowledgeUnit,
            MergePayload,
            integrate_units,
            structural_merge_body,
            _find_exact_published_node,
            _parse_frontmatter,
            _wikilink_title_index,
            format_wikilink,
            resolve_wikilink_target,
        )
        from ..knowledge.lock import KnowledgeLockTimeout
        from ..knowledge.store import kb_root

        unit = KnowledgeUnit(
            name=title,
            bucket=bucket,
            summary=content,
            confidence=1.0,
            signals=["save_to_knowledge"],
            preconditions=(preconditions or "").strip(),
            steps=list(steps or []),
            expected=(expected or "").strip(),
            priority=(priority or "").strip(),
            requirement_id=(requirement_id or "").strip(),
            links=list(links or []),
        )
        merge_candidates = {}
        merge_payloads = {}
        exact = _find_exact_published_node(
            kb_id, title, preferred_bucket=bucket,
        )
        mount_name = mem_cfg.knowledge_dir_name or "knowledge"
        if exact is not None:
            target = kb_root(kb_id) / exact.path
            try:
                text = target.read_text(encoding="utf-8")
                fm, body = _parse_frontmatter(text)
                title_index = _wikilink_title_index(kb_id)
                formatted_links = [
                    format_wikilink(*resolve_wikilink_target(
                        link,
                        title_index=title_index,
                        knowledge_dir=mount_name,
                    ))
                    for link in unit.links
                ]
                merged = structural_merge_body(
                    body, unit, formatted_links=formatted_links or None,
                )
                merge_candidates[title.lower()] = exact
                merge_payloads[title.lower()] = MergePayload(
                    target_path=target,
                    expected_updated_at=(
                        fm.get("updated_at", "").strip().strip('"')
                    ),
                    merged_body=merged,
                    llm_ok=True,
                )
            except OSError:
                logger.debug(
                    "save_to_knowledge: existing node unreadable %s",
                    target,
                    exc_info=True,
                )
        try:
            written = integrate_units(
                kb_id=kb_id,
                agent_id=self.agent_id,
                units=[unit],
                derived_from=["tool:save_to_knowledge"],
                write_mode=mem_cfg.knowledge_write_mode,
                inbox_enabled=mem_cfg.knowledge_inbox_enabled,
                knowledge_dir=mount_name,
                merge_enabled=True,
                merge_candidates=merge_candidates,
                merge_payloads=merge_payloads,
            )
        except KnowledgeLockTimeout:
            return _tool_chunk(
                "Knowledge base is locked by another writer; try again.",
                ok=False,
            )
        except Exception as exc:
            logger.exception("save_to_knowledge failed")
            return _tool_chunk(f"Failed to save: {exc}", ok=False)

        if not written:
            return _tool_chunk(
                f"No new node written (possible duplicate of {title!r}).",
                ok=True,
            )
        await self._sync_search_index()
        return _tool_chunk(
            f"Saved to knowledge base {kb_id}: {written[0]}",
            ok=True,
        )

    async def _sync_search_index(self) -> None:
        """Apply watched-dir diffs to the ReMe index without wiping it.

        Newly written KB files are invisible to ``memory_search`` until this
        job lands. Retry a few times on a missing/failed response so a
        transient index hiccup does not leave published nodes unsearchable
        until the next watch cycle.
        """
        reme = getattr(self, "_reme", None)
        if reme is None:
            return
        if not getattr(reme, "is_started", True):
            return
        last_error = "unknown"
        for attempt in range(1, _INDEX_SYNC_ATTEMPTS + 1):
            try:
                response = await self._run_reme_job("index_sync")
            except Exception:
                last_error = "raised"
                logger.warning(
                    "knowledge index_sync raised attempt=%s/%s",
                    attempt,
                    _INDEX_SYNC_ATTEMPTS,
                )
                response = None
            if response is not None and getattr(response, "success", False):
                return
            if response is None:
                last_error = "no response"
            else:
                last_error = str(
                    getattr(response, "answer", "") or "success=False",
                )
            if attempt < _INDEX_SYNC_ATTEMPTS:
                logger.warning(
                    "knowledge index_sync failed attempt=%s/%s: %s",
                    attempt,
                    _INDEX_SYNC_ATTEMPTS,
                    last_error,
                )
                await asyncio.sleep(_INDEX_SYNC_RETRY_DELAY * attempt)
        logger.warning(
            "knowledge index_sync failed after %s attempts: %s",
            _INDEX_SYNC_ATTEMPTS,
            last_error,
        )

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
        results = (
            response.metadata.get("results") if response.success else None
        )
        if not results:
            return

        # Save original metadata for fallback reconstruction.
        original_link_expansion = (
            response.metadata.get("link_expansion", {})
            if response.success
            else {}
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

        # Truncate long texts for the reranker call. Keep the path so the
        # model can tell entities apart even when bodies start similarly.
        texts: list[str] = [self._rerank_doc_text(r) for r in results]

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
    def _rerank_doc_text(result: dict) -> str:
        """Build the short document the reranker sees for one hit."""
        path = str(result.get("path") or result.get("file") or "").strip()
        body = str(result.get("text") or "").strip()
        if path and body:
            combined = f"{path}\n{body}"
        else:
            combined = body or path
        if len(combined) <= _RERANK_TEXT_CHARS:
            return combined
        return combined[:_RERANK_TEXT_CHARS]

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
            key = (
                f"{r.get('path', '')}:"
                f"{r.get('start_line', 0)}-{r.get('end_line', 0)}"
            )
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
                header = f"========== {key} " f"[{score_str}] =========="
                lines.append(f"{header}\n{text}")
        return "\n".join(lines)

    def _get_reranker_config(self) -> RerankerConfig | None:
        """Return the reranker config, or None if not enabled.

        Config is read fresh on every call — ``load_agent_config()``
        already provides its own mtime-based caching, so an additional
        layer here would risk stale values (the user may change the
        API key, base URL, model, or disable reranking without restarting
        the agent process).
        """
        try:
            agent_cfg = load_agent_config(self.agent_id)
            cfg = agent_cfg.running.reme_light_memory_config.reranker_config
            if cfg.enabled and cfg.model_name:
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

        cap = max(1, search_cfg.max_results)
        reranker_config = self._get_reranker_config()
        # Over-fetch when reranker is enabled: take N * multiplier
        # candidates, rerank, then return top-N.
        effective_limit = (
            cap * reranker_config.candidate_multiplier
            if reranker_config
            else cap
        )
        kb_enabled = agent_type_has_knowledge_base(agent_config.agent_type)
        if kb_enabled:
            scope, bucket = self._resolve_kb_search_defaults(
                scope="knowledge",
                bucket="",
                mem_cfg=memory_cfg,
                agent_type=agent_config.agent_type,
            )
            if scope == "all":
                response = await self._dual_chunk_search(
                    query=query,
                    cap=cap,
                    effective_limit=effective_limit,
                    min_score=0,
                    mem_cfg=memory_cfg,
                    reranker_config=reranker_config,
                    bucket=bucket,
                )
            else:
                prefixes = self._chunk_search_prefixes(
                    scope=scope,
                    kb_enabled=True,
                    mem_cfg=memory_cfg,
                    bucket=bucket,
                )
                response = await self._run_chunk_search(
                    query=query,
                    limit=effective_limit,
                    min_score=0,
                    prefixes=prefixes,
                )
                if response is None:
                    return None
                self._filter_search_response_by_scope(
                    response,
                    scope=scope,
                    knowledge_dir=memory_cfg.knowledge_dir_name or "knowledge",
                    daily_dir=memory_cfg.daily_dir,
                    digest_dir=memory_cfg.digest_dir,
                    tag=False,
                )
                await self._rerank_and_cap_response(
                    query,
                    response,
                    cap,
                    reranker_config,
                )
        else:
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

        if response is None or not response.success:
            return None

        # Auto-injected context cannot afford neighbor-body noise.
        self._drop_link_expansions(response)

        if kb_enabled:
            answer = str(response.answer or "")
            if answer:
                response.answer = self._tag_answer_by_scope(
                    answer,
                    scope=scope,
                    knowledge_dir=memory_cfg.knowledge_dir_name or "knowledge",
                    daily_dir=memory_cfg.daily_dir,
                    digest_dir=memory_cfg.digest_dir,
                    add_labels=True,
                )

        text = str(response.answer or "").strip()
        if not text:
            return None

        assistant_msg = self._build_auto_memory_search_msg(
            query=query,
            max_results=cap,
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
        """Run one ReMe auto-dream pass, then knowledge dream when enabled."""
        response = await self._run_reme_job(
            "auto_dream",
            needs_llm=True,
            date=str(kwargs.get("date") or ""),
            hint=str(kwargs.get("hint") or ""),
        )
        if response is not None and not response.success:
            raise RuntimeError(str(response.answer))

        await self._maybe_run_knowledge_dream(**kwargs)

    async def _maybe_run_knowledge_dream(self, **kwargs: Any) -> None:
        """Extract private daily notes into the shared knowledge base."""
        agent_config = load_agent_config(self.agent_id)
        if not agent_type_has_knowledge_base(agent_config.agent_type):
            return
        mem_cfg = agent_config.running.reme_light_memory_config
        if not mem_cfg.knowledge_dream_enabled:
            return
        kb_id = mem_cfg.knowledge_base_id
        if not kb_id:
            from ..knowledge.store import resolve_kb_id

            kb_id = resolve_kb_id(
                agent_id=self.agent_id,
                knowledge_base_id=None,
            )

        from agentscope.message import Msg

        from ..knowledge.dream import run_knowledge_dream

        async def _llm_call(prompt: str) -> str:
            await self._update_qwenpaw_model()
            model, _formatter = create_model_and_formatter(self.agent_id)
            messages = [
                Msg(name="system", role="system", content=prompt),
            ]
            return await consume_model_response(model, messages)

        dedup_search = self._build_knowledge_dedup_search(mem_cfg) if mem_cfg.knowledge_dedup_enabled else None
        # Always build the merge/related probe when dedup or merge is on so
        # related_names can enrich wikilinks even if auto-merge is off.
        merge_search = (
            self._build_knowledge_merge_search(mem_cfg)
            if (mem_cfg.knowledge_merge_enabled or mem_cfg.knowledge_dedup_enabled)
            else None
        )
        catalog_search = (
            self._build_knowledge_catalog_search(mem_cfg)
            if (mem_cfg.knowledge_merge_enabled or mem_cfg.knowledge_dedup_enabled)
            else None
        )

        try:
            result = await run_knowledge_dream(
                agent_id=self.agent_id,
                workspace_dir=self.working_dir,
                kb_id=kb_id,
                daily_dir_name=mem_cfg.daily_dir,
                metadata_dir=mem_cfg.metadata_dir,
                language=agent_config.language,
                domain=agent_type_to_domain(agent_config.agent_type),
                scan_days=mem_cfg.knowledge_scan_days,
                max_units=mem_cfg.knowledge_max_units,
                write_mode=mem_cfg.knowledge_write_mode,
                inbox_enabled=mem_cfg.knowledge_inbox_enabled,
                knowledge_dir=mem_cfg.knowledge_dir_name or "knowledge",
                llm_call=_llm_call,
                dedup_search=dedup_search,
                merge_search=merge_search,
                catalog_search=catalog_search,
                merge_enabled=mem_cfg.knowledge_merge_enabled,
                merge_max_updates=mem_cfg.knowledge_merge_max_updates,
            )
            logger.info(
                "knowledge_dream finished agent=%s kb=%s result=%s",
                self.agent_id,
                kb_id,
                result,
            )
            if result.get("written"):
                await self._sync_search_index()
            needs_review = result.get("needs_review_count", 0)
            audit_reports = result.get("audit_reports") or []
            if audit_reports:
                logger.info(
                    "knowledge_dream audit agent=%s kb=%s reports=%d "
                    "needs_review=%d",
                    self.agent_id,
                    kb_id,
                    len(audit_reports),
                    needs_review,
                )
                for report in audit_reports:
                    level = logger.warning if report.get("needs_review") else logger.info
                    level(
                        "knowledge_dream audit report id=%s node=%s mode=%s "
                        "anomalies=%s needs_review=%s",
                        report.get("report_id"),
                        report.get("node_path"),
                        report.get("mode"),
                        ",".join(report.get("anomalies", [])) or "none",
                        report.get("needs_review"),
                    )
                if needs_review:
                    logger.warning(
                        "knowledge_dream: %d merge report(s) need human "
                        "audit in kb=%s (see GET /knowledge-bases/%s/"
                        "audit-reports?needs_review=true)",
                        needs_review,
                        kb_id,
                        kb_id,
                    )
        except Exception:
            logger.exception(
                "knowledge_dream failed agent=%s kb=%s",
                self.agent_id,
                kb_id,
            )

    def _build_knowledge_dedup_search(
        self,
        mem_cfg: "ReMeLightMemoryConfig",
    ) -> "Callable[[str, str], Awaitable[bool]]":
        """Build a semantic-duplicate probe for ``run_knowledge_dream``.

        Returns an async ``(name, summary) -> bool`` that runs the ReMe
        ``node_search`` job scoped to the shared knowledge mount via
        ``prefixes=["knowledge/"]`` (ReMe's node-level recall — one row per
        A new unit is treated as a semantic duplicate when ``node_search``
        recalls an existing published KB node whose alias-aware name
        similarity — lifted by summary/description overlap for near-miss
        titles — is >= ``knowledge_dedup_threshold``.

        Node-level name matching is more precise than the chunk-level
        cosine probe it replaces: it compares whole entities (by title,
        with extract-alias awareness so ``退款政策-补充`` matches
        ``退款政策``) rather than overlapping fragments, so it catches
        "same entity, rephrased/superset name" (e.g. ``客户画像`` vs
        ``客户画像分析``) while avoiding false positives from chunks that
        merely share wording. ``_inbox`` nodes are excluded so unpublished
        drafts never block a publish. The probe is best-effort: any
        ReMe/index failure resolves to False (no dedup), so a temporarily
        unavailable index never blocks publishing.
        """
        knowledge_dir = (mem_cfg.knowledge_dir_name or "knowledge").replace("\\", "/").strip("/")
        knowledge_prefixes = knowledge_published_path_prefixes(knowledge_dir)
        threshold = float(mem_cfg.knowledge_dedup_threshold)

        def _is_duplicate(name: str, hits: list, summary: str = "") -> bool:
            target = (name or "").strip().lower()
            if not target:
                return False
            for hit in hits:
                if not isinstance(hit, dict):
                    continue
                path = str(hit.get("path") or "").replace("\\", "/").lstrip("./")
                if not any(path.startswith(p) for p in knowledge_prefixes):
                    continue
                candidate = str(hit.get("name") or "").strip()
                if not candidate:
                    continue
                ratio = knowledge_claim_similarity(
                    target,
                    candidate,
                    summary,
                    str(hit.get("description") or ""),
                )
                if ratio >= threshold:
                    return True
            return False

        async def _dedup_search(name: str, summary: str) -> bool:
            query = f"{name} {summary}".strip() or name
            if not query:
                return False
            try:
                response = await self._run_reme_job(
                    "node_search",
                    query=query,
                    limit=20,
                    prefixes=knowledge_prefixes,
                )
            except Exception:
                logger.debug(
                    "knowledge dedup node_search failed for %r",
                    name,
                    exc_info=True,
                )
                return False
            if response is None or not response.success:
                return False
            hits = response.metadata.get("hits") if response.metadata else None
            if not hits:
                return False
            try:
                return _is_duplicate(name, hits, summary)
            except Exception:
                logger.debug(
                    "knowledge dedup hit parsing failed for %r",
                    name,
                    exc_info=True,
                )
                return False

        return _dedup_search

    def _build_knowledge_merge_search(
        self,
        mem_cfg: "ReMeLightMemoryConfig",
    ) -> "Callable[[str, str], Awaitable[MergeCandidate | None]]":
        """Build a merge-target + related-link probe for ``run_knowledge_dream``.

        Returns an async ``(name, summary) -> MergeCandidate | None`` that
        runs the same ReMe ``node_search`` as the dedup probe but returns a
        ranked candidate instead of a bool. A candidate is ``is_clear``
        only when its claim similarity (alias-aware name, lifted by
        summary/description overlap) >= ``knowledge_merge_threshold`` AND
        it beats the runner-up by >= ``knowledge_merge_margin`` (or it is
        the only hit). Near-duplicates (similarity >= ``knowledge_dedup_threshold``
        but not a clear merge) return ``is_clear=False`` **with a path**
        so integrate routes them to ``_inbox`` instead of publishing a
        sibling node. Weaker related hits keep an empty path for synapse
        weaving only.

        Non-target hits with name-similarity >= ``knowledge_related_threshold``
        are collected into ``related_names`` so integrate can weave
        ``[[wikilink]]`` associations (ReMe-style synapse) even when the
        top hit is not a same-abstraction merge target.

        The path is returned relative to the KB root (stripping the
        ``knowledge/`` mount prefix) so :func:`integrate_units` can resolve
        it on disk.
        """
        knowledge_dir = (mem_cfg.knowledge_dir_name or "knowledge").replace("\\", "/").strip("/")
        knowledge_prefix = knowledge_dir + "/"
        knowledge_prefixes = knowledge_published_path_prefixes(knowledge_dir)
        threshold = float(mem_cfg.knowledge_merge_threshold)
        margin = float(mem_cfg.knowledge_merge_margin)
        related_threshold = float(
            getattr(mem_cfg, "knowledge_related_threshold", 0.70),
        )
        dedup_threshold = float(
            getattr(mem_cfg, "knowledge_dedup_threshold", 0.78),
        )

        def _rank(name: str, hits: list, summary: str = "") -> MergeCandidate | None:
            target = (name or "").strip().lower()
            if not target:
                return None
            scored: list[tuple[float, str, str]] = []
            for hit in hits:
                if not isinstance(hit, dict):
                    continue
                path = str(hit.get("path") or "").replace("\\", "/").lstrip("./")
                if not any(path.startswith(p) for p in knowledge_prefixes):
                    continue
                candidate = str(hit.get("name") or "").strip()
                if not candidate:
                    continue
                ratio = knowledge_claim_similarity(
                    target,
                    candidate,
                    summary,
                    str(hit.get("description") or ""),
                )
                scored.append((ratio, candidate, path))
            if not scored:
                return None
            scored.sort(key=lambda t: t[0], reverse=True)
            top_ratio, top_name, top_path = scored[0]
            second_ratio = scored[1][0] if len(scored) > 1 else 0.0
            is_clear = (
                top_ratio >= threshold
                and ((top_ratio - second_ratio) >= margin or len(scored) == 1)
            )
            # Related = other hits above related_threshold that are not the
            # same-abstraction target (when clear) / not the unit itself.
            related: list[str] = []
            for ratio, cand_name, _path in scored:
                if ratio < related_threshold:
                    continue
                if cand_name.strip().lower() == target:
                    continue
                if is_clear and cand_name.strip().lower() == top_name.strip().lower():
                    continue
                if cand_name not in related:
                    related.append(cand_name)
                if len(related) >= MAX_SYNAPSE_LINKS:
                    break
            if top_ratio < related_threshold and not is_clear:
                # Nothing useful for merge or synapse.
                return None
            # Strip the knowledge mount prefix so the path is KB-relative.
            rel = top_path
            if rel.startswith(knowledge_prefix):
                rel = rel[len(knowledge_prefix):]
            if top_ratio < threshold:
                if top_ratio >= dedup_threshold:
                    # Near-duplicate: hold for review instead of CREATE.
                    return MergeCandidate(
                        name=top_name,
                        path=rel,
                        ratio=top_ratio,
                        is_clear=False,
                        related_names=related,
                    )
                # Below merge and dedup: synapse weaving only.
                if not related:
                    return None
                return MergeCandidate(
                    name="",
                    path="",
                    ratio=top_ratio,
                    is_clear=False,
                    related_names=related,
                )
            return MergeCandidate(
                name=top_name,
                path=rel,
                ratio=top_ratio,
                is_clear=is_clear,
                related_names=related,
            )

        async def _merge_search(name: str, summary: str) -> MergeCandidate | None:
            query = f"{name} {summary}".strip() or name
            if not query:
                return None
            try:
                response = await self._run_reme_job(
                    "node_search",
                    query=query,
                    limit=20,
                    prefixes=knowledge_prefixes,
                )
            except Exception:
                logger.debug(
                    "knowledge merge node_search failed for %r",
                    name,
                    exc_info=True,
                )
                return None
            if response is None or not response.success:
                return None
            hits = response.metadata.get("hits") if response.metadata else None
            if not hits:
                return None
            try:
                return _rank(name, hits, summary)
            except Exception:
                logger.debug(
                    "knowledge merge hit parsing failed for %r",
                    name,
                    exc_info=True,
                )
                return None

        return _merge_search

    def _build_knowledge_catalog_search(
        self,
        mem_cfg: "ReMeLightMemoryConfig",
    ) -> "Callable[[str], Awaitable[list[tuple[str, str]]]]":
        """Recall published KB titles related to a daily-note query.

        Returns ``(name, bucket)`` rows from ReMe ``node_search`` scoped to
        published prefixes. Used to seed the extract prompt's existing-node
        catalog so ``merge_target`` can point at nodes that are actually
        about today's notes, not the first 80 files on disk. Best-effort:
        index failures yield an empty list and lexical ranking still runs.
        """
        from ..knowledge.dream import _bucket_from_rel

        knowledge_dir = (mem_cfg.knowledge_dir_name or "knowledge").replace(
            "\\", "/",
        ).strip("/")
        knowledge_prefix = knowledge_dir + "/"
        knowledge_prefixes = knowledge_published_path_prefixes(knowledge_dir)

        def _hits_to_entries(hits: list) -> list[tuple[str, str]]:
            out: list[tuple[str, str]] = []
            seen: set[str] = set()
            for hit in hits:
                if not isinstance(hit, dict):
                    continue
                path = str(hit.get("path") or "").replace("\\", "/").lstrip("./")
                if not any(path.startswith(p) for p in knowledge_prefixes):
                    continue
                name = str(hit.get("name") or "").strip()
                if not name:
                    continue
                key = name.lower()
                if key in seen:
                    continue
                seen.add(key)
                rel = (
                    path[len(knowledge_prefix):]
                    if path.startswith(knowledge_prefix)
                    else path
                )
                out.append((name, _bucket_from_rel(rel)))
            return out

        async def _catalog_search(query: str) -> list[tuple[str, str]]:
            q = (query or "").strip()
            if not q:
                return []
            if len(q) > 1200:
                q = q[:1200]
            try:
                response = await self._run_reme_job(
                    "node_search",
                    query=q,
                    limit=20,
                    prefixes=knowledge_prefixes,
                )
            except Exception:
                logger.debug(
                    "knowledge catalog node_search failed",
                    exc_info=True,
                )
                return []
            if response is None or not response.success:
                return []
            hits = response.metadata.get("hits") if response.metadata else None
            if not hits:
                return []
            try:
                return _hits_to_entries(hits)
            except Exception:
                logger.debug(
                    "knowledge catalog hit parsing failed",
                    exc_info=True,
                )
                return []

        return _catalog_search

    def knowledge_mount_warning(self) -> str | None:
        """Return a user-facing dangling-mount warning, if any.

        Populated when the shared knowledge-base directory was removed on
        disk while the agent still references it. ``None`` when the mount
        is healthy (or the agent has no KB).
        """
        return self._knowledge_mount_warning

    async def reme_status(self) -> "Response | None":
        """Return embedded ReMe component memory estimates and process RSS.

        Attaches ``knowledge_mount_warning`` to the response metadata so the
        console can surface a dangling-mount notice to the user.
        """
        response = await self._run_reme_job("status")
        if response is not None and self._knowledge_mount_warning:
            if response.metadata is None:
                response.metadata = {}
            response.metadata["knowledge_mount_warning"] = self._knowledge_mount_warning
        return response

    async def graph_snapshot(self) -> "Response | None":
        """Return the complete indexed wikilink graph for the console."""
        return await self._run_reme_job("graph_snapshot")

    async def rebuild_index(self) -> "Response | None":
        """Clear and rebuild the ReMe search index on explicit request."""
        if self._reindex_lock.locked():
            raise RuntimeError("Memory index rebuild is already running")
        async with self._reindex_lock:
            return await self._run_reme_job("reindex")
