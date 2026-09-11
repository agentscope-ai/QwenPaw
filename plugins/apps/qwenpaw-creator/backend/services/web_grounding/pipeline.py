# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long,protected-access,too-many-branches
# pylint: disable=too-many-nested-blocks,too-many-statements
"""End-to-end web-grounding orchestration and compatibility implementation.

The module has three layers:
- detect whether a prompt depends on external/current facts;
- search configured providers for source-backed web and visual results;
- return compact, source-backed grounding context that downstream modes can use.
"""

from __future__ import annotations

import asyncio
from typing import Any

from models import config as model_config
from utils.logger import setup_logger

from .common import as_list as _as_list
from .common import clean_text as _clean_text
from .providers import search as provider_search
from .rendering import fact_from_source as _fact_from_source
from .rendering import render_grounded_context as _render_grounded_context
from . import staging
from . import triage as grounding_triage
from . import verification
from . import visual_jobs

_clean_query = grounding_triage._clean_query
_compact_context_for_detector = grounding_triage._compact_context_for_detector
_derive_queries = grounding_triage._derive_queries
_detector_mode = grounding_triage._detector_mode
_expand_visual_query_jobs = visual_jobs._expand_visual_query_jobs
_expand_visual_queries = visual_jobs._expand_visual_queries
_filter_visual_search_result_for_job = (
    visual_jobs._filter_visual_search_result_for_job
)
_strict_identity_jobs_without_accepted_refs = (
    visual_jobs._strict_identity_jobs_without_accepted_refs
)
_strict_identity_retry_queries = visual_jobs._strict_identity_retry_queries
_visual_job_key = visual_jobs._visual_job_key
classify_grounding_needs = grounding_triage.classify_grounding_needs
classify_grounding_needs_llm = grounding_triage.classify_grounding_needs_llm
detect_grounding_needs = grounding_triage.detect_grounding_needs
triage_grounding_request = grounding_triage.triage_grounding_request
_accepted_visual_fit_score = verification._accepted_visual_fit_score
_enforce_single_selected_visual_source = (
    verification._enforce_single_selected_visual_source
)
_is_accepted_visual_source = verification._is_accepted_visual_source
_normalized_visual_verification = verification._normalized_visual_verification
_visual_reference_quality_score = verification._visual_reference_quality_score
verify_visual_grounding_groups_with_vlm = (
    verification.verify_visual_grounding_groups_with_vlm
)
verify_visual_grounding_with_vlm = (
    verification.verify_visual_grounding_with_vlm
)
search_visual_refs = provider_search.search_visual_refs
search_visual_refs_by_image = provider_search.search_visual_refs_by_image
search_web = provider_search.search_web
extract_web_pages = provider_search.extract_web_pages
_dedupe_sources = provider_search._dedupe_sources
_dedupe_visual_sources = provider_search._dedupe_visual_sources
_dedupe_visual_sources_with_query_coverage = (
    provider_search._dedupe_visual_sources_with_query_coverage
)

DEFAULT_MAX_SOURCES = 6
DEFAULT_TIMEOUT = 60.0
DEFAULT_IMAGE_DOWNLOAD_TIMEOUT = 30.0
DEFAULT_VISUAL_RESULTS_PER_JOB = 3
logger = setup_logger("services.web_grounding.pipeline")


async def stage_visual_grounding_sources(
    visual_sources: list[dict[str, Any]],
    *,
    timeout: float = DEFAULT_IMAGE_DOWNLOAD_TIMEOUT,
    max_bytes: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Download and content-address candidates through the staging boundary."""
    return await staging.stage_visual_grounding_sources(
        visual_sources,
        timeout=timeout,
        max_bytes=max_bytes,
        downloader=staging.download_visual_source,
    )


async def ground_prompt_context(
    prompt: str,
    context: dict[str, Any] | None = None,
    *,
    queries: list[str] | None = None,
    force: bool = False,
    detect_only: bool = False,
    detector: str | None = None,
    max_sources: int = DEFAULT_MAX_SOURCES,
    timeout: float = DEFAULT_TIMEOUT,
    visual_search_timeout: float | None = None,
    image_download_timeout: float | None = None,
    verification_timeout: float | None = None,
    include_visuals: bool | None = None,
    verify_visuals: bool = True,
) -> dict[str, Any]:
    """Detect grounding needs, search web sources, and return grounded context."""
    prompt = _clean_text(prompt, max_chars=1200)
    context = context if isinstance(context, dict) else {}
    requested_queries = [_clean_query(q) for q in _as_list(queries)]
    requested_queries = [q for q in requested_queries if q]
    if not model_config.get_web_grounding_enabled():
        return {
            "ok": True,
            "status": "skipped",
            "needs_grounding": False,
            "need_websearch": False,
            "confidence": 1.0,
            "reasons": ["grounding is disabled in Creator settings"],
            "queries": requested_queries,
            "entities": [],
            "detector": "disabled",
            "detector_issues": [],
            "domain": "",
            "include_visuals": False,
            "facts": [],
            "sources": [],
            "visual_sources": [],
            "visual_download": {
                "status": "skipped",
                "detail": "grounding disabled",
                "downloaded_count": 0,
                "failed_count": 0,
            },
            "visual_verification": {
                "status": "skipped",
                "detail": "grounding disabled",
            },
            "grounded_context": "",
            "issues": ["grounding_disabled"],
            "triage": {},
            "next_action_hints": [
                "Proceed without web grounding; it is disabled in settings.",
            ],
        }
    effective_visual_search_timeout = float(
        (
            visual_search_timeout
            if visual_search_timeout is not None
            else model_config.get_web_grounding_visual_search_timeout_seconds()
        ),
    )
    effective_image_download_timeout = float(
        (
            image_download_timeout
            if image_download_timeout is not None
            else model_config.get_web_grounding_image_download_timeout_seconds()
        ),
    )
    effective_verification_timeout = float(
        (
            verification_timeout
            if verification_timeout is not None
            else model_config.get_web_grounding_verification_timeout_seconds()
        ),
    )
    logger.info(
        "Ground prompt context started prompt_len=%d requested_queries=%d force=%s detect_only=%s include_visuals=%s detector=%s",
        len(prompt),
        len(requested_queries),
        force,
        detect_only,
        include_visuals,
        detector or _detector_mode(None),
    )

    triage = await triage_grounding_request(
        prompt,
        context=context,
        queries=requested_queries,
        force=force,
        detector=detector,
    )
    effective_include_visuals = (
        bool(include_visuals)
        if include_visuals is not None
        else bool(triage.get("include_visuals"))
    )
    analysis = {
        key: triage[key]
        for key in (
            "needs_grounding",
            "need_websearch",
            "confidence",
            "reasons",
            "queries",
            "entities",
            "detector",
            "detector_issues",
            "domain",
            "include_visuals",
        )
        if key in triage
    }
    analysis["include_visuals"] = effective_include_visuals

    if detect_only:
        logger.info(
            "Ground prompt context detected status=detected needs_grounding=%s queries=%d detector=%s",
            analysis.get("needs_grounding"),
            len(analysis.get("queries") or []),
            analysis.get("detector"),
        )
        return {"ok": True, "status": "detected", **analysis, "triage": triage}

    if not analysis["needs_grounding"]:
        logger.info(
            "Ground prompt context skipped needs_grounding=false detector=%s",
            analysis.get("detector"),
        )
        return {
            "ok": True,
            "status": "skipped",
            **analysis,
            "facts": [],
            "sources": [],
            "visual_sources": [],
            "visual_download": {
                "status": "skipped",
                "detail": "grounding not needed",
                "downloaded_count": 0,
                "failed_count": 0,
            },
            "visual_verification": {
                "status": "skipped",
                "detail": "grounding not needed",
            },
            "grounded_context": "",
            "issues": [],
            "triage": triage,
            "next_action_hints": [
                "Proceed without web grounding; prompt appears self-contained.",
            ],
        }

    max_primary_queries = grounding_triage.DEFAULT_MAX_PRIMARY_QUERIES
    suggested_queries = list(
        dict.fromkeys(analysis.get("queries") or _derive_queries(prompt)),
    )[:max_primary_queries]
    planned_visual_jobs = (
        _expand_visual_query_jobs(
            suggested_queries,
            context=context,
            entities=list(analysis.get("entities") or []),
            max_visual_queries=max(DEFAULT_MAX_SOURCES, max_sources),
        )
        if effective_include_visuals
        else []
    )

    def _suggested_query_index(job: dict[str, Any]) -> int:
        entity_name = str(job.get("entity_name") or "").casefold()
        job_query = str(job.get("query") or "").casefold()
        return next(
            (
                index
                for index, query in enumerate(suggested_queries)
                if (entity_name and entity_name in query.casefold())
                or (not entity_name and job_query == query.casefold())
            ),
            len(suggested_queries),
        )

    planned_visual_jobs.sort(key=_suggested_query_index)
    visual_queries = [str(job["query"]) for job in planned_visual_jobs]
    identity_names = [
        str(job.get("entity_name") or "").strip()
        for job in planned_visual_jobs
        if bool(job.get("strict_identity"))
        and str(job.get("entity_name") or "").strip()
    ]
    identity_names.sort(
        key=lambda name: next(
            (
                index
                for index, query in enumerate(suggested_queries)
                if name.casefold() in query.casefold()
            ),
            len(suggested_queries),
        ),
    )
    planned_text_queries = [
        f"{name} official profile biography" for name in identity_names
    ]
    planned_text_queries.extend(
        query
        for query in suggested_queries
        if not any(
            name.casefold() in query.casefold() for name in identity_names
        )
    )
    search_queries = list(
        dict.fromkeys(planned_text_queries or suggested_queries),
    )[:max_primary_queries]
    all_sources: list[dict[str, Any]] = []
    all_visual_sources: list[dict[str, Any]] = []
    visual_providers: list[str] = []
    visual_providers_attempted: list[str] = []
    visual_search_trace: list[dict[str, Any]] = []
    visual_identity_retry: dict[str, Any] = {
        "status": "skipped",
        "detail": "no strict identity retry needed",
    }
    identity_confirmation: dict[str, Any] = {
        "status": "skipped",
        "detail": "no Lens identity candidate required confirmation",
        "candidates": [],
    }
    issues: list[str] = list(analysis.get("detector_issues") or [])

    async def _safe_search_web(query: str) -> dict[str, Any]:
        try:
            return await search_web(
                query,
                max_sources=max_sources,
                timeout=timeout,
            )
        except (
            Exception
        ) as exc:  # noqa: BLE001 - grounding should degrade, not crash the agent turn
            logger.warning(
                "Web grounding search task failed query=%r error=%s",
                query,
                exc,
            )
            return {
                "query": query,
                "sources": [],
                "issues": [f"search_web:{exc.__class__.__name__}: {exc}"],
                "provider": "",
            }

    async def _safe_search_visual_refs(job: dict[str, Any]) -> dict[str, Any]:
        query = str(job.get("query") or "")
        reference_image = str(job.get("reference_image") or "").strip()
        reference_bbox = job.get("reference_bbox")
        try:
            lens_issues: list[str] = []
            lens_attempted: list[str] = []
            if reference_image:
                # Serper Lens reverse image search runs first when the entity
                # carries a reference image; text search remains the fallback.
                lens_kwargs: dict[str, Any] = {
                    "query": query,
                    "max_sources": min(
                        DEFAULT_VISUAL_RESULTS_PER_JOB,
                        max_sources,
                    ),
                    "timeout": effective_visual_search_timeout,
                }
                if isinstance(reference_bbox, (list, tuple)):
                    lens_kwargs["bbox"] = list(reference_bbox)
                lens_result = await search_visual_refs_by_image(
                    reference_image,
                    **lens_kwargs,
                )
                if lens_result.get("visual_sources"):
                    lens_result["visual_job"] = job
                    return lens_result
                lens_issues = list(lens_result.get("issues") or [])
                lens_attempted = list(
                    lens_result.get("providers_attempted") or [],
                )
            result = await search_visual_refs(
                query,
                max_sources=min(DEFAULT_VISUAL_RESULTS_PER_JOB, max_sources),
                timeout=effective_visual_search_timeout,
            )
            if lens_issues:
                result["issues"] = [
                    *lens_issues,
                    *(result.get("issues") or []),
                ]
            if lens_attempted:
                result["providers_attempted"] = [
                    *lens_attempted,
                    *(result.get("providers_attempted") or []),
                ]
            result["visual_job"] = job
            return result
        except (
            Exception
        ) as exc:  # noqa: BLE001 - visual grounding should degrade independently
            logger.warning(
                "Visual grounding search task failed query=%r error=%s",
                query,
                exc,
            )
            return {
                "query": query,
                "visual_sources": [],
                "issues": [
                    f"search_visual_refs:{exc.__class__.__name__}: {exc}",
                ],
                "provider": "",
                "providers": [],
                "providers_attempted": [],
                "visual_job": job,
            }

    text_tasks = [
        asyncio.create_task(_safe_search_web(query))
        for query in search_queries
    ]
    visual_tasks = (
        [
            asyncio.create_task(_safe_search_visual_refs(job))
            for job in planned_visual_jobs
        ]
        if effective_include_visuals
        else []
    )

    text_results = await asyncio.gather(*text_tasks) if text_tasks else []
    visual_results = (
        await asyncio.gather(*visual_tasks) if visual_tasks else []
    )

    for result in text_results:
        all_sources.extend(result.get("sources") or [])
        issues.extend(result.get("issues") or [])
    for visual_result in visual_results:
        job = (
            visual_result.get("visual_job")
            if isinstance(visual_result.get("visual_job"), dict)
            else {}
        )
        (
            filtered_visual_sources,
            result_issues,
            result_trace,
        ) = _filter_visual_search_result_for_job(
            visual_result,
            job,
        )
        all_visual_sources.extend(filtered_visual_sources)
        issues.extend(result_issues)
        visual_providers.extend(
            str(item)
            for item in (visual_result.get("providers") or [])
            if item
        )
        visual_providers_attempted.extend(
            str(item)
            for item in (visual_result.get("providers_attempted") or [])
            if item
        )
        visual_search_trace.append(result_trace)

    lens_candidates: list[str] = []
    for source in all_visual_sources:
        if source.get("provider") != "serper_lens" or not source.get(
            "strict_identity",
        ):
            continue
        candidate = _clean_text(source.get("title"), max_chars=140)
        if candidate and candidate.casefold() not in {
            "match",
            "lens match",
            "untitled",
        }:
            lens_candidates.append(candidate)
    lens_candidates = list(dict.fromkeys(lens_candidates))[:2]
    if lens_candidates:
        confirmation_sources: list[dict[str, Any]] = []
        confirmation_trace: list[dict[str, Any]] = []
        for candidate in lens_candidates:
            confirmation_query = f"{candidate} official identity"
            search_result = await _safe_search_web(confirmation_query)
            candidate_sources = list(search_result.get("sources") or [])
            issues.extend(search_result.get("issues") or [])
            trace_item: dict[str, Any] = {
                "candidate": candidate,
                "query": confirmation_query,
                "search_sources": len(candidate_sources),
                "extracted_sources": 0,
                "status": "insufficient_evidence",
            }
            if candidate_sources:
                extraction = await extract_web_pages(
                    [str(candidate_sources[0].get("url") or "")],
                    goal=f"Confirm the specific identity and facts for {candidate}",
                    timeout=timeout,
                )
                extracted_sources = list(extraction.get("sources") or [])
                confirmation_sources.extend(extracted_sources)
                confirmation_sources.extend(candidate_sources)
                issues.extend(extraction.get("issues") or [])
                trace_item["extracted_sources"] = len(extracted_sources)
                candidate_key = candidate.casefold()
                candidate_supported = any(
                    candidate_key
                    in " ".join(
                        (
                            str(source.get("title") or ""),
                            str(source.get("content") or ""),
                            str(source.get("snippet") or ""),
                        ),
                    ).casefold()
                    for source in extracted_sources
                )
                trace_item["status"] = (
                    "confirmed"
                    if candidate_supported
                    else (
                        "conflicting_or_thin_evidence"
                        if extracted_sources
                        else "search_only"
                    )
                )
            confirmation_trace.append(trace_item)
        all_sources = [*confirmation_sources, *all_sources]
        identity_confirmation = {
            "status": (
                "confirmed"
                if any(
                    item["status"] == "confirmed"
                    for item in confirmation_trace
                )
                else "insufficient_evidence"
            ),
            "detail": "Lens candidates were cross-checked with web search and page extraction",
            "candidates": confirmation_trace,
        }

    sources = _dedupe_sources(all_sources, max_sources=max_sources)
    for index, source in enumerate(sources, start=1):
        source["index"] = index
    facts = [
        fact
        for index, source in enumerate(sources, start=1)
        if (fact := _fact_from_source(source, index))
    ]
    visual_sources: list[dict[str, Any]] = []
    if effective_include_visuals:
        for job in planned_visual_jobs:
            job_key = str(job.get("job_key") or _visual_job_key(job))
            job_sources = [
                source
                for source in all_visual_sources
                if str(source.get("visual_job_key") or "") == job_key
            ]
            visual_sources.extend(
                _dedupe_visual_sources(
                    job_sources,
                    max_sources=min(
                        DEFAULT_VISUAL_RESULTS_PER_JOB,
                        max_sources,
                    ),
                ),
            )
    if effective_include_visuals and visual_sources:
        visual_sources, visual_download = await stage_visual_grounding_sources(
            visual_sources,
            timeout=effective_image_download_timeout,
        )
        issues.extend(visual_download.get("issues") or [])
    else:
        visual_download = {
            "status": "skipped",
            "detail": (
                "visual grounding not requested"
                if not effective_include_visuals
                else "no visual search candidates"
            ),
            "downloaded_count": 0,
            "failed_count": 0,
        }
    if effective_include_visuals and verify_visuals:
        (
            visual_sources,
            visual_verification,
        ) = await verify_visual_grounding_groups_with_vlm(
            prompt,
            visual_sources,
            planned_visual_jobs,
            context=context,
            timeout=effective_verification_timeout,
        )
        missing_strict_jobs = _strict_identity_jobs_without_accepted_refs(
            planned_visual_jobs,
            visual_sources,
        )
        if missing_strict_jobs:
            retry_jobs: list[dict[str, Any]] = []
            for job in missing_strict_jobs:
                for retry_query in _strict_identity_retry_queries(job):
                    retry_jobs.append({**job, "query": retry_query})

            retry_visual_results = (
                await asyncio.gather(
                    *[
                        asyncio.create_task(_safe_search_visual_refs(job))
                        for job in retry_jobs
                    ],
                )
                if retry_jobs
                else []
            )
            retry_candidates: list[dict[str, Any]] = []
            retry_providers: list[str] = []
            retry_attempted: list[str] = []
            for visual_result in retry_visual_results:
                job = (
                    visual_result.get("visual_job")
                    if isinstance(visual_result.get("visual_job"), dict)
                    else {}
                )
                (
                    filtered_visual_sources,
                    result_issues,
                    result_trace,
                ) = _filter_visual_search_result_for_job(
                    visual_result,
                    job,
                    retry=True,
                )
                retry_candidates.extend(filtered_visual_sources)
                issues.extend(result_issues)
                visual_search_trace.append(result_trace)
                retry_providers.extend(
                    str(item)
                    for item in (visual_result.get("providers") or [])
                    if item
                )
                retry_attempted.extend(
                    str(item)
                    for item in (
                        visual_result.get("providers_attempted") or []
                    )
                    if item
                )
                visual_providers.extend(
                    str(item)
                    for item in (visual_result.get("providers") or [])
                    if item
                )
                visual_providers_attempted.extend(
                    str(item)
                    for item in (
                        visual_result.get("providers_attempted") or []
                    )
                    if item
                )

            existing_urls = {
                str(source.get("url") or "").strip().casefold()
                for source in visual_sources
                if str(source.get("url") or "").strip()
            }
            retry_visual_sources: list[dict[str, Any]] = []
            for job in missing_strict_jobs:
                job_key = str(job.get("job_key") or _visual_job_key(job))
                job_sources = [
                    source
                    for source in retry_candidates
                    if str(source.get("visual_job_key") or "") == job_key
                    and str(source.get("url") or "").strip().casefold()
                    not in existing_urls
                ]
                retry_visual_sources.extend(
                    _dedupe_visual_sources(
                        job_sources,
                        max_sources=DEFAULT_MAX_SOURCES,
                    ),
                )

            retry_download: dict[str, Any] = {
                "status": "skipped",
                "detail": "no strict identity retry candidates",
                "downloaded_count": 0,
                "failed_count": 0,
            }
            retry_verification: dict[str, Any] = {
                "status": "skipped",
                "detail": "no strict identity retry candidates",
            }
            if retry_visual_sources:
                (
                    retry_visual_sources,
                    retry_download,
                ) = await stage_visual_grounding_sources(
                    retry_visual_sources,
                    timeout=effective_image_download_timeout,
                )
                issues.extend(retry_download.get("issues") or [])
                (
                    retry_visual_sources,
                    retry_verification,
                ) = await verify_visual_grounding_groups_with_vlm(
                    prompt,
                    retry_visual_sources,
                    missing_strict_jobs,
                    context=context,
                    timeout=effective_verification_timeout,
                )
                visual_sources.extend(retry_visual_sources)
                visual_sources.sort(
                    key=lambda item: (
                        1 if _is_accepted_visual_source(item) else 0,
                        _accepted_visual_fit_score(item),
                        -int(item.get("visual_group_rank") or 9999),
                        -int(item.get("rank") or item.get("index") or 9999),
                    ),
                    reverse=True,
                )
                for rank, source in enumerate(visual_sources, start=1):
                    source["rank"] = rank

                visual_verification = dict(visual_verification)
                initial_groups = list(visual_verification.get("groups") or [])
                retry_groups = []
                for group in retry_verification.get("groups") or []:
                    if isinstance(group, dict):
                        retry_group = dict(group)
                        retry_group["retry"] = True
                        retry_groups.append(retry_group)
                for retry_group in retry_groups:
                    retry_key = str(retry_group.get("job_key") or "")
                    replaced = False
                    for index, group in enumerate(initial_groups):
                        group_key = str(group.get("job_key") or "")
                        if retry_key and group_key == retry_key:
                            if int(
                                retry_group.get("selected_count") or 0,
                            ) >= int(group.get("selected_count") or 0):
                                initial_groups[index] = retry_group
                            replaced = True
                            break
                    if not replaced:
                        initial_groups.append(retry_group)
                visual_verification["groups"] = initial_groups
                visual_verification["selected_count"] = sum(
                    1
                    for item in visual_sources
                    if _is_accepted_visual_source(item)
                )
                visual_verification["rejected_count"] = sum(
                    1
                    for item in visual_sources
                    if not _is_accepted_visual_source(item)
                )

            missing_after_retry = _strict_identity_jobs_without_accepted_refs(
                planned_visual_jobs,
                visual_sources,
            )
            visual_identity_retry = {
                "status": "success" if not missing_after_retry else "degraded",
                "attempted_jobs": [
                    str(job.get("entity_name") or job.get("query") or "")
                    for job in missing_strict_jobs
                ],
                "missing_jobs": [
                    str(job.get("entity_name") or job.get("query") or "")
                    for job in missing_after_retry
                ],
                "queries": [str(job.get("query") or "") for job in retry_jobs],
                "providers": list(dict.fromkeys(retry_providers)),
                "providers_attempted": list(dict.fromkeys(retry_attempted)),
                "visual_download": retry_download,
                "visual_verification": retry_verification,
            }
            visual_verification = dict(visual_verification)
            visual_verification[
                "strict_identity_retry"
            ] = visual_identity_retry
    else:
        visual_verification = {
            "status": "skipped",
            "detail": (
                "visual grounding not requested"
                if not effective_include_visuals
                else "visual verification disabled"
            ),
        }
    missing_strict_jobs = (
        _strict_identity_jobs_without_accepted_refs(
            planned_visual_jobs,
            visual_sources,
        )
        if effective_include_visuals and verify_visuals
        else []
    )
    for job in missing_strict_jobs:
        issues.append(
            f"strict_identity_reference_missing:{job.get('entity_name') or job.get('query') or 'unknown'}",
        )

    if effective_include_visuals and verify_visuals:
        usable_visual_sources = [
            source
            for source in visual_sources
            if _is_accepted_visual_source(source)
        ]
    else:
        usable_visual_sources = list(visual_sources)
    status = (
        "success"
        if (sources or usable_visual_sources) and not missing_strict_jobs
        else "degraded"
    )
    if not sources and not usable_visual_sources:
        issues.append("no_sources_found")
    elif not sources:
        issues.append("no_text_sources_found")

    logger.info(
        "Ground prompt context completed status=%s queries=%d sources=%d visual_sources=%d issues=%d",
        status,
        len(search_queries),
        len(sources),
        len(visual_sources),
        len(set(issues)),
    )
    provider_names = list(
        dict.fromkeys(
            [
                str(source.get("provider") or "")
                for source in [*sources, *visual_sources]
                if str(source.get("provider") or "").strip()
            ],
        ),
    )
    visual_providers = list(dict.fromkeys(visual_providers))
    visual_providers_attempted = list(
        dict.fromkeys(visual_providers_attempted),
    )

    return {
        "ok": True,
        "status": status,
        **analysis,
        "suggested_queries": suggested_queries,
        "queries": search_queries,
        "visual_queries": visual_queries,
        "query_plan": {
            "text": search_queries,
            "visual": visual_queries,
        },
        "visual_jobs": [
            {
                "query": job.get("query") or "",
                "entity_name": job.get("entity_name") or "",
                "entity_type": job.get("entity_type") or "",
                "usage": job.get("usage") or "context",
                "strict_identity": bool(job.get("strict_identity")),
                "reference_bbox": job.get("reference_bbox"),
            }
            for job in planned_visual_jobs
        ],
        "facts": facts,
        "sources": sources,
        "visual_sources": visual_sources,
        "visual_search_trace": visual_search_trace,
        "identity_confirmation": identity_confirmation,
        "visual_download": visual_download,
        "visual_verification": visual_verification,
        "grounded_context": _render_grounded_context(
            search_queries,
            facts,
            sources,
            visual_sources,
        ),
        "issues": list(dict.fromkeys(issues)),
        "provider": provider_names[-1] if provider_names else "",
        "providers": provider_names,
        "visual_providers": visual_providers,
        "visual_providers_attempted": visual_providers_attempted,
        "triage": triage,
        "next_action_hints": [
            "Use grounded_context as source-backed context before generating or editing factual content.",
            "When visual_sources are present, use them as image-backed identity, style, product, place, or cultural reference cues.",
            "If sources are sparse, ask for narrower entities or provide references.",
        ],
    }
