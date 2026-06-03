# -*- coding: utf-8 -*-
"""E2B sandbox provider — pure httpx, no E2B SDK dependency.

Creates and manages sandboxes via sandbox-manager's E2B-compatible API.
Executes commands via gRPC-Web protocol directly against the envd inside
each sandbox Pod.

Environment variables:
    E2B_API_URL      sandbox-manager E2B endpoint (e.g. http://host:8000/e2b)
    E2B_API_KEY      bearer token for sandbox-manager
    E2B_SANDBOX_URL  sandbox-manager base URL (e.g. http://host:8000)
"""

import asyncio
import base64
import json
import logging
import os
import struct
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

_ANONYMOUS_USER = "__anonymous__"


def _sandbox_key(user_id: str, session_id: str) -> str:
    return f"{user_id or _ANONYMOUS_USER}:{session_id}"


def _grpc_web_frame(payload: dict) -> bytes:
    body = json.dumps(payload).encode()
    return b"\x00" + struct.pack(">I", len(body)) + body


def _parse_grpc_web_response(data: bytes) -> List[dict]:
    results = []
    pos = 0
    while pos + 5 <= len(data):
        flag = data[pos]
        msg_len = struct.unpack(">I", data[pos + 1 : pos + 5])[0]
        msg = data[pos + 5 : pos + 5 + msg_len]
        if flag == 0:
            try:
                results.append(json.loads(msg))
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
        pos += 5 + msg_len
    return results


class E2BSandboxHandle:
    """Handle for a live E2B sandbox, connected via envd gRPC-Web."""

    def __init__(
        self,
        sandbox_id: str,
        envd_url: str,
        envd_token: str,
        api_url: str,
        api_key: str,
    ) -> None:
        self.sandbox_id = sandbox_id
        self._envd_url = envd_url
        self._envd_token = envd_token
        self._api_url = api_url
        self._api_key = api_key

    def _envd_headers(self, content_type: str = "application/json") -> dict:
        return {"X-Access-Token": self._envd_token, "Content-Type": content_type}

    async def _grpc_call(self, path: str, payload: dict) -> List[dict]:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._envd_url}{path}",
                content=_grpc_web_frame(payload),
                headers=self._envd_headers("application/grpc-web+json"),
                timeout=60,
            )
        return _parse_grpc_web_response(resp.content)

    async def run_command(
        self, command: str, cwd: str = "/home/user", timeout: int = 60
    ) -> Tuple[int, str, str]:
        """Run a shell command. Returns (exit_code, stdout, stderr)."""
        frames = await self._grpc_call(
            "/process.Process/Start",
            {
                "process": {
                    "cmd": "/bin/bash",
                    "args": ["-c", command],
                    "envVars": {},
                    "cwd": cwd,
                }
            },
        )

        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        exit_code = 0

        for frame in frames:
            event = frame.get("event", {})
            data = event.get("data", {})
            if "stdout" in data:
                stdout_parts.append(
                    base64.b64decode(data["stdout"]).decode("utf-8", errors="replace")
                )
            if "stderr" in data:
                stderr_parts.append(
                    base64.b64decode(data["stderr"]).decode("utf-8", errors="replace")
                )
            end = event.get("end", {})
            if end:
                status_str = end.get("status", "")
                if "exit status" in status_str:
                    try:
                        exit_code = int(status_str.split("exit status")[-1].strip())
                    except ValueError:
                        exit_code = 1 if not end.get("exited", True) else 0

        return exit_code, "".join(stdout_parts), "".join(stderr_parts)

    async def read_file(self, path: str) -> bytes:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._envd_url}/files",
                params={"path": path},
                headers={"X-Access-Token": self._envd_token},
                timeout=30,
            )
            if resp.status_code == 404:
                raise FileNotFoundError(f"File not found in sandbox: {path}")
            resp.raise_for_status()
            return resp.content

    async def write_file(self, path: str, content: bytes | str) -> None:
        if isinstance(content, str):
            content = content.encode("utf-8")
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._envd_url}/files",
                files={"file": ("upload", content, "application/octet-stream")},
                data={"path": path},
                headers={"X-Access-Token": self._envd_token},
                timeout=30,
            )
            resp.raise_for_status()

    async def list_dir(self, path: str) -> List[Dict[str, Any]]:
        frames = await self._grpc_call(
            "/filesystem.Filesystem/ListDir", {"path": path}
        )
        entries = []
        for frame in frames:
            for e in frame.get("entries", []):
                entries.append(e)
        return entries


class E2BSandboxProvider:
    """SandboxProvider backed by sandbox-manager's E2B-compatible API.

    Uses httpx directly — no e2b pip package required.
    """

    def __init__(
        self,
        template_id: str = "e2b",
        api_url: str | None = None,
        api_key: str | None = None,
        sandbox_url: str | None = None,
    ) -> None:
        self._template_id = template_id
        self._api_url = (
            api_url or os.environ.get("E2B_API_URL", "")
        ).rstrip("/")
        self._api_key = api_key or os.environ.get("E2B_API_KEY", "")
        self._sandbox_url = (
            sandbox_url or os.environ.get("E2B_SANDBOX_URL", "")
        ).rstrip("/")
        self._handles: Dict[str, E2BSandboxHandle] = {}
        self._lock = asyncio.Lock()
        logger.info(
            "E2BSandboxProvider initialized (api=%s, template=%s)",
            self._api_url,
            self._template_id,
        )

    @property
    def template_id(self) -> str:
        return self._template_id

    async def get_or_create(
        self, session_id: str, user_id: str = ""
    ) -> Optional[E2BSandboxHandle]:
        key = _sandbox_key(user_id, session_id)

        async with self._lock:
            if key in self._handles:
                return self._handles[key]

        effective_user = user_id or _ANONYMOUS_USER
        logger.info(
            "E2BSandboxProvider: creating sandbox user=%s session=%s",
            effective_user,
            session_id,
        )

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._api_url}/sandboxes",
                json={"templateID": self._template_id, "timeout": 300},
                headers={"X-API-Key": self._api_key},
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()

        sbx_id = data["sandboxID"]
        envd_token = data["envdAccessToken"]

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._sandbox_url}/get_info",
                json={"identity": sbx_id},
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                timeout=30,
            )
            resp.raise_for_status()
            envd_url = resp.json()["data"]["url"]

        async with httpx.AsyncClient() as client:
            await client.post(
                f"{envd_url}/init",
                json={"accessToken": envd_token, "envVars": {}},
                headers={"Content-Type": "application/json"},
                timeout=30,
            )

        handle = E2BSandboxHandle(
            sandbox_id=sbx_id,
            envd_url=envd_url,
            envd_token=envd_token,
            api_url=self._api_url,
            api_key=self._api_key,
        )

        logger.info(
            "E2BSandboxProvider: sandbox created id=%s envd=%s",
            sbx_id,
            envd_url,
        )

        async with self._lock:
            if key in self._handles:
                await self._delete_sandbox(sbx_id)
                return self._handles[key]
            self._handles[key] = handle

        return handle

    async def release(self, session_id: str, user_id: str = "") -> None:
        key = _sandbox_key(user_id, session_id)
        handle = None
        async with self._lock:
            handle = self._handles.pop(key, None)
        if handle:
            await self._delete_sandbox(handle.sandbox_id)

    async def release_all(self) -> None:
        async with self._lock:
            handles = list(self._handles.values())
            self._handles.clear()
        for h in handles:
            try:
                await self._delete_sandbox(h.sandbox_id)
            except Exception:
                logger.warning(
                    "Failed to release sandbox %s", h.sandbox_id, exc_info=True
                )

    async def _delete_sandbox(self, sandbox_id: str) -> None:
        try:
            async with httpx.AsyncClient() as client:
                await client.delete(
                    f"{self._api_url}/sandboxes/{sandbox_id}",
                    headers={"X-API-Key": self._api_key},
                    timeout=10,
                )
            logger.info("E2BSandboxProvider: released sandbox %s", sandbox_id)
        except Exception:
            logger.warning(
                "Failed to delete sandbox %s", sandbox_id, exc_info=True
            )
