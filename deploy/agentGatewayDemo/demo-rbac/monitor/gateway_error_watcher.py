"""实时监控 AgentGateway 日志，将错误事件上报到 Security Center。"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

DEFAULT_SECURITY_CENTER_URL = "http://127.0.0.1:8091"
DEFAULT_EVENTS_PATH = "/security-center/v1/events"
DEFAULT_POLL_SECONDS = 0.5
DEFAULT_REQUEST_TIMEOUT = 10

LOG_HEADER_RE = re.compile(r"^(\S+)\s+(\S+)\s+(\S+)\s+(.*)$")
QUOTED_FIELD_RE = re.compile(r'(?P<key>[\w.\-]+)="(?P<val>[^"]*)"')
PLAIN_FIELD_RE = re.compile(r"(?P<key>[\w.\-]+)=(?P<val>\S+)")


def parse_access_log_line(line: str) -> dict[str, Any]:
    """解析 AgentGateway access log 行（与 demo-rbac/scripts/_auth-log-parse.ps1 对齐）。"""
    result: dict[str, Any] = {
        "raw": line,
        "timestamp": None,
        "level": None,
        "scope": None,
        "fields": {},
    }
    rest = line
    match = LOG_HEADER_RE.match(line)
    if match:
        result["timestamp"] = match.group(1)
        result["level"] = match.group(2)
        result["scope"] = match.group(3)
        rest = match.group(4)

    fields: dict[str, str] = {}
    for field_match in QUOTED_FIELD_RE.finditer(rest):
        fields[field_match.group("key")] = field_match.group("val")

    stripped = QUOTED_FIELD_RE.sub(" ", rest)
    for field_match in PLAIN_FIELD_RE.finditer(stripped):
        key = field_match.group("key")
        if key not in fields:
            fields[key] = field_match.group("val")

    result["fields"] = fields
    return result


def _http_status(fields: dict[str, str]) -> int | None:
    raw = fields.get("http.status")
    if not raw or not raw.isdigit():
        return None
    return int(raw)


def classify_error(parsed: dict[str, Any]) -> tuple[bool, str, str]:
    """返回 (is_error, event_type_id, severity)。"""
    level = (parsed.get("level") or "").lower()
    fields = parsed.get("fields") or {}
    error_text = fields.get("error", "").strip()
    status = _http_status(fields)

    if level in {"error", "critical", "fatal"}:
        return True, "gateway_log_error", "HIGH"
    if level == "warn" and error_text:
        return True, "gateway_log_warning", "MEDIUM"

    if parsed.get("scope") == "request":
        if error_text:
            if "unknown tool" in error_text.lower():
                return True, "mcp_authorization_deny", "MEDIUM"
            if error_text.lower().startswith("mcp:"):
                return True, "mcp_protocol_error", "MEDIUM"
            return True, "gateway_request_error", "MEDIUM"
        if status is not None and status >= 500:
            return True, "http_server_error", "HIGH"
        if status is not None and status >= 400:
            return True, "http_client_error", "LOW"

    if error_text:
        return True, "gateway_log_error", "MEDIUM"

    return False, "", ""


def build_summary(parsed: dict[str, Any], event_type_id: str) -> str:
    fields = parsed.get("fields") or {}
    error_text = fields.get("error")
    status = fields.get("http.status")
    method = fields.get("http.method")
    path = fields.get("http.path")
    subject = fields.get("jwt.sub")
    tool = fields.get("gen_ai.tool.name") or fields.get("audit_mcp_tool")

    parts = [f"AgentGateway {event_type_id}"]
    if method and path:
        parts.append(f"{method} {path}")
    if status:
        parts.append(f"status={status}")
    if subject:
        parts.append(f"subject={subject}")
    if tool:
        parts.append(f"tool={tool}")
    if error_text:
        parts.append(error_text)
    elif parsed.get("scope"):
        parts.append(f"scope={parsed['scope']}")
    return " | ".join(parts)


def build_payload(parsed: dict[str, Any], source_file: str) -> dict[str, Any]:
    fields = parsed.get("fields") or {}
    payload = {
        "gateway": fields.get("gateway"),
        "listener": fields.get("listener"),
        "route": fields.get("route"),
        "httpMethod": fields.get("http.method"),
        "httpPath": fields.get("http.path"),
        "httpStatus": fields.get("http.status"),
        "jwtSubject": fields.get("jwt.sub"),
        "mcpMethod": fields.get("mcp.method.name"),
        "mcpTarget": fields.get("mcp.target"),
        "mcpTool": fields.get("gen_ai.tool.name") or fields.get("audit_mcp_tool"),
        "error": fields.get("error"),
        "reason": fields.get("reason"),
        "protocol": fields.get("protocol"),
        "logLevel": parsed.get("level"),
        "logScope": parsed.get("scope"),
        "sourceFile": source_file,
        "rawLogLine": parsed.get("raw"),
    }
    return {key: value for key, value in payload.items() if value is not None}


def make_event_id(parsed: dict[str, Any]) -> str:
    raw = parsed.get("raw") or ""
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    ts = (parsed.get("timestamp") or datetime.now(timezone.utc).isoformat()).replace(":", "")
    return f"agw-{ts}-{digest}"


def format_request_error(exc: requests.RequestException) -> str:
    parts = [str(exc)]
    response = getattr(exc, "response", None)
    if response is not None:
        parts.append(f"status={response.status_code}")
        body = (response.text or "").strip()
        if body:
            parts.append(f"body={body}")
    return " | ".join(parts)


def normalize_occurred_at(parsed: dict[str, Any]) -> str:
    ts = parsed.get("timestamp")
    if ts:
        if ts.endswith("Z"):
            return ts
        return f"{ts}Z"
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class SecurityCenterClient:
    def __init__(self, base_url: str, events_path: str, timeout: float) -> None:
        self._url = base_url.rstrip("/") + events_path
        self._timeout = timeout
        self._session = requests.Session()

    def send_event(self, event: dict[str, Any]) -> dict[str, Any]:
        response = self._session.post(self._url, json=event, timeout=self._timeout)
        response.raise_for_status()
        if not response.content:
            return {}
        return response.json()


class LogTailWatcher:
    def __init__(
        self,
        path: Path,
        client: SecurityCenterClient,
        *,
        source_system: str,
        schema_version: str,
        poll_seconds: float,
        state: dict[str, Any],
        sent_fingerprints: set[str],
        logger: logging.Logger,
    ) -> None:
        self.path = path
        self.client = client
        self.source_system = source_system
        self.schema_version = schema_version
        self.poll_seconds = poll_seconds
        self.state = state
        self.sent_fingerprints = sent_fingerprints
        self.logger = logger
        self._key = str(path)

    def _offset(self) -> int:
        files = self.state.setdefault("files", {})
        if self._key not in files:
            if self.path.exists():
                return self.path.stat().st_size
            return 0
        return int(files[self._key])

    def _set_offset(self, offset: int) -> None:
        self.state.setdefault("files", {})[self._key] = offset

    def _process_line(self, line: str) -> None:
        line = line.rstrip("\r\n")
        if not line.strip() or line.startswith("--- restart "):
            return

        if self._key.endswith(".err"):
            parsed = {
                "raw": line,
                "timestamp": datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
                "level": "error",
                "scope": "stderr",
                "fields": {"error": line},
            }
            is_error = True
            event_type_id = "gateway_stderr_error"
            severity = "HIGH"
        else:
            parsed = parse_access_log_line(line)
            is_error, event_type_id, severity = classify_error(parsed)
            if not is_error:
                return

        fingerprint = hashlib.sha256((parsed.get("raw") or "").encode("utf-8")).hexdigest()
        if fingerprint in self.sent_fingerprints:
            return
        self.sent_fingerprints.add(fingerprint)
        if len(self.sent_fingerprints) > 2000:
            self.sent_fingerprints.clear()

        event = {
            "sourceSystem": self.source_system,
            "eventId": make_event_id(parsed),
            "eventTypeId": event_type_id,
            "schemaVersion": self.schema_version,
            "severity": severity,
            "summary": build_summary(parsed, event_type_id),
            "occurredAt": normalize_occurred_at(parsed),
            "payload": build_payload(parsed, self.path.name),
        }

        try:
            result = self.client.send_event(event)
            self.logger.info(
                "sent eventId=%s type=%s severity=%s response=%s",
                event["eventId"],
                event_type_id,
                severity,
                json.dumps(result, ensure_ascii=False) if result else "ok",
            )
        except requests.RequestException as exc:
            self.logger.error(
                "failed to send eventId=%s type=%s: %s",
                event["eventId"],
                event_type_id,
                format_request_error(exc),
            )

    def run_once(self) -> None:
        if not self.path.exists():
            return

        current_size = self.path.stat().st_size
        offset = self._offset()
        if offset > current_size:
            offset = 0

        with self.path.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(offset)
            while True:
                line = handle.readline()
                if not line:
                    break
                self._process_line(line)
            self._set_offset(handle.tell())

    def watch_forever(self, stop_path: Path | None) -> None:
        self.logger.info("watching %s", self.path)
        while True:
            if stop_path and stop_path.exists():
                self.logger.info("stop signal detected, exiting")
                return
            self.run_once()
            time.sleep(self.poll_seconds)


def load_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"files": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"files": {}}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    demo_root = Path(__file__).resolve().parents[1]
    default_log = demo_root / "logs" / "gateway-access.log"
    default_state = demo_root / "logs" / "gateway-error-watcher.state.json"

    parser = argparse.ArgumentParser(description="Watch AgentGateway logs and report errors.")
    parser.add_argument("--log-file", type=Path, default=default_log)
    parser.add_argument("--stderr-log-file", type=Path, default=default_log.with_suffix(".log.err"))
    parser.add_argument("--state-file", type=Path, default=default_state)
    parser.add_argument("--security-center-url", default=os.getenv("SECURITY_CENTER_URL", DEFAULT_SECURITY_CENTER_URL))
    parser.add_argument("--events-path", default=os.getenv("SECURITY_CENTER_EVENTS_PATH", DEFAULT_EVENTS_PATH))
    parser.add_argument("--source-system", default=os.getenv("SECURITY_CENTER_SOURCE_SYSTEM", "agentgateway_rbac"))
    parser.add_argument("--schema-version", default="1.0")
    parser.add_argument("--poll-seconds", type=float, default=DEFAULT_POLL_SECONDS)
    parser.add_argument("--timeout", type=float, default=DEFAULT_REQUEST_TIMEOUT)
    parser.add_argument("--from-start", action="store_true", help="Scan existing log content instead of tailing from saved offset.")
    parser.add_argument("--once", action="store_true", help="Process available lines once and exit.")
    return parser.parse_args()


def configure_logging() -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )
    return logging.getLogger("gateway_error_watcher")


def main() -> int:
    args = parse_args()
    logger = configure_logging()

    state = load_state(args.state_file)
    if args.from_start:
        state = {"files": {}}

    client = SecurityCenterClient(args.security_center_url, args.events_path, args.timeout)
    sent_fingerprints: set[str] = set()

    watchers = [
        LogTailWatcher(
            args.log_file,
            client,
            source_system=args.source_system,
            schema_version=args.schema_version,
            poll_seconds=args.poll_seconds,
            state=state,
            sent_fingerprints=sent_fingerprints,
            logger=logger,
        ),
        LogTailWatcher(
            args.stderr_log_file,
            client,
            source_system=args.source_system,
            schema_version=args.schema_version,
            poll_seconds=args.poll_seconds,
            state=state,
            sent_fingerprints=sent_fingerprints,
            logger=logger,
        ),
    ]

    logger.info(
        "security center=%s%s sourceSystem=%s",
        args.security_center_url.rstrip("/"),
        args.events_path,
        args.source_system,
    )

    stop_path = args.state_file.with_suffix(".stop")

    try:
        if args.once:
            for watcher in watchers:
                watcher.run_once()
            save_state(args.state_file, state)
            return 0

        if stop_path.exists():
            stop_path.unlink(missing_ok=True)

        while True:
            if stop_path.exists():
                logger.info("stop signal detected, exiting")
                break
            for watcher in watchers:
                watcher.run_once()
            save_state(args.state_file, state)
            time.sleep(args.poll_seconds)
    except KeyboardInterrupt:
        logger.info("interrupted, exiting")
    finally:
        save_state(args.state_file, state)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
