# -*- coding: utf-8 -*-
"""Conservative filesystem repairs for ``qwenpaw doctor fix``.

Backup, allowlist, atomic write. Includes ``reconcile-workspace-skills``,
which calls the same ``reconcile_workspace_manifest`` as the app (CLI-only,
no server).

``rebuild-console-npm`` runs ``npm ci && npm run build`` under ``console/``
in a source checkout and copies ``console/dist`` into
``src/qwenpaw/console/`` (needs network for npm).

``validate-all-jobs-json`` reuses
:func:`~qwenpaw.cli.doctor_checks.check_cron_jobs_files` (read-only); exits
non-zero on FAIL (for CI).

``doctor fix --non-interactive`` allows only :data:`NONINTERACTIVE_FIX_IDS`
(safe + read-only validation + workspace skill reconcile); rejects risky ids
even with ``-y``.
"""
from __future__ import annotations

# pylint: disable=too-many-branches,too-many-statements
# pylint: disable=too-many-return-statements
import json
import os
import secrets
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..__version__ import __version__
from ..agents.skills_manager import (
    get_workspace_skill_manifest_path,
    reconcile_workspace_manifest,
)
from ..app.crons.models import JobsFile, ScheduleSpec
from ..config import load_config
from ..config.config import (
    AgentProfileConfig,
    build_fallback_agent_profile_config,
)
from ..config.utils import (
    _normalize_working_dir_bound_paths,
    read_last_api,
    strict_validate_config_file,
)
from ..constant import JOBS_FILE, WORKING_DIR
from ..utils.console_static import find_qwenpaw_source_repo_root
from .doctor_checks import check_cron_jobs_files

SAFE_FIX_IDS = frozenset({"ensure-working-dir", "ensure-workspace-dirs"})
# Read-only: validate every workspace + legacy jobs.json (no writes; no
# --yes).
READONLY_FIX_IDS = frozenset({"validate-all-jobs-json"})
# Sync workspace ``skill.json`` with ``skills/`` (same as app reconcile);
# no --yes.
SYNC_FIX_IDS = frozenset({"reconcile-workspace-skills"})
# Mutating fixes: require --yes (may create agent.json / jobs.json or rewrite
# jobs).
RISKY_FIX_IDS = frozenset(
    {
        "seed-missing-agent-json",
        "reset-invalid-agent-json",
        "write-empty-jobs-json",
        "normalize-jobs-cron",
        "rebuild-console-npm",
    },
)
ALL_FIX_IDS = SAFE_FIX_IDS | READONLY_FIX_IDS | SYNC_FIX_IDS | RISKY_FIX_IDS
# Subset allowed with ``doctor fix --non-interactive`` (CI / upgrade scripts).
NONINTERACTIVE_FIX_IDS = SAFE_FIX_IDS | READONLY_FIX_IDS | SYNC_FIX_IDS

BACKUP_SUBDIR = "doctor-fix-backups"


def _utc_session_id() -> str:
    return (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + secrets.token_hex(4)
    )


def _working_dir_resolved(working_dir: Path) -> Path:
    return working_dir.expanduser().resolve()


def workspace_under_working_dir(workspace: Path, wd: Path) -> bool:
    try:
        workspace.resolve().relative_to(wd.resolve())
        return True
    except ValueError:
        return False


def path_allowed_for_write(target: Path, wd: Path) -> bool:
    """Allow writes only under ``WORKING_DIR`` (resolved)."""
    try:
        target.resolve().relative_to(wd.resolve())
        return True
    except ValueError:
        return False


def _relative_under_wd(path: Path, wd: Path) -> Path:
    return path.resolve().relative_to(wd.resolve())


def _normalize_cron_fields_in_jobs_dict(data: dict[str, Any]) -> bool:
    """Mutate *data* (``jobs.json`` root dict) so each job schedule matches
    ``ScheduleSpec`` normalization. Compares against on-disk strings before
    validation (``JobsFile`` validation already normalizes in memory).

    Returns whether any ``cron`` or ``timezone`` field was updated.
    """
    jobs = data.get("jobs")
    if not isinstance(jobs, list):
        return False
    changed = False
    for j in jobs:
        if not isinstance(j, dict):
            continue
        sch = j.get("schedule")
        if not isinstance(sch, dict):
            continue
        cron = sch.get("cron")
        if not isinstance(cron, str):
            continue
        tz_raw = sch.get("timezone", "UTC")
        tz = tz_raw if isinstance(tz_raw, str) else "UTC"
        jid = j.get("id", "?")
        try:
            ns = ScheduleSpec(type="cron", cron=cron, timezone=tz)
        except ValueError:
            raise ValueError(f"job {jid!r}: invalid cron {cron!r}") from None
        if ns.cron != cron:
            sch["cron"] = ns.cron
            changed = True
        if ns.timezone != tz:
            sch["timezone"] = ns.timezone
            changed = True
    return changed


def _workspace_agent_json_valid(path: Path) -> bool:
    """Same validity criteria as ``check_agent_json_profiles``."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(raw, dict):
        return False
    try:
        raw = _normalize_working_dir_bound_paths(raw)
    except Exception:  # pylint: disable=broad-exception-caught
        pass
    try:
        AgentProfileConfig.model_validate(raw)
    except Exception:  # pylint: disable=broad-exception-caught
        return False
    return True


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode("utf-8")
    tmp = path.with_name(f"{path.name}.tmp.{secrets.token_hex(8)}")
    try:
        tmp.write_bytes(data)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _backup_one_file(session_files: Path, path: Path, wd: Path) -> None:
    rel = _relative_under_wd(path, wd)
    dest = session_files / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        shutil.copy2(path, dest)
    else:
        marker = dest.with_suffix(dest.suffix + ".MISSING")
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("", encoding="utf-8")


def _effective_cli_api_host_port(
    host_override: str | None,
    port_override: int | None,
) -> tuple[str, int]:
    """Match ``main.cli`` host/port resolution for backup audit metadata."""
    host, port = host_override, port_override
    if host is None or port is None:
        last = read_last_api()
        if last:
            host = host or last[0]
            port = port or last[1]
    return host or "127.0.0.1", port or 8088


def _write_meta(
    session_dir: Path,
    argv: list[str],
    fix_ids: list[str],
    backed_paths: list[str],
    *,
    working_dir: str,
    dry_run: bool,
    yes: bool,
    no_backup: bool,
    non_interactive: bool,
    cli_api_host: str | None,
    cli_api_port: int | None,
) -> None:
    cfg = load_config()
    ch, cp = _effective_cli_api_host_port(cli_api_host, cli_api_port)
    meta = {
        "qwenpaw_version": __version__,
        "utc": datetime.now(timezone.utc).isoformat(),
        "argv": argv,
        "fix_ids": fix_ids,
        "backed_up_files_relative": backed_paths,
        "working_dir": working_dir,
        "dry_run": dry_run,
        "yes": yes,
        "no_backup": no_backup,
        "non_interactive": non_interactive,
        "config_last_api": {
            "host": cfg.last_api.host,
            "port": cfg.last_api.port,
        },
        "cli_resolved_api": {
            "host": ch,
            "port": cp,
            "base_url": f"http://{ch}:{cp}",
        },
        "restore_hint": (
            "Copy files from the 'files/' subtree back to your working dir "
            "with the same relative paths."
        ),
    }
    (session_dir / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


@dataclass(frozen=True)
class PlannedFix:
    fix_id: str
    description: str
    paths_to_backup: tuple[Path, ...]
    apply_fn: Callable[[], None]


def _parse_only(only: str | None) -> list[str]:
    if not only or not only.strip():
        return sorted(SAFE_FIX_IDS)
    ids = [x.strip() for x in only.split(",") if x.strip()]
    bad = [x for x in ids if x not in ALL_FIX_IDS]
    if bad:
        raise ValueError(
            f"unknown fix id(s): {bad!r}; known: {sorted(ALL_FIX_IDS)}",
        )
    return ids


def _plan_fixes(
    fix_ids: list[str],
    wd: Path,
    yes: bool,
    *,
    dry_run: bool = False,
    no_backup: bool = False,
) -> tuple[list[str], list[PlannedFix]]:
    """Return (skip_messages, planned operations)."""
    if fix_ids:
        for fid in fix_ids:
            if fid in RISKY_FIX_IDS and not yes and not dry_run:
                raise ValueError(
                    f"fix {fid!r} requires --yes (-y) to apply "
                    "(may modify files or run external tools such as npm). "
                    "Use `qwenpaw doctor fix --dry-run --only ...` to preview "
                    "the plan without -y.",
                )

    needs_existing_wd = bool(
        set(fix_ids)
        & {
            "ensure-workspace-dirs",
            "seed-missing-agent-json",
            "reset-invalid-agent-json",
            "write-empty-jobs-json",
            "reconcile-workspace-skills",
            "normalize-jobs-cron",
        },
    )
    if (
        needs_existing_wd
        and not wd.is_dir()
        and "ensure-working-dir" not in fix_ids
    ):
        raise ValueError(
            f"working directory {wd} does not exist; include "
            "ensure-working-dir in --only or run `qwenpaw doctor fix` without "
            "--only (safe fixes include it when needed).",
        )

    skip_msgs: list[str] = []
    planned: list[PlannedFix] = []

    if "ensure-working-dir" in fix_ids:
        if not wd.is_dir():
            parent = wd.parent
            if not parent.is_dir():
                raise ValueError(
                    f"refusing to create {wd}: parent directory does not "
                    f"exist: {parent}",
                )
            if not os.access(parent, os.W_OK):
                raise ValueError(
                    f"refusing to create {wd}: parent not writable: {parent}",
                )

            def _mk(wdir: Path = wd) -> None:
                wdir.mkdir(mode=0o700, exist_ok=False)

            planned.append(
                PlannedFix(
                    "ensure-working-dir",
                    f"create working directory {wd}",
                    (),
                    _mk,
                ),
            )

    config_ok, _cfg_msg = strict_validate_config_file()
    cfg = None
    if config_ok:
        try:
            cfg = load_config()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            skip_msgs.append(
                f"config-dependent fixes skipped: load_config failed: {exc}",
            )
            cfg = None

    if "validate-all-jobs-json" in fix_ids:
        if cfg is None:
            skip_msgs.append(
                "validate-all-jobs-json: skipped (root config invalid or "
                "load_config failed)",
            )
        else:
            ok, det = check_cron_jobs_files(cfg)
            skip_msgs.append(
                f"validate-all-jobs-json: {'OK' if ok else 'FAIL'} — {det}",
            )

    if cfg is not None and "ensure-workspace-dirs" in fix_ids:
        for agent_id, ref in cfg.agents.profiles.items():
            wsp = Path(ref.workspace_dir).expanduser()
            if not workspace_under_working_dir(wsp, wd):
                continue
            if wsp.is_dir():
                continue
            desc = f"mkdir workspace for agent {agent_id!r}: {wsp}"

            def _mk_ws(p: Path = wsp, root: Path = wd) -> None:
                if not path_allowed_for_write(p, root):
                    raise RuntimeError(f"path not allowed: {p}")
                p.mkdir(mode=0o700, parents=True, exist_ok=True)

            planned.append(
                PlannedFix(
                    "ensure-workspace-dirs",
                    desc,
                    (),
                    _mk_ws,
                ),
            )

    if cfg is not None and "seed-missing-agent-json" in fix_ids:
        for agent_id in cfg.agents.profiles:
            ref = cfg.agents.profiles[agent_id]
            wsp = Path(ref.workspace_dir).expanduser()
            if not workspace_under_working_dir(wsp, wd):
                continue
            agent_json = wsp / "agent.json"
            if agent_json.exists():
                continue
            if not wsp.is_dir():
                continue

            profile = build_fallback_agent_profile_config(agent_id, cfg)
            payload = profile.model_dump(exclude_none=True)
            text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
            AgentProfileConfig.model_validate(json.loads(text))

            def _seed(
                aj: Path = agent_json,
                body: str = text,
                root: Path = wd,
            ) -> None:
                if aj.exists():
                    return
                if not path_allowed_for_write(aj, root):
                    raise RuntimeError(f"path not allowed: {aj}")
                _atomic_write_text(aj, body)

            planned.append(
                PlannedFix(
                    "seed-missing-agent-json",
                    f"write initial {agent_json} from root config defaults",
                    (agent_json,),
                    _seed,
                ),
            )

    if cfg is not None and "reset-invalid-agent-json" in fix_ids:
        for agent_id in cfg.agents.profiles:
            ref = cfg.agents.profiles[agent_id]
            wsp = Path(ref.workspace_dir).expanduser()
            if not workspace_under_working_dir(wsp, wd):
                continue
            if not wsp.is_dir():
                continue
            agent_json = wsp / "agent.json"
            if not agent_json.is_file():
                continue
            if _workspace_agent_json_valid(agent_json):
                continue
            profile = build_fallback_agent_profile_config(agent_id, cfg)
            payload = profile.model_dump(exclude_none=True)
            text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
            AgentProfileConfig.model_validate(json.loads(text))

            def _reset(
                aj: Path = agent_json,
                body: str = text,
                root: Path = wd,
            ) -> None:
                if not path_allowed_for_write(aj, root):
                    raise RuntimeError(f"path not allowed: {aj}")
                _atomic_write_text(aj, body)

            planned.append(
                PlannedFix(
                    "reset-invalid-agent-json",
                    f"replace invalid {agent_json} with root config defaults "
                    "(backup first)",
                    (agent_json,),
                    _reset,
                ),
            )

    if cfg is not None and "write-empty-jobs-json" in fix_ids:
        empty = JobsFile(version=1, jobs=[])
        body = (
            json.dumps(empty.model_dump(), ensure_ascii=False, indent=2) + "\n"
        )
        JobsFile.model_validate(json.loads(body))

        for agent_id in cfg.agents.profiles:
            ref = cfg.agents.profiles[agent_id]
            wsp = Path(ref.workspace_dir).expanduser()
            if not workspace_under_working_dir(wsp, wd):
                continue
            jp = wsp / JOBS_FILE
            if jp.exists():
                continue
            if not wsp.is_dir():
                continue

            def _jobs(
                p: Path = jp,
                b: str = body,
                root: Path = wd,
            ) -> None:
                if p.exists():
                    return
                if not path_allowed_for_write(p, root):
                    raise RuntimeError(f"path not allowed: {p}")
                _atomic_write_text(p, b)

            planned.append(
                PlannedFix(
                    "write-empty-jobs-json",
                    f"write empty {jp} (version=1, jobs=[])",
                    (jp,),
                    _jobs,
                ),
            )

    if cfg is not None and "reconcile-workspace-skills" in fix_ids:
        for agent_id, ref in cfg.agents.profiles.items():
            wsp = Path(ref.workspace_dir).expanduser()
            if not workspace_under_working_dir(wsp, wd):
                continue
            if not wsp.is_dir():
                continue
            mp = get_workspace_skill_manifest_path(wsp)
            backup_paths: tuple[Path, ...] = (mp,) if mp.is_file() else ()

            def _rec(ws: Path = wsp, root: Path = wd) -> None:
                if not workspace_under_working_dir(ws, root):
                    raise RuntimeError(f"path not allowed: {ws}")
                reconcile_workspace_manifest(ws)

            planned.append(
                PlannedFix(
                    "reconcile-workspace-skills",
                    f"reconcile skill.json with skills/ for agent "
                    f"{agent_id!r} ({wsp})",
                    backup_paths,
                    _rec,
                ),
            )

    if cfg is not None and "normalize-jobs-cron" in fix_ids:
        for agent_id, ref in cfg.agents.profiles.items():
            wsp = Path(ref.workspace_dir).expanduser()
            if not workspace_under_working_dir(wsp, wd):
                continue
            if not wsp.is_dir():
                continue
            jp = wsp / JOBS_FILE
            if not jp.is_file():
                continue
            try:
                raw = json.loads(jp.read_text(encoding="utf-8"))
            except Exception as exc:  # pylint: disable=broad-exception-caught
                skip_msgs.append(
                    f"{agent_id}: {jp.name} invalid or unreadable — "
                    f"skip normalize-jobs-cron ({exc})",
                )
                continue
            if not isinstance(raw, dict):
                skip_msgs.append(
                    f"{agent_id}: {jp.name} root must be a JSON object — "
                    "skip normalize-jobs-cron",
                )
                continue
            try:
                if not _normalize_cron_fields_in_jobs_dict(raw):
                    continue
            except ValueError as exc:
                skip_msgs.append(f"{agent_id}: {exc}")
                continue
            try:
                jf = JobsFile.model_validate(raw)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                skip_msgs.append(
                    f"{agent_id}: {jp.name} invalid after cron normalize — "
                    f"skip ({exc})",
                )
                continue
            body = (
                json.dumps(
                    jf.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n"
            )

            def _write_norm(
                jpath: Path = jp,
                text: str = body,
                root: Path = wd,
            ) -> None:
                if not path_allowed_for_write(jpath, root):
                    raise RuntimeError(f"path not allowed: {jpath}")
                _atomic_write_text(jpath, text)

            planned.append(
                PlannedFix(
                    "normalize-jobs-cron",
                    f"normalize cron day-of-week fields in {jp}",
                    (jp,),
                    _write_norm,
                ),
            )

    if "rebuild-console-npm" in fix_ids:
        repo = find_qwenpaw_source_repo_root()
        if repo is None:
            skip_msgs.append(
                "rebuild-console-npm: only in a QwenPaw source checkout "
                "(./console/package.json + ./console/package-lock.json + "
                "./src/qwenpaw/)",
            )
        elif not shutil.which("npm"):
            skip_msgs.append("rebuild-console-npm: npm not found on PATH")
        else:
            console = repo / "console"
            dist = console / "dist"
            dst = repo / "src" / "qwenpaw" / "console"
            desc = (
                f"npm ci + npm run build in {console}, then copy {dist} -> "
                f"{dst} (bundles web UI for editable installs)"
            )

            def _rebuild_console(
                r: Path = repo,
                cdir: Path = console,
                dist_dir: Path = dist,
                target: Path = dst,
                skip_prev_backup: bool = no_backup,
            ) -> None:
                if not cdir.is_dir():
                    raise RuntimeError(f"missing console directory: {cdir}")
                if not (cdir / "package-lock.json").is_file():
                    raise RuntimeError(
                        f"missing {cdir / 'package-lock.json'} "
                        "(npm ci needs a lockfile)",
                    )
                if (
                    not skip_prev_backup
                    and target.exists()
                    and any(target.iterdir())
                ):
                    bkp_root = r / ".qwenpaw-doctor-fix-backups"
                    sid = _utc_session_id()
                    bkp = bkp_root / sid
                    prev = bkp / "previous-console-bundle"
                    prev.parent.mkdir(parents=True, exist_ok=True)
                    if prev.exists():
                        shutil.rmtree(prev)
                    shutil.copytree(target, prev)
                    bkp.mkdir(parents=True, exist_ok=True)
                    meta = {
                        "qwenpaw_version": __version__,
                        "previous_bundle": str(prev),
                    }
                    (bkp / "meta.json").write_text(
                        json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8",
                    )
                subprocess.run(
                    ["npm", "ci"],
                    cwd=str(cdir),
                    check=True,
                    env=os.environ.copy(),
                )
                subprocess.run(
                    ["npm", "run", "build"],
                    cwd=str(cdir),
                    check=True,
                    env=os.environ.copy(),
                )
                if (
                    not dist_dir.is_dir()
                    or not (dist_dir / "index.html").is_file()
                ):
                    raise RuntimeError(
                        f"after npm run build, expected "
                        f"{dist_dir / 'index.html'}",
                    )
                if target.exists():
                    shutil.rmtree(target)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(dist_dir, target)

            planned.append(
                PlannedFix(
                    "rebuild-console-npm",
                    desc,
                    (),
                    _rebuild_console,
                ),
            )

    return skip_msgs, planned


def run_doctor_fix(
    *,
    dry_run: bool,
    yes: bool,
    only: str | None,
    no_backup: bool,
    backup_dir: Path | None,
    working_dir: Path | None,
    echo: Callable[[str], None],
    echo_err: Callable[[str], None],
    confirm_fn: Callable[[str], bool] | None,
    argv: list[str] | None = None,
    cli_api_host: str | None = None,
    cli_api_port: int | None = None,
    non_interactive: bool = False,
) -> int:
    """Run planned fixes.

    Returns 0 on success or user abort without writes; 1 on error.
    """
    wd = _working_dir_resolved(working_dir or WORKING_DIR)
    argv = argv if argv is not None else sys.argv

    try:
        fix_ids = _parse_only(only)
    except ValueError as exc:
        echo_err(str(exc))
        return 1

    if non_interactive:
        disallowed = sorted(set(fix_ids) - NONINTERACTIVE_FIX_IDS)
        if disallowed:
            echo_err(
                "--non-interactive allows only "
                f"{sorted(NONINTERACTIVE_FIX_IDS)}; disallowed: {disallowed}",
            )
            return 1

    try:
        skip_msgs, planned = _plan_fixes(
            fix_ids,
            wd,
            yes=yes,
            dry_run=dry_run,
            no_backup=no_backup,
        )
    except ValueError as exc:
        echo_err(str(exc))
        return 1

    for msg in skip_msgs:
        echo(f"  (note) {msg}")

    validate_failed = any(
        m.startswith("validate-all-jobs-json: FAIL") for m in skip_msgs
    )

    if not planned:
        if any(m.startswith("validate-all-jobs-json:") for m in skip_msgs):
            echo(
                "(read-only jobs.json validation complete; no file changes "
                "planned.)",
            )
            return 1 if validate_failed else 0
        echo("Nothing to do (already satisfied).")
        return 0

    echo("Planned operations:")
    for p in planned:
        echo(f"  [{p.fix_id}] {p.description}")

    if dry_run:
        echo("(dry-run: no files modified)")
        return 1 if validate_failed else 0

    if no_backup:
        echo_err(
            "WARNING: --no-backup — no copies under doctor-fix-backups if "
            "something goes wrong.",
        )

    skip_confirm = yes or non_interactive
    if not skip_confirm:
        fn = confirm_fn or (lambda _m: False)
        if not fn("Apply these changes?"):
            echo("Aborted (no changes written).")
            return 0

    mkdir_wd_ops = [p for p in planned if p.fix_id == "ensure-working-dir"]
    rest_ops = [p for p in planned if p.fix_id != "ensure-working-dir"]

    try:
        for p in mkdir_wd_ops:
            p.apply_fn()
    except Exception as exc:  # pylint: disable=broad-exception-caught
        echo_err(f"Stopped after error: {exc}")
        return 1

    wd = _working_dir_resolved(working_dir or WORKING_DIR)
    if not wd.is_dir():
        echo_err(f"working directory still missing after fixes: {wd}")
        return 1

    session_dir: Path | None = None
    session_files: Path | None = None
    backed_rels: list[str] = []

    if not no_backup:
        base = _working_dir_resolved(backup_dir) if backup_dir else wd
        if not base.is_dir():
            echo_err(f"backup base directory missing: {base}")
            return 1
        try:
            base.relative_to(wd)
        except ValueError:
            if backup_dir is not None:
                echo_err("--backup-dir must be inside the working directory.")
                return 1

        session_dir = base / BACKUP_SUBDIR / _utc_session_id()
        session_files = session_dir / "files"
        session_dir.mkdir(parents=True, exist_ok=True)

    all_applied_ids: list[str] = [p.fix_id for p in mkdir_wd_ops]

    try:
        for p in rest_ops:
            for path in p.paths_to_backup:
                if not path_allowed_for_write(path, wd):
                    raise RuntimeError(
                        f"refusing to touch disallowed path: {path}",
                    )
                if session_files is not None and path.is_file():
                    _backup_one_file(session_files, path, wd)
                    backed_rels.append(str(_relative_under_wd(path, wd)))
            p.apply_fn()
            all_applied_ids.append(p.fix_id)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        echo_err(f"Stopped after error (no further operations): {exc}")
        if session_dir is not None:
            echo_err(f"Partial backup may be under: {session_dir}")
        return 1

    if session_dir is not None and session_files is not None:
        _write_meta(
            session_dir,
            list(argv),
            all_applied_ids,
            backed_rels,
            working_dir=str(wd),
            dry_run=dry_run,
            yes=yes,
            no_backup=no_backup,
            non_interactive=non_interactive,
            cli_api_host=cli_api_host,
            cli_api_port=cli_api_port,
        )
        echo(f"Backup session: {session_dir}")

    echo("Done.")
    return 1 if validate_failed else 0
