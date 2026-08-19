# -*- coding: utf-8 -*-
"""Knowledge dream: extract units from private daily notes into shared KB."""

from __future__ import annotations

import difflib
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field

from .lock import KnowledgeLockTimeout, knowledge_write_lock
from .prompts import (
    build_coverage_extract_prompt,
    build_extract_prompt,
    build_merge_integrity_prompt,
    build_merge_prompt,
)
from .store import (
    INBOX_BUCKET,
    LEGACY_FLAT_BUCKETS,
    PUBLISHED_BUCKETS,
    kb_root,
    validate_kb_id,
)

logger = logging.getLogger(__name__)

CATALOG_NAME = "knowledge_dream"
# Keep ASCII alnum, CJK Unified Ideographs, and a few safe separators.
_SLUG_KEEP_RE = re.compile(
    r"[^0-9a-zA-Z\u4e00-\u9fff._-]+",
)

# Integrate action vocabulary (ReMe-aligned). MERGE is accepted as a legacy
# alias of REFINE at resolve time.
_VALID_ACTIONS = frozenset({"CREATE", "CORROBORATE", "REFINE", "CORRECT", "MERGE"})
_BODY_REWRITE_ACTIONS = frozenset({"REFINE", "MERGE", "CORRECT"})


class KnowledgeUnit(BaseModel):
    """One extracted knowledge unit ready for integrate.

    Business-domain units typically populate only ``name``/``bucket``/
    ``summary``. Test-domain units additionally populate the structured
    test fields (``preconditions``/``steps``/``expected``/``priority``/
    ``requirement_id``) so a test case node carries its executable shape,
    not just free text. ``links`` holds titles of related KB nodes (any
    domain) and is rendered as ``[[wikilink]]`` so ReMe's ``expand_links``
    surfaces the traceability graph on recall.
    """

    name: str
    bucket: str = "wiki"
    summary: str = ""
    paths: list[str] = Field(default_factory=list)
    confidence: float = 0.7
    signals: list[str] = Field(default_factory=list)
    action_hint: str | None = None
    # Test-domain structured fields (optional, empty for business units).
    preconditions: str = ""
    steps: list[str] = Field(default_factory=list)
    expected: str = ""
    priority: str = ""
    requirement_id: str = ""
    # Cross-node references rendered as [[wikilink]] in the node body.
    links: list[str] = Field(default_factory=list)
    # Optional LLM hint: title of the published node this unit should merge
    # into. The merge search result takes precedence when available; this
    # only disambiguates when the search is inconclusive.
    merge_target: str = ""


@dataclass
class MergeCandidate:
    """A published KB node identified as a merge target for a new unit.

    ``is_clear`` is True only when the candidate is an unambiguous winner:
    similarity >= threshold AND it beats the runner-up by >= margin (or it
    is the only hit). Ambiguous candidates must not trigger auto-merge.

    ``related_names`` holds titles of *related* (not same-abstraction)
    published nodes recalled in the same ``node_search`` pass — used to
    enrich ``unit.links`` (synapse / wikilink weaving) without merging.
    """

    name: str
    path: str
    ratio: float
    is_clear: bool = False
    related_names: list[str] = field(default_factory=list)


@dataclass
class InboxMeta:
    """Metadata written onto an _inbox draft so replay/promote can act."""

    reason: str
    intended_bucket: str
    merge_target_path: str = ""
    retry_count: int = 0


def _slugify(name: str) -> str:
    """Build a stable filesystem slug; preserve CJK to avoid collisions."""
    text = (name or "").strip().lower()
    text = _SLUG_KEEP_RE.sub("-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-._")
    if text:
        return text[:80]
    digest = hashlib.sha1((name or "node").encode("utf-8")).hexdigest()[:10]
    return f"node-{digest}"


# Trailing aliases extractors often append instead of using merge_target.
# Do not strip 说明 / 分析 — those are frequently distinct neighbor nodes.
_TITLE_ALIAS_SUFFIX_RE = re.compile(
    r"(?:[-_/\s]+(?:补充|补|修正|修订|更新|再确认|新版|v\d+)"
    r"|(?:补充|修正|修订|更新|再确认|新版))$",
    re.IGNORECASE,
)
_MAX_DERIVED_FROM = 32
_MAX_CATALOG_NODES = 80
_CATALOG_QUERY_CHARS = 1200
_CATALOG_SEARCH_CHUNKS = 3
INBOX_MAX_RETRIES = 3

# Why a unit landed in _inbox. Retryable reasons are replayed by the next
# knowledge dream; the rest wait for human promote / merge / reject.
INBOX_REASON_AMBIGUOUS = "ambiguous_candidate"
INBOX_REASON_CREATE_CONFLICT = "create_conflict"
INBOX_REASON_CROSS_DOMAIN = "cross_domain"
INBOX_REASON_MISSING_PAYLOAD = "missing_payload"
INBOX_REASON_STALE = "stale"
INBOX_REASON_STALE_TARGET = "stale_target"
INBOX_REASON_AT_CAP = "at_cap"
INBOX_REASON_EMPTY_UPDATE = "empty_update"
INBOX_REASON_CORROBORATE_FAILED = "corroborate_failed"
INBOX_REASON_SEMANTIC_DUP = "semantic_dup"
INBOX_REASON_LOW_CONFIDENCE = "low_confidence"
INBOX_REASON_MERGE_DISABLED = "merge_disabled"
INBOX_REASON_EXACT_UNMERGED = "exact_unmerged"
INBOX_REASON_INTEGRITY_FAILED = "integrity_failed"
INBOX_REASON_INTEGRITY_SKIPPED = "integrity_check_skipped"
INBOX_REASON_NO_TARGET = "no_merge_target"

INBOX_RETRYABLE_REASONS = frozenset({
    INBOX_REASON_MISSING_PAYLOAD,
    INBOX_REASON_STALE,
    INBOX_REASON_STALE_TARGET,
    INBOX_REASON_CORROBORATE_FAILED,
    INBOX_REASON_INTEGRITY_SKIPPED,
})
# Name-similarity floor for lexical same-entity linking when the extract
# used a different title than the published node. Below merge_threshold, so
# a unique title-in-summary hit can still auto-merge; ambiguous pairs are
# left as CREATE (no extra inbox).
_LEXICAL_LINK_FLOOR = 0.50
_LEXICAL_LINK_MARGIN = 0.15
# Auto-woven [[wikilink]] neighbors per unit (test domain only). Business
# nodes skip synapse weaving so weak title-similar neighbors do not show
# up as chunk-recall noise via expand_links.
MAX_SYNAPSE_LINKS = 3


def _canonical_title(name: str) -> str:
    """Strip common extract aliases so '退款政策-补充' matches '退款政策'."""
    text = (name or "").strip().lower()
    stripped = _TITLE_ALIAS_SUFFIX_RE.sub("", text).strip("-_/\t ")
    return stripped or text


def knowledge_name_similarity(left: str, right: str) -> float:
    """Name similarity for merge/dedup, with extract-alias awareness.

    Raw ``SequenceMatcher`` on '退款政策-补充' vs '退款政策' is ~0.73
    (below both dedup and merge thresholds). Canonicalizing known suffixes
    treats those as the same abstraction (~0.94) without collapsing
    genuine neighbors such as '退款政策说明'.
    """
    a = (left or "").strip().lower()
    b = (right or "").strip().lower()
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if _slugify(a) == _slugify(b):
        return 1.0
    raw = difflib.SequenceMatcher(None, a, b).ratio()
    ca, cb = _canonical_title(a), _canonical_title(b)
    if ca and cb:
        if ca == cb:
            return max(raw, 0.94)
        return max(raw, difflib.SequenceMatcher(None, ca, cb).ratio())
    return raw


def _normalize_claim_text(text: str) -> str:
    """Flatten a summary/description for claim-level similarity."""
    flat = re.sub(r"\s+", " ", (text or "").strip().lower())
    return flat[:240]


def knowledge_claim_similarity(
    left_name: str,
    right_name: str,
    left_text: str = "",
    right_text: str = "",
) -> float:
    """Name similarity, lifted by summary/description overlap for near-miss titles.

    ``退款规则`` vs ``退款口径`` is ~0.5 on the title alone (below dedup).
    When both claims describe the same policy, the flattened summaries
    can still mark them as the same abstraction. Unrelated titles
    (below ``_LEXICAL_LINK_FLOOR``) are not lifted, so shared wording
    between different entities does not false-positive.
    """
    name = knowledge_name_similarity(left_name, right_name)
    left = _normalize_claim_text(left_text)
    right = _normalize_claim_text(right_text)
    if name < _LEXICAL_LINK_FLOOR or len(left) < 8 or len(right) < 8:
        return name
    claim = difflib.SequenceMatcher(None, left, right).ratio()
    return max(name, claim)


def _unique_dest(dest_dir: Path, slug: str) -> Path:
    """Return ``{slug}.md`` or ``{slug}-{n}.md`` when the path exists."""
    candidate = dest_dir / f"{slug}.md"
    if not candidate.exists():
        return candidate
    for idx in range(2, 1000):
        alt = dest_dir / f"{slug}-{idx}.md"
        if not alt.exists():
            return alt
    digest = hashlib.sha1(slug.encode("utf-8")).hexdigest()[:8]
    return dest_dir / f"{slug}-{digest}.md"


def _yaml_list(values: list[str]) -> str:
    if not values:
        return "[]"
    escaped = []
    for value in values:
        item = str(value).replace("\\", "\\\\").replace('"', '\\"')
        escaped.append(f'"{item}"')
    return "[" + ", ".join(escaped) + "]"


def _catalog_path(workspace_dir: Path, metadata_dir: str) -> Path:
    return workspace_dir / metadata_dir / f"{CATALOG_NAME}.json"


def load_catalog(workspace_dir: Path, metadata_dir: str) -> dict[str, Any]:
    path = _catalog_path(workspace_dir, metadata_dir)
    if not path.is_file():
        return {"processed": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Corrupt knowledge_dream catalog at %s", path)
        return {"processed": {}}


def save_catalog(
    workspace_dir: Path,
    metadata_dir: str,
    catalog: dict[str, Any],
) -> None:
    path = _catalog_path(workspace_dir, metadata_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _recent_daily_files(
    daily_dir: Path,
    *,
    scan_days: int,
    catalog: dict[str, Any],
) -> list[Path]:
    if not daily_dir.is_dir():
        return []
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=max(1, scan_days))
    processed = catalog.get("processed") or {}
    files: list[Path] = []
    for path in sorted(daily_dir.glob("*.md")):
        try:
            # Prefer YYYY-MM-DD.md naming; fall back to mtime.
            stem = path.stem
            day = datetime.strptime(stem[:10], "%Y-%m-%d").date()
        except ValueError:
            day = datetime.fromtimestamp(
                path.stat().st_mtime,
                tz=timezone.utc,
            ).date()
        if day < cutoff:
            continue
        mtime = path.stat().st_mtime
        prev = processed.get(path.name)
        if prev is not None and float(prev.get("mtime", 0)) >= mtime:
            continue
        files.append(path)
    return files


def _deduped_steps(steps: list[str]) -> list[str]:
    """Remove blank and duplicate step strings while preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for step in steps:
        step = step.strip()
        if not step or step in seen:
            continue
        seen.add(step)
        out.append(step)
    return out


def _coerce_str_list(value: Any) -> list[str]:
    """Coerce a JSON value into a list of stripped strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value).strip()]


def _normalize_bucket(bucket: str, default_bucket: str) -> str:
    """Validate/normalize a bucket string to a published namespaced bucket.

    Legacy flat buckets (``personal``/``procedure``/``wiki``) from
    pre-domain callers are mapped to ``business/{flat}`` so existing
    code and on-disk KBs keep working. Unknown buckets fall back to
    ``default_bucket`` (domain-appropriate).
    """
    bucket = (bucket or "").strip().lower()
    if bucket in PUBLISHED_BUCKETS:
        return bucket
    if bucket in LEGACY_FLAT_BUCKETS:
        return f"business/{bucket}"
    return default_bucket


def _try_parse_units(
    raw: str,
    *,
    max_units: int,
    domain: str = "business",
) -> tuple[list[KnowledgeUnit], bool]:
    """Parse LLM JSON output into units.

    Returns ``(units, parsed_ok)``. ``parsed_ok`` is False when the model
    did not emit a JSON array (malformed / refused). An empty array is a
    successful parse of "nothing to extract".
    """
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\[[\s\S]*\]", text)
        if not match:
            logger.warning("knowledge_dream: no JSON array in LLM output")
            return [], False
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return [], False
    if not isinstance(data, list):
        return [], False
    default_bucket = (
        "test/test_cases" if domain.lower().startswith("test") else "business/wiki"
    )
    units: list[KnowledgeUnit] = []
    for item in data[:max_units]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        bucket = _normalize_bucket(
            str(item.get("bucket") or ""), default_bucket,
        )
        try:
            confidence = float(item.get("confidence", 0.7))
        except (TypeError, ValueError):
            confidence = 0.7
        signals = _coerce_str_list(item.get("signals"))[:8]
        units.append(
            KnowledgeUnit(
                name=name,
                bucket=bucket,
                summary=str(item.get("summary") or "").strip(),
                confidence=max(0.0, min(1.0, confidence)),
                signals=signals,
                action_hint=(
                    str(item["action_hint"]).strip().upper()
                    if item.get("action_hint")
                    else None
                ),
                preconditions=str(item.get("preconditions") or "").strip(),
                steps=_deduped_steps(_coerce_str_list(item.get("steps"))),
                expected=str(item.get("expected") or "").strip(),
                priority=str(item.get("priority") or "").strip(),
                requirement_id=str(item.get("requirement_id") or "").strip(),
                links=_coerce_str_list(item.get("links")),
                merge_target=str(item.get("merge_target") or "").strip(),
            ),
        )
    return units, True


def _parse_units(
    raw: str,
    *,
    max_units: int,
    domain: str = "business",
) -> list[KnowledgeUnit]:
    """Parse LLM JSON output into ``KnowledgeUnit`` instances.

    ``domain`` decides the default bucket when the LLM omits one or
    returns an unrecognized value: business → ``business/wiki``, test →
    ``test/test_cases``. Recognized buckets from either domain are
    accepted as-is so a test agent can still file a procedure into
    ``business/procedure`` when it genuinely belongs there.
    """
    units, _ok = _try_parse_units(raw, max_units=max_units, domain=domain)
    return units


def _unit_dedupe_key(unit: KnowledgeUnit) -> str:
    return _canonical_title(unit.name) or unit.name.strip().lower()


def _dedupe_units(units: list[KnowledgeUnit]) -> list[KnowledgeUnit]:
    """Keep the first unit per canonical title (coverage pass may repeat)."""
    seen: set[str] = set()
    out: list[KnowledgeUnit] = []
    for unit in units:
        key = _unit_dedupe_key(unit)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(unit)
    return out


def _format_extracted_units(units: list[KnowledgeUnit]) -> str:
    """Compact already-extracted list for the coverage prompt."""
    lines: list[str] = []
    for unit in units:
        hint = f" {unit.action_hint}" if unit.action_hint else ""
        target = f" → {unit.merge_target}" if unit.merge_target else ""
        lines.append(f"- {unit.name} ({unit.bucket}){hint}{target}")
    return "\n".join(lines)


def _title_mentioned_in_summary(
    title: str,
    summary: str,
    *,
    unit_name: str = "",
) -> bool:
    """True when ``title`` appears in ``summary`` as a distinct mention.

    Substring hits against the unit's own name are ignored so neighbors
    like 「退款政策说明」 do not count as mentioning 「退款政策」.
    """
    cand = (title or "").strip().lower()
    blob = (summary or "").strip().lower()
    name_l = (unit_name or "").strip().lower()
    if len(cand) < 2 or not blob:
        return False
    if name_l and cand != name_l and (cand in name_l or name_l in cand):
        return False
    return cand in blob


def _lexical_merge_candidate(
    kb_id: str,
    unit: KnowledgeUnit,
) -> MergeCandidate | None:
    """Filesystem fallback: unique same-domain published node for ``unit``.

    A candidate is returned only when it is an unambiguous winner
    (score >= floor and beats the runner-up by margin, or it is the only
    hit). Ambiguous pairs return None so integrate CREATEs rather than
    stacking inbox drafts.
    """
    root = kb_root(kb_id)
    unit_domain = _domain_of_bucket(unit.bucket)
    scored: list[tuple[float, str, str]] = []
    for path in _iter_published_node_paths(kb_id):
        rec = _node_catalog_record(path, root)
        if rec is None:
            continue
        name, bucket, description = rec
        if _domain_of_bucket(bucket) != unit_domain:
            continue
        ratio = knowledge_name_similarity(unit.name, name)
        if _title_mentioned_in_summary(
            name, unit.summary, unit_name=unit.name,
        ):
            ratio = max(ratio, 0.94)
        if description and unit.summary:
            desc_ratio = difflib.SequenceMatcher(
                None,
                unit.summary.strip().lower()[:240],
                f"{name} {description}".strip().lower()[:240],
            ).ratio()
            ratio = max(ratio, desc_ratio)
        if ratio < _LEXICAL_LINK_FLOOR:
            continue
        try:
            rel = str(path.relative_to(root)).replace("\\", "/")
        except ValueError:
            continue
        scored.append((ratio, name, rel))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    top_ratio, top_name, top_path = scored[0]
    second_ratio = scored[1][0] if len(scored) > 1 else 0.0
    if len(scored) > 1 and (top_ratio - second_ratio) < _LEXICAL_LINK_MARGIN:
        return None
    return MergeCandidate(
        name=top_name,
        path=top_path,
        ratio=top_ratio,
        is_clear=True,
    )


def _existing_node_titles(kb_id: str) -> set[str]:
    """Collect titles/slugs of published nodes across all domain buckets.

    Scans every ``PUBLISHED_BUCKETS`` directory plus any legacy flat
    buckets (``personal``/``procedure``/``wiki``) left from before the
    domain-namespaced layout, so dedup keeps working for KBs created
    under the old schema. ``_inbox`` and ``.locks`` are skipped.
    """
    root = kb_root(kb_id)
    titles: set[str] = set()
    scan_dirs: list[Path] = [root / b for b in PUBLISHED_BUCKETS]
    # Legacy flat buckets from pre-domain KBs. New writes no longer land
    # here, but old nodes must still be dedup-able.
    scan_dirs.extend(root / b for b in LEGACY_FLAT_BUCKETS)
    for folder in scan_dirs:
        if not folder.is_dir():
            continue
        for path in folder.rglob("*.md"):
            titles.update(_node_title_aliases(path))
    return titles


def _node_display_name(path: Path) -> str:
    """Best human title: frontmatter name, then H1, then stem."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return path.stem
    fm, _body = _parse_frontmatter(text)
    fm_name = fm.get("name", "").strip().strip('"').strip("'")
    if fm_name:
        return fm_name
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip() or path.stem
    return path.stem


def _bucket_from_rel(rel: str) -> str:
    """Bucket key from a KB-relative node path (``business/wiki/x.md``)."""
    parts = Path((rel or "").replace("\\", "/")).parts
    if len(parts) >= 3:
        return "/".join(parts[:2])
    if parts:
        return parts[0]
    return ""


def _catalog_query_chunks(
    text: str,
    *,
    size: int = _CATALOG_QUERY_CHARS,
    max_chunks: int = _CATALOG_SEARCH_CHUNKS,
) -> list[str]:
    """Split a daily corpus into short queries for ``node_search``.

    Prefers ``##`` sections (one per daily file in the extract corpus) so
    a two-day scan does not collapse into a single truncated blob.
    """
    raw = (text or "").strip()
    if not raw:
        return []
    sections = [
        part.strip() for part in re.split(r"(?m)^##\s+", raw) if part.strip()
    ]
    if not sections:
        sections = [raw]
    chunks: list[str] = []
    for section in sections:
        chunks.append(section if len(section) <= size else section[:size])
        if len(chunks) >= max_chunks:
            break
    return chunks


def _title_hit_score(name: str, query_lower: str) -> float:
    """How strongly a node title is attested in the daily-note query."""
    name_l = (name or "").strip().lower()
    if not name_l or not query_lower:
        return 0.0
    if name_l in query_lower:
        return 3.0
    canon = _canonical_title(name)
    if canon and canon != name_l and canon in query_lower:
        return 2.6
    best = 0
    n = len(name_l)
    for length in range(n, 1, -1):
        if name_l[:length] in query_lower or name_l[-length:] in query_lower:
            best = length
            break
    if best >= 2:
        return 1.0 + best / n
    for word in re.findall(r"[a-z0-9]{3,}", name_l):
        if re.search(rf"\b{re.escape(word)}\b", query_lower):
            return 1.5
    return 0.0


def _description_hit_score(description: str, query_lower: str) -> float:
    """Small boost when a distinctive description phrase appears in the query."""
    desc = (description or "").strip().lower()
    if len(desc) < 4 or not query_lower:
        return 0.0
    for run in re.findall(r"[\u4e00-\u9fff]{4,}", desc):
        if run[:4] in query_lower:
            return 0.4
    for word in re.findall(r"[a-z0-9]{4,}", desc):
        if word in query_lower:
            return 0.4
    return 0.0


def _catalog_relevance_score(
    name: str,
    description: str,
    query_lower: str,
) -> float:
    title = _title_hit_score(name, query_lower)
    if title <= 0 and not description:
        return 0.0
    return title + _description_hit_score(description, query_lower)


def _node_catalog_record(path: Path, root: Path) -> tuple[str, str, str] | None:
    """Return ``(name, bucket, description)`` for a published node."""
    try:
        rel = str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return None
    bucket = _bucket_from_rel(rel)
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    fm, _body = _parse_frontmatter(text)
    name = fm.get("name", "").strip().strip('"').strip("'")
    if not name:
        for line in text.splitlines():
            if line.startswith("# "):
                name = line[2:].strip()
                break
    if not name:
        name = path.stem
    description = fm.get("description", "").strip().strip('"').strip("'")
    return name, bucket, description


def _format_catalog_line(name: str, bucket: str, description: str = "") -> str:
    base = f"- {name} ({bucket or 'business/wiki'})"
    desc = (description or "").strip()
    if not desc:
        return base
    if len(desc) > 80:
        desc = desc[:77].rstrip() + "..."
    return f"{base}: {desc}"


def _published_node_catalog_fallback(kb_id: str, *, limit: int) -> list[str]:
    """Filesystem-order sample used only when nothing matches the query."""
    root = kb_root(kb_id)
    seen: set[str] = set()
    lines: list[str] = []
    for path in _iter_published_node_paths(kb_id):
        rec = _node_catalog_record(path, root)
        if rec is None:
            continue
        name, bucket, description = rec
        key = name.lower()
        if not key or key in seen:
            continue
        seen.add(key)
        lines.append(_format_catalog_line(name, bucket, description))
        if len(lines) >= limit:
            break
    return lines


def _published_node_catalog(
    kb_id: str,
    *,
    query: str = "",
    limit: int = _MAX_CATALOG_NODES,
    recalled: list[tuple[str, str]] | None = None,
) -> str:
    """Compact published-title list for the extract prompt.

    Prefer nodes related to ``query`` (today's daily notes): semantic
    ``recalled`` hits first, then title/description overlap. Unrelated
    filesystem-first nodes are omitted when anything matches. When
    nothing matches, fall back to a short path-order sample so the
    model still sees some titles. Each line includes a one-line
    description when the node has one, so the extract model can fill
    ``merge_target`` from meaning rather than title alone.
    """
    root = kb_root(kb_id)
    query_lower = (query or "").lower()
    records: dict[str, tuple[str, str, str]] = {}
    for path in _iter_published_node_paths(kb_id):
        rec = _node_catalog_record(path, root)
        if rec is None:
            continue
        name, bucket, description = rec
        key = name.lower()
        if key:
            records.setdefault(key, rec)

    lines: list[str] = []
    seen: set[str] = set()
    for name, bucket in recalled or []:
        key = (name or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        desc = ""
        rec = records.get(key)
        if rec is not None:
            desc = rec[2]
            bucket = bucket or rec[1]
        lines.append(_format_catalog_line(name.strip(), (bucket or "").strip(), desc))
        if len(lines) >= limit:
            return "\n".join(lines)

    ranked: list[tuple[float, str, str, str]] = []
    if query_lower:
        for name, bucket, description in records.values():
            if name.lower() in seen:
                continue
            score = _catalog_relevance_score(name, description, query_lower)
            if score <= 0:
                continue
            ranked.append((score, name, bucket, description))
        ranked.sort(key=lambda item: (-item[0], item[1].lower()))
        for _score, name, bucket, description in ranked:
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            lines.append(_format_catalog_line(name, bucket, description))
            if len(lines) >= limit:
                break

    if lines:
        return "\n".join(lines)
    return "\n".join(_published_node_catalog_fallback(kb_id, limit=limit))


def _iter_published_node_paths(kb_id: str) -> list[Path]:
    """Yield published markdown paths (namespaced + legacy flat buckets)."""
    root = kb_root(kb_id)
    paths: list[Path] = []
    scan_dirs: list[Path] = [root / b for b in PUBLISHED_BUCKETS]
    scan_dirs.extend(root / b for b in LEGACY_FLAT_BUCKETS)
    for folder in scan_dirs:
        if not folder.is_dir():
            continue
        paths.extend(p for p in folder.rglob("*.md") if p.is_file())
    return paths


def _node_title_aliases(path: Path) -> set[str]:
    """Return lowercase title aliases for a node (stem + H1 + frontmatter name)."""
    aliases = {path.stem.lower()}
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return aliases
    fm, _body = _parse_frontmatter(text)
    raw_name = fm.get("name", "").strip().strip('"').strip("'")
    if raw_name:
        aliases.add(raw_name.lower())
    for line in text.splitlines():
        if line.startswith("# "):
            aliases.add(line[2:].strip().lower())
            break
    return aliases


# ReMe takes wikilink targets literally (no basename search). Store
# workspace-relative paths so expand_links can resolve neighbors.
_WIKILINK_RE = re.compile(
    r"\[\[(?P<target>[^\[\]|#\n]+?)(?P<anchor>#[^\[\]|\n]+)?(?P<alias>\|[^\[\]\n]+)?\]\]",
)
_KB_RELATIVE_PREFIXES = (
    "business/",
    "test/",
    "wiki/",
    "procedure/",
    "personal/",
    "_inbox/",
)
DEFAULT_KNOWLEDGE_DIR = "knowledge"


def _looks_like_wikilink_path(target: str) -> bool:
    text = (target or "").replace("\\", "/").strip()
    if not text:
        return False
    return "/" in text or text.lower().endswith(".md")


def _wikilink_title_index(kb_id: str) -> dict[str, str]:
    """Map lowercase title/slug aliases to KB-relative paths."""
    root = kb_root(kb_id)
    index: dict[str, str] = {}
    for path in _iter_published_node_paths(kb_id):
        try:
            rel = str(path.relative_to(root)).replace("\\", "/")
        except ValueError:
            continue
        for alias in _node_title_aliases(path):
            index.setdefault(alias, rel)
    return index


def _normalize_workspace_wikilink_path(
    target: str,
    *,
    knowledge_dir: str = DEFAULT_KNOWLEDGE_DIR,
) -> str:
    """Turn a path-like wikilink target into a workspace-relative path."""
    path = (target or "").replace("\\", "/").strip().lstrip("./")
    kd = (knowledge_dir or DEFAULT_KNOWLEDGE_DIR).replace("\\", "/").strip("/")
    if not path:
        return path
    if path == kd or path.startswith(kd + "/"):
        return path
    if any(path == p.rstrip("/") or path.startswith(p) for p in _KB_RELATIVE_PREFIXES):
        return f"{kd}/{path}"
    if path.lower().endswith(".md") and "/" not in path:
        return f"{kd}/{path}"
    return path


def resolve_wikilink_target(
    target: str,
    *,
    title_index: dict[str, str] | None = None,
    knowledge_dir: str = DEFAULT_KNOWLEDGE_DIR,
) -> tuple[str, str]:
    """Resolve a wikilink target to ``(workspace_path_or_title, display)``.

    Unresolved titles are returned unchanged so the intent is not dropped.
    """
    raw = (target or "").strip()
    display = raw
    if not raw:
        return raw, display
    kd = (knowledge_dir or DEFAULT_KNOWLEDGE_DIR).replace("\\", "/").strip("/")
    if _looks_like_wikilink_path(raw):
        path = _normalize_workspace_wikilink_path(raw, knowledge_dir=kd)
        stem = Path(path).stem
        return path, stem or display
    index = title_index or {}
    rel = index.get(raw.lower()) or index.get(_slugify(raw).lower())
    if rel:
        return f"{kd}/{rel}", raw
    return raw, display


def format_wikilink(target: str, display: str, *, anchor: str = "") -> str:
    """Render ``[[path|title]]`` when target is a path; otherwise ``[[title]]``."""
    safe_target = (
        (target or "").replace("\\", "/").replace("]]", "").replace("[", "")
    )
    safe_display = (
        (display or "").replace("]]", "").replace("[", "").replace("|", "")
    )
    safe_anchor = (anchor or "").strip()
    if safe_anchor and not safe_anchor.startswith("#"):
        safe_anchor = "#" + safe_anchor
    if _looks_like_wikilink_path(safe_target) and safe_display and safe_display != safe_target:
        return f"[[{safe_target}{safe_anchor}|{safe_display}]]"
    return f"[[{safe_target}{safe_anchor}]]"


def _rewrite_wikilinks_in_text(
    text: str,
    *,
    title_index: dict[str, str],
    knowledge_dir: str = DEFAULT_KNOWLEDGE_DIR,
) -> str:
    """Rewrite title-only wikilinks to workspace-relative paths (idempotent)."""

    def _sub(match: re.Match[str]) -> str:
        target = (match.group("target") or "").strip()
        anchor = match.group("anchor") or ""
        alias = match.group("alias") or ""
        display = alias[1:].strip() if alias.startswith("|") else target
        if _looks_like_wikilink_path(target):
            path = _normalize_workspace_wikilink_path(
                target, knowledge_dir=knowledge_dir,
            )
            if path == target and alias:
                return match.group(0)
            return format_wikilink(path, display or Path(path).stem, anchor=anchor)
        resolved, resolved_display = resolve_wikilink_target(
            target, title_index=title_index, knowledge_dir=knowledge_dir,
        )
        if resolved == target and not _looks_like_wikilink_path(resolved):
            return match.group(0)
        return format_wikilink(
            resolved,
            display if alias else resolved_display,
            anchor=anchor,
        )

    return _WIKILINK_RE.sub(_sub, text)


def _rewrite_wikilinks_file(
    path: Path,
    title_index: dict[str, str],
    knowledge_dir: str = DEFAULT_KNOWLEDGE_DIR,
) -> bool:
    """Rewrite wikilinks in one markdown file. Returns True if changed."""
    try:
        original = path.read_text(encoding="utf-8")
    except OSError:
        return False
    updated = _rewrite_wikilinks_in_text(
        original, title_index=title_index, knowledge_dir=knowledge_dir,
    )
    if updated == original:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def _wikilink_target_key(link: str) -> str:
    """Normalize a wikilink (full ``[[...]]`` or raw target) for set membership."""
    raw = (link or "").strip()
    match = _WIKILINK_RE.search(raw) if "[[" in raw else None
    target = (match.group("target") if match else raw).replace("\\", "/")
    return target.strip().lower()


def _union_body_wikilinks(old_body: str, new_body: str) -> str:
    """Ensure wikilinks present in ``old_body`` survive into ``new_body``."""
    old_matches = list(_WIKILINK_RE.finditer(old_body or ""))
    if not old_matches:
        return new_body
    body = new_body or ""
    seen = {
        _wikilink_target_key(m.group(0))
        for m in _WIKILINK_RE.finditer(body)
    }
    missing = []
    for match in old_matches:
        key = _wikilink_target_key(match.group(0))
        if key in seen:
            continue
        missing.append(match.group(0))
        seen.add(key)
    if not missing:
        return body
    bullets = "\n".join(f"- {item}" for item in missing)
    heading_re = re.compile(r"^##\s+(关联|Links)\s*$", re.MULTILINE)
    heading = heading_re.search(body)
    if heading:
        insert_at = heading.end()
        prefix = body[:insert_at]
        suffix = body[insert_at:]
        glue = "" if prefix.endswith("\n") else "\n"
        rest = suffix.lstrip("\n")
        return f"{prefix}{glue}{bullets}\n{rest}"
    trimmed = body.rstrip()
    return f"{trimmed}\n\n## 关联\n\n{bullets}\n"


_PRE_HEADINGS = frozenset({"前置条件", "preconditions"})
_STEP_HEADINGS = frozenset({"测试步骤", "steps", "步骤"})
_EXP_HEADINGS = frozenset({"预期结果", "expected"})
_LINK_HEADINGS = frozenset({"关联", "links"})


def _split_body_sections(
    body: str,
) -> tuple[str, str, list[tuple[str, str]]]:
    """Return ``(h1, lead, [(heading, content), ...])``."""
    lines = (body or "").splitlines()
    h1 = ""
    rest_start = 0
    if lines and lines[0].startswith("# "):
        h1 = lines[0][2:].strip()
        rest_start = 1
        if rest_start < len(lines) and not lines[rest_start].strip():
            rest_start += 1
    sections: list[tuple[str, str]] = []
    current = ""
    buf: list[str] = []
    for line in lines[rest_start:]:
        if line.startswith("## "):
            if current or any(part.strip() for part in buf):
                sections.append((current, "\n".join(buf).strip()))
            current = line[3:].strip()
            buf = []
        else:
            buf.append(line)
    if current or any(part.strip() for part in buf):
        sections.append((current, "\n".join(buf).strip()))
    lead = ""
    structured: list[tuple[str, str]] = []
    if sections and sections[0][0] == "":
        lead = sections[0][1]
        structured = sections[1:]
    else:
        structured = sections
    return h1, lead, structured


def _heading_kind(heading: str) -> str:
    key = (heading or "").strip().lower()
    if key in _PRE_HEADINGS:
        return "pre"
    if key in _STEP_HEADINGS:
        return "steps"
    if key in _EXP_HEADINGS:
        return "expected"
    if key in _LINK_HEADINGS:
        return "links"
    return "other"


def _render_steps(steps: list[str]) -> str:
    return "\n".join(f"{i}. {s}" for i, s in enumerate(steps, start=1))


def structural_merge_body(
    old_body: str,
    unit: KnowledgeUnit,
    *,
    formatted_links: list[str] | None = None,
) -> str:
    """Deterministic weave of ``unit`` into ``old_body`` (no LLM).

    Used by explicit ``save_to_knowledge`` updates. Replaces the lead
    summary and any structured test sections the unit actually provides,
    keeps unrecognized sections, and unions the links section.
    """
    h1, lead, sections = _split_body_sections(old_body)
    title = h1 or unit.name
    new_lead = unit.summary.strip() if unit.summary.strip() else lead
    kept: list[tuple[str, str]] = []
    replaced = {"pre": False, "steps": False, "expected": False, "links": False}
    for heading, content in sections:
        kind = _heading_kind(heading)
        if kind == "pre" and unit.preconditions.strip():
            kept.append((heading, unit.preconditions.strip()))
            replaced["pre"] = True
        elif kind == "steps" and unit.steps:
            kept.append((heading, _render_steps(unit.steps)))
            replaced["steps"] = True
        elif kind == "expected" and unit.expected.strip():
            kept.append((heading, unit.expected.strip()))
            replaced["expected"] = True
        elif kind == "links":
            replaced["links"] = True
            kept.append((heading, content))
        else:
            kept.append((heading, content))
    if unit.preconditions.strip() and not replaced["pre"]:
        kept.append(("前置条件", unit.preconditions.strip()))
    if unit.steps and not replaced["steps"]:
        kept.append(("测试步骤", _render_steps(unit.steps)))
    if unit.expected.strip() and not replaced["expected"]:
        kept.append(("预期结果", unit.expected.strip()))
    link_items = list(formatted_links or [])
    if not link_items:
        link_items = [f"[[{item}]]" for item in unit.links if item.strip()]
    # Union old 关联 bullets with new links.
    old_link_block = ""
    for heading, content in kept:
        if _heading_kind(heading) == "links":
            old_link_block = content
            break
    combined_links: list[str] = []
    seen_keys: set[str] = set()
    for raw in list(_WIKILINK_RE.finditer(old_link_block or old_body or "")):
        key = _wikilink_target_key(raw.group(0))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        combined_links.append(raw.group(0))
    for item in link_items:
        key = _wikilink_target_key(item)
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)
        combined_links.append(item)
    out_sections = [
        (heading, content)
        for heading, content in kept
        if _heading_kind(heading) != "links"
    ]
    if combined_links:
        bullets = "\n".join(f"- {item}" for item in combined_links)
        out_sections.append(("关联", bullets))
    lines = [f"# {title}", ""]
    if new_lead:
        lines.extend([new_lead, ""])
    for heading, content in out_sections:
        lines.extend([f"## {heading}", "", content, ""])
    return "\n".join(lines).rstrip() + "\n"


def migrate_wikilink_targets(
    kb_id: str,
    *,
    knowledge_dir: str = DEFAULT_KNOWLEDGE_DIR,
) -> int:
    """Rewrite title-only ``[[wikilink]]`` targets in published nodes.

    Returns the number of files changed. Idempotent. Holds the KB write
    lock so concurrent integrate/merge cannot race the rewrite.
    """
    kb_id = validate_kb_id(kb_id)
    changed = 0
    with knowledge_write_lock(kb_id):
        title_index = _wikilink_title_index(kb_id)
        for path in _iter_published_node_paths(kb_id):
            if _rewrite_wikilinks_file(path, title_index, knowledge_dir):
                changed += 1
    if changed:
        logger.info(
            "Migrated wikilink targets in %d published node(s) of kb %s",
            changed,
            kb_id,
        )
    return changed


def _seed_title_index_from_units(
    title_index: dict[str, str],
    units: list[KnowledgeUnit],
) -> None:
    """Predict paths for in-batch units so sibling links can resolve."""
    for unit in units:
        bucket = _normalize_bucket(unit.bucket, "business/wiki")
        rel = f"{bucket}/{_slugify(unit.name)}.md"
        title_index.setdefault(unit.name.strip().lower(), rel)
        title_index.setdefault(_slugify(unit.name).lower(), rel)


def _find_exact_published_node(
    kb_id: str,
    name: str,
    *,
    preferred_bucket: str = "",
) -> MergeCandidate | None:
    """Locate a published node whose title/slug exactly matches ``name``.

    Prefers ``preferred_bucket`` (same-bucket exact hit) then same-domain
    hits, then any published match. Returns a *clear* merge candidate so
    exact title collisions can CORROBORATE/REFINE instead of being dropped.
    """
    root = kb_root(kb_id)
    name_l = (name or "").strip().lower()
    if not name_l:
        return None
    slug_l = _slugify(name).lower()
    preferred = (preferred_bucket or "").strip().lower()
    preferred_domain = _domain_of_bucket(preferred) if preferred else ""

    ranked: list[tuple[int, Path]] = []
    for path in _iter_published_node_paths(kb_id):
        aliases = _node_title_aliases(path)
        if name_l not in aliases and slug_l not in aliases:
            continue
        try:
            rel = str(path.relative_to(root)).replace("\\", "/")
        except ValueError:
            continue
        score = 0
        # Bucket path prefix for namespaced dirs (business/wiki/...).
        bucket_key = "/".join(Path(rel).parts[:2]) if len(Path(rel).parts) >= 2 else Path(rel).parts[0]
        if preferred and (
            rel.startswith(preferred + "/") or bucket_key == preferred
        ):
            score = 2
        elif preferred_domain and _domain_of_bucket(rel) == preferred_domain:
            score = 1
        ranked.append((score, path))

    if not ranked:
        return None
    ranked.sort(key=lambda item: (-item[0], str(item[1])))
    best = ranked[0][1]
    rel = str(best.relative_to(root)).replace("\\", "/")
    # Prefer human title from frontmatter/H1 when available.
    aliases = _node_title_aliases(best)
    display = name.strip()
    try:
        text = best.read_text(encoding="utf-8", errors="ignore")
        fm, _body = _parse_frontmatter(text)
        fm_name = fm.get("name", "").strip().strip('"').strip("'")
        if fm_name:
            display = fm_name
        else:
            for line in text.splitlines():
                if line.startswith("# "):
                    display = line[2:].strip()
                    break
    except OSError:
        pass
    del aliases
    return MergeCandidate(
        name=display or name,
        path=rel,
        ratio=1.0,
        is_clear=True,
    )

def _frontmatter_description(summary: str) -> str:
    """One-line, YAML-safe description for ReMe node_search to inline.

    ReMe's ``node_search`` returns frontmatter ``name`` + ``description``
    per node. KB nodes historically had no ``description``, so node-level
    recall returned empty descriptions. We synthesize one from the unit
    summary (first line, capped) so node-level recall yields a useful
    entity overview without a follow-up ``read``.
    """
    line = (summary or "").strip().replace("\r", " ").replace("\n", " ")
    line = re.sub(r"\s+", " ", line)
    if len(line) > 120:
        line = line[:117].rstrip() + "..."
    # Strip double quotes so the quoted YAML value round-trips safely.
    return line.replace('"', "")


def _frontmatter_description_from_body(body: str, fallback: str = "") -> str:
    """Description from the merged body: first prose paragraph, not the update snippet."""
    parts: list[str] = []
    for line in (body or "").splitlines():
        stripped = line.strip()
        if not stripped:
            if parts:
                break
            continue
        if stripped.startswith("#"):
            continue
        if stripped.startswith("[[") or stripped.startswith("- [["):
            continue
        parts.append(stripped)
        if sum(len(item) for item in parts) >= 120:
            break
    text = " ".join(parts).strip()
    return _frontmatter_description(text or fallback)


def _yaml_scalar(value: str) -> str:
    """Quote a scalar for frontmatter; empty becomes empty string field."""
    if value == "":
        return '""'
    safe = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{safe}"'


def _node_markdown(
    unit: KnowledgeUnit,
    *,
    agent_id: str,
    derived_from: list[str],
    status: str = "published",
    bucket: str | None = None,
    title_index: dict[str, str] | None = None,
    knowledge_dir: str = DEFAULT_KNOWLEDGE_DIR,
    inbox_meta: InboxMeta | None = None,
) -> str:
    """Render a unit as frontmatter + body markdown.

    ``bucket`` overrides ``unit.bucket`` in the rendered frontmatter so
    callers that normalize the bucket (e.g. legacy flat → ``business/``)
    write the resolved value, keeping the on-disk path and the
    frontmatter in sync.

    Test-domain structured fields are written to frontmatter so
    ``node_search`` can surface them without a follow-up ``read``, and
    also rendered into the body as sections for chunk-level recall.
    ``links`` become ``[[wikilink]]`` lines. Titles are resolved to
    workspace-relative paths (``knowledge/business/wiki/foo.md``) so
    ReMe's ``expand_links`` can follow the requirement↔case↔defect
    graph on recall; the original title is kept as a display alias.
    """
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    safe_name = unit.name.replace('"', "")
    description = _frontmatter_description(unit.summary)
    resolved_bucket = bucket if bucket is not None else unit.bucket
    fm_lines = [
        "---",
        f'name: "{safe_name}"',
        f'description: "{description}"',
        f"bucket: {resolved_bucket}",
        f"status: {status}",
        f"confidence: {unit.confidence}",
        f"updated_by_agent: {agent_id}",
        f"updated_at: {now}",
        f"derived_from: {_yaml_list(derived_from)}",
        f"signals: {_yaml_list(unit.signals)}",
    ]
    # Test-domain structured fields (omitted when empty so business nodes
    # keep their lean frontmatter).
    if unit.priority:
        fm_lines.append(f"priority: {_yaml_scalar(unit.priority)}")
    if unit.requirement_id:
        fm_lines.append(
            f"requirement_id: {_yaml_scalar(unit.requirement_id)}",
        )
    if unit.links:
        fm_lines.append(f"links: {_yaml_list(unit.links)}")
    if inbox_meta is not None:
        fm_lines.append(f"intended_bucket: {inbox_meta.intended_bucket}")
        fm_lines.append(f"inbox_reason: {inbox_meta.reason}")
        fm_lines.append(f"retry_count: {inbox_meta.retry_count}")
        if inbox_meta.merge_target_path:
            fm_lines.append(
                f"merge_target_path: {_yaml_scalar(inbox_meta.merge_target_path)}",
            )
        if unit.action_hint:
            fm_lines.append(f"action_hint: {unit.action_hint}")
        if unit.merge_target:
            fm_lines.append(f"merge_target: {_yaml_scalar(unit.merge_target)}")
    fm_lines.append("---")

    body_lines = [f"# {unit.name}", "", unit.summary]
    if unit.preconditions:
        body_lines.extend(["", "## 前置条件", unit.preconditions])
    if unit.steps:
        body_lines.extend(["", "## 测试步骤"])
        for i, step in enumerate(unit.steps, start=1):
            body_lines.append(f"{i}. {step}")
    if unit.expected:
        body_lines.extend(["", "## 预期结果", unit.expected])
    if unit.links:
        body_lines.extend(["", "## 关联", ""])
        for link in unit.links:
            safe = link.replace("]]", "").replace("[", "")
            target, display = resolve_wikilink_target(
                safe,
                title_index=title_index,
                knowledge_dir=knowledge_dir,
            )
            body_lines.append(f"- {format_wikilink(target, display)}")
    body_lines.append("")
    return "\n".join(fm_lines) + "\n\n" + "\n".join(body_lines) + "\n"


# ---------------------------------------------------------------------------
# Auto-merge: LLM-driven clean body + audit report (publish-then-flag)
# ---------------------------------------------------------------------------

_PRIORITY_RANK = {"P0": 4, "P1": 3, "P2": 2, "P3": 1}

# Anomaly thresholds for audit flagging.
_LOW_CONFIDENCE = 0.55
_LARGE_DIFF_RATIO = 0.5


@dataclass
class MergePayload:
    """Pre-computed LLM merge result for one unit, produced outside the lock.

    ``expected_updated_at`` is the target node's frontmatter ``updated_at``
    captured at pre-read time. Under the write lock, :func:`_merge_node`
    re-reads the target and refuses to apply the payload if the value has
    changed (another writer merged in between) — the unit is then routed
    to ``_inbox`` instead of clobbering a concurrent merge.

    ``llm_ok`` is False when the LLM returned no usable body and
    ``merged_body`` is a structural fallback; the merge still proceeds but
    the audit report is flagged ``llm_merge_fallback``.

    ``integrity_ok`` is False when the post-merge LLM review reported
    dropped still-valid claims or unrelated injection, **or** when the
    review could not be completed (LLM error / unparseable verdict).
    Integrate then routes the unit to ``_inbox`` instead of publishing
    the rewrite (fail-closed).

    ``integrity_skipped`` is True when the review LLM failed or returned
    unparseable output. Combined with ``integrity_ok=False`` this is a
    retryable inbox reason (``integrity_check_skipped``); an explicit
    reject stays ``integrity_failed`` and waits for a human.
    """

    target_path: Path
    expected_updated_at: str
    merged_body: str
    llm_ok: bool
    integrity_ok: bool = True
    integrity_skipped: bool = False


@dataclass
class MergeOutcome:
    """Result of a single in-place merge attempt."""

    done: bool
    reason: str  # "ok" | "at_cap" | "stale" | "no_payload"
    anomalies: list[str]
    report_path: Path | None


class AuditReportSummary(BaseModel):
    """One merge-event summary, surfaced by the audit API."""

    report_id: str
    date: str
    node_path: str
    agent_id: str
    mode: str
    merge_count: int
    corroborate_count: int = 0
    anomalies: list[str] = Field(default_factory=list)
    needs_review: bool = False
    reviewed: bool = False
    report_path: str = ""


class InboxItemSummary(BaseModel):
    """One _inbox draft, surfaced by the inbox API and replay."""

    stem: str
    name: str
    intended_bucket: str
    inbox_reason: str
    merge_target_path: str = ""
    retry_count: int = 0
    retryable: bool = False
    confidence: float = 0.0
    summary: str = ""
    agent_id: str = ""
    updated_at: str = ""
    action_hint: str = ""
    path: str = ""


class InboxActionError(Exception):
    """Human inbox action failed; ``status_code`` maps to the REST layer."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 400,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail or {"message": message}


def _unquote_fm(raw: str) -> str:
    """Strip one layer of YAML quotes from a frontmatter scalar."""
    text = (raw or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return text


def _normalize_unit_bucket(unit: KnowledgeUnit) -> str:
    """Resolve a unit's destination published bucket (never ``_inbox``)."""
    bucket = (unit.bucket or "").strip()
    if bucket == INBOX_BUCKET:
        bucket = ""
    if bucket in PUBLISHED_BUCKETS:
        return bucket
    if bucket in LEGACY_FLAT_BUCKETS:
        return f"business/{bucket}"
    if bucket.startswith("test/"):
        return "test/test_cases"
    return "business/wiki"


def _inbox_reason_from_merge_outcome(reason: str) -> str:
    if reason == "at_cap":
        return INBOX_REASON_AT_CAP
    if reason == "stale":
        return INBOX_REASON_STALE
    return INBOX_REASON_MISSING_PAYLOAD


def _read_retry_count(path: Path) -> int:
    try:
        fm, _body = _parse_frontmatter(path.read_text(encoding="utf-8"))
        return int(_unquote_fm(fm.get("retry_count", "0")))
    except (OSError, TypeError, ValueError):
        return 0


def _drop_inbox_source(
    sources: dict[str, Path],
    unit_name: str,
    *,
    keep: Path | None = None,
) -> None:
    src = sources.get(unit_name.lower())
    if src is None:
        return
    try:
        if not src.is_file():
            return
        if keep is not None and src.resolve() == keep.resolve():
            return
        src.unlink()
    except OSError:
        logger.debug(
            "knowledge_dream: failed to drop inbox source %s",
            src,
            exc_info=True,
        )


def _priority_rank(p: str) -> int:
    return _PRIORITY_RANK.get((p or "").strip().upper(), 0)


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split a node file into raw frontmatter values and body text.

    Returns ``(fm, body)`` where ``fm`` maps frontmatter keys to their raw
    string value (lists kept as their ``["a", "b"]`` literal). Returns
    ``({}, text)`` when no frontmatter fence is present.
    """
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    # First line is "---"; find the closing "---".
    close = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            close = i
            break
    if close is None:
        return {}, text
    fm: dict[str, str] = {}
    for line in lines[1:close]:
        if not line.strip() or line.strip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fm[key.strip()] = value.strip()
    body = "\n".join(lines[close + 1 :])
    return fm, body


def _parse_yaml_list_literal(raw: str) -> list[str]:
    """Parse a ``["a", "b"]`` frontmatter value into a list of strings."""
    raw = (raw or "").strip()
    if not raw or raw == "[]":
        return []
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    items: list[str] = []
    for token in re.findall(r'"((?:[^"\\]|\\.)*)"', raw):
        items.append(token.replace('\\"', '"').replace("\\\\", "\\"))
    return items


def _domain_of_bucket(bucket: str) -> str:
    """Return the domain tag (``test`` / ``business``) for a bucket path."""
    b = (bucket or "").strip("/")
    if b.startswith("test/"):
        return "test"
    return "business"


def _strip_merge_output(raw: str) -> str:
    """Strip code fences from LLM merge output; return the body text."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:markdown|md)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _detect_anomalies(
    *,
    old_body: str,
    new_body: str,
    unit: KnowledgeUnit,
    mode: str,
    merge_count_after: int,
    max_updates: int,
    llm_ok: bool,
    integrity_skipped: bool = False,
) -> list[str]:
    """Flag merge events that warrant a human look.

    The node is already published (publish-then-flag); these flags only
    set ``needs_review`` on the audit report so the API can surface the
    risky ones first. A report with no anomalies is still written for
    traceability but is not flagged.
    """
    flags: list[str] = []
    if unit.confidence < _LOW_CONFIDENCE:
        flags.append("low_confidence")
    old_len = len(old_body or "")
    new_len = len(new_body or "")
    base = max(old_len, 1)
    if abs(new_len - old_len) / base > _LARGE_DIFF_RATIO:
        flags.append("large_body_diff")
    if mode.upper() == "CORRECT":
        flags.append("correct_mode")
    # CORROBORATE does not consume merge_count; do not flag body-rewrite cap.
    if mode.upper() != "CORROBORATE" and merge_count_after >= max_updates:
        flags.append("near_merge_cap")
    if not llm_ok:
        flags.append("llm_merge_fallback")
    if integrity_skipped:
        flags.append("integrity_check_skipped")
    return flags


def _parse_integrity_verdict(raw: str) -> tuple[bool, bool]:
    """Parse the post-merge integrity JSON.

    Returns ``(integrity_ok, parsed_ok)``. ``parsed_ok`` is False when the
    model did not emit a usable object (caller should fail-closed).
    """
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return False, False
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return False, False
    if not isinstance(data, dict):
        return False, False
    lost = data.get("lost_claims") or []
    injected = data.get("injected_unrelated") or []
    if not isinstance(lost, list):
        lost = [lost] if lost else []
    if not isinstance(injected, list):
        injected = [injected] if injected else []
    lost_n = [str(item).strip() for item in lost if str(item).strip()]
    injected_n = [str(item).strip() for item in injected if str(item).strip()]
    if "ok" in data:
        try:
            explicit = bool(data["ok"])
        except (TypeError, ValueError):
            explicit = not lost_n and not injected_n
    else:
        explicit = not lost_n and not injected_n
    ok = explicit and not lost_n and not injected_n
    return ok, True


def _audit_dir(kb_root_path: Path) -> Path:
    return kb_root_path / "_audit"


def _audit_report_path(
    kb_root_path: Path,
    slug: str,
    date_tag: str,
    event_tag: str | int,
) -> Path:
    """Build an audit report path.

    ``event_tag`` is typically the post-event ``merge_count`` for body
    rewrites, or ``c{corroborate_count}`` for frontmatter-only
    reaffirmations (so frequent CORROBORATE does not collide with or
    burn the body-rewrite counter).
    """
    safe_slug = _slugify(slug) or "node"
    return _audit_dir(kb_root_path) / f"{date_tag}_{safe_slug}_{event_tag}.md"


def _write_audit_report(
    report_path: Path,
    *,
    node_path: str,
    agent_id: str,
    mode: str,
    date_tag: str,
    merge_count_after: int,
    anomalies: list[str],
    unit: KnowledgeUnit,
    derived_from: list[str],
    before_text: str,
    after_text: str,
    corroborate_count_after: int = 0,
) -> None:
    """Write a human-readable before/after report and append to the index."""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_id = report_path.stem
    needs_review = bool(anomalies)
    lines = [
        f"# 合并审计报告 {report_id}",
        "",
        f"- 节点: `{node_path}`",
        f"- 智能体: `{agent_id}`",
        f"- 模式: {mode}",
        f"- 日期: {date_tag}",
        f"- merge_count: {merge_count_after}",
        f"- corroborate_count: {corroborate_count_after}",
        f"- 异常标记: {', '.join(anomalies) if anomalies else '（无）'}",
        f"- 需要审计: {'是' if needs_review else '否'}",
        f"- 来源: {', '.join(derived_from) if derived_from else '（无）'}",
        "",
        "## 触发本次合并的知识单元",
        "",
        f"- name: {unit.name}",
        f"- bucket: {unit.bucket}",
        f"- summary: {unit.summary or '（无）'}",
        f"- confidence: {unit.confidence}",
        "",
        "## 合并前",
        "",
        "```markdown",
        before_text.strip(),
        "```",
        "",
        "## 合并后",
        "",
        "```markdown",
        after_text.strip(),
        "```",
        "",
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")

    index_path = _audit_dir(report_path.parent.parent) / "index.jsonl"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "report_id": report_id,
        "date": date_tag,
        "node_path": node_path,
        "agent_id": agent_id,
        "mode": mode,
        "merge_count": merge_count_after,
        "corroborate_count": corroborate_count_after,
        "anomalies": anomalies,
        "needs_review": needs_review,
        "reviewed": False,
        "report_path": str(report_path.relative_to(report_path.parent.parent)).replace("\\", "/"),
    }
    with index_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _normalize_claim_text(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").strip())


def _summary_is_new_claim(
    summary: str,
    old_body: str = "",
    old_description: str = "",
) -> bool:
    """Return True when ``summary`` adds a claim not already in the node."""
    compact = _normalize_claim_text(summary)
    if not compact:
        return False
    haystack = _normalize_claim_text(
        f"{old_description or ''} {old_body or ''}",
    )
    if not haystack:
        return True
    if compact in haystack:
        return False
    sentences = [
        _normalize_claim_text(part)
        for part in re.split(r"[。.!！?？;；]", summary)
        if part.strip()
    ]
    if sentences and all(sent in haystack for sent in sentences):
        return False
    return True


def _has_update_content(unit: KnowledgeUnit) -> bool:
    """Return True if the unit actually carries content to merge."""
    if unit.summary.strip():
        return True
    if unit.preconditions.strip():
        return True
    if unit.steps:
        return True
    if unit.expected.strip():
        return True
    if unit.links:
        return True
    return False


def _has_substantive_update(
    unit: KnowledgeUnit,
    *,
    old_body: str = "",
    old_description: str = "",
) -> bool:
    """Return True when the unit adds content worth a body rewrite.

    Structural test fields always count. A non-empty ``summary`` counts
    only when it is a *new* claim relative to the existing body/description
    (when those are provided). Without an existing body we keep the
    conservative default: any summary is treated as substance so we do
    not silently CORROBORATE and drop a new claim.
    """
    if unit.preconditions.strip():
        return True
    if unit.steps:
        return True
    if unit.expected.strip():
        return True
    if not unit.summary.strip():
        return False
    if not (old_body or "").strip() and not (old_description or "").strip():
        return True
    return _summary_is_new_claim(unit.summary, old_body, old_description)


def _normalize_action_hint(raw: str | None) -> str | None:
    """Normalize LLM / caller action hints to the integrate vocabulary.

    ``MERGE`` is kept as a legacy alias of ``REFINE`` for backward compatibility
    with older extract prompts and tests.
    """
    if not raw:
        return None
    action = str(raw).strip().upper()
    if action == "MERGE":
        return "REFINE"
    if action in _VALID_ACTIONS:
        return action
    return None


def _resolve_integrate_action(
    unit: KnowledgeUnit,
    *,
    has_clear_candidate: bool,
    exact_title_match: bool = False,
    old_body: str = "",
    old_description: str = "",
) -> str:
    """Resolve the integrate action for a unit given merge-candidate clarity.

    Mirrors ReMe's same_abstraction routing:
    - explicit CREATE / CORROBORATE / REFINE / CORRECT win (except CREATE is
      demoted when a clear same-abstraction candidate exists — same entity
      almost never means a brand-new node);
    - empty hint + clear candidate → REFINE if substantive, else CORROBORATE;
    - empty hint + no candidate → CREATE.
    """
    action = _normalize_action_hint(unit.action_hint)
    if action == "CREATE" and (exact_title_match or has_clear_candidate):
        # CREATE against a known same-abstraction node is a mis-label;
        # re-resolve from content so we REFINE/CORROBORATE instead of
        # opening a sibling (or holding as create_conflict).
        action = None
    if action is not None:
        return action
    if has_clear_candidate:
        return (
            "REFINE"
            if _has_substantive_update(
                unit, old_body=old_body, old_description=old_description,
            )
            else "CORROBORATE"
        )
    return "CREATE"


def _enrich_unit_links(unit: KnowledgeUnit, related_names: list[str]) -> None:
    """Union related node titles into ``unit.links`` (synapse weaving).

    Business-domain units skip auto-weaving: LLM-extracted ``links`` stay,
    but title-similar neighbors are not written into the body (those
    ``[[wikilink]]`` lines would be expanded on chunk recall). Test-domain
    units still weave, capped at ``MAX_SYNAPSE_LINKS`` new titles.
    """
    if not related_names:
        return
    if _domain_of_bucket(unit.bucket) == "business":
        return
    seen = {link.strip().lower() for link in unit.links if link.strip()}
    seen.add(unit.name.strip().lower())
    added = 0
    for name in related_names:
        if added >= MAX_SYNAPSE_LINKS:
            break
        key = (name or "").strip()
        if not key or key.lower() in seen:
            continue
        unit.links.append(key)
        seen.add(key.lower())
        added += 1


def _apply_frontmatter_update_fields(
    fm: dict[str, str],
    unit: KnowledgeUnit,
    *,
    agent_id: str,
    derived_from: list[str],
    mode: str,
    now: str,
    merge_count_after: int | None = None,
    corroborate_count_after: int | None = None,
    body_for_description: str | None = None,
) -> None:
    """Apply the shared frontmatter field policy used by merge/corroborate.

    ``merge_count`` tracks body-rewriting REFINE/CORRECT only.
    ``corroborate_count`` tracks frontmatter-only reaffirmations and does
    not consume the body-rewrite quota (``knowledge_merge_max_updates``).
    When ``body_for_description`` is set (the merged body), node-level
    recall describes the published body rather than the latest update snippet.
    """
    is_rewrite = mode.upper() in {"CORRECT", "REFINE", "MERGE"}
    if is_rewrite and body_for_description is not None:
        desc = _frontmatter_description_from_body(
            body_for_description, fallback=unit.summary,
        )
        if desc:
            fm["description"] = _yaml_scalar(desc)
    elif is_rewrite and unit.summary:
        fm["description"] = _yaml_scalar(_frontmatter_description(unit.summary))
    old_pri = fm.get("priority", "").strip().strip('"')
    if _priority_rank(unit.priority) > _priority_rank(old_pri):
        fm["priority"] = _yaml_scalar(unit.priority)
    old_req = fm.get("requirement_id", "").strip().strip('"')
    if unit.requirement_id and unit.requirement_id != old_req:
        merged_req = (
            unit.requirement_id
            if not old_req
            else f"{old_req}, {unit.requirement_id}"
        )
        fm["requirement_id"] = _yaml_scalar(merged_req)
    old_links = set(_parse_yaml_list_literal(fm.get("links", "")))
    new_links = old_links | set(unit.links)
    fm["links"] = _yaml_list(sorted(new_links))
    old_signals = _parse_yaml_list_literal(fm.get("signals", ""))
    for sig in unit.signals:
        if sig not in old_signals:
            old_signals.append(sig)
    fm["signals"] = _yaml_list(old_signals[:16])
    try:
        old_conf = float(fm.get("confidence", "0"))
    except (TypeError, ValueError):
        old_conf = 0.0
    fm["confidence"] = max(old_conf, unit.confidence)
    if merge_count_after is not None:
        fm["merge_count"] = str(merge_count_after)
    if corroborate_count_after is not None:
        fm["corroborate_count"] = str(corroborate_count_after)
    fm["updated_by_agent"] = agent_id
    fm["updated_at"] = now
    merged_derived: list[str] = []
    seen_derived: set[str] = set()
    for item in _parse_yaml_list_literal(fm.get("derived_from", "")) + list(derived_from):
        if not item or item in seen_derived:
            continue
        seen_derived.add(item)
        merged_derived.append(item)
    fm["derived_from"] = _yaml_list(merged_derived[-_MAX_DERIVED_FROM:])


def _render_frontmatter_and_body(fm: dict[str, str], body: str) -> str:
    """Serialize frontmatter + body back to a markdown file string."""
    fm_lines = ["---"]
    if "name" in fm:
        fm_lines.append(f'name: {fm["name"]}')
    for key, value in fm.items():
        if key == "name":
            continue
        fm_lines.append(f"{key}: {value}")
    fm_lines.append("---")
    return "\n".join(fm_lines) + "\n\n" + body.strip() + "\n"


def _corroborate_node(
    target_path: Path,
    unit: KnowledgeUnit,
    *,
    agent_id: str,
    derived_from: list[str],
    max_updates: int,
    kb_root_path: Path,
    audit_sink: list[AuditReportSummary] | None = None,
) -> MergeOutcome:
    """Reaffirm an existing node without rewriting its body (CORROBORATE).

    Updates provenance / confidence / signals / links only. Inspired by
    ReMe's CORROBORATE action: same abstraction reappears → strengthen
    evidence, keep the abstract body stable.

    Does **not** consume ``merge_count`` / ``knowledge_merge_max_updates``:
    frequent reaffirmations must not block later REFINE/CORRECT. A separate
    ``corroborate_count`` is tracked for observability and audit filenames.
    """
    try:
        text = target_path.read_text(encoding="utf-8")
    except OSError:
        return MergeOutcome(False, "no_payload", [], None)
    fm, body = _parse_frontmatter(text)

    try:
        merge_count = int(fm.get("merge_count", "0"))
    except (TypeError, ValueError):
        merge_count = 0
    try:
        corroborate_count = int(fm.get("corroborate_count", "0"))
    except (TypeError, ValueError):
        corroborate_count = 0
    corroborate_count_after = corroborate_count + 1

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    date_tag = now[:10]
    _apply_frontmatter_update_fields(
        fm,
        unit,
        agent_id=agent_id,
        derived_from=derived_from,
        mode="CORROBORATE",
        now=now,
        corroborate_count_after=corroborate_count_after,
    )
    new_text = _render_frontmatter_and_body(fm, body)
    target_path.write_text(new_text, encoding="utf-8")

    anomalies = _detect_anomalies(
        old_body=body,
        new_body=body,
        unit=unit,
        mode="CORROBORATE",
        merge_count_after=merge_count,
        max_updates=max_updates,
        llm_ok=True,
    )
    rel_node = str(target_path.relative_to(kb_root_path)).replace("\\", "/")
    report_path = _audit_report_path(
        kb_root_path, target_path.stem, date_tag, f"c{corroborate_count_after}",
    )
    _write_audit_report(
        report_path,
        node_path=rel_node,
        agent_id=agent_id,
        mode="CORROBORATE",
        date_tag=date_tag,
        merge_count_after=merge_count,
        corroborate_count_after=corroborate_count_after,
        anomalies=anomalies,
        unit=unit,
        derived_from=derived_from,
        before_text=text,
        after_text=new_text,
    )
    summary = AuditReportSummary(
        report_id=report_path.stem,
        date=date_tag,
        node_path=rel_node,
        agent_id=agent_id,
        mode="CORROBORATE",
        merge_count=merge_count,
        corroborate_count=corroborate_count_after,
        anomalies=anomalies,
        needs_review=bool(anomalies),
        reviewed=False,
        report_path=str(report_path.relative_to(kb_root_path)).replace("\\", "/"),
    )
    if audit_sink is not None:
        audit_sink.append(summary)
    return MergeOutcome(True, "ok", anomalies, report_path)


def _merge_node(
    target_path: Path,
    unit: KnowledgeUnit,
    *,
    agent_id: str,
    derived_from: list[str],
    mode: str,
    max_updates: int,
    payload: MergePayload,
    kb_root_path: Path,
    audit_sink: list[AuditReportSummary] | None = None,
) -> MergeOutcome:
    """Merge ``unit`` into the existing node at ``target_path`` in place.

    The merged body is **pre-computed by the LLM** (in
    :func:`run_knowledge_dream`, outside the write lock) and carried in
    ``payload.merged_body``. Under the lock this function re-reads the
    target; if ``updated_at`` changed since the payload was built the
    payload is stale and the merge is refused (caller routes to
    ``_inbox``). Frontmatter scalar fields use the conservative policy
    (priority takes the more urgent, links/signals union, description
    is rewritten from the merged body so node recall matches the current
    statement of truth). A before/after audit report is always
    written; anomalies set ``needs_review`` so the API can surface them.
    """
    try:
        text = target_path.read_text(encoding="utf-8")
    except OSError:
        return MergeOutcome(False, "no_payload", [], None)
    fm, body = _parse_frontmatter(text)

    merge_count = 0
    try:
        merge_count = int(fm.get("merge_count", "0"))
    except (TypeError, ValueError):
        merge_count = 0
    if merge_count >= max_updates:
        return MergeOutcome(False, "at_cap", [], None)
    try:
        corroborate_count = int(fm.get("corroborate_count", "0"))
    except (TypeError, ValueError):
        corroborate_count = 0

    # Staleness guard: another writer merged between pre-read and lock.
    current_updated_at = fm.get("updated_at", "").strip().strip('"')
    if payload.expected_updated_at and current_updated_at != payload.expected_updated_at:
        return MergeOutcome(False, "stale", [], None)

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    date_tag = now[:10]
    merge_count_after = merge_count + 1

    # --- body: LLM-produced clean rewrite (no append-only history) ---
    new_body = payload.merged_body.strip() or body
    new_body = _union_body_wikilinks(body, new_body)

    # --- frontmatter field policy (shared with CORROBORATE) ---
    _apply_frontmatter_update_fields(
        fm,
        unit,
        agent_id=agent_id,
        derived_from=derived_from,
        mode=mode,
        merge_count_after=merge_count_after,
        now=now,
        body_for_description=new_body,
    )

    new_text = _render_frontmatter_and_body(fm, new_body)
    target_path.write_text(new_text, encoding="utf-8")

    anomalies = _detect_anomalies(
        old_body=body,
        new_body=new_body,
        unit=unit,
        mode=mode,
        merge_count_after=merge_count_after,
        max_updates=max_updates,
        llm_ok=payload.llm_ok,
        integrity_skipped=payload.integrity_skipped,
    )
    rel_node = str(target_path.relative_to(kb_root_path)).replace("\\", "/")
    report_path = _audit_report_path(
        kb_root_path, target_path.stem, date_tag, merge_count_after,
    )
    _write_audit_report(
        report_path,
        node_path=rel_node,
        agent_id=agent_id,
        mode=mode,
        date_tag=date_tag,
        merge_count_after=merge_count_after,
        corroborate_count_after=corroborate_count,
        anomalies=anomalies,
        unit=unit,
        derived_from=derived_from,
        before_text=text,
        after_text=new_text,
    )
    summary = AuditReportSummary(
        report_id=report_path.stem,
        date=date_tag,
        node_path=rel_node,
        agent_id=agent_id,
        mode=mode,
        merge_count=merge_count_after,
        corroborate_count=corroborate_count,
        anomalies=anomalies,
        needs_review=bool(anomalies),
        reviewed=False,
        report_path=str(report_path.relative_to(kb_root_path)).replace("\\", "/"),
    )
    if audit_sink is not None:
        audit_sink.append(summary)
    return MergeOutcome(True, "ok", anomalies, report_path)


def integrate_units(
    *,
    kb_id: str,
    agent_id: str,
    units: list[KnowledgeUnit],
    derived_from: list[str],
    write_mode: str = "open",
    inbox_enabled: bool = False,
    semantic_dup_names: set[str] | None = None,
    merge_candidates: dict[str, MergeCandidate] | None = None,
    merge_enabled: bool = False,
    merge_max_updates: int = 5,
    merge_payloads: dict[str, MergePayload] | None = None,
    audit_sink: list[AuditReportSummary] | None = None,
    knowledge_dir: str = DEFAULT_KNOWLEDGE_DIR,
    inbox_sources: dict[str, Path] | None = None,
) -> list[Path]:
    """Write units into the shared KB under write lock. Returns written paths.

    Routing rules (when ``merge_enabled`` is False the legacy behavior is
    preserved — CORRECT/REFINE/MERGE/semantic-dup all go to ``_inbox``,
    and exact title/slug hits are skipped to avoid ``name-2.md`` near-dups):

    - Exact title/slug match against published nodes:
      - ``merge_enabled=False`` → skip (no second file).
      - ``merge_enabled=True`` → inject a clear merge candidate and
        CORROBORATE/REFINE/CORRECT into that node (CREATE is demoted so
        same-name updates are not dropped).
    - Auto-integrate (only when ``merge_enabled``): a unit with a *clear*
      same-domain merge candidate is routed by resolved action:
      - ``CORROBORATE`` → frontmatter-only reaffirmation via
        :func:`_corroborate_node` (no body rewrite, no LLM payload;
        does not consume ``merge_max_updates``).
      - ``REFINE`` / ``CORRECT`` (``MERGE`` aliases to ``REFINE``) →
        LLM-precomputed clean body via :func:`_merge_node`.
      - ``CREATE`` + clear candidate is demoted to REFINE/CORROBORATE
        (same entity; do not open a sibling). Cross-domain still goes
        to ``_inbox``.
      - Integrity review rejected the rewrite → ``_inbox``
        (``integrity_failed``). Review LLM failed or returned unparseable
        output → ``_inbox`` (``integrity_check_skipped``, retryable).
    - Empty action hint + clear candidate → ``CORROBORATE`` when the unit
      has no substantive structural fields, else ``REFINE``.
    - No usable LLM merge body for REFINE/CORRECT → ``_inbox``.
    - Cross-domain candidate → ``_inbox`` (v1: same-domain only).
    - Candidate node already at ``merge_max_updates`` body rewrites →
      ``_inbox`` for REFINE/CORRECT only (CORROBORATE still applies).
    - Stale payload (target changed between pre-read and lock) → ``_inbox``.
    - ``CORRECT`` with no candidate → ``_inbox`` (do not publish a sibling).
    - ``REFINE`` with no candidate → published as new.
    - ``strict`` mode + low confidence → ``_inbox``.
    - otherwise → published in the unit's bucket.

    ``audit_sink`` collects an :class:`AuditReportSummary` per successful
    merge/corroborate so the caller (:func:`run_knowledge_dream`) can
    surface them.

    ``inbox_sources`` maps ``unit.name.lower()`` to an existing ``_inbox``
    draft path (replay). Failed re-integrates overwrite that file and bump
    ``retry_count``; successful merge/publish deletes it.

    ``inbox_enabled`` is unused here (drafts are always written so nothing
    is lost). Auto-replay of retryable drafts is gated in
    :func:`run_knowledge_dream`; human promote/merge/reject live on the
    knowledge-bases API.
    """
    del inbox_enabled
    kb_id = validate_kb_id(kb_id)
    semantic_dups = semantic_dup_names or set()
    # Copy so injecting exact-match candidates does not mutate the caller's dict.
    candidates = dict(merge_candidates or {})
    payloads = merge_payloads or {}
    sources = inbox_sources or {}
    mount_name = (knowledge_dir or DEFAULT_KNOWLEDGE_DIR).strip() or DEFAULT_KNOWLEDGE_DIR
    written: list[Path] = []
    with knowledge_write_lock(kb_id):
        existing = _existing_node_titles(kb_id)
        root = kb_root(kb_id)
        title_index = _wikilink_title_index(kb_id)
        _seed_title_index_from_units(title_index, units)
        merged_targets: set[str] = set()
        for unit in units:
            slug = _slugify(unit.name)
            exact = None
            if unit.name.lower() in existing or slug.lower() in existing:
                exact = _find_exact_published_node(
                    kb_id, unit.name, preferred_bucket=unit.bucket,
                )
            # Exact title/slug hit: when merge is off, keep the historical
            # skip so we do not create name-2.md near-duplicates. When merge
            # is on, inject a clear candidate and fall through to
            # CORROBORATE/REFINE/CORRECT — skipping here used to drop updates.
            if exact is not None and not merge_enabled:
                logger.info(
                    "knowledge_dream: skip exact duplicate %r in kb %s "
                    "(merge disabled)",
                    unit.name,
                    kb_id,
                )
                continue
            if exact is not None:
                key = unit.name.lower()
                prior = candidates.get(key)
                # Exact title must always win over a fuzzy clear candidate —
                # otherwise we can REFINE the wrong near-neighbor node.
                if prior is not None and prior.related_names:
                    exact.related_names = list(
                        dict.fromkeys(
                            list(exact.related_names) + list(prior.related_names),
                        ),
                    )
                candidates[key] = exact
                logger.info(
                    "knowledge_dream: exact title/slug %r → merge candidate "
                    "%s in kb %s",
                    unit.name,
                    exact.path,
                    kb_id,
                )

            # --- auto-merge / corroborate gating ---
            merged = False
            inbox_reason: str | None = None
            inbox_target = ""
            if merge_enabled:
                cand = candidates.get(unit.name.lower())
                if (cand is None or not cand.path) and unit.merge_target:
                    hinted = _find_exact_published_node(
                        kb_id,
                        unit.merge_target,
                        preferred_bucket=unit.bucket,
                    )
                    if hinted is not None:
                        cand = hinted
                if cand is not None and cand.path:
                    inbox_target = cand.path
                    if not cand.is_clear:
                        # A near-duplicate exists but the target is
                        # ambiguous (two equally-similar nodes) — hold
                        # for review rather than publishing a near-dup or
                        # merging into the wrong target.
                        inbox_reason = INBOX_REASON_AMBIGUOUS
                    else:
                        unit_domain = _domain_of_bucket(unit.bucket)
                        cand_domain = _domain_of_bucket(cand.path)
                        target_path = root / cand.path
                        old_body = ""
                        old_description = ""
                        try:
                            pre_text = target_path.read_text(encoding="utf-8")
                            pre_fm, old_body = _parse_frontmatter(pre_text)
                            old_description = (
                                pre_fm.get("description", "")
                                .strip()
                                .strip('"')
                                .strip("'")
                            )
                        except OSError:
                            pass
                        action = _resolve_integrate_action(
                            unit,
                            has_clear_candidate=True,
                            exact_title_match=exact is not None,
                            old_body=old_body,
                            old_description=old_description,
                        )
                        if action == "CREATE":
                            # LLM explicitly wants new but a same-domain
                            # node exists — genuine conflict, hold.
                            inbox_reason = INBOX_REASON_CREATE_CONFLICT
                        elif cand_domain != unit_domain:
                            # v1: same-domain merge only; cross-domain → inbox.
                            inbox_reason = INBOX_REASON_CROSS_DOMAIN
                        elif action == "CORROBORATE":
                            outcome = _corroborate_node(
                                target_path,
                                unit,
                                agent_id=agent_id,
                                derived_from=derived_from,
                                max_updates=merge_max_updates,
                                kb_root_path=root,
                                audit_sink=audit_sink,
                            )
                            if outcome.done:
                                written.append(target_path)
                                existing.add(unit.name.lower())
                                existing.add(slug.lower())
                                logger.info(
                                    "knowledge_dream: corroborated %r into %s "
                                    "in kb %s (anomalies=%s)",
                                    unit.name,
                                    cand.path,
                                    kb_id,
                                    ",".join(outcome.anomalies) or "none",
                                )
                                merged = True
                            else:
                                logger.info(
                                    "knowledge_dream: corroborate skipped %r "
                                    "into %s in kb %s reason=%s",
                                    unit.name,
                                    cand.path,
                                    kb_id,
                                    outcome.reason,
                                )
                                inbox_reason = INBOX_REASON_CORROBORATE_FAILED
                        else:
                            # REFINE / CORRECT — need an LLM body payload.
                            target_key = str(target_path.resolve())
                            if target_key in merged_targets:
                                # Same-batch: body already rewritten with a
                                # combined payload; keep remaining provenance.
                                outcome = _corroborate_node(
                                    target_path,
                                    unit,
                                    agent_id=agent_id,
                                    derived_from=derived_from,
                                    max_updates=merge_max_updates,
                                    kb_root_path=root,
                                    audit_sink=audit_sink,
                                )
                                if outcome.done:
                                    written.append(target_path)
                                    existing.add(unit.name.lower())
                                    existing.add(slug.lower())
                                    merged = True
                                else:
                                    inbox_reason = (
                                        INBOX_REASON_CORROBORATE_FAILED
                                    )
                            else:
                                payload = payloads.get(unit.name.lower())
                                if payload is None or not payload.llm_ok:
                                    inbox_reason = INBOX_REASON_MISSING_PAYLOAD
                                elif not payload.integrity_ok:
                                    logger.info(
                                        "knowledge_dream: merge integrity failed "
                                        "for %r in kb %s skipped=%s → inbox",
                                        unit.name, kb_id,
                                        payload.integrity_skipped,
                                    )
                                    inbox_reason = (
                                        INBOX_REASON_INTEGRITY_SKIPPED
                                        if payload.integrity_skipped
                                        else INBOX_REASON_INTEGRITY_FAILED
                                    )
                                elif not _has_update_content(unit):
                                    logger.info(
                                        "knowledge_dream: unit %r has no update "
                                        "content for refine/correct in kb %s → inbox",
                                        unit.name, kb_id,
                                    )
                                    inbox_reason = INBOX_REASON_EMPTY_UPDATE
                                elif (
                                    payload.target_path.resolve()
                                    != target_path.resolve()
                                ):
                                    logger.info(
                                        "knowledge_dream: stale merge target for "
                                        "%r (payload=%s actual=%s) → inbox",
                                        unit.name,
                                        payload.target_path,
                                        target_path,
                                    )
                                    inbox_reason = INBOX_REASON_STALE_TARGET
                                else:
                                    mode = (
                                        "CORRECT"
                                        if action == "CORRECT"
                                        else "REFINE"
                                    )
                                    outcome = _merge_node(
                                        target_path,
                                        unit,
                                        agent_id=agent_id,
                                        derived_from=derived_from,
                                        mode=mode,
                                        max_updates=merge_max_updates,
                                        payload=payload,
                                        kb_root_path=root,
                                        audit_sink=audit_sink,
                                    )
                                    if outcome.done:
                                        written.append(target_path)
                                        existing.add(unit.name.lower())
                                        existing.add(slug.lower())
                                        merged_targets.add(target_key)
                                        logger.info(
                                            "knowledge_dream: merged %r into %s "
                                            "in kb %s mode=%s (anomalies=%s)",
                                            unit.name,
                                            cand.path,
                                            kb_id,
                                            mode,
                                            ",".join(outcome.anomalies) or "none",
                                        )
                                        merged = True
                                    else:
                                        logger.info(
                                            "knowledge_dream: merge skipped %r "
                                            "into %s in kb %s reason=%s",
                                            unit.name,
                                            cand.path,
                                            kb_id,
                                            outcome.reason,
                                        )
                                        inbox_reason = (
                                            _inbox_reason_from_merge_outcome(
                                                outcome.reason,
                                            )
                                        )
            if merged:
                _drop_inbox_source(sources, unit.name)
                continue

            if inbox_reason is None:
                resolved = _normalize_action_hint(unit.action_hint)
                if not merge_enabled and resolved in (
                    "CORRECT", "REFINE", "CORROBORATE",
                ):
                    # Merge disabled: hold updates for human review (legacy).
                    inbox_reason = INBOX_REASON_MERGE_DISABLED
                elif unit.name.lower() in semantic_dups:
                    inbox_reason = INBOX_REASON_SEMANTIC_DUP
                    logger.info(
                        "knowledge_dream: semantic duplicate %r routed to "
                        "_inbox in kb %s",
                        unit.name,
                        kb_id,
                    )
                elif merge_enabled and resolved == "CORRECT":
                    # A correction with no published target would CREATE a
                    # sibling instead of fixing the old body.
                    inbox_reason = INBOX_REASON_NO_TARGET
                elif write_mode == "strict" and unit.confidence < 0.55:
                    inbox_reason = INBOX_REASON_LOW_CONFIDENCE
            # Exact match with merge on should never fall through to CREATE a
            # second published file; hold for review if integrate did not land.
            if exact is not None and not merged and inbox_reason is None:
                inbox_reason = INBOX_REASON_EXACT_UNMERGED
                if not inbox_target:
                    inbox_target = exact.path

            intended_bucket = _normalize_unit_bucket(unit)
            if inbox_reason is not None:
                dest_dir = root / INBOX_BUCKET
                dest_dir.mkdir(parents=True, exist_ok=True)
                source = sources.get(unit.name.lower())
                if source is not None and source.is_file():
                    dest = source
                    retry_count = _read_retry_count(source) + 1
                else:
                    dest = _unique_dest(dest_dir, slug)
                    retry_count = 0
                dest.write_text(
                    _node_markdown(
                        unit,
                        agent_id=agent_id,
                        derived_from=derived_from,
                        status="inbox",
                        bucket=INBOX_BUCKET,
                        title_index=title_index,
                        knowledge_dir=mount_name,
                        inbox_meta=InboxMeta(
                            reason=inbox_reason,
                            intended_bucket=intended_bucket,
                            merge_target_path=inbox_target,
                            retry_count=retry_count,
                        ),
                    ),
                    encoding="utf-8",
                )
            else:
                dest_dir = root / intended_bucket
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = _unique_dest(dest_dir, slug)
                dest.write_text(
                    _node_markdown(
                        unit,
                        agent_id=agent_id,
                        derived_from=derived_from,
                        status="published",
                        bucket=intended_bucket,
                        title_index=title_index,
                        knowledge_dir=mount_name,
                    ),
                    encoding="utf-8",
                )
                _drop_inbox_source(sources, unit.name, keep=dest)
            written.append(dest)
            existing.add(slug.lower())
            existing.add(unit.name.lower())
            existing.add(dest.stem.lower())
        # Rewrite wikilinks on every written file (covers merge-LLM bodies
        # that still emit title-only [[links]]).
        title_index = _wikilink_title_index(kb_id)
        _seed_title_index_from_units(title_index, units)
        for path in written:
            if path.is_file() and path.suffix.lower() == ".md":
                _rewrite_wikilinks_file(path, title_index, mount_name)
    return written


# ---------------------------------------------------------------------------
# Inbox: parse / list / promote / merge / reject / auto-replay
# ---------------------------------------------------------------------------


def _inbox_dir(root: Path) -> Path:
    return root / INBOX_BUCKET


def _rejected_dir(root: Path) -> Path:
    return root / INBOX_BUCKET / "_rejected"


def _resolve_inbox_path(root: Path, stem: str) -> Path | None:
    """Resolve ``stem`` to an ``_inbox/*.md`` file (never ``_rejected``)."""
    raw = str(stem or "").strip().replace("\\", "/")
    if not raw or raw in {".", ".."} or "/" in raw:
        return None
    name = Path(raw).name
    if name != raw:
        return None
    if not name.lower().endswith(".md"):
        name = f"{name}.md"
    if name.startswith("."):
        return None
    inbox = _inbox_dir(root)
    path = inbox / name
    if path.parent != inbox:
        return None
    if not path.is_file():
        return None
    return path


def _safe_published_path(root: Path, rel: str) -> Path | None:
    """Resolve a published-node relative path under ``root``; no traversal."""
    rel_n = (rel or "").replace("\\", "/").lstrip("/")
    if not rel_n:
        return None
    parts = Path(rel_n).parts
    if not parts or ".." in parts:
        return None
    if parts[0] in {INBOX_BUCKET, "_audit", ".locks"}:
        return None
    try:
        root_res = root.resolve()
        path = (root / rel_n).resolve()
        path.relative_to(root_res)
    except (OSError, ValueError):
        return None
    if not path.is_file():
        return None
    return path


def _candidate_from_rel_path(root: Path, rel: str) -> MergeCandidate | None:
    path = _safe_published_path(root, rel)
    if path is None:
        return None
    try:
        rel_n = str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return None
    return MergeCandidate(
        name=_node_display_name(path),
        path=rel_n,
        ratio=1.0,
        is_clear=True,
    )


def _steps_from_section(content: str) -> list[str]:
    steps: list[str] = []
    for line in (content or "").splitlines():
        stripped = line.strip()
        numbered = re.match(r"^\d+\.\s+(.*)$", stripped)
        if numbered:
            text = numbered.group(1).strip()
            if text:
                steps.append(text)
            continue
        if stripped.startswith("- "):
            text = stripped[2:].strip()
            if text:
                steps.append(text)
    return steps


def _link_titles_from_text(text: str) -> list[str]:
    titles: list[str] = []
    seen: set[str] = set()
    for match in _WIKILINK_RE.finditer(text or ""):
        alias = (match.group("alias") or "").lstrip("|").strip()
        target = (match.group("target") or "").strip()
        label = alias or Path(target).stem
        key = label.lower()
        if not key or key in seen:
            continue
        seen.add(key)
        titles.append(label)
    return titles


def inbox_item_from_path(path: Path, *, kb_root_path: Path) -> InboxItemSummary | None:
    """Parse one ``_inbox/*.md`` draft into an API/replay summary."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    fm, body = _parse_frontmatter(text)
    _h1, lead, _sections = _split_body_sections(body)
    name = _unquote_fm(fm.get("name", "")) or _h1 or path.stem
    intended = _unquote_fm(fm.get("intended_bucket", ""))
    if not intended or intended == INBOX_BUCKET:
        intended = "business/wiki"
    reason = _unquote_fm(fm.get("inbox_reason", ""))
    try:
        retry_count = int(_unquote_fm(fm.get("retry_count", "0")))
    except (TypeError, ValueError):
        retry_count = 0
    try:
        confidence = float(_unquote_fm(fm.get("confidence", "0")))
    except (TypeError, ValueError):
        confidence = 0.0
    try:
        rel = str(path.relative_to(kb_root_path)).replace("\\", "/")
    except ValueError:
        rel = f"{INBOX_BUCKET}/{path.name}"
    return InboxItemSummary(
        stem=path.stem,
        name=name,
        intended_bucket=intended,
        inbox_reason=reason,
        merge_target_path=_unquote_fm(fm.get("merge_target_path", "")),
        retry_count=retry_count,
        retryable=(
            reason in INBOX_RETRYABLE_REASONS
            and retry_count < INBOX_MAX_RETRIES
        ),
        confidence=confidence,
        summary=lead.strip(),
        agent_id=_unquote_fm(fm.get("updated_by_agent", "")),
        updated_at=_unquote_fm(fm.get("updated_at", "")),
        action_hint=_unquote_fm(fm.get("action_hint", "")),
        path=rel,
    )


def unit_from_inbox_path(path: Path) -> KnowledgeUnit | None:
    """Rebuild a :class:`KnowledgeUnit` from an inbox draft."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    fm, body = _parse_frontmatter(text)
    _h1, lead, sections = _split_body_sections(body)
    name = _unquote_fm(fm.get("name", "")) or _h1 or path.stem
    intended = _unquote_fm(fm.get("intended_bucket", ""))
    preconditions = ""
    expected = ""
    steps: list[str] = []
    section_links: list[str] = []
    for heading, content in sections:
        kind = _heading_kind(heading)
        if kind == "pre":
            preconditions = content.strip()
        elif kind == "steps":
            steps = _steps_from_section(content)
        elif kind == "expected":
            expected = content.strip()
        elif kind == "links":
            section_links = _link_titles_from_text(content)
    fm_links = _parse_yaml_list_literal(fm.get("links", ""))
    links = list(dict.fromkeys(fm_links or section_links))
    try:
        confidence = float(_unquote_fm(fm.get("confidence", "0.7") or "0.7"))
    except (TypeError, ValueError):
        confidence = 0.7
    return KnowledgeUnit(
        name=name,
        bucket=intended or "business/wiki",
        summary=lead.strip(),
        confidence=confidence,
        signals=_parse_yaml_list_literal(fm.get("signals", "")),
        action_hint=_unquote_fm(fm.get("action_hint", "")) or None,
        preconditions=preconditions,
        steps=steps,
        expected=expected,
        priority=_unquote_fm(fm.get("priority", "")),
        requirement_id=_unquote_fm(fm.get("requirement_id", "")),
        links=links,
        merge_target=_unquote_fm(fm.get("merge_target", "")),
    )


def _derived_from_inbox_path(path: Path) -> list[str]:
    try:
        fm, _body = _parse_frontmatter(path.read_text(encoding="utf-8"))
    except OSError:
        return []
    return _parse_yaml_list_literal(fm.get("derived_from", ""))


def list_inbox_items(kb_id: str) -> list[InboxItemSummary]:
    """List ``_inbox/*.md`` drafts (excludes ``_rejected``), newest first."""
    kb_id = validate_kb_id(kb_id)
    root = kb_root(kb_id)
    inbox = _inbox_dir(root)
    if not inbox.is_dir():
        return []
    items: list[InboxItemSummary] = []
    for path in sorted(inbox.glob("*.md")):
        if not path.is_file() or path.name.startswith("."):
            continue
        item = inbox_item_from_path(path, kb_root_path=root)
        if item is not None:
            items.append(item)
    items.sort(key=lambda item: item.updated_at or "", reverse=True)
    return items


def get_inbox_item(kb_id: str, stem: str) -> InboxItemSummary | None:
    """Return one inbox draft summary, or None if missing."""
    kb_id = validate_kb_id(kb_id)
    root = kb_root(kb_id)
    path = _resolve_inbox_path(root, stem)
    if path is None:
        return None
    return inbox_item_from_path(path, kb_root_path=root)


def promote_inbox_item(
    kb_id: str,
    stem: str,
    *,
    agent_id: str,
    knowledge_dir: str = DEFAULT_KNOWLEDGE_DIR,
) -> Path:
    """Publish an inbox draft into its ``intended_bucket`` as a new node.

    Raises :class:`InboxActionError` on missing draft (404) or when a
    published node with the same title already exists (409 — merge instead).
    """
    kb_id = validate_kb_id(kb_id)
    mount_name = (knowledge_dir or DEFAULT_KNOWLEDGE_DIR).strip() or DEFAULT_KNOWLEDGE_DIR
    with knowledge_write_lock(kb_id):
        root = kb_root(kb_id)
        path = _resolve_inbox_path(root, stem)
        if path is None:
            raise InboxActionError(
                f"Inbox item {stem!r} not found in kb {kb_id!r}",
                status_code=404,
            )
        unit = unit_from_inbox_path(path)
        if unit is None:
            raise InboxActionError(
                f"Inbox item {stem!r} is unreadable",
                status_code=400,
            )
        unit.bucket = _normalize_unit_bucket(unit)
        exact = _find_exact_published_node(
            kb_id, unit.name, preferred_bucket=unit.bucket,
        )
        if exact is not None:
            raise InboxActionError(
                f"Published node {unit.name!r} already exists; merge instead",
                status_code=409,
                detail={
                    "message": (
                        f"Published node {unit.name!r} already exists; "
                        "merge instead"
                    ),
                    "existing_path": exact.path,
                },
            )
        dest_dir = root / unit.bucket
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{_slugify(unit.name)}.md"
        if dest.exists():
            raise InboxActionError(
                f"Destination {dest.name} already exists; merge instead",
                status_code=409,
                detail={
                    "message": (
                        f"Destination {dest.name} already exists; merge instead"
                    ),
                    "existing_path": str(dest.relative_to(root)).replace("\\", "/"),
                },
            )
        derived = _derived_from_inbox_path(path) or [f"{INBOX_BUCKET}/{path.name}"]
        title_index = _wikilink_title_index(kb_id)
        dest.write_text(
            _node_markdown(
                unit,
                agent_id=agent_id,
                derived_from=derived,
                status="published",
                bucket=unit.bucket,
                title_index=title_index,
                knowledge_dir=mount_name,
            ),
            encoding="utf-8",
        )
        _rewrite_wikilinks_file(dest, title_index, mount_name)
        try:
            path.unlink()
        except OSError:
            logger.debug("promote_inbox_item: failed to drop %s", path, exc_info=True)
        return dest


def merge_inbox_item(
    kb_id: str,
    stem: str,
    *,
    agent_id: str,
    target_path: str = "",
    mode: str = "REFINE",
    merge_max_updates: int = 5,
    knowledge_dir: str = DEFAULT_KNOWLEDGE_DIR,
) -> Path:
    """Structurally merge an inbox draft into a published node.

    ``target_path`` overrides the draft's ``merge_target_path``. Mode is
    ``REFINE`` (default, ``MERGE`` alias) or ``CORRECT``. Raises
    :class:`InboxActionError` on missing draft/target (404) or ``at_cap`` (409).
    """
    kb_id = validate_kb_id(kb_id)
    normalized = (mode or "REFINE").strip().upper()
    if normalized == "MERGE":
        normalized = "REFINE"
    if normalized not in ("REFINE", "CORRECT"):
        raise InboxActionError(
            f"Unsupported merge mode {mode!r}; use REFINE or CORRECT",
            status_code=400,
        )
    mount_name = (knowledge_dir or DEFAULT_KNOWLEDGE_DIR).strip() or DEFAULT_KNOWLEDGE_DIR
    with knowledge_write_lock(kb_id):
        root = kb_root(kb_id)
        path = _resolve_inbox_path(root, stem)
        if path is None:
            raise InboxActionError(
                f"Inbox item {stem!r} not found in kb {kb_id!r}",
                status_code=404,
            )
        unit = unit_from_inbox_path(path)
        if unit is None:
            raise InboxActionError(
                f"Inbox item {stem!r} is unreadable",
                status_code=400,
            )
        unit.bucket = _normalize_unit_bucket(unit)
        item = inbox_item_from_path(path, kb_root_path=root)
        rel = (target_path or "").strip() or (
            item.merge_target_path if item is not None else ""
        )
        dest = _safe_published_path(root, rel) if rel else None
        if dest is None and unit.merge_target:
            hinted = _find_exact_published_node(
                kb_id, unit.merge_target, preferred_bucket=unit.bucket,
            )
            if hinted is not None:
                dest = _safe_published_path(root, hinted.path)
        if dest is None:
            hinted = _find_exact_published_node(
                kb_id, unit.name, preferred_bucket=unit.bucket,
            )
            if hinted is not None:
                dest = _safe_published_path(root, hinted.path)
        if dest is None:
            raise InboxActionError(
                f"No merge target for inbox item {stem!r}",
                status_code=400,
            )
        try:
            text = dest.read_text(encoding="utf-8")
        except OSError as exc:
            raise InboxActionError(
                f"Merge target unreadable for inbox item {stem!r}",
                status_code=404,
            ) from exc
        fm, old_body = _parse_frontmatter(text)
        title_index = _wikilink_title_index(kb_id)
        formatted_links = [
            format_wikilink(*resolve_wikilink_target(
                link,
                title_index=title_index,
                knowledge_dir=mount_name,
            ))
            for link in unit.links
        ]
        merged_body = structural_merge_body(
            old_body, unit, formatted_links=formatted_links or None,
        )
        merged_body = _rewrite_wikilinks_in_text(
            merged_body,
            title_index=title_index,
            knowledge_dir=mount_name,
        )
        payload = MergePayload(
            target_path=dest,
            expected_updated_at=_unquote_fm(fm.get("updated_at", "")),
            merged_body=merged_body,
            llm_ok=True,
        )
        derived = _derived_from_inbox_path(path) or [f"{INBOX_BUCKET}/{path.name}"]
        outcome = _merge_node(
            dest,
            unit,
            agent_id=agent_id,
            derived_from=derived,
            mode=normalized,
            max_updates=merge_max_updates,
            payload=payload,
            kb_root_path=root,
        )
        if not outcome.done:
            if outcome.reason == "at_cap":
                raise InboxActionError(
                    f"Merge target is at the update cap for {stem!r}",
                    status_code=409,
                    detail={
                        "message": (
                            f"Merge target is at the update cap for {stem!r}"
                        ),
                        "reason": "at_cap",
                    },
                )
            raise InboxActionError(
                f"Merge failed for {stem!r}: {outcome.reason}",
                status_code=409,
                detail={"message": str(outcome.reason), "reason": outcome.reason},
            )
        _rewrite_wikilinks_file(dest, title_index, mount_name)
        try:
            path.unlink()
        except OSError:
            logger.debug("merge_inbox_item: failed to drop %s", path, exc_info=True)
        return dest


def reject_inbox_item(kb_id: str, stem: str) -> Path:
    """Move an inbox draft to ``_inbox/_rejected/`` (not indexed)."""
    kb_id = validate_kb_id(kb_id)
    with knowledge_write_lock(kb_id):
        root = kb_root(kb_id)
        path = _resolve_inbox_path(root, stem)
        if path is None:
            raise InboxActionError(
                f"Inbox item {stem!r} not found in kb {kb_id!r}",
                status_code=404,
            )
        dest_dir = _rejected_dir(root)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = _unique_dest(dest_dir, path.stem)
        path.replace(dest)
        return dest


async def _precompute_merge_payloads(
    *,
    kb_id: str,
    units: list[KnowledgeUnit],
    merge_candidates: dict[str, MergeCandidate],
    language: str,
    llm_call,
    knowledge_dir: str,
) -> dict[str, MergePayload]:
    """LLM-merge bodies grouped by target, produced outside the write lock."""
    merge_payloads: dict[str, MergePayload] = {}
    if not merge_candidates:
        return merge_payloads
    root = kb_root(kb_id)
    title_index = _wikilink_title_index(kb_id)
    _seed_title_index_from_units(title_index, units)
    groups: dict[str, list[tuple[KnowledgeUnit, str]]] = {}
    target_meta: dict[str, tuple[Path, str, str]] = {}
    for unit in units:
        cand = merge_candidates.get(unit.name.lower())
        if cand is None or not cand.is_clear or not cand.path:
            continue
        if _domain_of_bucket(unit.bucket) != _domain_of_bucket(cand.path):
            continue
        if not _has_update_content(unit):
            continue
        target_path = root / cand.path
        try:
            text = target_path.read_text(encoding="utf-8")
        except OSError:
            logger.debug(
                "knowledge_dream: merge target unreadable %s",
                target_path,
            )
            continue
        fm, body = _parse_frontmatter(text)
        exact_hit = _find_exact_published_node(
            kb_id, unit.name, preferred_bucket=unit.bucket,
        ) is not None
        action = _resolve_integrate_action(
            unit,
            has_clear_candidate=True,
            exact_title_match=exact_hit,
            old_body=body,
            old_description=(
                fm.get("description", "").strip().strip('"').strip("'")
            ),
        )
        if action in ("CREATE", "CORROBORATE"):
            continue
        key = str(target_path)
        groups.setdefault(key, []).append((unit, action))
        if key not in target_meta:
            target_meta[key] = (
                target_path,
                fm.get("updated_at", "").strip().strip('"'),
                body,
            )

    for key, group in groups.items():
        target_path, expected_updated_at, body = target_meta[key]
        primary, _primary_action = group[0]
        extra = [item[0] for item in group[1:]]
        mode = (
            "CORRECT"
            if any(action == "CORRECT" for _unit, action in group)
            else "REFINE"
        )
        all_links: list[str] = []
        seen_links: set[str] = set()
        for grouped_unit, _action in group:
            for link in grouped_unit.links:
                low = link.strip().lower()
                if not low or low in seen_links:
                    continue
                seen_links.add(low)
                all_links.append(link)
        formatted_links = [
            format_wikilink(*resolve_wikilink_target(
                link,
                title_index=title_index,
                knowledge_dir=knowledge_dir,
            ))
            for link in all_links
        ]
        try:
            merged_raw = await llm_call(
                build_merge_prompt(
                    language=language,
                    mode=mode,
                    old_body=body,
                    unit=primary,
                    formatted_links=formatted_links or None,
                    extra_units=extra or None,
                ),
            )
        except Exception:
            logger.debug(
                "knowledge_dream: merge LLM failed for %r",
                primary.name,
                exc_info=True,
            )
            continue
        merged_body = _strip_merge_output(merged_raw)
        if not merged_body:
            logger.info(
                "knowledge_dream: empty merge body for %r → inbox",
                primary.name,
            )
            continue
        merged_body = _rewrite_wikilinks_in_text(
            merged_body,
            title_index=title_index,
            knowledge_dir=knowledge_dir,
        )
        integrity_ok = True
        integrity_skipped = False
        try:
            verdict_raw = await llm_call(
                build_merge_integrity_prompt(
                    language=language,
                    mode=mode,
                    old_body=body,
                    new_body=merged_body,
                    unit=primary,
                    formatted_links=formatted_links or None,
                    extra_units=extra or None,
                ),
            )
            integrity_ok, parsed_ok = _parse_integrity_verdict(verdict_raw)
            if not parsed_ok:
                integrity_ok = False
                integrity_skipped = True
                logger.warning(
                    "knowledge_dream: merge integrity unparseable for %r; "
                    "fail-closed",
                    primary.name,
                )
            elif not integrity_ok:
                logger.info(
                    "knowledge_dream: merge integrity rejected %r",
                    primary.name,
                )
        except Exception:
            integrity_ok = False
            integrity_skipped = True
            logger.warning(
                "knowledge_dream: merge integrity LLM failed for %r; "
                "fail-closed",
                primary.name,
            )
        payload = MergePayload(
            target_path=target_path,
            expected_updated_at=expected_updated_at,
            merged_body=merged_body,
            llm_ok=True,
            integrity_ok=integrity_ok,
            integrity_skipped=integrity_skipped,
        )
        for grouped_unit, _action in group:
            merge_payloads[grouped_unit.name.lower()] = payload
    return merge_payloads


async def replay_retryable_inbox(
    *,
    kb_id: str,
    agent_id: str,
    language: str,
    llm_call,
    merge_search: (
        Callable[[str, str], Awaitable[MergeCandidate | None]] | None
    ) = None,
    merge_enabled: bool = True,
    merge_max_updates: int = 5,
    write_mode: str = "open",
    knowledge_dir: str = DEFAULT_KNOWLEDGE_DIR,
    audit_sink: list[AuditReportSummary] | None = None,
    only_stems: set[str] | None = None,
) -> list[Path]:
    """Re-integrate retryable ``_inbox`` drafts (scheme B). Does not re-extract.

    Only drafts whose ``inbox_reason`` is retryable and ``retry_count`` is
    below :data:`INBOX_MAX_RETRIES` are considered. ``only_stems`` limits
    replay to drafts that existed *before* the current dream's integrate
    so a same-run missing payload is not immediately retried.
    """
    kb_id = validate_kb_id(kb_id)
    items = [
        item for item in list_inbox_items(kb_id)
        if item.retryable and (only_stems is None or item.stem in only_stems)
    ]
    if not items:
        return []
    root = kb_root(kb_id)
    units: list[KnowledgeUnit] = []
    sources: dict[str, Path] = {}
    merge_candidates: dict[str, MergeCandidate] = {}
    derived: list[str] = []
    for item in items:
        path = _resolve_inbox_path(root, item.stem)
        if path is None:
            continue
        unit = unit_from_inbox_path(path)
        if unit is None:
            continue
        unit.bucket = _normalize_unit_bucket(unit)
        units.append(unit)
        sources[unit.name.lower()] = path
        derived.extend(_derived_from_inbox_path(path))
        key = unit.name.lower()
        if item.merge_target_path:
            cand = _candidate_from_rel_path(root, item.merge_target_path)
            if cand is not None:
                merge_candidates[key] = cand
        if key not in merge_candidates and merge_search is not None:
            try:
                cand = await merge_search(unit.name, unit.summary)
            except Exception:
                logger.debug(
                    "knowledge_dream: inbox replay merge_search failed for %r",
                    unit.name,
                    exc_info=True,
                )
                cand = None
            if cand is not None:
                merge_candidates[key] = cand
        if key not in merge_candidates and merge_enabled:
            exact = _find_exact_published_node(
                kb_id, unit.name, preferred_bucket=unit.bucket,
            )
            if exact is not None:
                merge_candidates[key] = exact
            elif unit.merge_target:
                hinted = _find_exact_published_node(
                    kb_id, unit.merge_target, preferred_bucket=unit.bucket,
                )
                if hinted is not None:
                    merge_candidates[key] = hinted
    if not units:
        return []
    payloads: dict[str, MergePayload] = {}
    if merge_enabled:
        payloads = await _precompute_merge_payloads(
            kb_id=kb_id,
            units=units,
            merge_candidates=merge_candidates,
            language=language,
            llm_call=llm_call,
            knowledge_dir=knowledge_dir,
        )
    logger.info(
        "knowledge_dream: replaying %d retryable inbox item(s) in kb %s",
        len(units),
        kb_id,
    )
    return integrate_units(
        kb_id=kb_id,
        agent_id=agent_id,
        units=units,
        derived_from=list(dict.fromkeys(derived)),
        write_mode=write_mode,
        inbox_enabled=True,
        merge_candidates=merge_candidates,
        merge_enabled=merge_enabled,
        merge_max_updates=merge_max_updates,
        merge_payloads=payloads,
        audit_sink=audit_sink,
        knowledge_dir=knowledge_dir,
        inbox_sources=sources,
    )


async def run_knowledge_dream(
    *,
    agent_id: str,
    workspace_dir: str | Path,
    kb_id: str,
    daily_dir_name: str,
    metadata_dir: str,
    language: str,
    domain: str,
    scan_days: int,
    max_units: int,
    write_mode: str,
    inbox_enabled: bool,
    llm_call,
    dedup_search: Callable[[str, str], Awaitable[bool]] | None = None,
    merge_search: (
        Callable[[str, str], Awaitable[MergeCandidate | None]] | None
    ) = None,
    catalog_search: (
        Callable[[str], Awaitable[list[tuple[str, str]]]] | None
    ) = None,
    merge_enabled: bool = False,
    merge_max_updates: int = 5,
    knowledge_dir: str = DEFAULT_KNOWLEDGE_DIR,
) -> dict[str, Any]:
    """Diff daily notes → extract → locked integrate → catalog checkpoint.

    ``llm_call`` is an async callable ``(prompt: str) -> str``.

    ``dedup_search`` is an optional async callable
    ``(name: str, summary: str) -> bool`` returning True when a published
    KB node is semantically close enough to the unit to be considered a
    duplicate. When provided, units flagged as semantic duplicates are
    routed to ``_inbox`` (see ``integrate_units``). The threshold and KB
    path filtering live in the caller so this module stays ReMe-agnostic.

    ``merge_search`` is an optional async callable
    ``(name: str, summary: str) -> MergeCandidate | None`` returning a
    clear merge target when one exists. When ``merge_enabled`` is True the
    candidate drives auto-merge; when False it is ignored. ``dedup_search``
    and ``merge_search`` are typically the same probe returning different
    result shapes — keep them separate so the legacy bool probe stays
    unchanged when merge is off.

    ``catalog_search`` is an optional async callable ``(query: str) ->
    list[tuple[name, bucket]]`` used to recall published nodes related to
    today's notes (typically ReMe ``node_search``). Hits are listed first
    in the extract prompt's existing-node catalog; title overlap against
    the daily corpus fills the rest. When omitted, ranking is lexical
    only.

    When ``inbox_enabled`` is True, retryable ``_inbox`` drafts from
    *previous* runs are replayed after integrate (and even when there is
    no changed daily). Human promote/merge/reject does not depend on this
    flag.
    """
    workspace = Path(workspace_dir)
    catalog = load_catalog(workspace, metadata_dir)
    daily_dir = workspace / daily_dir_name
    changed = _recent_daily_files(
        daily_dir,
        scan_days=scan_days,
        catalog=catalog,
    )
    if not changed:
        if inbox_enabled:
            audit_sink: list[AuditReportSummary] = []
            try:
                replayed = await replay_retryable_inbox(
                    kb_id=kb_id,
                    agent_id=agent_id,
                    language=language,
                    llm_call=llm_call,
                    merge_search=merge_search,
                    merge_enabled=merge_enabled,
                    merge_max_updates=merge_max_updates,
                    write_mode=write_mode,
                    knowledge_dir=knowledge_dir,
                    audit_sink=audit_sink,
                )
            except KnowledgeLockTimeout:
                logger.warning(
                    "knowledge_dream inbox replay lock timeout for kb=%s",
                    kb_id,
                )
                replayed = []
            if replayed:
                return {
                    "skipped": False,
                    "written": [str(p) for p in replayed],
                    "units": 0,
                    "audit_reports": [r.model_dump() for r in audit_sink],
                    "needs_review_count": sum(
                        1 for r in audit_sink if r.needs_review
                    ),
                }
        return {"skipped": True, "reason": "no_changed_daily", "written": []}

    # Capture mtime *at read time* for each file. If a daily note is appended
    # during the LLM extract below, checkpointing with the post-extract mtime
    # would mark the new (unprocessed) content as already processed — a
    # completeness leak. Using the mtime snapshot here guarantees we only
    # mark "processed up to this mtime", so a later change re-triggers dream.
    parts: list[str] = []
    derived: list[str] = []
    mtimes: dict[str, float] = {}
    for path in changed:
        try:
            mtimes[path.name] = path.stat().st_mtime
            parts.append(f"## {path.name}\n{path.read_text(encoding='utf-8')}")
            derived.append(f"{daily_dir_name}/{path.name}")
        except OSError:
            mtimes.pop(path.name, None)
            continue
    if not parts:
        return {"skipped": True, "reason": "unreadable_daily", "written": []}

    daily_corpus = "\n\n".join(parts)
    recalled: list[tuple[str, str]] = []
    if catalog_search is not None:
        seen_keys: set[str] = set()
        for chunk in _catalog_query_chunks(daily_corpus):
            try:
                hits = await catalog_search(chunk)
            except Exception:
                logger.debug(
                    "knowledge_dream: catalog_search failed",
                    exc_info=True,
                )
                continue
            for name, bucket in hits or []:
                key = (name or "").strip().lower()
                if not key or key in seen_keys:
                    continue
                seen_keys.add(key)
                recalled.append((name.strip(), (bucket or "").strip()))

    existing_nodes = _published_node_catalog(
        kb_id, query=daily_corpus, recalled=recalled,
    )
    prompt = build_extract_prompt(
        language=language,
        domain=domain,
        daily_corpus=daily_corpus,
        max_units=max_units,
        existing_nodes=existing_nodes,
    )
    raw = await llm_call(prompt)
    units, parse_ok = _try_parse_units(
        raw, max_units=max_units, domain=domain,
    )
    coverage_ok = True
    try:
        coverage_raw = await llm_call(
            build_coverage_extract_prompt(
                language=language,
                daily_corpus=daily_corpus,
                max_units=max_units,
                already_extracted=_format_extracted_units(units),
                existing_nodes=existing_nodes,
            ),
        )
        extra, extra_ok = _try_parse_units(
            coverage_raw, max_units=max_units, domain=domain,
        )
        if extra_ok:
            if extra:
                units = _dedupe_units(list(units) + extra)
                parse_ok = True
        else:
            coverage_ok = False
            logger.warning(
                "knowledge_dream: coverage parse failed agent=%s kb=%s",
                agent_id,
                kb_id,
            )
    except Exception:
        coverage_ok = False
        logger.warning(
            "knowledge_dream: coverage extract failed agent=%s kb=%s",
            agent_id,
            kb_id,
            exc_info=True,
        )

    if not parse_ok and not units:
        logger.warning(
            "knowledge_dream: extract parse failed agent=%s kb=%s; "
            "not checkpointing catalog",
            agent_id,
            kb_id,
        )
        audit_sink: list[AuditReportSummary] = []
        written: list[Path] = []
        if inbox_enabled:
            try:
                written = await replay_retryable_inbox(
                    kb_id=kb_id,
                    agent_id=agent_id,
                    language=language,
                    llm_call=llm_call,
                    merge_search=merge_search,
                    merge_enabled=merge_enabled,
                    merge_max_updates=merge_max_updates,
                    write_mode=write_mode,
                    knowledge_dir=knowledge_dir,
                    audit_sink=audit_sink,
                )
            except KnowledgeLockTimeout:
                logger.warning(
                    "knowledge_dream inbox replay lock timeout for kb=%s",
                    kb_id,
                )
        return {
            "skipped": False,
            "reason": "extract_parse_failed",
            "written": [str(p) for p in written],
            "units": 0,
            "audit_reports": [r.model_dump() for r in audit_sink],
            "needs_review_count": sum(
                1 for r in audit_sink if r.needs_review
            ),
        }

    if not units:
        # Checkpoint empty diffs only when coverage also succeeded;
        # a failed coverage pass must not freeze the daily as "done".
        if coverage_ok:
            for name, mtime in mtimes.items():
                catalog.setdefault("processed", {})[name] = {
                    "mtime": mtime,
                    "units": 0,
                    "written": 0,
                }
            save_catalog(workspace, metadata_dir, catalog)
        else:
            logger.warning(
                "knowledge_dream: coverage incomplete agent=%s kb=%s; "
                "not checkpointing catalog",
                agent_id,
                kb_id,
            )
        audit_sink: list[AuditReportSummary] = []
        written: list[Path] = []
        if inbox_enabled:
            try:
                written = await replay_retryable_inbox(
                    kb_id=kb_id,
                    agent_id=agent_id,
                    language=language,
                    llm_call=llm_call,
                    merge_search=merge_search,
                    merge_enabled=merge_enabled,
                    merge_max_updates=merge_max_updates,
                    write_mode=write_mode,
                    knowledge_dir=knowledge_dir,
                    audit_sink=audit_sink,
                )
            except KnowledgeLockTimeout:
                logger.warning(
                    "knowledge_dream inbox replay lock timeout for kb=%s",
                    kb_id,
                )
        result = {
            "skipped": False,
            "written": [str(p) for p in written],
            "units": 0,
            "audit_reports": [r.model_dump() for r in audit_sink],
            "needs_review_count": sum(
                1 for r in audit_sink if r.needs_review
            ),
        }
        if not coverage_ok:
            result["reason"] = "coverage_incomplete"
        return result

    semantic_dup_names: set[str] = set()
    if dedup_search is not None:
        for unit in units:
            try:
                if await dedup_search(unit.name, unit.summary):
                    semantic_dup_names.add(unit.name.lower())
            except Exception:
                logger.debug(
                    "knowledge_dream: dedup_search failed for %r",
                    unit.name,
                    exc_info=True,
                )

    merge_candidates: dict[str, MergeCandidate] = {}
    # Always probe when merge_search is provided — even with merge_enabled
    # False — so related_names can enrich wikilinks (synapse weaving).
    if merge_search is not None:
        for unit in units:
            try:
                cand = await merge_search(unit.name, unit.summary)
            except Exception:
                logger.debug(
                    "knowledge_dream: merge_search failed for %r",
                    unit.name,
                    exc_info=True,
                )
                continue
            if cand is not None:
                merge_candidates[unit.name.lower()] = cand

    # Synapse: weave related (not same-abstraction) titles into unit.links.
    for unit in units:
        cand = merge_candidates.get(unit.name.lower())
        if cand is not None:
            _enrich_unit_links(unit, cand.related_names)

    # Exact title/slug hits are the strongest same-abstraction signal —
    # inject them as clear candidates so payload pre-compute and integrate
    # can CORROBORATE/REFINE instead of silently skipping. Exact always
    # overrides a fuzzy clear candidate (wrong near-neighbor risk).
    if merge_enabled:
        for unit in units:
            key = unit.name.lower()
            prior = merge_candidates.get(key)
            exact = _find_exact_published_node(
                kb_id, unit.name, preferred_bucket=unit.bucket,
            )
            if exact is None:
                continue
            if prior is not None and prior.related_names:
                exact.related_names = list(
                    dict.fromkeys(
                        list(exact.related_names) + list(prior.related_names),
                    ),
                )
                _enrich_unit_links(unit, exact.related_names)
            merge_candidates[key] = exact

        # LLM merge_target is the next-strongest signal after exact self-title.
        # Resolve via aliases (stem / H1 / frontmatter) so it participates in
        # payload pre-compute instead of only being seen under the write lock
        # (where a missing payload would dump the unit into _inbox).
        for unit in units:
            if not unit.merge_target:
                continue
            key = unit.name.lower()
            prior = merge_candidates.get(key)
            if prior is not None and prior.is_clear and prior.path:
                # Exact self-title or a clear search hit already won.
                if _find_exact_published_node(
                    kb_id, unit.name, preferred_bucket=unit.bucket,
                ) is not None:
                    continue
            hinted = _find_exact_published_node(
                kb_id, unit.merge_target, preferred_bucket=unit.bucket,
            )
            if hinted is None:
                continue
            if prior is not None and prior.related_names:
                hinted.related_names = list(
                    dict.fromkeys(
                        list(hinted.related_names) + list(prior.related_names),
                    ),
                )
                _enrich_unit_links(unit, hinted.related_names)
            merge_candidates[key] = hinted

        # Lexical fallback: unique same-domain published title mentioned in
        # the unit summary (or high name/description overlap) when search
        # did not return a clear target. Ambiguous pairs are skipped so we
        # CREATE rather than inbox.
        for unit in units:
            key = unit.name.lower()
            prior = merge_candidates.get(key)
            if prior is not None and prior.path:
                continue
            lexical = _lexical_merge_candidate(kb_id, unit)
            if lexical is None:
                continue
            merge_candidates[key] = lexical
            logger.info(
                "knowledge_dream: lexical merge target %r → %s for %r",
                lexical.name,
                lexical.path,
                unit.name,
            )

    # When merge is enabled and a clear same-abstraction target exists,
    # drop the semantic-dup inbox flag so CORROBORATE/REFINE can land
    # instead of stacking near-duplicates in _inbox.
    if merge_enabled and semantic_dup_names:
        for unit in units:
            cand = merge_candidates.get(unit.name.lower())
            if cand is None or not cand.is_clear:
                continue
            if _domain_of_bucket(unit.bucket) != _domain_of_bucket(cand.path):
                continue
            exact_hit = _find_exact_published_node(
                kb_id, unit.name, preferred_bucket=unit.bucket,
            ) is not None
            if _resolve_integrate_action(
                unit,
                has_clear_candidate=True,
                exact_title_match=exact_hit,
            ) == "CREATE":
                continue
            semantic_dup_names.discard(unit.name.lower())

    # Snapshot retryable drafts *before* integrate so same-run inbox
    # writes are not immediately replayed (next dream picks them up).
    prior_replay_stems: set[str] | None = None
    if inbox_enabled:
        prior_replay_stems = {
            item.stem for item in list_inbox_items(kb_id) if item.retryable
        }

    # --- pre-compute LLM merge bodies (outside the write lock) ---
    # Only REFINE / CORRECT need a body rewrite. CORROBORATE is frontmatter-
    # only and skips the LLM call. Units that share a target are grouped
    # into one LLM call so a same-batch second unit does not stale the
    # first payload. A staleness guard (expected_updated_at) still refuses
    # a concurrent writer between pre-read and lock.
    merge_payloads: dict[str, MergePayload] = {}
    if merge_enabled and merge_candidates:
        merge_payloads = await _precompute_merge_payloads(
            kb_id=kb_id,
            units=units,
            merge_candidates=merge_candidates,
            language=language,
            llm_call=llm_call,
            knowledge_dir=knowledge_dir,
        )

    audit_sink: list[AuditReportSummary] = []
    try:
        written = integrate_units(
            kb_id=kb_id,
            agent_id=agent_id,
            units=units,
            derived_from=derived,
            write_mode=write_mode,
            inbox_enabled=inbox_enabled,
            semantic_dup_names=semantic_dup_names,
            merge_candidates=merge_candidates,
            merge_enabled=merge_enabled,
            merge_max_updates=merge_max_updates,
            merge_payloads=merge_payloads,
            audit_sink=audit_sink,
            knowledge_dir=knowledge_dir,
        )
    except KnowledgeLockTimeout:
        logger.warning(
            "knowledge_dream lock timeout for kb=%s agent=%s; "
            "not checkpointing catalog",
            kb_id,
            agent_id,
        )
        return {
            "skipped": True,
            "reason": "lock_timeout",
            "written": [],
            "audit_reports": [],
            "needs_review_count": 0,
        }

    if inbox_enabled:
        try:
            replayed = await replay_retryable_inbox(
                kb_id=kb_id,
                agent_id=agent_id,
                language=language,
                llm_call=llm_call,
                merge_search=merge_search,
                merge_enabled=merge_enabled,
                merge_max_updates=merge_max_updates,
                write_mode=write_mode,
                knowledge_dir=knowledge_dir,
                audit_sink=audit_sink,
                only_stems=prior_replay_stems,
            )
            written.extend(replayed)
        except KnowledgeLockTimeout:
            logger.warning(
                "knowledge_dream inbox replay lock timeout for kb=%s; "
                "daily integrate already checkpointed",
                kb_id,
            )

    if coverage_ok:
        for name, mtime in mtimes.items():
            catalog.setdefault("processed", {})[name] = {
                "mtime": mtime,
                "units": len(units),
                "written": len(written),
            }
        save_catalog(workspace, metadata_dir, catalog)
    else:
        logger.warning(
            "knowledge_dream: coverage incomplete agent=%s kb=%s; "
            "not checkpointing catalog",
            agent_id,
            kb_id,
        )
    needs_review_count = sum(1 for r in audit_sink if r.needs_review)
    result = {
        "skipped": False,
        "written": [str(p) for p in written],
        "units": len(units),
        "audit_reports": [r.model_dump() for r in audit_sink],
        "needs_review_count": needs_review_count,
    }
    if not coverage_ok:
        result["reason"] = "coverage_incomplete"
    return result


# ---------------------------------------------------------------------------
# Audit report read/ack (for the knowledge-bases API)
# ---------------------------------------------------------------------------


def _audit_index_path(kb_root_path: Path) -> Path:
    return _audit_dir(kb_root_path) / "index.jsonl"


def list_audit_reports(
    kb_id: str,
    *,
    needs_review_only: bool = False,
) -> list[AuditReportSummary]:
    """List merge audit reports for a KB, newest first.

    Reads ``_audit/index.jsonl``. Malformed lines are skipped. When
    ``needs_review_only`` is True only reports still needing review are
    returned (``needs_review and not reviewed``).
    """
    kb_id = validate_kb_id(kb_id)
    index_path = _audit_index_path(kb_root(kb_id))
    if not index_path.is_file():
        return []
    out: list[AuditReportSummary] = []
    try:
        raw = index_path.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            summary = AuditReportSummary(**data)
        except Exception:
            continue
        if needs_review_only and not (summary.needs_review and not summary.reviewed):
            continue
        out.append(summary)
    out.reverse()  # newest first (index is append-ordered)
    return out


def read_audit_report(kb_id: str, report_id: str) -> str | None:
    """Return the full markdown audit report body, or None if missing."""
    kb_id = validate_kb_id(kb_id)
    # report_id is the file stem; resolve under _audit/.
    safe = _slugify(report_id)
    candidate = _audit_dir(kb_root(kb_id)) / f"{safe}.md"
    if candidate.is_file():
        try:
            return candidate.read_text(encoding="utf-8")
        except OSError:
            return None
    # Fall back to exact stem match (report_id already includes date/slug/n).
    candidate = _audit_dir(kb_root(kb_id)) / f"{report_id}.md"
    if candidate.is_file():
        try:
            return candidate.read_text(encoding="utf-8")
        except OSError:
            return None
    return None


def ack_audit_report(kb_id: str, report_id: str) -> AuditReportSummary | None:
    """Mark an audit report as reviewed; returns the updated summary or None."""
    kb_id = validate_kb_id(kb_id)
    index_path = _audit_index_path(kb_root(kb_id))
    if not index_path.is_file():
        return None
    try:
        raw = index_path.read_text(encoding="utf-8")
    except OSError:
        return None
    lines = raw.splitlines()
    updated: list[str] = []
    found: AuditReportSummary | None = None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            updated.append(line)
            continue
        if data.get("report_id") == report_id:
            data["reviewed"] = True
            found = AuditReportSummary(**data)
        updated.append(json.dumps(data, ensure_ascii=False))
    if found is None:
        return None
    index_path.write_text("\n".join(updated) + "\n", encoding="utf-8")
    return found
