# -*- coding: utf-8 -*-
"""The published video's real duration drives the element span.

An s2v clip only lasts as long as its driving audio; the plan may have
reserved more room. Publishing must shrink the span to the delivered
footage and pull later elements forward so the final cut stays seamless
instead of freezing the last frame to fill the plan.
"""

from __future__ import annotations

from services.media_files.element_adapter import reconcile_candidate_span


def _candidate(ticks_per_second: int = 1000) -> dict:
    return {
        "timelines": {
            "items": {
                "timeline:main": {
                    "ticks_per_second": ticks_per_second,
                    "elements_by_id": {
                        "el:talk": {
                            "span": {
                                "start_tick": 0,
                                "duration_tick": 5000,
                            },
                        },
                        "el:shot2": {
                            "span": {
                                "start_tick": 5000,
                                "duration_tick": 5000,
                            },
                        },
                        "el:narration2": {
                            "span": {
                                "start_tick": 5000,
                                "duration_tick": 5000,
                            },
                        },
                        "el:overlap": {
                            # Starts inside the shrunk segment: stays put.
                            "span": {
                                "start_tick": 1000,
                                "duration_tick": 1000,
                            },
                        },
                    },
                },
            },
        },
    }


def test_shorter_footage_shrinks_span_and_ripples_later_elements() -> None:
    candidate = _candidate()
    changed = reconcile_candidate_span(
        candidate,
        element_id="el:talk",
        actual_duration_seconds=2.8,
    )
    assert changed is True
    elements = candidate["timelines"]["items"]["timeline:main"][
        "elements_by_id"
    ]
    assert elements["el:talk"]["span"]["duration_tick"] == 2800
    # Everything that started at/after the old end moves forward together.
    assert elements["el:shot2"]["span"]["start_tick"] == 2800
    assert elements["el:narration2"]["span"]["start_tick"] == 2800
    # An element inside the shrunk window keeps its position.
    assert elements["el:overlap"]["span"]["start_tick"] == 1000


def test_reconcile_is_idempotent_on_replay() -> None:
    candidate = _candidate()
    assert reconcile_candidate_span(
        candidate,
        element_id="el:talk",
        actual_duration_seconds=2.8,
    )
    replayed = reconcile_candidate_span(
        candidate,
        element_id="el:talk",
        actual_duration_seconds=2.8,
    )
    assert replayed is False
    elements = candidate["timelines"]["items"]["timeline:main"][
        "elements_by_id"
    ]
    assert elements["el:shot2"]["span"]["start_tick"] == 2800


def test_within_tolerance_and_longer_footage_leave_span_alone() -> None:
    near = _candidate()
    assert (
        reconcile_candidate_span(
            near,
            element_id="el:talk",
            actual_duration_seconds=4.9,
        )
        is False
    )
    longer = _candidate()
    assert (
        reconcile_candidate_span(
            longer,
            element_id="el:talk",
            actual_duration_seconds=5.6,
        )
        is False
    )
    for candidate in (near, longer):
        elements = candidate["timelines"]["items"]["timeline:main"][
            "elements_by_id"
        ]
        assert elements["el:talk"]["span"]["duration_tick"] == 5000
        assert elements["el:shot2"]["span"]["start_tick"] == 5000


def test_missing_element_or_duration_is_a_no_op() -> None:
    candidate = _candidate()
    assert (
        reconcile_candidate_span(
            candidate,
            element_id="el:ghost",
            actual_duration_seconds=2.0,
        )
        is False
    )
    assert (
        reconcile_candidate_span(
            candidate,
            element_id="el:talk",
            actual_duration_seconds=None,
        )
        is False
    )
