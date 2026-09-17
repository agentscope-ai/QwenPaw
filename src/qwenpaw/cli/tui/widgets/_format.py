# -*- coding: utf-8 -*-
"""Text-formatting helpers shared by the transcript widgets."""

from __future__ import annotations

# One-line param summaries (panel titles, the activity line) cap here.
_SUMMARY_LIMIT = 72


def summarize_params(params: str | None, limit: int = _SUMMARY_LIMIT) -> str:
    """A compact one-line gist of tool params (e.g. the actual command).

    Params may span multiple lines (one per key, indented JSON for nested
    values), so collapse all whitespace into single spaces and cap the
    result — the full text stays available in the panel body.
    """
    if not params:
        return ""
    flat = " ".join(params.split())
    return flat[:limit] + " …" if len(flat) > limit else flat
