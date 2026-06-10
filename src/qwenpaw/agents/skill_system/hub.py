# -*- coding: utf-8 -*-
"""Skills hub client and install helpers."""
from __future__ import annotations

import asyncio
import base64
import contextvars
import io
import json
import logging
import os
import re
import time
import zipfile
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal
from urllib.parse import quote, urlparse, unquote

import frontmatter
import httpx
import yaml

from agentscope_runtime.engine.schemas.exception import ConfigurationException
from ...exceptions import SkillsError
from ...constant import EnvVarLoader
from .models import SkillConflictError
from .pool_service import SkillPoolService
from .store import suggest_conflict_name
from .workspace_service import SkillService

logger = logging.getLogger(__name__)


# ---------- Public types & exceptions --------------------------------------

InstallOrigin = Literal[
    "",
    "skills-sh",
    "github",
    "lobehub",
    "modelscope",
    "aliyun",
    "skillsmp",
    "clawhub",
    "url",
    "zip",
]


@dataclass
class HubSkillResult:
    slug: str
    name: str
    description: str = ""
    version: str = ""
    source_url: str = ""
    author: str = ""
    icon_url: str = ""


@dataclass
class HubInstallResult:
    name: str
    enabled: bool
    source_url: str
    installed_from: InstallOrigin = ""


class SkillImportCancelled(RuntimeError):
    """Raised when a skill import task is cancelled by user."""


def _build_hub_conflict(name: str) -> dict[str, Any]:
    conflict = {
        "reason": "conflict",
        "skill_name": name,
        "suggested_name": suggest_conflict_name(name),
    }
    return {
        **conflict,
        "conflicts": [conflict],
        "message": (
            f"Failed to create skill '{name}'. " "This skill already exists."
        ),
    }


# ---------- Constants ------------------------------------------------------

RETRYABLE_HTTP_STATUS = {
    408,
    409,
    425,
    429,
    500,
    502,
    503,
    504,
}

SKILL_PACKAGE_MAX_ENTRIES = 4096
SKILL_PACKAGE_MAX_BYTES = 200 * 1024 * 1024
HTTP_READ_CHUNK_BYTES = 256 * 1024

_GITHUB_CACHE_DEFAULT_TTL = 300  # 5 minutes
_GITHUB_CACHE_MISS = object()

# ---------- Module-level mutable state -------------------------------------

# GitHub response cache: key → (timestamp, value).
_github_cache: dict[str, tuple[float, Any]] = {}

# Per-key locks for the GitHub response cache. Without these, two
# concurrent callers seeing the same cache miss both fire the same HTTP
# request and burn the GitHub rate-limit budget twice.
_github_cache_key_locks: dict[str, asyncio.Lock] = {}
_github_cache_locks_lock = asyncio.Lock()

# Lazy module-level httpx singleton.
_async_client_lock = asyncio.Lock()
_async_client: httpx.AsyncClient | None = None

# In-flight request tracker. aclose_hub_client() waits on _drain_event so
# concurrent shutdown does not yank the client out from under a live
# request. Event starts set ("drained") because there are no requests yet.
_in_flight: int = 0
_drain_event: asyncio.Event = asyncio.Event()
_drain_event.set()

# Cancel checker (callable returning bool), propagated by contextvar so
# nested install tasks each carry their own checker without interference.
_cancel_checker_ctx: contextvars.ContextVar[
    Any | None
] = contextvars.ContextVar("skills_hub_cancel_checker", default=None)


# ---------- Env-driven config ----------------------------------------------


def _github_cache_ttl() -> float:
    raw = EnvVarLoader.get_str("QWENPAW_GITHUB_CACHE_TTL", "")
    if raw:
        try:
            return max(0.0, float(raw))
        except (TypeError, ValueError):
            pass
    return float(_GITHUB_CACHE_DEFAULT_TTL)


def _hub_http_timeout() -> float:
    raw = EnvVarLoader.get_str("QWENPAW_SKILLS_HUB_HTTP_TIMEOUT", "30")
    try:
        return max(3.0, float(raw))
    except Exception:
        return 30.0


def _hub_http_retries() -> int:
    raw = EnvVarLoader.get_str("QWENPAW_SKILLS_HUB_HTTP_RETRIES", "3")
    try:
        return max(0, int(raw))
    except Exception:
        return 3


def _hub_http_backoff_base() -> float:
    raw = EnvVarLoader.get_str("QWENPAW_SKILLS_HUB_HTTP_BACKOFF_BASE", "0.8")
    try:
        return max(0.1, float(raw))
    except Exception:
        return 0.8


def _hub_http_backoff_cap() -> float:
    raw = EnvVarLoader.get_str("QWENPAW_SKILLS_HUB_HTTP_BACKOFF_CAP", "6")
    try:
        return max(0.5, float(raw))
    except Exception:
        return 6.0


def _compute_backoff_seconds(attempt: int) -> float:
    base = _hub_http_backoff_base()
    cap = _hub_http_backoff_cap()
    return min(cap, base * (2 ** max(0, attempt - 1)))


# ---------- Hub URL builders -----------------------------------------------


def _hub_base_url() -> str:
    return EnvVarLoader.get_str(
        "QWENPAW_SKILLS_HUB_BASE_URL",
        "https://clawhub.ai",
    )


def _hub_search_path() -> str:
    return EnvVarLoader.get_str(
        "QWENPAW_SKILLS_HUB_SEARCH_PATH",
        "/api/v1/search",
    )


def _hub_version_path() -> str:
    return EnvVarLoader.get_str(
        "QWENPAW_SKILLS_HUB_VERSION_PATH",
        "/api/v1/skills/{slug}/versions/{version}",
    )


def _hub_detail_path() -> str:
    return EnvVarLoader.get_str(
        "QWENPAW_SKILLS_HUB_DETAIL_PATH",
        "/api/v1/skills/{slug}",
    )


def _hub_file_path() -> str:
    return EnvVarLoader.get_str(
        "QWENPAW_SKILLS_HUB_FILE_PATH",
        "/api/v1/skills/{slug}/file",
    )


def _join_url(base: str, path: str) -> str:
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


# ---------- Cancellation hooks ---------------------------------------------


def _ensure_not_cancelled() -> None:
    checker = _cancel_checker_ctx.get()
    if checker is None:
        return
    try:
        if bool(checker()):
            raise SkillImportCancelled("Skill import cancelled by user")
    except SkillImportCancelled:
        raise
    except Exception:
        # Ignore checker failures and continue.
        return


@contextmanager
def _with_cancel_checker(checker: Any | None):
    token = _cancel_checker_ctx.set(checker)
    try:
        yield
    finally:
        _cancel_checker_ctx.reset(token)


# ---------- GitHub response cache ------------------------------------------


def _github_cache_get(key: str) -> Any:
    entry = _github_cache.get(key)
    if entry is None:
        return None
    ts, value = entry
    if time.monotonic() - ts > _github_cache_ttl():
        del _github_cache[key]
        return None
    return value


def _github_cached(key: str) -> Any:
    val = _github_cache_get(key)
    return _GITHUB_CACHE_MISS if val is None else val


def _github_cache_set(key: str, value: Any) -> None:
    _github_cache[key] = (time.monotonic(), value)


async def _github_cache_lock_for(key: str) -> asyncio.Lock:
    async with _github_cache_locks_lock:
        lock = _github_cache_key_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _github_cache_key_locks[key] = lock
        return lock


async def _github_cached_call(
    key: str,
    factory: Callable[[], Awaitable[Any]],
) -> Any:
    """Return cached value or run factory under a per-key lock.

    Prevents thundering-herd when multiple coroutines miss the same key:
    only the first one fires the network call; the rest wait on the lock
    and read the freshly-written cache entry.
    """
    cached = _github_cached(key)
    if cached is not _GITHUB_CACHE_MISS:
        return cached
    lock = await _github_cache_lock_for(key)
    async with lock:
        cached = _github_cached(key)
        if cached is not _GITHUB_CACHE_MISS:
            return cached
        result = await factory()
        _github_cache_set(key, result)
        return result


# ---------- Shared httpx async client --------------------------------------


def _build_async_client() -> httpx.AsyncClient:
    timeout = _hub_http_timeout()
    return httpx.AsyncClient(
        timeout=httpx.Timeout(
            connect=min(10.0, timeout),
            read=timeout,
            write=10.0,
            pool=5.0,
        ),
        transport=httpx.AsyncHTTPTransport(retries=2),
        follow_redirects=True,
        headers={"User-Agent": "qwenpaw-skills-hub/1.0"},
        limits=httpx.Limits(
            max_keepalive_connections=8,
            max_connections=20,
        ),
    )


async def _get_async_client() -> httpx.AsyncClient:
    global _async_client
    async with _async_client_lock:
        if _async_client is None or _async_client.is_closed:
            _async_client = _build_async_client()
        return _async_client


@asynccontextmanager
async def _track_request() -> Any:
    """Mark a request as in-flight; aclose_hub_client() waits for these."""
    global _in_flight
    _in_flight += 1
    _drain_event.clear()
    try:
        yield
    finally:
        _in_flight -= 1
        if _in_flight <= 0:
            _in_flight = 0
            _drain_event.set()


async def aclose_hub_client() -> None:
    """Close the shared AsyncClient. Waits for in-flight requests first."""
    global _async_client
    try:
        await asyncio.wait_for(_drain_event.wait(), timeout=10.0)
    except asyncio.TimeoutError:
        logger.warning(
            "aclose_hub_client: %d request(s) still in flight after 10s; "
            "closing anyway",
            _in_flight,
        )
    async with _async_client_lock:
        if _async_client is not None and not _async_client.is_closed:
            await _async_client.aclose()
        _async_client = None


# ---------- HTTP request primitives ----------------------------------------


async def _maybe_retry(
    attempt: int,
    attempts: int,
    url: str,
    exc: Exception,
    reason: str,
) -> bool:
    """Sleep with backoff and return True if the caller should retry."""
    if attempt >= attempts:
        return False
    delay = _compute_backoff_seconds(attempt)
    logger.warning(
        "Hub %s on %s (attempt %d/%d), retrying in %.2fs: %s",
        reason,
        url,
        attempt,
        attempts,
        delay,
        exc,
    )
    _ensure_not_cancelled()
    await asyncio.sleep(delay)
    return True


def _request_headers(full_url: str, accept: str) -> dict[str, str]:
    headers = {"Accept": accept}
    host = (urlparse(full_url).netloc or "").lower()
    github_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if github_token and "api.github.com" in host:
        headers["Authorization"] = f"Bearer {github_token}"
    return headers


def _check_max_bytes(
    full_url: str,
    content_length: int | None,
    max_bytes: int | None,
) -> None:
    if (
        max_bytes is not None
        and content_length is not None
        and content_length > max_bytes
    ):
        raise SkillsError(
            message=f"Response body too large from {full_url}: "
            f"{content_length} bytes exceeds limit {max_bytes}",
        )


async def _stream_to_bytes(
    response: httpx.Response,
    *,
    full_url: str,
    max_bytes: int | None,
    expected_length: int | None,
) -> bytes:
    body = bytearray()
    async for chunk in response.aiter_bytes(chunk_size=HTTP_READ_CHUNK_BYTES):
        _ensure_not_cancelled()
        if not chunk:
            continue
        body.extend(chunk)
        if max_bytes is not None and len(body) > max_bytes:
            raise SkillsError(
                message=f"Response body too large from {full_url}: "
                f"download exceeded limit {max_bytes}",
            )
    # Validate framing only when we got the raw body: Content-Length is the
    # on-the-wire byte count, but `aiter_bytes()` yields already-decoded
    # bytes when `Content-Encoding` (gzip/br/…) or `Transfer-Encoding`
    # (chunked) is in play, so length comparison is meaningless there.
    if (
        expected_length is not None
        and not response.headers.get(
            "Content-Encoding",
        )
        and not response.headers.get(
            "Transfer-Encoding",
        )
        and len(body) < expected_length
    ):
        raise httpx.RemoteProtocolError(
            f"Truncated response from {full_url}: got {len(body)} bytes, "
            f"expected {expected_length}",
            request=response.request,
        )
    return bytes(body)


# ---------- Low-level HTTP fetchers ----------------------------------------


# pylint: disable-next=too-many-branches,too-many-statements
async def _http_fetch(
    url: str,
    params: dict[str, Any] | None = None,
    accept: str = "application/json",
    max_bytes: int | None = None,
    timeout: float | None = None,
) -> bytes:
    _ensure_not_cancelled()
    if max_bytes is not None and max_bytes <= 0:
        raise ConfigurationException(
            config_key="skills_hub.max_bytes",
            message="max_bytes must be greater than 0",
        )

    host = (urlparse(url).netloc or "").lower()
    headers = _request_headers(url, accept)
    attempts = _hub_http_retries() + 1
    last_error: Exception | None = None

    stream_kwargs: dict[str, Any] = {"params": params, "headers": headers}
    if timeout is not None:
        stream_kwargs["timeout"] = httpx.Timeout(
            connect=min(10.0, timeout),
            read=timeout,
            write=10.0,
            pool=5.0,
        )

    for attempt in range(1, attempts + 1):
        _ensure_not_cancelled()
        try:
            client = await _get_async_client()
            async with _track_request():
                async with client.stream(
                    "GET",
                    url,
                    **stream_kwargs,
                ) as response:
                    if response.status_code >= 400:
                        body = await response.aread()
                        raise httpx.HTTPStatusError(
                            f"HTTP {response.status_code}",
                            request=response.request,
                            response=httpx.Response(
                                status_code=response.status_code,
                                headers=response.headers,
                                content=body,
                                request=response.request,
                            ),
                        )
                    raw_len = response.headers.get("Content-Length")
                    try:
                        content_length = int(raw_len) if raw_len else None
                    except (TypeError, ValueError):
                        content_length = None
                    _check_max_bytes(url, content_length, max_bytes)
                    return await _stream_to_bytes(
                        response,
                        full_url=url,
                        max_bytes=max_bytes,
                        expected_length=content_length,
                    )
        except httpx.HTTPStatusError as e:
            last_error = e
            status = e.response.status_code
            if status == 403 and "api.github.com" in host:
                body_text = ""
                try:
                    body_text = e.response.text
                except Exception:
                    body_text = ""
                if (
                    "rate limit" in body_text.lower()
                    or "rate limit" in str(e).lower()
                ):
                    raise SkillsError(
                        message="GitHub API rate limit exceeded"
                        ". Set GITHUB_TOKEN "
                        "to increase the limit, then retry.",
                    ) from e
            if status in RETRYABLE_HTTP_STATUS and await _maybe_retry(
                attempt,
                attempts,
                url,
                e,
                reason=f"HTTP {status}",
            ):
                continue
            if status == 429:
                hint = ""
                if "api.github.com" in host or "github" in url.lower():
                    hint = (
                        " For GitHub sources, set GITHUB_TOKEN to avoid "
                        "rate limits."
                    )
                raise SkillsError(
                    message=(
                        f"Hub returned 429 (Too Many Requests) after "
                        f"{attempts - 1} retries. Try again later.{hint}"
                    ),
                ) from e
            if status >= 500:
                raise SkillsError(
                    message=f"Hub returned {status} after "
                    f"{attempts - 1} retries. Try again later.",
                ) from e
            raise
        except httpx.RemoteProtocolError as e:
            last_error = e
            if await _maybe_retry(
                attempt,
                attempts,
                url,
                e,
                reason="stream closed early",
            ):
                continue
            raise
        except (httpx.TransportError, httpx.TimeoutException) as e:
            last_error = e
            if await _maybe_retry(
                attempt,
                attempts,
                url,
                e,
                reason="transport error",
            ):
                continue
            raise
    if last_error is not None:
        raise last_error
    raise SkillsError(message=f"Failed to request hub URL: {url}")


async def _http_get(
    url: str,
    params: dict[str, Any] | None = None,
    accept: str = "application/json",
    timeout: float | None = None,
) -> str:
    payload = await _http_fetch(
        url,
        params=params,
        accept=accept,
        timeout=timeout,
    )
    return payload.decode("utf-8", errors="replace")


async def _http_bytes_get(
    url: str,
    params: dict[str, Any] | None = None,
    accept: str = "application/octet-stream, */*",
    max_bytes: int | None = None,
) -> bytes:
    return await _http_fetch(
        url,
        params=params,
        accept=accept,
        max_bytes=max_bytes,
    )


async def _http_json_get(
    url: str,
    params: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> Any:
    body = await _http_get(
        url,
        params=params,
        accept="application/json",
        timeout=timeout,
    )
    return json.loads(body)


# Public alias: the shared async JSON GET, reusing hub's pooled httpx
# client + retry + cancellation hooks. Market providers (ModelScope etc.)
# import this so all skill-ecosystem HTTP traffic flows through one
# client. Raises httpx.HTTPStatusError on non-2xx.
http_json_get = _http_json_get


async def _http_text_get(
    url: str,
    params: dict[str, Any] | None = None,
) -> str:
    return await _http_get(
        url,
        params=params,
        accept="text/plain, text/markdown, */*",
    )


# ---------- Search response normalization ----------------------------------


def _norm_search_items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("items", "skills", "results", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
        if all(k in data for k in ("name", "slug")):
            return [data]
    return []


# ---------- Bundle tree helpers & normalization ----------------------------


def _safe_path_parts(path: str) -> list[str] | None:
    if not path or path.startswith("/"):
        return None
    parts = [p for p in path.split("/") if p]
    if not parts:
        return None
    for part in parts:
        if part in (".", ".."):
            return None
    return parts


def _tree_insert(
    tree: dict[str, Any],
    parts: list[str],
    content: str,
) -> None:
    node = tree
    for part in parts[:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    node[parts[-1]] = content


def _files_to_tree(
    files: dict[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    references: dict[str, Any] = {}
    scripts: dict[str, Any] = {}
    for rel, content in files.items():
        if not isinstance(rel, str) or not isinstance(content, str):
            continue
        parts = _safe_path_parts(rel)
        if not parts:
            continue
        if parts[0] == "references" and len(parts) > 1:
            _tree_insert(references, parts[1:], content)
        elif parts[0] == "scripts" and len(parts) > 1:
            _tree_insert(scripts, parts[1:], content)
    return references, scripts


def _sanitize_tree(tree: Any) -> dict[str, Any]:
    if not isinstance(tree, dict):
        return {}
    out: dict[str, Any] = {}
    for key, value in tree.items():
        if not isinstance(key, str):
            continue
        if key in (".", "..") or "/" in key or "\\" in key:
            continue
        if isinstance(value, dict):
            out[key] = _sanitize_tree(value)
        elif isinstance(value, str):
            out[key] = value
    return out


def _bundle_has_content(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    content = (
        payload.get("content")
        or payload.get("skill_md")
        or payload.get("skillMd")
    )
    if isinstance(content, str) and content.strip():
        return True
    files = payload.get("files")
    if isinstance(files, dict) and isinstance(files.get("SKILL.md"), str):
        return True
    return False


def _extract_version_hint(
    detail: dict[str, Any],
    requested_version: str,
) -> str:
    if requested_version:
        return requested_version
    latest = detail.get("latestVersion")
    if isinstance(latest, dict):
        ver = latest.get("version")
        if isinstance(ver, str) and ver:
            return ver
    skill = detail.get("skill")
    if isinstance(skill, dict):
        tags = skill.get("tags")
        if isinstance(tags, dict):
            latest_tag = tags.get("latest")
            if isinstance(latest_tag, str) and latest_tag:
                return latest_tag
    return ""


# pylint: disable-next=too-many-branches
def _normalize_bundle(
    data: Any,
) -> tuple[str, str, dict[str, Any], dict[str, Any], dict[str, Any]]:
    payload = data
    if (
        isinstance(data, dict)
        and isinstance(data.get("skill"), dict)
        and not _bundle_has_content(data)
    ):
        payload = data["skill"]
    if not isinstance(payload, dict):
        raise SkillsError(message="Hub bundle is not a valid JSON object")

    content = (
        payload.get("content")
        or payload.get("skill_md")
        or payload.get("skillMd")
        or ""
    )
    if not isinstance(content, str):
        content = ""

    references = _sanitize_tree(payload.get("references"))
    scripts = _sanitize_tree(payload.get("scripts"))
    extra_files: dict[str, Any] = {}

    # Fallback: parse from a flat files mapping
    files = payload.get("files")
    if isinstance(files, dict):
        ref2, scr2 = _files_to_tree(files)
        if not references:
            references = ref2
        if not scripts:
            scripts = scr2
        for rel, file_content in files.items():
            if not isinstance(rel, str) or not isinstance(file_content, str):
                continue
            if rel == "SKILL.md":
                continue
            parts = _safe_path_parts(rel)
            if not parts:
                continue
            if parts[0] in ("references", "scripts"):
                continue
            _tree_insert(extra_files, parts, file_content)
        if not content and isinstance(files.get("SKILL.md"), str):
            content = files["SKILL.md"]

    if not content:
        raise SkillsError(message="Hub bundle missing SKILL.md content")

    name = payload.get("name", "")
    if not isinstance(name, str):
        name = ""
    if not name:
        try:
            post = frontmatter.loads(content)
            name = post.get("name", "")
        except yaml.YAMLError:
            name = ""
    if not name:
        raise SkillsError(message="Hub bundle missing skill name")

    return name, content, references, scripts, extra_files


# ---------- Text & name helpers --------------------------------------------


def _safe_fallback_name(raw: str) -> str:
    out = re.sub(r"[^a-zA-Z0-9_-]", "-", raw).strip("-_")
    return out or "imported-skill"


def _normalize_skill_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _sanitize_skill_dir_name(name: str) -> str:
    """Sanitize skill name for use as directory name.

    Display names like "Excel / XLSX" must not be used as-is because "/"
    can be misinterpreted as a path separator.
    """
    if not name or not isinstance(name, str):
        return "imported-skill"
    if "/" in name or "\\" in name:
        sanitized = _normalize_skill_key(name)
        return sanitized or _safe_fallback_name(name)
    return name


def _is_http_url(text: str) -> bool:
    parsed = urlparse(text.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _is_probably_text_blob(payload: bytes) -> bool:
    if not payload:
        return True
    if b"\x00" in payload:
        return False
    sample = payload[:1024]
    text_chars = bytearray({7, 8, 9, 10, 12, 13, 27})
    text_chars.extend(range(0x20, 0x100))
    non_text = sample.translate(None, bytes(text_chars))
    return len(non_text) <= max(1, len(sample) // 10)


def _extract_error_message_from_payload(payload: bytes) -> str:
    if not payload:
        return ""
    if not _is_probably_text_blob(payload):
        return ""
    text = payload.decode("utf-8", errors="ignore").strip()
    if not text:
        return ""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(data, dict):
        for key in ("error", "message"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return text


def _format_http_error_body(error: httpx.HTTPStatusError) -> str:
    try:
        body_bytes = error.response.content
    except Exception:
        body_bytes = b""
    if body_bytes:
        message = _extract_error_message_from_payload(bytes(body_bytes))
        if message:
            return message
    return str(error)


# ---------- Provider URL parsers -------------------------------------------


def _extract_clawhub_slug_from_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if "clawhub.ai" not in host:
        return ""
    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return ""
    # clawhub pages can be /owner/skill or /skill
    return parts[-1].strip()


def _extract_skills_sh_spec(url: str) -> tuple[str, str, str] | None:
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if host not in {"skills.sh", "www.skills.sh"}:
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 3:
        return None
    owner, repo, skill = parts[0], parts[1], parts[2]
    if not owner or not repo or not skill:
        return None
    return owner, repo, skill


def _extract_skillsmp_slug(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if host not in {"skillsmp.com", "www.skillsmp.com"}:
        return ""
    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return ""
    if "skills" in parts:
        idx = parts.index("skills")
        if idx + 1 < len(parts):
            return parts[idx + 1].strip()
    return ""


def _extract_lobehub_identifier(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    parts = [unquote(p) for p in parsed.path.split("/") if p]
    if not parts:
        return ""
    if host in {"lobehub.com", "www.lobehub.com"}:
        if "skills" not in parts:
            return ""
        idx = parts.index("skills")
        if idx + 1 < len(parts):
            return parts[idx + 1].strip()
        return ""
    if host == "market.lobehub.com":
        marker = ["api", "v1", "skills"]
        if len(parts) >= 5 and parts[:3] == marker and parts[4] == "download":
            return parts[3].strip()
    return ""


def _extract_modelscope_skill_spec(
    url: str,
) -> tuple[str, str, str] | None:
    """Parse ModelScope skills URL into (owner, skill_name, version_hint)."""
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if host not in {"modelscope.cn", "www.modelscope.cn"}:
        return None
    parts = [unquote(p) for p in parsed.path.split("/") if p]
    if len(parts) < 3 or parts[0] != "skills":
        return None

    # Owner is preserved verbatim (including any leading `@`) so the
    # archive URL we synthesise matches the original skill id exactly.
    owner = parts[1].strip()
    skill_name = parts[2].strip()
    if not owner or not skill_name:
        return None

    version_hint = ""
    if len(parts) >= 6 and parts[3] == "archive" and parts[4] == "zip":
        archive_name = parts[5].strip()
        if archive_name.endswith(".zip"):
            archive_name = archive_name[: -len(".zip")]
        version_hint = archive_name
    return owner, skill_name, version_hint


def _extract_aliyun_skill_spec(url: str) -> str | None:
    """Parse an Aliyun AgentExplorer skill URL and return the skill id.

    Accepts URLs synthesised by `qwenpaw.market.providers.aliyun`, of the
    form `https://api.aliyun.com/agentexplorer/skills/<skill_id>`.
    """
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if host not in {"api.aliyun.com", "www.api.aliyun.com"}:
        return None
    parts = [unquote(p) for p in parsed.path.split("/") if p]
    if len(parts) < 3:
        return None
    if parts[0].lower() != "agentexplorer" or parts[1].lower() != "skills":
        return None
    skill_id = parts[2].strip()
    return skill_id or None


def _extract_github_spec(
    url: str,
) -> tuple[str, str, str, str] | None:
    """Parse GitHub repo URL into (owner, repo, branch, path_hint)."""
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if host not in {"github.com", "www.github.com"}:
        return None
    parts = [unquote(p) for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1]
    branch = ""
    path_hint = ""
    # /owner/repo/tree/<branch>/<path...>
    if len(parts) >= 4 and parts[2] in {"tree", "blob"}:
        branch = parts[3]
        if len(parts) > 4:
            path_hint = "/".join(parts[4:])
    elif len(parts) > 2:
        # e.g. /owner/repo/<extra>, treat as path hint
        path_hint = "/".join(parts[2:])
    return owner, repo, branch, path_hint


def _resolve_clawhub_slug(bundle_url: str) -> str:
    from_url = _extract_clawhub_slug_from_url(bundle_url)
    if from_url:
        return from_url
    return ""


# ---------- GitHub Contents API client -------------------------------------


def _github_api_url(owner: str, repo: str, suffix: str) -> str:
    base = f"https://api.github.com/repos/{owner}/{repo}"
    cleaned = suffix.lstrip("/")
    return f"{base}/{cleaned}" if cleaned else base


def _github_encode_path(path: str) -> str:
    cleaned = path.strip("/")
    if not cleaned:
        return ""
    return quote(cleaned, safe="/")


async def _github_repo_exists(owner: str, repo: str) -> bool:
    if not owner or not repo:
        return False

    async def fetch() -> bool:
        try:
            data = await _http_json_get(_github_api_url(owner, repo, ""))
        except Exception:
            return False
        return isinstance(data, dict) and data.get("full_name") is not None

    return await _github_cached_call(f"repo_exists:{owner}/{repo}", fetch)


async def _github_get_default_branch(owner: str, repo: str) -> str:
    async def fetch() -> str:
        repo_meta = await _http_json_get(_github_api_url(owner, repo, ""))
        if isinstance(repo_meta, dict):
            raw = repo_meta.get("default_branch")
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
        return "main"

    return await _github_cached_call(f"default_branch:{owner}/{repo}", fetch)


async def _github_list_skill_md_roots(
    owner: str,
    repo: str,
    ref: str,
) -> list[str]:
    async def fetch() -> list[str]:
        tree_url = _github_api_url(owner, repo, f"git/trees/{ref}")
        try:
            data = await _http_json_get(tree_url, {"recursive": "1"})
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return []
            raise
        if not isinstance(data, dict):
            return []
        tree = data.get("tree")
        if not isinstance(tree, list):
            return []
        roots: list[str] = []
        for item in tree:
            if not isinstance(item, dict):
                continue
            path = item.get("path")
            if not isinstance(path, str):
                continue
            if path == "SKILL.md":
                roots.append("")
                continue
            if path.endswith("/SKILL.md"):
                roots.append(path[: -len("/SKILL.md")])
        # Keep order stable and unique
        seen: set[str] = set()
        unique: list[str] = []
        for root in roots:
            if root in seen:
                continue
            seen.add(root)
            unique.append(root)
        return unique

    return await _github_cached_call(
        f"skill_md_roots:{owner}/{repo}/{ref}",
        fetch,
    )


async def _github_get_content_entry(
    owner: str,
    repo: str,
    path: str,
    ref: str,
) -> dict[str, Any]:
    async def fetch() -> dict[str, Any]:
        encoded_path = _github_encode_path(path)
        content_url = _github_api_url(owner, repo, f"contents/{encoded_path}")
        data = await _http_json_get(content_url, {"ref": ref})
        if not isinstance(data, dict):
            raise SkillsError(
                message=f"Unexpected GitHub response for path: {path}",
            )
        return data

    return await _github_cached_call(
        f"content:{owner}/{repo}/{path}@{ref}",
        fetch,
    )


async def _github_get_dir_entries(
    owner: str,
    repo: str,
    path: str,
    ref: str,
) -> list[dict[str, Any]]:
    async def fetch() -> list[dict[str, Any]]:
        encoded_path = _github_encode_path(path)
        suffix = "contents" if not encoded_path else f"contents/{encoded_path}"
        content_url = _github_api_url(owner, repo, suffix)
        data = await _http_json_get(content_url, {"ref": ref})
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        return []

    return await _github_cached_call(
        f"dir:{owner}/{repo}/{path}@{ref}",
        fetch,
    )


async def _github_read_file(entry: dict[str, Any]) -> str:
    download_url = entry.get("download_url")
    if isinstance(download_url, str) and download_url:
        return await _http_text_get(download_url)

    content = entry.get("content")
    if isinstance(content, str) and content:
        try:
            normalized = content.replace("\n", "")
            return base64.b64decode(normalized).decode(
                "utf-8",
                errors="replace",
            )
        except Exception:
            pass

    raise SkillsError(message="Unable to read file content from GitHub entry")


def _join_repo_path(root: str, leaf: str) -> str:
    if not root:
        return leaf
    return f"{root.rstrip('/')}/{leaf.lstrip('/')}"


def _relative_from_root(full_path: str, root: str) -> str:
    if not root:
        return full_path.lstrip("/")
    prefix = f"{root.rstrip('/')}/"
    if full_path.startswith(prefix):
        return full_path[len(prefix) :]
    return full_path


async def _github_collect_tree_files(
    owner: str,
    repo: str,
    ref: str,
    root: str,
    max_files: int = 4096,
) -> dict[str, str]:
    files: dict[str, str] = {}
    pending = [root] if root else [""]
    visited = 0
    while pending:
        _ensure_not_cancelled()
        current_dir = pending.pop()
        target_dir = current_dir or ""
        entries = await _github_get_dir_entries(owner, repo, target_dir, ref)
        for entry in entries:
            _ensure_not_cancelled()
            entry_type = str(entry.get("type") or "")
            entry_path = str(entry.get("path") or "")
            if not entry_path:
                continue
            if entry_type == "dir":
                pending.append(entry_path)
                continue
            if entry_type != "file":
                continue
            rel = _relative_from_root(entry_path, root)
            files[rel] = await _github_read_file(entry)
            visited += 1
            if visited >= max_files:
                logger.warning(
                    "Hub file collection capped at %d files",
                    max_files,
                )
                return files
    return files


# pylint: disable-next=too-many-return-statements,too-many-branches
async def _resolve_skillsmp_spec(
    url: str,
) -> tuple[str, str, str] | None:
    """Parse SkillsMP URL slug into (owner, repo, skill_hint).

    Example:
      openclaw-openclaw-skills-himalaya-skill-md
      -> owner=openclaw, repo=openclaw-skills, skill_hint=himalaya
    """
    slug = _extract_skillsmp_slug(url)
    if not slug:
        return None
    if slug.endswith("-skill-md"):
        slug = slug[: -len("-skill-md")]
    tokens = [t for t in slug.split("-") if t]
    if len(tokens) < 3:
        return None

    owner = tokens[0]
    tail_tokens = tokens[1:]
    # Try repo split points and pick the first repo that exists on GitHub.
    # Keep requests bounded to avoid rate-limit pressure.
    max_split = min(len(tail_tokens), 6)
    for i in range(max_split, 0, -1):
        repo = "-".join(tail_tokens[:i]).strip()
        if not repo:
            continue
        if not await _github_repo_exists(owner, repo):
            continue
        remainder = tail_tokens[i:]
        skill_hint = "-".join(remainder).strip() if remainder else ""
        return owner, repo, skill_hint

    # Conservative fallback when repo existence checks fail
    repo = tail_tokens[0]
    skill_hint = "-".join(tail_tokens[1:]).strip()
    return owner, repo, skill_hint


# ---------- Provider: skills.sh / GitHub / SkillsMP (GitHub-backed) --------


async def _fetch_bundle_from_skills_sh_url(
    bundle_url: str,
    requested_version: str,
) -> tuple[Any, str]:
    spec = _extract_skills_sh_spec(bundle_url)
    if spec is None:
        raise ConfigurationException(
            config_key="skills_hub.bundle_url",
            message="Invalid skills.sh URL format",
        )
    owner, repo, skill = spec
    default_branch = await _github_get_default_branch(owner, repo) or "main"
    bundle, source_url = await _fetch_bundle_from_repo_and_skill_hint(
        owner=owner,
        repo=repo,
        skill_hint=skill,
        requested_version=requested_version,
        default_branch=default_branch,
    )
    bundle["name"] = skill
    return bundle, source_url


# pylint: disable-next=too-many-branches,too-many-statements
async def _fetch_bundle_from_repo_and_skill_hint(
    *,
    owner: str,
    repo: str,
    skill_hint: str,
    requested_version: str,
    default_branch: str = "main",
) -> tuple[Any, str]:
    if requested_version.strip():
        branch_candidates = [requested_version.strip()]
    else:
        branch_candidates = []
        if default_branch:
            branch_candidates.append(default_branch)
        for b in ("main", "master"):
            if b not in branch_candidates:
                branch_candidates.append(b)
    skill = skill_hint.strip()

    selected_root = ""
    skill_md_entry: dict[str, Any] | None = None
    branch = branch_candidates[0]
    for candidate_branch in branch_candidates:
        branch = candidate_branch
        roots = [
            _join_repo_path("skills", skill) if skill else "",
            skill,
            "",
        ]
        roots = [r for r in roots if r or r == ""]
        for root in roots:
            skill_md_path = _join_repo_path(root, "SKILL.md")
            try:
                entry = await _github_get_content_entry(
                    owner,
                    repo,
                    skill_md_path,
                    branch,
                )
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    continue
                raise
            if str(entry.get("type") or "") == "file":
                selected_root = root
                skill_md_entry = entry
                break
        if skill_md_entry is not None:
            break

    if skill_md_entry is None:
        skill_norm = _normalize_skill_key(skill)
        for candidate_branch in branch_candidates:
            branch = candidate_branch
            roots = await _github_list_skill_md_roots(owner, repo, branch)
            for root in roots:
                leaf = root.split("/")[-1] if root else root
                leaf_norm = _normalize_skill_key(leaf)
                if not leaf_norm:
                    continue
                if not skill_norm or (
                    leaf_norm == skill_norm
                    or leaf_norm in skill_norm
                    or skill_norm in leaf_norm
                    or skill_norm.endswith(f"-{leaf_norm}")
                ):
                    selected_root = root
                    skill_md_path = _join_repo_path(root, "SKILL.md")
                    try:
                        entry = await _github_get_content_entry(
                            owner,
                            repo,
                            skill_md_path,
                            branch,
                        )
                    except httpx.HTTPStatusError:
                        continue
                    if str(entry.get("type") or "") == "file":
                        skill_md_entry = entry
                        break
            if skill_md_entry is not None:
                break

    if skill_md_entry is None:
        raise SkillsError(
            message=f"Could not find SKILL.md in source repository "
            f"https://github.com/{owner}/{repo}. "
            f"Path hint: {skill_hint!r}; tried branches: {branch_candidates}. "
            "Ensure the URL points to a folder containing SKILL.md, e.g. "
            "https://github.com/owner/repo/tree/master/skills/skill-name",
        )

    files: dict[str, str] = {
        "SKILL.md": await _github_read_file(skill_md_entry),
    }
    files.update(
        await _github_collect_tree_files(
            owner=owner,
            repo=repo,
            ref=branch,
            root=selected_root,
        ),
    )
    source_url = f"https://github.com/{owner}/{repo}"
    skill_name = skill.split("/")[-1].strip() if skill else repo
    return {"name": skill_name or repo, "files": files}, source_url


async def _fetch_bundle_from_github_url(
    bundle_url: str,
    requested_version: str,
) -> tuple[Any, str]:
    spec = _extract_github_spec(bundle_url)
    if spec is None:
        raise ConfigurationException(
            config_key="skills_hub.bundle_url",
            message="Invalid GitHub URL format. Use a repo or path URL, e.g. "
            "https://github.com/owner/repo or "
            "https://github.com/owner/repo/tree/branch/path/to/skill",
        )
    owner, repo, branch_in_url, path_hint = spec
    path_hint = path_hint.strip("/")
    # If path points directly to SKILL.md, normalize to its parent directory.
    if path_hint.endswith("/SKILL.md"):
        path_hint = path_hint[: -len("/SKILL.md")]
    elif path_hint == "SKILL.md":
        path_hint = ""
    branch = requested_version.strip() or branch_in_url.strip()
    default_branch = ""
    try:
        default_branch = await _github_get_default_branch(owner, repo)
    except Exception:
        pass
    return await _fetch_bundle_from_repo_and_skill_hint(
        owner=owner,
        repo=repo,
        skill_hint=path_hint,
        requested_version=branch,
        default_branch=default_branch or "main",
    )


async def _fetch_bundle_from_skillsmp_url(
    bundle_url: str,
    requested_version: str,
) -> tuple[Any, str]:
    spec = await _resolve_skillsmp_spec(bundle_url)
    if spec is None:
        raise ConfigurationException(
            config_key="skills_hub.bundle_url",
            message="Invalid skillsmp URL format",
        )
    owner, repo, skill_hint = spec
    return await _fetch_bundle_from_repo_and_skill_hint(
        owner=owner,
        repo=repo,
        skill_hint=skill_hint,
        requested_version=requested_version,
    )


# ---------- Provider: LobeHub (zip download) -------------------------------


def _lobehub_download_url(identifier: str) -> str:
    return "https://market.lobehub.com/api/v1/skills/" f"{identifier}/download"


def _should_keep_lobehub_file(parts: list[str]) -> bool:
    if not parts:
        return False
    if parts == ["SKILL.md"]:
        return True
    if parts[0] in {"references", "scripts"} and len(parts) > 1:
        return True
    return len(parts) == 1


def _lobehub_zip_to_bundle(identifier: str, payload: bytes) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            files: dict[str, str] = {}
            entry_count = 0
            total_bytes = 0
            for info in zf.infolist():
                if info.is_dir():
                    continue
                entry_count += 1
                if entry_count > SKILL_PACKAGE_MAX_ENTRIES:
                    raise SkillsError(
                        message="LobeHub skill package has too many files",
                    )
                total_bytes += max(0, info.file_size)
                if total_bytes > SKILL_PACKAGE_MAX_BYTES:
                    raise SkillsError(
                        message="LobeHub skill package is too large to import",
                    )
                parts = _safe_path_parts(info.filename.replace("\\", "/"))
                if not parts:
                    continue
                if not _should_keep_lobehub_file(parts):
                    continue
                rel_path = "/".join(parts)
                raw = zf.read(info)
                if not _is_probably_text_blob(raw):
                    logger.warning(
                        "Skipping non-text file from LobeHub package: %s",
                        rel_path,
                    )
                    continue
                files[rel_path] = raw.decode("utf-8", errors="replace")
    except zipfile.BadZipFile as e:
        message = _extract_error_message_from_payload(payload)
        if message:
            raise SkillsError(
                message=f"LobeHub skill download failed: {message}",
            ) from e
        raise SkillsError(
            message="LobeHub skill download did not return a valid zip",
        ) from e

    if "SKILL.md" not in files:
        raise SkillsError(message="LobeHub skill package is missing SKILL.md")
    try:
        post = frontmatter.loads(files["SKILL.md"])
    except yaml.YAMLError:
        post = None
    skill_name = post.get("name") if post is not None else None
    if not isinstance(skill_name, str) or not skill_name.strip():
        skill_name = identifier
    return {"name": skill_name.strip(), "files": files}


async def _fetch_bundle_from_lobehub_url(
    bundle_url: str,
    requested_version: str,
) -> tuple[Any, str]:
    identifier = _extract_lobehub_identifier(bundle_url)
    if not identifier:
        raise ConfigurationException(
            config_key="skills_hub.bundle_url",
            message="Invalid LobeHub skill URL format",
        )
    params = (
        {"version": requested_version.strip()}
        if requested_version.strip()
        else None
    )
    try:
        payload = await _http_bytes_get(
            _lobehub_download_url(identifier),
            params=params,
            accept="application/zip, application/octet-stream, */*",
            max_bytes=SKILL_PACKAGE_MAX_BYTES,
        )
    except httpx.HTTPStatusError as e:
        raise SkillsError(
            message="LobeHub skill download failed: "
            f"{_format_http_error_body(e)}",
        ) from e
    except ValueError as e:
        raise SkillsError(message=f"LobeHub skill download failed: {e}") from e
    return _lobehub_zip_to_bundle(identifier, payload), bundle_url


# ---------- Provider: ModelScope (archive zip) -----------------------------


def _modelscope_archive_to_bundle(
    payload: bytes,
    fallback_name: str,
) -> dict[str, Any]:
    # Archive wraps every file in `skills-<owner>.<name>-<branch>-<sha>/`;
    # strip that prefix so paths align with the install pipeline.
    try:
        zf = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as e:
        raise SkillsError(
            message="ModelScope archive is not a valid zip",
        ) from e

    files: dict[str, str] = {}
    entry_count = 0
    total_bytes = 0
    with zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            entry_count += 1
            if entry_count > SKILL_PACKAGE_MAX_ENTRIES:
                raise SkillsError(
                    message="ModelScope archive has too many files",
                )
            total_bytes += max(0, info.file_size)
            if total_bytes > SKILL_PACKAGE_MAX_BYTES:
                raise SkillsError(
                    message="ModelScope archive is too large to import",
                )
            parts = _safe_path_parts(info.filename.replace("\\", "/"))
            if not parts or len(parts) < 2:
                continue
            rel = "/".join(parts[1:])
            raw = zf.read(info)
            if not _is_probably_text_blob(raw):
                continue
            files[rel] = raw.decode("utf-8", errors="replace")

    if "SKILL.md" not in files:
        raise SkillsError(
            message="ModelScope archive is missing SKILL.md",
        )

    name = fallback_name
    try:
        post = frontmatter.loads(files["SKILL.md"])
        fm_name = post.get("name")
        if isinstance(fm_name, str) and fm_name.strip():
            name = fm_name.strip()
    except yaml.YAMLError:
        pass
    return {"name": name, "files": files}


async def _fetch_bundle_from_modelscope_url(
    bundle_url: str,
    requested_version: str,
) -> tuple[Any, str]:
    spec = _extract_modelscope_skill_spec(bundle_url)
    if spec is None:
        raise ConfigurationException(
            config_key="skills_hub.bundle_url",
            message="Invalid ModelScope URL format. Use URL like "
            "https://modelscope.cn/skills/@owner/skill-name",
        )
    owner, skill_name, version_hint = spec
    branch = requested_version.strip() or version_hint or "master"
    archive_url = (
        "https://www.modelscope.cn/skills/"
        f"{quote(owner, safe='@')}/{quote(skill_name, safe='')}"
        f"/archive/zip/{quote(branch, safe='')}"
    )
    try:
        payload = await _http_bytes_get(
            archive_url,
            max_bytes=SKILL_PACKAGE_MAX_BYTES,
        )
    except httpx.HTTPStatusError as e:
        raise SkillsError(
            message=(
                "ModelScope archive download failed: "
                f"{_format_http_error_body(e)}. Not every ModelScope skill "
                "is published as a downloadable archive — if this one isn't, "
                "import it from its underlying source URL (GitHub / ClawHub) "
                "instead."
            ),
        ) from e
    return (
        _modelscope_archive_to_bundle(payload, fallback_name=skill_name),
        bundle_url,
    )


# ---------- Provider: Aliyun AgentExplorer (signed API) --------------------


def _aliyun_response_to_bundle(
    skill_name: str,
    body: Any,
) -> dict[str, Any]:
    """Convert GetSkillContent response → canonical bundle dict.

    Verified live response shape: `{"requestId": "...", "content": "..."}`.
    The `content` field is the full SKILL.md as a string (frontmatter +
    body). Multi-file references / scripts aren't available through
    this endpoint; the bundle is single-file.
    """
    if not isinstance(body, dict):
        raise SkillsError(
            message="Aliyun GetSkillContent returned a non-dict body",
        )
    content = body.get("content")
    if not isinstance(content, str) or not content.strip():
        raise SkillsError(
            message="Aliyun GetSkillContent response missing `content`",
        )
    return {"name": skill_name, "files": {"SKILL.md": content}}


async def _fetch_bundle_from_aliyun_url(
    bundle_url: str,
    requested_version: str,
) -> tuple[Any, str]:
    """Aliyun AgentExplorer install — `GET /openapi/skills/{skill_id}`.

    V3 ACS3-HMAC-SHA256 signed via `alibabacloud_tea_openapi`.
    Credentials come from the standard Aliyun chain (env,
    `~/.alibabacloud/credentials`, RAM role).
    """
    del requested_version  # endpoint has no version selector
    skill_id = _extract_aliyun_skill_spec(bundle_url)
    if not skill_id:
        raise ConfigurationException(
            config_key="skills_hub.bundle_url",
            message=(
                "Invalid Aliyun skill URL. Expected a URL like "
                "https://api.aliyun.com/agentexplorer/skills/<skill_id>"
            ),
        )

    try:
        from qwenpaw.market.providers.aliyun import (
            call_aliyun_action_async,
        )
    except ImportError as exc:  # pragma: no cover
        raise ConfigurationException(
            config_key="skills_hub.aliyun.sdk",
            message=(
                "Aliyun SDK not installed — run "
                "`uv add alibabacloud-tea-openapi alibabacloud-credentials "
                "alibabacloud-tea-util`"
            ),
        ) from exc

    try:
        resp_body = await call_aliyun_action_async(
            action="GetSkillContent",
            pathname=f"/openapi/skills/{quote(skill_id, safe='')}",
            method="GET",
        )
    except Exception as exc:  # noqa: BLE001
        raise SkillsError(
            message=f"Aliyun GetSkillContent failed: {exc}",
        ) from exc

    bundle = _aliyun_response_to_bundle(skill_id, resp_body)
    return bundle, bundle_url


# ---------- Provider: ClawHub (slug-based detail API) ----------------------


# pylint: disable-next=too-many-return-statements,too-many-branches
async def _hydrate_clawhub_payload(
    data: Any,
    *,
    slug: str,
    requested_version: str,
) -> Any:
    """Convert ClawHub metadata responses into a bundle with file contents."""
    if _bundle_has_content(data):
        return data
    if not isinstance(data, dict):
        return data
    skill = data.get("skill")
    if not isinstance(skill, dict):
        return data

    skill_slug = str(skill.get("slug") or slug or "").strip()
    if not skill_slug:
        return data

    version_data = data
    version_obj = data.get("version")
    if not isinstance(version_obj, dict) or not isinstance(
        version_obj.get("files"),
        list,
    ):
        version_hint = _extract_version_hint(data, requested_version)
        if not version_hint:
            return data
        base = _hub_base_url()
        version_url = _join_url(
            base,
            _hub_version_path().format(slug=skill_slug, version=version_hint),
        )
        version_data = await _http_json_get(version_url)
        version_obj = (
            version_data.get("version")
            if isinstance(version_data, dict)
            else None
        )

    if not isinstance(version_obj, dict):
        return data
    files_meta = version_obj.get("files")
    if not isinstance(files_meta, list):
        return data

    version_str = str(
        version_obj.get("version") or requested_version or "",
    ).strip()
    base = _hub_base_url()
    file_url = _join_url(base, _hub_file_path().format(slug=skill_slug))
    files: dict[str, str] = {}
    last_fetch_error: Exception | None = None
    for item in files_meta:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        if not isinstance(path, str) or not path:
            continue
        params = {"path": path}
        if version_str:
            params["version"] = version_str
        try:
            files[path] = await _http_text_get(file_url, params=params)
        except Exception as e:
            last_fetch_error = e
            logger.warning("Failed to fetch hub file %s: %s", path, e)

    if not files.get("SKILL.md"):
        if last_fetch_error is not None:
            raise SkillsError(
                message="Failed to fetch SKILL.md from hub: "
                + str(last_fetch_error),
            ) from last_fetch_error
        return data

    return {
        "name": skill.get("displayName") or skill_slug,
        "files": files,
    }


async def _fetch_bundle_from_clawhub_slug(
    slug: str,
    version: str,
) -> tuple[Any, str]:
    if not slug:
        raise ConfigurationException(
            config_key="skills_hub.slug",
            message="slug is required for clawhub install",
        )
    base = _hub_base_url()
    errors: list[str] = []
    candidates = [
        _join_url(base, _hub_detail_path().format(slug=slug)),
    ]
    data: Any | None = None
    source_url = ""
    for candidate in candidates:
        try:
            data = await _http_json_get(candidate)
            source_url = candidate
            break
        except Exception as e:
            errors.append(f"{candidate}: {e}")
    if data is None:
        raise SkillsError(
            message="When importing from ClawHub: " + "; ".join(errors),
        )
    hydrated = await _hydrate_clawhub_payload(
        data,
        slug=slug,
        requested_version=version,
    )
    return hydrated, source_url


async def _fetch_bundle_from_clawhub_url(
    bundle_url: str,
    requested_version: str,
) -> tuple[Any, str]:
    """Adapter so ClawHub fits the standard provider fetcher signature."""
    slug = _resolve_clawhub_slug(bundle_url)
    if not slug:
        raise ConfigurationException(
            config_key="skills_hub.bundle_url",
            message="Invalid ClawHub URL format",
        )
    return await _fetch_bundle_from_clawhub_slug(slug, requested_version)


# ---------- Public search API ----------------------------------------------


async def search_hub_skills(
    query: str,
    limit: int = 20,
    timeout: float | None = None,
) -> list[HubSkillResult]:
    base = _hub_base_url()
    search_url = _join_url(base, _hub_search_path())
    data = await _http_json_get(
        search_url,
        {"q": query, "limit": limit},
        timeout=timeout,
    )
    items = _norm_search_items(data)
    results: list[HubSkillResult] = []
    for item in items:
        slug = str(item.get("slug") or item.get("name") or "").strip()
        if not slug:
            continue
        owner = item.get("owner") if isinstance(item, dict) else None
        owner_handle = ""
        owner_display = ""
        owner_image = ""
        if isinstance(owner, dict):
            owner_handle = str(owner.get("handle") or "").strip()
            owner_display = str(owner.get("displayName") or "").strip()
            owner_image = str(owner.get("image") or "").strip()
        if not owner_handle and isinstance(item, dict):
            owner_handle = str(item.get("ownerHandle") or "").strip()
        results.append(
            HubSkillResult(
                slug=slug,
                name=str(
                    item.get("name") or item.get("displayName") or slug,
                ),
                description=str(
                    item.get("description") or item.get("summary") or "",
                ),
                version=str(item.get("version") or ""),
                source_url=str(item.get("url") or ""),
                author=owner_display or owner_handle,
                icon_url=owner_image,
            ),
        )
    return results


# ---------- Provider routing -----------------------------------------------

# Single source of truth for provider routing. Each entry pairs a sync,
# cheap URL matcher (returns truthy on a hit) with the async fetcher to
# invoke. Order matters — first match wins. Add new providers here.
_ProviderMatcher = Callable[[str], Any]
_ProviderFetcher = Callable[..., Awaitable[tuple[Any, str]]]

PROVIDERS: list[tuple[InstallOrigin, _ProviderMatcher, _ProviderFetcher]] = [
    ("skills-sh", _extract_skills_sh_spec, _fetch_bundle_from_skills_sh_url),
    ("github", _extract_github_spec, _fetch_bundle_from_github_url),
    ("lobehub", _extract_lobehub_identifier, _fetch_bundle_from_lobehub_url),
    (
        "modelscope",
        _extract_modelscope_skill_spec,
        _fetch_bundle_from_modelscope_url,
    ),
    ("aliyun", _extract_aliyun_skill_spec, _fetch_bundle_from_aliyun_url),
    ("skillsmp", _extract_skillsmp_slug, _fetch_bundle_from_skillsmp_url),
    ("clawhub", _resolve_clawhub_slug, _fetch_bundle_from_clawhub_url),
]


def _match_provider(
    bundle_url: str,
) -> tuple[InstallOrigin, _ProviderFetcher | None]:
    for name, matcher, fetcher in PROVIDERS:
        if matcher(bundle_url):
            return name, fetcher
    return "url", None


def _classify_install_origin(bundle_url: str) -> InstallOrigin:
    """Short origin label persisted on the manifest entry."""
    if not bundle_url:
        return ""
    name, _ = _match_provider(bundle_url)
    return name


async def _resolve_bundle_from_url(
    bundle_url: str,
    version: str,
) -> tuple[Any, str]:
    _, fetcher = _match_provider(bundle_url)
    if fetcher is not None:
        return await fetcher(bundle_url, requested_version=version)
    # Fallback for direct bundle JSON URLs.
    return await _http_json_get(bundle_url), bundle_url


# ---------- Public install API ---------------------------------------------


@dataclass
class _InstallPayload:
    name: str
    content: str
    references: dict[str, Any]
    scripts: dict[str, Any]
    extra_files: dict[str, Any]
    source_url: str
    installed_from: InstallOrigin


async def _prepare_install_payload(
    bundle_url: str,
    version: str,
    target_name: str | None,
) -> _InstallPayload:
    """Validate, fetch, normalise, resolve final skill name.

    Shared front-half of both install entry points; the entry points
    differ only in which store (workspace vs pool) they write to and in
    cancel/enable semantics.
    """
    if not bundle_url or not _is_http_url(bundle_url):
        raise ConfigurationException(
            config_key="skills_hub.bundle_url",
            message="bundle_url must be a valid http(s) URL",
        )
    _ensure_not_cancelled()
    data, source_url = await _resolve_bundle_from_url(bundle_url, version)
    installed_from = _classify_install_origin(bundle_url)
    name, content, references, scripts, extra_files = _normalize_bundle(data)
    if not name:
        fallback = urlparse(bundle_url).path.strip("/").split("/")[-1]
        name = _safe_fallback_name(fallback)
    # Sanitize: display names like "Excel / XLSX" cannot be dir names.
    name = _sanitize_skill_dir_name(name)
    normalized_target = str(target_name or "").strip()
    if normalized_target:
        name = _sanitize_skill_dir_name(normalized_target)
    return _InstallPayload(
        name=name,
        content=content,
        references=references,
        scripts=scripts,
        extra_files=extra_files,
        source_url=source_url,
        installed_from=installed_from,
    )


async def install_skill_from_hub(
    *,
    workspace_dir: Path,
    bundle_url: str,
    version: str = "",
    enable: bool = False,
    target_name: str | None = None,
    cancel_checker: Any | None = None,
) -> HubInstallResult:
    with _with_cancel_checker(cancel_checker):
        payload = await _prepare_install_payload(
            bundle_url,
            version,
            target_name,
        )
        _ensure_not_cancelled()
        skill_service = SkillService(workspace_dir)
        # SkillService writes to disk synchronously; off-load so the
        # event loop stays responsive during large file dumps.
        created = await asyncio.to_thread(
            skill_service.create_skill,
            name=payload.name,
            content=payload.content,
            references=payload.references,
            scripts=payload.scripts,
            extra_files=payload.extra_files,
            installed_from=payload.installed_from,
        )
        if not created:
            raise SkillConflictError(_build_hub_conflict(payload.name))

        _ensure_not_cancelled()
        enabled = False
        if enable:
            enable_result = await asyncio.to_thread(
                skill_service.enable_skill,
                created,
            )
            enabled = bool(enable_result.get("success", False))
            if not enabled:
                logger.warning(
                    "Skill '%s' imported but enable failed",
                    created,
                )

        return HubInstallResult(
            name=created,
            enabled=enabled,
            source_url=payload.source_url,
            installed_from=payload.installed_from,
        )


async def import_pool_skill_from_hub(
    *,
    bundle_url: str,
    version: str = "",
    target_name: str | None = None,
    cancel_checker: Any | None = None,
) -> HubInstallResult:
    with _with_cancel_checker(cancel_checker):
        payload = await _prepare_install_payload(
            bundle_url,
            version,
            target_name,
        )
        _ensure_not_cancelled()
        pool_service = SkillPoolService()
        created = await asyncio.to_thread(
            pool_service.create_skill,
            name=payload.name,
            content=payload.content,
            references=payload.references,
            scripts=payload.scripts,
            extra_files=payload.extra_files,
            installed_from=payload.installed_from,
        )
        if not created:
            raise SkillConflictError(_build_hub_conflict(payload.name))

        return HubInstallResult(
            name=created,
            enabled=False,
            source_url=payload.source_url,
            installed_from=payload.installed_from,
        )
