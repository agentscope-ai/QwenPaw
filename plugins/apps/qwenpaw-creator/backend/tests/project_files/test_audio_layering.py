# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Three-layer audio separation: required roles, the narration-voiced
overlap gate, shot placement, and the v8->v9 role migration."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any

import pytest
from pydantic import ValidationError

from services.media_files.local_execution import _timeline_speech_windows
from services.project_files.migrations import migrate_project_document
from services.project_files.models import AudioCreation, Project
from services.project_files.serialization import (
    canonical_json_bytes,
    load_project_json,
)


pytestmark = pytest.mark.unit

_AUDIO_URL = "https://example.com/bgm.mp3"
_AUDIO_CHECKSUM = hashlib.sha256(_AUDIO_URL.encode("utf-8")).hexdigest()


def _project_raw() -> dict[str, Any]:
    raw = Project.new(
        project_id="project-audio",
        name="Audio Project",
        now=datetime(2026, 8, 24, 8, 0, tzinfo=timezone.utc),
    ).model_dump(mode="json")
    raw["assets"] = {
        "source_versions_by_id": {
            "audio-version-1": {
                "version_id": "audio-version-1",
                "logical_asset_id": "logical-audio-1",
                "name": "bgm.mp3",
                "file_id": None,
                "checksum": _AUDIO_CHECKSUM,
                "media_kind": "audio",
                "media_type": "audio/mpeg",
                "duration_seconds": 60,
                "created_at": "2026-08-24T08:00:00Z",
                "metadata": {
                    "publicSourceUrl": _AUDIO_URL,
                    "sourceKind": "remote_url",
                    "checksumKind": "source_url_sha256",
                },
            },
        },
    }
    return raw


def _r2v_element(
    element_id: str,
    *,
    start_tick: int,
    duration_tick: int,
    dialogue: str,
    enabled: bool = True,
) -> dict[str, Any]:
    return {
        "element_id": element_id,
        "label": "R2V",
        "enabled": enabled,
        "span": {"start_tick": start_tick, "duration_tick": duration_tick},
        "location": {
            "coordinate_space": "normalized_canvas",
            "x": 0.5,
            "y": 0.5,
            "width": 1,
            "height": 1,
            "anchor_x": 0.5,
            "anchor_y": 0.5,
            "rotation_degrees": 0,
            "opacity": 1,
        },
        "z_index": 0,
        "creation": {
            "type": "r2v",
            "intent": "剧情",
            "shots": {
                "items": {
                    "shot-1": {
                        "shot_id": "shot-1",
                        "description": "角色开口说话",
                        "camera": "⊙ 静止",
                        "framing": "中景",
                        "dialogue": dialogue,
                        "duration_seconds": duration_tick / 1000,
                    },
                },
                "order": ["shot-1"],
            },
        },
    }


def _two_shot_r2v_element(
    *,
    duration_tick: int = 6_000,
    shot_seconds: tuple[float, float] = (3.0, 3.0),
    dialogues: tuple[str, str] = ("第一镜有台词", ""),
) -> dict[str, Any]:
    element = _r2v_element(
        "r2v-1",
        start_tick=0,
        duration_tick=duration_tick,
        dialogue=dialogues[0],
    )
    shots = element["creation"]["shots"]
    shots["items"]["shot-1"]["duration_seconds"] = shot_seconds[0]
    shots["items"]["shot-2"] = {
        "shot_id": "shot-2",
        "description": "第二镜",
        "camera": "⊙ 静止",
        "framing": "全景",
        "dialogue": dialogues[1],
        "duration_seconds": shot_seconds[1],
    }
    shots["order"] = ["shot-1", "shot-2"]
    return element


def _s2v_element(
    element_id: str,
    *,
    start_tick: int,
    duration_tick: int,
) -> dict[str, Any]:
    element = _r2v_element(
        element_id,
        start_tick=start_tick,
        duration_tick=duration_tick,
        dialogue="",
    )
    element["creation"] = {
        "type": "s2v",
        "intent": "口播",
        "script": "大家好，欢迎收看",
    }
    return element


def _audio_element(
    element_id: str,
    *,
    start_tick: int,
    duration_tick: int,
    role: str | None,
    enabled: bool = True,
    version_id: str = "audio-version-1",
) -> dict[str, Any]:
    creation: dict[str, Any] = {
        "type": "audio",
        "source_asset_version_id": version_id,
    }
    if role is not None:
        creation["role"] = role
    return {
        "element_id": element_id,
        "label": "Audio",
        "enabled": enabled,
        "span": {"start_tick": start_tick, "duration_tick": duration_tick},
        "z_index": 0,
        "creation": creation,
    }


def _with_elements(*elements: dict[str, Any]) -> dict[str, Any]:
    raw = _project_raw()
    raw["timelines"]["items"]["timeline:main"]["elements_by_id"] = {
        element["element_id"]: element for element in elements
    }
    return raw


def test_audio_role_is_a_required_enum_and_fades_default_unset() -> None:
    # The mixing role is a stored fact, never a guessed default.
    with pytest.raises(ValidationError):
        AudioCreation(source_asset_version_id="audio-version-1")
    with pytest.raises(ValidationError):
        AudioCreation(
            source_asset_version_id="audio-version-1",
            role="voiceover",
        )
    # Fades are the agent's creative call; None means "adaptive default
    # at render time" and an explicit value (including 0) is kept.
    creation = AudioCreation(
        source_asset_version_id="audio-version-1",
        role="bgm",
    )
    assert creation.role == "bgm"
    assert creation.fade_in_seconds is None
    assert creation.fade_out_seconds is None
    explicit = AudioCreation(
        source_asset_version_id="audio-version-1",
        role="bgm",
        fade_in_seconds=0.0,
        fade_out_seconds=5.0,
    )
    assert explicit.fade_in_seconds == 0.0
    assert explicit.fade_out_seconds == 5.0


def test_v8_migration_stamps_roles_and_the_result_stays_loadable() -> None:
    """The migration must never emit a document its own validator rejects.

    Pre-role audio becomes narration (the pre-role mixer ducked footage
    under every track) unless it overlaps a natively voiced element or an
    earlier narration — stamping narration there would trip the load-time
    overlap gate (s2v driving voice, or two voices at once) and make the
    project unopenable, so those tracks become sfx instead.
    """

    raw = _with_elements(
        _r2v_element(
            "r2v-1",
            start_tick=0,
            duration_tick=5_000,
            dialogue="我今天去了一个地方",
        ),
        _audio_element(  # first role-less span, no s2v here: narration
            "audio-overlapping",
            start_tick=0,
            duration_tick=8_000,
            role=None,
        ),
        _audio_element(  # overlaps the narration above: sfx
            "audio-clear",
            start_tick=5_000,
            duration_tick=3_000,
            role=None,
        ),
        _audio_element(  # explicit role is authoritative
            "audio-explicit",
            start_tick=0,
            duration_tick=2_000,
            role="bgm",
        ),
    )
    raw["schema_version"] = 8

    migrated = migrate_project_document(raw)

    elements = migrated["timelines"]["items"]["timeline:main"][
        "elements_by_id"
    ]
    assert elements["audio-overlapping"]["creation"]["role"] == "narration"
    assert elements["audio-clear"]["creation"]["role"] == "sfx"
    assert elements["audio-explicit"]["creation"]["role"] == "bgm"
    assert "role" not in elements["r2v-1"]["creation"]
    assert migrated["schema_version"] == 9
    Project.model_validate(migrated)  # loadable, or the migration failed


def test_pre_merge_v9_document_missing_roles_is_repaired_on_load() -> None:
    """Two "schema v9" lineages merged: pr-150's original v9 exported
    documents without ``creation.role`` on audio Elements. They already
    say schema_version=9, so the v8->v9 migration never runs — loading
    must apply the same stamping as an idempotent same-version repair
    instead of failing validation with "role Field required".
    """

    raw = _with_elements(
        _r2v_element(
            "r2v-1",
            start_tick=0,
            duration_tick=5_000,
            dialogue="我今天去了一个地方",
        ),
        _audio_element(  # first role-less span: narration
            "audio-overlapping",
            start_tick=0,
            duration_tick=8_000,
            role=None,
        ),
        _audio_element(  # overlaps the narration above: sfx
            "audio-clear",
            start_tick=5_000,
            duration_tick=3_000,
            role=None,
        ),
        _audio_element(  # explicit role is authoritative
            "audio-explicit",
            start_tick=0,
            duration_tick=2_000,
            role="bgm",
        ),
    )
    assert raw["schema_version"] == 9  # the exact failing import shape

    # The archive-import path parses JSON and calls load_project_document.
    project = load_project_json(json.dumps(raw))

    elements = project.timelines.items["timeline:main"].elements_by_id
    assert elements["audio-overlapping"].creation.role == "narration"
    assert elements["audio-clear"].creation.role == "sfx"
    assert elements["audio-explicit"].creation.role == "bgm"

    # Idempotent: a second pass over the repaired document is a no-op.
    repaired = migrate_project_document(raw)
    assert migrate_project_document(repaired) == repaired


def test_v9_document_with_roles_is_not_altered_by_the_repair() -> None:
    raw = _with_elements(
        _r2v_element(
            "r2v-1",
            start_tick=0,
            duration_tick=5_000,
            dialogue="我今天去了一个地方",
        ),
        _audio_element(
            "audio-bgm",
            start_tick=0,
            duration_tick=8_000,
            role="bgm",
        ),
        _audio_element(
            "audio-narration",
            start_tick=5_000,
            duration_tick=3_000,
            role="narration",
        ),
    )
    assert raw["schema_version"] == 9

    assert migrate_project_document(raw) == raw


def test_legacy_dialogue_rows_do_not_gate_narration() -> None:
    raw = _with_elements(
        _r2v_element(
            "r2v-1",
            start_tick=0,
            duration_tick=5_000,
            dialogue="我今天去了一个地方",
        ),
        _audio_element(
            "narration-1",
            start_tick=4_000,
            duration_tick=3_000,
            role="narration",
        ),
    )
    Project.model_validate(raw)


def test_gate_accepts_non_conflicting_audio_layouts() -> None:
    # Narration clear of the voiced span.
    Project.model_validate(
        _with_elements(
            _r2v_element(
                "r2v-1",
                start_tick=0,
                duration_tick=5_000,
                dialogue="我今天去了一个地方",
            ),
            _audio_element(
                "narration-1",
                start_tick=5_000,
                duration_tick=3_000,
                role="narration",
            ),
        ),
    )
    # Narration over a dialogue-free clip.
    Project.model_validate(
        _with_elements(
            _r2v_element(
                "r2v-1",
                start_tick=0,
                duration_tick=5_000,
                dialogue="",
            ),
            _audio_element(
                "narration-1",
                start_tick=0,
                duration_tick=5_000,
                role="narration",
            ),
        ),
    )
    # BGM may overlap dialogue: the mixer self-ducks it instead.
    Project.model_validate(
        _with_elements(
            _r2v_element(
                "r2v-1",
                start_tick=0,
                duration_tick=5_000,
                dialogue="我今天去了一个地方",
            ),
            _audio_element(
                "bgm-1",
                start_tick=0,
                duration_tick=8_000,
                role="bgm",
            ),
        ),
    )
    # A disabled voiced element does not gate anything.
    Project.model_validate(
        _with_elements(
            _r2v_element(
                "r2v-1",
                start_tick=0,
                duration_tick=5_000,
                dialogue="我今天去了一个地方",
                enabled=False,
            ),
            _audio_element(
                "narration-1",
                start_tick=0,
                duration_tick=5_000,
                role="narration",
            ),
        ),
    )


def test_narration_may_cover_the_silent_shots_of_an_element() -> None:
    raw = _with_elements(
        _two_shot_r2v_element(),
        _audio_element(
            "narration-1",
            start_tick=3_000,
            duration_tick=3_000,
            role="narration",
        ),
    )
    Project.model_validate(raw)


def test_legacy_shot_timing_does_not_gate_narration() -> None:
    raw = _with_elements(
        _two_shot_r2v_element(),
        _audio_element(
            "narration-1",
            start_tick=2_000,
            duration_tick=2_000,
            role="narration",
        ),
    )
    Project.model_validate(raw)


def test_legacy_durations_do_not_create_speech_windows() -> None:
    """Retired duration/dialogue rows cannot supply real speech timing."""

    drifting = _two_shot_r2v_element(
        duration_tick=10_000,
        shot_seconds=(8.0, 8.0),
        dialogues=("", "后半段才开口"),
    )
    # Neither former interval imposes a narrative-based audio gate.
    raw = _with_elements(
        drifting,
        _audio_element(
            "narration-1",
            start_tick=5_000,
            duration_tick=2_800,
            role="narration",
        ),
    )
    Project.model_validate(raw)
    # No speech windows are invented from the discarded rows.
    raw = _with_elements(
        drifting,
        _audio_element(
            "narration-1",
            start_tick=0,
            duration_tick=4_900,
            role="narration",
        ),
    )
    project = Project.model_validate(raw)
    timeline = project.timelines.items["timeline:main"]
    assert not _timeline_speech_windows(timeline)


def test_s2v_element_gates_narration_over_its_whole_span() -> None:
    raw = _with_elements(
        _s2v_element("s2v-1", start_tick=0, duration_tick=5_000),
        _audio_element(
            "narration-1",
            start_tick=4_000,
            duration_tick=3_000,
            role="narration",
        ),
    )
    with pytest.raises(ValidationError, match="overlaps the voiced"):
        Project.model_validate(raw)


def test_two_overlapping_narration_tracks_are_rejected() -> None:
    """The double-voice defect: re-voicing must rebind, never stack.

    A narration re-synthesized with a new voice over the same span is a
    second voice talking at once; the gate refuses it so the agent has to
    rebind the existing Element (or delete it) instead of adding another.
    """

    raw = _with_elements(
        _audio_element(
            "narration-male",
            start_tick=0,
            duration_tick=5_000,
            role="narration",
        ),
        _audio_element(
            "narration-female",
            start_tick=0,
            duration_tick=5_000,
            role="narration",
        ),
    )
    with pytest.raises(ValidationError, match="two narration tracks"):
        Project.model_validate(raw)


def test_partially_overlapping_narration_is_rejected() -> None:
    raw = _with_elements(
        _audio_element(
            "narration-1",
            start_tick=0,
            duration_tick=5_000,
            role="narration",
        ),
        _audio_element(
            "narration-2",
            start_tick=3_000,
            duration_tick=5_000,
            role="narration",
        ),
    )
    with pytest.raises(ValidationError, match="double voice"):
        Project.model_validate(raw)


def test_adjacent_narration_segments_do_not_conflict() -> None:
    # [0,5000) then [5000,10000): half-open spans touch but never overlap,
    # so per-shot segmented narration stays valid.
    raw = _with_elements(
        _audio_element(
            "narration-1",
            start_tick=0,
            duration_tick=5_000,
            role="narration",
        ),
        _audio_element(
            "narration-2",
            start_tick=5_000,
            duration_tick=5_000,
            role="narration",
        ),
    )
    Project.model_validate(raw)


def test_narration_may_overlap_bgm_and_sfx() -> None:
    # Only narration-vs-narration is a double voice; a music bed and layered
    # effects are meant to run under the narration.
    raw = _with_elements(
        _audio_element(
            "narration-1",
            start_tick=0,
            duration_tick=5_000,
            role="narration",
        ),
        _audio_element(
            "bgm-1",
            start_tick=0,
            duration_tick=8_000,
            role="bgm",
        ),
        _audio_element(
            "sfx-1",
            start_tick=1_000,
            duration_tick=3_000,
            role="sfx",
        ),
    )
    Project.model_validate(raw)


def test_disabled_narration_does_not_gate_overlap() -> None:
    # A disabled duplicate is not a second audible voice; the gate ignores
    # disabled elements exactly as it does for the s2v check.
    raw = _with_elements(
        _audio_element(
            "narration-on",
            start_tick=0,
            duration_tick=5_000,
            role="narration",
        ),
        _audio_element(
            "narration-off",
            start_tick=0,
            duration_tick=5_000,
            role="narration",
            enabled=False,
        ),
    )
    Project.model_validate(raw)


def test_legacy_double_narration_keeps_the_newest_take_not_id_order() -> None:
    """A project saved before the double-voice gate must still OPEN, and the
    repair must keep the take the user actually re-voiced to.

    "Newest" is the source version's ``created_at``, NOT element order: the
    canonical encoder sorts ``elements_by_id`` by id, so the newer take can
    easily sort first. Here the female re-voice (``audio-version-2``, created
    later) has an id that sorts BEFORE the male original, so any
    order-based heuristic would keep the wrong (older male) voice.
    """

    raw = _with_elements(
        _audio_element(  # newer re-voice, but its id sorts first
            "aaa-female",
            start_tick=0,
            duration_tick=5_000,
            role="narration",
            version_id="audio-version-2",
        ),
        _audio_element(  # older original, its id sorts last
            "zzz-male",
            start_tick=0,
            duration_tick=5_000,
            role="narration",
            version_id="audio-version-1",
        ),
    )
    versions = raw["assets"]["source_versions_by_id"]
    versions["audio-version-2"] = {
        **versions["audio-version-1"],
        "version_id": "audio-version-2",
        "logical_asset_id": "logical-audio-2",
        "created_at": "2026-09-01T08:00:00Z",  # the re-voice, synthesized later
    }
    assert raw["schema_version"] == 9

    # Writing the same pair directly is still rejected (no repair on write).
    with pytest.raises(ValidationError, match="two narration tracks"):
        Project.model_validate(raw)

    # Loading repairs it: newest take kept, older take muted.
    project = load_project_json(json.dumps(raw))
    elements = project.timelines.items["timeline:main"].elements_by_id
    assert elements["aaa-female"].enabled is True  # newer created_at
    assert elements["zzz-male"].enabled is False  # older take, muted
    assert elements["zzz-male"].creation.role == "narration"

    # Idempotent: re-running the repair over its own output is a no-op.
    repaired = migrate_project_document(raw)
    assert migrate_project_document(repaired) == repaired


def test_narration_repair_mutes_only_spans_the_latest_take_overlaps() -> None:
    # Muting follows the overlap, not a blanket "one narration per
    # timeline": [0,10) and [12,20) never touch, so both stay enabled; only
    # the middle take [5,15), which the latest [12,20) overlaps, is muted.
    raw = _with_elements(
        _audio_element(
            "narration-a",
            start_tick=0,
            duration_tick=10_000,
            role="narration",
        ),
        _audio_element(
            "narration-b",
            start_tick=5_000,
            duration_tick=10_000,
            role="narration",
        ),
        _audio_element(
            "narration-c",
            start_tick=12_000,
            duration_tick=8_000,
            role="narration",
        ),
    )
    project = load_project_json(json.dumps(raw))
    elements = project.timelines.items["timeline:main"].elements_by_id
    assert elements["narration-a"].enabled is True
    assert elements["narration-b"].enabled is False
    assert elements["narration-c"].enabled is True


def test_roleless_audio_roles_do_not_depend_on_json_key_order() -> None:
    """Stamping role-less legacy audio is serialization-order independent.

    ``elements_by_id`` key order is not part of a document's identity: the
    canonical encoder sorts keys, so two orderings hash to the SAME ETag. But
    the stamping pass accumulates narration spans as it walks, so iterating in
    insertion order would resolve A=[0,5)/B=[4,10) to A=narration/B=sfx in one
    ordering and the opposite in the other -- one ETag, two different mixes.
    The walk is keyed on ``(start_tick, element_id)`` so the earliest voice is
    always the narration.

    Only narration ducks the footage audio (local_execution builds its duck
    windows from narration tracks and mixes sfx verbatim), so a stable role
    also means a stable duck window: [0,5) here, with B's non-overlapping tail
    [5,10) never ducked.
    """

    forward = _with_elements(
        _audio_element(
            "a-track",
            start_tick=0,
            duration_tick=5_000,
            role=None,
        ),
        _audio_element(
            "b-track",
            start_tick=4_000,
            duration_tick=6_000,
            role=None,
        ),
    )
    reversed_keys = _with_elements(
        _audio_element(
            "b-track",
            start_tick=4_000,
            duration_tick=6_000,
            role=None,
        ),
        _audio_element(
            "a-track",
            start_tick=0,
            duration_tick=5_000,
            role=None,
        ),
    )

    # Same content -> identical canonical bytes -> one ETag, whichever order
    # the keys were inserted in.
    assert canonical_json_bytes(forward) == canonical_json_bytes(reversed_keys)

    def roles(raw: dict[str, Any]) -> dict[str, str]:
        project = load_project_json(json.dumps(raw))
        return {
            element_id: element.creation.role
            for element_id, element in project.timelines.items[
                "timeline:main"
            ].elements_by_id.items()
        }

    # The earliest span is the narration and the later overlap is sfx in BOTH
    # key orders, so one ETag now yields exactly one mix.
    assert (
        roles(forward)
        == roles(reversed_keys)
        == {
            "a-track": "narration",
            "b-track": "sfx",
        }
    )
