# -*- coding: utf-8 -*-
"""Subprocess worker that owns Browser SDK execution and its backend."""

from __future__ import annotations

import ast
import asyncio
import builtins as _builtins
import contextlib
import io
import inspect
import socket
from types import CodeType
from typing import Any, Callable, Mapping, cast

from ..errors import (
    BrowserError,
    ErrorCategory,
    ErrorCause,
    ErrorClassification,
    classify_browser_error,
)
from ..governance.error_codes import BrowserErrorCode
from ..runtime.links import register_local
from ..runtime.ports import EventSink
from ..sdk.contracts import ActionResult, Observation, Owner
from ..sdk.execution_context import (
    ExecutionContext,
    get_execution_context,
    get_perception_count,
    reset_perception_count,
    reset_execution_context,
    set_execution_context,
)
from ..sdk.facade import Browser, list_cdp_targets
from .broker import Broker, BrokeredControlLink
from .wire import (
    ExecRequest,
    ExecResult,
    MAX_FRAME_BYTES,
    WIRE_PROTOCOL_VERSION,
    WireProtocolError,
    encode_frame_async,
    exec_request_from_payload,
    exec_result_payload,
    read_frame,
    spill_stdout,
)

_REMOTE_CONTEXT_CAPABILITIES = {
    "chrome": (frozenset({"profile"}), "profile"),
}
_DEFAULT_REMOTE_CONTEXT_CAPABILITY = (
    frozenset({"incognito", "profile"}),
    "incognito",
)


def _overflow_result(result: ExecResult) -> ExecResult:
    """Turn an unsendable result into a lossless, sendable one."""
    error: dict[str, Any] = {
        "category": "FATAL",
        "reason": "output_too_large",
        "detail": (
            f"browser output is {len(result.stdout.encode('utf-8'))} bytes, "
            f"above the {MAX_FRAME_BYTES}-byte single-frame limit"
        ),
        "teaching": (
            "Filter the text in Python (for example by line matching) and "
            "print only what you need."
        ),
    }
    if result.stdout:
        try:
            error["overflow_stdout_path"] = spill_stdout(
                result.request_id,
                result.stdout,
            )
        except OSError:
            error["teaching"] = (
                "Filter the text in Python and print only what you need; "
                "the full output could not be preserved."
            )
    else:
        error["reason"] = "result_too_large"
        error["detail"] = "the returned value exceeds the single-frame limit"
        error[
            "teaching"
        ] = "Return a small summary instead of the whole object."
    return ExecResult(request_id=result.request_id, error=error)


class RemoteControlLink:
    """Worker-side proxy for the Chrome ControlLink in the main process."""

    variant = "chrome"

    def __init__(self, writer: asyncio.StreamWriter | None) -> None:
        self._writer = writer
        self._pending: dict[str, asyncio.Future[Mapping[str, Any]]] = {}
        self._pending_approvals: dict[
            str,
            asyncio.Future[Mapping[str, Any]],
        ] = {}
        self._sinks: list[EventSink] = []
        self._send_lock = asyncio.Lock()
        self._reader_task: asyncio.Task[None] | None = None
        self._next_call_id = 0
        self._next_approval_id = 0

    def is_available(self) -> bool:
        return self._writer is not None

    def for_variant(self, variant: str) -> "_VariantRemoteControlLink":
        """Expose this one wire proxy under a resolved backend variant."""
        return _VariantRemoteControlLink(self, variant)

    def on_event(self, sink: EventSink) -> Callable[[], None]:
        self._sinks.append(sink)
        return lambda: self._sinks.remove(sink)

    async def start(self, reader: asyncio.StreamReader) -> None:
        """Start processing control replies and events from the main side."""
        if self._reader_task is None:
            self._reader_task = asyncio.create_task(self._read_loop(reader))

    async def request(
        self,
        method: str,
        params: Mapping[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        """Forward one semantic control request and await its call-id reply."""
        if self._writer is None:
            raise WireProtocolError(
                "remote Chrome control link is unavailable",
            )
        self._next_call_id += 1
        call_id = str(self._next_call_id)
        future: asyncio.Future[
            Mapping[str, Any]
        ] = asyncio.get_running_loop().create_future()
        self._pending[call_id] = future
        try:
            frame = await encode_frame_async(
                "ctrl_call",
                {
                    "call_id": call_id,
                    "method": method,
                    "params": dict(params),
                },
            )
            async with self._send_lock:
                self._writer.write(frame)
                await self._writer.drain()
            if timeout is None:
                return await future
            return await asyncio.wait_for(future, timeout)
        finally:
            self._pending.pop(call_id, None)

    async def approve(
        self,
        *,
        origin: str,
        method: str,
        params: dict[str, Any],
    ) -> Mapping[str, Any]:
        """Ask the trusted main process to adjudicate one side effect."""
        if self._writer is None:
            raise WireProtocolError("approval transport is unavailable")
        self._next_approval_id += 1
        request_id = f"approval-{self._next_approval_id}"
        future: asyncio.Future[
            Mapping[str, Any]
        ] = asyncio.get_running_loop().create_future()
        self._pending_approvals[request_id] = future
        try:
            frame = await encode_frame_async(
                "approval_request",
                {
                    "request_id": request_id,
                    "origin": origin,
                    "method": method,
                    "params": dict(params),
                },
            )
            async with self._send_lock:
                self._writer.write(frame)
                await self._writer.drain()
            return await future
        finally:
            self._pending_approvals.pop(request_id, None)

    async def _read_loop(self, reader: asyncio.StreamReader) -> None:
        try:
            while True:
                await self.handle_frame(await read_frame(reader))
        except (OSError, WireProtocolError) as exc:
            self._fail_pending(str(exc))

    async def handle_frame(  # pylint: disable=too-many-branches
        self,
        frame: Mapping[str, Any],
    ) -> None:
        """Dispatch one main-process control reply or event frame."""
        if frame.get("v") != WIRE_PROTOCOL_VERSION:
            raise WireProtocolError("wire protocol version mismatch")
        kind = frame.get("kind")
        payload = frame.get("payload")
        if not isinstance(payload, dict):
            raise WireProtocolError("invalid remote control payload")
        if kind == "ctrl_result":
            call_id = payload.get("call_id")
            if not isinstance(call_id, str):
                raise WireProtocolError("ctrl_result is missing call_id")
            future = self._pending.get(call_id)
            if future is None or future.done():
                return
            if "result" in payload and isinstance(payload["result"], dict):
                future.set_result(payload["result"])
                return
            error = payload.get("error")
            if isinstance(error, dict):
                browser_error = error.get("browser_error")
                if isinstance(browser_error, dict):
                    category_value = browser_error.get("category")
                    if not isinstance(category_value, str):
                        raise WireProtocolError(
                            "invalid browser_error category",
                        )
                    cause_value = browser_error.get("cause")
                    try:
                        rebuilt = BrowserError(
                            category=ErrorCategory(category_value),
                            cause=(
                                ErrorCause(cause_value)
                                if isinstance(cause_value, str)
                                else None
                            ),
                            suggested_action=str(
                                browser_error.get("suggested_action") or "",
                            ),
                            reason=str(browser_error.get("reason") or ""),
                            detail=str(browser_error.get("detail") or ""),
                        )
                    except ValueError as exc:
                        raise WireProtocolError(
                            "invalid browser_error classification",
                        ) from exc
                    future.set_exception(rebuilt)
                    return
                wire_error = WireProtocolError(
                    str(error.get("detail", "ctrl_call failed")),
                )
                wire_error.browser_error_code = str(
                    error.get("browser_error_code", ""),
                )
                future.set_exception(wire_error)
                return
            raise WireProtocolError("invalid ctrl_result payload")
        if kind == "event":
            for sink in list(self._sinks):
                sink(payload)
            return
        if kind == "approval_verdict":
            request_id = payload.get("request_id")
            if not isinstance(request_id, str):
                raise WireProtocolError(
                    "approval_verdict is missing request_id",
                )
            future = self._pending_approvals.get(request_id)
            if future is not None and not future.done():
                future.set_result(payload)
            return
        raise WireProtocolError(f"unexpected worker-side frame kind: {kind}")

    def _fail_pending(self, detail: str) -> None:
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(WireProtocolError(detail))
        for future in list(self._pending_approvals.values()):
            if not future.done():
                future.set_exception(WireProtocolError(detail))

    async def close(self) -> None:
        """Stop receiving remote traffic and close the worker socket writer."""
        if self._reader_task is not None:
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task
        self._fail_pending("remote Chrome control link closed")
        if self._writer is not None:
            self._writer.close()
            with contextlib.suppress(Exception):
                await self._writer.wait_closed()


class _VariantRemoteControlLink:
    """Variant-labelled view over the single worker-to-main proxy."""

    def __init__(self, remote: RemoteControlLink, variant: str) -> None:
        self._remote = remote
        self.variant = variant

    def is_available(self) -> bool:
        return self._remote.is_available()

    @property
    def supported_contexts(self) -> frozenset[str]:
        """Expose the selected backend's truthful context capability."""
        return _REMOTE_CONTEXT_CAPABILITIES.get(
            self.variant,
            _DEFAULT_REMOTE_CONTEXT_CAPABILITY,
        )[0]

    @property
    def default_context(self) -> str:
        """Provide Chrome's fail-closed automatic context fallback."""
        return _REMOTE_CONTEXT_CAPABILITIES.get(
            self.variant,
            _DEFAULT_REMOTE_CONTEXT_CAPABILITY,
        )[1]

    def on_event(self, sink: EventSink) -> Callable[[], None]:
        return self._remote.on_event(sink)

    async def probe_availability(self) -> dict[str, bool]:
        """Ask the main process for provider facts at decision time."""
        ctx = get_execution_context()
        owner = ctx.owner if ctx is not None else None
        result = await self._remote.request(
            "link_availability",
            {
                "variant": self.variant,
                "workspace_id": "" if owner is None else owner.workspace_id,
                "session_id": "" if owner is None else owner.session_id,
            },
        )
        return dict(result)

    async def request(
        self,
        method: str,
        params: Mapping[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        labelled = dict(params)
        labelled["variant"] = self.variant
        return await self._remote.request(method, labelled, timeout=timeout)


class BlockReturn(BaseException):
    """Carry the value of a module-level browser-code ``return``."""

    def __init__(self, value: object = None) -> None:
        super().__init__()
        self.value = value


class _ReturnRewriter(ast.NodeTransformer):
    """Turn only module-level returns into an uncatchable control signal."""

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        return node

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef

    def visit_Return(self, node: ast.Return) -> ast.AST:
        call = ast.Call(
            func=ast.Name(id="__qwenpaw_block_return__", ctx=ast.Load()),
            args=[node.value] if node.value is not None else [],
            keywords=[],
        )
        return ast.copy_location(ast.Raise(exc=call, cause=None), node)


class _ModuleReturnTrapChecker(ast.NodeVisitor):
    """Reject return shapes whose user handler can swallow the signal."""

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        del node

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef

    def visit_Try(self, node: ast.Try) -> None:
        finder = _ModuleReturnFinder()
        for statement in node.body:
            finder.visit(statement)
        if finder.found and node.handlers:
            raise BrowserError(
                category=ErrorCategory.FATAL,
                cause=ErrorCause.API_MISUSE,
                suggested_action=(
                    "Move the module-level return outside the try block."
                ),
                reason=(
                    "module-level return inside try/except is swallowed by "
                    "the wrapper"
                ),
            )
        self.generic_visit(node)


class _ModuleReturnFinder(ast.NodeVisitor):
    """Find a return without crossing into a nested lexical scope."""

    def __init__(self) -> None:
        self.found = False

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        del node

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef

    def visit_Return(self, node: ast.Return) -> None:
        del node
        self.found = True


def _check_module_return_swallow(module: ast.Module) -> None:
    """Keep module-level return control flow from being silently swallowed."""
    _ModuleReturnTrapChecker().visit(module)


def _prepare(code: str) -> tuple[CodeType, CodeType | None]:
    """Compile browser code for persistent-namespace execution."""
    module = ast.parse(code, filename="browser_code")
    _check_module_return_swallow(module)
    module = _ReturnRewriter().visit(module)
    eval_code = None
    if module.body and isinstance(module.body[-1], ast.Expr):
        tail = module.body.pop()
        expression = ast.Expression(tail.value)
        ast.fix_missing_locations(expression)
        eval_code = cast(
            CodeType,
            compile(
                expression,
                "browser_code",
                "eval",
                flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT,
            ),
        )
    ast.fix_missing_locations(module)
    exec_code = cast(
        CodeType,
        compile(
            module,
            "browser_code",
            "exec",
            flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT,
        ),
    )
    return exec_code, eval_code


def register_variant_proxies(remote_link: RemoteControlLink) -> None:
    """Register all main-process browser variants in this worker."""
    for variant in ("chrome", "cdp", "playwright"):
        register_local(
            BrokeredControlLink(
                remote_link.for_variant(variant),
                Broker(approval_client=remote_link.approve),
            ),
        )


def _render(value: object, *, perceived: bool = False) -> str:
    """Render SDK results before they cross the wire boundary."""
    if isinstance(value, Observation):
        return value.text or "(empty observation)"
    if isinstance(value, ActionResult):
        return value.evidence or "(no evidence)"
    if value is None:
        if perceived:
            return ""
        return (
            "This block performed no perception call (snapshot). If you "
            "acted on the page, re-perceive before claiming success."
        )
    return str(value)


_IDENTITY_ANCHOR = (
    "This is QwenPaw's builtin Browser SDK, not Playwright. "
    "The API surface is closed - the skill reference lists ALL of it; "
    "anything not listed does not exist."
)


def _public_surface(obj: object) -> str:
    """Return the SDK-visible public methods for a failed receiver."""
    names = (name for name in dir(type(obj)) if not name.startswith("_"))
    return ", ".join(sorted(names))


def _api_misuse_teaching(exc: BaseException) -> str:
    """Explain AttributeError/TypeError with identity and recovery context."""
    negation = str(exc)
    surface = ""
    obj = getattr(exc, "obj", None)
    name = getattr(exc, "name", None)
    if isinstance(exc, AttributeError) and obj is not None and name:
        negation = f"{type(obj).__name__} has no attribute {name!r}."
        surface = (
            f"\nAvailable on {type(obj).__name__.lower()}: "
            f"{_public_surface(obj)}."
        )
    return (
        f"{_IDENTITY_ANCHOR}\n{negation}{surface}\n"
        "Full reference: re-load the browser skill (Skill tool)."
    )


def _name_error_teaching(exc: NameError) -> str:
    """Explain that an earlier block prevented a name assignment."""
    missing = getattr(exc, "name", None) or "that name"
    return (
        f"{missing} is not defined in this namespace - usually a previous "
        "code block failed before assigning it. Re-run the assignment:\n"
        "browser = await Browser.connect()\npage = await browser.open(url)"
    )


def _deepest_frame_filename(exc: BaseException) -> str | None:
    """Return the innermost traceback filename for truthful attribution."""
    traceback = exc.__traceback__
    filename: str | None = None
    while traceback is not None:
        filename = traceback.tb_frame.f_code.co_filename
        traceback = traceback.tb_next
    return filename


def _is_model_code_error(exc: BaseException) -> bool:
    """Model code is compiled with the stable synthetic filename."""
    return _deepest_frame_filename(exc) == "browser_code"


def _internal_error_result(
    request: ExecRequest,
    stdout: io.StringIO,
    exc: BaseException,
) -> ExecResult:
    """Return an honest fatal outcome for Browser SDK implementation faults."""
    return ExecResult(
        request_id=request.request_id,
        stdout=stdout.getvalue(),
        error={
            "category": ErrorCategory.FATAL.value,
            "cause": ErrorCause.INTERNAL.value,
            "reason": "QwenPaw Browser SDK internal failure",
            "detail": f"{type(exc).__name__}: {exc}",
            "teaching": (
                "QwenPaw Browser SDK internal failure - retrying the "
                "same call will not help. Use a different listed API "
                "to finish the task, or report this step as blocked."
            ),
        },
    )


_SESSION_NAMESPACES: dict[str, dict[str, Any]] = {}
_BANNER_EMITTED: set[str] = set()


def _degradation_banner(request: ExecRequest, automatic_fallback: bool) -> str:
    """Return one honest backend-degradation banner per worker session."""
    if not automatic_fallback:
        return ""
    key = f"{request.owner_workspace_id}:{request.owner_session_id}"
    if key in _BANNER_EMITTED:
        return ""
    _BANNER_EMITTED.add(key)
    return (
        "[backend: playwright — isolated browser, NO user login state "
        "(chrome extension not connected)]\n"
    )


def _session_namespace(session_id: str) -> dict[str, Any]:
    """Return one session's persistent execution namespace."""
    namespace = _SESSION_NAMESPACES.get(session_id)
    if namespace is None:
        namespace = {
            "__builtins__": _builtins.__dict__,
            "Browser": Browser,
            "list_cdp_targets": list_cdp_targets,
        }
        _SESSION_NAMESPACES[session_id] = namespace
    return namespace


def _teaching_for(classification: ErrorClassification) -> str:
    """Turn stable transport classification into an actionable LLM hint."""
    if classification.category is ErrorCategory.REROUTE:
        return (
            "The Chrome extension connection changed or disconnected. "
            "Reconnect the browser session, then retry the operation."
        )
    if classification.category is ErrorCategory.RETRYABLE:
        return (
            "The browser did not confirm this request in time. Inspect the "
            "current page state before retrying to avoid duplicating effects."
        )
    return "The browser reported a typed failure; inspect the current state."


# pylint: disable=too-many-return-statements
# pylint: disable=too-many-branches
async def execute_request(
    request: ExecRequest,
) -> ExecResult:
    """Execute one request in the session namespace and return wire data."""
    namespace = _session_namespace(request.owner_session_id)
    try:
        exec_code, eval_code = _prepare(request.code)
    except BrowserError as exc:
        return ExecResult(
            request_id=request.request_id,
            error={
                "category": exc.category.value,
                "reason": exc.reason,
                "detail": exc.detail,
                "teaching": str(exc),
            },
        )
    except (SyntaxError, ValueError) as exc:
        return ExecResult(
            request_id=request.request_id,
            error={
                "category": "API_MISUSE",
                "reason": "code did not parse as Python",
                "detail": str(exc),
                "teaching": (
                    "This tool runs module-level async Python. Write it "
                    "like:\nbrowser = await Browser.connect()\npage = await "
                    "browser.open(url)\nobs = await page.snapshot()\n"
                    "re-load the browser skill (Skill tool) for the full API."
                ),
            },
        )
    owner = Owner(
        workspace_id=request.owner_workspace_id,
        session_id=request.owner_session_id,
    )
    token = set_execution_context(
        ExecutionContext(
            owner=owner,
            context=request.context,
        ),
    )
    stdout = io.StringIO()
    automatic_fallback = False
    try:
        with contextlib.redirect_stdout(stdout):
            reset_perception_count()
            namespace["__qwenpaw_block_return__"] = BlockReturn
            value = eval(exec_code, namespace)
            if inspect.isawaitable(value):
                value = await value
            if eval_code is not None:
                value = eval(eval_code, namespace)
                if inspect.isawaitable(value):
                    value = await value
            context = get_execution_context()
            automatic_fallback = bool(
                context is not None and context.automatic_identity_fallback,
            )
    except BlockReturn as returned:
        value = returned.value
    except BrowserError as exc:
        return ExecResult(
            request_id=request.request_id,
            stdout=stdout.getvalue(),
            error={
                "category": exc.category.value,
                "reason": exc.reason,
                "detail": exc.detail,
                "teaching": str(exc),
            },
        )
    except ImportError as exc:
        return ExecResult(
            request_id=request.request_id,
            stdout=stdout.getvalue(),
            error={
                "category": "API_MISUSE",
                "reason": "imported the SDK; Browser is already in scope",
                "detail": str(exc),
                "teaching": (
                    "Do not import the QwenPaw Browser SDK — Browser is "
                    "already available in your namespace. Delete the "
                    "import line and call await Browser.connect() "
                    "directly; open pages with await browser.open(url)."
                ),
            },
        )
    except NameError as exc:
        if not _is_model_code_error(exc):
            return _internal_error_result(request, stdout, exc)
        return ExecResult(
            request_id=request.request_id,
            stdout=stdout.getvalue(),
            error={
                "category": "API_MISUSE",
                "reason": "used a name not defined in this session",
                "detail": str(exc),
                "teaching": _name_error_teaching(exc),
            },
        )
    except (AttributeError, TypeError) as exc:
        if not _is_model_code_error(exc):
            return _internal_error_result(request, stdout, exc)
        return ExecResult(
            request_id=request.request_id,
            stdout=stdout.getvalue(),
            error={
                "category": "API_MISUSE",
                "reason": "called a method on the wrong object or type",
                "detail": str(exc),
                "teaching": _api_misuse_teaching(exc),
            },
        )
    except BaseException as exc:
        error_code = str(getattr(exc, "browser_error_code", ""))
        if error_code:
            try:
                classification = classify_browser_error(
                    BrowserErrorCode(error_code),
                )
            except ValueError:
                pass
            else:
                return ExecResult(
                    request_id=request.request_id,
                    stdout=stdout.getvalue(),
                    error={
                        "category": classification.category.value,
                        "reason": classification.suggested_action,
                        "detail": str(exc),
                        "teaching": _teaching_for(classification),
                    },
                )
        if not _is_model_code_error(exc):
            return _internal_error_result(request, stdout, exc)
        return ExecResult(
            request_id=request.request_id,
            stdout=stdout.getvalue(),
            error={
                "category": "FATAL",
                "reason": type(exc).__name__,
                "detail": str(exc),
                "teaching": f"unexpected error: {exc}",
            },
        )
    finally:
        reset_execution_context(token)
    return ExecResult(
        request_id=request.request_id,
        value=_degradation_banner(request, automatic_fallback)
        + _render(value, perceived=get_perception_count() > 0),
        stdout=stdout.getvalue(),
        handoff=(
            value
            if isinstance(value, dict) and value.get("status") == "handoff"
            else None
        ),
    )


def worker_main(sock: socket.socket) -> None:
    """Run the worker's async serve loop as a multiprocessing target."""
    asyncio.run(_serve(sock))


async def _serve(sock: socket.socket) -> None:
    """Receive requests until shutdown, then reclaim browser resources."""
    sock.setblocking(False)
    reader, writer = await asyncio.open_connection(sock=sock)
    remote_link = RemoteControlLink(writer)
    register_variant_proxies(remote_link)
    requests: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def receive() -> None:
        try:
            while True:
                frame = await read_frame(reader)
                if frame["kind"] == "exec_request":
                    await requests.put(frame["payload"])
                else:
                    await remote_link.handle_frame(frame)
        except (OSError, WireProtocolError):
            await requests.put(None)

    receiver = asyncio.create_task(receive())
    try:
        while True:
            payload = await requests.get()
            if payload is None:
                return
            try:
                request = exec_request_from_payload(payload)
                result = await execute_request(request)
            except Exception as exc:
                result = ExecResult(
                    request_id=getattr(request, "request_id", ""),
                    error={
                        "category": "FATAL",
                        "reason": type(exc).__name__,
                        "detail": str(exc),
                        "teaching": (
                            "The browser worker hit an unexpected internal "
                            "error; re-run your last step."
                        ),
                    },
                )
            try:
                frame = await encode_frame_async(
                    "exec_result",
                    exec_result_payload(result),
                )
            except WireProtocolError:
                frame = await encode_frame_async(
                    "exec_result",
                    exec_result_payload(_overflow_result(result)),
                )
            writer.write(frame)
            await writer.drain()
    finally:
        receiver.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await receiver
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
