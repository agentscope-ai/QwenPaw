# -*- coding: utf-8 -*-
"""Filesystem layout for shared knowledge bases under WORKING_DIR."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ...constant import WORKING_DIR
from ...utils.io_utils import write_json_atomic

logger = logging.getLogger(__name__)

# Domain-namespaced buckets. Business knowledge (product/dev/qa jointly
# maintained) lives under ``business/``; test artifacts (QA-owned) live
# under ``test/``. ``_inbox`` stays at the KB root so ``_path_scope_tag``
# keeps recognizing it across both domains.
BUSINESS_BUCKETS = ("business/wiki", "business/procedure", "business/personal")
TEST_BUCKETS = (
    "test/test_design",
    "test/test_cases",
    "test/test_data",
    "test/defects",
)
INBOX_BUCKET = "_inbox"
KB_BUCKETS = (*BUSINESS_BUCKETS, *TEST_BUCKETS, INBOX_BUCKET)

# Published buckets (exclude ``_inbox``). Used by dedup scans and
# validation. Kept as a derived tuple so adding a bucket only touches the
# domain constants above.
PUBLISHED_BUCKETS = tuple(b for b in KB_BUCKETS if b != INBOX_BUCKET)

# Pre-domain flat buckets. New writes no longer land here, but old nodes
# must stay watchable / searchable / dedup-able.
LEGACY_FLAT_BUCKETS = ("personal", "procedure", "wiki")

# Domain roots covering namespaced published buckets, used as ReMe
# search_filter prefixes (excludes ``_inbox``, ``_audit``, ``KB.md``).
PUBLISHED_DOMAIN_PREFIXES = ("business", "test")

_KB_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")


class KnowledgeBaseMeta(BaseModel):
    """Metadata persisted as KB.md frontmatter + body."""

    id: str
    name: str = ""
    domain: str = "business"
    version: int = 1
    created_at: str = ""
    updated_at: str = ""
    description: str = ""


def _join_bucket(root: Path, bucket: str) -> Path:
    """Join a possibly namespaced bucket (``business/wiki``) onto ``root``."""
    parts = [p for p in str(bucket).replace("\\", "/").split("/") if p]
    return root.joinpath(*parts)


def knowledge_watch_dirs(workspace_dir: str | Path, knowledge_dir: str) -> list[str]:
    """Absolute published-bucket paths for ReMe watch/reindex.

    Watches only formal knowledge directories so ``_inbox``, ``_audit``,
    and ``KB.md`` are never indexed. Includes legacy flat buckets for
    knowledge bases created before the domain-namespaced layout.
    """
    root = Path(workspace_dir).expanduser() / (knowledge_dir or "knowledge")
    buckets = list(PUBLISHED_BUCKETS)
    buckets.extend(b for b in LEGACY_FLAT_BUCKETS if b not in buckets)
    return [str(_join_bucket(root, b)) for b in buckets]


def knowledge_published_path_prefixes(knowledge_dir: str) -> list[str]:
    """Workspace-relative path prefixes covering published KB nodes.

    Used as ReMe ``search_filter.prefixes`` / ``node_search`` prefixes so
    retrieval never considers ``_inbox``, ``_audit``, or ``KB.md``.
    """
    return knowledge_scope_path_prefixes(knowledge_dir, bucket="")


def knowledge_scope_path_prefixes(
    knowledge_dir: str,
    bucket: str = "",
) -> list[str]:
    """Published-KB prefixes, optionally narrowed to a domain or bucket.

    ``bucket`` may be:
    - empty / ``all`` / ``*``: all published domains plus legacy flat buckets
    - ``business`` / ``test``: that domain (business also includes legacy flats)
    - a published bucket (``business/wiki``, ``test/test_cases``, …)
    - a legacy flat name (``wiki`` / ``procedure`` / ``personal``)

    Returns an empty list when ``bucket`` is not recognized.
    """
    kd = (knowledge_dir or "knowledge").replace("\\", "/").strip("/")
    raw = (bucket or "").strip().lower().replace("\\", "/").strip("/")
    if raw in ("all", "*"):
        raw = ""
    if not raw:
        prefixes = [f"{kd}/{domain}/" for domain in PUBLISHED_DOMAIN_PREFIXES]
        prefixes.extend(f"{kd}/{flat}/" for flat in LEGACY_FLAT_BUCKETS)
        return prefixes
    if raw in PUBLISHED_DOMAIN_PREFIXES:
        prefixes = [f"{kd}/{raw}/"]
        if raw == "business":
            prefixes.extend(f"{kd}/{flat}/" for flat in LEGACY_FLAT_BUCKETS)
        return prefixes
    if raw in LEGACY_FLAT_BUCKETS:
        return [f"{kd}/business/{raw}/", f"{kd}/{raw}/"]
    if raw in PUBLISHED_BUCKETS:
        prefixes = [f"{kd}/{raw}/"]
        if raw.startswith("business/"):
            flat = raw.split("/", 1)[1]
            if flat in LEGACY_FLAT_BUCKETS:
                prefixes.append(f"{kd}/{flat}/")
        return prefixes
    return []


def knowledge_bucket_choices() -> tuple[str, ...]:
    """Values accepted by ``memory_search(bucket=...)``."""
    return (
        "all",
        *PUBLISHED_DOMAIN_PREFIXES,
        *PUBLISHED_BUCKETS,
        *LEGACY_FLAT_BUCKETS,
    )


def knowledge_bases_root() -> Path:
    """Return ``{WORKING_DIR}/knowledge_bases``."""
    return Path(WORKING_DIR).expanduser() / "knowledge_bases"


def kb_root(kb_id: str) -> Path:
    """Absolute path for one knowledge base."""
    return knowledge_bases_root() / validate_kb_id(kb_id)


def validate_kb_id(kb_id: str) -> str:
    """Validate and normalize a knowledge-base id."""
    value = (kb_id or "").strip()
    if not value or not _KB_ID_RE.match(value):
        raise ValueError(
            f"Invalid knowledge_base_id {kb_id!r}. "
            "Use 1-64 chars: letters, digits, '.', '_', '-'.",
        )
    return value


def resolve_kb_id(
    *,
    agent_id: str,
    knowledge_base_id: str | None,
) -> str:
    """Resolve the KB id for an agent (explicit or ``kb_{agent_id}``)."""
    if knowledge_base_id:
        return validate_kb_id(knowledge_base_id)
    safe_agent = re.sub(r"[^a-zA-Z0-9._-]", "_", agent_id.strip())
    if not safe_agent:
        raise ValueError("agent_id is required to auto-create a knowledge base")
    return validate_kb_id(f"kb_{safe_agent}")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _read_kb_md(path: Path) -> KnowledgeBaseMeta | None:
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    meta: dict[str, Any] = {}
    body = text
    if text.startswith("---"):
        # Split on the closing ``---`` fence. Use a regex split with a limit
        # of 2 so a description body that itself contains ``---`` is preserved.
        import re

        parts = re.split(r"^---\s*$", text, maxsplit=2, flags=re.MULTILINE)
        if len(parts) >= 3:
            body = parts[2].lstrip("\n")
            frontmatter_text = parts[1]
            try:
                import yaml

                parsed = yaml.safe_load(frontmatter_text)
                if isinstance(parsed, dict):
                    meta = parsed
            except Exception:
                # Fall back to line-based parsing if YAML is malformed.
                for line in frontmatter_text.splitlines():
                    if ":" not in line:
                        continue
                    key, raw = line.split(":", 1)
                    meta[key.strip()] = raw.strip().strip("\"'")
    return KnowledgeBaseMeta(
        id=str(meta.get("id") or path.parent.name),
        name=str(meta.get("name") or path.parent.name),
        domain=str(meta.get("domain") or "business"),
        version=int(meta.get("version") or 1),
        created_at=str(meta.get("created_at") or ""),
        updated_at=str(meta.get("updated_at") or ""),
        description=body.strip(),
    )


def _write_kb_md(path: Path, meta: KnowledgeBaseMeta) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = meta.description.strip()
    # Quote the name so values with ``:`` or special chars round-trip safely.
    content = (
        "---\n"
        f"id: {meta.id}\n"
        f'name: "{meta.name}"\n'
        f"domain: {meta.domain}\n"
        f"version: {meta.version}\n"
        f"created_at: {meta.created_at}\n"
        f"updated_at: {meta.updated_at}\n"
        "---\n"
        f"{body}\n"
    )
    path.write_text(content, encoding="utf-8")


def ensure_kb(
    kb_id: str,
    *,
    name: str | None = None,
    domain: str = "business",
    description: str = "",
) -> KnowledgeBaseMeta:
    """Create knowledge-base skeleton if missing; return metadata."""
    kb_id = validate_kb_id(kb_id)
    root = kb_root(kb_id)
    root.mkdir(parents=True, exist_ok=True)
    for bucket in KB_BUCKETS:
        # Namespaced buckets like ``business/wiki`` need parents=True.
        (root / bucket).mkdir(parents=True, exist_ok=True)
    (root / ".locks").mkdir(exist_ok=True)

    kb_md = root / "KB.md"
    existing = _read_kb_md(kb_md)
    if existing is not None:
        return existing

    now = _now_iso()
    meta = KnowledgeBaseMeta(
        id=kb_id,
        name=(name or kb_id).strip() or kb_id,
        domain=domain or "business",
        version=1,
        created_at=now,
        updated_at=now,
        description=description,
    )
    _write_kb_md(kb_md, meta)
    # Lightweight index for listing without parsing every KB.md later.
    index_path = knowledge_bases_root() / "_index.json"
    try:
        index: dict[str, Any] = {}
        if index_path.is_file():
            import json

            index = json.loads(index_path.read_text(encoding="utf-8"))
        index[kb_id] = {
            "id": meta.id,
            "name": meta.name,
            "domain": meta.domain,
            "updated_at": meta.updated_at,
        }
        write_json_atomic(index_path, index)
    except Exception:
        logger.debug("Failed to update knowledge base index", exc_info=True)
    logger.info("Created knowledge base %s at %s", kb_id, root)
    return meta


def list_knowledge_bases() -> list[KnowledgeBaseMeta]:
    """List knowledge bases present under ``knowledge_bases/``."""
    root = knowledge_bases_root()
    if not root.is_dir():
        return []
    items: list[KnowledgeBaseMeta] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith("_"):
            continue
        if child.name.startswith("."):
            continue
        meta = _read_kb_md(child / "KB.md")
        if meta is None:
            meta = KnowledgeBaseMeta(id=child.name, name=child.name)
        items.append(meta)
    return items
