#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Benchmark packaged QwenPaw desktop backend startup milestones."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import tempfile
import threading
import time
from typing import Any, TextIO
import urllib.error
import urllib.request
from uuid import uuid4


METRIC_PREFIX = "QWENPAW_STARTUP_METRIC "
METRICS_ENV = "QWENPAW_DESKTOP_STARTUP_METRICS"
SHUTDOWN_TOKEN_ENV = "QWENPAW_DESKTOP_SHUTDOWN_TOKEN"
SHUTDOWN_TOKEN_HEADER = "X-QwenPaw-Desktop-Shutdown-Token"


def parse_metric_line(line: str) -> dict[str, Any] | None:
    """Parse a structured metric embedded in one process output line."""
    marker_index = line.find(METRIC_PREFIX)
    if marker_index < 0:
        return None
    raw_payload = line[marker_index + len(METRIC_PREFIX) :].strip()
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or not payload.get("event"):
        return None
    return payload


def percentile(values: list[float], quantile: float) -> float:
    """Return a linearly interpolated percentile for non-empty values."""
    if not values:
        raise ValueError("percentile requires at least one value")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    fraction = position - lower_index
    lower = ordered[lower_index]
    upper = ordered[upper_index]
    return lower + (upper - lower) * fraction


def summarize_runs(
    runs: list[dict[str, Any]],
    target_event: str,
) -> dict[str, Any]:
    """Summarize successful external and internal target timings."""
    successful = [run for run in runs if run.get("success")]
    wall_values = [float(run["wall_elapsed_ms"]) for run in successful]
    metric_values = [
        float(run["metrics"][target_event]["elapsed_ms"]) for run in successful
    ]

    def _stats(values: list[float]) -> dict[str, float]:
        return {
            "min": round(min(values), 3),
            "p50": round(percentile(values, 0.50), 3),
            "p90": round(percentile(values, 0.90), 3),
            "p95": round(percentile(values, 0.95), 3),
            "max": round(max(values), 3),
        }

    result: dict[str, Any] = {
        "requested_runs": len(runs),
        "successful_runs": len(successful),
        "failed_runs": len(runs) - len(successful),
    }
    if successful:
        result["wall_elapsed_ms"] = _stats(wall_values)
        result["python_elapsed_ms"] = _stats(metric_values)
    return result


def _forward_stream(
    name: str,
    stream: TextIO,
    output_queue: queue.Queue[tuple[str, str | None]],
) -> None:
    try:
        for line in stream:
            output_queue.put((name, line.rstrip("\r\n")))
    finally:
        output_queue.put((name, None))


def _shutdown_backend(port: int | None, token: str) -> None:
    if port is None:
        return
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/desktop/shutdown",
        method="POST",
        headers={SHUTDOWN_TOKEN_HEADER: token},
    )
    try:
        with urllib.request.urlopen(request, timeout=2):
            pass
    except (OSError, urllib.error.URLError):
        pass


def _force_stop(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            [
                "taskkill",
                "/PID",
                f"{process.pid}",
                "/T",
                "/F",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


# pylint: disable=too-many-branches,too-many-statements
def run_once(
    executable: Path,
    working_dir: Path,
    target_event: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Launch the backend once and wait for the requested startup event."""
    shutdown_token = uuid4().hex
    environment = dict(os.environ)
    environment.update(
        {
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUNBUFFERED": "1",
            "QWENPAW_DESKTOP_APP": "1",
            "QWENPAW_WORKING_DIR": str(working_dir),
            METRICS_ENV: "1",
            SHUTDOWN_TOKEN_ENV: shutdown_token,
        },
    )
    creation_flags = 0
    if os.name == "nt":
        creation_flags = subprocess.CREATE_NO_WINDOW
    started_ns = time.perf_counter_ns()
    process = subprocess.Popen(  # pylint: disable=consider-using-with
        [str(executable)],
        cwd=str(executable.parent),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creation_flags,
        start_new_session=os.name != "nt",
    )
    if process.stdout is None or process.stderr is None:
        raise RuntimeError("backend output pipes were not created")

    output_queue: queue.Queue[tuple[str, str | None]] = queue.Queue()
    threads = [
        threading.Thread(
            target=_forward_stream,
            args=("stdout", process.stdout, output_queue),
            daemon=True,
        ),
        threading.Thread(
            target=_forward_stream,
            args=("stderr", process.stderr, output_queue),
            daemon=True,
        ),
    ]
    for thread in threads:
        thread.start()

    metrics: dict[str, dict[str, Any]] = {}
    captured_output: list[dict[str, str]] = []
    deadline = time.monotonic() + timeout_seconds
    target_seen_ns: int | None = None
    open_streams = len(threads)

    try:
        while time.monotonic() < deadline and open_streams:
            try:
                stream_name, line = output_queue.get(timeout=0.1)
            except queue.Empty:
                if process.poll() is not None:
                    continue
                continue
            if line is None:
                open_streams -= 1
                continue
            captured_output.append({"stream": stream_name, "line": line})
            metric = parse_metric_line(line)
            if metric is None:
                continue
            event = str(metric["event"])
            metrics[event] = metric
            if event == target_event:
                target_seen_ns = time.perf_counter_ns()
                break
    finally:
        port_metric = metrics.get("port_bound", {})
        raw_port = port_metric.get("port")
        port = int(raw_port) if raw_port is not None else None
        _shutdown_backend(port, shutdown_token)
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            _force_stop(process)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

    if target_seen_ns is None:
        return {
            "success": False,
            "exit_code": process.poll(),
            "metrics": metrics,
            "output_tail": captured_output[-80:],
            "error": f"event {target_event} was not seen",
        }
    return {
        "success": True,
        "exit_code": process.poll(),
        "wall_elapsed_ms": round(
            (target_seen_ns - started_ns) / 1_000_000,
            3,
        ),
        "metrics": metrics,
        "output_tail": captured_output[-20:],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark packaged desktop backend startup",
    )
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--warmup-runs", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--target-event",
        default="default_agent_ready",
    )
    return parser.parse_args()


def main() -> int:
    """Run warmups and measured launches, then write a JSON report."""
    args = _parse_args()
    executable = args.executable.resolve()
    if not executable.is_file():
        raise FileNotFoundError(
            f"backend executable not found: {executable}",
        )
    if args.runs < 1 or args.warmup_runs < 0:
        raise ValueError("run counts must be positive")

    with tempfile.TemporaryDirectory(
        prefix="qwenpaw-desktop-startup-",
    ) as temporary_dir:
        working_dir = Path(temporary_dir)
        warmups = [
            run_once(
                executable,
                working_dir,
                args.target_event,
                args.timeout,
            )
            for _ in range(args.warmup_runs)
        ]
        runs = [
            run_once(
                executable,
                working_dir,
                args.target_event,
                args.timeout,
            )
            for _ in range(args.runs)
        ]

    report = {
        "schema_version": 1,
        "executable": str(executable),
        "platform": os.name,
        "target_event": args.target_event,
        "warmups": warmups,
        "runs": runs,
        "summary": summarize_runs(runs, args.target_event),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        f"{json.dumps(report, indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )
    print(f"Wrote startup benchmark to {args.output}")
    print(f"{json.dumps(report['summary'], indent=2, sort_keys=True)}")
    return 0 if report["summary"]["successful_runs"] == args.runs else 1


if __name__ == "__main__":
    raise SystemExit(main())
