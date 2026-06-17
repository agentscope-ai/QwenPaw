# -*- coding: utf-8 -*-
"""Tauri sidecar entry point for starting the Python backend."""
from __future__ import annotations

from collections.abc import Sequence
import json
import logging
import multiprocessing as mp
import os
import socket
import sys

import click

from qwenpaw.tauri.env import (
    DESKTOP_APP_ENV,
    DESKTOP_CORS_ORIGINS_ENV,
    DESKTOP_READY_PREFIX,
    ensure_desktop_cors_origins,
)
from qwenpaw.tauri.sidecar_logging import install_sidecar_logging

logger = logging.getLogger(__name__)


def _is_frozen_desktop() -> bool:
    return bool(getattr(sys, "frozen", False)) or (
        os.environ.get(DESKTOP_APP_ENV) == "1"
    )


def _looks_like_python_invocation(args: Sequence[str]) -> bool:
    """True if *args* look like a Python interpreter command line.

    The packaged backend is launched with no positional arguments, so any
    Python-style argv means a plugin spawned ``sys.executable <args>`` treating
    this binary as an interpreter (e.g. ``-m pkg``, ``script.py``, ``-c ...``).
    """
    if not args:
        return False
    first = args[0]
    if first in ("-m", "-c", "-"):
        return True
    if first.endswith(".py"):
        return True
    # Single-dash interpreter flags (-u, -E, -X ...), but not --options.
    return len(first) >= 2 and first[0] == "-" and first[1] != "-"


def _bundled_python() -> str:
    """Path to the bundled standalone CPython, or ``""`` if missing."""
    python = (os.environ.get("QWENPAW_DESKTOP_PY_RUNTIME") or "").strip()
    if python and os.path.isfile(python):
        return python
    return ""


def _child_env_with_plugin_site(env: "dict | None") -> "dict | None":
    """Return *env* (or a copy of ``os.environ``) with the plugin site dir
    prepended to ``PYTHONPATH`` so the bundled CPython can import plugin deps.
    """
    site_dir = (os.environ.get("QWENPAW_PLUGIN_SITE") or "").strip()
    if not site_dir:
        return env
    base = dict(os.environ if env is None else env)
    existing = base.get("PYTHONPATH", "")
    base["PYTHONPATH"] = (
        site_dir + os.pathsep + existing if existing else site_dir
    )
    return base


def _redirect_backend_python_cmd(cmd: object) -> "list | None":
    """If *cmd* runs this backend binary as a Python interpreter, return a
    rewritten command targeting the bundled CPython; otherwise ``None``.

    Plugins commonly spawn ``[sys.executable, "-m", pkg]`` to launch helper
    processes. In the frozen desktop build ``sys.executable`` is the backend
    binary, so that would start another backend and crash-loop the app
    (issue #5209). Redirecting at spawn time keeps the caller's ``Popen.pid``
    pointing at the real interpreter on every platform.
    """
    if not isinstance(cmd, (list, tuple)) or not cmd:
        return None
    exe = cmd[0]
    if not isinstance(exe, str):
        return None
    if os.path.normcase(exe) != os.path.normcase(sys.executable):
        return None
    if not _looks_like_python_invocation([str(a) for a in cmd[1:]]):
        return None
    python = _bundled_python()
    if not python:
        return None
    return [python, *cmd[1:]]


def _reexec_as_bundled_python(args: Sequence[str]) -> None:
    """Re-run a mis-routed interpreter invocation via the bundled CPython.

    Deep fallback for spawn paths that bypass ``subprocess`` (``os.execv``,
    shell strings, etc.) and reach this binary's ``main()`` with Python-style
    argv. Re-exec the bundled standalone CPython with the same arguments, with
    plugin-installed deps (``QWENPAW_PLUGIN_SITE``) importable.
    """
    python = _bundled_python()
    if not python:
        print(
            "qwenpaw-backend is the desktop backend, not a Python "
            "interpreter, and no bundled runtime is available to run: "
            f"{list(args)}",
            file=sys.stderr,
        )
        raise SystemExit(2)
    site_dir = (os.environ.get("QWENPAW_PLUGIN_SITE") or "").strip()
    if site_dir:
        existing = os.environ.get("PYTHONPATH", "")
        os.environ["PYTHONPATH"] = (
            site_dir + os.pathsep + existing if existing else site_dir
        )
    os.execv(python, [python, *args])


def _install_subprocess_guard() -> None:
    """Harden child-process spawning in the frozen desktop build.

    Two transparent fixes, applied without plugins having to cooperate:

    * Redirect ``subprocess`` calls that run this backend binary as a Python
      interpreter (``[sys.executable, "-m", ...]`` etc.) to the bundled
      CPython. The spawned process *is* the real interpreter, so the caller's
      ``Popen.pid`` stays accurate on every platform (issue #5209).
      ``multiprocessing`` is unaffected: it spawns via ``_winapi`` /
      ``posix_spawn`` rather than ``subprocess.Popen``.
    * On Windows, suppress console windows for child processes that don't pass
      ``CREATE_NO_WINDOW`` themselves (e.g. plugins shelling out to
      ``tasklist``).
    """
    if not _is_frozen_desktop():
        return
    import subprocess

    if getattr(subprocess.Popen, "_qwenpaw_guarded", False):
        return

    is_windows = os.name == "nt"
    create_no_window = 0x08000000
    create_new_console = 0x00000010
    original_init = subprocess.Popen.__init__

    def _init(self, args=None, *rest, **kwargs):  # type: ignore
        redirected = _redirect_backend_python_cmd(args)
        if redirected is not None:
            args = redirected
            kwargs["env"] = _child_env_with_plugin_site(kwargs.get("env"))
        if is_windows:
            flags = kwargs.get("creationflags", 0) or 0
            # Respect callers that explicitly want a visible new console.
            if not flags & create_new_console:
                kwargs["creationflags"] = flags | create_no_window
            startupinfo = kwargs.get("startupinfo") or subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0  # SW_HIDE
            kwargs["startupinfo"] = startupinfo
        return original_init(self, args, *rest, **kwargs)

    subprocess.Popen.__init__ = _init  # type: ignore[method-assign]
    setattr(subprocess.Popen, "_qwenpaw_guarded", True)


def _ensure_qwenpaw_app_not_loaded() -> None:
    if "qwenpaw.app._app" in sys.modules:
        raise RuntimeError(
            "qwenpaw app imported before desktop CORS origins were set",
        )


def _sync_loaded_qwenpaw_constant_cors_origins() -> None:
    constant_module = sys.modules.get("qwenpaw.constant")
    if constant_module is not None:
        constant_module.CORS_ORIGINS = os.environ.get(
            DESKTOP_CORS_ORIGINS_ENV,
            "",
        ).strip()


def _ensure_utf8_stdio() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _install_certifi_env() -> None:
    if os.environ.get("SSL_CERT_FILE"):
        return
    try:
        import certifi
    except Exception:
        logger.debug(
            "certifi is unavailable; leaving SSL bundle env unset",
            exc_info=True,
        )
        return

    cert_file = certifi.where()
    if not cert_file or not os.path.isfile(cert_file):
        logger.debug(
            "certifi returned an invalid certificate path: %r",
            cert_file,
        )
        return
    os.environ.setdefault("SSL_CERT_FILE", cert_file)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", cert_file)
    os.environ.setdefault("CURL_CA_BUNDLE", cert_file)


def _install_desktop_runtime() -> None:
    os.environ.setdefault(DESKTOP_APP_ENV, "1")
    # Must run before importing the FastAPI app: it applies CORS middleware
    # from qwenpaw.constant.CORS_ORIGINS at import time.
    _ensure_qwenpaw_app_not_loaded()
    ensure_desktop_cors_origins()
    _sync_loaded_qwenpaw_constant_cors_origins()


def _run_click_command(
    command: click.Command,
    args: Sequence[str],
    label: str,
) -> None:
    try:
        command.main(args=args, standalone_mode=False)
    except click.ClickException as exc:
        message = f"desktop {label} failed: {exc.format_message()}"
        print(message, file=sys.stderr)
        raise RuntimeError(message) from exc
    except click.Abort as exc:
        message = f"desktop {label} aborted"
        print(message, file=sys.stderr)
        raise RuntimeError(message) from exc
    except SystemExit as exc:
        if exc.code in (None, 0):
            return
        message = f"desktop {label} exited with code {exc.code}"
        print(message, file=sys.stderr)
        raise RuntimeError(message) from exc


def _emit_backend_ready(port: int) -> None:
    payload = json.dumps({"port": port}, separators=(",", ":"))
    print(f"{DESKTOP_READY_PREFIX} {payload}", flush=True)


def _run_backend_server(log_level: str) -> None:
    import uvicorn

    from qwenpaw.config.utils import write_last_api
    from qwenpaw.constant import LOG_LEVEL_ENV, WORKING_DIR
    from qwenpaw.utils.logging import (
        SuppressPathAccessLogFilter,
        setup_logger,
    )
    from qwenpaw.utils.port import get_stable_port, write_port_file

    host = "127.0.0.1"
    normalized_log_level = log_level.lower()
    if normalized_log_level not in {
        "critical",
        "error",
        "warning",
        "info",
        "debug",
        "trace",
    }:
        normalized_log_level = "info"

    os.environ[LOG_LEVEL_ENV] = normalized_log_level
    os.environ.pop("QWENPAW_RELOAD_MODE", None)
    setup_logger(normalized_log_level)
    if normalized_log_level in ("debug", "trace"):
        from qwenpaw.cli.main import log_init_timings

        log_init_timings()

    logging.getLogger("uvicorn.access").addFilter(
        SuppressPathAccessLogFilter(["/console/push-messages"]),
    )

    # Reuse the previous port so localStorage origin stays stable across
    # restarts, preserving user preferences (selected agent, etc.).
    port_file = str(WORKING_DIR / "desktop_port")
    port, reused_socket = get_stable_port(port_file, host)

    config = uvicorn.Config(
        "qwenpaw.app._app:app",
        host=host,
        port=0,
        reload=False,
        workers=1,
        log_level=normalized_log_level,
    )

    if reused_socket:
        backend_socket = reused_socket
    else:
        backend_socket = config.bind_socket()

    try:
        port = _socket_port(backend_socket)
        write_port_file(port_file, port)
        write_last_api(host, port)
        _emit_backend_ready(port)
        uvicorn.Server(config).run(sockets=[backend_socket])
    except Exception:
        backend_socket.close()
        raise


def _socket_port(sock: socket.socket) -> int:
    address = sock.getsockname()
    if not isinstance(address, tuple) or len(address) < 2:
        raise RuntimeError(f"unexpected backend socket address: {address!r}")
    return int(address[1])


def main() -> None:
    if _is_frozen_desktop() and _looks_like_python_invocation(sys.argv[1:]):
        _reexec_as_bundled_python(sys.argv[1:])
        return
    _ensure_utf8_stdio()
    _install_subprocess_guard()
    _install_desktop_runtime()

    from qwenpaw.constant import LOG_LEVEL_ENV, WORKING_DIR

    install_sidecar_logging(WORKING_DIR / "desktop.log")
    _install_certifi_env()

    # Auto-initialize if no config exists
    config_path = WORKING_DIR / "config.json"
    if not config_path.exists():
        from qwenpaw.cli.init_cmd import init_cmd

        _run_click_command(
            init_cmd,
            args=["--defaults", "--accept-security"],
            label="initialization",
        )

    _run_backend_server(os.environ.get(LOG_LEVEL_ENV, "info"))


if __name__ == "__main__":
    mp.freeze_support()
    main()
