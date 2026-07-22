# -*- coding: utf-8 -*-
"""Command-line management for QwenPaw Pet Desktop."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from . import runtime
from .pet_package import install_default_pet, install_pet


def _get_json(url: str, timeout: float = 0.8) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def command_init(_args: argparse.Namespace) -> int:
    target = install_default_pet()
    token = runtime.ensure_token()
    print(f"Installed default pet: {target}")
    print(f"QwenPaw working dir: {runtime.qwenpaw_working_dir()}")
    print(f"Pet resources dir: {runtime.pets_dir()}")
    print(f"Runtime home: {runtime.home_dir()}")
    print(f"Token path: {runtime.token_path()} ({len(token)} chars)")
    print("")
    print("Install the QwenPaw backend plugin with:")
    print("  qwenpaw plugin install ./plugins/qwenpaw-pet")
    return 0


def command_start(args: argparse.Namespace) -> int:
    runtime.ensure_runtime()
    try:
        health = _get_json(f"http://127.0.0.1:{args.port}/health")
        if health.get("ok"):
            print(f"QwenPaw Pet already running on port {args.port}")
            return 0
    except Exception:
        pass

    if args.foreground:
        from .app import main as app_main

        app_args = ["--port", str(args.port), "--scale", str(args.scale)]
        if args.pet_dir:
            app_args.extend(["--pet-dir", args.pet_dir])
        return app_main(app_args)

    # log_file is held open for the lifetime of the spawned child;
    # a ``with`` block would close it before the child writes anything.
    log_file = runtime.log_path().open(  # pylint: disable=consider-using-with
        "ab",
    )
    cmd = [
        sys.executable,
        "-m",
        "qwenpaw_pet_desktop.app",
        "--port",
        str(args.port),
        "--scale",
        str(args.scale),
    ]
    if args.pet_dir:
        cmd.extend(["--pet-dir", args.pet_dir])
    # Fire-and-forget detached daemon: a ``with`` block would wait on
    # exit, which is the opposite of what we want here.
    process = runtime.detached_popen(
        cmd,
        stdout=log_file,
        stderr=log_file,
        stdin=subprocess.DEVNULL,
        env=os.environ.copy(),
    )
    runtime.write_pid(process.pid)
    print(f"Started QwenPaw Pet Desktop (pid {process.pid})")
    print(f"Log: {runtime.log_path()}")
    return 0


def command_stop(_args: argparse.Namespace) -> int:
    result = runtime.stop_process()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def command_status(args: argparse.Namespace) -> int:
    status = runtime.current_process_status()
    try:
        status["health"] = _get_json(f"http://127.0.0.1:{args.port}/health")
    except urllib.error.URLError as exc:
        status["healthError"] = str(exc)
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


def command_install_pet(args: argparse.Namespace) -> int:
    target = install_pet(Path(args.path).expanduser().resolve())
    print(f"Installed pet: {target}")
    return 0


def command_install_default_pet(_args: argparse.Namespace) -> int:
    target = install_default_pet()
    print(f"Installed default pet: {target}")
    return 0


def command_token(_args: argparse.Namespace) -> int:
    token = runtime.ensure_token()
    print(token)
    return 0


def command_switch(args: argparse.Namespace) -> int:
    body: dict[str, str] = {}
    if args.pet_dir:
        body["pet_dir"] = args.pet_dir
    else:
        body["pet_id"] = args.pet_id
    data = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    token = runtime.read_token()
    if token:
        headers["X-QwenPaw-Pet-Token"] = token
    request = urllib.request.Request(
        f"http://127.0.0.1:{args.port}/pet",
        data=data,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5.0) as response:
            print(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        err = exc.read().decode("utf-8", errors="replace")
        print(err, file=sys.stderr)
        return 1
    return 0


def command_send(args: argparse.Namespace) -> int:
    body = {"event": args.event, "state": args.state, "text": args.text}
    data = json.dumps(
        {k: v for k, v in body.items() if v is not None},
    ).encode()
    request = urllib.request.Request(
        f"http://127.0.0.1:{args.port}/event",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=1.0) as response:
        print(response.read().decode("utf-8"))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="qwenpaw-pet")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="Install the bundled default pet")
    p.set_defaults(func=command_init)

    p = sub.add_parser("start", help="Start the desktop pet")
    p.add_argument("--foreground", action="store_true")
    p.add_argument("--pet-dir", default=None)
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--scale", type=float, default=0.58)
    p.set_defaults(func=command_start)

    p = sub.add_parser("stop", help="Stop the desktop pet")
    p.set_defaults(func=command_stop)

    p = sub.add_parser("status", help="Show runtime status")
    p.add_argument("--port", type=int, default=8765)
    p.set_defaults(func=command_status)

    p = sub.add_parser("install-pet", help="Install a pet package folder")
    p.add_argument("path")
    p.set_defaults(func=command_install_pet)

    p = sub.add_parser("install-default-pet", help="Install bundled pet")
    p.set_defaults(func=command_install_default_pet)

    p = sub.add_parser("token", help="Print the local update token")
    p.set_defaults(func=command_token)

    p = sub.add_parser(
        "switch",
        help="Hot-switch pet on the running desktop (no restart)",
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--pet-dir", help="Full path to a pet package directory")
    g.add_argument(
        "--pet-id",
        help="Folder name under QwenPaw pets/ (e.g. snowpaw)",
    )
    p.add_argument("--port", type=int, default=8765)
    p.set_defaults(func=command_switch)

    p = sub.add_parser("send", help="Send a test event to the desktop")
    p.add_argument("event")
    p.add_argument("--state", default=None)
    p.add_argument("--text", default=None)
    p.add_argument("--port", type=int, default=8765)
    p.set_defaults(func=command_send)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
