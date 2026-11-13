#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dev_watch.py — Watch creator sources and hot-sync into a running QwenPaw.

Frontend: expects `vite build --watch` (started by dev.sh) to keep
rebuilding ui/dist incrementally; any dist change is rsynced into the
installed plugin copy. Plugin static files are read from disk on every
request, so a browser hard-refresh is all that's needed — no reinstall.

Backend: any backend/*.py change is rsynced into the installed copy and
then hot-reloaded via `POST /api/plugins/install` with source pointing at
the installed dir itself. The loader skips copytree when source == target,
so this is a pure module reload (~1s), using the localhost auth bypass.
"""

import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKING_DIR = os.path.expanduser(
    os.environ.get("QWENPAW_WORKING_DIR", "~/.qwenpaw"),
)
PORT = os.environ.get("QWENPAW_PORT", "8088")
INSTALLED_DIR = os.path.join(WORKING_DIR, "plugins", "qwenpaw-creator")
POLL_SECONDS = 1.0

# Watch only vite's outDir (dist/app). dist/index.js is NOT watched or
# written here: vite watch ignores only its outDir, so writing anything
# else under ui/ (e.g. via package-plugin.mjs) retriggers a rebuild and
# creates an endless build loop. The entry is generated in-memory and
# written straight into the installed copy instead.
FRONTEND_SRC = os.path.join(PLUGIN_DIR, "ui", "dist", "app")
BACKEND_SRC = os.path.join(PLUGIN_DIR, "backend")


def snapshot(root: str, exts: tuple = ()) -> dict:
    result = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            if exts and not name.endswith(exts):
                continue
            path = os.path.join(dirpath, name)
            try:
                result[path] = os.stat(path).st_mtime
            except OSError:
                pass
    return result


def rsync(src: str, dst: str) -> None:
    subprocess.run(
        [
            "rsync",
            "-a",
            "--delete",
            "--exclude",
            "__pycache__",
            src.rstrip("/") + "/",
            dst.rstrip("/") + "/",
        ],
        check=True,
    )


def sync_frontend() -> None:
    """Mirror dist/app into the installed copy and regenerate index.js.

    Replicates ui/scripts/package-plugin.mjs (build-id substitution into
    plugin-entry.js) without touching the workspace, to avoid retriggering
    vite watch.
    """
    index_html = os.path.join(FRONTEND_SRC, "index.html")
    with open(index_html, "rb") as f:
        build_id = hashlib.sha256(f.read()).hexdigest()[:12]
    with open(
        os.path.join(PLUGIN_DIR, "ui", "plugin-entry.js"),
        encoding="utf-8",
    ) as f:
        entry = f.read()
    if "__CREATOR_BUILD_ID__" not in entry:
        raise RuntimeError(
            "plugin-entry.js missing __CREATOR_BUILD_ID__ placeholder",
        )
    dst_dist = os.path.join(INSTALLED_DIR, "ui", "dist")
    rsync(FRONTEND_SRC, os.path.join(dst_dist, "app"))
    with open(os.path.join(dst_dist, "index.js"), "w", encoding="utf-8") as f:
        f.write(entry.replace("__CREATOR_BUILD_ID__", build_id))


def reload_backend() -> None:
    payload = json.dumps({"source": INSTALLED_DIR, "force": True}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/api/plugins/install",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        json.loads(resp.read())


def main() -> None:
    if not os.path.isdir(INSTALLED_DIR):
        sys.exit(
            f"Installed copy not found: {INSTALLED_DIR}\n"
            "Run scripts/dev.sh install once first.",
        )
    print(f"[dev-watch] installed copy : {INSTALLED_DIR}")
    print(
        "[dev-watch] backend reload : "
        f"POST 127.0.0.1:{PORT}/api/plugins/install (force)",
    )
    print("[dev-watch] watching ui/dist/app and backend/ ... (Ctrl+C to stop)")

    fe_state = snapshot(FRONTEND_SRC)
    be_state = snapshot(BACKEND_SRC, (".py", ".json", ".txt"))

    while True:
        time.sleep(POLL_SECONDS)

        fe_now = snapshot(FRONTEND_SRC)
        if fe_now != fe_state:
            # Debounce: wait until the vite rebuild fully settles (snapshot
            # stable across two polls) before syncing.
            while True:
                time.sleep(0.7)
                settled = snapshot(FRONTEND_SRC)
                if settled == fe_now:
                    break
                fe_now = settled
            try:
                sync_frontend()
                fe_state = fe_now
                print(
                    f"[dev-watch] {time.strftime('%H:%M:%S')} "
                    "frontend synced — hard-refresh the browser",
                )
            except Exception as exc:
                # Keep fe_state unchanged so the next poll retries (e.g. a
                # sync attempted mid-build before index.html existed).
                print(
                    f"[dev-watch] frontend sync failed, retrying: {exc}",
                    file=sys.stderr,
                )
                time.sleep(2)

        be_now = snapshot(BACKEND_SRC, (".py", ".json", ".txt"))
        if be_now != be_state:
            rsync(BACKEND_SRC, os.path.join(INSTALLED_DIR, "backend"))
            be_state = be_now
            try:
                reload_backend()
                print(
                    f"[dev-watch] {time.strftime('%H:%M:%S')} "
                    "backend synced + hot-reloaded",
                )
            except Exception as exc:
                print(
                    f"[dev-watch] backend reload FAILED: {exc}",
                    file=sys.stderr,
                )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[dev-watch] stopped")
