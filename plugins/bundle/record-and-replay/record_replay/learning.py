# -*- coding: utf-8 -*-
"""Learn application service for turning recording evidence into a Skill."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from qwenpaw.agents.skill_system import SkillService
from qwenpaw.agents.skill_system.store import render_skill_md, validate_skill_content
from qwenpaw.utils.io_utils import run_sync_io
from .errors import (
    RecordingConsentError,
    RecordingDraftError,
    RecordingLearnError,
)
from .learn_models import (
    LearnCaptureContract,
    LearnEvidenceEnvelope,
    LearnEvidenceEvent,
    LearnEvidenceLocator,
    LearnEvidencePreview,
    LearnIntegritySummary,
    LearnIntentContext,
    LearnModelTarget,
    MaterializedSkill,
    RecordingReview,
    ReviewedSkillDraft,
    StructuredSkillDraft,
)
from .models import RecordingEvent, RecordingState, utc_now
from .session_store import RecordingStore

logger = logging.getLogger(__name__)

_CONSENT_TTL = timedelta(minutes=10)
_DRAFT_TTL = timedelta(hours=1)
_MAX_SELECTED_EVENTS = 2000
_MAX_EVIDENCE_EVENTS = 256
_EVENT_PAGE_SIZE = 500
_MODEL_TIMEOUT_SECONDS = 45.0
_MODEL_MAX_TOKENS = 1800
_SUPPORTED_TYPES = frozenset({"click", "drag", "scroll", "key_down", "key_up"})
_FIELD_SCOPE = (
    "learn_evidence_schema_version",
    "recording_id",
    "capture_contract.*",
    "event.type",
    "event.source_sequences",
    "app.bundle_id",
    "app.name",
    "window.role",
    "target.role",
    "target.subrole",
    "target.identifier",
    "target.name",
    "input.action_metadata_without_absolute_coordinates",
    "redaction.redacted",
    "intent.goal",
    "intent.confirmed_context",
    "integrity.counts",
)


DraftGenerator = Callable[
    [str, LearnModelTarget, LearnEvidenceEnvelope],
    Awaitable[StructuredSkillDraft],
]
ModelTargetResolver = Callable[[str], LearnModelTarget]


@dataclass(frozen=True)
class _ConsentGrant:
    token: UUID
    workspace_dir: Path
    agent_id: str
    target: LearnModelTarget
    envelope: LearnEvidenceEnvelope
    envelope_digest: str
    expires_at: datetime


@dataclass(frozen=True)
class _DraftGrant:
    workspace_dir: Path
    agent_id: str
    artifact: ReviewedSkillDraft
    expires_at: datetime


def _clean_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def _locator(event: RecordingEvent) -> LearnEvidenceLocator:
    app = event.app or {}
    window = event.window or {}
    target = event.target or {}
    return LearnEvidenceLocator(
        bundle_id=_clean_text(app.get("bundle_id")),
        app_name=_clean_text(app.get("name")),
        window_role=_clean_text(window.get("role")),
        role=_clean_text(target.get("role")),
        subrole=_clean_text(target.get("subrole")),
        identifier=_clean_text(target.get("identifier")),
        name=_clean_text(target.get("name")),
    )


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return round(float(value), 3)


def _semantic_event(  # pylint: disable=too-many-branches
    event: RecordingEvent,
) -> dict[str, Any] | None:
    if event.type not in _SUPPORTED_TYPES:
        return None
    event_input = event.input
    action: dict[str, object] = {}
    if event.type == "click":
        semantic_type = "activate"
        for key in ("button", "click_count", "duration_ms"):
            if key in event_input:
                action[key] = event_input[key]
    elif event.type == "drag":
        semantic_type = "drag"
        start_x = _number(event_input.get("start_x"))
        start_y = _number(event_input.get("start_y"))
        end_x = _number(event_input.get("x"))
        end_y = _number(event_input.get("y"))
        if start_x is not None and end_x is not None:
            action["delta_x"] = round(end_x - start_x, 3)
        if start_y is not None and end_y is not None:
            action["delta_y"] = round(end_y - start_y, 3)
        for key in ("button", "duration_ms", "sample_count"):
            if key in event_input:
                action[key] = event_input[key]
    elif event.type == "scroll":
        semantic_type = "scroll"
        for key in ("delta_x", "delta_y"):
            value = _number(event_input.get(key))
            if value is not None:
                action[key] = value
    else:
        semantic_type = "redacted_input"
        action["key_events"] = 1
        if event.type == "key_down":
            action["key_down_events"] = 1
        modifiers = event_input.get("modifiers")
        if isinstance(modifiers, list):
            action["modifiers"] = sorted(
                {str(item) for item in modifiers if str(item)},
            )
        key_class = _clean_text(event_input.get("key_class"))
        if key_class is not None:
            action["key_classes"] = [key_class]
    return {
        "source_sequences": [event.seq],
        "type": semantic_type,
        "locator": _locator(event),
        "action": action,
        "redacted": bool(event.redaction.get("redacted")),
        "last_monotonic_ms": event.t_monotonic_ms,
    }


def _mergeable(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    if previous["type"] not in {"scroll", "redacted_input"}:
        return False
    return (
        previous["type"] == current["type"]
        and previous["locator"] == current["locator"]
        and current["last_monotonic_ms"] - previous["last_monotonic_ms"]
        <= 1500
    )


def _merge_group(previous: dict[str, Any], current: dict[str, Any]) -> None:
    previous["source_sequences"].extend(current["source_sequences"])
    previous["last_monotonic_ms"] = current["last_monotonic_ms"]
    previous["redacted"] = previous["redacted"] or current["redacted"]
    if previous["type"] == "scroll":
        for key in ("delta_x", "delta_y"):
            total = _number(previous["action"].get(key)) or 0.0
            addition = _number(current["action"].get(key)) or 0.0
            previous["action"][key] = round(total + addition, 3)
        previous["action"]["sample_count"] = len(
            previous["source_sequences"],
        )
        return
    previous["action"]["key_events"] = int(
        previous["action"].get("key_events", 0),
    ) + int(current["action"].get("key_events", 0))
    previous["action"]["key_down_events"] = int(
        previous["action"].get("key_down_events", 0),
    ) + int(current["action"].get("key_down_events", 0))
    modifiers = set(previous["action"].get("modifiers", []))
    modifiers.update(current["action"].get("modifiers", []))
    if modifiers:
        previous["action"]["modifiers"] = sorted(modifiers)
    key_classes = set(previous["action"].get("key_classes", []))
    key_classes.update(current["action"].get("key_classes", []))
    if key_classes:
        previous["action"]["key_classes"] = sorted(key_classes)


def _compact_events(
    events: Sequence[RecordingEvent],
) -> list[LearnEvidenceEvent]:
    groups: list[dict[str, Any]] = []
    for event in events:
        semantic = _semantic_event(event)
        if semantic is None:
            continue
        if groups and _mergeable(groups[-1], semantic):
            _merge_group(groups[-1], semantic)
        else:
            groups.append(semantic)
    if not groups:
        raise RecordingLearnError("recording_has_no_supported_events")
    if len(groups) > _MAX_EVIDENCE_EVENTS:
        raise RecordingLearnError("evidence_too_large_select_fewer_events")
    return [
        LearnEvidenceEvent(
            evidence_id=f"event-{index:04d}",
            source_sequences=group["source_sequences"],
            type=group["type"],
            locator=group["locator"],
            action=group["action"],
            redacted=group["redacted"],
        )
        for index, group in enumerate(groups, start=1)
    ]


def build_evidence_envelope(  # pylint: disable=too-many-arguments
    *,
    recording_id: UUID,
    persisted_event_count: int,
    dropped_event_count: int,
    events: Sequence[RecordingEvent],
    goal: str,
    confirmed_context: str = "",
) -> LearnEvidenceEnvelope:
    """Minimize and compact selected recording events for bounded Learn."""
    if not events:
        raise RecordingLearnError("recording_has_no_selected_events")
    if len(events) > _MAX_SELECTED_EVENTS:
        raise RecordingLearnError("evidence_too_large_select_fewer_events")

    compacted = _compact_events(events)
    return LearnEvidenceEnvelope(
        recording_id=recording_id,
        capture_contract=LearnCaptureContract(),
        integrity=LearnIntegritySummary(
            persisted_event_count=persisted_event_count,
            selected_event_count=len(events),
            evidence_event_count=len(compacted),
            dropped_event_count=dropped_event_count,
            redacted_event_count=sum(
                1 for event in events if event.redaction.get("redacted")
            ),
        ),
        intent=LearnIntentContext(
            goal=goal,
            confirmed_context=confirmed_context,
        ),
        events=compacted,
    )


def validate_grounded_draft(
    draft: StructuredSkillDraft,
    envelope: LearnEvidenceEnvelope,
) -> None:
    """Reject model decisions that are not grounded and accounted for."""
    if draft.goal != envelope.intent.goal:
        raise RecordingDraftError("draft_goal_changed")
    by_id = {event.evidence_id: event for event in envelope.events}
    ordered_ids = list(by_id)
    used_ids = [step.source_event_id for step in draft.steps]
    ignored_ids = draft.ignored_event_ids
    if len(used_ids) != len(set(used_ids)):
        raise RecordingDraftError("draft_reuses_evidence")
    if len(ignored_ids) != len(set(ignored_ids)):
        raise RecordingDraftError("draft_reuses_ignored_evidence")
    unknown = (set(used_ids) | set(ignored_ids)) - set(by_id)
    if unknown:
        raise RecordingDraftError("draft_references_unknown_evidence")
    if set(used_ids) & set(ignored_ids):
        raise RecordingDraftError("draft_uses_ignored_evidence")
    if set(used_ids) | set(ignored_ids) != set(by_id):
        raise RecordingDraftError("draft_does_not_account_for_all_evidence")
    used_set = set(used_ids)
    ignored_set = set(ignored_ids)
    expected_used_order = [item for item in ordered_ids if item in used_set]
    expected_ignored_order = [
        item for item in ordered_ids if item in ignored_set
    ]
    if used_ids != expected_used_order:
        raise RecordingDraftError("draft_reorders_evidence")
    if ignored_ids != expected_ignored_order:
        raise RecordingDraftError("draft_reorders_ignored_evidence")

    for step in draft.steps:
        event = by_id[step.source_event_id]
        expected_action = (
            "request-input" if event.type == "redacted_input" else event.type
        )
        if step.action != expected_action:
            raise RecordingDraftError("draft_action_not_grounded")
        if step.locator != event.locator:
            raise RecordingDraftError("draft_locator_not_grounded")


def _markdown_text(value: str) -> str:
    return " ".join(value.replace("`", "'").split())


def render_reviewed_skill(draft: StructuredSkillDraft) -> str:
    """Render validated structured data into a small, reviewable SKILL.md."""
    lines = ["# Outcome", "", _markdown_text(draft.goal), ""]
    if draft.inputs:
        lines.extend(["## Inputs", ""])
        for item in draft.inputs:
            requirement = "required" if item.required else "optional"
            lines.append(
                f"- `{item.name}` ({requirement}): "
                f"{_markdown_text(item.description)}",
            )
        lines.append("")

    lines.extend(["## Workflow", ""])
    for index, step in enumerate(draft.steps, start=1):
        lines.append(f"{index}. {_markdown_text(step.instruction)}")
        target = step.locator
        locator_parts = [
            value
            for value in (
                target.bundle_id,
                target.role,
                target.identifier,
                target.name,
            )
            if value
        ]
        if locator_parts:
            rendered = " / ".join(
                f"`{_markdown_text(value)}`" for value in locator_parts
            )
            lines.append(f"   - Stable target evidence: {rendered}.")
        lines.append(
            f"   - Verify: {_markdown_text(step.verification)}",
        )
    lines.extend(
        [
            "",
            "## Execution policy",
            "",
            "- Prefer a connector or dedicated API for stable semantic "
            "operations when one is available.",
            "- Use Browser automation for stable web controls and Computer "
            "Use for unsupported desktop UI or visual verification.",
            "- Resolve controls from the current interface. Recorded "
            "coordinates are not replay instructions.",
            "- Stop and ask the user if a required input, target, or "
            "verification result is ambiguous.",
        ],
    )
    return render_skill_md(
        proposed_name=draft.name,
        description=draft.description,
        body="\n".join(lines),
    )


def _envelope_digest(envelope: LearnEvidenceEnvelope) -> str:
    payload = json.dumps(
        envelope.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def resolve_model_target(agent_id: str) -> LearnModelTarget:
    """Resolve the exact configured provider/model without calling it."""
    # Lazy imports avoid loading provider credentials before Learn is used.
    # pylint: disable=import-outside-toplevel
    from qwenpaw.config.config import load_agent_config
    from qwenpaw.providers import ProviderManager

    # pylint: enable=import-outside-toplevel

    agent_config = load_agent_config(agent_id)
    slot = agent_config.active_model
    manager = ProviderManager.get_instance()
    if slot is None or not slot.provider_id or not slot.model:
        slot = manager.get_active_model()
    if slot is None or not slot.provider_id or not slot.model:
        raise RecordingLearnError("learn_model_unavailable")
    provider = manager.get_provider(slot.provider_id)
    if provider is None:
        raise RecordingLearnError("learn_provider_unavailable")
    return LearnModelTarget(
        provider_id=slot.provider_id,
        model=slot.model,
        is_local=bool(provider.is_local),
    )


async def generate_structured_skill_draft(
    agent_id: str,
    target: LearnModelTarget,
    envelope: LearnEvidenceEnvelope,
) -> StructuredSkillDraft:
    """Run one bounded, tool-free Learn call using the approved model."""
    # Keep model/provider imports outside desktop recording startup.
    # pylint: disable=import-outside-toplevel
    from agentscope.message import Msg, TextBlock

    from qwenpaw.agents.model_factory import create_model_and_formatter
    from qwenpaw.config.config import ModelSlotConfig

    # pylint: enable=import-outside-toplevel

    system_text = (
        "Create a reusable Skill draft from the supplied Record & Replay "
        "evidence. Return only the requested structured object. Copy goal "
        "verbatim. Every evidence_id must appear exactly once, either as one "
        "step's source_event_id or in ignored_event_ids. Preserve evidence "
        "order. Copy the locator exactly from each used event and use its "
        "event type as the action, except that redacted_input maps to "
        "request-input. Do not invent UI state, typed content, coordinates, "
        "outcomes, or controls. Make redacted input a Skill "
        "input. Ignore navigation noise unrelated to the user's goal. Prefer "
        "semantic outcomes over replaying incidental UI actions. List every "
        "unresolved ambiguity explicitly."
    )
    messages = [
        Msg(
            name="system",
            role="system",
            content=[TextBlock(type="text", text=system_text)],
        ),
        Msg(
            name="user",
            role="user",
            content=[
                TextBlock(
                    type="text",
                    text=json.dumps(
                        envelope.model_dump(mode="json"),
                        ensure_ascii=False,
                    ),
                ),
            ],
        ),
    ]
    model, _ = create_model_and_formatter(
        agent_id=agent_id,
        model_slot_override=ModelSlotConfig(
            provider_id=target.provider_id,
            model=target.model,
        ),
    )
    try:
        async with asyncio.timeout(_MODEL_TIMEOUT_SECONDS):
            response = await model.generate_structured_output(
                messages,
                StructuredSkillDraft,
                max_tokens=_MODEL_MAX_TOKENS,
                disable_thinking=True,
            )
        return StructuredSkillDraft.model_validate(response.content)
    except TimeoutError as exc:
        raise RecordingLearnError("learn_model_timeout") from exc
    except RecordingLearnError:
        raise
    except Exception as exc:
        logger.warning(
            "Record & Replay Learn model call failed: %s",
            type(exc).__name__,
            exc_info=True,
        )
        raise RecordingLearnError("learn_model_failed") from exc


class DesktopLearningService:
    """Application boundary for consent, bounded Learn, and materialization."""

    def __init__(
        self,
        *,
        target_resolver: ModelTargetResolver = resolve_model_target,
        draft_generator: DraftGenerator = generate_structured_skill_draft,
    ) -> None:
        self._target_resolver = target_resolver
        self._draft_generator = draft_generator
        self._lock = asyncio.Lock()
        self._consents: dict[UUID, _ConsentGrant] = {}
        self._drafts: dict[UUID, _DraftGrant] = {}

    async def review(
        self,
        *,
        workspace_dir: str | Path,
        agent_id: str,
        recording_id: UUID,
    ) -> RecordingReview:
        """Return a coordinate-free local timeline for evidence selection."""
        root = Path(workspace_dir).expanduser().resolve()
        store = RecordingStore(root)
        session = await run_sync_io(store.get, recording_id)
        if session.agent_id != agent_id or session.workspace_id != agent_id:
            raise RecordingLearnError("recording_not_owned_by_agent")
        if session.state is not RecordingState.COMPLETED:
            raise RecordingLearnError("recording_is_not_completed")
        events = await self._read_all_events(store, recording_id)
        return RecordingReview(
            recording_id=recording_id,
            persisted_event_count=session.event_count,
            dropped_event_count=session.dropped_event_count,
            events=_compact_events(events),
        )

    async def prepare(  # pylint: disable=too-many-arguments,too-many-locals
        self,
        *,
        workspace_dir: str | Path,
        agent_id: str,
        recording_id: UUID,
        goal: str,
        confirmed_context: str = "",
        selected_sequences: Sequence[int] | None = None,
    ) -> LearnEvidencePreview:
        """Build evidence locally and issue a short-lived consent challenge."""
        root = Path(workspace_dir).expanduser().resolve()
        store = RecordingStore(root)
        session = await run_sync_io(store.get, recording_id)
        if session.agent_id != agent_id or session.workspace_id != agent_id:
            raise RecordingLearnError("recording_not_owned_by_agent")
        if session.state is not RecordingState.COMPLETED:
            raise RecordingLearnError("recording_is_not_completed")
        events = await self._read_all_events(store, recording_id)
        selected = self._select_events(events, selected_sequences)
        envelope = build_evidence_envelope(
            recording_id=recording_id,
            persisted_event_count=session.event_count,
            dropped_event_count=session.dropped_event_count,
            events=selected,
            goal=goal,
            confirmed_context=confirmed_context,
        )
        target = self._target_resolver(agent_id)
        now = utc_now()
        grant = _ConsentGrant(
            token=uuid4(),
            workspace_dir=root,
            agent_id=agent_id,
            target=target,
            envelope=envelope,
            envelope_digest=_envelope_digest(envelope),
            expires_at=now + _CONSENT_TTL,
        )
        async with self._lock:
            self._remove_expired(now)
            self._consents[grant.token] = grant
        integrity = envelope.integrity
        return LearnEvidencePreview(
            recording_id=recording_id,
            consent_token=grant.token,
            expires_at=grant.expires_at,
            model_target=target,
            external_transfer=not target.is_local,
            persisted_event_count=integrity.persisted_event_count,
            selected_event_count=integrity.selected_event_count,
            evidence_event_count=integrity.evidence_event_count,
            dropped_event_count=integrity.dropped_event_count,
            redacted_event_count=integrity.redacted_event_count,
            field_scope=list(_FIELD_SCOPE),
        )

    async def generate(
        self,
        *,
        workspace_dir: str | Path,
        agent_id: str,
        consent_token: UUID,
    ) -> ReviewedSkillDraft:
        """Consume explicit consent and generate one grounded Skill draft."""
        root = Path(workspace_dir).expanduser().resolve()
        async with self._lock:
            now = utc_now()
            self._remove_expired(now)
            grant = self._consents.pop(consent_token, None)
        if grant is None:
            raise RecordingConsentError("learn_consent_missing_or_expired")
        if grant.workspace_dir != root or grant.agent_id != agent_id:
            raise RecordingConsentError("learn_consent_scope_mismatch")
        if _envelope_digest(grant.envelope) != grant.envelope_digest:
            raise RecordingConsentError("learn_evidence_changed")
        current_target = self._target_resolver(agent_id)
        if current_target != grant.target:
            raise RecordingConsentError("learn_model_target_changed")

        structured = await self._draft_generator(
            agent_id,
            grant.target,
            grant.envelope,
        )
        validate_grounded_draft(structured, grant.envelope)
        by_id = {event.evidence_id: event for event in grant.envelope.events}
        used_sequences = [
            sequence
            for step in structured.steps
            for sequence in by_id[step.source_event_id].source_sequences
        ]
        ignored_sequences = [
            sequence
            for event_id in structured.ignored_event_ids
            for sequence in by_id[event_id].source_sequences
        ]
        artifact = ReviewedSkillDraft(
            draft_id=uuid4(),
            recording_id=grant.envelope.recording_id,
            name=structured.name,
            description=structured.description,
            content=render_reviewed_skill(structured),
            inputs=structured.inputs,
            steps=structured.steps,
            source_sequences=used_sequences,
            ignored_source_sequences=ignored_sequences,
            ambiguities=structured.ambiguities,
            assumptions=structured.assumptions,
            needs_confirmation=bool(structured.ambiguities),
        )
        async with self._lock:
            self._drafts[artifact.draft_id] = _DraftGrant(
                workspace_dir=root,
                agent_id=agent_id,
                artifact=artifact,
                expires_at=utc_now() + _DRAFT_TTL,
            )
        return artifact

    async def materialize(
        self,
        *,
        workspace_dir: str | Path,
        agent_id: str,
        draft_id: UUID,
        name: str,
        content: str,
    ) -> MaterializedSkill:
        """Commit a reviewed draft through the existing SkillService."""
        root = Path(workspace_dir).expanduser().resolve()
        async with self._lock:
            now = utc_now()
            self._remove_expired(now)
            grant = self._drafts.get(draft_id)
        if grant is None:
            raise RecordingDraftError("skill_draft_missing_or_expired")
        if grant.workspace_dir != root or grant.agent_id != agent_id:
            raise RecordingDraftError("skill_draft_scope_mismatch")
        if grant.artifact.needs_confirmation:
            raise RecordingDraftError("skill_draft_has_unresolved_ambiguities")
        try:
            frontmatter_name, _ = validate_skill_content(content)
        except Exception as exc:
            raise RecordingDraftError("skill_content_invalid") from exc
        if frontmatter_name != name:
            raise RecordingDraftError("skill_name_does_not_match_frontmatter")
        try:
            created = await run_sync_io(
                SkillService(root).create_skill,
                name=name,
                content=content,
                enable=True,
                source="agent",
            )
        except RecordingDraftError:
            raise
        except Exception as exc:
            logger.warning(
                "Record & Replay Skill materialization failed: %s",
                type(exc).__name__,
                exc_info=True,
            )
            raise RecordingDraftError("skill_materialization_failed") from exc
        if created is None:
            raise RecordingDraftError("skill_name_conflict")
        async with self._lock:
            self._drafts.pop(draft_id, None)
        return MaterializedSkill(
            name=created,
            enabled=True,
            reload_scheduled=False,
        )

    async def recover_draft(
        self,
        *,
        workspace_dir: str | Path,
        agent_id: str,
        recording_id: UUID,
    ) -> ReviewedSkillDraft | None:
        """Return the newest unexpired draft for one owned recording."""
        root = Path(workspace_dir).expanduser().resolve()
        async with self._lock:
            now = utc_now()
            self._remove_expired(now)
            matches = [
                grant
                for grant in self._drafts.values()
                if grant.workspace_dir == root
                and grant.agent_id == agent_id
                and str(grant.artifact.recording_id) == str(recording_id)
            ]
        if not matches:
            return None
        return max(matches, key=lambda grant: grant.expires_at).artifact

    async def _read_all_events(
        self,
        store: RecordingStore,
        recording_id: UUID,
    ) -> list[RecordingEvent]:
        events: list[RecordingEvent] = []
        offset = 0
        while True:
            page = await run_sync_io(
                store.read_events,
                recording_id,
                offset=offset,
                limit=_EVENT_PAGE_SIZE,
            )
            events.extend(page)
            if len(page) < _EVENT_PAGE_SIZE:
                return events
            offset += len(page)

    @staticmethod
    def _select_events(
        events: list[RecordingEvent],
        selected_sequences: Sequence[int] | None,
    ) -> list[RecordingEvent]:
        if selected_sequences is None:
            return events
        requested = list(selected_sequences)
        if not requested:
            raise RecordingLearnError("recording_has_no_selected_events")
        if requested != sorted(set(requested)):
            raise RecordingLearnError("selected_sequences_not_ordered_unique")
        if len(requested) > _MAX_SELECTED_EVENTS:
            raise RecordingLearnError("evidence_too_large_select_fewer_events")
        by_seq = {event.seq: event for event in events}
        if set(requested) - set(by_seq):
            raise RecordingLearnError("selected_sequence_not_found")
        return [by_seq[sequence] for sequence in requested]

    def _remove_expired(self, now: datetime) -> None:
        self._consents = {
            key: grant
            for key, grant in self._consents.items()
            if grant.expires_at > now
        }
        self._drafts = {
            key: grant
            for key, grant in self._drafts.items()
            if grant.expires_at > now
        }


__all__ = [
    "DesktopLearningService",
    "build_evidence_envelope",
    "generate_structured_skill_draft",
    "render_reviewed_skill",
    "resolve_model_target",
    "validate_grounded_draft",
]
