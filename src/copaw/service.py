# -*- coding: utf-8 -*-
"""Platform-specific service managers for running CoPaw as a system service.

Supported platforms:
- Linux: systemd (user service by default, system service with --system)
- macOS: launchd (LaunchAgent)
- Windows: Task Scheduler (runs at logon)
"""
from __future__ import annotations

import abc
import logging
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Optional

from .constant import WORKING_DIR

logger = logging.getLogger(__name__)

SERVICE_NAME = "copaw"
LAUNCHD_LABEL = "com.copaw.app"
LOG_DIR = WORKING_DIR / "logs"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_copaw_executable() -> str:
    """Find the absolute path to the ``copaw`` CLI entry-point."""
    python = Path(sys.executable).resolve()
    if sys.platform == "win32":
        candidate = python.parent / "copaw.exe"
    else:
        candidate = python.parent / "copaw"
    if candidate.is_file():
        return str(candidate)

    found = shutil.which("copaw")
    if found:
        return str(Path(found).resolve())

    raise FileNotFoundError(
        "Cannot locate the copaw executable. "
        "Make sure CoPaw is properly installed and on your PATH."
    )


def _ensure_log_dir() -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_DIR


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class ServiceManager(abc.ABC):
    """Platform-agnostic interface for service lifecycle management."""

    @abc.abstractmethod
    def install(
        self,
        host: str = "127.0.0.1",
        port: int = 8088,
        *,
        system: bool = False,
    ) -> None:
        """Install and enable the service for auto-start."""

    @abc.abstractmethod
    def uninstall(self, *, system: bool = False) -> None:
        """Stop and remove the service."""

    @abc.abstractmethod
    def start(self, *, system: bool = False) -> None:
        """Start the service."""

    @abc.abstractmethod
    def stop(self, *, system: bool = False) -> None:
        """Stop the service."""

    @abc.abstractmethod
    def restart(self, *, system: bool = False) -> None:
        """Restart the service."""

    @abc.abstractmethod
    def status(self, *, system: bool = False) -> str:
        """Return a human-readable status string."""

    @abc.abstractmethod
    def logs(
        self,
        *,
        lines: int = 50,
        follow: bool = False,
        system: bool = False,
    ) -> None:
        """Stream / print recent service logs to stdout."""


# ---------------------------------------------------------------------------
# Linux — systemd
# ---------------------------------------------------------------------------

class SystemdServiceManager(ServiceManager):
    """Manage CoPaw as a systemd service (user or system)."""

    # --- paths ---

    @staticmethod
    def _user_unit_path() -> Path:
        return Path.home() / ".config" / "systemd" / "user" / f"{SERVICE_NAME}.service"

    @staticmethod
    def _system_unit_path() -> Path:
        return Path(f"/etc/systemd/system/{SERVICE_NAME}.service")

    def _unit_path(self, system: bool) -> Path:
        return self._system_unit_path() if system else self._user_unit_path()

    @staticmethod
    def _systemctl(args: list[str], *, system: bool) -> subprocess.CompletedProcess:
        cmd = ["systemctl"]
        if not system:
            cmd.append("--user")
        cmd.extend(args)
        return subprocess.run(cmd, capture_output=True, text=True)

    # --- public API ---

    def install(
        self,
        host: str = "127.0.0.1",
        port: int = 8088,
        *,
        system: bool = False,
    ) -> None:
        copaw = _get_copaw_executable()
        _ensure_log_dir()

        unit = textwrap.dedent(f"""\
            [Unit]
            Description=CoPaw Personal Assistant
            After=network-online.target
            Wants=network-online.target

            [Service]
            Type=simple
            ExecStart={copaw} app --host {host} --port {port}
            Restart=on-failure
            RestartSec=5
            Environment=COPAW_WORKING_DIR={WORKING_DIR}

            [Install]
            WantedBy={'multi-user.target' if system else 'default.target'}
        """)

        unit_path = self._unit_path(system)
        if system:
            # Need root to write to /etc/systemd/system
            subprocess.run(
                ["sudo", "tee", str(unit_path)],
                input=unit,
                capture_output=True,
                text=True,
                check=True,
            )
        else:
            unit_path.parent.mkdir(parents=True, exist_ok=True)
            unit_path.write_text(unit, encoding="utf-8")

        self._systemctl(["daemon-reload"], system=system)
        self._systemctl(["enable", SERVICE_NAME], system=system)

        if not system:
            # Enable lingering so user service starts at boot even without login
            subprocess.run(
                ["loginctl", "enable-linger", os.environ.get("USER", "")],
                capture_output=True,
                text=True,
            )

        print(f"Service installed: {unit_path}")
        print(f"Run 'copaw service start' to start the service.")

    def uninstall(self, *, system: bool = False) -> None:
        self._systemctl(["stop", SERVICE_NAME], system=system)
        self._systemctl(["disable", SERVICE_NAME], system=system)

        unit_path = self._unit_path(system)
        if unit_path.exists():
            if system:
                subprocess.run(
                    ["sudo", "rm", str(unit_path)],
                    capture_output=True,
                    text=True,
                )
            else:
                unit_path.unlink()

        self._systemctl(["daemon-reload"], system=system)
        print(f"Service uninstalled (removed {unit_path}).")

    def start(self, *, system: bool = False) -> None:
        r = self._systemctl(["start", SERVICE_NAME], system=system)
        if r.returncode != 0:
            print(f"Failed to start: {r.stderr.strip()}")
        else:
            print("CoPaw service started.")

    def stop(self, *, system: bool = False) -> None:
        r = self._systemctl(["stop", SERVICE_NAME], system=system)
        if r.returncode != 0:
            print(f"Failed to stop: {r.stderr.strip()}")
        else:
            print("CoPaw service stopped.")

    def restart(self, *, system: bool = False) -> None:
        r = self._systemctl(["restart", SERVICE_NAME], system=system)
        if r.returncode != 0:
            print(f"Failed to restart: {r.stderr.strip()}")
        else:
            print("CoPaw service restarted.")

    def status(self, *, system: bool = False) -> str:
        r = self._systemctl(["status", SERVICE_NAME], system=system)
        return r.stdout or r.stderr

    def logs(
        self,
        *,
        lines: int = 50,
        follow: bool = False,
        system: bool = False,
    ) -> None:
        cmd = ["journalctl"]
        if not system:
            cmd.append("--user")
        cmd.extend(["-u", SERVICE_NAME, "-n", str(lines)])
        if follow:
            cmd.append("-f")
        subprocess.run(cmd)


# ---------------------------------------------------------------------------
# macOS — launchd
# ---------------------------------------------------------------------------

class LaunchdServiceManager(ServiceManager):
    """Manage CoPaw as a launchd LaunchAgent on macOS."""

    @staticmethod
    def _plist_path() -> Path:
        return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"

    def install(
        self,
        host: str = "127.0.0.1",
        port: int = 8088,
        *,
        system: bool = False,
    ) -> None:
        if system:
            print(
                "System-wide launchd daemons require manual setup. "
                "Installing as user LaunchAgent instead."
            )
        copaw = _get_copaw_executable()
        log_dir = _ensure_log_dir()

        plist = textwrap.dedent(f"""\
            <?xml version="1.0" encoding="UTF-8"?>
            <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
              "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
            <plist version="1.0">
            <dict>
                <key>Label</key>
                <string>{LAUNCHD_LABEL}</string>
                <key>ProgramArguments</key>
                <array>
                    <string>{copaw}</string>
                    <string>app</string>
                    <string>--host</string>
                    <string>{host}</string>
                    <string>--port</string>
                    <string>{port}</string>
                </array>
                <key>RunAtLoad</key>
                <true/>
                <key>KeepAlive</key>
                <true/>
                <key>StandardOutPath</key>
                <string>{log_dir / 'copaw.log'}</string>
                <key>StandardErrorPath</key>
                <string>{log_dir / 'copaw.err'}</string>
                <key>EnvironmentVariables</key>
                <dict>
                    <key>COPAW_WORKING_DIR</key>
                    <string>{WORKING_DIR}</string>
                </dict>
            </dict>
            </plist>
        """)

        plist_path = self._plist_path()
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        plist_path.write_text(plist, encoding="utf-8")

        print(f"Service installed: {plist_path}")
        print("Run 'copaw service start' to start the service.")

    def uninstall(self, *, system: bool = False) -> None:
        plist = self._plist_path()
        if plist.exists():
            subprocess.run(
                ["launchctl", "unload", "-w", str(plist)],
                capture_output=True,
                text=True,
            )
            plist.unlink()
            print(f"Service uninstalled (removed {plist}).")
        else:
            print("Service is not installed.")

    def start(self, *, system: bool = False) -> None:
        plist = self._plist_path()
        if not plist.exists():
            print("Service is not installed. Run 'copaw service install' first.")
            return
        r = subprocess.run(
            ["launchctl", "load", "-w", str(plist)],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            print(f"Failed to start: {r.stderr.strip()}")
        else:
            print("CoPaw service started.")

    def stop(self, *, system: bool = False) -> None:
        plist = self._plist_path()
        if not plist.exists():
            print("Service is not installed.")
            return
        r = subprocess.run(
            ["launchctl", "unload", str(plist)],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            print(f"Failed to stop: {r.stderr.strip()}")
        else:
            print("CoPaw service stopped.")

    def restart(self, *, system: bool = False) -> None:
        self.stop(system=system)
        self.start(system=system)

    def status(self, *, system: bool = False) -> str:
        r = subprocess.run(
            ["launchctl", "list"],
            capture_output=True,
            text=True,
        )
        for line in r.stdout.splitlines():
            if LAUNCHD_LABEL in line:
                parts = line.split()
                pid = parts[0] if parts[0] != "-" else "(not running)"
                return f"CoPaw service: PID={pid}\n{line}"
        return "CoPaw service is not loaded."

    def logs(
        self,
        *,
        lines: int = 50,
        follow: bool = False,
        system: bool = False,
    ) -> None:
        log_file = LOG_DIR / "copaw.log"
        err_file = LOG_DIR / "copaw.err"

        if follow:
            # tail -f both logs
            cmd = ["tail", "-f"]
            files = [str(f) for f in (log_file, err_file) if f.exists()]
            if not files:
                print(f"No log files found in {LOG_DIR}")
                return
            subprocess.run(["tail", "-f"] + files)
        else:
            for label, path in [("stdout", log_file), ("stderr", err_file)]:
                if path.exists():
                    print(f"--- {label}: {path} ---")
                    text = path.read_text(encoding="utf-8", errors="replace")
                    tail = text.splitlines()[-lines:]
                    print("\n".join(tail))
                else:
                    print(f"--- {label}: (no log file) ---")


# ---------------------------------------------------------------------------
# Windows — Task Scheduler
# ---------------------------------------------------------------------------

class WindowsTaskSchedulerManager(ServiceManager):
    """Manage CoPaw via Windows Task Scheduler (runs at user logon).

    For a true Windows Service, consider using NSSM:
        nssm install CoPaw <copaw-exe> app --host 127.0.0.1 --port 8088
    """

    _TASK_NAME = "CoPaw"

    def install(
        self,
        host: str = "127.0.0.1",
        port: int = 8088,
        *,
        system: bool = False,
    ) -> None:
        copaw = _get_copaw_executable()
        log_dir = _ensure_log_dir()

        # Build the XML definition for a scheduled task.
        # Using XML gives us more control than schtasks /Create flags.
        log_file = str(log_dir / "copaw.log")

        # Use PowerShell to register the task for maximum compatibility
        # We create a task that:
        #  - Triggers at logon
        #  - Does NOT stop if going on batteries
        #  - Has no execution time limit
        #  - Restarts on failure
        ps_script = textwrap.dedent(f"""\
            $ErrorActionPreference = 'Stop'
            $taskName = '{self._TASK_NAME}'

            # Remove existing task if present
            $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
            if ($existing) {{
                Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
            }}

            $action = New-ScheduledTaskAction `
                -Execute '{copaw}' `
                -Argument 'app --host {host} --port {port}' `
                -WorkingDirectory '{WORKING_DIR}'

            $trigger = New-ScheduledTaskTrigger -AtLogOn

            $settings = New-ScheduledTaskSettingsSet `
                -AllowStartIfOnBatteries `
                -DontStopIfGoingOnBatteries `
                -StartWhenAvailable `
                -RestartCount 3 `
                -RestartInterval (New-TimeSpan -Minutes 1) `
                -ExecutionTimeLimit (New-TimeSpan -Days 0)

            Register-ScheduledTask `
                -TaskName $taskName `
                -Action $action `
                -Trigger $trigger `
                -Settings $settings `
                -Description 'CoPaw Personal Assistant' | Out-Null

            Write-Output "OK"
        """)

        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0 or "OK" not in r.stdout:
            print(f"Failed to install service:\n{r.stderr.strip()}")
            return

        print(f"Scheduled task '{self._TASK_NAME}' created (runs at logon).")
        print(f"Run 'copaw service start' to start the service now.")

    def uninstall(self, *, system: bool = False) -> None:
        # Stop first
        self.stop()

        r = subprocess.run(
            [
                "schtasks", "/Delete",
                "/TN", self._TASK_NAME,
                "/F",
            ],
            capture_output=True,
            text=True,
        )
        if r.returncode == 0:
            print(f"Scheduled task '{self._TASK_NAME}' removed.")
        else:
            if "cannot find" in r.stderr.lower() or "does not exist" in r.stderr.lower():
                print("Service is not installed.")
            else:
                print(f"Failed to remove task: {r.stderr.strip()}")

    def start(self, *, system: bool = False) -> None:
        r = subprocess.run(
            [
                "schtasks", "/Run",
                "/TN", self._TASK_NAME,
            ],
            capture_output=True,
            text=True,
        )
        if r.returncode == 0:
            print("CoPaw service started.")
        else:
            print(f"Failed to start: {r.stderr.strip()}")

    def stop(self, *, system: bool = False) -> None:
        r = subprocess.run(
            [
                "schtasks", "/End",
                "/TN", self._TASK_NAME,
            ],
            capture_output=True,
            text=True,
        )
        if r.returncode == 0:
            print("CoPaw service stopped.")
        else:
            # Not an error if it wasn't running
            err = r.stderr.strip().lower()
            if "not currently running" in err or "is not running" in err:
                print("CoPaw service is not running.")
            else:
                print(f"Failed to stop: {r.stderr.strip()}")

    def restart(self, *, system: bool = False) -> None:
        self.stop(system=system)
        self.start(system=system)

    def status(self, *, system: bool = False) -> str:
        r = subprocess.run(
            [
                "schtasks", "/Query",
                "/TN", self._TASK_NAME,
                "/FO", "LIST",
                "/V",
            ],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            return "CoPaw service is not installed."
        return r.stdout

    def logs(
        self,
        *,
        lines: int = 50,
        follow: bool = False,
        system: bool = False,
    ) -> None:
        log_file = LOG_DIR / "copaw.log"
        if not log_file.exists():
            print(
                f"No log file found at {log_file}.\n"
                "Note: Windows Task Scheduler does not capture stdout by default.\n"
                "Check the console output or configure file logging in copaw."
            )
            return

        if follow:
            print(f"Tailing {log_file} (Ctrl+C to stop)...")
            # PowerShell Get-Content -Wait is the Windows equivalent of tail -f
            subprocess.run(
                [
                    "powershell", "-NoProfile", "-Command",
                    f"Get-Content -Path '{log_file}' -Tail {lines} -Wait",
                ],
            )
        else:
            text = log_file.read_text(encoding="utf-8", errors="replace")
            tail = text.splitlines()[-lines:]
            print("\n".join(tail))


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_service_manager() -> ServiceManager:
    """Return the appropriate :class:`ServiceManager` for the current OS."""
    if sys.platform == "linux":
        return SystemdServiceManager()
    elif sys.platform == "darwin":
        return LaunchdServiceManager()
    elif sys.platform == "win32":
        return WindowsTaskSchedulerManager()
    else:
        raise RuntimeError(f"Unsupported platform: {sys.platform}")


def is_service_installed() -> bool:
    """Quick check: is the CoPaw service currently installed?"""
    if sys.platform == "linux":
        return SystemdServiceManager._user_unit_path().exists() or \
               SystemdServiceManager._system_unit_path().exists()
    elif sys.platform == "darwin":
        return LaunchdServiceManager._plist_path().exists()
    elif sys.platform == "win32":
        r = subprocess.run(
            ["schtasks", "/Query", "/TN", "CoPaw"],
            capture_output=True,
            text=True,
        )
        return r.returncode == 0
    return False
