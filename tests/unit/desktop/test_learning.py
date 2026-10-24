# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from record_replay.errors import RecordingConsentError, RecordingDraftError
from record_replay.learn_models import (
    LearnEvidenceEnvelope,
    LearnModelTarget,
    SkillDraftInput,
    SkillDraftStep,
    StructuredSkillDraft,
)
from record_replay.learning import (
    DesktopLearningService,
    build_evidence_envelope,
    validate_grounded_draft,
)
from record_replay.models import RecordingEvent, RecordingState
from record_replay.session_store import RecordingStore


def _event(
    seq: int,
    event_type: str = "click",
    *,
    t_monotonic_ms: int | None = None,
    event_input: dict[str, Any] | None = None,
    redacted: bool = False,
) -> RecordingEvent:
    return RecordingEvent(
        seq=seq,
        t_monotonic_ms=t_monotonic_ms or seq * 100,
        type=event_type,
        app={"bundle_id": "com.apple.calculator", "name": "Calculator"},
        window={"role": "AXWindow", "title": "Calculator"},
        target={
            "role": "AXButton",
            "identifier": "Nine",
            "name": "9",
            "bounds": [100, 200, 40, 40],
        },
        input=event_input or {"button": "left", "x": 120, "y": 220},
        redaction={"redacted": redacted, "reasons": []},
    )


def _envelope(events: list[RecordingEvent]) -> LearnEvidenceEnvelope:
    return build_evidence_envelope(
        recording_id="12345678-1234-5678-1234-567812345678",
        persisted_event_count=len(events),
        dropped_event_count=0,
        events=events,
        goal="Enter a number in Calculator",
    )


def _valid_draft(envelope: LearnEvidenceEnvelope) -> StructuredSkillDraft:
    steps = [
        SkillDraftStep(
            source_event_id=event.evidence_id,
            action=(
                "request-input"
                if event.type == "redacted_input"
                else event.type
            ),
            locator=event.locator,
            instruction=f"Perform {event.type} in Calculator",
            verification="Confirm Calculator reflects the action",
        )
        for event in envelope.events
    ]
    inputs = (
        [
            SkillDraftInput(
                name="value",
                description="Value to enter in Calculator",
            ),
        ]
        if any(event.type == "redacted_input" for event in envelope.events)
        else []
    )
    return StructuredSkillDraft(
        name="enter-calculator-value",
        description="Enter a requested value in Calculator when asked.",
        goal=envelope.intent.goal,
        inputs=inputs,
        steps=steps,
        ignored_event_ids=[],
        ambiguities=[],
        assumptions=[],
    )


def _completed_recording(workspace: Path) -> tuple[RecordingStore, str]:
    store = RecordingStore(workspace)
    session = store.create(
        workspace_id="default",
        user_id="local-console",
        agent_id="default",
    )
    store.transition(session.recording_id, RecordingState.RECORDING)
    store.append_events(session.recording_id, [_event(1)])
    store.transition(session.recording_id, RecordingState.FINALIZING)
    store.complete(session.recording_id)
    return store, str(session.recording_id)


def test_evidence_builder_compacts_and_removes_coordinates() -> None:
    events = [
        _event(
            1,
            "scroll",
            event_input={"delta_x": 0, "delta_y": -2, "x": 10, "y": 20},
        ),
        _event(
            2,
            "scroll",
            event_input={"delta_x": 0, "delta_y": -3, "x": 11, "y": 21},
        ),
        _event(3),
        _event(
            4,
            "key_down",
            event_input={"key_class": "printable", "length": 1},
            redacted=True,
        ),
        _event(
            5,
            "key_up",
            event_input={"key_class": "printable", "length": 1},
            redacted=True,
        ),
    ]

    envelope = _envelope(events)

    assert [event.type for event in envelope.events] == [
        "scroll",
        "activate",
        "redacted_input",
    ]
    assert envelope.events[0].source_sequences == [1, 2]
    assert envelope.events[0].action == {
        "delta_x": 0.0,
        "delta_y": -5.0,
        "sample_count": 2,
    }
    assert envelope.events[2].source_sequences == [4, 5]
    assert envelope.events[2].action["key_events"] == 2
    assert envelope.events[2].action["key_down_events"] == 1
    serialized = envelope.model_dump(mode="json")
    assert "bounds" not in str(serialized)
    assert "'x':" not in str(serialized)
    assert "'y':" not in str(serialized)
    assert envelope.capture_contract.coordinates_included is False
    assert envelope.capture_contract.keyboard_content_recorded is False
    draft = _valid_draft(envelope)
    validate_grounded_draft(draft, envelope)
    assert draft.steps[-1].action == "request-input"


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ("unknown", "draft_references_unknown_evidence"),
        ("locator", "draft_locator_not_grounded"),
        ("missing", "draft_does_not_account_for_all_evidence"),
        ("reordered", "draft_reorders_evidence"),
    ],
)
def test_grounding_validator_rejects_ungrounded_model_output(
    mutation: str,
    error: str,
) -> None:
    envelope = _envelope([_event(1), _event(2)])
    draft = _valid_draft(envelope).model_dump(mode="json")
    if mutation == "unknown":
        draft["steps"][0]["source_event_id"] = "event-9999"
    elif mutation == "locator":
        draft["steps"][0]["locator"]["identifier"] = "Invented"
    elif mutation == "missing":
        draft["steps"] = draft["steps"][:1]
    elif mutation == "reordered":
        draft["steps"] = list(reversed(draft["steps"]))

    with pytest.raises(RecordingDraftError, match=error):
        validate_grounded_draft(
            StructuredSkillDraft.model_validate(draft),
            envelope,
        )


async def test_prepare_does_not_call_model_and_model_change_revokes_consent(
    tmp_path: Path,
) -> None:
    _, recording_id = _completed_recording(tmp_path)
    target = LearnModelTarget(
        provider_id="provider-a",
        model="model-a",
        is_local=False,
    )
    current = [target]
    called = False

    async def generate(*_args: Any) -> StructuredSkillDraft:
        nonlocal called
        called = True
        raise AssertionError("model must not run during prepare")

    service = DesktopLearningService(
        target_resolver=lambda _agent_id: current[0],
        draft_generator=generate,
    )
    preview = await service.prepare(
        workspace_dir=tmp_path,
        agent_id="default",
        recording_id=recording_id,
        goal="Enter 9 in Calculator",
    )
    assert called is False
    assert preview.external_transfer is True
    assert preview.model_target == target
    assert "learn_evidence_schema_version" in preview.field_scope
    assert "recording_id" in preview.field_scope
    assert "capture_contract.*" in preview.field_scope
    assert "target.identifier" in preview.field_scope

    current[0] = target.model_copy(update={"model": "model-b"})
    with pytest.raises(
        RecordingConsentError,
        match="learn_model_target_changed",
    ):
        await service.generate(
            workspace_dir=tmp_path,
            agent_id="default",
            consent_token=preview.consent_token,
        )
    assert called is False


async def test_generate_materializes_reviewed_skill_transactionally(
    tmp_path: Path,
) -> None:
    _, recording_id = _completed_recording(tmp_path)
    target = LearnModelTarget(
        provider_id="local",
        model="test-model",
        is_local=True,
    )

    async def generate(
        _agent_id: str,
        _target: LearnModelTarget,
        envelope: LearnEvidenceEnvelope,
    ) -> StructuredSkillDraft:
        return _valid_draft(envelope)

    service = DesktopLearningService(
        target_resolver=lambda _agent_id: target,
        draft_generator=generate,
    )
    preview = await service.prepare(
        workspace_dir=tmp_path,
        agent_id="default",
        recording_id=recording_id,
        goal="Enter a number in Calculator",
    )
    draft = await service.generate(
        workspace_dir=tmp_path,
        agent_id="default",
        consent_token=preview.consent_token,
    )

    assert draft.needs_confirmation is False
    assert draft.source_sequences == [1]
    assert "Recorded coordinates are not replay instructions" in draft.content
    assert "name: enter-calculator-value" in draft.content
    assert (
        await service.recover_draft(
            workspace_dir=tmp_path,
            agent_id="default",
            recording_id=recording_id,
        )
        == draft
    )

    result = await service.materialize(
        workspace_dir=tmp_path,
        agent_id="default",
        draft_id=draft.draft_id,
        name=draft.name,
        content=draft.content,
    )
    skill_path = tmp_path / "skills" / result.name / "SKILL.md"
    assert result.created is True
    assert result.enabled is True
    assert skill_path.read_text(encoding="utf-8") == draft.content
    manifest = (tmp_path / "skill.json").read_text(encoding="utf-8")
    assert '"enter-calculator-value"' in manifest
    assert '"enabled": true' in manifest
    assert (
        await service.recover_draft(
            workspace_dir=tmp_path,
            agent_id="default",
            recording_id=recording_id,
        )
        is None
    )

    with pytest.raises(
        RecordingDraftError,
        match="skill_draft_missing_or_expired",
    ):
        await service.materialize(
            workspace_dir=tmp_path,
            agent_id="default",
            draft_id=draft.draft_id,
            name=draft.name,
            content=draft.content,
        )


async def test_unresolved_ambiguity_blocks_materialization(
    tmp_path: Path,
) -> None:
    _, recording_id = _completed_recording(tmp_path)
    target = LearnModelTarget(
        provider_id="local",
        model="test-model",
        is_local=True,
    )

    async def generate(
        _agent_id: str,
        _target: LearnModelTarget,
        envelope: LearnEvidenceEnvelope,
    ) -> StructuredSkillDraft:
        return _valid_draft(envelope).model_copy(
            update={"ambiguities": ["Which value should be reusable?"]},
        )

    service = DesktopLearningService(
        target_resolver=lambda _agent_id: target,
        draft_generator=generate,
    )
    preview = await service.prepare(
        workspace_dir=tmp_path,
        agent_id="default",
        recording_id=recording_id,
        goal="Enter a number in Calculator",
    )
    draft = await service.generate(
        workspace_dir=tmp_path,
        agent_id="default",
        consent_token=preview.consent_token,
    )
    assert draft.needs_confirmation is True

    with pytest.raises(
        RecordingDraftError,
        match="skill_draft_has_unresolved_ambiguities",
    ):
        await service.materialize(
            workspace_dir=tmp_path,
            agent_id="default",
            draft_id=draft.draft_id,
            name=draft.name,
            content=draft.content,
        )
