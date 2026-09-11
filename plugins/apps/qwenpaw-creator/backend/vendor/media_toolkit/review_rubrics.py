# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
# Vendored from Qwen-MM-Plugins (Apache-2.0), release commit 077aea6.
# Upstream path: src/capabilities/video-edit/skill/review/final-review.md
#   (§D Appeal rubric, [rubric-verbatim] rows and common failures),
#   src/capabilities/video-edit/skill/review/scene-review.md (the six checks),
#   src/capabilities/video-edit/skill/review/source-review.md (technical probe).
# Modified for QwenPaw Creator. See backend/vendor/NOTICE.md.
"""Structured review rules ported from the upstream video-edit skill docs.

This module is the single source of truth for every run-review prompt and
for the taste principles rendered into the Creator agent prompts. The rubric
row names and anchor questions are kept verbatim from the upstream
``final-review.md`` (§D, marked ``[rubric-verbatim]`` upstream: renaming rows
voids the review). Creator modification: the upstream "concept <= 5 caps the
verdict at revise" VETO semantics is intentionally NOT ported — Creator's
run review is advisory, so a low concept score becomes a major-severity
suggestion instead of a delivery gate.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RubricRow:
    """One Appeal rubric row (0-10 score scale upstream)."""

    index: int
    key: str
    name: str
    # Upstream row 0 carries veto power; Creator keeps the flag for
    # provenance but downstream consumers must treat it as advisory only.
    upstream_veto: bool
    anchor_questions: str


# final-review.md §D — "Use these seven rows verbatim ([rubric-verbatim])".
APPEAL_RUBRIC_ROWS: tuple[RubricRow, ...] = (
    RubricRow(
        index=0,
        key="concept",
        name="Concept",
        upstream_veto=True,
        anchor_questions=(
            "Can you state the piece's idea in one sentence? Cover all text "
            "— is the subject still recognizable? Swap the subject — does "
            'the piece still "work"? (If yes → template, <=5.)'
        ),
    ),
    RubricRow(
        index=1,
        key="contract",
        name="Contract adherence",
        upstream_veto=False,
        anchor_questions=(
            "Do pacing/density/motion match the three dials? Design read "
            "realized? Device ledger: every declared device (signature + "
            "each Body item) gets a render timestamp — declared-but-absent "
            "= fail this row. Count >=3 distinct BODY device families on "
            "the render (title/badges/closing card don't count)."
        ),
    ),
    RubricRow(
        index=2,
        key="rhythm",
        name="Rhythm",
        upstream_veto=False,
        anchor_questions=(
            "Hook inside 1.5s? Energy alternates? Holds respected (T2)? No "
            "shot >7s in narrated pieces?"
        ),
    ),
    RubricRow(
        index=3,
        key="restraint",
        name="Restraint",
        upstream_veto=False,
        anchor_questions=(
            "Signature device 1-2 uses (T1)? No mass glints (T3)? No "
            "repetition (T4)?"
        ),
    ),
    RubricRow(
        index=4,
        key="craft",
        name="Craft quality",
        upstream_veto=False,
        anchor_questions=(
            "Seams motivated, text sharp, mattes clean, grade consistent"
        ),
    ),
    RubricRow(
        index=5,
        key="sound",
        name="Sound",
        upstream_veto=False,
        anchor_questions=(
            "Two-track doctrine present? SFX pinned to real actions? Clean "
            "tail?"
        ),
    ),
    RubricRow(
        index=6,
        key="typography_motion",
        name="Typography & motion",
        upstream_veto=False,
        anchor_questions=(
            "Hero titles match the declared text treatment? Bare default "
            "font on a hero title without written justification = fail this "
            "row; Chinese text in a system fallback (PingFang/Heiti) = fail "
            "even if declared. Text below the Type scale floor = fail. "
            "Overlay/title/data motion matches the contract's Motion plan "
            "(named recipes) — undeclared freestyle motion = fail this row."
        ),
    ),
)

# final-review.md §D — the upstream veto sentence, quoted into major
# suggestions when concept scores <= CONCEPT_WEAK_THRESHOLD (advisory only).
CONCEPT_WEAK_THRESHOLD = 5
CONCEPT_VETO_QUOTE = "execution polish cannot rescue an empty concept"

# final-review.md §D — "Common failures to name explicitly".
COMMON_FAILURES: tuple[str, ...] = (
    "slow/unclear opening",
    "flat shot rhythm",
    "decorative motion serving nothing",
    "same layout every scene",
    "text cards dominating",
    "hero titles in undeclared default type",
    "overlay motion outside the approved palette with no logged reason",
    "uniform punch-in entrance on every cut",
    "opacity pops at shot entrances",
    "elastic overshoot in a non-cute register",
    "shots resting at non-1.0 scale after a seam (zoom drift/breathing)",
    "effective zoom or sharpness jumping cut-to-cut from runtime rescaling",
    "no reason to keep watching",
)


@dataclass(frozen=True, slots=True)
class SceneCheck:
    """One scene-review check (minutes-scale, per scene render)."""

    index: int
    key: str
    title: str
    description: str


# scene-review.md — "The six checks (all on the SCENE RENDER, not snapshots)".
SCENE_REVIEW_CHECKS: tuple[SceneCheck, ...] = (
    SceneCheck(
        index=1,
        key="devices",
        title="Devices",
        description=(
            "Every contract device this scene owns is visible at its "
            "timestamp: name → timestamp → what you saw. A device that "
            'didn\'t land blocks VERIFIED; "will fix in the master" is not '
            "a state that exists."
        ),
    ),
    SceneCheck(
        index=2,
        key="type_fonts",
        title="Type & fonts",
        description=(
            "Real font files rendering (no PingFang/system fallback, no "
            "tofu/placeholder glyphs); every size above the type scale "
            "floor; legible at thumbnail zoom."
        ),
    ),
    SceneCheck(
        index=3,
        key="composition_safety",
        title="Composition safety",
        description=(
            "Nothing covers faces/UI/focal action ([no-occlusion]); overlay "
            "anchor differs from the previous scene's; every overlay has a "
            "full life-cycle — entrance, idle micro-motion if held >1.5s, "
            "choreographed exit with a hard kill (no element leaking past "
            "the scene's time box)."
        ),
    ),
    SceneCheck(
        index=4,
        key="motion_quality",
        title="Motion quality",
        description=(
            "Entrances match the declared recipes and presets; overshoot "
            "character fits the register; nothing rests at non-1.0 scale at "
            "scene end ([no-zoom-drift]); first and last frame clean "
            "(cold-render check — verify frame 0 on the render, not the "
            "preview)."
        ),
    ),
    SceneCheck(
        index=5,
        key="technical",
        title="Technical",
        description=(
            "Black check on the scene render (interior AND head/tail); "
            "duration equals the locked time box exactly; scene-owned SFX "
            "present and peaking sanely."
        ),
    ),
    SceneCheck(
        index=6,
        key="watch_once",
        title="Watch it once as a viewer",
        description=(
            "Does the beat land? Anything you didn't have time to read "
            "(T2)? This impression IS the NL observation — write it while "
            "it's fresh, doubts included."
        ),
    ),
)

# source-review.md — "Required technical probe" field list.
SOURCE_PROBE_FIELDS: tuple[str, ...] = (
    "absolute path",
    "duration",
    "resolution",
    "fps",
    "codec/pixel format",
    "audio stream presence + sample rate + channels",
    "file size",
    "known mismatches across files (fps/resolution/sample-rate/codec)",
)

# final-review.md §B — the evidence discipline every review inherits.
EVIDENCE_DISCIPLINE = (
    "For each criterion cite evidence — a criterion without a timestamp "
    "cannot be marked pass"
)


__all__ = [
    "APPEAL_RUBRIC_ROWS",
    "COMMON_FAILURES",
    "CONCEPT_VETO_QUOTE",
    "CONCEPT_WEAK_THRESHOLD",
    "EVIDENCE_DISCIPLINE",
    "RubricRow",
    "SCENE_REVIEW_CHECKS",
    "SOURCE_PROBE_FIELDS",
    "SceneCheck",
]
