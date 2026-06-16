"""模拟 Security Center：接收 AgentGateway 错误事件并打印到控制台。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import urlparse

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8091
DEFAULT_EVENTS_PATH = "/security-center/v1/events"


def _normalize_path(path: str) -> str:
    parsed = urlparse(path)
    normalized = parsed.path.rstrip("/") or "/"
    return normalized


def _parse_utc_timestamp(value: str | None) -> datetime | None:
    """Parse ISO-8601 UTC timestamps from AgentGateway / watcher events."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if not text or text == "-":
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_local_time(value: str | datetime | None) -> str:
    """Format a UTC timestamp for the local computer clock."""
    if isinstance(value, datetime):
        parsed = value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    else:
        parsed = _parse_utc_timestamp(value)
    if parsed is None:
        return str(value) if value is not None else "-"
    local_dt = parsed.astimezone()
    local_label = local_dt.strftime("%Y-%m-%d %H:%M:%S")
    tz_name = local_dt.tzname() or "local"
    utc_label = parsed.strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"{local_label} ({tz_name}) | UTC {utc_label}"


def _emit(message: str, *, stream: TextIO | None = None) -> None:
    """Write to console.

    On Windows, PowerShell may not show stdout written from HTTP worker
    threads. stderr is reliable, so event output uses stderr by default.
    """
    target = stream or sys.stderr
    target.write(message)
    if not message.endswith("\n"):
        target.write("\n")
    target.flush()


def _print_event(event: dict[str, Any], *, index: int, stream: TextIO | None = None) -> None:
    received_utc = datetime.now(timezone.utc)
    severity = event.get("severity", "-")
    event_type = event.get("eventTypeId", "-")
    event_id = event.get("eventId", "-")
    summary = event.get("summary", "")
    occurred_at = event.get("occurredAt", "-")
    source = event.get("sourceSystem", "-")

    lines = [
        "",
        "=" * 72,
        f"[{_format_local_time(received_utc)}] EVENT #{index}",
        "-" * 72,
        f"  sourceSystem : {source}",
        f"  eventId      : {event_id}",
        f"  eventTypeId  : {event_type}",
        f"  severity     : {severity}",
        f"  occurredAt   : {_format_local_time(occurred_at)}",
        f"  summary      : {summary}",
    ]

    payload = event.get("payload")
    if isinstance(payload, dict) and payload:
        lines.append("  payload:")
        for key in (
            "httpMethod",
            "httpPath",
            "httpStatus",
            "jwtSubject",
            "mcpTool",
            "mcpTarget",
            "error",
            "reason",
            "logLevel",
            "sourceFile",
        ):
            value = payload.get(key)
            if value:
                lines.append(f"    {key}: {value}")

    lines.extend(
        [
            "-" * 72,
            "  full event:",
            json.dumps(event, ensure_ascii=False, indent=2),
            "=" * 72,
        ]
    )
    _emit("\n".join(lines), stream=stream)


class MockSecurityCenterHandler(BaseHTTPRequestHandler):
    server_version = "MockSecurityCenter/1.0"
    event_count = 0
    events_path = DEFAULT_EVENTS_PATH
    event_log_file: Path | None = None

    def log_message(self, format: str, *args: Any) -> None:
        _emit("[http] " + (format % args))

    def _send_json(self, status: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _append_event_log(self, event: dict[str, Any]) -> None:
        log_file = type(self).event_log_file
        if log_file is None:
            return
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    def do_GET(self) -> None:
        if _normalize_path(self.path) == "/health":
            self._send_json(
                200,
                {
                    "status": "ok",
                    "service": "mock-security-center",
                    "eventsReceived": type(self).event_count,
                },
            )
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if _normalize_path(self.path) != _normalize_path(type(self).events_path):
            self._send_json(404, {"error": "not found", "path": self.path})
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            event = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            self._send_json(400, {"error": "invalid json", "detail": str(exc)})
            return

        if not isinstance(event, dict):
            self._send_json(400, {"error": "event body must be a JSON object"})
            return

        type(self).event_count += 1
        _print_event(event, index=type(self).event_count)
        self._append_event_log(event)

        event_id = str(event.get("eventId") or f"mock-{type(self).event_count}")
        self._send_json(
            200,
            {
                "status": "accepted",
                "eventId": event_id,
                "receivedAt": datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
            },
        )


def parse_args() -> argparse.Namespace:
    demo_root = Path(__file__).resolve().parents[1]
    default_log = demo_root / "logs" / "mock-security-center.events.jsonl"

    parser = argparse.ArgumentParser(
        description="Mock Security Center for AgentGateway error event integration tests.",
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--events-path", default=DEFAULT_EVENTS_PATH)
    parser.add_argument(
        "--event-log-file",
        type=Path,
        default=default_log,
        help="Append received events as JSON lines (backup when console output is missed).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    MockSecurityCenterHandler.events_path = args.events_path
    MockSecurityCenterHandler.event_log_file = args.event_log_file

    # Single-threaded server: avoids Windows console stdout issues from worker threads.
    server = HTTPServer((args.host, args.port), MockSecurityCenterHandler)
    url = f"http://{args.host}:{args.port}{args.events_path}"
    health_url = f"http://{args.host}:{args.port}/health"

    _emit("Mock Security Center started")
    _emit(f"  listen       : {args.host}:{args.port}")
    _emit(f"  events POST  : {url}")
    _emit(f"  health GET   : {health_url}")
    _emit(f"  event log    : {args.event_log_file}")
    _emit("  waiting for AgentGateway error events... (Ctrl+C to stop)")
    _emit("")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _emit("\nMock Security Center stopped.")
    finally:
        server.server_close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
