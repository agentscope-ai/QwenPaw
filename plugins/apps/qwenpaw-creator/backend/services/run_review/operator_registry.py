# -*- coding: utf-8 -*-
"""User-configurable review operator registry (self-review 高级配置).

Every APE-imported review operator is individually switchable through the
``self_review.operators`` section of model_config.json. The default is
"auto": an operator with its dependency available is on, one whose
dependency (ASR key / easyocr / opencv) is missing is off — 能开尽开.
An explicit ``true``/``false`` from the user always wins; an explicit
``true`` on a missing dependency still degrades to a recorded skip at
runtime (fail-open), it can never crash a review.

Tier-level model dependencies (LLM for tier 1, VLM for tiers 2/3) are
owned by the tier switches themselves; operator-level dependencies only
cover operator-specific extras, so ``auto`` here never re-checks what
the tier switch already guarantees.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.util import find_spec
from typing import Any, Literal

OperatorDependency = Literal["none", "asr", "ocr", "cv2"]


@dataclass(frozen=True, slots=True)
class ReviewOperator:
    """One switchable review capability."""

    key: str
    tier: int
    dependency: OperatorDependency = "none"
    # Degrades internally when an optional library is missing (the
    # operator still produces partial facts), so auto keeps it on.
    degrades_without_dependency: bool = False


REVIEW_OPERATORS: tuple[ReviewOperator, ...] = (
    # Tier 0 — objective fact operators (facts, never verdicts).
    ReviewOperator("video_index", 0),
    ReviewOperator("machine_params", 0),
    ReviewOperator("light_metrics", 0),
    ReviewOperator("audio_content", 0),
    ReviewOperator("av_sync", 0, dependency="asr"),
    ReviewOperator("cross_shot_consistency", 0),
    ReviewOperator(
        "camera_motion",
        0,
        dependency="cv2",
        degrades_without_dependency=True,
    ),
    ReviewOperator("ocr_text", 0, dependency="ocr"),
    # Tier 1 — script-to-shots reasoning check.
    ReviewOperator("script_check", 1),
    # Tier 2 — media review probe surfaces.
    ReviewOperator("defect_bank", 2),
    ReviewOperator("faithfulness", 2),
    ReviewOperator("focused_frames", 2),
    # Tier 3 — render review near-miss challenge pass.
    ReviewOperator("challenge", 3),
)

_OPERATORS_BY_KEY = {operator.key: operator for operator in REVIEW_OPERATORS}


def operator_keys() -> tuple[str, ...]:
    return tuple(operator.key for operator in REVIEW_OPERATORS)


def _dependency_available(dependency: OperatorDependency) -> bool:
    if dependency == "none":
        return True
    if dependency == "asr":
        from models.config import get_asr_api_key

        return bool(get_asr_api_key())
    if dependency == "ocr":
        return find_spec("easyocr") is not None
    if dependency == "cv2":
        return find_spec("cv2") is not None
    return False


def _configured_operators() -> dict[str, bool]:
    """Explicit user choices from the persisted self_review section."""
    from models.config import get_self_review_operators

    return get_self_review_operators()


def is_operator_enabled(key: str) -> bool:
    """Effective switch for one operator (user value wins, else auto).

    Unknown keys resolve to False so a stale config entry can never turn
    on a code path that no longer exists.
    """
    operator = _OPERATORS_BY_KEY.get(key)
    if operator is None:
        return False
    configured = _configured_operators().get(key)
    if isinstance(configured, bool):
        return configured
    capable = _dependency_available(operator.dependency)
    return capable or operator.degrades_without_dependency


def operator_status_report() -> list[dict[str, Any]]:
    """Response-only status rows for the settings UI (never persisted).

    Each row: key/tier/dependency plus the resolved state — ``source``
    is ``user`` when an explicit boolean is persisted, ``auto``
    otherwise; ``capability_ok`` reports the dependency probe so the UI
    can explain WHY an auto operator is off.
    """
    configured = _configured_operators()
    rows: list[dict[str, Any]] = []
    for operator in REVIEW_OPERATORS:
        explicit = configured.get(operator.key)
        capable = _dependency_available(operator.dependency)
        if isinstance(explicit, bool):
            enabled = explicit
            source = "user"
        else:
            enabled = capable or operator.degrades_without_dependency
            source = "auto"
        rows.append(
            {
                "key": operator.key,
                "tier": operator.tier,
                "dependency": operator.dependency,
                "degrades": operator.degrades_without_dependency,
                "capability_ok": capable,
                "enabled": enabled,
                "source": source,
            },
        )
    return rows


__all__ = [
    "REVIEW_OPERATORS",
    "ReviewOperator",
    "is_operator_enabled",
    "operator_keys",
    "operator_status_report",
]
