# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener, urlopen
from xml.sax.saxutils import escape as xml_escape

import click

from ..config.utils import read_last_api, write_last_api
from ..constant import LOG_LEVEL_ENV, WORKING_DIR

_LOG_LEVEL_CHOICES = [
    "critical",
    "error",
    "warning",
    "info",
    "debug",
    "trace",
]
_DEFAULT_LAUNCHD_LABEL = "ai.copaw.app"
_DEFAULT_SYSTEMD_UNIT = "copaw-app.service"


@dataclass
class ServiceStatus:
    backend: str
    installed: bool
    installed_path: Path
    loaded: bool
    running: bool
    pid: Optional[int] = None
    detail: str = ""


def _run_command(
    command: list[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise click.ClickException(
            f"Required command not found: {command[0]}",
        ) from exc

    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        if not detail:
            detail = f"exit code {result.returncode}"
        raise click.ClickException(
            f"Command failed: {' '.join(command)}\n{detail}",
        )
    return result


def _resolve_host_port(
    ctx: click.Context,
    host: Optional[str],
    port: Optional[int],
) -> tuple[str, int]:
    if host is None or port is None:
        last = read_last_api()
        if last:
            host = host or last[0]
            port = port or last[1]
    if host is None:
        host = (ctx.obj or {}).get("host", "127.0.0.1")
    if port is None:
        port = (ctx.obj or {}).get("port", 8088)
    return host, port


def _service_program_arguments(
    host: str,
    port: int,
    log_level: str,
) -> list[str]:
    return [
        sys.executable,
        "-m",
        "copaw",
        "app",
        "--host",
        host,
        "--port",
        str(port),
        "--log-level",
        log_level,
    ]


def _service_environment(log_level: str) -> dict[str, str]:
    env = {
        "COPAW_WORKING_DIR": str(WORKING_DIR),
        LOG_LEVEL_ENV: log_level,
        "PYTHONUNBUFFERED": "1",
    }
    current_path = os.environ.get("PATH", "").strip()
    if current_path:
        env["PATH"] = current_path
    return env


def _detect_backend() -> str:
    if sys.platform == "darwin":
        return "launchd"
    if sys.platform.startswith("linux"):
        return "systemd"
    raise click.ClickException(
        f"copaw service is not supported on this platform: {sys.platform}",
    )


def _launchd_label() -> str:
    raw = os.environ.get("COPAW_LAUNCHD_LABEL", "").strip()
    return raw or _DEFAULT_LAUNCHD_LABEL


def _launchd_domain() -> str:
    if not hasattr(os, "getuid"):
        raise click.ClickException(
            "launchd management requires a POSIX user session",
        )
    return f"gui/{os.getuid()}"


def _launchd_plist_path(label: str) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"


def build_launchd_plist(
    *,
    label: str,
    program_arguments: list[str],
    working_directory: Path,
    environment: dict[str, str],
    stdout_path: Path,
    stderr_path: Path,
) -> str:
    args_xml = "\n".join(
        f"      <string>{xml_escape(arg)}</string>"
        for arg in program_arguments
    )
    env_xml = "\n".join(
        f"      <key>{xml_escape(k)}</key>\n"
        f"      <string>{xml_escape(v)}</string>"
        for k, v in sorted(environment.items())
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        "<dict>\n"
        f"  <key>Label</key>\n  <string>{xml_escape(label)}</string>\n"
        "  <key>ProgramArguments</key>\n"
        "  <array>\n"
        f"{args_xml}\n"
        "  </array>\n"
        "  <key>WorkingDirectory</key>\n"
        f"  <string>{xml_escape(str(working_directory))}</string>\n"
        "  <key>EnvironmentVariables</key>\n"
        "  <dict>\n"
        f"{env_xml}\n"
        "  </dict>\n"
        "  <key>RunAtLoad</key>\n  <true/>\n"
        "  <key>KeepAlive</key>\n  <true/>\n"
        "  <key>StandardOutPath</key>\n"
        f"  <string>{xml_escape(str(stdout_path))}</string>\n"
        "  <key>StandardErrorPath</key>\n"
        f"  <string>{xml_escape(str(stderr_path))}</string>\n"
        "</dict>\n"
        "</plist>\n"
    )


def _parse_launchctl_print(output: str) -> tuple[bool, Optional[int], str]:
    pid: Optional[int] = None
    state = ""
    for raw in output.splitlines():
        line = raw.strip()
        if line.startswith("state ="):
            state = line.split("=", 1)[1].strip().strip('"')
        if line.startswith("pid ="):
            pid_raw = line.split("=", 1)[1].strip()
            try:
                parsed = int(pid_raw)
            except ValueError:
                continue
            if parsed > 0:
                pid = parsed
    normalized_state = state.lower()
    running = pid is not None or normalized_state in {"running", "active"}
    return running, pid, state


def _launchd_status() -> ServiceStatus:
    label = _launchd_label()
    plist_path = _launchd_plist_path(label)
    domain = _launchd_domain()
    status = _run_command(
        ["launchctl", "print", f"{domain}/{label}"],
        check=False,
    )
    loaded = status.returncode == 0
    running = False
    pid: Optional[int] = None
    detail = ""
    if loaded:
        running, pid, state = _parse_launchctl_print(
            status.stdout or status.stderr,
        )
        detail = state
    else:
        detail = (status.stderr or status.stdout).strip()
    return ServiceStatus(
        backend="launchd",
        installed=plist_path.is_file(),
        installed_path=plist_path,
        loaded=loaded,
        running=running,
        pid=pid,
        detail=detail,
    )


def _launchd_install(
    *,
    program_arguments: list[str],
    environment: dict[str, str],
    force: bool,
) -> None:
    label = _launchd_label()
    domain = _launchd_domain()
    plist_path = _launchd_plist_path(label)
    if plist_path.exists() and not force:
        raise click.ClickException(
            (
                f"LaunchAgent already exists: {plist_path}\n"
                "Use --force to overwrite."
            ),
        )

    logs_dir = WORKING_DIR / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist = build_launchd_plist(
        label=label,
        program_arguments=program_arguments,
        working_directory=WORKING_DIR,
        environment=environment,
        stdout_path=logs_dir / "service.log",
        stderr_path=logs_dir / "service.err.log",
    )
    plist_path.write_text(plist, encoding="utf-8")

    _run_command(["launchctl", "bootout", f"{domain}/{label}"], check=False)
    _run_command(
        ["launchctl", "bootout", domain, str(plist_path)],
        check=False,
    )
    _run_command(
        ["launchctl", "bootstrap", domain, str(plist_path)],
        check=True,
    )
    _run_command(
        ["launchctl", "kickstart", "-k", f"{domain}/{label}"],
        check=True,
    )


def _launchd_start() -> None:
    label = _launchd_label()
    domain = _launchd_domain()
    plist_path = _launchd_plist_path(label)
    if not plist_path.exists():
        raise click.ClickException(
            (
                f"LaunchAgent is not installed: {plist_path}\n"
                "Run: copaw service install"
            ),
        )
    kick = _run_command(
        ["launchctl", "kickstart", "-k", f"{domain}/{label}"],
        check=False,
    )
    if kick.returncode == 0:
        return
    boot: Optional[subprocess.CompletedProcess[str]] = None
    for _ in range(30):
        boot = _run_command(
            ["launchctl", "bootstrap", domain, str(plist_path)],
            check=False,
        )
        if boot.returncode == 0:
            break
        time.sleep(0.5)
    if boot is None or boot.returncode != 0:
        detail = ((boot.stderr or boot.stdout).strip() if boot else "").strip()
        if not detail:
            detail = "bootstrap failed"
        raise click.ClickException(f"Failed to start LaunchAgent: {detail}")
    _run_command(
        ["launchctl", "kickstart", "-k", f"{domain}/{label}"],
        check=True,
    )


def _launchd_stop() -> None:
    label = _launchd_label()
    domain = _launchd_domain()
    bootout = _run_command(
        ["launchctl", "bootout", f"{domain}/{label}"],
        check=False,
    )
    if bootout.returncode == 0:
        return
    plist_path = _launchd_plist_path(label)
    if plist_path.exists():
        _run_command(
            ["launchctl", "bootout", domain, str(plist_path)],
            check=False,
        )


def _launchd_restart() -> None:
    label = _launchd_label()
    domain = _launchd_domain()
    plist_path = _launchd_plist_path(label)
    if not plist_path.exists():
        raise click.ClickException(
            (
                f"LaunchAgent is not installed: {plist_path}\n"
                "Run: copaw service install"
            ),
        )
    kick = _run_command(
        ["launchctl", "kickstart", "-k", f"{domain}/{label}"],
        check=False,
    )
    if kick.returncode == 0:
        return
    _launchd_start()


def _launchd_uninstall() -> None:
    plist_path = _launchd_plist_path(_launchd_label())
    _launchd_stop()
    if plist_path.exists():
        plist_path.unlink()


def _systemd_unit_name() -> str:
    raw = os.environ.get("COPAW_SYSTEMD_UNIT", "").strip()
    if not raw:
        return _DEFAULT_SYSTEMD_UNIT
    return raw if raw.endswith(".service") else f"{raw}.service"


def _systemd_unit_path(unit_name: str) -> Path:
    return Path.home() / ".config" / "systemd" / "user" / unit_name


def _systemd_escape_env_value(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def _validate_systemd_line(name: str, value: str) -> None:
    if "\n" in value or "\r" in value:
        raise click.ClickException(f"{name} cannot contain newlines")


def build_systemd_unit(
    *,
    description: str,
    program_arguments: list[str],
    working_directory: Path,
    environment: dict[str, str],
) -> str:
    _validate_systemd_line("Description", description)
    _validate_systemd_line("WorkingDirectory", str(working_directory))
    exec_start = " ".join(shlex.quote(arg) for arg in program_arguments)
    env_lines = "\n".join(
        (
            f'Environment="{_systemd_escape_env_value(k)}='
            f'{_systemd_escape_env_value(v)}"'
        )
        for k, v in sorted(environment.items())
    )
    return (
        "[Unit]\n"
        f"Description={description}\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n\n"
        "[Service]\n"
        "Type=simple\n"
        f"WorkingDirectory={working_directory}\n"
        f"ExecStart={exec_start}\n"
        f"{env_lines}\n"
        "Restart=always\n"
        "RestartSec=3\n\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def _parse_systemctl_show(output: str) -> tuple[bool, Optional[int], str]:
    running = False
    pid: Optional[int] = None
    state = ""
    for raw in output.splitlines():
        line = raw.strip()
        if line.startswith("ActiveState="):
            state = line.split("=", 1)[1].strip()
            running = state == "active"
        if line.startswith("MainPID="):
            pid_raw = line.split("=", 1)[1].strip()
            try:
                parsed = int(pid_raw)
            except ValueError:
                continue
            if parsed > 0:
                pid = parsed
    return running, pid, state


def _parse_systemctl_load_state(output: str) -> str:
    for raw in output.splitlines():
        line = raw.strip()
        if line.startswith("LoadState="):
            return line.split("=", 1)[1].strip()
    return ""


def _systemd_status() -> ServiceStatus:
    unit_name = _systemd_unit_name()
    unit_path = _systemd_unit_path(unit_name)
    enabled = _run_command(
        ["systemctl", "--user", "is-enabled", unit_name],
        check=False,
    )
    show = _run_command(
        [
            "systemctl",
            "--user",
            "show",
            unit_name,
            "--property",
            "LoadState,ActiveState,MainPID",
        ],
        check=False,
    )
    loaded = False
    running = False
    pid: Optional[int] = None
    detail = ""
    if show.returncode == 0:
        running, pid, state = _parse_systemctl_show(show.stdout)
        load_state = _parse_systemctl_load_state(show.stdout)
        loaded = load_state == "loaded"
        enabled_text = "yes" if enabled.returncode == 0 else "no"
        detail = (
            f"active={state}, "
            f"load={load_state or 'unknown'}, "
            f"enabled={enabled_text}"
        )
    else:
        detail = (show.stderr or show.stdout).strip()
    return ServiceStatus(
        backend="systemd",
        installed=unit_path.is_file(),
        installed_path=unit_path,
        loaded=loaded,
        running=running,
        pid=pid,
        detail=detail,
    )


def _systemd_install(
    *,
    program_arguments: list[str],
    environment: dict[str, str],
    force: bool,
) -> None:
    unit_name = _systemd_unit_name()
    unit_path = _systemd_unit_path(unit_name)
    if unit_path.exists() and not force:
        raise click.ClickException(
            (
                f"systemd unit already exists: {unit_path}\n"
                "Use --force to overwrite."
            ),
        )

    unit_path.parent.mkdir(parents=True, exist_ok=True)
    unit_content = build_systemd_unit(
        description="CoPaw application service",
        program_arguments=program_arguments,
        working_directory=WORKING_DIR,
        environment=environment,
    )
    unit_path.write_text(unit_content, encoding="utf-8")
    _run_command(["systemctl", "--user", "daemon-reload"], check=True)
    _run_command(["systemctl", "--user", "enable", unit_name], check=True)
    _run_command(["systemctl", "--user", "start", unit_name], check=True)


def _systemd_start() -> None:
    unit_name = _systemd_unit_name()
    unit_path = _systemd_unit_path(unit_name)
    if not unit_path.exists():
        raise click.ClickException(
            (
                f"systemd unit is not installed: {unit_path}\n"
                "Run: copaw service install"
            ),
        )
    _run_command(["systemctl", "--user", "start", unit_name], check=True)


def _systemd_stop() -> None:
    _run_command(
        ["systemctl", "--user", "stop", _systemd_unit_name()],
        check=False,
    )


def _systemd_restart() -> None:
    _run_command(
        ["systemctl", "--user", "restart", _systemd_unit_name()],
        check=True,
    )


def _systemd_uninstall() -> None:
    unit_name = _systemd_unit_name()
    unit_path = _systemd_unit_path(unit_name)
    _run_command(
        ["systemctl", "--user", "disable", "--now", unit_name],
        check=False,
    )
    if unit_path.exists():
        unit_path.unlink()
    _run_command(["systemctl", "--user", "daemon-reload"], check=False)


def _resolve_service_status() -> ServiceStatus:
    backend = _detect_backend()
    if backend == "launchd":
        return _launchd_status()
    return _systemd_status()


def _install_service(
    *,
    host: str,
    port: int,
    log_level: str,
    force: bool,
) -> None:
    args = _service_program_arguments(host, port, log_level)
    env = _service_environment(log_level)
    backend = _detect_backend()
    if backend == "launchd":
        _launchd_install(program_arguments=args, environment=env, force=force)
        return
    _systemd_install(program_arguments=args, environment=env, force=force)


def _start_service() -> None:
    backend = _detect_backend()
    if backend == "launchd":
        _launchd_start()
        return
    _systemd_start()


def _stop_service() -> None:
    backend = _detect_backend()
    if backend == "launchd":
        _launchd_stop()
        return
    _systemd_stop()


def _restart_service() -> None:
    backend = _detect_backend()
    if backend == "launchd":
        _launchd_restart()
        return
    _systemd_restart()


def _uninstall_service() -> None:
    backend = _detect_backend()
    if backend == "launchd":
        _launchd_uninstall()
        return
    _systemd_uninstall()


def _normalize_probe_host(host: str) -> tuple[str, bool]:
    normalized = host.strip()
    lowered = normalized.lower()
    if lowered in {"localhost", "127.0.0.1", "0.0.0.0"}:
        return "127.0.0.1", True
    if lowered in {"::", "::1"}:
        return "::1", True
    return normalized, False


def _url_host(host: str) -> str:
    if ":" in host and not (host.startswith("[") and host.endswith("]")):
        return f"[{host}]"
    return host


def _probe_version(host: str, port: int, timeout: float) -> tuple[bool, str]:
    probe_host, use_local_opener = _normalize_probe_host(host)
    url = f"http://{_url_host(probe_host)}:{port}/api/version"
    request_timeout = max(min(timeout, 5.0), 0.2)
    deadline = time.monotonic() + max(timeout, 0.2)
    last_error = "unreachable"
    while True:
        try:
            if use_local_opener:
                opener = build_opener(ProxyHandler({}))
                response = opener.open(url, timeout=request_timeout)
            else:
                response = urlopen(url, timeout=request_timeout)
            with response as resp:
                body = resp.read().decode("utf-8", errors="replace")
            break
        except URLError as exc:
            last_error = f"unreachable ({exc.reason})"
        except OSError as exc:
            last_error = f"unreachable ({exc})"
        if time.monotonic() >= deadline:
            return False, last_error
        time.sleep(0.25)

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return False, "invalid JSON response"
    version = payload.get("version")
    if isinstance(version, str) and version:
        return True, f"ok (version={version})"
    return False, "missing version field"


@click.group("service")
def service_group() -> None:
    """Manage CoPaw as a background service (launchd/systemd user service)."""


@service_group.command("install")
@click.option(
    "--host",
    default=None,
    help="Bind host used by the managed `copaw app` process.",
)
@click.option(
    "--port",
    default=None,
    type=int,
    help="Bind port used by the managed `copaw app` process.",
)
@click.option(
    "--log-level",
    default="info",
    type=click.Choice(_LOG_LEVEL_CHOICES, case_sensitive=False),
    show_default=True,
    help="Log level for managed service process.",
)
@click.option(
    "--force",
    is_flag=True,
    help="Overwrite existing service definition if present.",
)
@click.pass_context
def install_cmd(
    ctx: click.Context,
    host: Optional[str],
    port: Optional[int],
    log_level: str,
    force: bool,
) -> None:
    """Install and start background service."""
    host, port = _resolve_host_port(ctx, host, port)
    _install_service(
        host=host,
        port=port,
        log_level=log_level.lower(),
        force=force,
    )
    write_last_api(host, port)
    backend = _detect_backend()
    click.echo(f"✓ Installed CoPaw service ({backend})")
    click.echo(f"  Host/Port: {host}:{port}")
    if backend == "systemd":
        click.echo("  Tip: To keep service alive after logout, run:")
        click.echo(
            (
                "    sudo loginctl enable-linger "
                f"{os.environ.get('USER', '<user>')}"
            ),
        )


@service_group.command("uninstall")
def uninstall_cmd() -> None:
    """Uninstall background service definition."""
    _uninstall_service()
    click.echo("✓ Uninstalled CoPaw service")


@service_group.command("start")
def start_cmd() -> None:
    """Start background service."""
    _start_service()
    click.echo("✓ CoPaw service started")


@service_group.command("stop")
def stop_cmd() -> None:
    """Stop background service."""
    _stop_service()
    click.echo("✓ CoPaw service stopped")


@service_group.command("restart")
def restart_cmd() -> None:
    """Restart background service."""
    _restart_service()
    click.echo("✓ CoPaw service restarted")


@service_group.command("status")
@click.option(
    "--host",
    default=None,
    help="Host for API probe. Defaults to last known/global host.",
)
@click.option(
    "--port",
    default=None,
    type=int,
    help="Port for API probe. Defaults to last known/global port.",
)
@click.option(
    "--no-probe",
    is_flag=True,
    help="Skip HTTP /api/version probe.",
)
@click.option(
    "--timeout",
    default=2.0,
    show_default=True,
    type=float,
    help="Probe timeout (seconds).",
)
@click.pass_context
def status_cmd(
    ctx: click.Context,
    host: Optional[str],
    port: Optional[int],
    no_probe: bool,
    timeout: float,
) -> None:
    """Show service supervisor status and optional HTTP probe."""
    status = _resolve_service_status()
    host, port = _resolve_host_port(ctx, host, port)

    click.echo(f"Backend: {status.backend}")
    click.echo(f"Installed: {'yes' if status.installed else 'no'}")
    click.echo(f"Definition: {status.installed_path}")
    click.echo(f"Loaded: {'yes' if status.loaded else 'no'}")
    click.echo(f"Running: {'yes' if status.running else 'no'}")
    if status.pid:
        click.echo(f"PID: {status.pid}")
    if status.detail:
        click.echo(f"Detail: {status.detail}")

    if no_probe:
        return
    ok, message = _probe_version(host, port, timeout)
    click.echo(f"API probe ({host}:{port}/api/version): {message}")
    if not ok and status.running:
        raise click.ClickException(
            "Service is running but API probe failed. Check service logs.",
        )
