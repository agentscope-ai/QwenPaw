# -*- coding: utf-8 -*-
"""Fire-and-forget desktop event emitter."""

from __future__ import annotations

import asyncio
import functools
import logging
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("qwenpaw.pet_desktop")

# ``True`` once the plugin has either spawned the pet desktop *or*
# observed a healthy one during startup (see ``ensure_desktop_available``
# below). The shutdown hook only kills processes that the plugin has
# "adopted" this way — that covers both the autostart case and the case
# where a previous QwenPaw run left the pet behind. A user who never
# lets QwenPaw see the pet (e.g. ``QWENPAW_PET_AUTOSTART=0`` and the pet
# is not running at startup) will not have their standalone desktop
# killed on QwenPaw exit. Hard opt-out: ``QWENPAW_PET_STOP_ON_SHUTDOWN=0``.
_DESKTOP_OWNED = False

# Last URL that successfully answered ``GET /health`` (or the URL we
# chose when spawning after a port collision).
_active_desktop_base: str | None = None


def _mark_desktop_owned() -> None:
    """Mark the desktop as managed by this QwenPaw process."""
    global _DESKTOP_OWNED
    _DESKTOP_OWNED = True


def _clear_desktop_base_url_cache() -> None:
    global _active_desktop_base
    _active_desktop_base = None


TOKEN_PATH = Path(
    os.environ.get(
        "QWENPAW_PET_TOKEN_PATH",
        str(Path.home() / ".qwenpaw-pet/runtime/update-token"),
    ),
)

EVENT_TO_STATE = {
    "qwenpaw.startup": "waving",
    "qwenpaw.shutdown": "idle",
    "query.received": "jumping",
    "query.running": "running",
    "query.first_token": "review",
    "query.done": "review",
    "tool.detected": "running",
    "tool.result": "review",
    "query.cancelled": "waiting",
    "query.error": "failed",
    "approval.pending": "waiting",
    "approval.resolved": "idle",
    "approval.bulk_cancel": "idle",
    "idle": "idle",
}


def _read_token() -> str | None:
    try:
        token = TOKEN_PATH.read_text(encoding="utf-8").strip()
        return token or None
    except OSError:
        return None


def _headers() -> dict[str, str]:
    token = _read_token()
    if not token:
        return {}
    return {"X-QwenPaw-Pet-Token": token}


def _httpx_client_kwargs() -> dict[str, Any]:
    """Options for calls to the local pet desktop.

    ``trust_env=False`` avoids routing ``127.0.0.1`` through HTTP(S)_PROXY
    (e.g. Clash on 7890), which would time out and break all pet events.
    """
    return {"trust_env": False, "timeout": 0.35}


def _spawn_host_port_from_env() -> tuple[str, int]:
    """Host + preferred TCP port for ``qwenpaw_pet_desktop.app``."""
    url = (os.environ.get("QWENPAW_PET_DESKTOP_URL") or "").strip()
    if url:
        u = urlparse(url)
        host = (u.hostname or "127.0.0.1").strip() or "127.0.0.1"
        if u.port is not None:
            return host, int(u.port)
        if (u.scheme or "http").lower() == "https":
            return host, 443
        return host, 8765
    host = (os.environ.get("QWENPAW_PET_DESKTOP_HOST") or "127.0.0.1").strip()
    host = host or "127.0.0.1"
    port = int(os.environ.get("QWENPAW_PET_DESKTOP_PORT", "8765"))
    return host, port


def _tcp_bind_test(host: str, port: int) -> bool:
    """Return whether ``(host, port)`` is free for a new listener."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def _pick_listen_port(host: str, preferred: int) -> int:
    """Use ``preferred`` if free; otherwise scan upward, then ask the OS.

    Set ``QWENPAW_PET_DESKTOP_STRICT_PORT=1`` to disable fallback (spawn
    may still fail with EADDRINUSE if the port is taken between the probe
    and the child bind — rare on localhost).

    If ``QWENPAW_PET_DESKTOP_URL`` pins an explicit ``host:port``, we never
    pick another port — otherwise the running bridge would not match the
    URL the user configured.
    """
    if os.environ.get("QWENPAW_PET_DESKTOP_STRICT_PORT", "0") == "1":
        return preferred
    if (os.environ.get("QWENPAW_PET_DESKTOP_URL") or "").strip():
        return preferred
    if _tcp_bind_test(host, preferred):
        return preferred
    for p in range(preferred + 1, preferred + 128):
        if _tcp_bind_test(host, p):
            logger.info(
                "QwenPaw Pet: preferred desktop port %s busy on %s; using %s",
                preferred,
                host,
                p,
            )
            return p
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        ephem = int(s.getsockname()[1])
        logger.warning(
            "QwenPaw Pet: desktop using ephemeral port %s on %s",
            ephem,
            host,
        )
        return ephem


def _desktop_url_candidates() -> list[str]:
    """Ordered URLs to try for ``GET /health`` (deduped)."""
    explicit = (os.environ.get("QWENPAW_PET_DESKTOP_URL") or "").strip()
    if explicit:
        return [explicit.rstrip("/")]

    out: list[str] = []
    try:
        from qwenpaw_pet_desktop import runtime as pet_rt

        bu = pet_rt.read_bridge_url()
        if bu:
            out.append(bu.rstrip("/"))
    except Exception:
        pass

    host = (os.environ.get("QWENPAW_PET_DESKTOP_HOST") or "127.0.0.1").strip()
    host = host or "127.0.0.1"
    port = int(os.environ.get("QWENPAW_PET_DESKTOP_PORT", "8765"))
    default_u = f"http://{host}:{port}"
    out.append(default_u.rstrip("/"))

    seen: set[str] = set()
    uniq: list[str] = []
    for u in out:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


def _resolved_desktop_base_url() -> str:
    """Base URL for mutating HTTP calls (``/event``, ``/pet``).

    Prefer the last healthy endpoint; otherwise probe once via
    ``desktop_health``; fall back to the first candidate.
    """
    global _active_desktop_base
    if _active_desktop_base:
        return _active_desktop_base.rstrip("/")
    desktop_health()
    if _active_desktop_base:
        return _active_desktop_base.rstrip("/")
    cands = _desktop_url_candidates()
    return cands[0].rstrip("/") if cands else "http://127.0.0.1:8765"


def desktop_health() -> dict[str, Any] | None:
    global _active_desktop_base
    for base in _desktop_url_candidates():
        try:
            response = httpx.get(
                f"{base.rstrip('/')}/health",
                **_httpx_client_kwargs(),
            )
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict):
                _active_desktop_base = base.rstrip("/")
                return data
        except Exception:
            continue
    _active_desktop_base = None
    return None


_MISSING_DEPS_HINT = (
    "Desktop runtime import failed (likely a missing dependency in "
    "QwenPaw's interpreter). Install into the same environment: "
    'pip install "fastapi>=0.110" "uvicorn>=0.27" "pillow>=10.0" '
    '"pyside6-essentials>=6.6" (PySide6 wheels exist for Python 3.10-3.13).'
)


def _spawn_desktop_background() -> tuple[bool, str | None]:
    """Start the pet desktop in a detached process.

    Runs ``sys.executable -m qwenpaw_pet_desktop.app``. The package lives
    next to this plugin and is on the *parent's* ``sys.path`` because
    ``plugin.py`` injects the plugin directory; the child process gets
    that location via ``PYTHONPATH`` so ``python -m qwenpaw_pet_desktop.app``
    resolves without any ``pip install``. Third-party deps (fastapi,
    uvicorn, pillow, PySide6) still need to be available to ``sys.executable``.

    Returns:
        ``(True, None)`` if a process was spawned, else
        ``(False, user-facing reason)``.
    """
    try:
        from qwenpaw_pet_desktop import runtime as pet_rt
    except ImportError as exc:
        return False, f"{_MISSING_DEPS_HINT} ({exc})"

    try:
        pet_rt.ensure_runtime()
        # Create the bridge token *before* spawning so the very first
        # event the plugin emits already carries ``X-QwenPaw-Pet-Token``
        # (the server requires the token by default; without this the
        # window between spawn and ``ensure_token`` would 401).
        try:
            pet_rt.ensure_token()
        except Exception:
            logger.warning(
                "Could not pre-create pet bridge token",
                exc_info=True,
            )
        host, preferred_port = _spawn_host_port_from_env()
        port = _pick_listen_port(host, preferred_port)
        display_host = (
            "127.0.0.1" if host in ("0.0.0.0", "::", "[::]") else host
        )
        listen_url = f"http://{display_host}:{port}"
        pet_rt.write_bridge_url(listen_url)

        cmd: list[str] = [
            sys.executable,
            "-m",
            "qwenpaw_pet_desktop.app",
            "--host",
            host,
            "--port",
            str(port),
        ]
        scale = os.environ.get("QWENPAW_PET_DESKTOP_SCALE")
        if scale:
            cmd.extend(["--scale", str(scale)])
        pet_dir = os.environ.get("QWENPAW_PET_DESKTOP_PET_DIR")
        if pet_dir:
            cmd.extend(["--pet-dir", pet_dir])
        # subprocess does *not* inherit the parent's runtime sys.path
        # mutations (plugin.py adds the plugin dir to sys.path so the
        # embedded ``qwenpaw_pet_desktop`` package is importable here).
        # Propagate that path via PYTHONPATH so ``python -m
        # qwenpaw_pet_desktop.app`` can find the package.
        env = os.environ.copy()
        plugin_dir = str(Path(__file__).resolve().parent)
        existing_pp = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            plugin_dir + os.pathsep + existing_pp
            if existing_pp
            else plugin_dir
        )
        # ``Popen`` duplicates the log FD into the child's stdout/stderr,
        # so the parent's handle is safe to close as soon as the spawn
        # returns. Using ``with`` here both fixes the FD leak and lets
        # the detached child keep writing to the same file.
        with pet_rt.log_path().open("ab") as log_file:
            proc = subprocess.Popen(  # pylint: disable=consider-using-with
                cmd,
                stdout=log_file,
                stderr=log_file,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                env=env,
            )
        pet_rt.write_pid(proc.pid)
        global _active_desktop_base
        _active_desktop_base = listen_url
        _mark_desktop_owned()
        return True, None
    except OSError as exc:
        return False, f"failed to start desktop: {exc}"


def _stop_pid(  # pylint: disable=too-many-branches
    pid: int,
    *,
    grace: float = 2.0,
) -> bool:
    """Best-effort terminate ``pid`` and its session.

    Sends ``SIGTERM`` first (to the whole session group when possible —
    the desktop spawns with ``start_new_session=True``), waits up to
    ``grace`` seconds for graceful exit, then escalates to ``SIGKILL``.
    Returns ``True`` if the process is no longer running by the end.

    The branch count is deliberately high: every signal call has to
    independently distinguish "process already gone" (success) from
    "permission denied / EPERM" (failure to log) on both the per-PID
    and per-session-group code paths. Squashing those branches behind
    a helper would lose either the granular error logging or the
    process-group fallback, so we silence pylint here instead.
    """
    sent_term = False
    try:
        pgid = os.getpgid(pid)
    except OSError:
        pgid = None

    try:
        if pgid is not None and pgid != os.getpgid(os.getpid()):
            os.killpg(pgid, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
        sent_term = True
    except ProcessLookupError:
        return True
    except OSError as exc:
        logger.warning("SIGTERM to pet desktop pid=%s failed: %s", pid, exc)

    if sent_term:
        deadline = time.time() + grace
        while time.time() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return True
            except OSError:
                return True
            time.sleep(0.1)

    try:
        if pgid is not None and pgid != os.getpgid(os.getpid()):
            os.killpg(pgid, signal.SIGKILL)
        else:
            os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    except OSError as exc:
        logger.warning("SIGKILL to pet desktop pid=%s failed: %s", pid, exc)
        return False
    return True


def stop_desktop(*, force: bool = False) -> dict[str, Any]:
    """Stop the pet desktop process that this QwenPaw process manages.

    Called from ``_shutdown`` so the floating pet exits together with
    QwenPaw — the default mental model is that the desktop is a child
    of QwenPaw, not a long-running independent service. Users who want
    to keep the pet alive across QwenPaw restarts can opt out with
    ``QWENPAW_PET_STOP_ON_SHUTDOWN=0``.

    By default this only acts on a desktop that QwenPaw has *adopted*
    (``_DESKTOP_OWNED``): either we spawned it, or ``/health`` was
    responding at startup / explicit ``desktop/start`` time. Pass
    ``force=True`` to stop a desktop that QwenPaw never observed (e.g.
    started just now by another tool while QwenPaw was already up).
    """
    if os.environ.get("QWENPAW_PET_STOP_ON_SHUTDOWN", "1") == "0":
        return {"ok": True, "stopped": False, "reason": "opted out"}
    if not _DESKTOP_OWNED and not force:
        return {"ok": True, "stopped": False, "reason": "not autostarted"}

    try:
        from qwenpaw_pet_desktop import runtime as pet_rt
    except ImportError as exc:
        return {
            "ok": True,
            "stopped": False,
            "reason": f"runtime not importable: {exc}",
        }

    pid = pet_rt.read_pid()
    if not pid:
        _clear_desktop_base_url_cache()
        return {"ok": True, "stopped": False, "reason": "no pid file"}
    if not pet_rt.is_pid_running(pid):
        _clear_desktop_base_url_cache()
        return {"ok": True, "stopped": False, "reason": "not running"}

    stopped = _stop_pid(pid)
    _clear_desktop_base_url_cache()
    return {"ok": True, "stopped": stopped, "pid": pid}


def _wait_for_desktop_ready(timeout: float, interval: float = 0.1) -> bool:
    """Poll ``/health`` until the desktop responds or ``timeout`` elapses.

    Uses ``time.sleep`` so this is safe to run only from threads — call
    sites that may execute in an asyncio context should dispatch it via
    ``asyncio.to_thread``.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if desktop_health():
            return True
        time.sleep(interval)
    return False


def ensure_desktop_available() -> None:
    """Best-effort start of the desktop runtime.

    If the executable is not installed or the user prefers manual startup,
    this stays quiet. QwenPaw should never fail because the pet is absent.

    Adoption rule: if a desktop is *already* responding to ``/health`` at
    startup (e.g. left over from a previous QwenPaw run that crashed
    before its shutdown hook ran), the plugin claims it via
    ``_mark_desktop_owned()`` so the shutdown hook will stop it on the
    way out — otherwise the pet would slowly accumulate orphan
    processes that the next QwenPaw run merely "skips spawning".

    The plugin startup hook is registered as a regular callable, but the
    plugin system may invoke us either from an asyncio event loop (during
    async startup) or from a plain thread. We detect the running loop and
    drop the blocking ``_wait_for_desktop_ready`` poll into a worker
    thread so the event loop never stalls for up to two seconds at
    startup.
    """
    if desktop_health():
        _mark_desktop_owned()
        return
    if os.environ.get("QWENPAW_PET_AUTOSTART", "1") == "0":
        return
    ok, hint = _spawn_desktop_background()
    if not ok:
        logger.warning("Could not autostart pet desktop: %s", hint)
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        _wait_for_desktop_ready(2.0)
        return

    async def _poll() -> None:
        await asyncio.to_thread(_wait_for_desktop_ready, 2.0)

    task = loop.create_task(_poll())

    def _done(t: asyncio.Task) -> None:
        try:
            t.result()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.warning(
                "ensure_desktop_available poll task failed",
                exc_info=True,
            )

    task.add_done_callback(_done)


def start_desktop_interactive() -> dict[str, Any]:
    """Explicit start from HTTP/UI.

    Always tries to spawn (ignores ``QWENPAW_PET_AUTOSTART``). Returns
    a JSON-friendly dict so the console can show *why* start failed.
    """
    health = desktop_health()
    if health and health.get("ok"):
        # User explicitly asked us to start it (via ``POST
        # /desktop/start`` from the console UI) — even though it was
        # already up, treat it as adopted so the shutdown hook will
        # stop it together with QwenPaw.
        _mark_desktop_owned()
        return {
            "ok": True,
            "alreadyRunning": True,
            "launchAttempted": False,
            "desktop": health,
            "message": "Desktop pet is already running.",
        }

    ok, hint = _spawn_desktop_background()
    if not ok:
        return {
            "ok": True,
            "alreadyRunning": False,
            "launchAttempted": False,
            "desktop": desktop_health(),
            "message": hint or "Could not start the desktop pet process.",
            "hint": _MISSING_DEPS_HINT,
        }

    # ``start_desktop_interactive`` is wired to ``POST /desktop/start`` as
    # a sync FastAPI route, so FastAPI dispatches it in a worker thread —
    # blocking ``time.sleep`` here is fine and does not stall the loop.
    if _wait_for_desktop_ready(3.0, interval=0.12):
        return {
            "ok": True,
            "alreadyRunning": False,
            "launchAttempted": True,
            "desktop": desktop_health(),
            "message": "Desktop pet started.",
        }

    return {
        "ok": True,
        "alreadyRunning": False,
        "launchAttempted": True,
        "desktop": desktop_health(),
        "message": (
            "A desktop process was spawned but /health is not ready yet "
            "(it may still be starting, or it exited immediately)."
        ),
        "hint": (
            "See log file under QwenPaw pet runtime "
            "(often ~/.qwenpaw-pet/runtime/pet-desktop.log)."
        ),
    }


def schedule_emit_pet_event(event: str, **payload: Any) -> None:
    """Notify desktop from async QwenPaw code without blocking the event loop.

    Calling sync ``httpx`` inside an ``async def`` blocks the entire asyncio
    runner (including the request that is waiting on tool approval).
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        emit_pet_event(event, **payload)
        return

    async def _run() -> None:
        await asyncio.to_thread(
            functools.partial(emit_pet_event, event, **payload),
        )

    task = loop.create_task(_run())

    def _done(t: asyncio.Task) -> None:
        try:
            t.result()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.warning(
                "schedule_emit_pet_event task failed",
                exc_info=True,
            )

    task.add_done_callback(_done)


def emit_pet_event(event: str, **payload: Any) -> None:
    """Send a lifecycle event to QwenPaw Pet Desktop.

    This function is intentionally fire-and-forget: short timeout, no
    exception escapes into QwenPaw's main request path.
    """
    state = payload.pop("state", None) or EVENT_TO_STATE.get(event, "idle")
    body = {
        "event": event,
        "state": state,
        "source": "qwenpaw",
        **payload,
    }
    try:
        response = httpx.post(
            f"{_resolved_desktop_base_url()}/event",
            json=body,
            headers=_headers(),
            **_httpx_client_kwargs(),
        )
        if response.status_code >= 400:
            logger.warning(
                "QwenPaw Pet Desktop POST /event HTTP %s "
                "event=%s detail=%s",
                response.status_code,
                event,
                (response.text or "")[:200],
            )
    except Exception:
        logger.warning("QwenPaw Pet Desktop POST /event failed", exc_info=True)


def switch_pet_desktop(
    *,
    pet_dir: str | None = None,
    pet_id: str | None = None,
) -> dict[str, Any]:
    """Hot-switch the running pet via ``POST /pet`` (no desktop restart)."""
    body: dict[str, str] = {}
    if pet_dir and str(pet_dir).strip():
        body["pet_dir"] = str(pet_dir).strip()
    elif pet_id and str(pet_id).strip():
        body["pet_id"] = str(pet_id).strip()
    else:
        return {"ok": False, "error": "missing pet_dir or pet_id"}
    client_kw = dict(_httpx_client_kwargs())
    client_kw["timeout"] = 3.0
    try:
        response = httpx.post(
            f"{_resolved_desktop_base_url()}/pet",
            json=body,
            headers=_headers(),
            **client_kw,
        )
        try:
            data = response.json()
        except Exception:
            data = {"ok": response.is_success}
        if not isinstance(data, dict):
            data = {"ok": response.is_success}
        if response.status_code >= 400:
            logger.warning(
                "QwenPaw Pet Desktop POST /pet HTTP %s detail=%s",
                response.status_code,
                (response.text or "")[:300],
            )
        return data
    except Exception as exc:
        logger.warning("QwenPaw Pet Desktop POST /pet failed: %s", exc)
        return {"ok": False, "error": str(exc)}
