# -*- coding: utf-8 -*-
"""
Read explicitly authored storyboard layout without equating frames to shots.
"""

from __future__ import annotations

import re

_DIGITS = "零一二三四五六七八九"
_NUMBER = r"(?:[1-9]\d?|[一二三四五六七八九十]{1,3})"
_PANELS = re.compile(
    rf"(?<![\d每第{_DIGITS}十])({_NUMBER})\s*(?:[个张格]\s*)?(?:等尺寸|等大)?\s*"
    r"(?:分镜格|分镜面板|故事板面板|面板|(?:时间)?关键帧)"
    r"|(?<![\w\d])(\d{1,2})\s*[- ]?\s*"
    r"(?:story(?:board)?\s+)?(?:panels?|keyframes?)\b"
    r"|\bpanels?\s*[:=]\s*(\d{1,2})(?!\d)",
    re.IGNORECASE,
)
_CELLS = re.compile(rf"(?<![\d{_DIGITS}十])({_NUMBER})\s*宫格")
_GRIDS = (
    re.compile(
        r"(?<!\d)([1-9])\s*(?:[行列]\s*)?[x×*]\s*([1-9])(?!\d)(?:\s*[行列])?",
        re.I,
    ),
    re.compile(r"(?<!\d)([1-9])\s*行\s*([1-9])\s*列"),
    re.compile(r"(?<!\d)([1-9])\s*列\s*([1-9])\s*行"),
)
_SINGLE = re.compile(
    r"单格分镜|单帧分镜|单(?:张|幅)(?:静态)?(?:关键帧|海报|画面|图片|图)"
    r"|\bsingle[- ](?:panel|still|poster|frame|image)\b",
    re.I,
)


def _number(value: str) -> int:
    if value.isascii():
        return int(value)
    if "十" in value:
        left, right = value.split("十", 1)
        if len(left) > 1 or len(right) > 1:
            return 0
        return (int(_DIGITS.index(left)) if left else 1) * 10 + (
            _DIGITS.index(right) if right else 0
        )
    return _DIGITS.index(value) if len(value) == 1 else 0


def declared_storyboard_panel_count(prompt: str) -> int | None:
    """Read panel/keyframe count, then grid capacity; never infer from shots.

    An explicit six-panel plan in a 3×3 grid has six illustrated panels, not
    nine. Conflicting explicit counts stay unresolved so review can request
    clarification instead of silently changing the user's layout.
    """
    grids = [match for pattern in _GRIDS for match in pattern.finditer(prompt)]

    def inside_grid(match: re.Match) -> bool:
        return any(
            grid.start() <= match.start() < grid.end() for grid in grids
        )

    counts = {
        _number(next(value for value in match.groups() if value))
        for match in _PANELS.finditer(prompt)
        if not inside_grid(match)
        if not re.search(r"(?:每|第)\s*$", prompt[: match.start()])
    } - {0}
    if counts:
        return next(iter(counts)) if len(counts) == 1 else None
    counts = {
        _number(match.group(1))
        for match in _CELLS.finditer(prompt)
        if not inside_grid(match)
    } - {0}
    counts.update(
        int(match.group(1)) ** 2
        for match in grids
        if match.group(1) == match.group(2)
    )
    if counts:
        return next(iter(counts)) if len(counts) == 1 else None
    return 1 if _SINGLE.search(prompt) else None
