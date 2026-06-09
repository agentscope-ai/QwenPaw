# -*- coding: utf-8 -*-
"""Minimal LSP JSON-RPC client over subprocess stdio.

Designed for short, synchronous queries from inside the agent's
``lsp`` tool: definition, references, hover, document / workspace
symbols, implementation.  No streaming, no incremental sync, no
diagnostics — only correct request / response pairing.

A module-level pool keyed by ``(project_dir, language_id)`` keeps one
server alive per project so repeated calls share the same process.
``shutdown_all`` is registered with :mod:`atexit`.
"""
from __future__ import annotations

import atexit
import json
import logging
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Optional

LOGGER = logging.getLogger(__name__)

# Hide Windows console window when spawning the server.
_SUBPROCESS_FLAGS = (
    getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if sys.platform == "win32"
    else 0
)

_DEFAULT_TIMEOUT = 15.0
_INITIALIZE_TIMEOUT = 30.0


# ---------------------------------------------------------------------
# Wire format (pure functions, easy to unit-test)
# ---------------------------------------------------------------------


def encode_message(message: dict) -> bytes:
    """Frame an LSP message as ``Content-Length: N\\r\\n\\r\\n`` + body."""
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    return header + body


def parse_messages(buffer: bytes) -> tuple[list[dict], bytes]:
    """Pull zero or more complete LSP messages out of ``buffer``.

    Returns ``(messages, leftover)``.  Malformed headers are skipped;
    bodies that are not valid JSON are silently dropped.
    """
    messages: list[dict] = []
    while True:
        sep = buffer.find(b"\r\n\r\n")
        if sep < 0:
            break
        header_bytes = buffer[:sep]
        rest = buffer[sep + 4 :]
        length: Optional[int] = None
        for line in header_bytes.split(b"\r\n"):
            if line.lower().startswith(b"content-length:"):
                try:
                    length = int(line.split(b":", 1)[1].strip())
                except ValueError:
                    length = None
                break
        if length is None:
            buffer = rest
            continue
        if len(rest) < length:
            break
        body = rest[:length]
        buffer = rest[length:]
        try:
            messages.append(json.loads(body.decode("utf-8")))
        except (json.JSONDecodeError, UnicodeDecodeError):
            LOGGER.debug("Dropping malformed LSP body: %r", body[:80])
    return messages, buffer


# ---------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------


class LspError(RuntimeError):
    """Raised when the LSP server returns a JSON-RPC error or dies."""


def _client_capabilities() -> dict:
    """Minimal client capability hash advertised to the server."""
    return {
        "textDocument": {
            "synchronization": {
                "didSave": False,
                "willSave": False,
                "willSaveWaitUntil": False,
                "dynamicRegistration": False,
            },
            "definition": {"linkSupport": False},
            "references": {},
            "hover": {"contentFormat": ["plaintext", "markdown"]},
            "documentSymbol": {
                "hierarchicalDocumentSymbolSupport": True,
            },
            "implementation": {"linkSupport": False},
        },
        "workspace": {
            "symbol": {},
            "workspaceFolders": True,
        },
    }


class LspClient:  # pylint: disable=too-many-instance-attributes
    """One running LSP server, scoped to one project + language pair."""

    def __init__(
        self,
        argv: list[str],
        project_dir: Path,
        language_id: str,
    ) -> None:
        self._argv = list(argv)
        self._project_dir = project_dir.resolve()
        self._language_id = language_id
        self._proc: Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._next_id = 1
        self._pending: dict[int, "queue.Queue[Any]"] = {}
        self._opened: set[str] = set()
        self._stopped = False

    # ---- lifecycle ------------------------------------------------

    def start(self) -> None:
        """Spawn the server and run ``initialize`` (idempotent)."""
        with self._lock:
            if self._proc is not None:
                return
            try:
                self._proc = (
                    subprocess.Popen(  # pylint: disable=consider-using-with
                        self._argv,
                        cwd=str(self._project_dir),
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        bufsize=0,
                        creationflags=_SUBPROCESS_FLAGS,
                    )
                )
            except (OSError, FileNotFoundError) as exc:
                raise LspError(
                    f"Failed to spawn LSP server {self._argv[0]}: {exc}",
                ) from exc
            self._reader = threading.Thread(
                target=self._read_loop,
                name=f"lsp-reader-{self._language_id}",
                daemon=True,
            )
            self._reader.start()
        self._initialize()

    def shutdown(self) -> None:
        """Best-effort: shutdown → exit → kill, then drain pending."""
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            proc = self._proc
            self._proc = None
        if proc is None:
            self._fail_pending("client shutdown")
            return
        try:
            try:
                self._send_raw(
                    proc,
                    {"jsonrpc": "2.0", "id": -1, "method": "shutdown"},
                )
                self._send_raw(proc, {"jsonrpc": "2.0", "method": "exit"})
            except LspError:
                pass
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    pass
        finally:
            self._fail_pending("client shutdown")

    def _fail_pending(self, reason: str) -> None:
        with self._lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for q in pending:
            try:
                q.put_nowait({"error": {"message": reason}})
            except queue.Full:
                pass

    # ---- internal: send + read ------------------------------------

    def _send_raw(self, proc: subprocess.Popen, message: dict) -> None:
        if proc.stdin is None:
            raise LspError("LSP server has no stdin")
        data = encode_message(message)
        with self._send_lock:
            try:
                proc.stdin.write(data)
                proc.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise LspError(
                    f"LSP server pipe broke: {exc}",
                ) from exc

    def _send(self, message: dict) -> None:
        proc = self._proc
        if proc is None:
            raise LspError("LSP server is not running")
        self._send_raw(proc, message)

    def _read_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        buffer = b""
        try:
            while True:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                buffer += chunk
                messages, buffer = parse_messages(buffer)
                for msg in messages:
                    self._dispatch(msg)
        except (OSError, ValueError):
            pass
        finally:
            self._fail_pending("LSP server died")

    def _dispatch(self, msg: dict) -> None:
        if "id" in msg and "method" in msg:
            # Server-initiated request — reply with null so the server
            # does not block waiting on us.  We do not implement any.
            try:
                self._send(
                    {"jsonrpc": "2.0", "id": msg["id"], "result": None},
                )
            except LspError:
                pass
            return
        if "id" in msg:
            req_id = msg["id"]
            with self._lock:
                q = self._pending.pop(req_id, None)
            if q is not None:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    pass
            return
        # Notification — ignore (e.g. textDocument/publishDiagnostics).

    def _request(
        self,
        method: str,
        params: dict,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> Any:
        with self._lock:
            req_id = self._next_id
            self._next_id += 1
            q: queue.Queue = queue.Queue(maxsize=1)
            self._pending[req_id] = q

        self._send(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": method,
                "params": params,
            },
        )
        try:
            response = q.get(timeout=timeout)
        except queue.Empty as exc:
            with self._lock:
                self._pending.pop(req_id, None)
            raise LspError(
                f"LSP request {method} timed out after {timeout}s",
            ) from exc

        if isinstance(response, dict) and "error" in response:
            raise LspError(
                f"LSP error from {method}: {response['error']}",
            )
        return response.get("result") if isinstance(response, dict) else None

    def _notify(self, method: str, params: dict) -> None:
        self._send(
            {"jsonrpc": "2.0", "method": method, "params": params},
        )

    # ---- initialize + didOpen -------------------------------------

    def _initialize(self) -> None:
        root_uri = self._project_dir.as_uri()
        self._request(
            "initialize",
            {
                "processId": os.getpid(),
                "rootUri": root_uri,
                "capabilities": _client_capabilities(),
                "workspaceFolders": [
                    {"uri": root_uri, "name": self._project_dir.name},
                ],
            },
            timeout=_INITIALIZE_TIMEOUT,
        )
        self._notify("initialized", {})

    def _ensure_open(self, file_path: Path) -> str:
        """Open ``file_path`` on the server if not already; return URI."""
        uri = file_path.resolve().as_uri()
        with self._lock:
            if uri in self._opened:
                return uri
        try:
            text = file_path.read_text(encoding="utf-8")
        except OSError:
            text = ""
        self._notify(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": uri,
                    "languageId": self._language_id,
                    "version": 1,
                    "text": text,
                },
            },
        )
        with self._lock:
            self._opened.add(uri)
        return uri

    # ---- public LSP operations ------------------------------------

    def definition(
        self,
        file_path: Path,
        line: int,
        character: int,
    ) -> Any:
        uri = self._ensure_open(file_path)
        return self._request(
            "textDocument/definition",
            {
                "textDocument": {"uri": uri},
                "position": {
                    "line": line - 1,
                    "character": character - 1,
                },
            },
        )

    def references(
        self,
        file_path: Path,
        line: int,
        character: int,
    ) -> Any:
        uri = self._ensure_open(file_path)
        return self._request(
            "textDocument/references",
            {
                "textDocument": {"uri": uri},
                "position": {
                    "line": line - 1,
                    "character": character - 1,
                },
                "context": {"includeDeclaration": True},
            },
        )

    def hover(
        self,
        file_path: Path,
        line: int,
        character: int,
    ) -> Any:
        uri = self._ensure_open(file_path)
        return self._request(
            "textDocument/hover",
            {
                "textDocument": {"uri": uri},
                "position": {
                    "line": line - 1,
                    "character": character - 1,
                },
            },
        )

    def document_symbol(self, file_path: Path) -> Any:
        uri = self._ensure_open(file_path)
        return self._request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": uri}},
        )

    def workspace_symbol(self, query: str) -> Any:
        return self._request("workspace/symbol", {"query": query})

    def implementation(
        self,
        file_path: Path,
        line: int,
        character: int,
    ) -> Any:
        uri = self._ensure_open(file_path)
        return self._request(
            "textDocument/implementation",
            {
                "textDocument": {"uri": uri},
                "position": {
                    "line": line - 1,
                    "character": character - 1,
                },
            },
        )


# ---------------------------------------------------------------------
# Pool
# ---------------------------------------------------------------------


_POOL_LOCK = threading.Lock()
_POOL: dict[tuple[str, str], LspClient] = {}


def get_client(
    project_dir: Path,
    language_id: str,
    argv: list[str],
) -> LspClient:
    """Return (creating if necessary) a started client from the pool."""
    key = (str(project_dir.resolve()), language_id)
    with _POOL_LOCK:
        client = _POOL.get(key)
        if client is None:
            client = LspClient(argv, project_dir, language_id)
            _POOL[key] = client
    client.start()
    return client


def shutdown_all() -> None:
    """Tear down every pooled client (best-effort)."""
    with _POOL_LOCK:
        clients = list(_POOL.values())
        _POOL.clear()
    for c in clients:
        try:
            c.shutdown()
        except Exception:  # noqa: BLE001  pragma: no cover
            LOGGER.debug("LSP shutdown raised", exc_info=True)


atexit.register(shutdown_all)
