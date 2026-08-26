# -*- coding: utf-8 -*-
"""Execute agent-written browser code with recording available.

The tool surface mirrors the main repository's browser tool: the model writes
module-level async Python, ``Browser`` is already in scope, and it works in a
perceive → act → verify loop. Creator adds one name, ``recorder``, so the
model decides for itself when footage is worth keeping — and therefore also
decides when no footage is needed at all.

Nothing about the flow is prescribed here. This module runs what the model
wrote, records the facts of what happened, and hands back both.
"""

from __future__ import annotations

import ast
import asyncio
import builtins
import contextlib
import io
import logging
import sys
import threading
import time
import types
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .manifest import TakeManifest
from .recorder import RecordedTake, TakeRecorder
from .recording_link import RecordingControlLink
from .session import LiveBrowserSession, LiveSessionError, workspace_dir

logger = logging.getLogger(__name__)

_MAX_OUTPUT_CHARS = 12_000
_MAX_RANGE_ITEMS = 1_000
_MAX_AST_NODES = 2_000
_MAX_LITERAL_ELEMENTS = 500
_MAX_STRING_CONSTANT_CHARS = 10_000
_MAX_NUMERIC_CONSTANT = 1_000_000
_MAX_LOOP_DEPTH = 2
_SOURCE_NAME = "browser_use_code"
_ALLOWED_BROWSER_DELEGATIONS = frozenset(
    {
        "close_page",
        "handoff",
        "pages",
        "session_status",
        "switch_page",
    },
)
_ALLOWED_PAGE_DELEGATIONS = frozenset(
    {
        "current_surface",
        "frame_locator",
        "get_by_label",
        "get_by_placeholder",
        "get_by_role",
        "get_by_text",
        "go_back",
        "go_forward",
        "keep",
        "keyboard",
        "locator",
        "mouse",
        "reload",
        "screenshot",
        "snapshot",
        "wait_for_load_state",
        "wait_for_timeout",
    },
)
_UNSAFE_NAME_REFERENCES = frozenset(
    {
        "__import__",
        "breakpoint",
        "classmethod",
        "compile",
        "delattr",
        "dir",
        "eval",
        "exec",
        "getattr",
        "globals",
        "help",
        "input",
        "locals",
        "object",
        "open",
        "property",
        "setattr",
        "staticmethod",
        "super",
        "type",
        "vars",
    },
)


def _bounded_range(*args: int) -> range:
    """Return a small range suitable for one browser-operation program.

    The bridge runs beside the Creator API server rather than in the host
    Browser tool's disposable worker process.  Bounding a model-authored loop
    keeps accidental or prompt-injected CPU work from monopolising the event
    loop, where ``asyncio.wait_for`` cannot pre-empt synchronous Python.
    """
    value = range(*args)
    if len(value) > _MAX_RANGE_ITEMS:
        raise LiveOperationError(
            "range is limited to "
            f"{_MAX_RANGE_ITEMS} items in live-operation code",
        )
    return value


_SAFE_BUILTINS = {
    name: getattr(builtins, name)
    for name in (
        "Exception",
        "RuntimeError",
        "TypeError",
        "ValueError",
        "TimeoutError",
        "abs",
        "all",
        "any",
        "bool",
        "dict",
        "enumerate",
        "filter",
        "float",
        "int",
        "isinstance",
        "len",
        "list",
        "map",
        "max",
        "min",
        "next",
        "print",
        "repr",
        "reversed",
        "round",
        "set",
        "slice",
        "sorted",
        "str",
        "sum",
        "tuple",
        "zip",
    )
}
_SAFE_BUILTINS["range"] = _bounded_range


class LiveOperationError(RuntimeError):
    """The submitted browser code could not be run."""


class _SyncDeadlineExceeded(BaseException):
    """Raised inside model code once its execution deadline has passed.

    Derives from BaseException so model-level ``except Exception`` handlers
    cannot swallow the pre-emption; bare ``except:`` is rejected by the AST
    validator for the same reason.
    """


def _code_objects(code: Any) -> list[Any]:
    stack = [code]
    collected = []
    while stack:
        current = stack.pop()
        collected.append(current)
        for const in current.co_consts:
            if isinstance(const, types.CodeType):
                stack.append(const)
    return collected


class _MonitoringDeadline:
    """Pre-empt synchronous model code via per-code-object line events.

    ``asyncio.wait_for`` fires only when the event loop regains control, so a
    synchronous loop written by the model would otherwise run to completion
    regardless of the timeout. Line-level monitoring scoped to exactly the
    model's own code objects raises inside that code the moment the deadline
    passes, keeping the rest of the process untraced.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._deadlines: dict[Any, float] = {}
        self._tool_id: int | None = None

    def activate(self, codes: list[Any], deadline: float) -> None:
        monitoring = sys.monitoring
        with self._lock:
            tool = self._acquire_tool()
            for code in codes:
                self._deadlines[code] = deadline
                monitoring.set_local_events(
                    tool,
                    code,
                    monitoring.events.LINE,
                )

    def deactivate(self, codes: list[Any]) -> None:
        monitoring = sys.monitoring
        with self._lock:
            for code in codes:
                self._deadlines.pop(code, None)
                if self._tool_id is not None:
                    monitoring.set_local_events(self._tool_id, code, 0)

    def _acquire_tool(self) -> int:
        if self._tool_id is not None:
            return self._tool_id
        monitoring = sys.monitoring
        for candidate in range(6):
            try:
                monitoring.use_tool_id(candidate, "creator-live-operation")
            except ValueError:
                continue
            monitoring.register_callback(
                candidate,
                monitoring.events.LINE,
                self._on_line,
            )
            self._tool_id = candidate
            return candidate
        raise LiveOperationError(
            "no monitoring slot is available to enforce the live-operation "
            "deadline",
        )

    def _on_line(self, code: Any, line_number: int) -> Any:
        del line_number
        deadline = self._deadlines.get(code)
        if deadline is None:
            return sys.monitoring.DISABLE
        if time.monotonic() >= deadline:
            raise _SyncDeadlineExceeded()
        return None


class _SettraceDeadline:
    """Fallback pre-emption for interpreters without ``sys.monitoring``."""

    def __init__(self) -> None:
        self._deadlines: dict[Any, float] = {}
        self._installed = False

    def activate(self, codes: list[Any], deadline: float) -> None:
        for code in codes:
            self._deadlines[code] = deadline
        if not self._installed:
            sys.settrace(self._global_trace)
            self._installed = True

    def deactivate(self, codes: list[Any]) -> None:
        for code in codes:
            self._deadlines.pop(code, None)
        if not self._deadlines and self._installed:
            sys.settrace(None)
            self._installed = False

    def _global_trace(self, frame: Any, event: str, arg: Any) -> Any:
        del event, arg
        if frame.f_code in self._deadlines:
            return self._local_trace
        return None

    def _local_trace(self, frame: Any, event: str, arg: Any) -> Any:
        del arg
        if event == "line":
            deadline = self._deadlines.get(frame.f_code)
            if deadline is not None and time.monotonic() >= deadline:
                raise _SyncDeadlineExceeded()
        return self._local_trace


_SYNC_DEADLINE = (
    _MonitoringDeadline()
    if hasattr(sys, "monitoring")
    else _SettraceDeadline()
)


class _ActivePage:
    """The page recording defaults to: the one most recently opened.

    Tracking the real SDK page object here — rather than the last page id the
    control link happened to see — means ``recorder.start()`` works right
    after ``browser.open(...)``, before any other operation has touched the
    page. Reusing the link's memory made the first recording depend on an
    incidental perceive/act call in between.
    """

    def __init__(self) -> None:
        self.page: Any = None


def _validate_browser_url(url: str) -> str:
    """Allow ordinary web navigation and fail closed for local/script URLs."""
    normalized = str(url).strip()
    if not normalized or any(ord(char) < 32 for char in normalized):
        raise LiveOperationError(
            "browser URLs must be non-empty HTTP(S) URLs without control "
            "characters",
        )
    scheme = urlsplit(normalized).scheme.lower()
    if scheme not in {"http", "https"}:
        raise LiveOperationError(
            f"browser URL scheme {scheme or '[missing]'} is unavailable in "
            "live-operation code; use an absolute HTTP(S) URL",
        )
    return normalized


class _BoundPage:
    """Expose the documented Page surface and validate every navigation."""

    def __init__(self, page: Any) -> None:
        self._page = page

    async def goto(self, url: str) -> Any:
        return await self._page.goto(_validate_browser_url(url))

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_") or name not in _ALLOWED_PAGE_DELEGATIONS:
            raise LiveOperationError(
                f"page method or attribute {name!r} is unavailable in "
                "live-operation code",
            )
        return getattr(self._page, name)


class AgentRecorder:
    """The ``recorder`` name the model sees inside its own code.

    Start and stop are explicit on purpose: filming only what a step actually
    needs is what keeps takes free of dead footage, and keeps the model's
    later reasoning about that footage cheap.
    """

    def __init__(
        self,
        session: LiveBrowserSession,
        recorder: TakeRecorder,
        active_page: "_ActivePage",
    ) -> None:
        self._session = session
        self._recorder = recorder
        self._active_page = active_page

    async def start(self, page: Any = None, *, label: str = "") -> str:
        """Begin a take on ``page`` (default: the page just opened)."""
        target = page if page is not None else self._active_page.page
        if isinstance(target, _BoundPage):
            # The proxy is the model-facing value; CDP binding needs the SDK
            # page retained inside it. This does not expose the raw page back
            # to model code, whose AST cannot access private attributes.
            target = target._page  # pylint: disable=protected-access
        if target is None:
            raise LiveSessionError(
                "no page has been opened yet; open a page first: "
                'page = await browser.open("https://example.com")',
            )
        cdp = await self._session.cdp_session_for(target)
        return await self._recorder.start(cdp, label=label)

    async def stop(self) -> dict[str, Any]:
        """End the take and report what was filmed."""
        take = await self._recorder.stop()
        return {
            "take_id": take.take_id,
            "label": take.label,
            "summary": take.summary,
        }

    def is_recording(self) -> bool:
        """Whether a take is currently being filmed."""
        return self._recorder.recording


class LiveOperationRun:
    """One tool invocation: its takes, screenshots and printed output."""

    def __init__(self) -> None:
        self.takes: list[RecordedTake] = []
        self.screenshots: list[str] = []
        self.output: str = ""
        self.result_repr: str = ""


async def run_browser_code(
    code: str,
    *,
    run_root: Path,
    run_id: str,
    identity: str = "guest",
    fps: int = 25,
    max_width: int = 1280,
    max_height: int = 720,
    max_take_seconds: float = 300.0,
    timeout_seconds: float = 600.0,
) -> LiveOperationRun:
    """Run the model's browser code, returning everything it produced."""
    source = code.strip()
    if not source:
        raise LiveOperationError("code is empty")
    compiled = _compile(source)
    return await _run_browser_code_isolated(
        compiled,
        run_root=run_root,
        run_id=run_id,
        identity=identity,
        fps=fps,
        max_width=max_width,
        max_height=max_height,
        max_take_seconds=max_take_seconds,
        timeout_seconds=timeout_seconds,
    )


async def _run_browser_code_isolated(
    compiled: Any,
    *,
    run_root: Path,
    run_id: str,
    identity: str,
    fps: int,
    max_width: int,
    max_height: int,
    max_take_seconds: float,
    timeout_seconds: float,
) -> LiveOperationRun:
    """Run one invocation on links owned or explicitly selected by Creator."""
    workspace = workspace_dir(run_root, run_id)
    outcome = LiveOperationRun()
    recorder = TakeRecorder(
        workspace=workspace,
        fps=fps,
        max_width=max_width,
        max_height=max_height,
        max_duration_seconds=max_take_seconds,
    )
    links, owned_playwright = _recording_links(recorder)

    # The SDK Engine binds this explicit wrapper directly. Nothing is added to
    # QwenPaw's shared control-link registry, even briefly.
    try:
        session = await LiveBrowserSession.connect(
            links=links,
            identity=identity,
        )
        selected = session.control_link
        if not isinstance(selected, RecordingControlLink):
            await session.close()
            raise LiveOperationError(
                "the selected browser backend could not be isolated for "
                "recording",
            )
        active_page = _ActivePage()
        stdout = io.StringIO()
        try:
            namespace: dict[str, Any] = {
                "__name__": "__browser_use__",
                "Browser": _BoundBrowser(session, active_page),
                "recorder": AgentRecorder(session, recorder, active_page),
            }
            value = await asyncio.wait_for(
                _execute(
                    compiled,
                    namespace,
                    output=stdout,
                    deadline_seconds=timeout_seconds,
                ),
                timeout=timeout_seconds,
            )
            if value is not None:
                outcome.result_repr = _clip(repr(value), 2_000)
        except TimeoutError as exc:
            raise LiveOperationError(
                f"browser code exceeded {timeout_seconds:g} seconds",
            ) from exc
        except Exception as exc:  # noqa: BLE001 - model-code boundary
            raise LiveOperationError(
                "browser code failed: " f"{type(exc).__name__}: {exc}",
            ) from exc
        finally:
            # A take the model forgot to stop still becomes usable footage
            # rather than being discarded with the captured frames.
            with contextlib.suppress(Exception):
                await recorder.stop_if_recording()
            outcome.takes = recorder.takes
            outcome.screenshots = selected.screenshots
            outcome.output = _clip(stdout.getvalue(), _MAX_OUTPUT_CHARS)
            await session.close()
    finally:
        # This in-process filming provider belongs to the current event loop.
        # Closing it here prevents Playwright state from leaking into another
        # Creator workspace's loop, while the ordinary Browser runtime keeps
        # its own long-lived worker plane unchanged.
        with contextlib.suppress(Exception):
            await owned_playwright.close_all()
    return outcome


class _BoundBrowser:
    """Expose ``Browser.connect()`` while reusing this run's live session.

    Opening a page is intercepted so recording can default to it. Delegation
    is limited to the documented, run-safe orchestration surface; lifecycle
    methods such as ``close`` remain owned by this bridge's ``finally`` block.
    """

    def __init__(
        self,
        session: LiveBrowserSession,
        active_page: _ActivePage,
    ) -> None:
        self._session = session
        self._active_page = active_page

    async def connect(self, *, identity: str = "guest") -> "_BoundBrowser":
        del identity  # the run's session already carries the resolved identity
        return self

    async def open(self, url: str | None = None) -> Any:
        resolved_url = None if url is None else _validate_browser_url(url)
        page = await self._session.browser.open(resolved_url)
        self._active_page.page = page
        return _BoundPage(page)

    async def present(self, url: str | None = None) -> Any:
        resolved_url = None if url is None else _validate_browser_url(url)
        page = await self._session.browser.present(resolved_url)
        self._active_page.page = page
        return _BoundPage(page)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_") or name not in _ALLOWED_BROWSER_DELEGATIONS:
            raise LiveOperationError(
                f"browser method or attribute {name!r} is unavailable in "
                "live-operation code",
            )
        return getattr(self._session.browser, name)


def _recording_links(
    recorder: TakeRecorder,
) -> tuple[tuple[RecordingControlLink, ...], Any]:
    """Wrap available providers without changing QwenPaw's registry."""
    from qwenpaw.browser.control_link.playwright.adapter import (
        PlaywrightControlLink,
    )
    from qwenpaw.browser.runtime.links import registered_links

    owned_playwright = PlaywrightControlLink()
    wrapped: list[RecordingControlLink] = []
    seen: set[str] = set()
    # Prefer a provider created on this event loop. Other variants remain
    # available for explicitly selected Chrome/CDP identities, but the global
    # Playwright singleton is skipped once this variant has been wrapped.
    for inner in (owned_playwright, *registered_links()):
        variant = str(getattr(inner, "variant", ""))
        if not variant or variant in seen:
            continue
        seen.add(variant)
        wrapped.append(
            RecordingControlLink(
                inner,
                manifest_source=lambda: recorder.manifest,
                elapsed_ms=recorder.elapsed_ms,
            ),
        )
    if not wrapped:
        raise LiveOperationError("no browser control link is available")
    return tuple(wrapped), owned_playwright


def _compile(source: str) -> Any:
    """Compile module-level async code, mirroring the host browser tool."""
    try:
        tree = ast.parse(source, filename=_SOURCE_NAME, mode="exec")
        _ModelCodeValidator().visit(tree)
        return compile(
            tree,
            _SOURCE_NAME,
            "exec",
            flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT,
        )
    except SyntaxError as exc:
        raise LiveOperationError(f"code has a syntax error: {exc}") from exc


class _ModelCodeValidator(ast.NodeVisitor):
    """Keep agent code on the declared operation objects.

    Unlike the host Browser tool's disposable worker process, Creator runs
    beside API keys and Project state. Imports and private-object traversal
    would turn a website prompt injection into backend code execution, so this
    bridge exposes ordinary Python control flow but no process escape surface.

    Amplifying operators, oversized literals and deep loop nesting are also
    rejected so a single statement cannot allocate unbounded memory before
    the line-level deadline can pre-empt it. These caps reduce risk; the
    deadline in ``_execute`` is what bounds total synchronous work.
    """

    def __init__(self) -> None:
        self._node_count = 0
        self._loop_depth = 0

    def visit(self, node: ast.AST) -> None:
        self._node_count += 1
        if self._node_count > _MAX_AST_NODES:
            raise LiveOperationError(
                f"code is limited to {_MAX_AST_NODES} syntax nodes in "
                "live-operation code",
            )
        super().visit(node)

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        del node
        raise LiveOperationError(
            "imports are unavailable in live-operation code; Browser, "
            "desktop, and recorder are already in scope",
        )

    visit_ImportFrom = visit_Import

    def _reject_definition(self, kind: str) -> None:
        raise LiveOperationError(
            f"{kind} definitions are unavailable in live-operation code; "
            "use top-level await and bounded control flow with the provided "
            "Browser, desktop, and recorder objects",
        )

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        del node
        self._reject_definition("function")

    def visit_AsyncFunctionDef(  # noqa: N802
        self,
        node: ast.AsyncFunctionDef,
    ) -> None:
        del node
        self._reject_definition("async function")

    def visit_Lambda(self, node: ast.Lambda) -> None:  # noqa: N802
        del node
        self._reject_definition("lambda")

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        del node
        self._reject_definition("class")

    def visit_While(self, node: ast.While) -> None:  # noqa: N802
        del node
        raise LiveOperationError(
            "while loops are unavailable in live-operation code; use a "
            "bounded for loop or the Browser SDK's wait methods",
        )

    def _enter_loops(self, count: int, node: ast.AST) -> None:
        self._loop_depth += count
        if self._loop_depth > _MAX_LOOP_DEPTH:
            raise LiveOperationError(
                f"loops nest deeper than {_MAX_LOOP_DEPTH} levels in "
                "live-operation code; flatten the iteration",
            )
        self.generic_visit(node)
        self._loop_depth -= count

    def visit_For(self, node: ast.For) -> None:  # noqa: N802
        self._enter_loops(1, node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:  # noqa: N802
        self._enter_loops(1, node)

    def _visit_comprehension(self, node: Any) -> None:
        self._enter_loops(len(node.generators), node)

    visit_ListComp = _visit_comprehension  # noqa: N815
    visit_SetComp = _visit_comprehension  # noqa: N815
    visit_DictComp = _visit_comprehension  # noqa: N815
    visit_GeneratorExp = _visit_comprehension  # noqa: N815

    def visit_ExceptHandler(  # noqa: N802
        self,
        node: ast.ExceptHandler,
    ) -> None:
        if node.type is None:
            raise LiveOperationError(
                "bare except clauses are unavailable in live-operation "
                "code; catch a specific exception type",
            )
        self.generic_visit(node)

    @staticmethod
    def _is_sequence_literal(node: ast.AST) -> bool:
        if isinstance(node, (ast.List, ast.Tuple, ast.Set, ast.Dict)):
            return True
        if isinstance(node, ast.JoinedStr):
            return True
        return isinstance(node, ast.Constant) and isinstance(
            node.value,
            (str, bytes),
        )

    def _reject_amplifying_operator(
        self,
        op: ast.operator,
        *operands: ast.AST,
    ) -> None:
        if isinstance(op, (ast.Pow, ast.LShift)):
            raise LiveOperationError(
                "power and left-shift operators are unavailable in "
                "live-operation code",
            )
        if isinstance(op, ast.Mult) and any(
            self._is_sequence_literal(operand) for operand in operands
        ):
            raise LiveOperationError(
                "sequence repetition is unavailable in live-operation code",
            )

    def visit_BinOp(self, node: ast.BinOp) -> None:  # noqa: N802
        self._reject_amplifying_operator(node.op, node.left, node.right)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:  # noqa: N802
        if isinstance(node.op, ast.Mult):
            # `x *= n` cannot be typed statically, so a str/list target
            # would amplify memory in one bytecode op; reject the form.
            raise LiveOperationError(
                "augmented multiplication is unavailable in live-operation "
                "code",
            )
        self._reject_amplifying_operator(node.op, node.target, node.value)
        self.generic_visit(node)

    def _reject_oversized_literal(self, count: int) -> None:
        if count > _MAX_LITERAL_ELEMENTS:
            raise LiveOperationError(
                "container literals are limited to "
                f"{_MAX_LITERAL_ELEMENTS} elements in live-operation code",
            )

    def visit_List(self, node: ast.List) -> None:  # noqa: N802
        self._reject_oversized_literal(len(node.elts))
        self.generic_visit(node)

    visit_Tuple = visit_List  # noqa: N815
    visit_Set = visit_List  # noqa: N815

    def visit_Dict(self, node: ast.Dict) -> None:  # noqa: N802
        self._reject_oversized_literal(len(node.keys))
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:  # noqa: N802
        value = node.value
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and abs(value) > _MAX_NUMERIC_CONSTANT
        ):
            raise LiveOperationError(
                "numeric constants are limited to "
                f"{_MAX_NUMERIC_CONSTANT} in live-operation code",
            )
        if (
            isinstance(value, (str, bytes))
            and len(value) > _MAX_STRING_CONSTANT_CHARS
        ):
            raise LiveOperationError(
                "string constants are limited to "
                f"{_MAX_STRING_CONSTANT_CHARS} characters in "
                "live-operation code",
            )

    def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802
        if node.attr.startswith("_"):
            raise LiveOperationError(
                "private attributes are unavailable in live-operation code",
            )
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:  # noqa: N802
        if node.id.startswith("__") or node.id in _UNSAFE_NAME_REFERENCES:
            raise LiveOperationError(
                "dunder, reflection, and process names are unavailable in "
                "live-operation code",
            )


async def _execute(
    compiled: Any,
    namespace: dict[str, Any],
    *,
    output: io.StringIO | None = None,
    deadline_seconds: float | None = None,
) -> Any:
    started = time.monotonic()
    safe_builtins = dict(_SAFE_BUILTINS)
    if output is not None:

        def captured_print(
            *values: Any,
            sep: str = " ",
            end: str = "\n",
            flush: bool = False,
        ) -> None:
            builtins.print(*values, sep=sep, end=end, file=output)
            if flush:
                output.flush()

        safe_builtins["print"] = captured_print
    namespace.setdefault("__builtins__", safe_builtins)
    codes: list[Any] = []
    if deadline_seconds is not None:
        codes = _code_objects(compiled)
        _SYNC_DEADLINE.activate(codes, started + deadline_seconds)
    try:
        outcome = eval(
            compiled,
            namespace,
        )  # noqa: S307 - the model's own code
        if asyncio.iscoroutine(outcome):
            outcome = await outcome
    except _SyncDeadlineExceeded as exc:
        raise LiveOperationError(
            f"browser code exceeded {deadline_seconds:g} seconds of "
            "execution and was pre-empted",
        ) from exc
    finally:
        if codes:
            _SYNC_DEADLINE.deactivate(codes)
    logger.info(
        "live operation code finished in %.1fs",
        time.monotonic() - started,
    )
    return outcome


def _clip(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + f"\n… truncated at {limit} characters"


def collect_manifests(takes: list[RecordedTake]) -> list[TakeManifest]:
    return [take.manifest for take in takes]


__all__ = [
    "AgentRecorder",
    "LiveOperationError",
    "LiveOperationRun",
    "collect_manifests",
    "run_browser_code",
]
