# -*- coding: utf-8 -*-
"""Read external memory and plugin sources without installing caches."""

from __future__ import annotations

import json
from heapq import nlargest
import sqlite3
import tomllib
from pathlib import Path
from typing import Any

from ..codex_plugin_adapter import ADAPTER as CODEX_PLUGIN_ADAPTER
from ..models import (
    SourceMCPServer,
    SourceMarketplace,
    SourceMemoryFile,
    SourceMemoryProject,
    SourcePlugin,
    SourceSkill,
)
from ..qoder_plugin_adapter import discover_qoder_custom_skill_adapter
from ..skill_transfer import read_bounded_tree, read_regular_file
from ._utils import find_nested_value

_CODEX_BUILTIN_MARKETPLACES = {
    "openai-bundled",
    "openai-curated",
    "openai-curated-remote",
    "openai-primary-runtime",
}
_CWD_KEYS = ("cwd", "directory", "project_path", "projectPath")
_MAX_TRANSCRIPT_PROBE_BYTES = 1024 * 1024
_MAX_CONFIG_BYTES = 4 * 1024 * 1024
_CODEX_CURATED_MEMORY_FILES = ("MEMORY.md", "memory_summary.md")
_CODEX_INTERNAL_MEMORY_FILES = (
    "raw_memories.md",
    "phase2_workspace_diff.md",
)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(read_regular_file(path, max_bytes=_MAX_CONFIG_BYTES))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return None


def _markdown_files(root: Path) -> list[SourceMemoryFile]:
    files: list[SourceMemoryFile] = []
    if not root.is_dir() or root.is_symlink():
        return files
    resolved_root = root.resolve()
    try:
        for entry in read_bounded_tree(
            root,
            reject_unsafe=False,
            read_data=False,
        ):
            if entry.is_dir or entry.relative.suffix.lower() != ".md":
                continue
            resolved = (resolved_root / entry.relative).resolve(strict=True)
            files.append(
                SourceMemoryFile(
                    source_path=resolved,
                    relative_path=entry.relative,
                ),
            )
    except (OSError, ValueError):
        pass
    return sorted(files, key=lambda item: str(item.relative_path))


def _codex_stage1_count(codex_home: Path) -> int:
    database = codex_home / "memories_1.sqlite"
    if database.is_symlink() or not database.is_file():
        return 0
    try:
        uri = f"{database.resolve().as_uri()}?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=2.0) as connection:
            value = connection.execute(
                "SELECT COUNT(*) FROM stage1_outputs WHERE "
                "length(trim(raw_memory)) > 0 OR "
                "length(trim(rollout_summary)) > 0",
            ).fetchone()
    except sqlite3.Error:
        return 0
    return int(value[0]) if value else 0


def codex_memory_status(codex_home: Path) -> dict[str, Any]:
    """Classify Codex memory without treating pipeline artifacts as memory."""
    codex_home = codex_home.expanduser()
    root = codex_home / "memories"
    curated = [
        name
        for name in _CODEX_CURATED_MEMORY_FILES
        if not (root / name).is_symlink() and (root / name).is_file()
    ]
    notes_root = root / "extensions" / "ad_hoc" / "notes"
    note_count = len(_markdown_files(notes_root))
    internal = [
        name
        for name in _CODEX_INTERNAL_MEMORY_FILES
        if not (root / name).is_symlink() and (root / name).is_file()
    ]
    stage1_count = _codex_stage1_count(codex_home)
    if curated:
        state = (
            "consolidated_with_internal_residue"
            if internal
            else "consolidated"
        )
    elif "phase2_workspace_diff.md" in internal:
        state = "consolidation_incomplete"
    elif note_count:
        state = "pending_ad_hoc"
    elif stage1_count:
        state = "phase1_only"
    elif internal:
        state = "consolidation_incomplete"
    else:
        state = "empty"
    return {
        "state": state,
        "curated_files": curated,
        "ad_hoc_note_count": note_count,
        "stage1_output_count": stage1_count,
        "ignored_internal_files": internal,
    }


# pylint: disable-next=too-many-branches
def discover_codex_memory(codex_home: Path) -> list[SourceMemoryProject]:
    """Discover only curated Codex memory and safe scoped source resources."""
    codex_home = codex_home.expanduser()
    memories_root = codex_home / "memories"
    projects: list[SourceMemoryProject] = []
    if not memories_root.is_dir():
        return projects

    status = codex_memory_status(codex_home)
    global_files: list[SourceMemoryFile] = []
    for name in _CODEX_CURATED_MEMORY_FILES:
        path = memories_root / name
        if path.is_symlink() or not path.is_file():
            continue
        global_files.append(
            SourceMemoryFile(
                source_path=path.resolve(),
                relative_path=Path(path.name),
            ),
        )
    if global_files:
        projects.append(
            SourceMemoryProject(
                source_id="codex:global",
                project_key="global",
                files=global_files,
                metadata={
                    "layout": "codex_global_memory",
                    "memory_state": status["state"],
                    "ignored_internal_files": status["ignored_internal_files"],
                },
            ),
        )

    # Avoid duplicating notes after Codex has consolidated them.
    if not global_files:
        notes_root = memories_root / "extensions" / "ad_hoc" / "notes"
        note_files = _markdown_files(notes_root)
        if note_files:
            projects.append(
                SourceMemoryProject(
                    source_id="codex:ad-hoc",
                    project_key="ad-hoc-notes",
                    files=note_files,
                    metadata={
                        "layout": "codex_ad_hoc_notes",
                        "memory_state": status["state"],
                    },
                ),
            )

    extensions_root = memories_root / "extensions"
    if not extensions_root.is_dir():
        return projects
    for extension in sorted(extensions_root.iterdir()):
        resources = extension / "resources"
        if extension.is_symlink() or not resources.is_dir():
            continue
        for project_root in sorted(resources.iterdir()):
            if project_root.is_symlink() or not project_root.is_dir():
                continue
            files = _markdown_files(project_root)
            if not files:
                continue
            scope = _read_json(project_root / "scope.json")
            cwd = ""
            if isinstance(scope, dict):
                cwd = str(scope.get("cwd") or "")
            source_id = f"codex:extension:{extension.name}:"
            source_id += project_root.name
            projects.append(
                SourceMemoryProject(
                    source_id=source_id,
                    project_key=f"{extension.name}-{project_root.name}",
                    cwd=cwd,
                    files=files,
                    metadata={
                        "layout": "codex_extension_resource",
                        "extension": extension.name,
                        "source_project_key": project_root.name,
                    },
                ),
            )
    return projects


def _absolute_cwd(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    path = Path(value).expanduser()
    return str(path) if path.is_absolute() else ""


def _cwd_in_value(value: Any) -> str:
    return find_nested_value(value, _CWD_KEYS, _absolute_cwd)


def _project_cwd_from_transcripts(project_root: Path) -> str:
    try:
        candidates = nlargest(
            20,
            (
                project_root / entry.relative
                for entry in read_bounded_tree(
                    project_root,
                    reject_unsafe=False,
                    read_data=False,
                )
                if not entry.is_dir and entry.relative.suffix == ".jsonl"
            ),
            key=lambda path: path.stat().st_mtime,
        )
    except (OSError, ValueError):
        return ""
    for path in candidates:
        if path.is_symlink() or not path.is_file():
            continue
        consumed = 0
        try:
            with path.open(encoding="utf-8", errors="replace") as stream:
                for line in stream:
                    consumed += len(line.encode("utf-8", errors="replace"))
                    if consumed > _MAX_TRANSCRIPT_PROBE_BYTES:
                        break
                    try:
                        value = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    cwd = _cwd_in_value(value)
                    if cwd:
                        return cwd
        except OSError:
            continue
    return ""


def discover_project_memory(agent_home: Path) -> list[SourceMemoryProject]:
    """Discover Qoder/Claude-style ``projects/*/memory/**/*.md`` stores."""
    projects_root = agent_home.expanduser() / "projects"
    projects: list[SourceMemoryProject] = []
    if not projects_root.is_dir():
        return projects
    for project_root in sorted(projects_root.iterdir()):
        if project_root.is_symlink() or not project_root.is_dir():
            continue
        files = _markdown_files(project_root / "memory")
        if not files:
            continue
        projects.append(
            SourceMemoryProject(
                source_id=f"project-memory:{project_root.name}",
                project_key=project_root.name,
                cwd=_project_cwd_from_transcripts(project_root),
                files=files,
                metadata={"layout": "project_memory"},
            ),
        )
    return projects


def _qoder_project_cwds(qoder_home: Path) -> dict[str, str]:
    """Map Qoder's encoded project keys back to transcript CWDs."""
    projects_root = qoder_home.expanduser() / "projects"
    mapping: dict[str, str] = {}
    if not projects_root.is_dir() or projects_root.is_symlink():
        return mapping
    try:
        project_roots = sorted(projects_root.iterdir())
    except OSError:
        return mapping
    for project_root in project_roots:
        if project_root.is_symlink() or not project_root.is_dir():
            continue
        cwd = _project_cwd_from_transcripts(project_root)
        if not cwd:
            continue
        encoded = cwd.lstrip("/\\").replace("/", "-").replace("\\", "-")
        mapping[encoded] = cwd
    return mapping


def _match_qoder_path(base: Path, encoded: str, depth: int = 0) -> str:
    """Resolve an encoded Qoder project key without guessing hyphen splits."""
    if not encoded or depth > 32 or not base.is_dir():
        return str(base) if not encoded else ""
    try:
        children = [
            child
            for child in base.iterdir()
            if child.is_dir() and not child.is_symlink()
        ]
    except OSError:
        return ""
    children.sort(key=lambda item: len(item.name), reverse=True)
    for child in children:
        if encoded == child.name:
            return str(child.resolve())
        prefix = f"{child.name}-"
        if encoded.startswith(prefix):
            remainder = encoded.removeprefix(prefix)
            resolved = _match_qoder_path(
                child,
                remainder,
                depth + 1,
            )
            if resolved:
                return resolved
    return ""


def _qoder_memory_cwd(project_key: str, cwd_map: dict[str, str]) -> str:
    cwd = cwd_map.get(project_key, "")
    if cwd:
        return cwd
    home = Path.home().resolve()
    home_key = str(home).lstrip("/\\").replace("/", "-").replace("\\", "-")
    if project_key == home_key:
        return str(home)
    prefix = f"{home_key}-"
    if not project_key.startswith(prefix):
        return ""
    remainder = project_key.removeprefix(prefix)
    return _match_qoder_path(home, remainder)


def discover_qoder_memory(qoder_home: Path) -> list[SourceMemoryProject]:
    """Discover current ``memories/<account>/{global,projects}`` stores."""
    qoder_home = qoder_home.expanduser()
    memories_root = qoder_home / "memories"
    if not memories_root.is_dir() or memories_root.is_symlink():
        return discover_project_memory(qoder_home)
    cwd_map = _qoder_project_cwds(qoder_home)
    projects: list[SourceMemoryProject] = []
    try:
        accounts = sorted(memories_root.iterdir())
    except OSError:
        return projects
    for account in accounts:
        if account.is_symlink() or not account.is_dir():
            continue
        global_files = _markdown_files(account / "global")
        if global_files:
            projects.append(
                SourceMemoryProject(
                    source_id=f"qoder-memory:{account.name}:global",
                    project_key=f"{account.name}-global",
                    files=global_files,
                    metadata={
                        "layout": "qoder_memory_v2",
                        "scope": "global",
                        "account": account.name,
                    },
                ),
            )
        scoped_root = account / "projects"
        if not scoped_root.is_dir() or scoped_root.is_symlink():
            continue
        try:
            scoped_projects = sorted(scoped_root.iterdir())
        except OSError:
            continue
        for source in scoped_projects:
            if source.is_symlink() or not source.is_dir():
                continue
            files = _markdown_files(source)
            if not files:
                continue
            source_id = f"qoder-memory:{account.name}:project:"
            source_id += source.name
            projects.append(
                SourceMemoryProject(
                    source_id=source_id,
                    project_key=f"{account.name}-{source.name}",
                    cwd=_qoder_memory_cwd(source.name, cwd_map),
                    files=files,
                    metadata={
                        "layout": "qoder_memory_v2",
                        "scope": "project",
                        "account": account.name,
                        "source_project_key": source.name,
                    },
                ),
            )
    projects.extend(discover_project_memory(qoder_home))
    return projects


def _skill_directories(root: Path) -> list[Path]:
    if not root.is_dir() or root.is_symlink():
        return []
    if (root / "SKILL.md").is_file():
        return [root]
    try:
        children = sorted(root.iterdir())
    except OSError:
        return []
    skill_dirs = []
    for child in children:
        if child.is_dir() and not child.is_symlink():
            if (child / "SKILL.md").is_file():
                skill_dirs.append(child)
    return skill_dirs


def discover_qoder_skills(qoder_home: Path) -> list[SourceSkill]:
    """Discover standalone global/project Skills, excluding plugin caches."""
    qoder_home = qoder_home.expanduser()
    roots: list[tuple[Path, str]] = [(qoder_home / "skills", "user")]
    for cwd in sorted(set(_qoder_project_cwds(qoder_home).values())):
        roots.append((Path(cwd) / ".qoder" / "skills", "project"))
    skills: list[SourceSkill] = []
    seen: set[Path] = set()
    for root, scope in roots:
        for directory in _skill_directories(root):
            try:
                resolved = directory.resolve(strict=True)
            except OSError:
                continue
            if resolved in seen:
                continue
            seen.add(resolved)
            skills.append(
                SourceSkill(
                    source_id=f"qoder-skill:{scope}:{resolved}",
                    name=directory.name,
                    directory=resolved,
                ),
            )
    return skills


def _credential_placeholders(values: Any) -> dict[str, str]:
    if not isinstance(values, dict):
        return {}
    placeholders: dict[str, str] = {}
    for key in values:
        name = str(key)
        safe_name = "".join(
            character if character.isalnum() else "_" for character in name
        ).upper()
        placeholders[name] = f"${{{safe_name or 'VALUE'}}}"
    return placeholders


# pylint: disable-next=too-many-locals
def _qoder_mcp_servers(
    records: Any,
    *,
    source_prefix: str,
    source_manifest: str,
    harness: str = "Qoder",
) -> tuple[list[SourceMCPServer], list[str], int]:
    """Normalize one external MCP manifest through the shared pipeline."""
    if not isinstance(records, dict):
        return [], [], 0
    servers: list[SourceMCPServer] = []
    warnings: list[str] = []
    for name, raw in sorted(records.items()):
        if not isinstance(raw, dict):
            warnings.append(
                f"{harness} MCP {name!r} has an invalid configuration.",
            )
            continue
        command = str(raw.get("command") or "")
        url = str(raw.get("url") or "")
        raw_type = str(raw.get("type") or raw.get("transport") or "")
        if command:
            transport = "stdio"
        elif raw_type in {"sse"}:
            transport = "sse"
        elif url:
            transport = "streamable_http"
        else:
            warning = f"{harness} MCP {name!r} has neither a command nor URL"
            warnings.append(
                f"{warning} and was skipped.",
            )
            continue
        args = raw.get("args")
        if not isinstance(args, list):
            args = []
        env = _credential_placeholders(raw.get("env"))
        for variable in raw.get("env_vars") or []:
            name_value = str(variable)
            if name_value:
                env.setdefault(name_value, f"${{{name_value}}}")
        headers = _credential_placeholders(raw.get("headers"))
        for header, variable in dict(
            raw.get("env_http_headers") or {},
        ).items():
            name_value = str(variable)
            if name_value:
                headers.setdefault(str(header), f"${{{name_value}}}")
        credentials_removed = bool(env or headers)
        runtime_bound = ".qoder/plugins/cache" in command.replace("\\", "/")
        servers.append(
            SourceMCPServer(
                source_id=f"{source_prefix}:{name}",
                name=str(name),
                transport=transport,
                enabled=bool(
                    raw.get("enabled", not raw.get("disabled", False)),
                ),
                command=command,
                args=[str(item) for item in args],
                env=env,
                cwd=str(raw.get("cwd") or ""),
                url=url,
                headers=headers,
                auth_status="reauthorize" if credentials_removed else "",
                metadata={
                    "source_manifest": source_manifest,
                    "credentials_removed": credentials_removed,
                    "source_runtime_bound": runtime_bound,
                },
            ),
        )
    return servers, warnings, len(records)


def discover_qoder_mcp(
    qoder_home: Path,
) -> tuple[list[SourceMCPServer], list[str], int]:
    """Translate Qoder's standard user-level ``mcp.json`` safely."""
    config = _read_json(qoder_home.expanduser() / "mcp.json")
    records = config.get("mcpServers") if isinstance(config, dict) else None
    return _qoder_mcp_servers(
        records,
        source_prefix="qoder:mcp",
        source_manifest="qoder_mcp_json",
    )


def discover_qoder_plugin_mcp(
    plugins: list[SourcePlugin],
) -> tuple[list[SourceMCPServer], list[str], int]:
    """Discover standard MCP manifests owned by enabled Qoder plugins."""
    servers: list[SourceMCPServer] = []
    warnings: list[str] = []
    discovered = 0
    seen: set[str] = set()
    for plugin in plugins:
        source = str(
            plugin.metadata.get("install_path") or plugin.install_source or "",
        )
        if not source or source.startswith(("http://", "https://")):
            continue
        root = Path(source).expanduser()
        for filename in (".mcp.json", "mcp.json"):
            config = _read_json(root / filename)
            records = (
                config.get("mcpServers") if isinstance(config, dict) else None
            )
            found, found_warnings, count = _qoder_mcp_servers(
                records,
                source_prefix=f"qoder:plugin-mcp:{plugin.source_id}",
                source_manifest="qoder_plugin_mcp_json",
            )
            for server in found:
                server.metadata["source_plugin"] = plugin.source_id
                if server.source_id not in seen:
                    seen.add(server.source_id)
                    servers.append(server)
            warnings.extend(found_warnings)
            discovered += count
    return servers, warnings, discovered


def discover_codex_plugin_mcp(
    plugins: list[SourcePlugin],
) -> tuple[list[SourceMCPServer], list[str], int]:
    """Discover MCP definitions declared by staged Codex content plugins."""
    servers: list[SourceMCPServer] = []
    warnings: list[str] = []
    discovered = 0
    for plugin in plugins:
        source = str(plugin.metadata.get("install_path") or "")
        if not source:
            continue
        root = Path(source).expanduser()
        manifest = next(
            (
                value
                for value in (
                    _read_json(root / ".codex-plugin/plugin.json"),
                    _read_json(root / ".claude-plugin/plugin.json"),
                )
                if isinstance(value, dict)
            ),
            None,
        )
        if not isinstance(manifest, dict):
            continue
        declared = manifest.get("mcpServers")
        records: Any = declared if isinstance(declared, dict) else None
        if isinstance(declared, str):
            relative = Path(declared)
            if relative.is_absolute() or ".." in relative.parts:
                warnings.append(
                    f"Codex plugin {plugin.name!r} has an unsafe MCP path.",
                )
                continue
            config = _read_json(root / relative)
            records = (
                config.get("mcpServers") if isinstance(config, dict) else None
            )
        elif records is None:
            for filename in (".mcp.json", "mcp.json"):
                config = _read_json(root / filename)
                if isinstance(config, dict):
                    records = config.get("mcpServers")
                    if isinstance(records, dict):
                        break
        found, found_warnings, count = _qoder_mcp_servers(
            records,
            source_prefix=f"codex:plugin-mcp:{plugin.source_id}",
            source_manifest="codex_plugin_mcp_json",
            harness="Codex",
        )
        for server in found:
            server.metadata["source_plugin"] = plugin.source_id
            raw = records.get(server.name, {})
            cwd = str(raw.get("cwd") or ".")
            if server.transport == "stdio" and not Path(cwd).is_absolute():
                server.cwd = ""
                server.metadata["source_plugin_relative_cwd"] = cwd
            servers.append(server)
        warnings.extend(found_warnings)
        discovered += count
    return servers, warnings, discovered


def _marketplace_source(config: dict[str, Any], base: Path) -> tuple[str, str]:
    source_type = str(config.get("source_type") or config.get("type") or "")
    source = str(
        config.get("source") or config.get("path") or config.get("url") or "",
    ).strip()
    if source and source_type in {"directory", "local", "path"}:
        path = Path(source).expanduser()
        if not path.is_absolute():
            path = base / path
        source = str(path.resolve())
    return source_type or "unknown", source


def _marketplace_manifest(root: Path) -> Path | None:
    candidates = (
        root / ".codex-plugin" / "marketplace.json",
        root / ".qoder-plugin" / "marketplace.json",
        root / "marketplace.json",
    )
    return next((path for path in candidates if path.is_file()), None)


def _qwen_plugin_source(  # pylint: disable=too-many-return-statements
    root: Path,
    plugin_name: str,
) -> str:
    """Resolve only a Marketplace entry containing QwenPaw plugin.json."""
    manifest_path = _marketplace_manifest(root)
    if manifest_path is None:
        direct = root / plugin_name
        if (direct / "plugin.json").is_file():
            return str(direct.resolve())
        return ""
    manifest = _read_json(manifest_path)
    entries = manifest.get("plugins") if isinstance(manifest, dict) else None
    if not isinstance(entries, list):
        return ""
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("name") or entry.get("id") or "") != plugin_name:
            continue
        raw_source = entry.get("source")
        if isinstance(raw_source, dict):
            raw_source = (
                raw_source.get("path")
                or raw_source.get("url")
                or raw_source.get("source")
            )
        if not isinstance(raw_source, str) or not raw_source.strip():
            return ""
        if raw_source.startswith(("http://", "https://")):
            return raw_source if raw_source.lower().endswith(".zip") else ""
        source_path = Path(raw_source).expanduser()
        if not source_path.is_absolute():
            source_path = manifest_path.parent / source_path
        try:
            source_path = source_path.resolve()
        except OSError:
            return ""
        if (source_path / "plugin.json").is_file():
            return str(source_path)
        return ""
    return ""


def _cached_plugin_details(
    cache_root: Path,
    marketplace: str,
    name: str,
) -> tuple[str, str, Path | None, dict[str, Any]]:
    plugin_root = cache_root / marketplace / name
    manifests = [
        *plugin_root.glob("*/.codex-plugin/plugin.json"),
        *plugin_root.glob("*/.claude-plugin/plugin.json"),
    ]
    if not manifests:
        return "", "", None, {}
    manifests.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    manifest_path = manifests[0]
    manifest = _read_json(manifest_path)
    if not isinstance(manifest, dict):
        return "", "", None, {}
    source = manifest_path.parent.parent
    if source.is_symlink() or not source.is_dir():
        source = None
    interface = manifest.get("interface")
    display_name = manifest.get("displayName")
    if not isinstance(display_name, str) and isinstance(interface, dict):
        display_name = interface.get("displayName")
    return (
        str(manifest.get("version") or ""),
        display_name.strip() if isinstance(display_name, str) else "",
        source.resolve() if source is not None else None,
        manifest,
    )


def _codex_content_bundle(root: Path, manifest: dict[str, Any]) -> bool:
    """Return whether a Codex plugin has portable Skill/MCP components."""
    return bool(
        manifest.get("skills")
        or manifest.get("mcpServers")
        or _skill_directories(root / "skills")
        or (root / ".mcp.json").is_file()
        or (root / "mcp.json").is_file(),
    )


# pylint: disable-next=too-many-locals,too-many-branches,too-many-statements
def discover_codex_plugins(
    codex_home: Path,
) -> tuple[list[SourceMarketplace], list[SourcePlugin]]:
    """Read enabled Codex plugin IDs and their Marketplace declarations."""
    codex_home = codex_home.expanduser()
    config_path = codex_home / "config.toml"
    try:
        data = read_regular_file(config_path, max_bytes=_MAX_CONFIG_BYTES)
        config = tomllib.loads(data.decode())
    except (OSError, UnicodeError, ValueError, tomllib.TOMLDecodeError):
        config = {}
    plugin_config = config.get("plugins")
    if not isinstance(plugin_config, dict):
        plugin_config = {}
    marketplace_config = config.get("marketplaces")
    if not isinstance(marketplace_config, dict):
        marketplace_config = {}

    enabled_ids: list[str] = []
    for plugin_id, value in plugin_config.items():
        enabled = value if isinstance(value, bool) else False
        if isinstance(value, dict):
            enabled = bool(value.get("enabled", False))
        if enabled and "@" in str(plugin_id):
            enabled_ids.append(str(plugin_id))

    remote_ids: set[str] = set()
    cache_root = codex_home / "plugins" / "cache"
    for marker in cache_root.glob("*/*/.codex-remote-plugin-install.json"):
        if marker.is_symlink() or not marker.is_file():
            continue
        plugin_id = f"{marker.parent.name}@{marker.parent.parent.name}"
        remote_ids.add(plugin_id)
        if plugin_id not in enabled_ids:
            enabled_ids.append(plugin_id)

    marketplace_names = sorted(
        {item.rsplit("@", 1)[1] for item in enabled_ids},
    )
    marketplaces: list[SourceMarketplace] = []
    resolved_roots: dict[str, Path] = {}
    for name in marketplace_names:
        raw = marketplace_config.get(name)
        if isinstance(raw, dict):
            source_type, source = _marketplace_source(raw, codex_home)
            ref_name = str(raw.get("ref") or "")
        else:
            source_type = (
                "builtin" if name in _CODEX_BUILTIN_MARKETPLACES else "unknown"
            )
            source = ""
            ref_name = ""
        source_path = Path(source).expanduser() if source else None
        if source_path is not None and source_path.is_dir():
            resolved_roots[name] = source_path.resolve()
        marketplaces.append(
            SourceMarketplace(
                source_id=f"codex:{name}",
                name=name,
                source=source,
                source_type=source_type,
                ref_name=ref_name,
            ),
        )

    plugins: list[SourcePlugin] = []
    for plugin_id in sorted(enabled_ids):
        source_name, marketplace = plugin_id.rsplit("@", 1)
        (
            version,
            display_name,
            cached_source,
            cached_manifest,
        ) = _cached_plugin_details(
            cache_root,
            marketplace,
            source_name,
        )
        root = resolved_roots.get(marketplace)
        metadata: dict[str, Any] = {
            "source_manifest": "codex",
            "remote_install": plugin_id in remote_ids,
        }
        if cached_source is not None:
            metadata["install_path"] = str(cached_source)
            if _codex_content_bundle(cached_source, cached_manifest):
                metadata["adapter"] = CODEX_PLUGIN_ADAPTER
        plugins.append(
            SourcePlugin(
                source_id=plugin_id,
                name=display_name or source_name,
                marketplace=marketplace,
                version=version,
                install_source=(
                    _qwen_plugin_source(root, source_name)
                    if root is not None
                    else ""
                ),
                metadata=metadata,
            ),
        )
    return marketplaces, plugins


# pylint: disable-next=too-many-locals,too-many-branches,too-many-statements
def discover_qoder_plugins(
    qoder_home: Path,
) -> tuple[list[SourceMarketplace], list[SourcePlugin]]:
    """Read Qoder's installed-plugin ledger without copying its cache."""
    qoder_home = qoder_home.expanduser()
    ledger = _read_json(qoder_home / "plugins" / "installed_plugins_v2.json")
    settings = _read_json(qoder_home / "settings.json")
    enabled_settings = (
        settings.get("enabledPlugins") if isinstance(settings, dict) else None
    )
    if not isinstance(enabled_settings, dict):
        enabled_settings = {}
    records = ledger.get("plugins") if isinstance(ledger, dict) else None
    if not isinstance(records, dict):
        return [], []
    plugins: list[SourcePlugin] = []
    marketplace_names: set[str] = set()
    for plugin_id, installs in sorted(records.items()):
        if "@" not in str(plugin_id) or not isinstance(installs, list):
            continue
        valid_records = [item for item in installs if isinstance(item, dict)]
        setting = enabled_settings.get(str(plugin_id))
        enabled_records = valid_records
        if setting is False:
            enabled_records = []
        elif setting is not True:
            enabled_records = []
            for item in valid_records:
                if bool(item.get("enabled", True)):
                    enabled_records.append(item)
        if not enabled_records:
            continue
        name, marketplace = str(plugin_id).rsplit("@", 1)
        marketplace_names.add(marketplace)
        version = str(enabled_records[0].get("version") or "")
        raw_install_path = str(enabled_records[0].get("installPath") or "")
        install_path = None
        if raw_install_path:
            install_path = Path(raw_install_path).expanduser()
        manifest = (
            _read_json(install_path / ".qoder-plugin" / "plugin.json")
            if install_path is not None
            else None
        )
        if not isinstance(manifest, dict) and install_path is not None:
            manifest = _read_json(install_path / "plugin.json")
        declared_skills = None
        if isinstance(manifest, dict):
            declared_skills = manifest.get("skills")
        plugin_skill_count = 0
        if isinstance(declared_skills, str) and declared_skills:
            plugin_skill_count = 1
        elif isinstance(declared_skills, list):
            plugin_skill_count = len(declared_skills)
        if install_path is not None:
            plugin_skill_count = max(
                plugin_skill_count,
                len(_skill_directories(install_path / "skills")),
            )
        if not version and isinstance(manifest, dict):
            version = str(manifest.get("version") or "")
        marketplace_root = qoder_home / "plugins" / "marketplaces"
        marketplace_root = marketplace_root / marketplace
        custom_adapter = discover_qoder_custom_skill_adapter(
            qoder_home,
            install_path,
            manifest,
            enabled_records[0],
            str(plugin_id),
        )
        plugins.append(
            SourcePlugin(
                source_id=str(plugin_id),
                name=name,
                marketplace=marketplace,
                version=version,
                install_source=(
                    str(install_path.resolve())
                    if custom_adapter is not None and install_path is not None
                    else (
                        _qwen_plugin_source(marketplace_root, name)
                        if marketplace_root.is_dir()
                        else ""
                    )
                ),
                metadata={
                    "source_manifest": "qoder",
                    "install_path": str(install_path or ""),
                    "plugin_owned_skill_count": plugin_skill_count,
                    "qoder_manifest": bool(manifest),
                    **(custom_adapter or {}),
                },
            ),
        )
    marketplaces = []
    for name in sorted(marketplace_names):
        if name == "local-custom":
            root = qoder_home / "plugins" / "custom"
            source_type = "local_custom"
        else:
            root = qoder_home / "plugins" / "marketplaces" / name
            source_type = "directory" if root.is_dir() else "builtin"
        marketplaces.append(
            SourceMarketplace(
                source_id=f"qoder:{name}",
                name=name,
                source=str(root.resolve()) if root.is_dir() else "",
                source_type=source_type,
            ),
        )
    return marketplaces, plugins


__all__ = [
    "discover_codex_memory",
    "codex_memory_status",
    "discover_codex_plugin_mcp",
    "discover_codex_plugins",
    "discover_project_memory",
    "discover_qoder_mcp",
    "discover_qoder_memory",
    "discover_qoder_plugin_mcp",
    "discover_qoder_plugins",
    "discover_qoder_skills",
]
