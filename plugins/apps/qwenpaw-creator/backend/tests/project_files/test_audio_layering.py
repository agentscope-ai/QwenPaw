# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Three-layer audio separation: required roles, the narration-voiced
overlap gate, shot placement, and the v8->v9 role migration."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from typing import Any

import pytest
from pydantic import ValidationError

from services.media_files.local_execution import _timeline_speech_windows
from services.project_files.migrations import migrate_project_document
from services.project_files.models import AudioCreation, Project


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
) -> dict[str, Any]:
    creation: dict[str, Any] = {
        "type": "audio",
        "source_asset_version_id": "audio-version-1",
    }
    if role is not None:
        creation["role"] = role
    return {
        "element_id": element_id,
        "label": "Audio",
        "enabled": True,
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
    under every track) unless it overlaps a natively voiced element —
    stamping narration there would trip the load-time overlap gate and
    make the project unopenable, so those tracks become sfx instead.
    """

    raw = _with_elements(
        _r2v_element(
            "r2v-1",
            start_tick=0,
            duration_tick=5_000,
            dialogue="我今天去了一个地方",
        ),
        _audio_element(  # full-length bed over the dialogue: sfx
            "audio-overlapping",
            start_tick=0,
            duration_tick=8_000,
            role=None,
        ),
        _audio_element(  # clear of the voiced span: narration
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
    assert elements["audio-overlapping"]["creation"]["role"] == "sfx"
    assert elements["audio-clear"]["creation"]["role"] == "narration"
    assert elements["audio-explicit"]["creation"]["role"] == "bgm"
    assert "role" not in elements["r2v-1"]["creation"]
    assert migrated["schema_version"] == 9
    Project.model_validate(migrated)  # loadable, or the migration failed


def test_narration_overlapping_dialogue_element_is_rejected() -> None:
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
    with pytest.raises(ValidationError, match="overlaps the voiced"):
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


def test_narration_over_the_voiced_shot_interval_is_rejected() -> None:
    raw = _with_elements(
        _two_shot_r2v_element(),
        _audio_element(
            "narration-1",
            start_tick=2_000,
            duration_tick=2_000,
            role="narration",
        ),
    )
    with pytest.raises(ValidationError, match="overlaps the voiced"):
        Project.model_validate(raw)


def test_shot_placement_scales_declared_durations_onto_the_span() -> None:
    """Declared shot durations rarely sum to the span exactly; the
    provider renders the shot list into the span, so placement must
    scale. Field probe: a 10s element with two 8s shots and dialogue in
    the second voices roughly 5-10s, not 8-10s."""

    drifting = _two_shot_r2v_element(
        duration_tick=10_000,
        shot_seconds=(8.0, 8.0),
        dialogues=("", "后半段才开口"),
    )
    # Narration over the true speaking interval (5s onward) is rejected …
    raw = _with_elements(
        drifting,
        _audio_element(
            "narration-1",
            start_tick=5_000,
            duration_tick=2_800,
            role="narration",
        ),
    )
    with pytest.raises(ValidationError, match="overlaps the voiced"):
        Project.model_validate(raw)
    # … narration inside the truly silent first half is accepted, and the
    # mixer's ducking windows agree with the gate.
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
    assert _timeline_speech_windows(timeline) == ((5.0, 10.0),)


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
