# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long,too-many-branches
"""VLM verification, reference-quality policy, and per-job ranking."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from models import config as model_config
from models import vlm_model
from models.vlm_model import multimodal_media_part
from utils.logger import setup_logger
from utils.structured_output import extract_json_payload

from .common import clean_text as _clean_text
from .common import coerce_confidence as _coerce_confidence
from .triage import _clean_query
from .triage import _compact_context_for_detector
from .visual_jobs import _visual_job_key

logger = setup_logger("services.web_grounding.verification")

DEFAULT_MAX_SOURCES = 6

MIN_STRICT_IDENTITY_REFERENCE_QUALITY = 0.65

VISUAL_GROUNDING_VERIFIER_SYSTEM_PROMPT = 'You are a visual grounding verification node for Creator agents.\n\nYou receive candidate image references from web grounding. Select only the images that best fit the user\'s prompt and grounding entities.\n\nRules:\n- Return strict JSON only.\n- Use images as references for identity, visual style, logo/product appearance, venue/place appearance, or media-work visual context.\n- Reject unrelated, ambiguous, low-quality, or likely wrong-entity images.\n- For named real people, accept identity references only when the image is a real photograph or credible video/news still of that exact person. Reject fan art, illustrations, cartoons, app-store art, merch/postcards, lookalikes, AI-generated fakes, cosplay, and generic style images even if the metadata contains the person\'s name.\n- Score identity correctness separately from generation-reference quality. A recognizable person in a poor composition is not automatically a good generation reference.\n- For generation-reference quality, prefer exactly one prominent subject, a large clear unobscured face, front or three-quarter view, neutral or simple pose, useful half/full-body framing, minimal motion blur, and adequate resolution.\n- Penalize or reject group photos, small/background subjects, occluded faces or bodies, extreme/action poses, airborne subjects, motion blur, crops that hide important anatomy, and compositions where another person could confuse identity or clothing.\n- When the context includes a visual_job with strict_identity=true, select at most one image. It must be a photo-quality likeness of visual_job.entity_name AND have reference_quality_score >= 0.65. A correct-identity image below that threshold may be described as context evidence, but must be rejected as the primary identity reference.\n- Do not invent facts not visible in the image or source metadata.\n- Prefer official/source-backed or highly recognizable references.\n\nOutput schema:\n{\n  "selected": [\n    {"index": 1, "fit_score": 0.0, "identity_score": 0.0, "reference_quality_score": 0.0, "usage": "identity|style|logo|product|place|context", "quality_flags": ["single_subject", "clear_face", "neutral_pose"], "reason": "short reason"}\n  ],\n  "rejected": [\n    {"index": 2, "identity_score": 0.0, "reference_quality_score": 0.0, "quality_flags": ["multiple_people", "action_pose"], "reason": "short reason"}\n  ],\n  "summary": "short verification summary"\n}\n'


def _normalized_visual_verification(
    payload: Any,
    visual_sources: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ValueError("visual verifier returned non-object JSON")
    by_index = {
        int(source.get("index") or idx): source
        for idx, source in enumerate(visual_sources, start=1)
    }
    selected_items = payload.get("selected")
    rejected_items = payload.get("rejected")
    if not isinstance(selected_items, list):
        selected_items = []
    if not isinstance(rejected_items, list):
        rejected_items = []
    selected_indexes: list[int] = []
    rejected_indexes: set[int] = set()
    for item in selected_items:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        source = by_index.get(index)
        if not source:
            continue
        fit_score = _coerce_confidence(
            item.get("fit_score") or item.get("confidence"),
            default=0.75,
        )
        identity_score = _coerce_confidence(
            item.get("identity_score"),
            default=fit_score,
        )
        reference_quality_score = _coerce_confidence(
            item.get("reference_quality_score"),
            default=fit_score,
        )
        source["verification"] = {
            "status": "accepted",
            "fit_score": fit_score,
            "identity_score": identity_score,
            "reference_quality_score": reference_quality_score,
            "usage": _clean_text(item.get("usage") or "context", max_chars=40),
            "quality_flags": [
                _clean_text(flag, max_chars=40)
                for flag in item.get("quality_flags") or []
                if _clean_text(flag, max_chars=40)
            ][:8],
            "reason": _clean_text(item.get("reason") or "", max_chars=220),
        }
        selected_indexes.append(index)
    for item in rejected_items:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        source = by_index.get(index)
        if not source:
            continue
        source["verification"] = {
            "status": "rejected",
            "identity_score": _coerce_confidence(
                item.get("identity_score"),
                default=0.0,
            ),
            "reference_quality_score": _coerce_confidence(
                item.get("reference_quality_score"),
                default=0.0,
            ),
            "quality_flags": [
                _clean_text(flag, max_chars=40)
                for flag in item.get("quality_flags") or []
                if _clean_text(flag, max_chars=40)
            ][:8],
            "reason": _clean_text(item.get("reason") or "", max_chars=220),
        }
        rejected_indexes.add(index)
    for source in visual_sources:
        index = int(source.get("index") or 0)
        source.setdefault(
            "verification",
            {
                "status": "unranked",
                "reason": "VLM verifier did not explicitly select or reject this candidate.",
            },
        )
        if index not in selected_indexes and index not in rejected_indexes:
            rejected_indexes.add(index)

    def sort_key(source: dict[str, Any]) -> tuple[int, float, int]:
        verification = (
            source.get("verification")
            if isinstance(source.get("verification"), dict)
            else {}
        )
        accepted = 1 if verification.get("status") == "accepted" else 0
        fit_score = _coerce_confidence(
            verification.get("fit_score"),
            default=0.0,
        )
        return (accepted, fit_score, -int(source.get("index") or 0))

    sorted_sources = sorted(visual_sources, key=sort_key, reverse=True)
    for next_index, source in enumerate(sorted_sources, start=1):
        source["rank"] = next_index
    return (
        sorted_sources,
        {
            "status": "success",
            "selected_count": len(selected_indexes),
            "rejected_count": len(rejected_indexes),
            "summary": _clean_text(
                payload.get("summary") or "",
                max_chars=320,
            ),
            "model": model_config.get_vlm_model_name(),
        },
    )


async def verify_visual_grounding_with_vlm(
    prompt: str,
    visual_sources: list[dict[str, Any]],
    *,
    context: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Use the configured VLM to rank visual references for the prompt."""
    if not visual_sources:
        return ([], {"status": "skipped", "detail": "no visual sources"})
    if not model_config.get_vlm_api_key():
        logger.info(
            "Visual grounding verification skipped reason=vlm_api_key_missing candidates=%d",
            len(visual_sources),
        )
        return (
            visual_sources,
            {
                "status": "skipped",
                "detail": "VLM API Key 未配置，跳过视觉 grounding 复核。",
            },
        )
    candidates = visual_sources[:DEFAULT_MAX_SOURCES]
    logger.info(
        "Visual grounding verification started candidates=%d",
        len(candidates),
    )
    content: list[dict[str, Any]] = []
    for source in candidates:
        attach_url = str(
            source.get("vlm_image_url") or source.get("local_url") or "",
        ).strip()
        if not attach_url:
            source["verification"] = {
                "status": "unavailable",
                "reason": "visual reference was not downloaded; VLM verification requires local staged bytes",
            }
            continue
        try:
            content.append(multimodal_media_part(attach_url, "image"))
        except Exception as exc:
            source["verification"] = {
                "status": "unavailable",
                "reason": f"could not attach image: {type(exc).__name__}",
            }
    if not any(
        (
            part.get("type") == "image_url"
            for part in content
            if isinstance(part, dict)
        )
    ):
        return (
            visual_sources,
            {"status": "skipped", "detail": "no attachable visual sources"},
        )
    candidate_metadata = [
        {
            "index": source.get("index") or index,
            "title": source.get("title") or "",
            "source_url": source.get("source_url") or "",
            "image_url": source.get("url") or "",
            "local_url": source.get("local_url") or "",
            "storage_sha256": source.get("storage_sha256") or "",
            "query": source.get("query") or "",
            "entity_name": source.get("entity_name") or "",
            "entity_type": source.get("entity_type") or "",
            "usage_hint": source.get("usage_hint") or "",
            "strict_identity": bool(source.get("strict_identity")),
        }
        for index, source in enumerate(candidates, start=1)
    ]
    content.append(
        {
            "type": "text",
            "text": f"Select the best visual grounding references for this Creator request.\nPrompt: {_clean_text(prompt, max_chars=900)}\nContext JSON: {json.dumps(_compact_context_for_detector(context), ensure_ascii=False)}\nCandidate metadata: {json.dumps(candidate_metadata, ensure_ascii=False)}\nReturn strict JSON matching the system schema. Use the indexes from candidate metadata.",
        },
    )
    try:
        effective_timeout = (
            timeout
            if timeout is not None
            else model_config.get_vlm_timeout_seconds()
        )
        response = await asyncio.wait_for(
            vlm_model.chat_completion(
                content,
                system_prompt=VISUAL_GROUNDING_VERIFIER_SYSTEM_PROMPT,
                temperature=0.0,
                max_tokens=900,
                timeout=effective_timeout,
            ),
            timeout=effective_timeout,
        )
        verified_sources, trace = _normalized_visual_verification(
            extract_json_payload(response),
            visual_sources,
        )
        logger.info(
            "Visual grounding verification completed status=%s selected=%d rejected=%d",
            trace.get("status"),
            trace.get("selected_count", 0),
            trace.get("rejected_count", 0),
        )
        return (verified_sources, trace)
    except Exception as exc:
        logger.warning("Visual grounding verification failed error=%s", exc)
        for source in visual_sources:
            verification = source.get("verification")
            if (
                not isinstance(verification, dict)
                or str(verification.get("status") or "").casefold()
                != "rejected"
            ):
                source["verification"] = {
                    "status": "error",
                    "reason": f"VLM visual grounding verification failed: {type(exc).__name__}: {exc}",
                }
        return (
            visual_sources,
            {
                "status": "degraded",
                "detail": f"VLM visual grounding verification failed: {type(exc).__name__}: {exc}",
                "model": model_config.get_vlm_model_name(),
            },
        )


def _is_accepted_visual_source(source: dict[str, Any]) -> bool:
    verification = source.get("verification")
    return (
        isinstance(verification, dict)
        and str(verification.get("status") or "").casefold() == "accepted"
    )


def _accepted_visual_fit_score(source: dict[str, Any]) -> float:
    verification = source.get("verification")
    if not isinstance(verification, dict):
        return 0.0
    return _coerce_confidence(verification.get("fit_score"), default=0.0)


def _visual_reference_quality_score(source: dict[str, Any]) -> float:
    verification = source.get("verification")
    if not isinstance(verification, dict):
        return 0.0
    return _coerce_confidence(
        verification.get("reference_quality_score"),
        default=_accepted_visual_fit_score(source),
    )


def _enforce_single_selected_visual_source(
    sources: list[dict[str, Any]],
    *,
    job: dict[str, Any],
) -> list[dict[str, Any]]:
    if bool(job.get("strict_identity")):
        for source in sources:
            if not _is_accepted_visual_source(source):
                continue
            quality_score = _visual_reference_quality_score(source)
            if quality_score >= MIN_STRICT_IDENTITY_REFERENCE_QUALITY:
                continue
            verification = source.get("verification") or {}
            source["verification"] = {
                **verification,
                "status": "rejected",
                "reason": f"Identity may be correct, but the image is not suitable as a primary generation reference (quality={quality_score:.2f}, required>={MIN_STRICT_IDENTITY_REFERENCE_QUALITY:.2f}).",
            }
    selected_seen = False
    ordered = sorted(
        sources,
        key=lambda item: (
            1 if _is_accepted_visual_source(item) else 0,
            _visual_reference_quality_score(item),
            _accepted_visual_fit_score(item),
            -int(item.get("rank") or item.get("index") or 9999),
        ),
        reverse=True,
    )
    for source in ordered:
        if not _is_accepted_visual_source(source):
            continue
        if not selected_seen:
            selected_seen = True
            source["usage"] = str(
                job.get("usage") or source.get("usage_hint") or "context",
            )
            continue
        source["verification"] = {
            "status": "rejected",
            "reason": "Lower-ranked candidate in the same visual grounding group; only one reference is kept per entity/query.",
        }
    return ordered


async def verify_visual_grounding_groups_with_vlm(
    prompt: str,
    visual_sources: list[dict[str, Any]],
    visual_jobs: list[dict[str, Any]],
    *,
    context: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Rank visual refs independently for each entity/query group."""
    if not visual_sources:
        return ([], {"status": "skipped", "detail": "no visual sources"})
    if not visual_jobs:
        return await verify_visual_grounding_with_vlm(
            prompt,
            visual_sources,
            context=context,
            timeout=timeout,
        )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for source in visual_sources:
        key = str(
            source.get("visual_job_key")
            or _clean_query(str(source.get("query") or "")).casefold()
            or "_ungrouped",
        )
        grouped.setdefault(key, []).append(source)

    async def verify_one(
        job: dict[str, Any],
        sources: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        for index, source in enumerate(sources, start=1):
            source["index"] = index
        job_context = dict(context or {})
        job_context["visual_job"] = {
            "query": job.get("query") or "",
            "entity_name": job.get("entity_name") or "",
            "entity_type": job.get("entity_type") or "",
            "usage": job.get("usage") or "context",
            "strict_identity": bool(job.get("strict_identity")),
        }
        job_prompt = prompt
        if job.get("entity_name"):
            job_prompt = f"{prompt}\n\nVisual grounding group: rank images only for entity {job.get('entity_name')} ({job.get('entity_type') or 'unknown'}), usage={job.get('usage') or 'context'}."
        verified, trace = await verify_visual_grounding_with_vlm(
            job_prompt,
            sources,
            context=job_context,
            timeout=timeout,
        )
        if (
            bool(job.get("strict_identity"))
            and str(trace.get("status") or "").casefold() != "success"
        ):
            for source in verified:
                source["verification"] = {
                    "status": "rejected",
                    "reason": "Strict person identity references require successful VLM verification.",
                }
        verified = _enforce_single_selected_visual_source(verified, job=job)
        trace = dict(trace)
        trace["query"] = job.get("query") or ""
        trace["entity_name"] = job.get("entity_name") or ""
        trace["entity_type"] = job.get("entity_type") or ""
        trace["usage"] = job.get("usage") or "context"
        trace["strict_identity"] = bool(job.get("strict_identity"))
        trace["job_key"] = str(job.get("job_key") or _visual_job_key(job))
        trace["selected_count"] = sum(
            (1 for item in verified if _is_accepted_visual_source(item))
        )
        trace["rejected_count"] = len(verified) - trace["selected_count"]
        return (verified, trace)

    tasks: list[Any] = []
    ordered_keys: list[str] = []
    for job in visual_jobs:
        key = str(job.get("job_key") or _visual_job_key(job))
        sources = grouped.get(key) or []
        if not sources:
            continue
        ordered_keys.append(key)
        tasks.append(verify_one(job, sources))
    for key, sources in grouped.items():
        if key in ordered_keys:
            continue
        fallback_job = {
            "query": sources[0].get("query") or key,
            "entity_name": "",
            "entity_type": "",
            "usage": "context",
            "strict_identity": False,
            "job_key": key,
        }
        ordered_keys.append(key)
        tasks.append(verify_one(fallback_job, sources))
    if not tasks:
        return (
            visual_sources,
            {"status": "skipped", "detail": "no non-empty visual groups"},
        )
    results = await asyncio.gather(*tasks)
    merged: list[dict[str, Any]] = []
    group_traces: list[dict[str, Any]] = []
    for group_index, (group_sources, group_trace) in enumerate(
        results,
        start=1,
    ):
        for source in group_sources:
            source["visual_group_rank"] = group_index
            merged.append(source)
        group_traces.append(group_trace)
    merged.sort(
        key=lambda item: (
            1 if _is_accepted_visual_source(item) else 0,
            -int(item.get("visual_group_rank") or 9999),
            _accepted_visual_fit_score(item),
            -int(item.get("rank") or item.get("index") or 9999),
        ),
        reverse=True,
    )
    for rank, source in enumerate(merged, start=1):
        source["rank"] = rank
    statuses = {str(trace.get("status") or "") for trace in group_traces}
    status = (
        "success"
        if "success" in statuses
        else group_traces[0].get("status", "skipped")
    )
    return (
        merged,
        {
            "status": status,
            "model": model_config.get_vlm_model_name(),
            "selected_count": sum(
                (1 for item in merged if _is_accepted_visual_source(item))
            ),
            "rejected_count": sum(
                (1 for item in merged if not _is_accepted_visual_source(item))
            ),
            "groups": group_traces,
        },
    )
