# -*- coding: utf-8 -*-
"""Skills hub client and install helpers."""
from __future__ import annotations

import json
import logging
import os
import re
import time
import base64
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urlparse, unquote
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import frontmatter

from .skills_manager import SkillService

logger = logging.getLogger(__name__)


@dataclass
class HubSkillResult:
    slug: str
    name: str
    description: str = ""
    version: str = ""
    source_url: str = ""


@dataclass
class HubInstallResult:
    name: str
    enabled: bool
    source_url: str


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


def _hub_http_timeout() -> float:
    raw = os.environ.get("COPAW_SKILLS_HUB_HTTP_TIMEOUT", "15")
    try:
        return max(3.0, float(raw))
    except Exception:
        return 15.0


def _hub_http_retries() -> int:
    raw = os.environ.get("COPAW_SKILLS_HUB_HTTP_RETRIES", "3")
    try:
        return max(0, int(raw))
    except Exception:
        return 3


def _hub_http_backoff_base() -> float:
    raw = os.environ.get("COPAW_SKILLS_HUB_HTTP_BACKOFF_BASE", "0.8")
    try:
        return max(0.1, float(raw))
    except Exception:
        return 0.8


def _hub_http_backoff_cap() -> float:
    raw = os.environ.get("COPAW_SKILLS_HUB_HTTP_BACKOFF_CAP", "6")
    try:
        return max(0.5, float(raw))
    except Exception:
        return 6.0


def _compute_backoff_seconds(attempt: int) -> float:
    base = _hub_http_backoff_base()
    cap = _hub_http_backoff_cap()
    return min(cap, base * (2 ** max(0, attempt - 1)))


def _hub_base_url() -> str:
    return os.environ.get("COPAW_SKILLS_HUB_BASE_URL", "https://clawhub.ai")


def _hub_search_path() -> str:
    return os.environ.get(
        "COPAW_SKILLS_HUB_SEARCH_PATH",
        "/api/v1/search",
    )


def _hub_version_path() -> str:
    return os.environ.get(
        "COPAW_SKILLS_HUB_VERSION_PATH",
        "/api/v1/skills/{slug}/versions/{version}",
    )


def _hub_detail_path() -> str:
    return os.environ.get(
        "COPAW_SKILLS_HUB_DETAIL_PATH",
        "/api/v1/skills/{slug}",
    )


def _hub_file_path() -> str:
    return os.environ.get(
        "COPAW_SKILLS_HUB_FILE_PATH",
        "/api/v1/skills/{slug}/file",
    )


def _join_url(base: str, path: str) -> str:
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


# pylint: disable-next=too-many-branches,too-many-statements
def _http_get(
    url: str,
    params: dict[str, Any] | None = None,
    accept: str = "application/json",
) -> str:
    full_url = url
    if params:
        full_url = f"{url}?{urlencode(params)}"
    req = Request(
        full_url,
        headers={
            "Accept": accept,
            "User-Agent": "copaw-skills-hub/1.0",
        },
    )
    parsed = urlparse(full_url)
    host = (parsed.netloc or "").lower()
    github_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if github_token and "api.github.com" in host:
        req.add_header("Authorization", f"Bearer {github_token}")
    retries = _hub_http_retries()
    timeout = _hub_http_timeout()
    attempts = retries + 1
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except HTTPError as e:
            last_error = e
            status = getattr(e, "code", 0) or 0
            if status == 403 and "api.github.com" in host:
                body = ""
                try:
                    body = e.read().decode("utf-8", errors="ignore")
                except Exception:
                    body = ""
                if (
                    "rate limit" in body.lower()
                    or "rate limit" in str(e).lower()
                ):
                    raise RuntimeError(
                        "GitHub API rate limit exceeded while fetching "
                        "skills.sh skill files. Set GITHUB_TOKEN "
                        "(or GH_TOKEN) to increase the limit, then retry.",
                    ) from e
            # Retry only temporary/rate-limit server failures.
            if attempt < attempts and status in RETRYABLE_HTTP_STATUS:
                delay = _compute_backoff_seconds(attempt)
                logger.warning(
                    "Hub HTTP %s on %s (attempt %d/%d), retrying in %.2fs",
                    status,
                    full_url,
                    attempt,
                    attempts,
                    delay,
                )
                time.sleep(delay)
                continue
            raise
        except URLError as e:
            last_error = e
            if attempt < attempts:
                delay = _compute_backoff_seconds(attempt)
                logger.warning(
                    "Hub URL error on %s (attempt %d/%d), "
                    "retrying in %.2fs: %s",
                    full_url,
                    attempt,
                    attempts,
                    delay,
                    e,
                )
                time.sleep(delay)
                continue
            raise
        except TimeoutError as e:
            last_error = e
            if attempt < attempts:
                delay = _compute_backoff_seconds(attempt)
                logger.warning(
                    "Hub timeout on %s (attempt %d/%d), retrying in %.2fs",
                    full_url,
                    attempt,
                    attempts,
                    delay,
                )
                time.sleep(delay)
                continue
            raise
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Failed to request hub URL: {full_url}")


def _http_json_get(url: str, params: dict[str, Any] | None = None) -> Any:
    body = _http_get(url, params=params, accept="application/json")
    return json.loads(body)


def _http_text_get(url: str, params: dict[str, Any] | None = None) -> str:
    return _http_get(
        url,
        params=params,
        accept="text/plain, text/markdown, */*",
    )


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


# pylint: disable-next=too-many-return-statements,too-many-branches
def _hydrate_clawhub_payload(
    data: Any,
    *,
    slug: str,
    requested_version: str,
) -> Any:
    """
    Convert ClawHub metadata responses into
    bundle-like payload with file contents.
    """
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
        version_data = _http_json_get(version_url)
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
            files[path] = _http_text_get(file_url, params=params)
        except Exception as e:
            logger.warning("Failed to fetch hub file %s: %s", path, e)

    if not files.get("SKILL.md"):
        return data

    return {
        "name": skill.get("displayName") or skill_slug,
        "files": files,
    }


# pylint: disable-next=too-many-branches
def _normalize_bundle(
    data: Any,
) -> tuple[str, str, dict[str, Any], dict[str, Any], dict[str, Any]]:
    payload = data
    if isinstance(data, dict) and isinstance(data.get("skill"), dict):
        payload = data["skill"]
    if not isinstance(payload, dict):
        raise ValueError("Hub bundle is not a valid JSON object")

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
        raise ValueError("Hub bundle missing SKILL.md content")

    name = payload.get("name", "")
    if not isinstance(name, str):
        name = ""
    if not name:
        try:
            post = frontmatter.loads(content)
            name = post.get("name", "")
        except Exception:
            name = ""
    if not name:
        raise ValueError("Hub bundle missing skill name")

    return name, content, references, scripts, extra_files


def _safe_fallback_name(raw: str) -> str:
    out = re.sub(r"[^a-zA-Z0-9_-]", "-", raw).strip("-_")
    return out or "imported-skill"


def _is_http_url(text: str) -> bool:
    parsed = urlparse(text.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


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


def _extract_github_spec(
    url: str,
) -> tuple[str, str, str, str] | None:
    """
    Parse GitHub repo/tree/blob URL into (owner, repo, branch, path_hint).
    """
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


def _github_repo_exists(owner: str, repo: str) -> bool:
    if not owner or not repo:
        return False
    try:
        data = _http_json_get(_github_api_url(owner, repo, ""))
        return isinstance(data, dict) and data.get("full_name") is not None
    except Exception:
        return False


# pylint: disable-next=too-many-return-statements,too-many-branches
def _extract_skillsmp_spec(
    url: str,
) -> tuple[str, str, str] | None:
    """
    Parse SkillsMP URL slug into (owner, repo, skill_hint).

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
        if not _github_repo_exists(owner, repo):
            continue
        remainder = tail_tokens[i:]
        skill_hint = "-".join(remainder).strip() if remainder else ""
        return owner, repo, skill_hint

    # Conservative fallback when repo existence checks fail
    repo = tail_tokens[0]
    skill_hint = "-".join(tail_tokens[1:]).strip()
    return owner, repo, skill_hint


def _resolve_clawhub_slug(bundle_url: str) -> str:
    from_url = _extract_clawhub_slug_from_url(bundle_url)
    if from_url:
        return from_url
    return ""


def _github_api_url(owner: str, repo: str, suffix: str) -> str:
    base = f"https://api.github.com/repos/{owner}/{repo}"
    cleaned = suffix.lstrip("/")
    return f"{base}/{cleaned}" if cleaned else base


def _github_get_default_branch(owner: str, repo: str) -> str:
    repo_meta = _http_json_get(_github_api_url(owner, repo, ""))
    if isinstance(repo_meta, dict):
        branch = repo_meta.get("default_branch")
        if isinstance(branch, str) and branch.strip():
            return branch.strip()
    return "main"


def _normalize_skill_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _github_list_skill_md_roots(
    owner: str,
    repo: str,
    ref: str,
) -> list[str]:
    tree_url = _github_api_url(owner, repo, f"git/trees/{ref}")
    try:
        data = _http_json_get(tree_url, {"recursive": "1"})
    except HTTPError as e:
        if getattr(e, "code", 0) == 404:
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


def _github_get_content_entry(
    owner: str,
    repo: str,
    path: str,
    ref: str,
) -> dict[str, Any]:
    content_url = _github_api_url(owner, repo, f"contents/{path}")
    data = _http_json_get(content_url, {"ref": ref})
    if not isinstance(data, dict):
        raise ValueError(f"Unexpected GitHub response for path: {path}")
    return data


def _github_get_dir_entries(
    owner: str,
    repo: str,
    path: str,
    ref: str,
) -> list[dict[str, Any]]:
    content_url = _github_api_url(owner, repo, f"contents/{path}")
    data = _http_json_get(content_url, {"ref": ref})
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    return []


def _github_read_file(entry: dict[str, Any]) -> str:
    download_url = entry.get("download_url")
    if isinstance(download_url, str) and download_url:
        return _http_text_get(download_url)

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

    raise ValueError("Unable to read file content from GitHub entry")


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


def _github_collect_tree_files(
    owner: str,
    repo: str,
    ref: str,
    root: str,
    subdir: str,
    max_files: int = 200,
) -> dict[str, str]:
    files: dict[str, str] = {}
    pending = [_join_repo_path(root, subdir)]
    visited = 0
    while pending:
        current_dir = pending.pop()
        entries = _github_get_dir_entries(owner, repo, current_dir, ref)
        for entry in entries:
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
            if not (
                rel.startswith("references/") or rel.startswith("scripts/")
            ):
                continue
            files[rel] = _github_read_file(entry)
            visited += 1
            if visited >= max_files:
                logger.warning(
                    "Hub file collection capped at %d files",
                    max_files,
                )
                return files
    return files


# pylint: disable-next=too-many-branches,too-many-statements
def _fetch_bundle_from_skills_sh_url(
    bundle_url: str,
    requested_version: str,
) -> tuple[Any, str]:
    spec = _extract_skills_sh_spec(bundle_url)
    if spec is None:
        raise ValueError("Invalid skills.sh URL format")
    owner, repo, skill = spec
    if requested_version.strip():
        branch_candidates = [requested_version.strip()]
    else:
        # Prefer repo default branch (e.g. master).
        default_branch = _github_get_default_branch(owner, repo)
        branch_candidates = [default_branch] if default_branch else []
        for b in ("main", "master"):
            if b and b not in branch_candidates:
                branch_candidates.append(b)

    selected_root = ""
    skill_md_entry: dict[str, Any] | None = None
    branch = branch_candidates[0]
    for candidate_branch in branch_candidates:
        branch = candidate_branch
        roots = [
            _join_repo_path("skills", skill),
            skill,
            "",
        ]
        for root in roots:
            skill_md_path = _join_repo_path(root, "SKILL.md")
            try:
                entry = _github_get_content_entry(
                    owner,
                    repo,
                    skill_md_path,
                    branch,
                )
            except HTTPError as e:
                if getattr(e, "code", 0) == 404:
                    continue
                raise
            if str(entry.get("type") or "") == "file":
                selected_root = root
                skill_md_entry = entry
                break
        if skill_md_entry is not None:
            break

    if skill_md_entry is None:
        # Fallback: discover skill roots from repo tree and fuzzy-match.
        skill_norm = _normalize_skill_key(skill)
        for candidate_branch in branch_candidates:
            branch = candidate_branch
            for root in _github_list_skill_md_roots(owner, repo, branch):
                leaf = root.split("/")[-1] if root else root
                leaf_norm = _normalize_skill_key(leaf)
                if not leaf_norm:
                    continue
                if (
                    leaf_norm == skill_norm
                    or leaf_norm in skill_norm
                    or skill_norm in leaf_norm
                    or skill_norm.endswith(f"-{leaf_norm}")
                ):
                    selected_root = root
                    skill_md_path = _join_repo_path(root, "SKILL.md")
                    try:
                        entry = _github_get_content_entry(
                            owner,
                            repo,
                            skill_md_path,
                            branch,
                        )
                    except HTTPError:
                        continue
                    if str(entry.get("type") or "") == "file":
                        skill_md_entry = entry
                        break
            if skill_md_entry is not None:
                break

    if skill_md_entry is None:
        raise ValueError(
            "Could not find SKILL.md from skills.sh source. "
            "This skill may not expose SKILL.md in the repository.",
        )

    files: dict[str, str] = {"SKILL.md": _github_read_file(skill_md_entry)}
    for subdir in ("references", "scripts"):
        try:
            files.update(
                _github_collect_tree_files(
                    owner=owner,
                    repo=repo,
                    ref=branch,
                    root=selected_root,
                    subdir=subdir,
                ),
            )
        except HTTPError as e:
            if getattr(e, "code", 0) != 404:
                raise

    source_url = f"https://github.com/{owner}/{repo}"
    return {"name": skill, "files": files}, source_url


# pylint: disable-next=too-many-branches,too-many-statements
def _fetch_bundle_from_repo_and_skill_hint(
    *,
    owner: str,
    repo: str,
    skill_hint: str,
    requested_version: str,
    default_branch: str = "main",
) -> tuple[Any, str]:
    branch_candidates = (
        [requested_version.strip()]
        if requested_version.strip()
        else ["main", "master"]
    )
    if default_branch and default_branch not in branch_candidates:
        branch_candidates.append(default_branch)
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
                entry = _github_get_content_entry(
                    owner,
                    repo,
                    skill_md_path,
                    branch,
                )
            except HTTPError as e:
                if getattr(e, "code", 0) == 404:
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
            for root in _github_list_skill_md_roots(owner, repo, branch):
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
                        entry = _github_get_content_entry(
                            owner,
                            repo,
                            skill_md_path,
                            branch,
                        )
                    except HTTPError:
                        continue
                    if str(entry.get("type") or "") == "file":
                        skill_md_entry = entry
                        break
            if skill_md_entry is not None:
                break

    if skill_md_entry is None:
        raise ValueError(
            f"Could not find SKILL.md in source repository "
            f"https://github.com/{owner}/{repo}. "
            f"Path hint: {skill_hint!r}; tried branches: {branch_candidates}. "
            "Ensure the URL points to a folder containing SKILL.md, e.g. "
            "https://github.com/owner/repo/tree/master/skills/skill-name",
        )

    files: dict[str, str] = {"SKILL.md": _github_read_file(skill_md_entry)}
    for subdir in ("references", "scripts"):
        try:
            files.update(
                _github_collect_tree_files(
                    owner=owner,
                    repo=repo,
                    ref=branch,
                    root=selected_root,
                    subdir=subdir,
                ),
            )
        except HTTPError as e:
            if getattr(e, "code", 0) != 404:
                raise
    source_url = f"https://github.com/{owner}/{repo}"
    skill_name = skill.split("/")[-1].strip() if skill else repo
    return {"name": skill_name or repo, "files": files}, source_url


def _fetch_bundle_from_github_url(
    bundle_url: str,
    requested_version: str,
) -> tuple[Any, str]:
    spec = _extract_github_spec(bundle_url)
    if spec is None:
        raise ValueError(
            "Invalid GitHub URL format. Use a repo or path URL, e.g. "
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
        default_branch = _github_get_default_branch(owner, repo)
    except Exception:
        pass
    return _fetch_bundle_from_repo_and_skill_hint(
        owner=owner,
        repo=repo,
        skill_hint=path_hint,
        requested_version=branch,
        default_branch=default_branch or "main",
    )


def _fetch_bundle_from_skillsmp_url(
    bundle_url: str,
    requested_version: str,
) -> tuple[Any, str]:
    spec = _extract_skillsmp_spec(bundle_url)
    if spec is None:
        raise ValueError("Invalid skillsmp URL format")
    owner, repo, skill_hint = spec
    return _fetch_bundle_from_repo_and_skill_hint(
        owner=owner,
        repo=repo,
        skill_hint=skill_hint,
        requested_version=requested_version,
    )


def _fetch_bundle_from_clawhub_slug(
    slug: str,
    version: str,
) -> tuple[Any, str]:
    if not slug:
        raise ValueError("slug is required for clawhub install")
    base = _hub_base_url()
    errors: list[str] = []
    candidates = [
        _join_url(base, _hub_detail_path().format(slug=slug)),
    ]
    data: Any | None = None
    source_url = ""
    for candidate in candidates:
        try:
            data = _http_json_get(candidate)
            source_url = candidate
            break
        except Exception as e:
            errors.append(f"{candidate}: {e}")
    if data is None:
        raise RuntimeError(
            "Unable to fetch skill from hub endpoints: " + "; ".join(errors),
        )
    return (
        _hydrate_clawhub_payload(
            data,
            slug=slug,
            requested_version=version,
        ),
        source_url,
    )


def search_hub_skills(query: str, limit: int = 20) -> list[HubSkillResult]:
    base = _hub_base_url()
    search_url = _join_url(base, _hub_search_path())
    data = _http_json_get(search_url, {"q": query, "limit": limit})
    items = _norm_search_items(data)
    results: list[HubSkillResult] = []
    for item in items:
        slug = str(item.get("slug") or item.get("name") or "").strip()
        if not slug:
            continue
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
            ),
        )
    return results


# pylint: disable-next=too-many-branches
def install_skill_from_hub(
    *,
    bundle_url: str,
    version: str = "",
    enable: bool = True,
    overwrite: bool = False,
) -> HubInstallResult:
    source_url = bundle_url
    data: Any

    if not bundle_url or not _is_http_url(bundle_url):
        raise ValueError("bundle_url must be a valid http(s) URL")

    skills_spec = _extract_skills_sh_spec(bundle_url)
    if skills_spec is not None:
        data, source_url = _fetch_bundle_from_skills_sh_url(
            bundle_url,
            requested_version=version,
        )
    else:
        github_spec = _extract_github_spec(bundle_url)
        if github_spec is not None:
            data, source_url = _fetch_bundle_from_github_url(
                bundle_url,
                requested_version=version,
            )
        else:
            skillsmp_slug = _extract_skillsmp_slug(bundle_url)
            if skillsmp_slug:
                data, source_url = _fetch_bundle_from_skillsmp_url(
                    bundle_url,
                    requested_version=version,
                )
            else:
                clawhub_slug = _resolve_clawhub_slug(bundle_url)
                if clawhub_slug:
                    data, source_url = _fetch_bundle_from_clawhub_slug(
                        clawhub_slug,
                        version,
                    )
                else:
                    # Backward-compatible fallback for direct bundle JSON URLs
                    data = _http_json_get(bundle_url)

    name, content, references, scripts, extra_files = _normalize_bundle(data)
    if not name:
        fallback = urlparse(bundle_url).path.strip("/").split("/")[-1]
        name = _safe_fallback_name(fallback)

    created = SkillService.create_skill(
        name=name,
        content=content,
        overwrite=overwrite,
        references=references,
        scripts=scripts,
        extra_files=extra_files,
    )
    if not created:
        raise RuntimeError(
            f"Failed to create skill '{name}'. "
            "Try overwrite=true if it already exists.",
        )

    enabled = False
    if enable:
        enabled = SkillService.enable_skill(name, force=True)
        if not enabled:
            logger.warning("Skill '%s' imported but enable failed", name)

    return HubInstallResult(
        name=name,
        enabled=enabled,
        source_url=source_url,
    )
