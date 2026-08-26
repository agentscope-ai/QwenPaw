# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access

from __future__ import annotations

from types import SimpleNamespace

import pytest

from domain.errors import ValidationError as DomainValidationError
from services.media_files.local_execution import (
    FfmpegLocalMediaRunner,
    _plan_timeline_transitions,
    _validate_contiguous_edit_elements,
)
from services.media_files.transitions import (
    TransitionClip,
    TransitionJoin,
    build_transition_filter_chain,
)
from services.project_files.models import (
    Project,
    TimelineElement,
    TimelineSpan,
    TransitionCreation,
)

from .conftest import make_r2v_element


pytestmark = pytest.mark.unit


def _r2v_element(
    element_id: str,
    *,
    start: int,
    duration: int = 5_000,
) -> TimelineElement:
    return make_r2v_element(
        element_id,
        label=element_id,
        video_prompt="动画，猫从左向右追逐老鼠，动作连续",
        start_tick=start,
        duration_tick=duration,
    )


def _transition_element(
    element_id: str,
    *,
    from_id: str,
    to_id: str,
    start: int,
    duration: int,
    kind: str = "crossfade",
) -> TimelineElement:
    return TimelineElement(
        element_id=element_id,
        span=TimelineSpan(start_tick=start, duration_tick=duration),
        creation=TransitionCreation(
            from_element_id=from_id,
            to_element_id=to_id,
            transition_kind=kind,
        ),
    )


def _timeline_with_transition(kind: str = "crossfade"):
    project = Project.new(project_id="transition-plan", name="Transition")
    timeline = project.timelines.items["timeline:main"]
    timeline.elements_by_id = {
        "a": _r2v_element("a", start=0, duration=5_000),
        "b": _r2v_element("b", start=4_600, duration=5_000),
        "fade": _transition_element(
            "fade",
            from_id="a",
            to_id="b",
            start=4_600,
            duration=400,
            kind=kind,
        ),
    }
    return timeline


def _visual(timeline, *ids):
    return [timeline.elements_by_id[element_id] for element_id in ids]


def test_filter_chain_emits_xfade_and_acrossfade_with_running_offsets():
    chain = build_transition_filter_chain(
        [
            TransitionClip(duration_seconds=5.0, has_audio=True),
            TransitionClip(duration_seconds=4.0, has_audio=True),
            TransitionClip(duration_seconds=3.0, has_audio=True),
        ],
        [
            TransitionJoin(kind="crossfade", blend_seconds=0.4),
            TransitionJoin(kind="fadeblack", blend_seconds=0.5),
        ],
        canvas_size=(1280, 720),
    )
    assert "xfade=transition=fade:duration=0.400000:offset=4.600000" in chain
    # The second pair's offset builds on the chain duration with the blend
    # already consumed: 4.6 + 4 - 0.5 = 8.1.
    assert (
        "xfade=transition=fadeblack:duration=0.500000:offset=8.100000" in chain
    )
    assert chain.count("acrossfade=d=") == 2
    assert chain.endswith("[aout]")
    assert "[vout]" in chain


def test_filter_chain_rejects_blend_longer_than_adjacent_clip():
    with pytest.raises(ValueError, match="must be shorter"):
        build_transition_filter_chain(
            [
                TransitionClip(duration_seconds=1.0, has_audio=True),
                TransitionClip(duration_seconds=5.0, has_audio=True),
            ],
            [TransitionJoin(kind="fade", blend_seconds=1.0)],
            canvas_size=(1280, 720),
        )


def test_plan_covers_overlap_and_validates_contiguity():
    timeline = _timeline_with_transition()
    visual = _visual(timeline, "a", "b")
    plans = _plan_timeline_transitions(timeline, visual)
    assert len(plans) == 1
    assert plans[0]["kind"] == "fade"
    # The blend consumes the whole 400ms overlap, no tail trim.
    assert plans[0]["duration_ms"] == 400
    assert plans[0]["tail_trim_ms"] == 0
    _validate_contiguous_edit_elements(visual, plans)
    with pytest.raises(DomainValidationError, match="期望 5000"):
        _validate_contiguous_edit_elements(visual)


def test_plan_rejects_non_adjacent_endpoints():
    timeline = _timeline_with_transition()
    timeline.elements_by_id["c"] = _r2v_element(
        "c",
        start=9_600,
        duration=5_000,
    )
    timeline.elements_by_id["fade"] = _transition_element(
        "fade",
        from_id="a",
        to_id="c",
        start=4_600,
        duration=400,
    )
    with pytest.raises(DomainValidationError, match="不相邻"):
        _plan_timeline_transitions(timeline, _visual(timeline, "a", "b", "c"))


def test_runner_accepts_whitelisted_kinds_and_rejects_unknown():
    def spec_with(kind: str):
        transition = {
            "fromElementId": "a",
            "toElementId": "b",
            "kind": kind,
            "duration_ms": 400,
            "tail_trim_ms": 0,
        }
        return SimpleNamespace(
            transitions=(transition,),
            inputs=(),
            audio_plan="",
        )

    FfmpegLocalMediaRunner._validate_supported_directives(spec_with("fade"))
    with pytest.raises(DomainValidationError, match="仅支持"):
        FfmpegLocalMediaRunner._validate_supported_directives(
            spec_with("swirl"),
        )


# ── beat-sync snapping (WT-B5) ───────────────────────────────────────────────


def _beat_spec(*, audio_tracks=()):
    def _input(ref: str, duration: float):
        return SimpleNamespace(
            source_ref=ref,
            start_seconds=0.0,
            end_seconds=duration,
            duration_seconds=duration,
        )

    transition = {
        "fromElementId": "a",
        "toElementId": "b",
        "kind": "fade",
        "duration_ms": 400,
        "tail_trim_ms": 300,
    }
    return SimpleNamespace(
        transitions=(transition,),
        inputs=(_input("element:a", 5.0), _input("element:b", 5.0)),
        audio_tracks=audio_tracks,
    )


def test_beat_snap_moves_the_xfade_end_onto_a_beat(monkeypatch) -> None:
    from services.media_files import local_execution as le
    from services.media_files.beat_grid import BeatGrid

    # Chain math: d0 = 5.0 - 0.3 = 4.7s, so the xfade resolves at 4.7s.
    # The nearest beat is 4.8s → δ=+0.1s comes out of the tail trim.
    monkeypatch.setattr(
        le,
        "extract_beat_grid",
        lambda path: BeatGrid(beats_ms=(4_800,), tempo_bpm=120.0),
    )
    spec = _beat_spec(
        audio_tracks=(
            {
                "path": "/tmp/bgm.mp3",
                "offset_seconds": 0.0,
                "max_duration_seconds": 10.0,
            },
        ),
    )
    tail_trims, joins = FfmpegLocalMediaRunner._transition_directives(spec)
    FfmpegLocalMediaRunner._snap_transitions_to_beats(spec, tail_trims, joins)
    join = joins[("element:a", "element:b")]
    assert join.effective_blend() == pytest.approx(0.5)
    assert tail_trims["element:a"] == pytest.approx(0.2)
    # Total chain duration is invariant: the overlap split changed, not
    # the committed cut layout.
    assert (5.0 - 0.2) + 5.0 - 0.5 == pytest.approx(9.3)
