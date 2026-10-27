# -*- coding: utf-8 -*-
"""ReMe proposals with host-owned models, archives, and atomic commit."""
# pylint: disable=protected-access

from copy import deepcopy
import asyncio
import logging

from agentscope.message import Msg

from ...constant import (
    QWENPAW_MESSAGE_TAG_KEY,
    SYNTHETIC_USER_MESSAGE_TAGS,
)
from ...utils.io_utils import run_async_to_completion
from ..model_factory import create_decision_model_async
from . import _as_internals as as_internals
from .types import DECISION_COMPACTED, DecisionCompactionResult

logger = logging.getLogger(__name__)


class DecisionCompactor:
    """One lazy decision client per agent; independent of long-term memory."""

    def __init__(self):
        self._component = None
        self._model = None

    async def close(self):
        """ReMe drains borrowed calls before QwenPaw releases its client."""
        await run_async_to_completion(self._close())

    async def _close(self):
        if self._component is not None:
            await self._component.close()
        if self._model is not None:
            await self._model.client.aclose()
        self._model = self._component = None

    async def _decision_component(self, agent):
        if self._component is None:
            from reme.components.as_decision_model import (
                AgentScopeAsDecisionModel,
            )

            component = AgentScopeAsDecisionModel()
            model = await create_decision_model_async(agent._agent_config)
            component.model = model
            self._model, self._component = model, component
        return self._component

    async def compact(
        self,
        agent,
        *,
        tokens: int,
        source_refs: dict[str, str] | None = None,
    ) -> DecisionCompactionResult:
        """Commit only validated output previews with a smaller real input.

        Scroll supplies durable recall references. Native mode archives each
        eligible result through its offloader. Every error leaves the current
        context intact and allows the original compression pipeline to run.
        The caller serializes access to the agent context and decides whether
        the committed token count meets its budget or needs more compression.
        """
        context_config = agent._agent_config.running.light_context_config
        cfg = context_config.decision_compact_config
        try:
            async with asyncio.timeout(cfg.total_timeout_seconds):
                return await self._compact(
                    agent,
                    cfg,
                    tokens,
                    source_refs,
                )
        except Exception:
            logger.warning(
                "Decision model compaction failed; using normal compaction",
                exc_info=True,
            )
            return DecisionCompactionResult(changed=False, tokens_after=tokens)

    async def _compact(
        self,
        agent,
        cfg,
        tokens: int,
        source_refs,
    ) -> DecisionCompactionResult:
        from reme.schema.compaction import CompactionRequest, CompactionResult
        from reme.steps.compaction import CompactContextStep, collect_pairs

        unchanged = DecisionCompactionResult(
            changed=False,
            tokens_after=tokens,
        )
        original = agent.state.context
        snapshot = [msg.model_dump(mode="json") for msg in original]
        # Protect the complete active turn as well as ReMe's recent window.
        active_start = next(
            (
                i
                for i in range(len(snapshot) - 1, -1, -1)
                if snapshot[i]["role"] == "user"
                and snapshot[i]
                .get("metadata", {})
                .get(QWENPAW_MESSAGE_TAG_KEY)
                not in SYNTHETIC_USER_MESSAGE_TAGS
            ),
            0,
        )
        protected = [msg["id"] for msg in snapshot[active_start:]]
        results = [
            block
            for message in snapshot
            for block in message["content"]
            if block["type"] == "tool_result"
        ]
        # Native mode uses temporary refs to discover safe pairs locally;
        # replace them with durable archive refs before calling ReMe.
        refs = (
            dict(source_refs)
            if source_refs is not None
            else dict.fromkeys((block["id"] for block in results), "pending")
        )
        options = cfg.model_dump(exclude={"enabled"})
        request = CompactionRequest(
            messages=snapshot,
            protected_message_ids=protected,
            protected_call_ids=[
                block["id"]
                for block in results
                if block.get("metadata", {}).get(DECISION_COMPACTED)
            ],
            source_refs=refs,
            eligible_tool_names=sorted({block["name"] for block in results}),
            options=options,
        )
        pairs = {
            pair.call_id: pair
            for pair in collect_pairs(request)
            if not pair.protected
        }
        if source_refs is None and pairs:
            request.source_refs = await self._archive_native(
                agent,
                pairs.values(),
                original,
            )
            pairs = {
                key: pair
                for key, pair in pairs.items()
                if key in request.source_refs
            }
        if not pairs:
            return unchanged
        request.goal = "\n".join(
            b.get("text", "")
            for m in snapshot[active_start:]
            for b in m["content"]
            if b["type"] == "text"
        )
        component = await self._decision_component(agent)
        response = await CompactContextStep(as_decision_model=component)(
            **request.model_dump(mode="json"),
        )
        if not response.success:
            return unchanged
        result = CompactionResult.model_validate(response.answer)
        if not result.changed:
            return unchanged
        candidate, changed_ids = self._validated_candidate(
            request,
            pairs,
            result,
            cfg,
        )
        if [
            msg.model_dump(mode="json") for msg in agent.state.context
        ] != snapshot:
            return unchanged
        # Count the exact formatter input, including system prompt and tools.
        # Roll back on failures/cancellation, before any subsequent await.
        agent.state.context = candidate
        committed = False
        try:
            kwargs = await as_internals.prepare_model_input(agent)
            after = await as_internals.count_model_input_tokens(
                agent,
                kwargs,
            )
            if after >= tokens:
                return unchanged
            agent._decision_compaction_revision = (
                getattr(agent, "_decision_compaction_revision", 0) + 1
            )
            committed = True
        finally:
            if not committed and agent.state.context is candidate:
                agent.state.context = original
        logger.info(
            "Decision model compacted %d tool results: %d -> %d input tokens",
            len(changed_ids),
            tokens,
            after,
        )
        return DecisionCompactionResult(changed=True, tokens_after=after)

    @staticmethod
    async def _archive_native(agent, pairs, original):
        """Archive safe candidate outputs before making them eligible."""
        offloader = getattr(agent, "offloader", None)
        if offloader is None:
            return {}
        refs = {}
        for pair in pairs:
            mi, bi = pair.result_location
            path = await offloader.offload_tool_result(
                agent._model_session_id,
                original[mi].content[bi],
                deduplicate=True,
            )
            if path:
                refs[pair.call_id] = f"read_file(file_path={str(path)!r})"
        return refs

    @staticmethod
    def _validated_candidate(request, pairs, result, cfg):
        """Compare the entire proposal with permitted output previews."""
        from reme.steps.compaction import preview_result

        refs = request.source_refs
        expected = deepcopy(request.messages)
        changed_ids = set()
        for decision in result.decisions:
            if decision.action != "preview":
                continue
            pair = pairs.get(decision.call_id)
            if pair is None or decision.source_ref != refs[pair.call_id]:
                raise ValueError("Invalid decision model source reference")
            if (
                decision.probability is None
                or decision.probability > cfg.drop_threshold
            ):
                raise ValueError("Invalid decision model preview decision")
            mi, bi = pair.result_location
            block = expected[mi]["content"][bi]
            replacement = preview_result(
                block,
                refs[pair.call_id],
                cfg.preview_chars,
            )
            if replacement is None or pair.call_id in changed_ids:
                raise ValueError("Invalid or duplicate decision model preview")
            block["output"] = replacement
            changed_ids.add(pair.call_id)
        if not changed_ids or expected != result.messages:
            raise ValueError(
                "Decision model proposal changed protected content",
            )
        candidate = [Msg.model_validate(msg) for msg in expected]
        for msg in candidate:
            for block in msg.content:
                if block.type == "tool_result" and block.id in changed_ids:
                    block.metadata[DECISION_COMPACTED] = True
        return candidate, changed_ids
