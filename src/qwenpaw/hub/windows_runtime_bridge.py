# -*- coding: utf-8 -*-
"""AppContainer-side supervisor for a Windows Hub Local runtime."""

from __future__ import annotations

import argparse
import subprocess
import threading

from .windows_reverse_tunnel import run_reverse_tunnel_client


def main() -> int:
    """Run QwenPaw and its outbound reverse-tunnel client together."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--control-port", type=int, required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--target-port", type=int, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    arguments = parser.parse_args()
    command = list(arguments.command)
    if command and command[0] == "--":
        command.pop(0)
    if not command:
        parser.error("runtime command is required")

    stop_event = threading.Event()
    tunnel = threading.Thread(
        target=run_reverse_tunnel_client,
        args=(
            arguments.control_port,
            arguments.token,
            arguments.target_port,
            stop_event,
        ),
        name="qwenpaw-runtime-tunnel",
        daemon=True,
    )
    tunnel.start()
    try:
        return subprocess.run(command, check=False).returncode
    finally:
        stop_event.set()
        tunnel.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
