# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access

from __future__ import annotations

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
    compute_chain_duration,
    normalize_transition_kind,
)
from services.project_files.models import (
    ElementLocation,
    EntityCollection,
    Project,
    R2VCreation,
    Shot,
    TimelineElement,
    TimelineSpan,
    TransitionCreation,
)


pytestmark = pytest.mark.unit


def _r2v_element(
    element_id: str,
    *,
    start: int,
    duration: int = 5_000,
) -> TimelineElement:
    shot = Shot(
        shot_id=f"{element_id}-shot",
        description="猫追逐老鼠",
        camera="→ 横摇右",
        framing="全景",
        duration_seconds=duration / 1_000,
    )
    return TimelineElement(
        element_id=element_id,
        label=element_id,
        span=TimelineSpan(start_tick=start, duration_tick=duration),
        location=ElementLocation(),
        creation=R2VCreation(
            narrative="猫发现老鼠后追逐",
            storyboard_prompt="动画分镜：猫发现并追逐老鼠",
            video_prompt="动画，猫从左向右追逐老鼠，动作连续",
            shots=EntityCollection(
                items={shot.shot_id: shot},
                order=[shot.shot_id],
            ),
        ),
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


def test_normalize_transition_kind_maps_aliases_and_falls_back_to_fade():
    assert normalize_transition_kind("cut") == "cut"
    assert normalize_transition_kind("crossfade") == "fade"
    assert normalize_transition_kind("FadeBlack") == "fadeblack"
    assert normalize_transition_kind("wipeleft") == "wipeleft"
    assert normalize_transition_kind("swirl-unknown") == "fade"
    assert normalize_transition_kind(None) == "fade"


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


def test_filter_chain_uses_concat_for_cut_joins_and_anullsrc_for_silent_clips():
    chain = build_transition_filter_chain(
        [
            TransitionClip(duration_seconds=2.0, has_audio=True),
            TransitionClip(duration_seconds=2.0, has_audio=False),
        ],
        [TransitionJoin(kind="cut", blend_seconds=0.4)],
        canvas_size=(1280, 720),
    )
    assert "xfade" not in chain
    assert "concat=n=2:v=1:a=0" in chain
    assert "concat=n=2:v=0:a=1" in chain
    assert "anullsrc=channel_layout=stereo:sample_rate=44100" in chain


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


def test_chain_duration_subtracts_effective_blends_only():
    clips = [
        TransitionClip(duration_seconds=5.0, has_audio=True),
        TransitionClip(duration_seconds=4.0, has_audio=True),
        TransitionClip(duration_seconds=3.0, has_audio=True),
    ]
    joins = [
        TransitionJoin(kind="fade", blend_seconds=0.4),
        TransitionJoin(kind="cut", blend_seconds=0.5),
    ]
    assert compute_chain_duration(clips, joins) == pytest.approx(11.6)


def test_plan_projects_overlap_into_blend_without_tail_trim():
    timeline = _timeline_with_transition()
    visual = [
        timeline.elements_by_id["a"],
        timeline.elements_by_id["b"],
    ]
    plans = _plan_timeline_transitions(timeline, visual)
    assert len(plans) == 1
    plan = plans[0]
    assert plan["kind"] == "fade"
    # The transition span equals the intersection: the blend consumes the
    # whole 400ms overlap, no tail trim.
    assert plan["duration_ms"] == 400
    assert plan["tail_trim_ms"] == 0


def test_plan_splits_extra_overlap_into_tail_trim():
    timeline = _timeline_with_transition()
    # The transition covers only part of the intersection: the remaining
    # overlap becomes tail trim on the `from` side.
    timeline.elements_by_id["fade"].span = TimelineSpan(
        start_tick=4_700,
        duration_tick=300,
    )
    visual = [
        timeline.elements_by_id["a"],
        timeline.elements_by_id["b"],
    ]
    plans = _plan_timeline_transitions(timeline, visual)
    assert plans[0]["duration_ms"] == 300
    assert plans[0]["tail_trim_ms"] == 100


def test_plan_treats_cut_kind_as_pure_tail_trim():
    timeline = _timeline_with_transition(kind="cut")
    visual = [
        timeline.elements_by_id["a"],
        timeline.elements_by_id["b"],
    ]
    plans = _plan_timeline_transitions(timeline, visual)
    assert plans[0]["kind"] == "cut"
    assert plans[0]["duration_ms"] == 0
    assert plans[0]["tail_trim_ms"] == 400


def test_plan_rejects_non_adjacent_endpoints():
    timeline = _timeline_with_transition()
    timeline.elements_by_id["c"] = _r2v_element(
        "c",
        start=9_600,
        duration=5_000,
    )
    visual = [
        timeline.elements_by_id["a"],
        timeline.elements_by_id["b"],
        timeline.elements_by_id["c"],
    ]
    timeline.elements_by_id["fade"] = TimelineElement(
        element_id="fade",
        span=TimelineSpan(start_tick=4_600, duration_tick=400),
        creation=TransitionCreation(
            from_element_id="a",
            to_element_id="c",
            transition_kind="crossfade",
        ),
    )
    with pytest.raises(DomainValidationError, match="不相邻"):
        _plan_timeline_transitions(timeline, visual)


def test_plan_rejects_duplicate_transitions_for_one_pair():
    timeline = _timeline_with_transition()
    timeline.elements_by_id["fade-2"] = _transition_element(
        "fade-2",
        from_id="a",
        to_id="b",
        start=4_700,
        duration=200,
    )
    visual = [
        timeline.elements_by_id["a"],
        timeline.elements_by_id["b"],
    ]
    with pytest.raises(DomainValidationError, match="只支持一个转场"):
        _plan_timeline_transitions(timeline, visual)


def test_contiguous_validation_allows_overlap_covered_by_transition():
    timeline = _timeline_with_transition()
    visual = [
        timeline.elements_by_id["a"],
        timeline.elements_by_id["b"],
    ]
    plans = _plan_timeline_transitions(timeline, visual)
    _validate_contiguous_edit_elements(visual, plans)
    with pytest.raises(DomainValidationError, match="期望 5000"):
        _validate_contiguous_edit_elements(visual)


def test_runner_accepts_whitelisted_kinds_and_rejects_unknown():
    def spec_with(kind: str):
        return type(
            "Spec",
            (),
            {
                "transitions": (
                    {
                        "fromElementId": "a",
                        "toElementId": "b",
                        "kind": kind,
                        "duration_ms": 400,
                        "tail_trim_ms": 0,
                    },
                ),
                "inputs": (),
                "audio_plan": "",
            },
        )()

    FfmpegLocalMediaRunner._validate_supported_directives(spec_with("fade"))
    FfmpegLocalMediaRunner._validate_supported_directives(spec_with("cut"))
    FfmpegLocalMediaRunner._validate_supported_directives(
        spec_with("dissolve"),
    )
    with pytest.raises(DomainValidationError, match="仅支持"):
        FfmpegLocalMediaRunner._validate_supported_directives(
            spec_with("swirl"),
        )


def test_runner_maps_transitions_to_segment_tail_trim_and_joins():
    spec = type(
        "Spec",
        (),
        {
            "transitions": (
                {
                    "fromElementId": "a",
                    "toElementId": "b",
                    "kind": "fade",
                    "duration_ms": 300,
                    "tail_trim_ms": 100,
                },
            ),
            "inputs": (
                type("Item", (), {"source_ref": "element:a"})(),
                type("Item", (), {"source_ref": "element:b"})(),
            ),
        },
    )()
    tail_trims, joins_by_pair = FfmpegLocalMediaRunner._transition_directives(
        spec,
    )
    assert tail_trims == {"element:a": pytest.approx(0.1)}
    joins = FfmpegLocalMediaRunner._resolve_segment_joins(
        spec,
        joins_by_pair,
    )
    assert len(joins) == 1
    assert joins[0].kind == "fade"
    assert joins[0].effective_blend() == pytest.approx(0.3)


# ── beat-sync snapping (WT-B5) ───────────────────────────────────────────────


def _beat_spec(*, audio_tracks=()):
    def _input(ref: str, duration: float):
        return type(
            "Item",
            (),
            {
                "source_ref": ref,
                "start_seconds": 0.0,
                "end_seconds": duration,
                "duration_seconds": duration,
            },
        )()

    return type(
        "Spec",
        (),
        {
            "transitions": (
                {
                    "fromElementId": "a",
                    "toElementId": "b",
                    "kind": "fade",
                    "duration_ms": 400,
                    "tail_trim_ms": 300,
                },
            ),
            "inputs": (_input("element:a", 5.0), _input("element:b", 5.0)),
            "audio_tracks": audio_tracks,
        },
    )()


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
