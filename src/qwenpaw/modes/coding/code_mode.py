# -*- coding: utf-8 -*-
"""Python tool orchestration using native AgentScope tools and permissions."""

from __future__ import annotations

import asyncio
import hashlib
import json
import keyword
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from copy import copy
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any

import jsonschema
from agentscope.message import DataBlock, TextBlock, ToolCallBlock
from agentscope.message import ToolResultState
from agentscope.permission import PermissionBehavior, PermissionDecision
from agentscope.permission import PermissionEngine
from agentscope.state import AgentState
from agentscope.tool import Toolkit, ToolBase, ToolChunk, ToolResponse

from ...config.context import get_current_recent_max_bytes
from ...config.context import current_script_tool_call
from ._process import WorkerProcess
from .prompt import CODE_DESCRIPTION

_execution_toolkit: ContextVar[Toolkit | None] = ContextVar(
    "code_execution_toolkit",
    default=None,
)


async def _tool_catalog(toolkit: Toolkit, groups=None) -> dict[str, dict]:
    """Use one catalog and identifier mapping for declarations and calls."""
    definitions = await toolkit.get_tool_schemas(groups)
    catalog = {}
    aliases = set()
    for index, item in enumerate(definitions):
        schema = item["function"]
        name = schema["name"]
        if name == "run_code":
            continue
        alias = re.sub(r"\W", "_", name)
        if (
            not alias.isidentifier()
            or keyword.iskeyword(alias)
            or alias.startswith("__")
        ):
            alias = f"tool_{alias}"
        while alias in aliases:
            alias = f"{alias}_{index}"
        aliases.add(alias)
        catalog[name] = {**schema, "python_name": alias}
    return catalog


def _describe_catalog(catalog: dict[str, dict]) -> str:
    """Inline real tool contracts within a bounded declaration budget."""
    sections = []
    for schema in catalog.values():
        name = schema["python_name"]
        parameters = json.dumps(schema["parameters"], ensure_ascii=False)
        sections.append(
            f"### tools.{name}\n{schema['description']}\n"
            f"Keyword arguments (JSON Schema): {parameters}",
        )
    budget = 12000
    selected = []
    for section in sorted(sections, key=len):
        if len(section) <= budget:
            selected.append(section)
            budget -= len(section)
    examples = []
    if "web_search" in catalog:
        examples.append(
            f'r = await tools.web_search(search_term="weather today"); '
            f'text(r["content"])',
        )
    if "execute_shell_command" in catalog:
        examples.append(
            f'r = await tools.execute_shell_command(command="pwd"); '
            f'text(r["content"])',
        )
    names = ", ".join(
        f"tools.{schema['python_name']}" for schema in catalog.values()
    )
    return (
        f"\n\nAvailable tools: {names or '(none)'}.\n"
        f"Inspect await describe_tool(name) for any omitted contract.\n"
        f"Examples (enabled tools): {'; '.join(examples)}\n\n"
        + "\n\n".join(selected)
    )


def build_code_mode_toolkit(
    *,
    tools: list,
    skills_or_loaders: list,
) -> Toolkit:
    """Expose one Python entry while retaining all enabled native tools."""
    catalog = Toolkit(tools=tools, skills_or_loaders=skills_or_loaders)
    code = CodeModeTool(catalog)
    return CodeModeToolkit(code)


class CodeModeToolkit(Toolkit):
    """A single code tool with the catalog's native skill instructions."""

    def __init__(self, code: CodeModeTool) -> None:
        super().__init__(tools=[code])
        self.code = code
        self.catalog = code.toolkit

    async def get_tool(self, name: str):
        return (
            await super().get_tool(name)
            if name == self.code.name
            else await self.catalog.get_tool(name)
        )

    async def add_tool(self, tool, group_name="basic") -> None:
        await self.catalog.add_tool(tool, group_name)

    async def call_tool(self, tool_call, state):
        invocation = _execution_toolkit.get()
        target = invocation if invocation is not None else self
        if target is self:
            async for chunk in super().call_tool(tool_call, state):
                yield chunk
        else:
            async for chunk in target.call_tool(tool_call, state):
                yield chunk

    async def get_tool_schemas(self, groups=None):
        catalog = await _tool_catalog(self.catalog, groups)
        self.code.description = CodeModeTool.description + _describe_catalog(
            catalog,
        )
        return await super().get_tool_schemas(groups)

    async def get_skill_instructions(self, activated_groups=None):
        instructions = await self.catalog.get_skill_instructions(
            activated_groups,
        )
        if instructions:
            viewer = self.catalog.builtin_skill_viewer.tool.name
            return (
                f"{instructions}\nCall the skill viewer as "
                f"tools.{viewer}(...) inside run_code."
            )
        return None


class CodeModeTool(ToolBase):
    """A fresh CPython worker sharing the live native tool catalog."""

    name = "run_code"
    is_read_only = True
    is_concurrency_safe = False
    is_state_injected = True
    input_schema = {
        "type": "object",
        "properties": {"code": {"type": "string"}},
        "required": ["code"],
        "additionalProperties": False,
    }
    description = CODE_DESCRIPTION

    def __init__(self, toolkit: Toolkit) -> None:
        super().__init__()
        self.toolkit = toolkit
        self.check_permission: Callable[
            ...,
            Awaitable[PermissionDecision],
        ] | None = None
        self.acting: Callable[
            [ToolCallBlock],
            AsyncIterator[ToolChunk | ToolResponse],
        ] | None = None
        self.condition = asyncio.Condition()
        self.readers = 0
        self.writer = False

    @asynccontextmanager
    async def execution_slot(self, tool):
        """Keep unsafe/stateful calls exclusive, including across scripts."""
        safe = tool.is_concurrency_safe and not tool.is_state_injected
        async with self.condition:
            await self.condition.wait_for(
                lambda: not self.writer
                and (self.readers < 32 if safe else self.readers == 0),
            )
            if safe:
                self.readers += 1
            else:
                self.writer = True
        try:
            yield
        finally:
            async with self.condition:
                if safe:
                    self.readers -= 1
                else:
                    self.writer = False
                self.condition.notify_all()

    async def execute_tool(self, tool, call, state) -> ToolResponse:
        """Enter native acting middleware without publishing raw context."""
        invocation = Toolkit(tools=[tool])
        token = _execution_toolkit.set(invocation)
        raw_token = current_script_tool_call.set(True)
        try:
            async with self.execution_slot(tool):
                acting = self.acting
                stream = (
                    acting(call)  # pylint: disable=not-callable
                    if acting is not None
                    else invocation.call_tool(call, state)
                )
                response = None
                async for chunk in stream:
                    if isinstance(chunk, ToolResponse):
                        response = chunk
                if response is None:
                    raise RuntimeError(
                        f"Tool '{tool.name}' returned no result",
                    )
                return response
        finally:
            current_script_tool_call.reset(raw_token)
            _execution_toolkit.reset(token)

    async def check_permissions(self, *_args, **_kwargs):
        """Authorize computation; every nested action has its own check."""
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="Script computation; nested tools retain permissions.",
        )

    async def call(self, code: str, _agent_state: AgentState) -> ToolChunk:
        """Execute a fresh script without sharing mutable invocation state."""
        return await _Script(self, _agent_state).run(code)


class _Script:
    """Own one sandbox's catalog, output budget and in-flight host calls."""

    def __init__(self, tool: CodeModeTool, state: AgentState) -> None:
        self.tool = tool
        self.state = state
        self.output: list = []
        self.calls: list[dict] = []
        self.pending: set[asyncio.Task] = set()
        self.budget = min(
            get_current_recent_max_bytes() or 16384,
            16 * 1024 * 1024,
        )
        self.media_budget = 16 * 1024 * 1024
        self.media_sources: set[str] = set()
        self.catalog: dict[str, dict] = {}
        self.aliases: dict[str, str] = {}
        self.python_names: dict[str, str] = {}

    async def _load_catalog(self) -> None:
        self.catalog = await _tool_catalog(
            self.tool.toolkit,
            self.state.tool_context.activated_groups,
        )
        self.aliases = {
            schema["python_name"]: name
            for name, schema in self.catalog.items()
        }
        self.python_names = {
            name: alias for alias, name in self.aliases.items()
        }

    def _tool_list(self) -> list[dict]:
        return [
            {
                "name": name,
                "python_name": self.python_names[name],
                "description": schema["description"],
            }
            for name, schema in self.catalog.items()
        ]

    async def search_tools(self, query: str = "") -> list[dict]:
        terms = query.lower().split()
        return [
            item
            for item in self._tool_list()
            if all(term in json.dumps(item).lower() for term in terms)
        ][:8]

    async def describe_tool(self, name: str) -> dict:
        name = self.aliases.get(name, name)
        schema = self.catalog.get(name)
        if schema is None:
            raise ValueError(f"Unknown or unavailable tool: {name}")
        return {
            **schema,
            "python_name": self.python_names[name],
            "call": f"await tools.{self.python_names[name]}(**arguments)",
            "returns": {
                "content": "Native content blocks; text is not parsed JSON",
                "metadata": "Tool metadata, or null",
                "state": "success, error, denied or interrupted",
            },
        }

    def text(self, value: Any) -> None:
        rendered = (
            value
            if isinstance(value, str)
            else json.dumps(value, ensure_ascii=False)
        )
        encoded = rendered.encode("utf-8")
        if self.budget <= 0:
            return
        if len(encoded) > self.budget:
            rendered = encoded[: self.budget].decode("utf-8", errors="ignore")
            rendered = f"{rendered}\n[Code output truncated]"
        self.budget -= len(encoded)
        self.output.append(TextBlock(text=rendered))

    def media(self, kind: str, block: dict) -> None:
        data = DataBlock.model_validate(block)
        if not data.source.media_type.startswith(f"{kind}/"):
            raise ValueError(f"{kind}() expects a data block of type {kind}/*")
        source = hashlib.sha256(
            json.dumps(
                data.source.model_dump(mode="json"),
                sort_keys=True,
            ).encode("utf-8"),
        ).hexdigest()
        if (
            data.source.type == "url"
            and data.source.url.scheme != "data"
            and source not in self.media_sources
        ):
            raise ValueError(
                f"{kind}() expects inline data or media returned by a tool; "
                f"read host media through the enabled tools first.",
            )
        self.media_budget -= len(json.dumps(block).encode("utf-8"))
        if self.media_budget < 0:
            raise ValueError(f"Code media output exceeded 16 MiB")
        self.output.append(data)

    async def invoke(self, name: str, *positional, **arguments) -> dict:
        if positional:
            raise TypeError(
                f"tools.{self.python_names[name]} requires keyword arguments; "
                f"inspect await describe_tool({name!r}) for parameter names.",
            )
        record = {"name": name, "state": "calling"}
        self.calls.append(record)
        try:
            tool = copy(
                await self.tool.toolkit.check_tool_available(
                    name,
                    self.state.tool_context.activated_groups,
                ),
            )
            if tool.is_external_tool:
                raise ValueError(
                    f"External-only tool cannot run in code: {name}",
                )
            jsonschema.validate(arguments, tool.input_schema)
            call = ToolCallBlock(
                id=f"code_{uuid.uuid4().hex}",
                name=name,
                input=json.dumps(arguments, ensure_ascii=False),
            )
            if self.tool.check_permission is not None:
                decision = await self.tool.check_permission(
                    call,
                    tool,
                    arguments,
                )
            else:
                decision = await PermissionEngine(
                    self.state.permission_context,
                ).check_permission(tool, arguments)
            if decision.behavior != PermissionBehavior.ALLOW:
                record["state"] = "denied"
                raise PermissionError(decision.message)
            response = await self.tool.execute_tool(tool, call, self.state)
            record["state"] = response.state.value
            if response.state == ToolResultState.INTERRUPTED:
                raise asyncio.CancelledError()
            result = response.model_dump(mode="json")
            if response.state != ToolResultState.SUCCESS:
                raise RuntimeError(json.dumps(result, ensure_ascii=False))
            for block in response.content:
                if isinstance(block, DataBlock) and block.source.type == "url":
                    self.media_sources.add(
                        hashlib.sha256(
                            json.dumps(
                                block.source.model_dump(mode="json"),
                                sort_keys=True,
                            ).encode("utf-8"),
                        ).hexdigest(),
                    )
            return {
                key: result[key]
                for key in (
                    "content",
                    "metadata",
                    "state",
                )
            }
        except asyncio.CancelledError:
            record["state"] = "interrupted"
            raise
        except Exception:
            if record["state"] == "calling":
                record["state"] = "error"
            raise

    async def _respond(self, worker: WorkerProcess, packet: dict) -> None:
        try:
            name = packet["name"]
            if name.startswith("tools."):
                alias = name.removeprefix("tools.")
                if alias not in self.aliases:
                    raise ValueError(f"Unknown or unavailable tool: {alias}")
                result = await self.invoke(
                    self.aliases[alias],
                    *packet["args"],
                    **packet["kwargs"],
                )
            else:
                helpers: dict[str, Callable[..., Awaitable[Any]]] = {
                    "search_tools": self.search_tools,
                    "describe_tool": self.describe_tool,
                }
                result = await helpers[name](
                    *packet["args"],
                    **packet["kwargs"],
                )
            response = {"id": packet["id"], "result": result}
        except Exception as exc:
            response = {
                "id": packet["id"],
                "error": f"{type(exc).__name__}: {exc}",
            }
        try:
            await worker.send(response)
        except ValueError as exc:
            await worker.send({"id": packet["id"], "error": str(exc)})
        except (BrokenPipeError, ConnectionError):
            pass
        finally:
            task = asyncio.current_task()
            assert task is not None
            self.pending.discard(task)

    async def _receive(self, worker: WorkerProcess) -> None:
        count = 0
        while True:
            packet = await worker.receive()
            if packet["kind"] == "call":
                count += 1
                if count > 1000:
                    raise RuntimeError(f"Code exceeded 1000 host calls")
                task = asyncio.create_task(self._respond(worker, packet))
                self.pending.add(task)
            elif packet["kind"] == "text":
                self.text(packet["value"])
            elif packet["kind"] in ("image", "audio", "video"):
                self.media(packet["kind"], packet["value"])
            elif packet["kind"] == "done":
                if packet.get("error"):
                    raise RuntimeError(packet["error"])
                return
            else:
                raise ValueError(f"Unknown worker message: {packet['kind']}")

    async def run(self, code: str) -> ToolChunk:
        status = ToolResultState.SUCCESS
        await self._load_catalog()
        tasks = []
        try:
            async with WorkerProcess() as worker:
                await worker.send({"code": code, "tools": self._tool_list()})
                receiver = asyncio.create_task(self._receive(worker))
                watchdog = asyncio.create_task(worker.watch())
                tasks = [receiver, watchdog]
                done, _ = await asyncio.wait(
                    tasks,
                    timeout=600,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:
                    raise TimeoutError(f"Code exceeded 600 seconds")
                if watchdog in done:
                    await watchdog
                await receiver
        except Exception as exc:
            status = ToolResultState.ERROR
            self.output.append(TextBlock(text=f"Script failed: {exc}"[:4096]))
        finally:
            pending = [*tasks, *self.pending]
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        return ToolChunk(
            content=self.output or [TextBlock(text=f"Script completed.")],
            state=status,
            metadata={"code_mode": {"calls": self.calls}},
        )
