# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long,redefined-outer-name,reimported
# pylint: disable=too-many-branches,too-many-return-statements,unused-import
"""Grounding triage, entity normalization, and visual-query planning."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from models import text_model
from utils.logger import setup_logger
from utils.structured_output import extract_json_payload

from .common import as_list as _as_list
from .common import clean_text as _clean_text
from .common import coerce_bool as _coerce_bool
from .common import coerce_confidence as _coerce_confidence
from .common import split_keywords as _split_keywords
from .common import string_list as _string_list


def _is_accepted_visual_source(source: dict[str, Any]) -> bool:
    verification = source.get("verification")
    return (
        isinstance(verification, dict)
        and str(verification.get("status") or "").casefold() == "accepted"
    )


DEFAULT_STRICT_IDENTITY_RETRY_QUERY_COUNT = 3

DEFAULT_DETECTOR = "hybrid"
DEFAULT_MAX_PRIMARY_QUERIES = 6

logger = setup_logger("services.web_grounding")

GROUNDING_DETECTOR_SYSTEM_PROMPT = 'You are a web-grounding intent classifier for Creator video/image workflows.\n\nDecide whether the user\'s prompt needs external web grounding before planning, editing, or generation.\n\nReturn needs_grounding=true when:\n- the user explicitly asks to search, browse, verify, fact-check, or use online information;\n- the core request depends on a specific real-world person, athlete, team, brand, company, place, event, match, tournament, IP, historical fact, statistic, source, roster, schedule, current status, or other external fact;\n- the prompt contains non-English aliases/transliterations or named entities that likely need identity facts (for example shirt number, club, nationality, visual reference);\n- the prompt names a real-world visual style, fashion/editorial reference, cultural artifact, traditional costume, jewelry, craft, architecture, motif, or material where visual accuracy depends on image references;\n- current/recent/future information is required, or the work cannot start correctly without factual lookup.\n\nReturn needs_grounding=false when:\n- the request is purely fictional, generic, stylistic, or self-contained;\n- the prompt already provides enough attached/reference material and does not need outside facts;\n- web search would only be nice-to-have instead of required for correctness.\n\nFor queries, provide up to 3 short search-ready queries. Prefer canonical English names when you know them, but include the original user term if unsure.\n\nOutput strict JSON only, with this schema:\n{\n  "needs_grounding": true,\n  "need_websearch": true,\n  "domain": "sports_target_player|sports|public_person|brand_product|place_event|entertainment_ip|visual_style|generic",\n  "include_visuals": true,\n  "confidence": 0.0,\n  "queries": ["short query"],\n  "entities": [{\n    "text": "original term",\n    "type": "person|team|place|event|brand|ip|style|cultural_artifact|costume|jewelry|other",\n    "canonical": "canonical name if known",\n    "needs_visual_grounding": true,\n    "visual_usage": "identity|style|logo|product|place|context",\n    "strict_identity": true\n  }],\n  "reasons": ["specific_real_world_entity"]\n}\n'
GROUNDING_DETECTOR_SYSTEM_PROMPT = GROUNDING_DETECTOR_SYSTEM_PROMPT.replace(
    "For queries, provide up to 3 short search-ready queries. Prefer canonical English names when you know them, but include the original user term if unsure.",
    "For queries, return the minimum number needed for distinct retrieval targets, up to 6; 6 is a ceiling, not a quota. Do not invent queries to fill the list. Prefer canonical English names when known. Never add a year, current, or latest unless the user explicitly requests that period or the requested fact is inherently time-sensitive. Keep person identity queries separate from show, stage, and style context queries.",
)

GROUNDING_DOMAINS = {
    "sports_target_player",
    "sports",
    "public_person",
    "brand_product",
    "place_event",
    "entertainment_ip",
    "visual_style",
    "generic",
}

_DOMAIN_ALIASES = {
    "sports_player": "sports_target_player",
    "athlete": "sports_target_player",
    "person_public": "public_person",
    "public_figure": "public_person",
    "celebrity": "public_person",
    "brand": "brand_product",
    "product": "brand_product",
    "organization": "brand_product",
    "company": "brand_product",
    "place": "place_event",
    "event": "place_event",
    "sports_event": "sports",
    "media_work": "entertainment_ip",
    "ip": "entertainment_ip",
    "style": "visual_style",
    "visual": "visual_style",
    "visual_reference": "visual_style",
    "visual_style_reference": "visual_style",
    "fashion": "visual_style",
    "costume": "visual_style",
    "jewelry": "visual_style",
    "cultural_artifact": "visual_style",
}

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

_VISUAL_REFERENCE_RE = re.compile(
    "\\b(visual|appearance|look|logo|reference|identity|recognize|face|jersey|kit|venue|style|aesthetic|mood\\s*board|moodboard|vogue|editorial|couture|runway|fashion|costume|jewelry|silverwork|ornament|headdress|embroidery|textile|motif|pattern|architecture|interior|material|texture|traditional|ethnic|folk|indigenous)\\b|外观|视觉|参考|识别|身份|脸|球衣|队服|标志|场馆|风格|造型|妆造|穿搭|服饰|服装|时装|秀场|高定|大片|美学|银饰|首饰|饰品|头饰|刺绣|纹样|图案|材质|质感|彝族|苗族|藏族|侗族|民族|民俗|非遗|传统|建筑|室内|场景",
    re.IGNORECASE,
)

_VISUAL_STYLE_RE = re.compile(
    "\\b(vogue|editorial|couture|runway|fashion|costume|jewelry|silverwork|ornament|headdress|embroidery|textile|motif|pattern|architecture|interior|material|texture|traditional|ethnic|folk|indigenous|mood\\s*board|moodboard)\\b|造型参考|视觉参考|妆造|穿搭|服饰|服装|时装|秀场|高定|大片|银饰|首饰|饰品|头饰|刺绣|纹样|图案|材质|质感|彝族|苗族|藏族|侗族|民族|民俗|非遗|传统|建筑|室内",
    re.IGNORECASE,
)

_EXPLICIT_SEARCH_RE = re.compile(
    "\\b(search|web search|browse|look up|google|verify|fact[- ]?check)\\b|上网|联网|网络搜索|网页搜索|搜索|搜一下|查一下|检索|核实|查证",
    re.IGNORECASE,
)

_TEMPORAL_RE = re.compile(
    "\\b(latest|newest|recent|current|today|yesterday|tomorrow|this year|breaking|live|updated|202[4-9]|203[0-9])\\b|最新|最近|当前|今天|昨日|昨天|明天|今年|本届|实时|现任|目前",
    re.IGNORECASE,
)

_FACT_INTENT_RE = re.compile(
    "\\b(who|what|when|where|which|rank|record|stats?|data|source|citation|schedule|roster|club|team|nationality|born|age|height|score|standings)\\b|资料|事实|来源|引用|是谁|哪里|排名|数据|记录|赛程|阵容|球队|俱乐部|国家队|世界杯|奥运|联赛|球员",
    re.IGNORECASE,
)

_REAL_WORLD_RE = re.compile(
    "\\b(real|actual|official|brand|company|person|athlete|celebrity|politician|city|country|event|tournament|match|league|nba|nfl|mlb|fifa|world cup)\\b|真实|官方|品牌|公司|人物|名人|运动员|赛事|比赛|城市|国家",
    re.IGNORECASE,
)

_CAPITALIZED_PHRASE_RE = re.compile(
    "\\b[A-Z][a-zA-Z]+(?:\\s+[A-Z][a-zA-Z]+){0,4}\\b",
)


def _context_queries(context: dict[str, Any] | None) -> list[str]:
    if not isinstance(context, dict):
        return []
    queries: list[str] = []
    for key in (
        "queries",
        "search_queries",
        "searchKeywords",
        "search_keywords",
    ):
        queries.extend(_as_list(context.get(key)))
    return list(
        dict.fromkeys((_clean_query(q) for q in queries if _clean_query(q))),
    )


def _detector_mode(detector: str | None = None) -> str:
    value = (
        (
            detector
            or os.environ.get("WEB_GROUNDING_DETECTOR")
            or DEFAULT_DETECTOR
        )
        .strip()
        .lower()
    )
    if value in {"off", "none", "disabled"}:
        return "heuristic"
    if value not in {"hybrid", "llm", "heuristic"}:
        return DEFAULT_DETECTOR
    return value


def _compact_context_for_detector(
    context: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(context, dict):
        return {}
    compact: dict[str, Any] = {}
    for key in (
        "requiresGrounding",
        "queries",
        "search_queries",
        "searchKeywords",
        "search_keywords",
        "entities",
        "base_profile",
        "target_profile",
        "groundingTriage",
        "include_visuals",
        "grounding_domain",
        "targetRefs",
        "files",
        "visual_job",
    ):
        if key in context:
            compact[key] = context[key]
    project = context.get("project")
    if isinstance(project, dict):
        compact["project"] = {
            key: project.get(key)
            for key in ("name", "description", "style", "aspectRatio")
            if project.get(key)
        }
    return compact


def _entity_reference_fields(item: dict[str, Any]) -> dict[str, Any]:
    reference_image = str(
        item.get("reference_image") or item.get("referenceImage") or "",
    ).strip()
    if not reference_image:
        return {}
    fields: dict[str, Any] = {"reference_image": reference_image[:2048]}
    reference_bbox = (
        item.get("reference_bbox")
        or item.get("referenceBbox")
        or item.get("bbox")
    )
    if isinstance(reference_bbox, (list, tuple)):
        fields["reference_bbox"] = list(reference_bbox)
    return fields


def _normalize_entities(value: Any) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                text = _clean_text(
                    item.get("text") or item.get("name") or item.get("entity"),
                    max_chars=120,
                )
                canonical = _clean_text(
                    item.get("canonical") or item.get("canonical_name"),
                    max_chars=120,
                )
                entity_type = _clean_text(
                    item.get("type") or item.get("kind") or "other",
                    max_chars=40,
                )
                if text or canonical:
                    normalized: dict[str, Any] = {
                        "text": text or canonical,
                        "type": entity_type or "other",
                        "canonical": canonical,
                    }
                    visual_usage = _clean_text(
                        item.get("visual_usage") or item.get("visualUsage"),
                        max_chars=40,
                    )
                    if visual_usage:
                        normalized["visual_usage"] = visual_usage
                    if "strict_identity" in item or "strictIdentity" in item:
                        normalized["strict_identity"] = _coerce_bool(
                            item.get(
                                "strict_identity",
                                item.get("strictIdentity"),
                            ),
                        )
                    if (
                        "needs_visual_grounding" in item
                        or "needsVisualGrounding" in item
                    ):
                        normalized["needs_visual_grounding"] = _coerce_bool(
                            item.get(
                                "needs_visual_grounding",
                                item.get("needsVisualGrounding"),
                            ),
                        )
                    description = _clean_text(
                        item.get("description")
                        or item.get("profile")
                        or item.get("note"),
                        max_chars=240,
                    )
                    if description:
                        normalized["description"] = description
                    # A caller-provided reference unlocks Lens for this job.
                    normalized.update(_entity_reference_fields(item))
                    entities.append(normalized)
            else:
                text = _clean_text(item, max_chars=120)
                if text:
                    entities.append(
                        {"text": text, "type": "other", "canonical": ""},
                    )
    else:
        for text in _string_list(value):
            entities.append({"text": text, "type": "other", "canonical": ""})
    return entities[:6]


def _normalize_grounding_domain(value: Any) -> str:
    raw = (
        _clean_text(value, max_chars=80)
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )
    if raw in GROUNDING_DOMAINS:
        return raw
    return _DOMAIN_ALIASES.get(raw, "generic")


def _infer_grounding_domain(
    prompt: str,
    context: dict[str, Any] | None,
    entities: list[dict[str, Any]],
) -> str:
    if isinstance(context, dict):
        explicit = _normalize_grounding_domain(context.get("grounding_domain"))
        if explicit != "generic":
            return explicit
        content_type = _clean_text(
            context.get("projectContentType") or context.get("contentType"),
            max_chars=80,
        ).lower()
        if content_type == "sports":
            return "sports"
    entity_types = {
        _clean_text(entity.get("type"), max_chars=80).lower()
        for entity in entities
        if isinstance(entity, dict)
    }
    if entity_types & {"sports_player", "athlete"}:
        return "sports_target_player"
    if entity_types & {"sports_team", "sports_event", "team"}:
        return "sports"
    if entity_types & {"person", "person_public", "celebrity"}:
        return "public_person"
    if entity_types & {"brand", "product", "organization", "company"}:
        return "brand_product"
    if entity_types & {"place", "event"}:
        return "place_event"
    if entity_types & {"ip", "media_work"}:
        return "entertainment_ip"
    if entity_types & {
        "style",
        "visual_style",
        "fashion",
        "costume",
        "jewelry",
        "cultural_artifact",
        "craft",
        "motif",
    }:
        return "visual_style"
    text = _clean_text(prompt, max_chars=600).lower()
    if re.search(
        "\\b(nba|nfl|mlb|fifa|football|soccer|athlete|player|team|league)\\b|球员|球队|联赛|体育|赛事",
        text,
    ):
        return "sports"
    if re.search(
        "\\b(brand|logo|product|company)\\b|品牌|产品|公司|标志|logo",
        text,
    ):
        return "brand_product"
    if re.search(
        "\\b(place|venue|city|country|stadium|event)\\b|地点|城市|国家|场馆|赛事",
        text,
    ):
        return "place_event"
    if re.search(
        "\\b(character|movie|anime|game|ip)\\b|角色|电影|动漫|游戏|版权|IP",
        text,
    ):
        return "entertainment_ip"
    if _VISUAL_STYLE_RE.search(text):
        return "visual_style"
    return "generic"


def _infer_include_visuals(
    prompt: str,
    context: dict[str, Any] | None,
    domain: str,
    entities: list[dict[str, Any]],
) -> bool:
    if isinstance(context, dict) and "include_visuals" in context:
        return _coerce_bool(context.get("include_visuals"))
    text = _clean_text(prompt, max_chars=600).lower()
    if _VISUAL_REFERENCE_RE.search(text):
        return True
    if domain in {
        "sports_target_player",
        "public_person",
        "brand_product",
        "place_event",
        "entertainment_ip",
        "visual_style",
    }:
        return any(
            (
                _clean_text(entity.get("type"), max_chars=80).lower()
                in _VISUAL_ENTITY_TYPES
                for entity in entities
                if isinstance(entity, dict)
            )
        )
    return False


def _normalize_llm_grounding_analysis(
    payload: Any,
    prompt: str,
    max_queries: int,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("grounding detector returned non-object JSON")
    needs_grounding = _coerce_bool(
        payload.get("needs_grounding", payload.get("need_websearch", False)),
    )
    queries: list[str] = []
    for key in ("queries", "search_queries", "searchQueries"):
        queries.extend(_as_list(payload.get(key)))
    queries.extend(
        _split_keywords(
            payload.get("search_keywords") or payload.get("searchKeywords"),
        ),
    )
    queries = list(
        dict.fromkeys(
            (_clean_query(query) for query in queries if _clean_query(query))
        ),
    )[:max_queries]
    if needs_grounding and (not queries):
        entities = _normalize_entities(
            payload.get("entities") or payload.get("terms"),
        )
        for entity in entities:
            candidate = entity.get("canonical") or entity.get("text")
            if candidate:
                queries.append(_clean_query(str(candidate)))
        if not queries:
            queries = _derive_queries(prompt, max_queries=max_queries)
    else:
        entities = _normalize_entities(
            payload.get("entities") or payload.get("terms"),
        )
    if not needs_grounding:
        queries = []
    reasons = _string_list(payload.get("reasons") or payload.get("reason"))
    if needs_grounding and (not reasons):
        reasons = ["llm_grounding_required"]
    return {
        "needs_grounding": needs_grounding,
        "need_websearch": needs_grounding,
        "domain": _normalize_grounding_domain(payload.get("domain")),
        "include_visuals": _coerce_bool(payload.get("include_visuals")),
        "confidence": _coerce_confidence(
            payload.get("confidence"),
            default=0.75 if needs_grounding else 0.2,
        ),
        "reasons": reasons,
        "queries": queries[:max_queries],
        "entities": entities,
        "detector": "llm",
        "detector_issues": [],
    }


def _clean_query(query: str) -> str:
    query = _clean_text(query, max_chars=180)
    query = re.sub(
        "^(please|can you|could you|help me|帮我|请|麻烦|上网|联网|搜索|搜一下|查一下|检索)\\s*",
        "",
        query,
        flags=re.IGNORECASE,
    )
    query = query.strip(" :：,，.。?？!！\"'`")
    words = query.split()
    if len(words) > 24:
        query = " ".join(words[:24])
    return query


def _derive_queries(
    prompt: str,
    max_queries: int = DEFAULT_MAX_PRIMARY_QUERIES,
) -> list[str]:
    text = _clean_text(prompt, max_chars=600)
    if not text:
        return []
    candidates: list[str] = []
    patterns = [
        "(?:search(?: for)?|look up|web search|browse for|verify|fact[- ]?check)\\s+(?P<q>[^。\\n!?？！]+)",
        "(?:上网|联网|网络搜索|网页搜索|搜索|搜一下|查一下|检索|核实|查证)\\s*(?P<q>[^。\\n!?？！]+)",
        "(?:about|regarding|关于|围绕)\\s+(?P<q>[^。\\n!?？！]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            candidates.append(match.group("q"))
    quoted = re.findall("[\\\"“”']([^\\\"“”']{3,100})[\\\"“”']", text)
    candidates.extend(quoted)
    if not candidates:
        candidates.append(text)
    queries = []
    for candidate in candidates:
        cleaned = _clean_query(candidate)
        if cleaned and cleaned not in queries:
            queries.append(cleaned)
        if len(queries) >= max_queries:
            break
    return queries


_PERSON_VISUAL_HINT_RE = re.compile(
    "\\b(person|public_person|celebrity|athlete|sports_player|footballer|player|actor|singer|model)\\b|人物|名人|球员|运动员|演员|歌手|模特",
    re.IGNORECASE,
)

_PERSON_QUERY_HINT_RE = re.compile(
    "\\b(appearance|facial|face|portrait|headshot|likeness|identity|casual|unstyled|styled|fashion|outfit|personality|traits|real)\\b|外貌|长相|脸|肖像|本人|身份|造型|穿搭|性格|真人",
    re.IGNORECASE,
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


def detect_grounding_needs(
    prompt: str,
    context: dict[str, Any] | None = None,
    *,
    max_queries: int = DEFAULT_MAX_PRIMARY_QUERIES,
) -> dict[str, Any]:
    """Classify whether a prompt should be grounded with web search."""
    text = _clean_text(prompt)
    lower = text.lower()
    reasons: list[str] = []
    if _EXPLICIT_SEARCH_RE.search(text):
        reasons.append("explicit_search")
    if _TEMPORAL_RE.search(text):
        reasons.append("time_sensitive")
    if _REAL_WORLD_RE.search(text) and _FACT_INTENT_RE.search(text):
        reasons.append("real_world_fact")
    if _CAPITALIZED_PHRASE_RE.search(text) and _FACT_INTENT_RE.search(text):
        reasons.append("named_entity_fact")
    if _VISUAL_STYLE_RE.search(text):
        reasons.append("visual_reference_term")
    if isinstance(context, dict) and context.get("requiresGrounding"):
        reasons.append("context_requires_grounding")
    pure_fiction = bool(
        re.search(
            "fictional|imaginary|invent|fantasy|虚构|架空|编一个|想象",
            lower,
        ),
    )
    if pure_fiction and (
        not set(reasons)
        & {
            "explicit_search",
            "time_sensitive",
            "context_requires_grounding",
            "visual_reference_term",
        }
    ):
        reasons = []
    queries = _context_queries(context) or _derive_queries(
        text,
        max_queries=max_queries,
    )
    needs_grounding = bool(reasons)
    confidence = 0.0
    if needs_grounding:
        confidence = min(0.95, 0.45 + 0.15 * len(set(reasons)))
    return {
        "needs_grounding": needs_grounding,
        "need_websearch": needs_grounding,
        "confidence": round(confidence, 2),
        "reasons": list(dict.fromkeys(reasons)),
        "queries": queries[:max_queries] if needs_grounding else [],
        "entities": [],
        "detector": "heuristic",
        "detector_issues": [],
    }


def _text_detector_configured() -> bool:
    try:
        from models import config as model_config

        return bool(model_config.get_text_api_key())
    except Exception:
        return False


async def classify_grounding_needs_llm(
    prompt: str,
    context: dict[str, Any] | None = None,
    *,
    max_queries: int = DEFAULT_MAX_PRIMARY_QUERIES,
) -> dict[str, Any]:
    """Use the configured text model to reason about whether web grounding is needed."""
    if not _text_detector_configured():
        raise RuntimeError("text_model_api_key_missing")
    user_payload = {
        "prompt": _clean_text(prompt, max_chars=1200),
        "context": _compact_context_for_detector(context),
    }
    raw = await text_model.chat_completion(
        "Classify this Creator request for web grounding:\n"
        + json.dumps(user_payload, ensure_ascii=False, default=str),
        system_prompt=GROUNDING_DETECTOR_SYSTEM_PROMPT,
        temperature=0.0,
        max_tokens=900,
        timeout=45.0,
    )
    return _normalize_llm_grounding_analysis(
        extract_json_payload(raw),
        prompt,
        max_queries,
    )


async def classify_grounding_needs(
    prompt: str,
    context: dict[str, Any] | None = None,
    *,
    max_queries: int = DEFAULT_MAX_PRIMARY_QUERIES,
    detector: str | None = None,
) -> dict[str, Any]:
    """Classify grounding need with LLM reasoning and heuristic fallback."""
    heuristic = detect_grounding_needs(
        prompt,
        context=context,
        max_queries=max_queries,
    )
    mode = _detector_mode(detector)
    if mode == "heuristic":
        return heuristic
    try:
        llm_analysis = await classify_grounding_needs_llm(
            prompt,
            context=context,
            max_queries=max_queries,
        )
    except Exception as exc:
        fallback = {**heuristic}
        fallback["detector"] = "heuristic_fallback"
        fallback["detector_issues"] = [
            f"llm_detector:{exc.__class__.__name__}: {exc}",
        ]
        return fallback
    if heuristic["needs_grounding"] and (not llm_analysis["needs_grounding"]):
        merged_reasons = list(
            dict.fromkeys([*heuristic["reasons"], "heuristic_override"]),
        )
        return {
            **heuristic,
            "detector": "hybrid",
            "confidence": max(
                heuristic.get("confidence", 0),
                llm_analysis.get("confidence", 0),
            ),
            "reasons": merged_reasons,
            "entities": llm_analysis.get("entities", []),
            "llm_detector": llm_analysis,
            "detector_issues": ["llm_detector_disagreed_with_heuristic"],
        }
    if heuristic["needs_grounding"] and llm_analysis["needs_grounding"]:
        llm_analysis["reasons"] = list(
            dict.fromkeys([*heuristic["reasons"], *llm_analysis["reasons"]]),
        )
        llm_analysis["confidence"] = max(
            heuristic.get("confidence", 0),
            llm_analysis.get("confidence", 0),
        )
    return llm_analysis


async def triage_grounding_request(
    prompt: str,
    context: dict[str, Any] | None = None,
    *,
    queries: list[str] | None = None,
    force: bool = False,
    detector: str | None = None,
    max_queries: int = DEFAULT_MAX_PRIMARY_QUERIES,
) -> dict[str, Any]:
    """Run the cheap grounding decision boundary without doing web search."""
    from .visual_jobs import _enrich_visual_entity_contract

    prompt = _clean_text(prompt, max_chars=1200)
    context = context if isinstance(context, dict) else {}
    requested_queries = [_clean_query(q) for q in _as_list(queries)]
    requested_queries = [query for query in requested_queries if query]
    if requested_queries or force:
        analysis = detect_grounding_needs(
            prompt,
            context=context,
            max_queries=max_queries,
        )
    else:
        analysis = await classify_grounding_needs(
            prompt,
            context=context,
            detector=detector,
            max_queries=max_queries,
        )
    reasons = list(analysis.get("reasons") or [])
    if requested_queries:
        analysis["queries"] = requested_queries[:max_queries]
        analysis["needs_grounding"] = True
        analysis["need_websearch"] = True
        reasons.append("explicit_queries")
    if force:
        analysis["needs_grounding"] = True
        analysis["need_websearch"] = True
        reasons.append("forced")
        if not analysis.get("queries"):
            analysis["queries"] = _derive_queries(
                prompt,
                max_queries=max_queries,
            )
    entities = _normalize_entities(analysis.get("entities"))
    domain = _normalize_grounding_domain(analysis.get("domain"))
    if domain == "generic":
        domain = _infer_grounding_domain(prompt, context, entities)
    include_visuals = bool(
        analysis.get("include_visuals"),
    ) or _infer_include_visuals(prompt, context, domain, entities)
    needs_grounding = bool(analysis.get("needs_grounding"))
    entities = _enrich_visual_entity_contract(
        entities,
        include_visuals=include_visuals if needs_grounding else False,
    )
    triage = {
        "ok": True,
        "status": "triaged",
        "needs_grounding": needs_grounding,
        "need_websearch": needs_grounding,
        "domain": domain,
        "include_visuals": include_visuals if needs_grounding else False,
        "confidence": _coerce_confidence(
            analysis.get("confidence"),
            default=0.75 if needs_grounding else 0.2,
        ),
        "reasons": list(
            dict.fromkeys((str(reason) for reason in reasons if reason)),
        ),
        "queries": (
            list(analysis.get("queries") or [])[:max_queries]
            if needs_grounding
            else []
        ),
        "entities": entities,
        "detector": analysis.get("detector") or _detector_mode(detector),
        "detector_issues": list(analysis.get("detector_issues") or []),
    }
    if analysis.get("llm_detector"):
        triage["llm_detector"] = analysis["llm_detector"]
    logger.info(
        "Grounding triage completed needs=%s domain=%s visuals=%s queries=%d detector=%s",
        triage["needs_grounding"],
        triage["domain"],
        triage["include_visuals"],
        len(triage["queries"]),
        triage["detector"],
    )
    return triage
