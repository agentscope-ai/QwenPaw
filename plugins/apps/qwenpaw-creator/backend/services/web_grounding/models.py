# -*- coding: utf-8 -*-
"""Shared typed contracts for the grounding pipeline."""

from __future__ import annotations

from typing import NotRequired, TypedDict


class VisualJob(TypedDict):
    query: str
    entity_name: str
    entity_type: str
    usage: str
    strict_identity: bool
    job_key: NotRequired[str]


class Verification(TypedDict, total=False):
    status: str
    fit_score: float
    identity_score: float
    reference_quality_score: float
    usage: str
    quality_flags: list[str]
    reason: str


class VisualSource(TypedDict, total=False):
    index: int
    rank: int
    url: str
    source_url: str
    thumbnail_url: str
    title: str
    provider: str
    query: str
    entity_name: str
    entity_type: str
    usage_hint: str
    strict_identity: bool
    visual_job_key: str
    local_path: str
    local_url: str
    vlm_image_url: str
    media_type: str
    storage_sha256: str
    verification: Verification


class GroundingResult(TypedDict, total=False):
    ok: bool
    status: str
    needs_grounding: bool
    need_websearch: bool
    queries: list[str]
    facts: list[dict[str, object]]
    sources: list[dict[str, object]]
    visual_sources: list[VisualSource]
    grounded_context: str
    issues: list[str]
