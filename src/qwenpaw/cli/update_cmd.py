# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import signal
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from importlib import metadata
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import click
import httpx
from packaging.version import InvalidVersion, Version

from ..__version__ import __version__
from ..constant import WORKING_DIR
from ..config.utils import read_last_api
from .process_utils import (
    _base_url,
    _candidate_hosts,
    _extract_port_from_command,
    _is_qwenpaw_service_command,
    _process_table,
)

_PYPI_JSON_URL = "https://pypi.org/pypi/qwenpaw/json"


def _subprocess_text_kwargs() -> dict[str, Any]:
    """Return robust text-decoding settings for subprocess output.

    Package installers may emit UTF-8 regardless of the active Windows code
    page. Using replacement for undecodable bytes prevents the update worker
    from crashing while streaming output.
    """
    return {
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }


@dataclass(frozen=True)
class InstallInfo:
    """Information about the current QwenPaw installation."""

    package_dir: str
    python_executable: str
    environment_root: str
    environment_kind: str
    installer: str
    source_type: str
    source_url: str | None = None


@dataclass(frozen=True)
class RunningServiceInfo:
    """Detected QwenPaw service endpoint state."""

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
    """Fetch the latest published QwenPaw version from PyPI."""
    try:
        resp = httpx.get(
            _PYPI_JSON_URL,
            timeout=10.0,
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as exc:
        raise click.ClickException(
            f"Failed to fetch the latest QwenPaw version from PyPI: {exc}",
        ) from exc
    except json.JSONDecodeError as exc:
        raise click.ClickException(
            "Received an invalid response from PyPI when checking for the "
            f"latest QwenPaw version: {exc}",
        ) from exc
    version = str(data.get("info", {}).get("version", "")).strip()
    if not version:
        raise click.ClickException(
            "Unable to determine the latest QwenPaw version.",
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
    dist = metadata.distribution("qwenpaw")
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
    python_executable = sys.executable
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
    """Probe a possible running QwenPaw HTTP service."""
    try:
        resp = httpx.get(
            f"{base_url.rstrip('/')}/api/version",
            timeout=2.0,
            headers={"Accept": "application/json"},
            trust_env=False,
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


def _process_candidate_ports() -> list[int]:
    """Infer candidate local QwenPaw service ports from running processes."""
    ports: list[int] = []
    for _pid, command in _process_table():
        if not _is_qwenpaw_service_command(command):
            continue

        port = _extract_port_from_command(command)
        if port not in ports:
            ports.append(port)
    return ports


def _detect_running_service_from_processes(
    preferred_hosts: list[str],
) -> RunningServiceInfo:
    """Best-effort local process fallback for service detection."""
    for port in _process_candidate_ports():
        hosts = preferred_hosts or ["127.0.0.1", "localhost"]
        for host in hosts:
            result = _probe_service(_base_url(host, port))
            if result.is_running:
                return result

        fallback_host = next(iter(hosts), "127.0.0.1")
        return RunningServiceInfo(
            is_running=True,
            base_url=_base_url(fallback_host, port),
        )

    return RunningServiceInfo(is_running=False)


def _detect_running_service(
    host: str | None,
    port: int | None,
) -> RunningServiceInfo:
    """Detect whether a QwenPaw HTTP service is currently running."""
    candidates: list[str] = []
    seen: set[str] = set()
    preferred_hosts: list[str] = []

    def _remember_hosts(candidate_host: str | None) -> None:
        for item in _candidate_hosts(candidate_host):
            if item not in preferred_hosts:
                preferred_hosts.append(item)

    def _add_candidate(
        candidate_host: str | None,
        candidate_port: int | None,
    ) -> None:
        if not candidate_host or candidate_port is None:
            return
        _remember_hosts(candidate_host)
        for resolved_host in _candidate_hosts(candidate_host):
            base_url = _base_url(resolved_host, candidate_port)
            if base_url in seen:
                continue
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

    return _detect_running_service_from_processes(preferred_hosts)


def _running_service_display(running: RunningServiceInfo) -> str:
    """Build a concise running-service description for user prompts."""
    if not running.base_url:
        return "a running QwenPaw service"
    version_suffix = f" (version {running.version})" if running.version else ""
    return f"QwenPaw service at {running.base_url}{version_suffix}"


def _confirm_force_shutdown(running: RunningServiceInfo) -> bool:
    """Ask whether `qwenpaw shutdown` should be used before updating."""
    click.echo("")
    click.secho("!" * 72, fg="yellow", bold=True)
    click.secho(
        "WARNING: RUNNING QWENPAW SERVICE DETECTED",
        fg="yellow",
        bold=True,
    )
    click.secho("!" * 72, fg="yellow", bold=True)
    click.secho(
        f"Detected {_running_service_display(running)}.",
        fg="yellow",
        bold=True,
    )
    click.secho(
        "Running `qwenpaw shutdown` will forcibly terminate the current "
        "QwenPaw backend/frontend processes.",
        fg="red",
        bold=True,
    )
    click.secho(
        "Active requests, background tasks, or unsaved work may be "
        "interrupted immediately.",
        fg="red",
        bold=True,
    )
    click.echo("")
    return click.confirm(
        "Run `qwenpaw shutdown` now and continue with the update?",
        default=False,
    )


def _run_shutdown_for_update(
    info: InstallInfo,
    running: RunningServiceInfo,
) -> None:
    """Run `qwenpaw shutdown` in the current environment before updating."""
    command = [info.python_executable, "-m", "qwenpaw"]
    parsed = urlparse(running.base_url or "")
    if parsed.port is not None:
        command.extend(["--port", str(parsed.port)])
    command.append("shutdown")

    click.echo("")
    click.echo("Running `qwenpaw shutdown` before updating...")

    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            **_subprocess_text_kwargs(),
            check=False,
        )
    except OSError as exc:
        raise click.ClickException(
            "Failed to run `qwenpaw shutdown`: " f"{exc}",
        ) from exc

    output = (result.stdout or "").strip()
    if output:
        click.echo(output)

    if result.returncode != 0:
        raise click.ClickException(
            "`qwenpaw shutdown` failed. Please stop the running QwenPaw "
            "service manually before running `qwenpaw update`.",
        )


def _build_upgrade_command(
    info: InstallInfo,
    latest_version: str,
) -> tuple[list[str], str]:
    """Build the installer command used by the detached update worker."""
    package_spec = f"qwenpaw=={latest_version}"
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


def _spawn_update_worker(
    plan_path: Path,
    *,
    capture_output: bool = True,
) -> subprocess.Popen[str]:
    """Spawn the worker that performs the actual package upgrade."""
    worker_code = (
        "from qwenpaw.cli.update_cmd import run_update_worker; "
        "import sys; "
        "sys.exit(run_update_worker(sys.argv[1]))"
    )
    kwargs: dict[str, Any] = {"stdin": subprocess.DEVNULL}
    if capture_output:
        kwargs.update(
            {
                "stdout": subprocess.PIPE,
                "stderr": subprocess.STDOUT,
                **_subprocess_text_kwargs(),
                "bufsize": 1,
            },
        )
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(
            subprocess,
            "CREATE_NEW_PROCESS_GROUP",
            0,
        )
    else:
        kwargs["start_new_session"] = True

    return subprocess.Popen(  # pylint: disable=consider-using-with
        [sys.executable, "-u", "-c", worker_code, str(plan_path)],
        **kwargs,
    )


def _terminate_update_worker(proc: subprocess.Popen[str]) -> None:
    """Best-effort termination for the worker and its installer child."""
    if proc.poll() is not None:
        return

    try:
        if sys.platform == "win32":
            ctrl_break = getattr(signal, "CTRL_BREAK_EVENT", None)
            if ctrl_break is not None:
                proc.send_signal(ctrl_break)
                try:
                    proc.wait(timeout=5)
                    return
                except subprocess.TimeoutExpired:
                    pass
            proc.terminate()
        else:
            os.killpg(proc.pid, signal.SIGTERM)
    except (OSError, ProcessLookupError, ValueError):
        return

    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except OSError:
            return


def _wait_for_process_exit(pid: int | None, timeout: float = 15.0) -> None:
    """Wait briefly for another process to exit before updating files."""
    if pid is None or pid <= 0:
        return

    if sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            synchronize = 0x00100000
            wait_timeout = 0x00000102
            handle = kernel32.OpenProcess(synchronize, False, pid)
            if not handle:
                return
            try:
                result = kernel32.WaitForSingleObject(
                    handle,
                    max(0, int(timeout * 1000)),
                )
                if result == wait_timeout:
                    time.sleep(1.0)
            finally:
                kernel32.CloseHandle(handle)
        except (AttributeError, ImportError, OSError):
            time.sleep(min(timeout, 2.0))
        return

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.1)


def _run_update_worker_foreground(plan_path: Path) -> int:
    """Run the update worker in a child process and wait for completion."""
    try:
        proc = _spawn_update_worker(plan_path)
    except OSError as exc:
        raise click.ClickException(
            "Failed to start update worker: " f"{exc}",
        ) from exc

    try:
        with proc:
            if proc.stdout is not None:
                for line in proc.stdout:
                    click.echo(line.rstrip())
            return proc.wait()
    except KeyboardInterrupt:
        click.echo("")
        click.echo("[qwenpaw] Update interrupted. Stopping installer...")
        _terminate_update_worker(proc)
        return 130


def _run_update_worker_detached(plan_path: Path) -> None:
    """Launch the update worker and return immediately."""
    try:
        _spawn_update_worker(plan_path, capture_output=False)
    except OSError as exc:
        raise click.ClickException(
            "Failed to start update worker: " f"{exc}",
        ) from exc


def _load_worker_plan(plan_path: str | Path) -> dict[str, Any]:
    """Load a persisted worker plan."""
    return json.loads(Path(plan_path).read_text(encoding="utf-8"))


def run_update_worker(plan_path: str | Path) -> int:
    """Run the update worker and stream installer output."""
    path = Path(plan_path)
    plan = _load_worker_plan(path)
    command = [str(part) for part in plan["command"]]

    _wait_for_process_exit(plan.get("launcher_pid"))

    click.echo("")
    click.echo(
        "[qwenpaw] Updating QwenPaw "
        f"{plan['current_version']} -> {plan['latest_version']}...",
    )
    click.echo(f"[qwenpaw] Using installer: {plan['installer_label']}")

    try:
        with subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            **_subprocess_text_kwargs(),
            bufsize=1,
        ) as proc:
            if proc.stdout is not None:
                for line in proc.stdout:
                    click.echo(line.rstrip())
            return_code = proc.wait()
    except FileNotFoundError as exc:
        click.echo(f"[qwenpaw] Update failed: {exc}")
        return_code = 1
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    if return_code == 0:
        click.echo("[qwenpaw] Update completed successfully.")
        click.echo(
            "[qwenpaw] Please restart any running QwenPaw service "
            "to use the new version.",
        )
    else:
        click.echo(f"[qwenpaw] Update failed with exit code {return_code}.")
        click.echo(
            "[qwenpaw] Please fix the error above and run "
            "`qwenpaw update` again.",
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
    "-y",
    is_flag=True,
    help="Do not prompt before starting the update",
)
@click.pass_context
def update_cmd(ctx: click.Context, yes: bool) -> None:
    """Upgrade QwenPaw in the current Python environment."""
    info = _detect_installation()
    latest_version = _fetch_latest_version()

    _echo_install_summary(info, latest_version)

    version_check = _is_newer_version(latest_version, __version__)
    if version_check is False:
        click.echo("QwenPaw is already up to date.")
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
        if yes:
            raise click.ClickException(
                "Detected "
                f"{_running_service_display(running)}. "
                "Please stop it before running `qwenpaw update`, or rerun "
                "without `--yes` to confirm a forced `qwenpaw shutdown`.",
            )
        if not _confirm_force_shutdown(running):
            click.echo("Cancelled.")
            return
        _run_shutdown_for_update(info, running)
        running = _detect_running_service(
            ctx.obj.get("host") if ctx.obj else None,
            ctx.obj.get("port") if ctx.obj else None,
        )
        if running.is_running:
            raise click.ClickException(
                f"Detected {_running_service_display(running)} "
                "after `qwenpaw shutdown`. "
                "Please stop it manually before running `qwenpaw update`.",
            )

    if not yes and not click.confirm(
        f"Update QwenPaw to {latest_version} in the current environment?",
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
        "launcher_pid": os.getpid() if sys.platform == "win32" else None,
    }
    plan_path = _write_worker_plan(plan)
    click.echo("")
    click.echo("Starting QwenPaw update...")

    if sys.platform == "win32":
        _run_update_worker_detached(plan_path)
        click.echo(
            "On Windows, the update will continue after this command exits "
            "to avoid locking `qwenpaw.exe`.",
        )
        click.echo("Keep this terminal open until the update completes.")
        return

    return_code = _run_update_worker_foreground(plan_path)

    if return_code != 0:
        ctx.exit(return_code)
