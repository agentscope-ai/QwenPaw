# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

import click
import httpx
from packaging.version import InvalidVersion, Version

from ..__version__ import __version__
from ..constant import WORKING_DIR
from ..config.utils import read_last_api

_PYPI_JSON_URL = "https://pypi.org/pypi/copaw/json"


@dataclass(frozen=True)
class InstallInfo:
    """Information about the current CoPaw installation."""

    package_dir: str
    python_executable: str
    environment_root: str
    environment_kind: str
    installer: str
    source_type: str
    source_url: str | None = None


@dataclass(frozen=True)
class RunningServiceInfo:
    """Detected CoPaw service endpoint state."""

    is_running: bool
    base_url: str | None = None
    version: str | None = None


def _version_obj(version: str) -> Any:
    """Parse version when possible; otherwise keep the raw string."""
    try:
        return Version(version)
    except InvalidVersion:
        return version


def _is_newer_version(latest: str, current: str) -> bool | None:
    """Return whether latest is newer than current.

    Returns `None` when either version cannot be compared reliably.
    """
    parsed_latest = _version_obj(latest)
    parsed_current = _version_obj(current)
    if isinstance(parsed_latest, str) or isinstance(parsed_current, str):
        if latest == current:
            return False
        return None
    return parsed_latest > parsed_current


def _fetch_latest_version() -> str:
    """Fetch the latest published CoPaw version from PyPI."""
    resp = httpx.get(
        _PYPI_JSON_URL,
        timeout=10.0,
        headers={"Accept": "application/json"},
    )
    resp.raise_for_status()
    data = resp.json()
    version = str(data.get("info", {}).get("version", "")).strip()
    if not version:
        raise click.ClickException(
            "Unable to determine the latest CoPaw version.",
        )
    return version


def _detect_source_type(
    direct_url: dict[str, Any] | None,
) -> tuple[str, str | None]:
    """Classify the current installation origin."""
    if not direct_url:
        return ("pypi", None)

    url = direct_url.get("url")
    dir_info = direct_url.get("dir_info") or {}
    if dir_info.get("editable"):
        return ("editable", url)
    if direct_url.get("vcs_info"):
        return ("vcs", url)
    if isinstance(url, str) and url.startswith("file://"):
        return ("local", url)
    return ("direct-url", url if isinstance(url, str) else None)


def _detect_installation() -> InstallInfo:
    """Inspect the current Python environment and installation style."""
    dist = metadata.distribution("copaw")
    # if installed through uv, installer will be `uv`
    installer = (dist.read_text("INSTALLER") or "pip").strip() or "pip"

    direct_url: dict[str, Any] | None = None
    direct_url_text = dist.read_text("direct_url.json")
    if direct_url_text:
        try:
            direct_url = json.loads(direct_url_text)
        except json.JSONDecodeError:
            direct_url = None

    source_type, source_url = _detect_source_type(direct_url)
    package_dir = Path(__file__).resolve().parent.parent
    python_executable = Path(sys.executable).resolve()
    environment_root = Path(sys.prefix).resolve()
    environment_kind = (
        "virtualenv" if sys.prefix != sys.base_prefix else "system"
    )

    return InstallInfo(
        package_dir=str(package_dir),
        python_executable=str(python_executable),
        environment_root=str(environment_root),
        environment_kind=environment_kind,
        installer=installer,
        source_type=source_type,
        source_url=source_url,
    )


def _probe_service(base_url: str) -> RunningServiceInfo:
    """Probe a possible running CoPaw HTTP service."""
    try:
        resp = httpx.get(
            f"{base_url.rstrip('/')}/api/version",
            timeout=2.0,
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        payload = resp.json()
    except (httpx.HTTPError, ValueError):
        return RunningServiceInfo(is_running=False)

    version = payload.get("version") if isinstance(payload, dict) else None
    return RunningServiceInfo(
        is_running=True,
        base_url=base_url.rstrip("/"),
        version=str(version) if version else None,
    )


def _detect_running_service(
    host: str | None,
    port: int | None,
) -> RunningServiceInfo:
    """Detect whether a CoPaw HTTP service is currently running."""
    candidates: list[str] = []
    seen: set[str] = set()

    def _add_candidate(
        candidate_host: str | None,
        candidate_port: int | None,
    ) -> None:
        if not candidate_host or candidate_port is None:
            return
        base_url = f"http://{candidate_host}:{candidate_port}"
        if base_url in seen:
            return
        seen.add(base_url)
        candidates.append(base_url)

    _add_candidate(host, port)
    last = read_last_api()
    if last:
        _add_candidate(last[0], last[1])
    _add_candidate("127.0.0.1", 8088)

    for base_url in candidates:
        result = _probe_service(base_url)
        if result.is_running:
            return result
    return RunningServiceInfo(is_running=False)


def _build_upgrade_command(
    info: InstallInfo,
    latest_version: str,
) -> tuple[list[str], str]:
    """Build the installer command used by the detached update worker."""
    package_spec = f"copaw=={latest_version}"
    installer = info.installer.lower()
    if installer.startswith("uv") and shutil.which("uv"):
        return (
            [
                "uv",
                "pip",
                "install",
                "--python",
                info.python_executable,
                "--upgrade",
                package_spec,
                "--prerelease=allow",
            ],
            "uv pip",
        )
    return (
        [
            info.python_executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
            package_spec,
            "--disable-pip-version-check",
        ],
        "pip",
    )


def _plan_dir() -> Path:
    """Directory used to persist short-lived update worker plans."""
    return WORKING_DIR / "updates"


def _write_worker_plan(plan: dict[str, Any]) -> Path:
    """Persist a worker plan for the detached process."""
    plan_dir = _plan_dir()
    plan_dir.mkdir(parents=True, exist_ok=True)
    plan_path = plan_dir / f"update-{int(time.time() * 1000)}.json"
    plan_path.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return plan_path


def _spawn_update_worker(plan_path: Path) -> None:
    """Spawn the detached worker that performs the actual package upgrade."""
    worker_code = (
        "from copaw.cli.update_cmd import run_update_worker; "
        "import sys; "
        "sys.exit(run_update_worker(sys.argv[1]))"
    )
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": None,
        "stderr": None,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(
            subprocess,
            "CREATE_NEW_PROCESS_GROUP",
            0,
        )
    else:
        kwargs["start_new_session"] = True

    subprocess.Popen(  # pylint: disable=consider-using-with
        [sys.executable, "-u", "-c", worker_code, str(plan_path)],
        **kwargs,
    )


def _load_worker_plan(plan_path: str | Path) -> dict[str, Any]:
    """Load a persisted worker plan."""
    return json.loads(Path(plan_path).read_text(encoding="utf-8"))


def run_update_worker(plan_path: str | Path) -> int:
    """Run the detached update worker and stream installer output."""
    path = Path(plan_path)
    plan = _load_worker_plan(path)
    command = [str(part) for part in plan["command"]]

    click.echo("")
    click.echo(
        "[copaw] Updating CoPaw "
        f"{plan['current_version']} -> {plan['latest_version']}...",
    )
    click.echo(f"[copaw] Using installer: {plan['installer_label']}")

    try:
        with subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        ) as proc:
            if proc.stdout is not None:
                for line in proc.stdout:
                    click.echo(line.rstrip())
            return_code = proc.wait()
    except FileNotFoundError as exc:
        click.echo(f"[copaw] Update failed: {exc}")
        return_code = 1
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    if return_code == 0:
        click.echo("[copaw] Update completed successfully.")
        click.echo(
            "[copaw] Please restart any running CoPaw service "
            "to use the new version.",
        )
    else:
        click.echo(f"[copaw] Update failed with exit code {return_code}.")
        click.echo(
            "[copaw] Please fix the error above and run "
            "`copaw update` again.",
        )

    return return_code


def _echo_install_summary(info: InstallInfo, latest_version: str) -> None:
    """Print the update summary shown before launching the worker."""
    click.echo(f"Current version: {__version__}")
    click.echo(f"Latest version:  {latest_version}")
    click.echo(f"Python:          {info.python_executable}")
    click.echo(
        f"Environment:     {info.environment_kind} "
        f"({info.environment_root})",
    )
    click.echo(f"Install path:    {info.package_dir}")
    click.echo(f"Installer:       {info.installer}")


def _confirm_source_override(info: InstallInfo, yes: bool) -> bool:
    """Confirm whether a non-PyPI installation should be overwritten."""
    if info.source_type == "pypi":
        return True

    detail = f" ({info.source_url})" if info.source_url else ""
    message = (
        "Detected a non-PyPI installation source: "
        f"{info.source_type}{detail}. Updating will overwrite the current "
        "installation with the PyPI release for this environment."
    )

    if yes:
        click.echo(
            f"Warning: {message} Proceeding because `--yes` was provided.",
        )
        return True

    click.echo(f"Warning: {message}")
    return click.confirm(
        "Continue and replace the current installation with the PyPI "
        "version?",
        default=False,
    )


@click.command("update")
@click.option(
    "--yes",
    is_flag=True,
    help="Do not prompt before starting the update",
)
@click.pass_context
def update_cmd(ctx: click.Context, yes: bool) -> None:
    """Upgrade CoPaw in the current Python environment."""
    info = _detect_installation()
    latest_version = _fetch_latest_version()

    _echo_install_summary(info, latest_version)

    version_check = _is_newer_version(latest_version, __version__)
    if version_check is False:
        click.echo("CoPaw is already up to date.")
        return

    if not _confirm_source_override(info, yes):
        click.echo("Cancelled.")
        return

    if version_check is None:
        if yes:
            click.echo(
                "Warning: unable to compare the current version"
                f"({__version__}) with the latest version ({latest_version})"
                " automatically. Proceeding because `--yes` was provided.",
            )
        elif not click.confirm(
            f"Unable to compare the current version ({__version__}) with the "
            f"latest version ({latest_version}) automatically. Continue with "
            "update anyway?",
            default=False,
        ):
            click.echo("Cancelled.")
            return

    running = _detect_running_service(
        ctx.obj.get("host") if ctx.obj else None,
        ctx.obj.get("port") if ctx.obj else None,
    )
    if running.is_running:
        version_suffix = (
            f" (version {running.version})" if running.version else ""
        )
        raise click.ClickException(
            "Detected a running CoPaw service at "
            f"{running.base_url}{version_suffix}. "
            "Please stop it before running `copaw update`.",
        )

    if not yes and not click.confirm(
        f"Update CoPaw to {latest_version} in the current environment?",
        default=True,
    ):
        click.echo("Cancelled.")
        return

    command, installer_label = _build_upgrade_command(info, latest_version)
    plan = {
        "current_version": __version__,
        "latest_version": latest_version,
        "installer_label": installer_label,
        "command": command,
        "install": asdict(info),
    }
    plan_path = _write_worker_plan(plan)
    _spawn_update_worker(plan_path)

    click.echo("")
    click.echo("Update process started in a separate process.")
    click.echo(
        "Wait for the installer output below, then restart CoPaw "
        "after it finishes.",
    )
