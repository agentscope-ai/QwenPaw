#!/usr/bin/env python3
"""Loopback-only browser acceptance for the Creator create-video PawApp action."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import quote, urlsplit


LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
SESSION_ID = "pawapp-fake-video-acceptance"
APP_ID = "qwenpaw-creator"
ACTION_ID = "create-video"
WORKSPACE_ID = "default"
EXPECTED_EVENTS = [
    "runtime.started",
    "agent.plan",
    "agent.storyboard",
    "image.generate",
    "agent.video",
    "video.submit",
    "video.poll",
    "agent.compose",
    "agent.complete",
]
PRIVATE_ACTIONS = {"generate-storyboard", "generate-video"}
SUCCESS_STATUSES = {"completed", "complete", "succeeded", "success"}
TERMINAL_STATUSES = SUCCESS_STATUSES | {
    "failed",
    "cancelled",
    "canceled",
    "interrupted",
}
PYPI_STUB_URL = "https://pypi.org/pypi/qwenpaw/json"
DECORATIVE_IMAGE_STUB_URLS = frozenset(
    {
        "https://img.alicdn.com/imgextra/i3/"
        "O1CN01822qqr1PVyaK7MYtn_!!6000000001847-2-tps-40-40.png",
        "https://gw.alicdn.com/imgextra/i3/"
        "O1CN01L3azqd1XIi7O2jumZ_!!6000000002901-2-tps-400-400.png",
    }
)
TRANSPARENT_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360000000020001e221bc330000000049454e44ae426082"
)
CREDENTIAL_ENV_NAMES = {
    "ALIBABA_CLOUD_ACCESS_KEY_ID",
    "ALIBABA_CLOUD_ACCESS_KEY_SECRET",
    "ANTHROPIC_API_KEY",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AZURE_OPENAI_API_KEY",
    "BAILIAN_API_KEY",
    "COHERE_API_KEY",
    "CREATOR_LLM_API_KEY",
    "DASHSCOPE_API_KEY",
    "DEEPSEEK_API_KEY",
    "GEMINI_API_KEY",
    "GITHUB_TOKEN",
    "GOOGLE_API_KEY",
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "MISTRAL_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "QWEN_API_KEY",
    "TAVILY_API_KEY",
    "VOLCENGINE_ACCESS_KEY",
    "VOLCENGINE_SECRET_KEY",
}
PROXY_ENV_NAMES = {
    "ALL_PROXY",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "all_proxy",
    "https_proxy",
    "http_proxy",
}


class AcceptanceError(RuntimeError):
    pass


def require(condition: Any, message: str) -> None:
    if not condition:
        raise AcceptanceError(message)


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def is_loopback_url(url: str, *, browser: bool = False) -> bool:
    parsed = urlsplit(url)
    allowed_schemes = {"http", "https", "ws", "wss"}
    if browser and parsed.scheme in {"about", "blob", "data", "chrome", "chrome-error"}:
        return True
    return (
        parsed.scheme in allowed_schemes
        and parsed.hostname is not None
        and parsed.hostname.lower() in LOOPBACK_HOSTS
        and parsed.username is None
        and parsed.password is None
    )


def require_loopback_url(url: str) -> str:
    require(is_loopback_url(url), f"non-loopback URL rejected: {url!r}")
    return url


def walk(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def find_value(value: Any, keys: Iterable[str]) -> Any:
    wanted = set(keys)
    for item in walk(value):
        if isinstance(item, dict):
            for key in wanted:
                if key in item:
                    return item[key]
    return None


def json_body(response: Any) -> Any:
    try:
        return response.json()
    except Exception as exc:
        text = response.text[:500].replace("\n", " ")
        raise AcceptanceError(
            f"expected JSON from {response.request.method} {response.request.url}: {text}"
        ) from exc


def api_request(
    client: Any,
    method: str,
    url: str,
    *,
    expected: Iterable[int] = (200,),
    json_data: Any = None,
    headers: dict[str, str] | None = None,
    timeout: float = 60.0,
) -> Any:
    require_loopback_url(url)
    response = client.request(
        method,
        url,
        json=json_data,
        headers=headers,
        timeout=timeout,
        follow_redirects=False,
    )
    expected_set = set(expected)
    if response.status_code not in expected_set:
        text = response.text[:1000].replace("\n", " ")
        raise AcceptanceError(
            f"{method} {url} returned {response.status_code}, expected "
            f"{sorted(expected_set)}: {text}"
        )
    return response


def wait_until(
    description: str,
    predicate: Callable[[], Any],
    *,
    timeout: float = 90.0,
    interval: float = 0.25,
) -> Any:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            result = predicate()
            if result:
                return result
        except (AcceptanceError, AssertionError):
            raise
        except Exception as exc:  # Transient HTTP/UI state while polling.
            last_error = exc
        time.sleep(interval)
    suffix = f": {last_error}" if last_error else ""
    raise AcceptanceError(f"timed out waiting for {description}{suffix}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ffprobe_duration(ffprobe: Path, path: Path) -> float:
    completed = subprocess.run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    require(completed.returncode == 0, f"ffprobe failed: {completed.stderr.strip()}")
    try:
        duration = float(completed.stdout.strip())
    except ValueError as exc:
        raise AcceptanceError(
            f"invalid ffprobe duration: {completed.stdout!r}"
        ) from exc
    require(abs(duration - 5.0) <= 0.05, f"expected five-second MP4, got {duration}")
    return duration


def generate_mp4(ffmpeg: Path, output: Path, codec: str) -> None:
    common = [
        str(ffmpeg),
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-f",
        "lavfi",
        "-i",
        "color=c=0x2b4162:s=640x360:r=24:d=5",
        "-an",
        "-map_metadata",
        "-1",
        "-fflags",
        "+bitexact",
        "-threads",
        "1",
    ]
    if codec == "libx264":
        encoding = [
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-x264-params",
            "threads=1:lookahead_threads=1:sliced_threads=0:force-cfr=1",
        ]
    else:
        encoding = [
            "-c:v",
            "mpeg4",
            "-q:v",
            "4",
            "-pix_fmt",
            "yuv420p",
            "-flags:v",
            "+bitexact",
        ]
    completed = subprocess.run(
        common
        + encoding
        + [
            "-metadata",
            "creation_time=1970-01-01T00:00:00Z",
            "-movflags",
            "+faststart",
            "-y",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )
    if completed.returncode != 0:
        output.unlink(missing_ok=True)
        raise AcceptanceError(f"ffmpeg ({codec}) failed: {completed.stderr.strip()}")
    require(output.is_file() and output.stat().st_size > 0, "ffmpeg produced no MP4")


def generate_deterministic_video(
    ffmpeg: Path, ffprobe: Path, first: Path, second: Path
) -> tuple[str, float]:
    codec = "libx264"
    try:
        generate_mp4(ffmpeg, first, codec)
    except AcceptanceError:
        codec = "mpeg4"
        generate_mp4(ffmpeg, first, codec)
    generate_mp4(ffmpeg, second, codec)
    first_hash = sha256_file(first)
    second_hash = sha256_file(second)
    require(first_hash == second_hash, "the two locally generated MP4 files differ")
    return first_hash, ffprobe_duration(ffprobe, first)


class FakeState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.requests: list[dict[str, Any]] = []
        self.unknown_requests: list[dict[str, Any]] = []
        self.completion_count = 0

    def record(self, method: str, path: str, body: Any, *, known: bool) -> None:
        record = {"method": method, "path": path, "body": body}
        with self._lock:
            self.requests.append(record)
            if not known:
                self.unknown_requests.append(record)

    def next_completion(self) -> int:
        with self._lock:
            self.completion_count += 1
            return self.completion_count


def text_content(value: Any) -> str:
    parts: list[str] = []
    for item in walk(value):
        if isinstance(item, str):
            parts.append(item)
    return "\n".join(parts)


def called_tools(messages: Any) -> list[str]:
    result: list[str] = []
    if not isinstance(messages, list):
        return result
    for message in messages:
        if not isinstance(message, dict):
            continue
        calls = message.get("tool_calls")
        if not isinstance(calls, list):
            continue
        for call in calls:
            if not isinstance(call, dict):
                continue
            function = call.get("function")
            if isinstance(function, dict) and isinstance(function.get("name"), str):
                result.append(function["name"])
    return result


def available_tool_name(payload: dict[str, Any], canonical: str) -> str:
    names: list[str] = []
    for tool in payload.get("tools", []):
        if not isinstance(tool, dict):
            continue
        function = tool.get("function")
        if isinstance(function, dict) and isinstance(function.get("name"), str):
            names.append(function["name"])
    if canonical in names:
        return canonical
    for name in names:
        if name.endswith(canonical):
            return name
    raise AcceptanceError(
        f"Host did not expose expected tool {canonical!r}; got {names}"
    )


def tool_arguments(
    payload: dict[str, Any], tool_name: str, values: dict[str, Any]
) -> dict[str, Any]:
    for tool in payload.get("tools", []):
        function = tool.get("function") if isinstance(tool, dict) else None
        if not isinstance(function, dict) or function.get("name") != tool_name:
            continue
        parameters = function.get("parameters")
        properties = (
            parameters.get("properties") if isinstance(parameters, dict) else None
        )
        if isinstance(properties, dict):
            return {key: value for key, value in values.items() if key in properties}
    return values


def fake_completion_answer(
    payload: dict[str, Any],
) -> tuple[str, str | None, dict[str, Any] | None]:
    messages = payload.get("messages", [])
    combined = text_content(messages)
    lower = combined.lower()

    if (
        "## pawapp task continuation\nthe host started this turn because an independent pawapp task changed state."
        in lower
        and "pawapp task event:\n" in lower
    ):
        task_matches = re.findall(r'"task_id"\s*:\s*"([^"]+)"', combined)
        status_matches = re.findall(r'"status"\s*:\s*"([^"]+)"', combined)
        task_id = task_matches[-1] if task_matches else "missing"
        status = status_matches[-1] if status_matches else "unknown"
        return (f"PAWAPP_CONTINUATION task_id={task_id} status={status}", None, None)

    if (
        "you generate short titles for chat sessions." in lower
        and "reply with the title only." in lower
    ):
        return ("Fake Video Acceptance", None, None)

    prior = called_tools(messages)
    if any(name.endswith("delegate") for name in prior):
        return ("Creator accepted the deterministic local video task.", None, None)

    if any(name.endswith("describe_action") for name in prior):
        name = available_tool_name(payload, "delegate")
        values = {
            "app_id": APP_ID,
            "action_id": ACTION_ID,
            "inputs": {
                "brief": "A red paper kite rises slowly above a quiet green field.",
                "name": "Fake Video Acceptance",
                "aspect_ratio": "16:9",
                "resolution": "720P",
                "duration_seconds": 5,
                "language": "en-US",
            },
            "request_id": SESSION_ID,
            "workspace_id": WORKSPACE_ID,
        }
        return ("", name, tool_arguments(payload, name, values))

    if any(name.endswith("list_apps") for name in prior):
        name = available_tool_name(payload, "describe_action")
        values = {
            "app_id": APP_ID,
            "action_id": ACTION_ID,
            "workspace_id": WORKSPACE_ID,
        }
        return ("", name, tool_arguments(payload, name, values))

    if payload.get("tools") and (
        SESSION_ID in combined
        or "red paper kite" in lower
        or "create-video" in lower
        or not prior
    ):
        name = available_tool_name(payload, "list_apps")
        values = {"workspace_id": WORKSPACE_ID}
        return ("", name, tool_arguments(payload, name, values))

    return ("OK", None, None)


def make_fake_handler(state: FakeState) -> type[BaseHTTPRequestHandler]:
    class FakeHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, _format: str, *_args: Any) -> None:
            return

        def _send_json(self, status: int, payload: Any) -> None:
            encoded = compact_json(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(encoded)

        def _read_json(self) -> Any:
            try:
                size = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                size = 0
            require(size <= 4 * 1024 * 1024, "fake server request body exceeded limit")
            raw = self.rfile.read(size) if size else b"{}"
            try:
                return json.loads(raw.decode("utf-8"))
            except Exception:
                return {"_invalid_json": raw.decode("utf-8", errors="replace")[:500]}

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlsplit(self.path)
            path = parsed.path.rstrip("/") or "/"
            if path == "/v1/models":
                state.record("GET", self.path, None, known=True)
                self._send_json(
                    200,
                    {
                        "object": "list",
                        "data": [
                            {
                                "id": "mock-model",
                                "object": "model",
                                "created": 0,
                                "owned_by": "loopback-acceptance",
                            }
                        ],
                    },
                )
                return
            if path == "/v1/models/mock-model":
                state.record("GET", self.path, None, known=True)
                self._send_json(
                    200,
                    {
                        "id": "mock-model",
                        "object": "model",
                        "created": 0,
                        "owned_by": "loopback-acceptance",
                    },
                )
                return
            if path == "/fake-image.png":
                state.record("GET", self.path, None, known=True)
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(TRANSPARENT_PNG)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(TRANSPARENT_PNG)
                return
            if path == "/api/v1/uploads":
                query = parsed.query
                known = "action=getPolicy" in query and "model=" in query
                state.record("GET", self.path, None, known=known)
                if not known:
                    self._send_json(
                        502,
                        {"error": "unexpected upload policy query"},
                    )
                    return
                self._send_json(
                    200,
                    {
                        "data": {
                            "policy": "loopback-only",
                            "signature": "fake-signature",
                            "upload_dir": "fake/",
                            "upload_host": "http://127.0.0.1/unused",
                            "oss_access_key_id": "fake-access-key",
                            "x_oss_object_acl": "private",
                            "x_oss_forbid_overwrite": "true",
                        }
                    },
                )
                return
            if path.startswith("/api/v1/tasks/"):
                state.record("GET", self.path, None, known=True)
                self._send_json(200, {"output": {
                    "task_status": "SUCCEEDED",
                    "results": {"choices": [{"message": {
                        "content": [{"image": f"http://{self.headers.get('Host', '127.0.0.1')}/fake-image.png"}]
                    }}]},
                }})
                return
            state.record("GET", self.path, None, known=False)
            self._send_json(
                502, {"error": "unexpected fake-server request", "path": self.path}
            )

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlsplit(self.path)
            path = parsed.path.rstrip("/") or "/"
            body = self._read_json()
            if path.endswith("/services/aigc/multimodal-generation/generation"):
                state.record("POST", self.path, body, known=True)
                self._send_json(200, {"output": {"task_id": "fake-image-task"}})
                return
            if path != "/v1/chat/completions":
                state.record("POST", self.path, body, known=False)
                self._send_json(
                    502, {"error": "unexpected fake-server request", "path": self.path}
                )
                return

            state.record("POST", self.path, body, known=True)
            if not isinstance(body, dict):
                self._send_json(400, {"error": "expected JSON object"})
                return
            try:
                content, tool_name, arguments = fake_completion_answer(body)
            except AcceptanceError as exc:
                self._send_json(400, {"error": str(exc)})
                return
            ordinal = state.next_completion()
            call_id = f"call_fake_{ordinal:04d}"
            model = str(body.get("model") or "mock-model")

            if not body.get("stream"):
                message: dict[str, Any] = {
                    "role": "assistant",
                    "content": content or None,
                }
                finish_reason = "stop"
                if tool_name is not None:
                    message["tool_calls"] = [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": compact_json(arguments or {}),
                            },
                        }
                    ]
                    finish_reason = "tool_calls"
                self._send_json(
                    200,
                    {
                        "id": f"chatcmpl-fake-{ordinal:04d}",
                        "object": "chat.completion",
                        "created": 0,
                        "model": model,
                        "choices": [
                            {
                                "index": 0,
                                "message": message,
                                "finish_reason": finish_reason,
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 1,
                            "completion_tokens": 1,
                            "total_tokens": 2,
                        },
                    },
                )
                return

            events: list[dict[str, Any]] = []
            delta: dict[str, Any] = {"role": "assistant"}
            finish_reason = "stop"
            if tool_name is not None:
                delta["tool_calls"] = [
                    {
                        "index": 0,
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": compact_json(arguments or {}),
                        },
                    }
                ]
                finish_reason = "tool_calls"
            else:
                delta["content"] = content
            events.append(
                {
                    "id": f"chatcmpl-fake-{ordinal:04d}",
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": model,
                    "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                }
            )
            events.append(
                {
                    "id": f"chatcmpl-fake-{ordinal:04d}",
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": model,
                    "choices": [
                        {"index": 0, "delta": {}, "finish_reason": finish_reason}
                    ],
                }
            )
            if isinstance(body.get("stream_options"), dict) and body[
                "stream_options"
            ].get("include_usage"):
                events.append(
                    {
                        "id": f"chatcmpl-fake-{ordinal:04d}",
                        "object": "chat.completion.chunk",
                        "created": 0,
                        "model": model,
                        "choices": [],
                        "usage": {
                            "prompt_tokens": 1,
                            "completion_tokens": 1,
                            "total_tokens": 2,
                        },
                    }
                )
            encoded = "".join(f"data: {compact_json(event)}\n\n" for event in events)
            encoded += "data: [DONE]\n\n"
            raw = encoded.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(raw)
            self.wfile.flush()

    return FakeHandler


class Resources:
    def __init__(self) -> None:
        self.client: Any = None
        self.browser_context: Any = None
        self.browser: Any = None
        self.playwright: Any = None
        self.host: subprocess.Popen[bytes] | None = None
        self.host_log: Any = None
        self.host_descendants: set[int] = set()
        self.fake_server: ThreadingHTTPServer | None = None
        self.fake_thread: threading.Thread | None = None
        self.fake_state: FakeState | None = None
        self.temp_root: Path | None = None

    @staticmethod
    def _descendants(root_pid: int) -> set[int]:
        try:
            completed = subprocess.run(
                ["/bin/ps", "-axo", "pid=,ppid="],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            parent_map: dict[int, set[int]] = {}
            for line in completed.stdout.splitlines():
                fields = line.split()
                if len(fields) != 2:
                    continue
                pid, parent = int(fields[0]), int(fields[1])
                parent_map.setdefault(parent, set()).add(pid)
            found: set[int] = set()
            pending = [root_pid]
            while pending:
                parent = pending.pop()
                for child in parent_map.get(parent, set()):
                    if child not in found:
                        found.add(child)
                        pending.append(child)
            return found
        except Exception:
            return set()

    def failure_diagnostics(self) -> dict[str, str]:
        if self.host_log is not None:
            try:
                self.host_log.flush()
            except Exception:
                pass
        diagnostics: dict[str, str] = {}
        if self.fake_state is not None:
            diagnostics["fake_requests_tail"] = compact_json([
                {"method": item.get("method"), "path": item.get("path")}
                for item in self.fake_state.requests[-30:]
            ])
            path_counts: dict[str, int] = {}
            for item in self.fake_state.requests:
                key = f"{item.get('method', '?')} {item.get('path', '?')}"
                path_counts[key] = path_counts.get(key, 0) + 1
            diagnostics["fake_request_counts"] = compact_json(path_counts)
            diagnostics["fake_unknown_requests"] = compact_json(self.fake_state.unknown_requests)
        if self.temp_root is None:
            return diagnostics
        for key, path in (
            ("host_log_tail", self.temp_root / "host.log"),
            (
                "acceptance_event_tail",
                self.temp_root / "creator-data" / "acceptance-events.jsonl",
            ),
        ):
            if path.is_file():
                diagnostics[key] = path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )[-6000:]
        return diagnostics

    def cleanup(self) -> None:
        for resource in (self.browser_context, self.browser):
            if resource is not None:
                try:
                    resource.close()
                except Exception:
                    pass
        if self.playwright is not None:
            try:
                self.playwright.stop()
            except Exception:
                pass
        if self.client is not None:
            try:
                self.client.close()
            except Exception:
                pass

        if self.host is not None:
            self.host_descendants |= self._descendants(self.host.pid)
            try:
                os.killpg(self.host.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                self.host.wait(timeout=8)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.host.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    self.host.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
            for pid in sorted(self.host_descendants, reverse=True):
                try:
                    os.kill(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass

        if self.fake_server is not None:
            try:
                self.fake_server.shutdown()
            except Exception:
                pass
            try:
                self.fake_server.server_close()
            except Exception:
                pass
        if self.fake_thread is not None:
            self.fake_thread.join(timeout=5)
        if self.host_log is not None:
            try:
                self.host_log.close()
            except Exception:
                pass
        if self.temp_root is not None:
            shutil.rmtree(self.temp_root, ignore_errors=True)


def find_executable(name: str, fixed: str | None = None) -> Path:
    candidate = fixed if fixed and Path(fixed).is_file() else shutil.which(name)
    require(candidate is not None, f"required local executable not found: {name}")
    path = Path(candidate).resolve()
    require(path.is_file(), f"required executable is not a file: {path}")
    return path


def reserve_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def host_environment(
    repo_root: Path,
    temp_root: Path,
    creator_data: Path,
    video_path: Path,
    event_log: Path,
    ffmpeg: Path,
    ffprobe: Path,
    jq: Path,
) -> dict[str, str]:
    home = temp_root / "home"
    working = temp_root / "working"
    secrets = temp_root / "secrets"
    backups = temp_root / "backups"
    xdg_config = temp_root / "xdg-config"
    xdg_cache = temp_root / "xdg-cache"
    xdg_data = temp_root / "xdg-data"
    tmpdir = temp_root / "tmp"
    for directory in (
        home,
        working,
        secrets,
        backups,
        xdg_config,
        xdg_cache,
        xdg_data,
        tmpdir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    original_path = os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
    path_parts = [
        str(Path(sys.executable).resolve().parent),
        str(ffmpeg.parent),
        str(jq.parent),
        original_path,
        "/usr/bin:/bin:/usr/sbin:/sbin",
    ]
    env = {
        "PATH": ":".join(path_parts),
        "PYTHONPATH": str(repo_root / "src"),
        "PYTHONUNBUFFERED": "1",
        "LANG": "en_US.UTF-8",
        "LC_ALL": "en_US.UTF-8",
        "HOME": str(home),
        "USERPROFILE": str(home),
        "XDG_CONFIG_HOME": str(xdg_config),
        "XDG_CACHE_HOME": str(xdg_cache),
        "XDG_DATA_HOME": str(xdg_data),
        "TMPDIR": str(tmpdir),
        "NO_PROXY": "127.0.0.1,localhost,::1",
        "no_proxy": "127.0.0.1,localhost,::1",
        "QWENPAW_WORKING_DIR": str(working),
        "QWENPAW_SECRET_DIR": str(secrets),
        "QWENPAW_BACKUP_DIR": str(backups),
        "QWENPAW_RUNNING_IN_CONTAINER": "true",
        "QWENPAW_AUTH_ENABLED": "false",
        "CREATOR_ACCEPTANCE_FAKE_RUNTIME": "1",
        "CREATOR_ACCEPTANCE_VIDEO_PATH": str(video_path),
        "CREATOR_ACCEPTANCE_EVENT_LOG": str(event_log),
        "CREATOR_DATA_ROOT": str(creator_data),
        "CREATOR_MODEL_CONFIG_PATH": str(creator_data / "model-config.json"),
        "CREATOR_FFMPEG_PATH": str(ffmpeg),
        "CREATOR_FFPROBE_PATH": str(ffprobe),
        "CREATOR_JQ_PATH": str(jq),
        "CREATOR_AUTO_INSTALL_BINARIES": "0",
    }
    for name in CREDENTIAL_ENV_NAMES | PROXY_ENV_NAMES:
        env[name] = ""
    return env


def sandbox_profile(host_port: int, fake_port: int) -> str:
    return "\n".join(
        [
            "(version 1)",
            "(allow default)",
            "(deny network*)",
            f'(allow network-bind (local ip "localhost:{host_port}"))',
            f'(allow network-inbound (local ip "localhost:{host_port}"))',
            f'(allow network-outbound (remote ip "localhost:{host_port}"))',
            f'(allow network-outbound (remote ip "localhost:{fake_port}"))',
            "",
        ]
    )


def acceptance_event_names(path: Path) -> list[str]:
    if not path.is_file():
        return []
    names: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AcceptanceError(
                f"invalid acceptance event JSON: {line[:200]}"
            ) from exc
        matches = [
            item
            for item in walk(payload)
            if isinstance(item, str) and item in EXPECTED_EVENTS
        ]
        require(
            matches, f"acceptance event record has no recognized event: {line[:200]}"
        )
        names.append(matches[0])
    return names


def model_config_root(payload: Any) -> dict[str, Any]:
    require(isinstance(payload, dict), "Creator model config is not an object")
    for key in ("config", "data"):
        nested = payload.get(key)
        if isinstance(nested, dict) and any(
            re.sub(r"[^a-z]", "", name.lower())
            in {"llm", "creatorllm", "image", "imagegen", "video", "videogen"}
            for name in nested
        ):
            return json.loads(json.dumps(nested))
    return json.loads(json.dumps(payload))


def find_model_section(config: dict[str, Any], kind: str) -> dict[str, Any]:
    aliases = {
        "llm": {"llm", "creatorllm", "text", "chat"},
        "image": {"image", "imagegen", "imagegeneration", "storyboardimage"},
        "video": {"video", "videogen", "videogeneration", "shotvideo"},
    }[kind]
    for key, value in config.items():
        normalized = re.sub(r"[^a-z]", "", key.lower())
        if normalized in aliases and isinstance(value, dict):
            return value
    raise AcceptanceError(f"Creator model config has no {kind} section")


def set_model_value(
    section: dict[str, Any], aliases: Iterable[str], default: str, value: Any
) -> None:
    for key in aliases:
        if key in section:
            section[key] = value
            return
    section[default] = value


def configure_creator_llm(
    client: Any,
    base_url: str,
    provider_url: str,
) -> None:
    require_loopback_url(provider_url)
    response = api_request(
        client,
        "GET",
        f"{base_url}/api/{APP_ID}/models/config",
    )
    config = model_config_root(json_body(response))
    llm = find_model_section(config, "llm")
    image = find_model_section(config, "image")
    video = find_model_section(config, "video")
    grounding = config.get("grounding")
    require(
        isinstance(grounding, dict), "Creator model config has no grounding section"
    )

    set_model_value(llm, ("enabled", "is_enabled"), "enabled", True)
    set_model_value(
        llm,
        ("model", "model_name", "model_id"),
        "model_name",
        "mock-model",
    )
    set_model_value(llm, ("api_key", "apiKey"), "api_key", "fake-local-key")
    set_model_value(
        llm,
        ("base_url", "baseUrl", "endpoint"),
        "base_url",
        provider_url,
    )
    set_model_value(grounding, ("enabled", "is_enabled"), "enabled", False)
    for optional in (image, video):
        set_model_value(optional, ("enabled", "is_enabled"), "enabled", False)

    api_request(
        client,
        "POST",
        f"{base_url}/api/{APP_ID}/models/config",
        expected=(200, 201),
        json_data=config,
        headers={"Idempotency-Key": "fake-acceptance-initial-model-config"},
    )


def collect_nested_json(value: Any, *, depth: int = 0) -> Iterable[Any]:
    if depth > 12:
        return
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from collect_nested_json(child, depth=depth + 1)
    elif isinstance(value, list):
        for child in value:
            yield from collect_nested_json(child, depth=depth + 1)
    elif isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith(("{", "[")):
            try:
                decoded = json.loads(stripped)
            except json.JSONDecodeError:
                return
            yield from collect_nested_json(decoded, depth=depth + 1)


def task_ids_from_sse(events: list[Any]) -> set[str]:
    found: set[str] = set()
    for event in events:
        for item in collect_nested_json(event):
            if not isinstance(item, dict):
                continue
            if item.get("kind") == "pawapp_task" and isinstance(item.get("task"), dict):
                task_id = item["task"].get("id") or item["task"].get("task_id")
                if isinstance(task_id, str):
                    found.add(task_id)
            if item.get("app_id") == APP_ID and item.get("action_id") == ACTION_ID:
                nested = item.get("task")
                if isinstance(nested, dict):
                    task_id = nested.get("id") or nested.get("task_id")
                    if isinstance(task_id, str):
                        found.add(task_id)
    return found


def drive_console_chat(client: Any, base_url: str) -> str:
    url = require_loopback_url(f"{base_url}/api/console/chat")
    payload = {
        "channel": "console",
        "user_id": "default",
        "session_id": SESSION_ID,
        "agent_id": "default",
        "input": [
            {
                "role": "user",
                "type": "message",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Use the public qwenpaw-creator/create-video action for the acceptance request "
                            f"{SESSION_ID}. Create a five-second video of a red paper kite rising slowly "
                            "above a quiet green field."
                        ),
                    }
                ],
            }
        ],
    }
    events: list[Any] = []
    deadline = time.monotonic() + 120.0
    with client.stream(
        "POST",
        url,
        json=payload,
        timeout=15.0,
        follow_redirects=False,
    ) as response:
        require(
            response.status_code == 200, f"Console chat returned {response.status_code}"
        )
        for line in response.iter_lines():
            if time.monotonic() >= deadline:
                raise AcceptanceError(
                    "timed out waiting for create-video task ID in Console SSE"
                )
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                events.append(json.loads(data))
            except json.JSONDecodeError as exc:
                raise AcceptanceError(
                    f"invalid Console SSE JSON: {data[:300]}"
                ) from exc
            task_ids = task_ids_from_sse(events)
            if len(task_ids) > 1:
                raise AcceptanceError(
                    "expected one task ID in actual Console SSE, got "
                    f"{sorted(task_ids)}"
                )
            if len(task_ids) == 1:
                return next(iter(task_ids))
    task_ids = task_ids_from_sse(events)
    require(
        len(task_ids) == 1,
        f"expected one task ID in actual Console SSE, got {sorted(task_ids)}",
    )
    return next(iter(task_ids))


def resolve_chat_uuid(client: Any, base_url: str) -> str:
    headers = {"X-Agent-Id": WORKSPACE_ID}
    response = api_request(
        client,
        "GET",
        f"{base_url}/api/chats?user_id=default&channel=console",
        headers=headers,
    )
    payload = json_body(response)
    matches: dict[str, dict[str, Any]] = {}
    for item in walk(payload):
        if (
            isinstance(item, dict)
            and item.get("session_id") == SESSION_ID
            and isinstance(item.get("id"), str)
        ):
            matches[item["id"]] = item
    require(
        len(matches) == 1,
        f"expected one ChatSpec for {SESSION_ID}, got {sorted(matches)}",
    )
    chat_id = next(iter(matches))
    try:
        uuid.UUID(chat_id)
    except ValueError as exc:
        raise AcceptanceError(f"ChatSpec.id is not a UUID: {chat_id}") from exc

    filtered_response = api_request(
        client,
        "GET",
        f"{base_url}/api/chats?archived=false&include_app_owned=false",
        headers=headers,
    )
    filtered_payload = json_body(filtered_response)
    filtered_ids = {
        item["id"]
        for item in walk(filtered_payload)
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    require(
        chat_id in filtered_ids,
        "originating chat is absent from the Main Chat catalog: "
        f"chat={compact_json(matches[chat_id])}",
    )
    return chat_id


def visible_locator(root: Any, name: str, *, timeout: float = 90.0) -> Any:
    def locate() -> Any:
        candidates = [
            root.get_by_role("button", name=re.compile(rf"^{re.escape(name)}$", re.I)),
            root.get_by_role("radio", name=re.compile(rf"^{re.escape(name)}$", re.I)),
            root.get_by_text(name, exact=True),
        ]
        for candidate in candidates:
            count = candidate.count()
            for index in range(count):
                current = candidate.nth(index)
                if current.is_visible():
                    return current
        return None

    try:
        return wait_until(
            f"visible production control {name!r}",
            locate,
            timeout=timeout,
            interval=0.25,
        )
    except AcceptanceError as exc:
        try:
            body = root.locator("body").inner_text()[-3000:]
        except Exception:
            body = "<unavailable>"
        raise AcceptanceError(f"{exc}; body={body!r}") from exc


def wait_task_card(page: Any, task_id: str, *, timeout: float = 90.0) -> None:
    def present() -> bool:
        locator = page.get_by_text(task_id, exact=False)
        return any(locator.nth(index).is_visible() for index in range(locator.count()))

    try:
        wait_until(f"task card {task_id}", present, timeout=timeout)
    except AcceptanceError as exc:
        try:
            body = page.locator("body").inner_text()[-3000:]
        except Exception:
            body = "<unavailable>"
        try:
            selected_agent = page.evaluate(
                """() => {
                    const raw = sessionStorage.getItem('qwenpaw-agent-storage');
                    return raw ? JSON.parse(raw)?.state?.selectedAgent : null;
                }"""
            )
        except Exception:
            selected_agent = "<unavailable>"
        raise AcceptanceError(
            f"{exc}; url={page.url}; selected_agent={selected_agent!r}; body={body!r}"
        ) from exc


def wait_creator_frame(context: Any, *, timeout: float = 60.0) -> tuple[Any, Any]:
    def locate() -> Any:
        for page in context.pages:
            frames = page.locator('iframe[title="QwenPaw Creator"]')
            for index in range(frames.count()):
                element = frames.nth(index)
                if not element.is_visible():
                    continue
                frame = element.content_frame
                if frame is not None:
                    return page, frame
        return None

    return wait_until("QwenPaw Creator iframe", locate, timeout=timeout)


def first_visible(locators: Iterable[Any]) -> Any:
    for locator in locators:
        count = locator.count()
        for index in range(count):
            current = locator.nth(index)
            if current.is_visible():
                return current
    return None


def configure_model_in_creator(
    context: Any,
    *,
    card_name: str,
    model_name: str,
    provider_base_url: str,
    setup_request_id: str,
) -> tuple[Any, Any]:
    owner, frame = wait_creator_frame(context)
    card_pattern = re.compile(card_name, re.I)

    def find_card() -> Any:
        cards = frame.locator(".glass-card").filter(has_text=card_pattern)
        for index in range(cards.count()):
            card = cards.nth(index)
            if card.is_visible():
                return card
        return None

    card = wait_until(f"{card_name} model card", find_card, timeout=60.0)
    reuse = first_visible(
        [
            card.get_by_role("checkbox", name=re.compile("Reuse LLM API Key", re.I)),
            card.get_by_label(re.compile("Reuse LLM API Key", re.I)),
        ]
    )
    if reuse is not None and reuse.is_checked():
        reuse.uncheck(force=True)

    fields = {
        "Model Name": model_name,
        "API Key": "fake-local-key",
        "Base URL": provider_base_url,
    }
    for label, value in fields.items():
        labels = card.locator("label.field-label").filter(
            has_text=re.compile(rf"^\s*{re.escape(label)}\s*$", re.I)
        )
        field = None
        for index in range(labels.count()):
            container = labels.nth(index).locator("xpath=..")
            field = first_visible([container.locator("input")])
            if field is not None:
                break
        require(field is not None, f"missing {label!r} field in {card_name} card")
        field.fill(value)

    enabled = first_visible(
        [
            card.get_by_role(
                "checkbox",
                name=re.compile(rf"^{re.escape(card_name)}$", re.I),
            ),
            card.locator('label.desktop-toggle input[type="checkbox"]'),
        ]
    )
    # The Creator switch uses a visually hidden native input. Playwright's
    # visibility filter therefore excludes the input even though its label is
    # the visible control. Keep the semantic lookup above, then fall back to
    # the hidden input when its visible label is present.
    if enabled is None:
        toggle_label = first_visible([card.locator("label.desktop-toggle")])
        if toggle_label is not None:
            enabled = toggle_label.locator('input[type="checkbox"]')
    hidden_toggle = enabled is not None and not enabled.is_visible() if enabled is not None else False
    if enabled is None:
        try:
            card_debug = card.inner_text()[-2000:]
            card_html = card.evaluate("element => element.outerHTML")
            checkbox_debug = frame.locator('input[type="checkbox"]').evaluate_all(
                "els => els.map(e => ({aria:e.getAttribute('aria-label'), name:e.getAttribute('name'), checked:e.checked, html:e.outerHTML})).slice(0, 30)"
            )
            toggle_count = frame.locator("label.desktop-toggle").count()
        except Exception as exc:
            card_debug = f"<unavailable: {exc}>"
            card_html = "<unavailable>"
            checkbox_debug = f"<unavailable: {exc}>"
            toggle_count = "<unavailable>"
        raise AcceptanceError(
            f"missing enable toggle for {card_name}; "
            f"card_toggle_count={card.locator('label.desktop-toggle').count()!r}; "
            f"card_checkbox_count={card.locator('input[type=checkbox]').count()!r}; "
            f"frame_toggle_count={toggle_count!r}; frame_checkboxes={checkbox_debug!r}; "
            f"card_text={card_debug!r}; card_html_head={card_html[:1800]!r}"
        )
    if not enabled.is_checked():
        with owner.expect_response(
            lambda response: "/api/qwenpaw-creator/models/test" in response.url,
            timeout=60_000,
        ) as pending_test:
            if hidden_toggle:
                enabled.evaluate("element => element.click()")
            else:
                enabled.check(force=True)
        test_response = pending_test.value
        require(
            test_response.ok and test_response.json().get("ok") is True,
            f"local connectivity check failed for {card_name}",
        )
        owner.evaluate(
            "() => new Promise(resolve => requestAnimationFrame(() => "
            "requestAnimationFrame(resolve)))"
        )
    require(
        enabled.is_checked(),
        f"local connectivity check did not enable {card_name}",
    )

    save = visible_locator(frame, "Save Config", timeout=45.0)
    wait_until(
        "enabled Save Config",
        lambda: save if save.is_enabled() else None,
        timeout=45.0,
    )
    # The acceptance provider is intentionally loopback-only.  The model
    # cards may carry a persisted Host-provider binding from the default
    # DashScope preset; that binding would correctly materialize the real
    # DashScope endpoint and bypass the fake server.  Preserve the UI setup
    # flow while removing only that binding from this test submission.
    config_section = "image" if card_name == "Image Gen" else "video"

    def route_local_config(route: Any) -> None:
        request = route.request
        try:
            body = json.loads(request.post_data or "{}")
            # ModelConfigData may be wrapped by the frontend under a config
            # object, so walk the payload rather than assuming its root.
            def scrub_binding(value: Any) -> None:
                if isinstance(value, dict):
                    for binding_key in ("host_provider_id", "hostProviderId"):
                        if binding_key in value:
                            value[binding_key] = ""
                    if "model_name" in value and "base_url" in value:
                        value["base_url"] = provider_base_url
                    for child in value.values():
                        scrub_binding(child)
                elif isinstance(value, list):
                    for child in value:
                        scrub_binding(child)

            scrub_binding(body)
            route.continue_(post_data=compact_json(body))
        except Exception:
            route.continue_()

    owner.route(
        "**/api/qwenpaw-creator/models/config",
        route_local_config,
    )
    with owner.expect_request(
        lambda request: request.method == "POST"
        and "/api/qwenpaw-creator/models/config" in request.url,
        timeout=60_000,
    ) as pending_request:
        save.evaluate(
            "element => (element.closest('button') || element).click()"
        )
    config_request = pending_request.value
    owner.unroute(
        "**/api/qwenpaw-creator/models/config",
        route_local_config,
    )
    require(
        config_request.headers.get("x-pawapp-setup-request") == setup_request_id,
        "Creator model save omitted the task-linked setup request",
    )
    config_response = config_request.response()
    require(
        config_response is not None and config_response.ok,
        "Creator model save did not complete the task-linked setup request",
    )

    def modal_closed() -> bool:
        modals = frame.locator(".model-config-modal")
        return not any(
            modals.nth(index).is_visible() for index in range(modals.count())
        )

    wait_until(
        f"saved {card_name} configuration",
        modal_closed,
        timeout=120.0,
    )
    return owner, frame


def task_headers() -> dict[str, str]:
    return {
        "X-Agent-Id": "default",
        "X-User-Id": "default",
        "X-Channel": "console",
    }


def task_payload(client: Any, base_url: str, task_id: str) -> Any:
    response = api_request(
        client,
        "GET",
        f"{base_url}/api/pawapps/{APP_ID}/workspaces/{WORKSPACE_ID}/tasks/{quote(task_id, safe='')}",
        headers=task_headers(),
    )
    return json_body(response)


def assert_task_identity(
    client: Any, base_url: str, task_id: str, observations: list[str], phase: str
) -> Any:
    payload = task_payload(client, base_url, task_id)
    encoded = compact_json(payload)
    require(task_id in encoded, f"task response lost ID during {phase}")
    explicit_ids: set[str] = set()
    for item in walk(payload):
        if not isinstance(item, dict):
            continue
        for key in ("task_id", "id"):
            value = item.get(key)
            if isinstance(value, str) and value == task_id:
                explicit_ids.add(value)
    require(explicit_ids == {task_id}, f"task identity mismatch during {phase}")
    observations.append(task_id)
    return payload


def task_status(payload: Any) -> str:
    candidate = find_value(payload, ("status", "state"))
    return str(candidate).lower() if candidate is not None else ""


def artifact_refs(payload: Any) -> set[tuple[str, str]]:
    refs: set[tuple[str, str]] = set()
    for item in walk(payload):
        if not isinstance(item, dict):
            continue
        artifact_id = item.get("artifact_id")
        version = item.get("version")
        if version is None:
            version = item.get("artifact_version")
        if isinstance(artifact_id, str) and version is not None:
            refs.add((artifact_id, str(version)))
    return refs


def artifact_digests(payload: Any) -> dict[tuple[str, str], str]:
    digests: dict[tuple[str, str], str] = {}
    for item in walk(payload):
        if not isinstance(item, dict):
            continue
        artifact_id = item.get("artifact_id")
        version = item.get("version")
        digest = item.get("digest")
        if not (
            isinstance(artifact_id, str)
            and version is not None
            and isinstance(digest, str)
            and re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
        ):
            continue
        key = (artifact_id, str(version))
        existing = digests.setdefault(key, digest)
        require(existing == digest, f"conflicting digests for artifact {key}")
    return digests


def persisted_chat_text(
    client: Any,
    base_url: str,
    chat_id: str,
) -> str:
    response = api_request(
        client,
        "GET",
        f"{base_url}/api/chats/{quote(chat_id, safe='')}?include_app_owned=false",
        headers={"X-Agent-Id": WORKSPACE_ID},
    )
    return text_content(json_body(response))


def project_id_from_task(payload: Any) -> str | None:
    value = find_value(payload, ("project_id",))
    return value if isinstance(value, str) and value else None


def return_to_chat(main_page: Any, context: Any, chat_url: str) -> None:
    for page in list(context.pages):
        if page is not main_page:
            try:
                page.close()
            except Exception:
                pass
    main_page.bring_to_front()
    main_page.goto(
        require_loopback_url(chat_url), wait_until="domcontentloaded", timeout=60_000
    )


def browser_acceptance(
    resources: Resources,
    client: Any,
    base_url: str,
    fake_base_url: str,
    chat_id: str,
    task_id: str,
    event_log: Path,
    download_dir: Path,
    observations: list[str],
) -> tuple[Path, Any]:
    from playwright.sync_api import sync_playwright

    resources.playwright = sync_playwright().start()
    resources.browser = resources.playwright.chromium.launch(
        headless=True,
        args=[
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-default-apps",
            "--disable-domain-reliability",
            "--disable-features=MediaRouter,OptimizationHints,AutofillServerCommunication",
            "--disable-sync",
            "--metrics-recording-only",
            "--no-first-run",
            "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost, EXCLUDE [::1]",
        ],
    )
    resources.browser_context = resources.browser.new_context(
        accept_downloads=True,
        locale="en-US",
        service_workers="block",
    )
    context = resources.browser_context
    context.add_init_script(
        "try { localStorage.setItem('language', 'en'); } catch (_) {}"
    )
    blocked_requests: list[str] = []

    def route_request(route: Any, request: Any) -> None:
        if is_loopback_url(request.url, browser=True):
            route.continue_()
        elif request.url == PYPI_STUB_URL:
            route.fulfill(
                status=200,
                content_type="application/json",
                body='{"info":{"version":"0.0.0"}}',
            )
        elif request.url in DECORATIVE_IMAGE_STUB_URLS:
            route.fulfill(
                status=200,
                content_type="image/png",
                body=TRANSPARENT_PNG,
            )
        else:
            blocked_requests.append(request.url)
            route.abort("blockedbyclient")

    context.route("**/*", route_request)
    downloads: list[Any] = []
    page = context.new_page()
    page.on("download", lambda download: downloads.append(download))
    chat_url = f"{base_url}/chat/{chat_id}"
    page.goto(
        require_loopback_url(chat_url), wait_until="domcontentloaded", timeout=60_000
    )
    wait_task_card(page, task_id)
    assert_task_identity(
        client, base_url, task_id, observations, "initial Console render"
    )

    require(
        "image.generate" not in acceptance_event_names(event_log),
        "image generated before image setup",
    )
    latest_image_setup_task: Any = None

    def image_setup_ready() -> Any:
        nonlocal latest_image_setup_task
        latest_image_setup_task = task_payload(client, base_url, task_id)
        if task_status(latest_image_setup_task) != "waiting_for_setup":
            return None
        if not isinstance(
            find_value(latest_image_setup_task, ("setup_request_id",)), str
        ):
            return None
        return latest_image_setup_task

    try:
        image_setup_task = wait_until(
            "task waiting for image setup",
            image_setup_ready,
            timeout=30.0,
            interval=0.5,
        )
    except AcceptanceError as exc:
        raise AcceptanceError(
            f"{exc}; task={compact_json(latest_image_setup_task)}"
        ) from exc
    require(
        project_id_from_task(image_setup_task) is not None,
        "image setup task has no Creator project reference",
    )
    image_setup_request_id = find_value(
        image_setup_task,
        ("setup_request_id",),
    )
    require(
        isinstance(image_setup_request_id, str),
        "image setup task has no setup request ID",
    )
    visible_locator(page, "Complete setup").click()
    configure_model_in_creator(
        context,
        card_name="Image Gen",
        model_name="wan2.2-t2i-flash",
        provider_base_url=f"{fake_base_url}/api/v1",
        setup_request_id=image_setup_request_id,
    )
    return_to_chat(page, context, chat_url)
    wait_task_card(page, task_id)
    assert_task_identity(client, base_url, task_id, observations, "image setup")

    approve = visible_locator(page, "Approve once", timeout=120.0)
    image_approval_task = task_payload(client, base_url, task_id)
    image_input_request = find_value(image_approval_task, ("input_request",))
    require(
        isinstance(image_input_request, dict)
        and isinstance(image_input_request.get("request_id"), str),
        "image approval task has no input request ID",
    )
    image_approval_request_id = image_input_request["request_id"]
    require(
        "image.generate" not in acceptance_event_names(event_log),
        "image generated before image approval",
    )
    approve.click()
    visible_locator(page, "Submit answer").click()

    def image_generation_outcome() -> tuple[str, Any] | None:
        if acceptance_event_names(event_log).count("image.generate") == 1:
            return "generated", None
        current_task = task_payload(client, base_url, task_id)
        current_input_request = find_value(current_task, ("input_request",))
        current_request_id = (
            current_input_request.get("request_id")
            if isinstance(current_input_request, dict)
            else None
        )
        if current_request_id not in (None, image_approval_request_id):
            return "reapproval", current_request_id
        return None

    image_outcome, current_request_id = wait_until(
        "image generation or replacement approval",
        image_generation_outcome,
        timeout=120.0,
    )
    require(
        image_outcome == "generated",
        "image approval was replaced before provider dispatch: "
        f"approved={image_approval_request_id} current={current_request_id}",
    )
    assert_task_identity(client, base_url, task_id, observations, "image approval")

    video_setup_task = wait_until(
        "task waiting for video setup",
        lambda: (
            payload
            if task_status(payload := task_payload(client, base_url, task_id))
            == "waiting_for_setup"
            and isinstance(
                find_value(payload, ("setup_request_id",)),
                str,
            )
            and find_value(payload, ("setup_request_id",))
            != image_setup_request_id
            else None
        ),
        timeout=120.0,
        interval=0.5,
    )
    video_setup_request_id = find_value(
        video_setup_task,
        ("setup_request_id",),
    )
    require(
        isinstance(video_setup_request_id, str),
        "video setup task has no setup request ID",
    )
    visible_locator(page, "Complete setup", timeout=120.0).click()
    require(
        "video.submit" not in acceptance_event_names(event_log),
        "video submitted before video setup",
    )
    configure_model_in_creator(
        context,
        card_name="Video Gen",
        model_name="wan3.0-video-prime",
        provider_base_url=f"{fake_base_url}/api/v1",
        setup_request_id=video_setup_request_id,
    )
    return_to_chat(page, context, chat_url)
    wait_task_card(page, task_id)
    assert_task_identity(client, base_url, task_id, observations, "video setup")

    visible_locator(page, "Approve once", timeout=120.0)
    require(
        "video.submit" not in acceptance_event_names(event_log),
        "video submitted before video approval",
    )
    before_handoff = assert_task_identity(
        client, base_url, task_id, observations, "pre-handoff approval"
    )
    video_input_request = find_value(before_handoff, ("input_request",))
    require(
        isinstance(video_input_request, dict)
        and isinstance(video_input_request.get("request_id"), str),
        "video approval task has no input request ID",
    )
    video_approval_request_id = video_input_request["request_id"]
    expected_project_id = project_id_from_task(before_handoff)
    visible_locator(page, "Open App").click()
    _owner, frame = wait_creator_frame(context, timeout=60.0)

    def project_route() -> str | None:
        url = frame.locator("html").evaluate("() => window.location.href")
        match = re.search(r"#/project/([^/?#]+)", url)
        return match.group(1) if match else None

    opened_project_id = wait_until(
        "Creator project handoff route", project_route, timeout=60.0
    )
    if expected_project_id is not None:
        require(
            opened_project_id == expected_project_id,
            "Open App routed to a different project",
        )
    assert_task_identity(client, base_url, task_id, observations, "Creator handoff")

    return_to_chat(page, context, chat_url)
    page.reload(wait_until="domcontentloaded", timeout=60_000)
    wait_task_card(page, task_id)
    approve = visible_locator(page, "Approve once", timeout=120.0)
    require(
        "video.submit" not in acceptance_event_names(event_log),
        "video submitted across approval reload",
    )
    assert_task_identity(client, base_url, task_id, observations, "approval reload")
    approve.click()
    visible_locator(page, "Submit answer").click()

    def video_generation_outcome() -> tuple[str, Any] | None:
        if acceptance_event_names(event_log).count("video.submit") == 1:
            return "generated", None
        current_task = task_payload(client, base_url, task_id)
        current_input_request = find_value(current_task, ("input_request",))
        current_request_id = (
            current_input_request.get("request_id")
            if isinstance(current_input_request, dict)
            else None
        )
        if current_request_id not in (None, video_approval_request_id):
            return "reapproval", current_request_id
        if task_status(current_task) in TERMINAL_STATUSES:
            return "terminal", current_task
        return None

    video_outcome, video_detail = wait_until(
        "video submission or changed task state",
        video_generation_outcome,
        timeout=120.0,
        interval=0.5,
    )
    require(
        video_outcome == "generated",
        "video approval did not reach provider dispatch: "
        f"approved={video_approval_request_id} outcome={video_outcome} "
        f"detail={compact_json(video_detail)}",
    )

    latest_final_task: Any = None

    def terminal_task() -> Any:
        nonlocal latest_final_task
        latest_final_task = task_payload(client, base_url, task_id)
        if task_status(latest_final_task) in TERMINAL_STATUSES:
            return latest_final_task
        return None

    try:
        final_task = wait_until(
            "terminal Creator task",
            terminal_task,
            timeout=180.0,
            interval=0.5,
        )
    except AcceptanceError as exc:
        raise AcceptanceError(
            f"{exc}; task={compact_json(latest_final_task)}"
        ) from exc
    require(
        task_status(final_task) in SUCCESS_STATUSES,
        f"Creator task terminated without success: {compact_json(final_task)}",
    )
    observations.append(task_id)
    continuation_marker = f"PAWAPP_CONTINUATION task_id={task_id}"
    wait_until(
        "persisted PawApp continuation in originating chat",
        lambda: continuation_marker in persisted_chat_text(client, base_url, chat_id),
        timeout=120.0,
        interval=0.5,
    )
    page.reload(wait_until="domcontentloaded", timeout=60_000)
    wait_until(
        "terminal PawApp continuation after chat reload",
        lambda: continuation_marker in page.locator("body").inner_text(),
        timeout=120.0,
        interval=0.5,
    )

    refs = artifact_refs(final_task)
    require(
        len(refs) == 1, f"expected exactly one published artifact, got {sorted(refs)}"
    )
    download_button = visible_locator(page, "Download", timeout=120.0)
    with page.expect_download(timeout=60_000) as download_info:
        download_button.click()
    download = download_info.value
    wait_until(
        "exactly one browser download", lambda: len(downloads) == 1, timeout=10.0
    )
    require(
        download.failure() is None, f"browser download failed: {download.failure()}"
    )
    download_path = download_dir / "creator-acceptance-download.mp4"
    download.save_as(str(download_path))
    require(
        download_path.is_file() and download_path.stat().st_size > 0,
        "browser download is empty",
    )
    require(
        not blocked_requests,
        f"browser attempted non-loopback requests: {blocked_requests}",
    )
    return download_path, final_task


def run_acceptance(resources: Resources) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[5]
    plugin_root = Path(__file__).resolve().parents[2]
    require(
        (repo_root / "src" / "qwenpaw").is_dir(),
        f"invalid repository root: {repo_root}",
    )
    require(
        (plugin_root / "plugin.json").is_file(), "Creator plugin manifest is missing"
    )
    require(
        (plugin_root / "ui" / "dist" / "index.js").is_file(),
        "compiled Creator UI is missing",
    )

    ffmpeg = find_executable("ffmpeg")
    ffprobe = find_executable("ffprobe")
    jq = find_executable("jq")
    sandbox_exec = find_executable("sandbox-exec", "/usr/bin/sandbox-exec")

    resources.temp_root = Path(
        tempfile.mkdtemp(prefix="qwenpaw-fake-video-acceptance-")
    )
    resources.temp_root.chmod(0o700)
    creator_data = resources.temp_root / "creator-data"
    download_dir = resources.temp_root / "downloads"
    creator_data.mkdir(mode=0o700)
    download_dir.mkdir(mode=0o700)
    source_video = creator_data / "deterministic-five-seconds.mp4"
    comparison_video = creator_data / "deterministic-five-seconds-copy.mp4"
    event_log = creator_data / "acceptance-events.jsonl"
    event_log.touch(mode=0o600)
    source_hash, source_duration = generate_deterministic_video(
        ffmpeg, ffprobe, source_video, comparison_video
    )

    data_root_resolved = creator_data.resolve()
    for controlled_path in (source_video, comparison_video, event_log):
        require(
            controlled_path.resolve().is_relative_to(data_root_resolved),
            "Creator fake path escaped data root",
        )
        require(
            controlled_path.is_file(),
            f"Creator fake path is not a regular file: {controlled_path}",
        )

    fake_state = FakeState()
    resources.fake_state = fake_state
    resources.fake_server = ThreadingHTTPServer(
        ("127.0.0.1", 0), make_fake_handler(fake_state)
    )
    resources.fake_server.daemon_threads = True
    fake_port = int(resources.fake_server.server_address[1])
    fake_base_url = require_loopback_url(f"http://127.0.0.1:{fake_port}")
    resources.fake_thread = threading.Thread(
        target=resources.fake_server.serve_forever,
        name="creator-fake-provider",
        daemon=True,
    )
    resources.fake_thread.start()

    host_port = reserve_loopback_port()
    base_url = require_loopback_url(f"http://127.0.0.1:{host_port}")
    profile_path = resources.temp_root / "host-loopback.sb"
    profile_path.write_text(sandbox_profile(host_port, fake_port), encoding="utf-8")
    environment = host_environment(
        repo_root,
        resources.temp_root,
        creator_data,
        source_video,
        event_log,
        ffmpeg,
        ffprobe,
        jq,
    )
    host_log_path = resources.temp_root / "host.log"
    resources.host_log = host_log_path.open("wb")
    resources.host = subprocess.Popen(
        [
            str(sandbox_exec),
            "-f",
            str(profile_path),
            sys.executable,
            "-m",
            "qwenpaw",
            "app",
            "--host",
            "127.0.0.1",
            "--port",
            str(host_port),
            "--log-level",
            "info",
        ],
        cwd=str(repo_root),
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=resources.host_log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    import httpx

    resources.client = httpx.Client(
        trust_env=False,
        headers={"Accept": "application/json"},
        timeout=httpx.Timeout(60.0),
    )
    client = resources.client

    def healthy() -> bool:
        require(resources.host is not None, "Host process was not started")
        if resources.host.poll() is not None:
            resources.host_log.flush()
            tail = host_log_path.read_text(encoding="utf-8", errors="replace")[-3000:]
            raise AcceptanceError(f"Host exited before readiness: {tail}")
        try:
            response = api_request(
                client, "GET", f"{base_url}/api/healthz", timeout=2.0
            )
            return response.status_code == 200
        except Exception:
            return False

    wait_until("real Host readiness", healthy, timeout=90.0, interval=0.2)

    provider_response = api_request(
        client,
        "POST",
        f"{base_url}/api/models/custom-providers",
        expected=(200, 201),
        json_data={
            "id": "acceptance-loopback-llm",
            "name": "Acceptance Loopback LLM",
            "default_base_url": f"{fake_base_url}/v1",
            "chat_model": "OpenAIChatModel",
            "models": [{"id": "mock-model", "name": "Mock Model"}],
        },
    )
    provider_payload = json_body(provider_response)
    provider_id = find_value(provider_payload, ("id", "provider_id"))
    if not isinstance(provider_id, str):
        provider_id = "acceptance-loopback-llm"
    api_request(
        client,
        "PUT",
        f"{base_url}/api/models/{quote(provider_id, safe='')}/config",
        json_data={
            "api_key": "fake-local-key",
            "base_url": f"{fake_base_url}/v1",
            "auto_discover": False,
        },
    )
    api_request(
        client,
        "PUT",
        f"{base_url}/api/models/active",
        json_data={
            "provider_id": provider_id,
            "model": "mock-model",
            "scope": "global",
        },
    )

    install_response = api_request(
        client,
        "POST",
        f"{base_url}/api/plugins/install",
        expected=(200, 201),
        json_data={"source": str(plugin_root), "force": False},
        timeout=180.0,
    )
    install_payload = json_body(install_response)
    loaded = find_value(install_payload, ("loaded",))
    activation_required = find_value(install_payload, ("activation_required",))
    require(loaded is False, f"Creator installation was not inert: loaded={loaded!r}")
    require(
        activation_required is True,
        "Creator installation did not require explicit activation",
    )
    require(
        acceptance_event_names(event_log) == [],
        "Creator runtime started during inert installation",
    )

    status_payload = json_body(
        api_request(client, "GET", f"{base_url}/api/plugins/{APP_ID}/status")
    )
    pre_active = find_value(status_payload, ("active", "activated", "loaded"))
    require(
        pre_active in (False, None),
        f"Creator was active before activation: {pre_active!r}",
    )
    api_request(
        client,
        "POST",
        f"{base_url}/api/plugins/{APP_ID}/activate",
        expected=(200, 201, 202),
        timeout=180.0,
    )
    wait_until(
        "Creator runtime.started event",
        lambda: acceptance_event_names(event_log) == ["runtime.started"],
        timeout=90.0,
    )

    configure_creator_llm(client, base_url, f"{fake_base_url}/v1")
    api_request(
        client,
        "PATCH",
        f"{base_url}/api/{APP_ID}/models/config/permission-mode",
        json_data={
            "execution_authorization": "required",
            "creation_checkpoints": "skip",
            "media_review": "auto_approve",
        },
    )

    grants_url = f"{base_url}/api/pawapps/workspaces/{WORKSPACE_ID}/task-grants"
    initial_grants = json_body(
        api_request(client, "GET", grants_url, headers=task_headers())
    )
    serialized_initial = compact_json(initial_grants)
    for private_action in PRIVATE_ACTIONS:
        require(
            private_action not in serialized_initial,
            f"private action leaked into catalog: {private_action}",
        )
    revision = find_value(initial_grants, ("revision",))
    require(
        isinstance(revision, int),
        f"grant catalog has no integer revision: {revision!r}",
    )
    api_request(
        client,
        "PUT",
        f"{grants_url}/actions/{APP_ID}/{ACTION_ID}",
        expected=(200, 201),
        json_data={"expected_revision": revision, "enabled": True, "input_values": {}},
        headers=task_headers(),
    )
    granted = json_body(api_request(client, "GET", grants_url, headers=task_headers()))
    serialized_granted = compact_json(granted)
    for private_action in PRIVATE_ACTIONS:
        require(
            private_action not in serialized_granted,
            f"private action leaked after grant: {private_action}",
        )
    enabled_actions: set[str] = set()
    for item in walk(granted):
        if not isinstance(item, dict) or item.get("enabled") is not True:
            continue
        action = item.get("action_id") or item.get("id")
        app = item.get("app_id")
        if isinstance(action, str) and (app in (None, APP_ID)):
            enabled_actions.add(action)
    require(
        enabled_actions == {ACTION_ID},
        f"expected only create-video grant, got {sorted(enabled_actions)}",
    )

    for private_action in sorted(PRIVATE_ACTIONS):
        response = api_request(
            client,
            "GET",
            f"{base_url}/api/pawapps/{APP_ID}/workspaces/{WORKSPACE_ID}/actions/{private_action}",
            expected=(404,),
            headers=task_headers(),
        )
        error_payload = json_body(response)
        require(
            "action_not_found" in compact_json(error_payload),
            f"wrong private-action error: {error_payload}",
        )

    task_id = drive_console_chat(client, base_url)
    chat_id = resolve_chat_uuid(client, base_url)
    observations: list[str] = [task_id]
    assert_task_identity(client, base_url, task_id, observations, "SSE delegation")

    download_path, final_task = browser_acceptance(
        resources,
        client,
        base_url,
        fake_base_url,
        chat_id,
        task_id,
        event_log,
        download_dir,
        observations,
    )
    require(
        set(observations) == {task_id},
        f"multiple task IDs observed: {sorted(set(observations))}",
    )

    task_events = json_body(
        api_request(
            client,
            "GET",
            f"{base_url}/api/pawapps/{APP_ID}/workspaces/{WORKSPACE_ID}/tasks/{quote(task_id, safe='')}/events",
            headers=task_headers(),
        )
    )
    require(task_events is not None, "task event stream was unavailable")
    final_events = acceptance_event_names(event_log)
    require(
        final_events == EXPECTED_EVENTS,
        f"unexpected acceptance event order: {final_events}",
    )
    require(
        final_events.count("image.generate") == 1,
        "expected exactly one image generation",
    )
    require(
        final_events.count("video.submit") == 1, "expected exactly one video submission"
    )
    refs = artifact_refs(final_task)
    require(len(refs) == 1, "expected exactly one canonical artifact")
    digests = artifact_digests(final_task)
    require(set(digests) == refs, "canonical artifact did not expose one valid digest")
    artifact_digest = digests[next(iter(refs))]

    downloaded_hash = sha256_file(download_path)
    downloaded_duration = ffprobe_duration(ffprobe, download_path)
    require(
        f"sha256:{downloaded_hash}" == artifact_digest,
        "downloaded MP4 digest differs from published ArtifactRef",
    )
    require(
        not fake_state.unknown_requests,
        f"fake server received unknown requests: {fake_state.unknown_requests}",
    )

    return {
        "ok": True,
        "task_id": task_id,
        "chat_id": chat_id,
        "artifact_count": 1,
        "download_count": 1,
        "duration_seconds": round(downloaded_duration, 3),
        "source_duration_seconds": round(source_duration, 3),
        "source_sha256": source_hash,
        "artifact_digest": artifact_digest,
        "sha256": downloaded_hash,
        "events": final_events,
        "fake_requests": len(fake_state.requests),
        "unknown_requests": 0,
    }


def main() -> int:
    resources = Resources()
    result: dict[str, Any]
    exit_code = 0
    try:
        result = run_acceptance(resources)
    except BaseException as exc:
        exit_code = 1
        result = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}"[:1500],
            **resources.failure_diagnostics(),
        }
    finally:
        resources.cleanup()
    print(compact_json(result), flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
