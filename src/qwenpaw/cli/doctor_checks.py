# -*- coding: utf-8 -*-
"""Read-only diagnostics for `copaw doctor` (no config or disk mutations)."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import platform
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..__version__ import __version__
from ..agents.skills_manager import get_workspace_skills_dir, read_skill_manifest
from ..app.crons.models import JobsFile
from ..config.config import (
    AgentProfileConfig,
    AgentProfileRef,
    AgentsConfig,
    ChannelConfig,
    Config,
    MCPConfig,
    SecurityConfig,
    ToolsConfig,
    load_agent_config,
)
from ..config.utils import (
    _normalize_working_dir_bound_paths,
    _read_config_data,
    get_config_path,
    get_jobs_path,
    get_playwright_chromium_executable_path,
    is_running_in_container,
)
from ..constant import (
    HEARTBEAT_FILE,
    JOBS_FILE,
    MEMORY_DIR,
    PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH_ENV,
    SECRET_DIR,
    WORKING_DIR,
)
from ..providers.provider import Provider


# Log file opened on app startup (see ``copaw.app._app`` lifespan).
COPAW_APP_LOG_NAME = "copaw.log"


def _resolve_existing_path_anchor(path: Path) -> Path | None:
    """First existing path walking up from *path* (for ``stat`` / ``disk_usage``)."""
    cur = path.expanduser()
    try:
        cur = cur.resolve(strict=False)
    except (OSError, RuntimeError):
        cur = path.expanduser()
    for _ in range(128):
        try:
            if cur.exists():
                return cur
        except OSError:
            return None
        parent = cur.parent
        if parent == cur:
            return None
        cur = parent
    return None


def check_copaw_log_writable() -> tuple[bool, str]:
    """``copaw app`` appends to ``WORKING_DIR / copaw.log`` during startup."""
    log_path = WORKING_DIR / COPAW_APP_LOG_NAME
    try:
        with open(log_path, "a", encoding="utf-8"):
            pass
    except OSError as exc:
        return (
            False,
            f"cannot append to {log_path} (required when starting `copaw app`): {exc}",
        )
    return True, str(log_path)


def check_agent_workspace_writable(cfg: Config) -> tuple[bool, str]:
    """Existing agent workspace directories must be writable for runtime state."""
    problems: list[str] = []
    checked = 0
    for agent_id, ref in cfg.agents.profiles.items():
        wd = Path(ref.workspace_dir).expanduser()
        if not wd.is_dir():
            continue
        checked += 1
        if not os.access(wd, os.W_OK):
            problems.append(f"{agent_id}: workspace not writable: {wd}")
    if problems:
        return False, "\n".join(problems)
    if checked == 0:
        return True, "no existing workspace dirs (skipped writability)"
    return True, f"{checked} workspace dir(s) writable"


def startup_extra_volume_disk_notes(cfg: Config | None) -> list[str]:
    """Low free space on volumes other than ``WORKING_DIR`` that hold persistence."""
    notes: list[str] = []
    try:
        wd_dev = WORKING_DIR.stat().st_dev
    except OSError:
        return notes

    anchors: dict[int, Path] = {}

    def consider(p: Path) -> None:
        anchor = _resolve_existing_path_anchor(p)
        if anchor is None:
            return
        try:
            dev = anchor.stat().st_dev
        except OSError:
            return
        if dev != wd_dev:
            anchors.setdefault(dev, anchor)

    consider(SECRET_DIR)
    if cfg is not None:
        for ref in cfg.agents.profiles.values():
            consider(Path(ref.workspace_dir))

    low_gib = 0.5
    for anchor in anchors.values():
        try:
            du = shutil.disk_usage(anchor)
        except OSError:
            continue
        free_gib = du.free / (1024**3)
        if free_gib < low_gib:
            notes.append(
                f"persistence path on another volume ({anchor}): {free_gib:.2f} GiB free "
                f"(below {low_gib} GiB) — writes may fail even if working_dir volume is healthy.",
            )
    return notes


def _active_python_environment_summary() -> str:
    """Short label for the venv/conda context of this Python (CoPaw CLI)."""
    ve = (os.environ.get("VIRTUAL_ENV") or "").strip()
    if ve:
        return f"{ve}"
    cenv = (os.environ.get("CONDA_DEFAULT_ENV") or "").strip()
    cpfx = (os.environ.get("CONDA_PREFIX") or "").strip()
    if cenv and cpfx:
        return f"conda {cenv} ({cpfx})"
    base = getattr(sys, "base_prefix", sys.prefix)
    if sys.prefix != base:
        return f"venv (sys.prefix={sys.prefix})"
    return "system interpreter (no virtualenv in effect)"


def environment_summary_lines() -> list[str]:
    """One line per fact; safe to paste into bug reports."""
    py_ver = sys.version.split()[0]
    lines = [
        f"python: {py_ver}",
        f"copaw: {__version__}",
        f"platform: {platform.system()} {platform.machine()}",
        f"copaw_environment: {_active_python_environment_summary()}",
        f"doctor_environment: {sys.executable}",
        f"working_dir: {WORKING_DIR}",
    ]
    copaw_wd = os.getenv("COPAW_WORKING_DIR")
    if copaw_wd:
        lines.append(f"COPAW_WORKING_DIR (env): {copaw_wd}")
    lines.append(f"sqlite library: {sqlite3.sqlite_version}")
    try:
        ver_tuple = tuple(
            map(int, sqlite3.sqlite_version.split(".")[:3]),
        )
        if ver_tuple < (3, 35):
            lines.append(
                "Note: SQLite < 3.35 may break Chroma / some vector stores; "
                "upgrade system SQLite if embeddings fail.",
            )
    except (ValueError, TypeError):
        pass
    try:
        du = shutil.disk_usage(WORKING_DIR)
        free_gib = du.free / (1024**3)
        lines.append(f"disk free (working dir volume): {free_gib:.2f} GiB")
        if free_gib < 0.5:
            lines.append(
                "Note: very low free space — risk of failed writes and corrupted state.",
            )
    except OSError:
        lines.append("disk free: (could not stat working dir volume)")
    return lines


def load_raw_config_dict() -> dict[str, Any] | None:
    path = get_config_path()
    if not path.is_file():
        return None
    data = _read_config_data(path)
    return data if isinstance(data, dict) else None


def scan_unknown_config_keys(raw: dict[str, Any]) -> list[str]:
    """Shallow unknown keys vs current Pydantic models (read-only; never delete).

    ``channels.*`` extras may still be valid (plugins); we flag with a note.
    """
    found: list[str] = []

    allowed_root = set(Config.model_fields.keys()) | {
        "last_api_host",
        "last_api_port",
    }
    for key in raw:
        if key not in allowed_root:
            found.append(f"top-level key {key!r} (not on root Config model)")

    agents = raw.get("agents")
    if isinstance(agents, dict):
        allowed = set(AgentsConfig.model_fields.keys())
        for key in agents:
            if key not in allowed:
                found.append(f"agents.{key!r} (not on AgentsConfig model)")

    tools = raw.get("tools")
    if isinstance(tools, dict):
        allowed = set(ToolsConfig.model_fields.keys())
        for key in tools:
            if key not in allowed:
                found.append(f"tools.{key!r} (not on ToolsConfig model)")

    security = raw.get("security")
    if isinstance(security, dict):
        allowed = set(SecurityConfig.model_fields.keys())
        for key in security:
            if key not in allowed:
                found.append(f"security.{key!r} (not on SecurityConfig model)")

    mcp = raw.get("mcp")
    if isinstance(mcp, dict):
        allowed = set(MCPConfig.model_fields.keys())
        for key in mcp:
            if key not in allowed:
                found.append(f"mcp.{key!r} (not on MCPConfig model)")

    channels = raw.get("channels")
    if isinstance(channels, dict):
        allowed = set(ChannelConfig.model_fields.keys())
        for key in channels:
            if key not in allowed:
                found.append(
                    f"channels.{key!r} — not a built-in channel field "
                    f"(may be a plugin; root ChannelConfig allows extra keys)",
                )

    return found


def legacy_single_agent_workspace_note(cfg: Config) -> str | None:
    """Align with ``migrate_legacy_workspace_to_default_agent`` preconditions.

    When this applies, ``copaw app`` may run an automatic migration; doctor only
    informs — it does not migrate.
    """
    profiles = cfg.agents.profiles
    if len(profiles) != 1 or "default" not in profiles:
        return None
    ref = profiles["default"]
    if not isinstance(ref, AgentProfileRef):
        return None
    agent_json = Path(ref.workspace_dir).expanduser() / "agent.json"
    if agent_json.is_file():
        return None
    return (
        "Only `default` is listed and workspace "
        f"`{agent_json}` is missing — the same situation "
        "`copaw app` uses to trigger legacy → multi-agent workspace migration. "
        "Start `copaw app` once (or see docs / `copaw init`). "
        "Doctor does not change config or files."
    )


def check_agent_profile_workspaces(cfg: Config) -> tuple[bool, str]:
    """Each ``agents.profiles`` entry should have a directory and ``agent.json``."""
    problems: list[str] = []
    for agent_id, ref in cfg.agents.profiles.items():
        wd = Path(ref.workspace_dir).expanduser()
        if not wd.is_dir():
            problems.append(
                f"{agent_id}: workspace_dir is not a directory: {wd}",
            )
            continue
        agent_json = wd / "agent.json"
        if not agent_json.is_file():
            problems.append(f"{agent_id}: missing {agent_json}")
    if problems:
        return False, "\n".join(problems)
    n = len(cfg.agents.profiles)
    return True, f"{n} agent profile(s); each workspace contains agent.json"


# --- OpenClaw-inspired read-only checks (cron, security hints, memory, hygiene) ---

_LARGE_PROMPT_BYTES = 350 * 1024
# Disabled: long-lived lock carrier files (e.g. .skill.json.lock) often stay on
# disk with old mtime while locks are still meaningful — too many false positives.
# _STALE_LOCK_SECS = 86400
_TOOL_RESULT_MANY = 400
_DIALOG_MANY = 200


def check_cron_jobs_files(cfg: Config) -> tuple[bool, str]:
    """Validate each agent workspace ``jobs.json`` and optional legacy root file."""
    problems: list[str] = []
    validated_paths: list[tuple[str, Path, int]] = []

    for agent_id, ref in cfg.agents.profiles.items():
        path = Path(ref.workspace_dir).expanduser() / JOBS_FILE
        if not path.is_file():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            jf = JobsFile.model_validate(raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            problems.append(f"{agent_id}: {path} — JSON error ({exc})")
            continue
        except Exception as exc:  # pylint: disable=broad-exception-caught
            problems.append(f"{agent_id}: {path} — schema ({exc})")
            continue
        validated_paths.append((agent_id, path, len(jf.jobs)))

    legacy = get_jobs_path()
    if legacy.is_file():
        try:
            raw = json.loads(legacy.read_text(encoding="utf-8"))
            jf = JobsFile.model_validate(raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            problems.append(f"legacy root: {legacy} — JSON error ({exc})")
        except Exception as exc:  # pylint: disable=broad-exception-caught
            problems.append(f"legacy root: {legacy} — schema ({exc})")
        else:
            validated_paths.append(("(root)", legacy, len(jf.jobs)))

    if problems:
        return False, "\n".join(problems)
    if not validated_paths:
        return True, "no jobs.json under agent workspaces (OK if you do not use cron)"
    summary = "; ".join(
        f"{aid}: {n} job(s)" for aid, _p, n in validated_paths
    )
    return True, f"{len(validated_paths)} file(s) OK — {summary}"


def _ms_playwright_browser_cache_roots() -> list[Path]:
    roots: list[Path] = []
    env = (os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "").strip()
    if env:
        roots.append(Path(env).expanduser())
    roots.append(Path.home() / ".cache" / "ms-playwright")
    if sys.platform == "darwin":
        roots.append(Path.home() / "Library" / "Caches" / "ms-playwright")
    localappdata = os.environ.get("LOCALAPPDATA")
    if localappdata:
        roots.append(Path(localappdata) / "ms-playwright")
    return roots


def _playwright_chromium_bundle_present() -> bool:
    """Best-effort: Playwright ``playwright install chromium`` cache directory."""
    for root in _ms_playwright_browser_cache_roots():
        try:
            if not root.is_dir():
                continue
            for child in root.iterdir():
                if child.is_dir() and child.name.startswith("chromium"):
                    return True
        except OSError:
            continue
    return False


def browser_automation_notes(cfg: Config | None) -> list[str]:
    """``browser_use`` / Playwright readiness (read-only hints).

    Does not start a browser; only checks imports, typical paths, and
    workspace ``browser/user_data`` layout.
    """
    notes: list[str] = []

    if importlib.util.find_spec("playwright") is None:
        notes.append(
            "browser_use needs the Playwright Python package — install with: "
            f"'{sys.executable}' -m pip install playwright && "
            f"'{sys.executable}' -m playwright install chromium",
        )
        return notes

    try:
        from playwright.async_api import async_playwright  # noqa: F401
    except ImportError:
        notes.append(
            "playwright is installed but async_api failed to import — reinstall "
            "the playwright package for this Python.",
        )
        return notes

    use_default = os.environ.get("COPAW_BROWSER_USE_DEFAULT", "1").strip().lower()
    if use_default in ("0", "false", "no", "off"):
        notes.append(
            "COPAW_BROWSER_USE_DEFAULT is off — browser_use will not prefer the "
            "OS default Chrome/Edge path; bundled or scanned Chromium paths apply.",
        )

    if is_running_in_container():
        notes.append(
            "Container environment: use headless browser_use unless you add "
            "display forwarding; install Chromium in the image or run "
            f"'{sys.executable}' -m playwright install chromium if launches fail.",
        )

    exe = get_playwright_chromium_executable_path()
    if not exe and sys.platform != "darwin":
        if not _playwright_chromium_bundle_present():
            notes.append(
                "No system Chrome/Chromium path found and no Playwright chromium "
                "cache detected — run "
                f"'{sys.executable}' -m playwright install chromium' or install "
                "Chrome/Edge, or set "
                f"{PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH_ENV}.",
            )
    elif not exe and sys.platform == "darwin":
        if not _playwright_chromium_bundle_present():
            notes.append(
                "No Chrome/Edge/Chromium on PATH — browser_use falls back to "
                "WebKit on macOS; install Chrome/Edge or run "
                f"'{sys.executable}' -m playwright install chromium' if you need "
                "Chromium specifically.",
            )

    if sys.platform.startswith("linux") and not is_running_in_container():
        if not (os.environ.get("DISPLAY") or "").strip():
            notes.append(
                "DISPLAY is unset — headed browser_use (visible window) may fail; "
                "use the default headless mode or configure X11/Wayland.",
            )

    if cfg is not None:
        for agent_id, ref in cfg.agents.profiles.items():
            ws = Path(ref.workspace_dir).expanduser()
            ud = ws / "browser" / "user_data"
            try:
                if ud.is_file():
                    notes.append(
                        f"{agent_id}: {ud} exists as a file — remove or rename it "
                        "so browser_use can use a profile directory.",
                    )
                elif ud.is_dir() and not os.access(ud, os.W_OK):
                    notes.append(
                        f"{agent_id}: {ud} is not writable — persistent browser "
                        "profiles may fail.",
                    )
            except OSError:
                pass

    return notes


def security_baseline_notes(cfg: Config) -> list[str]:
    """Non-fatal security posture hints (aligned with OpenClaw ``doctor:security``)."""
    notes: list[str] = []
    if not cfg.security.tool_guard.enabled:
        notes.append(
            "security.tool_guard.enabled is false — dangerous shell commands "
            "are not filtered.",
        )
    if cfg.security.skill_scanner.mode == "off":
        notes.append(
            "security.skill_scanner.mode is off — skills are not scanned "
            "before install.",
        )
    if not cfg.security.file_guard.enabled:
        notes.append(
            "security.file_guard.enabled is false — sensitive path blocking "
            "is off.",
        )
    return notes


def _embedding_has_credentials(emb_api_key: str) -> bool:
    if (emb_api_key or "").strip():
        return True
    return bool(
        os.getenv("OPENAI_API_KEY")
        or os.getenv("DASHSCOPE_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY"),
    )


def memory_embedding_notes(cfg: Config) -> list[str]:
    """Embedding / vector memory readiness (per agent ``agent.json``)."""
    notes: list[str] = []
    for agent_id in cfg.agents.profiles:
        try:
            ac = load_agent_config(agent_id)
        except Exception:  # pylint: disable=broad-exception-caught
            continue
        emb = ac.running.embedding_config
        ms = ac.running.memory_summary
        if ms.force_memory_search and not _embedding_has_credentials(emb.api_key):
            notes.append(
                f"{agent_id}: running.memory_summary.force_memory_search is on "
                "but no embedding API key is set in running.embedding_config.api_key "
                "and no common OPENAI_/DASHSCOPE_/ANTHROPIC_ API key env was found.",
            )
    return notes


def workspace_hygiene_notes(cfg: Config) -> list[str]:
    """Large prompt files, heavy tool_result/dialog dirs; memory tree size."""
    notes: list[str] = []
    bootstrap_names = (
        "AGENTS.md",
        "SOUL.md",
        "PROFILE.md",
        HEARTBEAT_FILE,
    )
    for agent_id, ref in cfg.agents.profiles.items():
        wd = Path(ref.workspace_dir).expanduser()
        if not wd.is_dir():
            continue
        for name in bootstrap_names:
            p = wd / name
            if not p.is_file():
                continue
            try:
                sz = p.stat().st_size
            except OSError:
                continue
            if sz > _LARGE_PROMPT_BYTES:
                notes.append(
                    f"{agent_id}: {name} is {sz // 1024} KiB — large prompts "
                    "burn context; consider splitting or summarizing.",
                )
        for sub, many, label in (
            ("tool_result", _TOOL_RESULT_MANY, "tool_result"),
            ("dialog", _DIALOG_MANY, "dialog"),
        ):
            d = wd / sub
            if not d.is_dir():
                continue
            try:
                n = sum(1 for _ in d.iterdir())
            except OSError:
                continue
            if n > many:
                notes.append(
                    f"{agent_id}: {label}/ has {n} entries — cleanup or archival "
                    "may improve performance.",
                )
        # Stale *.lock scan disabled — see _STALE_LOCK_SECS comment above.
        # stale = 0
        # for lock_path in wd.rglob("*.lock"):
        #     if not lock_path.is_file():
        #         continue
        #     try:
        #         if now - lock_path.stat().st_mtime > _STALE_LOCK_SECS:
        #             stale += 1
        #     except OSError:
        #         continue
        #     if stale >= 8:
        #         break
        # if stale > 0:
        #     notes.append(
        #         f"{agent_id}: {stale}+ stale *.lock file(s) under workspace "
        #         "(older than 24h) — possible crashed process; safe to inspect.",
        #     )

    if MEMORY_DIR.is_dir():
        try:
            mcount = sum(1 for p in MEMORY_DIR.rglob("*") if p.is_file())
        except OSError:
            mcount = 0
        if mcount > 5000:
            notes.append(
                f"global memory tree {MEMORY_DIR} has many files ({mcount}+) — "
                "expect slower indexing or backup size.",
            )
    return notes


# --- CoPaw-specific profile checks (agent.json, channels, MCP, skills, providers) ---


def _read_workspace_agent_json(ref: AgentProfileRef) -> dict[str, Any] | None:
    path = Path(ref.workspace_dir).expanduser() / "agent.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        data = _normalize_working_dir_bound_paths(data)
    except Exception:  # pylint: disable=broad-exception-caught
        pass
    return data


def check_agent_json_profiles(cfg: Config) -> tuple[bool, str]:
    """Validate ``agent.json`` with ``AgentProfileConfig`` (read-only; no ``load_agent_config``)."""
    problems: list[str] = []
    n_ok = 0
    for agent_id, ref in cfg.agents.profiles.items():
        path = Path(ref.workspace_dir).expanduser() / "agent.json"
        if not path.is_file():
            continue
        raw = _read_workspace_agent_json(ref)
        if raw is None:
            problems.append(f"{agent_id}: {path} — invalid or unreadable JSON")
            continue
        try:
            AgentProfileConfig.model_validate(raw)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            problems.append(f"{agent_id}: agent.json — {exc}")
            continue
        n_ok += 1
    if problems:
        return False, "\n".join(problems)
    if n_ok == 0:
        return True, "no agent.json files to validate"
    return True, f"{n_ok} agent.json file(s) match AgentProfileConfig"


def check_enabled_agents_load_agent_config(cfg: Config) -> tuple[bool, str]:
    """Dry-run :func:`~copaw.config.config.load_agent_config` for enabled profiles only.

    Matches agents started by ``MultiAgentManager.start_all_configured_agents``.
    When ``agent.json`` is missing, we do **not** call ``load_agent_config`` (that
    would write a fallback file on disk); we report FAIL for enabled agents instead.
    """
    problems: list[str] = []
    ok_n = 0
    enabled_n = 0
    for agent_id, ref in cfg.agents.profiles.items():
        if not getattr(ref, "enabled", True):
            continue
        enabled_n += 1
        ws = Path(ref.workspace_dir).expanduser()
        path = ws / "agent.json"
        if not path.is_file():
            problems.append(
                f"{agent_id}: enabled but missing {path} — at startup "
                "`load_agent_config` would create a fallback agent.json on disk; "
                "ensure the file exists or use `copaw doctor fix` where applicable.",
            )
            continue
        try:
            load_agent_config(agent_id)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            problems.append(f"{agent_id}: load_agent_config failed — {exc}")
            continue
        ok_n += 1
    if problems:
        return False, "\n".join(problems)
    if enabled_n == 0:
        return True, "no enabled agents in config"
    return True, f"{ok_n} enabled agent(s); load_agent_config OK"


def _effective_channels_mcp(
    cfg: Config,
    raw: dict[str, Any] | None,
) -> tuple[ChannelConfig, MCPConfig]:
    ch = cfg.channels
    mcp = cfg.mcp
    if raw is None:
        return ch, mcp
    if raw.get("channels") is not None:
        try:
            ch = ChannelConfig.model_validate(raw["channels"])
        except Exception:  # pylint: disable=broad-exception-caught
            pass
    if raw.get("mcp") is not None:
        try:
            mcp = MCPConfig.model_validate(raw["mcp"])
        except Exception:  # pylint: disable=broad-exception-caught
            pass
    return ch, mcp


def enabled_channel_notes(cfg: Config) -> list[str]:
    """Static checks for built-in channels with ``enabled`` and empty credentials."""
    notes: list[str] = []
    for agent_id, ref in cfg.agents.profiles.items():
        raw = _read_workspace_agent_json(ref)
        ch, _ = _effective_channels_mcp(cfg, raw)
        for name in ChannelConfig.model_fields:
            sub = getattr(ch, name, None)
            if sub is None:
                continue
            if not getattr(sub, "enabled", False):
                continue
            if name == "console":
                continue
            if name == "discord" and not (sub.bot_token or "").strip():
                notes.append(f"{agent_id}: discord enabled but bot_token is empty")
            elif name == "dingtalk":
                if not (sub.client_id or "").strip() or not (
                    sub.client_secret or ""
                ).strip():
                    notes.append(
                        f"{agent_id}: dingtalk enabled but client_id/client_secret incomplete",
                    )
            elif name == "feishu":
                if not (sub.app_id or "").strip() or not (
                    sub.app_secret or ""
                ).strip():
                    notes.append(
                        f"{agent_id}: feishu enabled but app_id/app_secret incomplete",
                    )
            elif name == "qq":
                if not (sub.app_id or "").strip() or not (
                    sub.client_secret or ""
                ).strip():
                    notes.append(
                        f"{agent_id}: qq enabled but app_id/client_secret incomplete",
                    )
            elif name == "telegram" and not (sub.bot_token or "").strip():
                notes.append(f"{agent_id}: telegram enabled but bot_token is empty")
            elif name == "mattermost":
                if not (sub.url or "").strip() or not (sub.bot_token or "").strip():
                    notes.append(
                        f"{agent_id}: mattermost enabled but url/bot_token incomplete",
                    )
            elif name == "mqtt" and not (sub.host or "").strip():
                notes.append(f"{agent_id}: mqtt enabled but host is empty")
            elif name == "matrix":
                if (
                    not (sub.homeserver or "").strip()
                    or not (sub.user_id or "").strip()
                    or not (sub.access_token or "").strip()
                ):
                    notes.append(
                        f"{agent_id}: matrix enabled but homeserver/user_id/access_token incomplete",
                    )
            elif name == "voice":
                if (
                    not (sub.twilio_account_sid or "").strip()
                    or not (sub.twilio_auth_token or "").strip()
                    or not (sub.phone_number or "").strip()
                ):
                    notes.append(
                        f"{agent_id}: voice enabled but Twilio fields incomplete",
                    )
            elif name == "wecom":
                if not (sub.bot_id or "").strip() or not (sub.secret or "").strip():
                    notes.append(
                        f"{agent_id}: wecom enabled but bot_id/secret incomplete",
                    )
            elif name == "xiaoyi":
                if (
                    not (sub.ak or "").strip()
                    or not (sub.sk or "").strip()
                    or not (sub.agent_id or "").strip()
                ):
                    notes.append(
                        f"{agent_id}: xiaoyi enabled but ak/sk/agent_id incomplete",
                    )
            elif name == "weixin":
                tok = (sub.bot_token or "").strip()
                fp = (sub.bot_token_file or "").strip()
                if tok:
                    pass
                elif fp:
                    p = Path(fp).expanduser()
                    if not p.is_file():
                        notes.append(
                            f"{agent_id}: weixin enabled but bot_token_file missing: {p}",
                        )
                else:
                    notes.append(
                        f"{agent_id}: weixin enabled but bot_token and bot_token_file unset",
                    )
            elif name == "imessage":
                dbp = Path(sub.db_path).expanduser()
                if not dbp.is_file():
                    notes.append(
                        f"{agent_id}: imessage enabled but chat.db not found at {dbp}",
                    )
        extra = getattr(ch, "__pydantic_extra__", None) or {}
        for key, val in extra.items():
            en = False
            if isinstance(val, dict):
                en = bool(val.get("enabled"))
            elif hasattr(val, "enabled"):
                en = bool(getattr(val, "enabled"))
            if en:
                notes.append(
                    f"{agent_id}: custom/plugin channel {key!r} is enabled — "
                    "verify credentials and connectivity.",
                )
    return notes


def _url_looks_httpish(url: str) -> bool:
    p = urlparse(url.strip())
    return p.scheme in ("http", "https") and bool(p.netloc)


def _mcp_client_problems(mcp: MCPConfig | None, label: str) -> list[str]:
    if mcp is None:
        return []
    problems: list[str] = []
    for cid, client in mcp.clients.items():
        if not client.enabled:
            continue
        if client.transport == "stdio":
            cmd0 = (client.command or "").strip().split()
            if not cmd0:
                problems.append(f"{label} MCP {cid!r}: stdio command is empty")
                continue
            exe = cmd0[0]
            if not shutil.which(exe):
                problems.append(
                    f"{label} MCP {cid!r}: stdio executable {exe!r} not found on PATH",
                )
        elif client.transport in ("streamable_http", "sse"):
            u = (client.url or "").strip()
            if not u:
                problems.append(
                    f"{label} MCP {cid!r}: {client.transport} url is empty",
                )
            elif not _url_looks_httpish(u):
                problems.append(
                    f"{label} MCP {cid!r}: url does not look like http(s)://…",
                )
    return problems


def mcp_client_notes(cfg: Config) -> list[str]:
    """Enabled MCP clients: PATH / URL sanity (root + per-agent ``agent.json`` mcp)."""
    notes: list[str] = []
    notes.extend(_mcp_client_problems(cfg.mcp, "root"))
    for agent_id, ref in cfg.agents.profiles.items():
        raw = _read_workspace_agent_json(ref)
        if raw is None or raw.get("mcp") is None:
            continue
        try:
            mcp = MCPConfig.model_validate(raw["mcp"])
        except Exception:  # pylint: disable=broad-exception-caught
            continue
        notes.extend(_mcp_client_problems(mcp, f"agent {agent_id}"))
    return notes


def skill_layout_notes(cfg: Config) -> list[str]:
    """Enabled skills in skill.json vs on-disk directories under the workspace."""
    notes: list[str] = []
    for agent_id, ref in cfg.agents.profiles.items():
        wd = Path(ref.workspace_dir).expanduser()
        if not wd.is_dir():
            continue
        manifest = read_skill_manifest(wd)
        skills = manifest.get("skills") or {}
        if not isinstance(skills, dict):
            continue
        root = get_workspace_skills_dir(wd)
        for sname, entry in skills.items():
            if not isinstance(entry, dict):
                continue
            if not entry.get("enabled", False):
                continue
            d = root / str(sname)
            if not d.is_dir():
                notes.append(
                    f"{agent_id}: skill {sname!r} enabled in skill.json but directory missing: {d}",
                )
    return notes


def provider_overview_notes() -> list[str]:
    """Custom providers with missing required fields (async provider registry)."""
    from ..providers.provider_manager import ProviderManager

    async def _run() -> list[str]:
        infos = await ProviderManager.get_instance().list_provider_info()
        out: list[str] = []
        for info in infos:
            if not info.is_custom:
                continue
            if info.require_api_key and not (info.api_key or "").strip():
                out.append(
                    f"custom provider {info.id!r}: API key required but empty",
                )
            if not info.is_local and not (info.base_url or "").strip():
                out.append(
                    f"custom provider {info.id!r}: base_url is empty",
                )
        return out

    return asyncio.run(_run())


def active_llm_local_failure_hint(provider: Provider, provider_id: str) -> str:
    """Short hint when ``check_model_connection`` failed for a local-oriented provider."""
    if provider_id == "ollama":
        base = (getattr(provider, "base_url", None) or "").strip()
        if not base:
            base = (os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").strip()
        return (
            f"Hint: start Ollama (e.g. `ollama serve`) and ensure the model is "
            f"available (`ollama pull …`). OpenAI-compatible API is usually "
            f"{base.rstrip('/')}/v1 ."
        )
    if provider_id == "lmstudio":
        base = (getattr(provider, "base_url", None) or "").strip() or "http://127.0.0.1:1234/v1"
        return (
            f"Hint: open LM Studio, load a model, and enable the local server. "
            f"Typical base URL: {base.rstrip('/')}"
        )
    if provider_id == "copaw-local":
        return (
            "Hint: CoPaw Local uses llama.cpp. Start the local server from the CoPaw "
            "console or install the llama.cpp binary from there. "
            "Run `copaw doctor --deep` to see llama.cpp install and server status."
        )
    if getattr(provider, "is_local", False):
        base = (getattr(provider, "base_url", None) or "").strip() or "your configured base_url"
        return (
            f"Hint: this provider is marked local — ensure the inference HTTP server "
            f"is running and matches {base}."
        )
    return ""


def copaw_local_llm_deep_notes() -> list[str]:
    """Read-only llama.cpp install + server snapshot (for ``--deep`` + ``copaw-local``)."""
    try:
        from ..local_models.manager import LocalModelManager
    except Exception as exc:  # pylint: disable=broad-exception-caught
        return [f"LocalModelManager unavailable: {exc}"]
    try:
        lm = LocalModelManager.get_instance()
    except Exception as exc:  # pylint: disable=broad-exception-caught
        return [f"LocalModelManager: {exc}"]
    notes: list[str] = []
    try:
        ok, msg = lm.check_llamacpp_installation()
        line = (
            "llama.cpp binary: OK"
            if ok
            else "llama.cpp binary: missing or not installed"
        )
        if msg:
            line += f" — {msg}"
        notes.append(line)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        notes.append(f"llama.cpp install check failed: {exc}")
    try:
        st = lm.get_llamacpp_server_status()
        notes.append(
            "llama.cpp server: "
            f"running={st.get('running')}, port={st.get('port')}, "
            f"model={st.get('model_name')!r}, pid={st.get('pid')}",
        )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        notes.append(f"llama.cpp server status failed: {exc}")
    try:
        if lm.is_llamacpp_server_transitioning():
            notes.append(
                "llama.cpp server is transitioning (start/stop in progress).",
            )
    except Exception:  # pylint: disable=broad-exception-caught
        pass
    return notes


def _slot_is_set(slot: Any) -> bool:
    return bool(getattr(slot, "provider_id", None) and getattr(slot, "model", None))


def _resolve_agent_effective_model_slot(
    agent_cfg: AgentProfileConfig,
    active_slot: Any | None,
) -> tuple[Any | None, str]:
    """Resolve which provider/model an agent will use for its default chat model."""
    if agent_cfg.active_model is not None and _slot_is_set(agent_cfg.active_model):
        return agent_cfg.active_model, "agent.active_model"

    routing = agent_cfg.llm_routing
    if getattr(routing, "enabled", False):
        if routing.mode == "cloud_first":
            if routing.cloud is not None and _slot_is_set(routing.cloud):
                return routing.cloud, "agent.llm_routing.cloud"
            if active_slot is not None and _slot_is_set(active_slot):
                return active_slot, "providers.active_llm (cloud fallback)"
            return None, "routing enabled but no cloud slot and no active LLM"
        # local_first
        if routing.local is not None and _slot_is_set(routing.local):
            return routing.local, "agent.llm_routing.local"
        return None, "routing enabled but local slot is not set"

    if active_slot is not None and _slot_is_set(active_slot):
        return active_slot, "providers.active_llm"
    return None, "no agent.active_model and no active LLM"


async def check_enabled_agents_model_connections(
    cfg: Config,
    *,
    timeout: float,
    deep: bool,
) -> tuple[bool, list[str], list[str]]:
    """Test each enabled agent's effective model connectivity (like UI 'test connection').

    Returns (all_ok, per_agent_lines, extra_notes).
    """
    from ..providers.provider_manager import ProviderManager

    mgr = ProviderManager.get_instance()
    active_slot = mgr.get_active_model()
    lines: list[str] = []
    notes: list[str] = []
    all_ok = True

    for agent_id, ref in cfg.agents.profiles.items():
        if not getattr(ref, "enabled", True):
            continue
        try:
            ac = load_agent_config(agent_id)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            all_ok = False
            lines.append(f"{agent_id}: FAIL — load_agent_config failed ({exc})")
            continue

        slot, source = _resolve_agent_effective_model_slot(ac, active_slot)
        if slot is None:
            all_ok = False
            lines.append(f"{agent_id}: FAIL — no model resolved ({source})")
            continue

        pid = (getattr(slot, "provider_id", "") or "").strip()
        model = (getattr(slot, "model", "") or "").strip()
        if not pid or not model:
            all_ok = False
            lines.append(f"{agent_id}: FAIL — invalid model slot ({source})")
            continue

        provider = mgr.get_provider(pid)
        if provider is None:
            all_ok = False
            lines.append(f"{agent_id}: FAIL — provider not found: {pid!r}")
            continue
        if not getattr(provider, "is_local", False):
            if not (getattr(provider, "base_url", "") or "").strip():
                all_ok = False
                lines.append(f"{agent_id}: FAIL — {pid}: base_url is not set")
                continue
        if getattr(provider, "require_api_key", False) and not (
            getattr(provider, "api_key", "") or ""
        ).strip():
            all_ok = False
            lines.append(f"{agent_id}: FAIL — {pid}: API key is required but not set")
            continue

        if deep and pid == "copaw-local":
            # Only add once (same underlying llama.cpp runtime).
            if not any("llama.cpp" in n for n in notes):
                notes.extend(copaw_local_llm_deep_notes())

        if not getattr(provider, "support_connection_check", True):
            lines.append(
                f"{agent_id}: OK — {pid} / {model} (live check skipped for this provider)",
            )
            continue

        try:
            ok, msg = await provider.check_model_connection(model, timeout=timeout)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            ok, msg = False, str(exc)
        if ok:
            lines.append(f"{agent_id}: OK — {pid} / {model} (reachable)")
            continue

        all_ok = False
        detail = f": {msg}" if msg else ""
        body = f"{pid} / {model} unreachable{detail}"
        if getattr(provider, "is_local", False) or pid in ("ollama", "lmstudio", "copaw-local"):
            hint = active_llm_local_failure_hint(provider, pid)
            if hint:
                body = f"{body}\n{hint}"
        lines.append(f"{agent_id}: FAIL — {body}")

    if not lines:
        return True, ["(no enabled agents)"], notes
    return all_ok, lines, notes


def console_static_diagnostic_notes() -> list[str]:
    """Extra context for the web console bundle (paths, mtime, source-tree npm fix)."""
    from datetime import datetime, timezone

    from ..utils.console_static import (
        CONSOLE_STATIC_ENV,
        find_copaw_source_repo_root,
        resolve_console_static_dir,
    )

    notes: list[str] = []
    env_dir = (os.environ.get(CONSOLE_STATIC_ENV) or "").strip()
    if env_dir:
        notes.append(
            f"{CONSOLE_STATIC_ENV} is set — the app serves console files from that "
            f"path ({env_dir}), not from the package or repo defaults.",
        )
    static = Path(resolve_console_static_dir())
    idx = static / "index.html"
    if idx.is_file():
        try:
            mtime = datetime.fromtimestamp(
                idx.stat().st_mtime,
                tz=timezone.utc,
            ).strftime("%Y-%m-%d %H:%M UTC")
        except OSError:
            mtime = "(unknown)"
        notes.append(
            f"resolved static dir: {static} — index.html present (mtime {mtime})",
        )
    else:
        notes.append(
            f"resolved static dir: {static} — index.html missing",
        )

    npm = shutil.which("npm")
    notes.append(
        "npm on PATH: "
        + (npm if npm else "not found (install Node.js or fix PATH)"),
    )

    repo = find_copaw_source_repo_root()
    if repo is not None:
        notes.append(
            f"source checkout detected at {repo} — bundle console into the package with "
            "`copaw doctor fix -y --only rebuild-console-npm` "
            "(`npm ci && npm run build` in console/, then copy to src/copaw/console/).",
        )
    else:
        notes.append(
            "source checkout not detected (normal for wheel installs) — use a git "
            "checkout to run the npm bundle fix, or point COPAW_CONSOLE_STATIC_DIR at "
            "a directory that contains index.html.",
        )
    return notes


def api_target_mismatch_note(cfg: Config, cli_base: str) -> str | None:
    """Warn when CLI --host/--port disagrees with persisted ``last_api``."""
    host = cfg.last_api.host
    port = cfg.last_api.port
    if host is None and port is None:
        return None
    eff_host = host or "127.0.0.1"
    eff_port = 8088 if port is None else port
    expected = f"http://{eff_host}:{eff_port}".rstrip("/")
    got = cli_base.rstrip("/")
    if got == expected:
        return None
    return (
        f"CLI targets {got!r} but config last_api is {eff_host!r}:{eff_port} — "
        "use the same host/port as the running server, or update last_api in config."
    )

