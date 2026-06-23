"""Reproduce Issue #5379: Windows uvicorn get_remote_addr crash.

This script demonstrates the bug reported in the issue and verifies
the fix.  Run with:  python test_windows_patch.py

Bug report: https://github.com/agentscope-ai/QwenPaw/issues/5379
"""
from __future__ import annotations

import sys
import textwrap


# ---------------------------------------------------------------------------
# Mock transport that simulates the corrupted data seen in the bug report
# ---------------------------------------------------------------------------
class _CorruptedTransport:
    """Simulate Windows ProactorEventLoop returning garbage peername."""

    CORRUPTED_PORT = b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"

    def __init__(self, corrupted: bool = True) -> None:
        if corrupted:
            # Exact data shape from the user's error log (line 125):
            # ValueError: invalid literal for int() with base 10: b'\x00\x00...'
            self._peername = ("127.0.0.1", self.CORRUPTED_PORT)
            self._sockname = ("127.0.0.1", self.CORRUPTED_PORT)
        else:
            self._peername = ("127.0.0.1", 12345)
            self._sockname = ("127.0.0.1", 8088)

    def get_extra_info(self, key: str, default=None):
        if key == "peername":
            return self._peername
        if key == "sockname":
            return self._sockname
        return default


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_SEPARATOR = "=" * 72


def _banner(title: str) -> None:
    print(f"\n{_SEPARATOR}")
    print(f"  {title}")
    print(_SEPARATOR)


def _ok(msg: str) -> None:
    print(f"  [PASS] {msg}")


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


# ---------------------------------------------------------------------------
# Step 1: Reproduce the crash WITHOUT the fix
# ---------------------------------------------------------------------------
def step1_reproduce_bug() -> bool:
    """Show the original uvicorn code crashes with corrupted peername."""
    _banner("Step 1: Reproduce the bug (original uvicorn code)")

    import importlib
    import uvicorn.protocols.utils as utils

    # Make sure we have the ORIGINAL (unpatched) functions.
    importlib.reload(utils)

    transport = _CorruptedTransport(corrupted=True)

    print("\n  Simulating the exact error from the user's log:")
    print(f"  peername = {transport.get_extra_info('peername')!r}\n")

    crashed = False
    try:
        result = utils.get_remote_addr(transport)
        _fail(f"Expected ValueError but got: {result!r}")
    except ValueError as exc:
        crashed = True
        _ok(f"Reproduced! Original get_remote_addr raises:\n"
            f"       ValueError: {exc}")
    except TypeError as exc:
        crashed = True
        _ok(f"Reproduced! Original get_remote_addr raises:\n"
            f"       TypeError: {exc}")

    if not crashed:
        _fail("Could not reproduce the crash with corrupted peername.")
        return False

    # Also test get_local_addr
    try:
        result = utils.get_local_addr(transport)
        print(f"\n  get_local_addr returned {result!r} (no crash)")
    except (ValueError, TypeError) as exc:
        _ok(f"get_local_addr also crashes: {type(exc).__name__}: {exc}")

    return True


# ---------------------------------------------------------------------------
# Step 2: Apply the fix and verify it works
# ---------------------------------------------------------------------------
def step2_verify_fix() -> bool:
    """Apply the patch and verify corrupted data no longer crashes."""
    _banner("Step 2: Apply the fix and verify")

    from qwenpaw.cli.app_cmd import _patch_uvicorn_addr_handlers

    _patch_uvicorn_addr_handlers()
    print("  Patch applied: _patch_uvicorn_addr_handlers()\n")

    import uvicorn.protocols.utils as utils

    transport_bad = _CorruptedTransport(corrupted=True)
    transport_good = _CorruptedTransport(corrupted=False)

    all_ok = True

    # --- get_remote_addr with corrupted data ---
    try:
        result = utils.get_remote_addr(transport_bad)
        if result is None:
            _ok("get_remote_addr(corrupted) -> None (no crash)")
        else:
            _fail(f"Expected None, got {result!r}")
            all_ok = False
    except Exception as exc:
        _fail(f"Still crashes after patch: {exc}")
        all_ok = False

    # --- get_remote_addr with valid data ---
    try:
        result = utils.get_remote_addr(transport_good)
        if result == ("127.0.0.1", 12345):
            _ok("get_remote_addr(valid) -> ('127.0.0.1', 12345) (unchanged)")
        else:
            _fail(f"Expected ('127.0.0.1', 12345), got {result!r}")
            all_ok = False
    except Exception as exc:
        _fail(f"Unexpected error with valid data: {exc}")
        all_ok = False

    # --- get_local_addr with corrupted data ---
    try:
        result = utils.get_local_addr(transport_bad)
        if result is None:
            _ok("get_local_addr(corrupted) -> None (no crash)")
        else:
            _fail(f"Expected None, got {result!r}")
            all_ok = False
    except Exception as exc:
        _fail(f"get_local_addr still crashes after patch: {exc}")
        all_ok = False

    # --- get_local_addr with valid data ---
    try:
        result = utils.get_local_addr(transport_good)
        if result == ("127.0.0.1", 8088):
            _ok("get_local_addr(valid) -> ('127.0.0.1', 8088) (unchanged)")
        else:
            _fail(f"Expected ('127.0.0.1', 8088), got {result!r}")
            all_ok = False
    except Exception as exc:
        _fail(f"Unexpected error with valid data: {exc}")
        all_ok = False

    return all_ok


# ---------------------------------------------------------------------------
# Step 3: Integration test – real uvicorn server with the patch
# ---------------------------------------------------------------------------
def step3_integration() -> bool:
    """Start a real uvicorn server with the patch, make an HTTP request."""
    _banner("Step 3: Integration test (real uvicorn server + patch)")

    import threading
    import time
    import urllib.request

    import uvicorn
    from fastapi import FastAPI

    from qwenpaw.cli.app_cmd import _patch_uvicorn_addr_handlers

    _patch_uvicorn_addr_handlers()

    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    for _ in range(50):
        if server.started:
            break
        time.sleep(0.1)

    if not server.started:
        _fail("uvicorn server failed to start")
        server.should_exit = True
        thread.join(timeout=3)
        return False

    _ok("uvicorn server started successfully")
    port = server.servers[0].sockets[0].getsockname()[1]

    try:
        resp = urllib.request.urlopen(
            f"http://127.0.0.1:{port}/health",
            timeout=5,
        )
        if resp.status == 200:
            _ok(f"GET /health -> 200 OK")
            return True
        else:
            _fail(f"GET /health -> {resp.status}")
            return False
    except Exception as exc:
        _fail(f"Request failed: {exc}")
        return False
    finally:
        server.should_exit = True
        thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    print(textwrap.dedent(f"""\
        {_SEPARATOR}
        Reproduce & Verify: Issue #5379
        Windows uvicorn get_remote_addr crash with corrupted peername
        Python {sys.version}
        Platform: {sys.platform}
        {_SEPARATOR}
    """))

    results: list[tuple[str, bool]] = []

    results.append(("Step 1: Reproduce bug", step1_reproduce_bug()))
    results.append(("Step 2: Verify fix", step2_verify_fix()))
    results.append(("Step 3: Integration", step3_integration()))

    _banner("Summary")
    all_pass = True
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")
        if not passed:
            all_pass = False

    if all_pass:
        print(f"\n  All steps passed. Bug reproduced and fix verified.")
    else:
        print(f"\n  Some steps failed. Check the output above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
