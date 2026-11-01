# -*- coding: utf-8 -*-
"""Standalone stdlib worker; host capabilities stay behind asynchronous RPC."""

from __future__ import annotations

import ast
import asyncio
import inspect
import json
import os
import sys
import threading
import traceback
from functools import partial
from types import SimpleNamespace

MAX_MESSAGE_BYTES = 16 * 1024 * 1024


class Worker:
    """Multiplex host calls and selected output over inherited stdio."""

    def __init__(self) -> None:
        # Keep the daemon reader off Python's shutdown-managed stdin buffer.
        self.input = os.fdopen(os.dup(sys.stdin.fileno()), "rb")
        self.output = sys.stdout.buffer
        self.lock = threading.Lock()
        self.pending: dict[int, asyncio.Future] = {}
        self.sequence = 0
        self.loop = asyncio.get_running_loop()

    def emit(self, kind: str, **data) -> None:
        packet = json.dumps(
            {"kind": kind, **data},
            ensure_ascii=False,
            default=str,
        )
        if len(packet.encode("utf-8")) > MAX_MESSAGE_BYTES:
            raise ValueError(f"Code message exceeds 16 MiB")
        with self.lock:
            self.output.write(f"{packet}\n".encode(f"utf-8"))
            self.output.flush()

    def resolve(self, packet: dict) -> None:
        future = self.pending.pop(packet["id"], None)
        if future is None or future.done():
            return
        if packet.get(f"cancelled"):
            future.cancel()
        elif "error" in packet:
            future.set_exception(RuntimeError(packet["error"]))
        else:
            future.set_result(packet["result"])

    def read_responses(self) -> None:
        try:
            while line := self.input.readline(MAX_MESSAGE_BYTES + 1):
                if len(line) > MAX_MESSAGE_BYTES:
                    raise ValueError(f"Host message exceeds 16 MiB")
                self.loop.call_soon_threadsafe(self.resolve, json.loads(line))
        except (OSError, ValueError):
            pass
        finally:
            if not self.loop.is_closed():
                self.loop.call_soon_threadsafe(self.disconnect)

    def disconnect(self) -> None:
        for future in self.pending.values():
            if not future.done():
                future.set_exception(RuntimeError(f"Code host disconnected"))

    async def call(self, name: str, *args, **kwargs):
        self.sequence += 1
        call_id = self.sequence
        future = self.loop.create_future()
        self.pending[call_id] = future
        try:
            self.emit(
                "call",
                id=call_id,
                name=name,
                args=args,
                kwargs=kwargs,
            )
            return await future
        finally:
            self.pending.pop(call_id, None)

    def text(self, value) -> None:
        self.emit("text", value=value)

    def write(self, text: str) -> int:
        if text:
            self.text(text)
        return len(text)

    def flush(self) -> None:
        """Output packets are flushed by emit."""

    async def run(self) -> None:
        initial = json.loads(self.input.readline(MAX_MESSAGE_BYTES + 1))
        threading.Thread(target=self.read_responses, daemon=True).start()
        sys.stdout = sys.stderr = self
        namespace = {
            "__name__": "__code_mode__",
            "tools": SimpleNamespace(
                **{
                    tool["python_name"]: partial(
                        self.call,
                        f"tools.{tool['python_name']}",
                    )
                    for tool in initial["tools"]
                },
            ),
            "ALL_TOOLS": initial["tools"],
            "search_tools": partial(self.call, "search_tools"),
            "describe_tool": partial(self.call, "describe_tool"),
            "text": self.text,
            "image": lambda block: self.emit("image", value=block),
            "audio": lambda block: self.emit("audio", value=block),
            "video": lambda block: self.emit("video", value=block),
        }
        try:
            tree = ast.parse(initial["code"], filename="<run_code>")
            if tree.body and isinstance(tree.body[-1], ast.Expr):
                expression = tree.body[-1]
                tree.body[-1] = ast.copy_location(
                    ast.Assign(
                        targets=[ast.Name(id="_code_result", ctx=ast.Store())],
                        value=expression.value,
                    ),
                    expression,
                )
                ast.fix_missing_locations(tree)
            compiled = compile(
                tree,
                filename="<run_code>",
                mode="exec",
                flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT,
            )
            result = eval(compiled, namespace)  # pylint: disable=eval-used
            if inspect.isawaitable(result):
                await result
            if namespace.get("_code_result") is not None:
                self.text(namespace["_code_result"])
            self.emit("done")
        except BaseException as exc:
            self.emit(
                f"done",
                error=traceback.format_exc()[-4096:],
                cancelled=isinstance(exc, asyncio.CancelledError),
            )


async def main() -> None:
    await Worker().run()


if __name__ == "__main__":
    asyncio.run(main())
