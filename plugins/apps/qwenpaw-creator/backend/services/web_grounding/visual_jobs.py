# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long,too-many-branches
"""Per-entity visual query jobs and strict-identity policy."""

from __future__ import annotations

import json
import re
from typing import Any

from .common import clean_text as _clean_text
from .common import coerce_bool as _coerce_bool
from .triage import _clean_query
from .triage import _normalize_entities


def _is_accepted_visual_source(source: dict[str, Any]) -> bool:
    verification = source.get("verification")
    return (
        isinstance(verification, dict)
        and str(verification.get("status") or "").casefold() == "accepted"
    )


DEFAULT_STRICT_IDENTITY_RETRY_QUERY_COUNT = 3

_VISUAL_ENTITY_TYPES = {
    "person",
    "sports_player",
    "team",
    "brand",
    "product",
    "place",
    "event",
    "ip",
    "media_work",
    "style",
    "visual_style",
    "fashion",
    "costume",
    "jewelry",
    "cultural_artifact",
    "craft",
    "motif",
}

_PERSON_VISUAL_HINT_RE = re.compile(
    "\\b(person|public_person|celebrity|athlete|sports_player|footballer|player|actor|singer|model)\\b|人物|名人|球员|运动员|演员|歌手|模特",
    re.IGNORECASE,
)

_PERSON_QUERY_HINT_RE = re.compile(
    "\\b(appearance|look|looks|facial|face|portrait|headshot|likeness|identity|persona|casual|unstyled|styled|fashion|outfit|personality|traits|physical\\s+features?|recognizable\\s+features?|funny\\s+moments?|off[-\\s]?pitch|celebration|real)\\b|外貌|长相|脸|肖像|本人|身份|造型|穿搭|性格|真人",
    re.IGNORECASE,
)

_LEADING_NAMED_ENTITY_RE = re.compile(
    r"^([A-Z][A-Za-z'’-]*(?:\s+[A-Z][A-Za-z'’-]*){0,3})(?=\s|$)",
)

_SHOW_VISUAL_HINT_RE = re.compile(
    "\\b(show|program|series|movie|film|anime|game|ip|stage|venue|event|idol\\s+producer|produce\\s+101|talent\\s+show|reality\\s+show|survival\\s+show)\\b|节目|综艺|舞台|赛事|场馆|电影|动漫|游戏|IP",
    re.IGNORECASE,
)

_STYLE_VISUAL_HINT_RE = re.compile(
    "\\b(style|fashion|costume|jewelry|motif|craft|design|uniform)\\b|风格|时尚|服装|制服|饰品|银饰|纹样|工艺|设计",
    re.IGNORECASE,
)

_PERSON_IDENTITY_ENTITY_TYPES = {
    "person",
    "public_person",
    "celebrity",
    "athlete",
    "sports_player",
    "footballer",
    "player",
    "actor",
    "singer",
    "model",
}

_SHOW_CONTEXT_ENTITY_TYPES = {
    "ip",
    "media_work",
    "show",
    "program",
    "series",
    "movie",
    "film",
    "anime",
    "game",
    "event",
    "venue",
}

_STYLE_ENTITY_TYPES = {
    "style",
    "visual_style",
    "fashion",
    "costume",
    "jewelry",
    "cultural_artifact",
    "craft",
    "motif",
}

_PERSON_IDENTITY_REJECT_RE = re.compile(
    "\\b(redbubble|teepublic|zazzle|etsy|deviantart|artstation|pinterest|pinimg|postcard|sticker|poster|print|canvas|merch|t-shirt|shirt|hoodie|fan[-\\s]?art|fanart|drawing|illustration|illustrated|cartoon|anime|sketch|painting|vector|clipart|caricature|avatar|wall art|ai[-\\s]?generated|midjourney|stable diffusion|render|cosplay|app store|google play|mobile game|game art)\\b|同人|插画|漫画|动漫|卡通|手绘|绘画|海报|明信片|贴纸|周边|应用商店|游戏|AI生成",
    re.IGNORECASE,
)


def _context_entity_descriptions(
    context: dict[str, Any] | None,
) -> dict[str, str]:
    if not isinstance(context, dict):
        return {}
    descriptions: dict[str, str] = {}
    base_profile = context.get("base_profile") or context.get("target_profile")
    if isinstance(base_profile, dict):
        name = _clean_text(
            base_profile.get("name")
            or base_profile.get("canonical")
            or base_profile.get("canonical_name"),
            max_chars=120,
        )
        if name:
            descriptions[name] = _clean_text(
                " ".join(
                    (
                        str(base_profile.get(key) or "")
                        for key in (
                            "description",
                            "raw_request",
                            "type",
                            "role",
                        )
                    )
                ),
                max_chars=240,
            )
        for key, value in base_profile.items():
            if key in {
                "name",
                "canonical",
                "canonical_name",
                "aliases",
                "raw_request",
            }:
                continue
            entity_name = _clean_text(key, max_chars=120)
            if not entity_name:
                continue
            if isinstance(value, str):
                descriptions.setdefault(
                    entity_name,
                    _clean_text(value, max_chars=240),
                )
            elif isinstance(value, dict):
                descriptions.setdefault(
                    entity_name,
                    _clean_text(
                        json.dumps(value, ensure_ascii=False),
                        max_chars=240,
                    ),
                )
    return descriptions


def _visual_entities_from_context(
    context: dict[str, Any] | None,
    entities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    def _visual_type(name: str, entity_type: str, description: str) -> str:
        normalized_type = _clean_text(entity_type, max_chars=80).lower()
        if normalized_type and normalized_type != "other":
            return normalized_type
        haystack = f"{name} {normalized_type} {description}"
        if _PERSON_VISUAL_HINT_RE.search(haystack):
            return "person"
        if _STYLE_VISUAL_HINT_RE.search(haystack):
            return "style"
        if _SHOW_VISUAL_HINT_RE.search(haystack):
            return "ip"
        return normalized_type or "other"

    descriptions = _context_entity_descriptions(context)
    candidates: list[dict[str, Any]] = []
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        name = _clean_text(
            entity.get("canonical") or entity.get("text"),
            max_chars=120,
        )
        if not name:
            continue
        description = descriptions.get(name, "")
        candidates.append(
            {
                "name": name,
                "type": _visual_type(
                    name,
                    str(entity.get("type") or ""),
                    description,
                ),
                "description": description,
                "visual_usage": _clean_text(
                    entity.get("visual_usage"),
                    max_chars=40,
                ),
                "strict_identity": entity.get("strict_identity"),
                "needs_visual_grounding": entity.get("needs_visual_grounding"),
                "reference_image": str(
                    entity.get("reference_image") or "",
                ).strip(),
                "reference_bbox": entity.get("reference_bbox"),
            },
        )
    if isinstance(context, dict):
        for entity in _normalize_entities(context.get("entities")):
            name = _clean_text(
                entity.get("canonical") or entity.get("text"),
                max_chars=120,
            )
            if not name:
                continue
            description = descriptions.get(name, "")
            candidates.append(
                {
                    "name": name,
                    "type": _visual_type(
                        name,
                        str(entity.get("type") or ""),
                        description,
                    ),
                    "description": description,
                    "visual_usage": _clean_text(
                        entity.get("visual_usage"),
                        max_chars=40,
                    ),
                    "strict_identity": entity.get("strict_identity"),
                    "needs_visual_grounding": entity.get(
                        "needs_visual_grounding",
                    ),
                    "reference_image": str(
                        entity.get("reference_image") or "",
                    ).strip(),
                    "reference_bbox": entity.get("reference_bbox"),
                },
            )
    for name, description in descriptions.items():
        candidates.append(
            {
                "name": name,
                "type": _visual_type(name, "", description),
                "description": description,
                "visual_usage": "",
                "strict_identity": None,
                "needs_visual_grounding": None,
            },
        )
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = candidate["name"].lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped[:6]


def _entity_visual_query(entity: dict[str, Any]) -> str:
    name = _clean_query(entity.get("name"))
    if not name:
        return ""
    entity_type = _clean_text(entity.get("type"), max_chars=80)
    description = _clean_text(entity.get("description"), max_chars=240)
    haystack = f"{name} {entity_type} {description}"
    if _PERSON_VISUAL_HINT_RE.search(haystack):
        # Identity retrieval should not inherit editorial modifiers or arbitrary
        # years from upstream free-form queries. Those terms tend to return
        # galleries, group shots, fashion coverage, and action photos instead of
        # a clean generation reference for the named person.
        return _clean_query(
            f"{name} official profile portrait clear face single person",
        )
    if _STYLE_VISUAL_HINT_RE.search(haystack):
        return _clean_query(f"{name} visual style costume design reference")
    if _SHOW_VISUAL_HINT_RE.search(haystack):
        return _clean_query(f"{name} official poster stage visual style")
    return _clean_query(f"{name} visual reference")


def _visual_entity_usage(entity: dict[str, Any]) -> str:
    explicit = _clean_text(entity.get("visual_usage"), max_chars=40).lower()
    if explicit in {
        "identity",
        "style",
        "logo",
        "product",
        "place",
        "context",
    }:
        return explicit
    entity_type = _clean_text(entity.get("type"), max_chars=80).lower()
    description = _clean_text(entity.get("description"), max_chars=240)
    haystack = f"{entity.get('name') or ''} {entity_type} {description}"
    if (
        entity_type in _PERSON_IDENTITY_ENTITY_TYPES
        or _PERSON_VISUAL_HINT_RE.search(haystack)
    ):
        return "identity"
    if entity_type in _STYLE_ENTITY_TYPES or _STYLE_VISUAL_HINT_RE.search(
        haystack,
    ):
        return "style"
    if (
        entity_type in _SHOW_CONTEXT_ENTITY_TYPES
        or _SHOW_VISUAL_HINT_RE.search(haystack)
    ):
        return "context"
    return "context"


def _explicit_or_inferred_bool(value: Any, *, inferred: bool) -> bool:
    if value is not None:
        return _coerce_bool(value)
    return bool(inferred)


def _enrich_visual_entity_contract(
    entities: list[dict[str, Any]],
    *,
    include_visuals: bool,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        candidate = dict(entity)
        name = _clean_text(
            candidate.get("canonical")
            or candidate.get("text")
            or candidate.get("name"),
            max_chars=120,
        )
        entity_type = _clean_text(candidate.get("type"), max_chars=80).lower()
        explicit_visual_usage = _clean_text(
            candidate.get("visual_usage"),
            max_chars=40,
        ).lower()
        visual_usage = _visual_entity_usage(
            {
                "name": name,
                "type": entity_type,
                "description": _clean_text(
                    candidate.get("description"),
                    max_chars=240,
                ),
                "visual_usage": explicit_visual_usage,
            },
        )
        explicitly_needs_visual = _coerce_bool(
            candidate.get("needs_visual_grounding"),
        )
        needs_visual = bool(include_visuals) and (
            entity_type in _VISUAL_ENTITY_TYPES
            or explicitly_needs_visual
            or explicit_visual_usage
            in {"identity", "style", "logo", "product", "place", "context"}
        )
        candidate.setdefault("visual_usage", visual_usage)
        candidate["needs_visual_grounding"] = (
            explicitly_needs_visual or needs_visual
        )
        candidate["strict_identity"] = _explicit_or_inferred_bool(
            candidate.get("strict_identity"),
            inferred=needs_visual and visual_usage == "identity",
        )
        enriched.append(candidate)
    return enriched


def _visual_job_key(job: dict[str, Any]) -> str:
    key = _clean_text(job.get("entity_key") or "", max_chars=240).casefold()
    if key:
        return key
    return _clean_query(str(job.get("query") or "")).casefold()


def _recover_person_entities_from_queries(
    search_queries: list[str],
) -> list[dict[str, Any]]:
    """Conservatively recover named people from explicit identity-like queries.

    Search-query generation commonly canonicalizes a person to an English proper
    name even when the upstream detector misses the entity in the original prompt.
    Only queries with strong person/identity cues participate, avoiding conversion
    of generic title-cased style or venue queries into identity jobs.
    """
    names: list[str] = []
    for query in search_queries:
        clean_query = _clean_query(query)
        if not clean_query or not (
            _PERSON_QUERY_HINT_RE.search(clean_query)
            or _PERSON_VISUAL_HINT_RE.search(clean_query)
        ):
            continue
        match = _LEADING_NAMED_ENTITY_RE.match(clean_query)
        if not match:
            continue
        name = _clean_text(match.group(1), max_chars=120)
        if name:
            names.append(name)

    # Prefer the most informative canonical form and collapse surname-only aliases.
    canonical: list[str] = []
    for name in sorted(
        set(names),
        key=lambda item: (-len(item.split()), -len(item)),
    ):
        folded = name.casefold()
        if any(
            folded == existing.casefold()
            or folded in {part.casefold() for part in existing.split()}
            for existing in canonical
        ):
            continue
        canonical.append(name)
    return [
        {
            "name": name,
            "type": "person",
            "description": "Recovered from an explicit person identity query.",
            "visual_usage": "identity",
            "strict_identity": True,
            "needs_visual_grounding": True,
        }
        for name in canonical[:6]
    ]


def _expand_visual_query_jobs(
    search_queries: list[str],
    *,
    context: dict[str, Any] | None,
    entities: list[dict[str, Any]],
    max_visual_queries: int,
) -> list[dict[str, Any]]:
    query_haystack = " ".join(search_queries)
    jobs: list[dict[str, Any]] = []
    visual_entities = _visual_entities_from_context(context, entities)
    recovered_entities = False
    if not visual_entities:
        visual_entities = _recover_person_entities_from_queries(search_queries)
        recovered_entities = bool(visual_entities)
    for entity in visual_entities:
        entity_name = _clean_text(entity.get("name"), max_chars=120)
        entity_type = _clean_text(entity.get("type"), max_chars=80).lower()
        if entity.get("needs_visual_grounding") is False:
            continue
        if entity_type in {"", "other"} and entity_name:
            entity_query_haystack = (
                " ".join(
                    (
                        query
                        for query in search_queries
                        if entity_name.casefold() in query.casefold()
                    )
                )
                or query_haystack
            )
            if _PERSON_QUERY_HINT_RE.search(entity_query_haystack):
                entity = {**entity, "type": "person"}
        query = _entity_visual_query(entity)
        if not query:
            continue
        usage = _visual_entity_usage(entity)
        entity_type = _clean_text(entity.get("type"), max_chars=80).lower()
        jobs.append(
            {
                "query": query,
                "entity_name": entity_name,
                "entity_type": entity_type,
                "entity_key": f"{entity_name.casefold()}\x1f{entity_type}",
                "description": _clean_text(
                    entity.get("description"),
                    max_chars=240,
                ),
                "usage": usage,
                "reference_image": str(
                    entity.get("reference_image") or "",
                ).strip(),
                "reference_bbox": entity.get("reference_bbox"),
                "strict_identity": _explicit_or_inferred_bool(
                    entity.get("strict_identity"),
                    inferred=usage == "identity"
                    and (
                        entity_type in _PERSON_IDENTITY_ENTITY_TYPES
                        or bool(
                            _PERSON_VISUAL_HINT_RE.search(
                                f"{entity_name} {entity_type}",
                            ),
                        )
                    ),
                ),
            },
        )
    if recovered_entities:
        recovered_names = [
            str(entity.get("name") or "").casefold()
            for entity in visual_entities
        ]
        for query in search_queries:
            clean_query = _clean_query(query)
            folded_query = clean_query.casefold()
            leading_match = _LEADING_NAMED_ENTITY_RE.match(clean_query)
            leading_name = (
                leading_match.group(1).casefold() if leading_match else ""
            )
            belongs_to_recovered_person = any(
                name
                and (
                    name in folded_query
                    or leading_name
                    in {part.casefold() for part in name.split()}
                )
                for name in recovered_names
            )
            if not clean_query or belongs_to_recovered_person:
                continue
            jobs.append(
                {
                    "query": clean_query,
                    "entity_name": "",
                    "entity_type": "",
                    "entity_key": "",
                    "description": "",
                    "usage": "context",
                    "strict_identity": False,
                },
            )
    if not jobs:
        for query in search_queries:
            clean_query = _clean_query(query)
            if clean_query:
                jobs.append(
                    {
                        "query": clean_query,
                        "entity_name": "",
                        "entity_type": "",
                        "entity_key": "",
                        "description": "",
                        "usage": "context",
                        "strict_identity": False,
                    },
                )
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for job in jobs:
        query = _clean_query(str(job.get("query") or ""))
        if not query:
            continue
        job = {**job, "query": query}
        key = _visual_job_key(job) or query.casefold()
        if key in seen:
            continue
        seen.add(key)
        job["job_key"] = key
        deduped.append(job)
        if len(deduped) >= max(1, max_visual_queries):
            break
    return deduped


def _expand_visual_queries(
    search_queries: list[str],
    *,
    context: dict[str, Any] | None,
    entities: list[dict[str, Any]],
    max_visual_queries: int,
) -> list[str]:
    return [
        str(job["query"])
        for job in _expand_visual_query_jobs(
            search_queries,
            context=context,
            entities=entities,
            max_visual_queries=max_visual_queries,
        )
    ]


def _person_identity_reject_reason(source: dict[str, Any]) -> str:
    haystack = " ".join(
        (
            str(source.get(key) or "")
            for key in ("title", "url", "source_url", "thumbnail_url")
        )
    )
    match = _PERSON_IDENTITY_REJECT_RE.search(haystack)
    if not match:
        return ""
    return f"non_photographic_or_untrusted_identity_source:{match.group(0)}"


def _annotate_visual_source_for_job(
    source: dict[str, Any],
    job: dict[str, Any],
) -> dict[str, Any]:
    enriched = dict(source)
    enriched.update(
        {
            "visual_job_key": job.get("job_key") or _visual_job_key(job),
            "entity_name": job.get("entity_name") or "",
            "entity_type": job.get("entity_type") or "",
            "usage_hint": job.get("usage") or "context",
            "strict_identity": bool(job.get("strict_identity")),
        },
    )
    return enriched


def _strict_identity_retry_queries(job: dict[str, Any]) -> list[str]:
    name = _clean_query(str(job.get("entity_name") or ""))
    if not name:
        return []
    templates = [
        f"{name} official player profile portrait",
        f"{name} official profile photo headshot",
        f"{name} portrait clear face single person",
    ]
    original = _clean_query(str(job.get("query") or "")).casefold()
    queries: list[str] = []
    seen: set[str] = {original} if original else set()
    for query in templates:
        clean = _clean_query(query)
        key = clean.casefold()
        if clean and key not in seen:
            seen.add(key)
            queries.append(clean)
        if len(queries) >= DEFAULT_STRICT_IDENTITY_RETRY_QUERY_COUNT:
            break
    return queries


def _filter_visual_search_result_for_job(
    visual_result: dict[str, Any],
    job: dict[str, Any],
    *,
    retry: bool = False,
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    raw_visual_sources = list(visual_result.get("visual_sources") or [])
    filtered_visual_sources: list[dict[str, Any]] = []
    prefilter_issues: list[str] = []
    for source in raw_visual_sources:
        if not isinstance(source, dict):
            continue
        if job.get("strict_identity"):
            reason = _person_identity_reject_reason(source)
            if reason:
                prefilter_issues.append(
                    f"visual_identity_prefilter_rejected:{visual_result.get('query') or ''}:{reason}",
                )
                continue
        filtered_visual_sources.append(
            _annotate_visual_source_for_job(source, job),
        )
    issues = [*(visual_result.get("issues") or []), *prefilter_issues]
    trace = {
        "query": visual_result.get("query") or "",
        "source_count": len(raw_visual_sources),
        "filtered_count": len(raw_visual_sources)
        - len(filtered_visual_sources),
        "staged_candidate_count": len(filtered_visual_sources),
        "entity_name": job.get("entity_name") or "",
        "entity_type": job.get("entity_type") or "",
        "usage": job.get("usage") or "context",
        "strict_identity": bool(job.get("strict_identity")),
        "provider": visual_result.get("provider") or "",
        "providers": visual_result.get("providers") or [],
        "providers_attempted": visual_result.get("providers_attempted") or [],
        "image_transport": visual_result.get("image_transport") or "",
        "bbox": visual_result.get("bbox"),
        "issues": issues,
    }
    if retry:
        trace["retry"] = True
    return (filtered_visual_sources, issues, trace)


def _strict_identity_jobs_without_accepted_refs(
    visual_jobs: list[dict[str, Any]],
    visual_sources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = []
    for job in visual_jobs:
        if not bool(job.get("strict_identity")):
            continue
        job_key = str(job.get("job_key") or _visual_job_key(job))
        has_accepted = any(
            (
                str(source.get("visual_job_key") or "") == job_key
                and _is_accepted_visual_source(source)
                for source in visual_sources
            )
        )
        if not has_accepted:
            missing.append(job)
    return missing
