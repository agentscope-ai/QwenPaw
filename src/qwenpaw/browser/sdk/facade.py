# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Browser orchestration facade for the Unified Browser SDK."""

from __future__ import annotations

import inspect
import asyncio
import uuid
from typing import TYPE_CHECKING, Callable, Literal, cast

from ..errors import BrowserError, ErrorCause, ErrorCategory
from ..runtime.engine import Engine
from .contracts import Owner, PageRef, SessionStatus
from .execution_context import get_execution_context

if TYPE_CHECKING:
    from .page import Page


async def list_cdp_targets(port=0, port_min=0, port_max=0, *, client=None):
    from ..control_link.cdp.discovery import list_cdp_targets as discover

    return await discover(port, port_min, port_max, client=client)


_ORCHESTRATION_API = (
    "connect",
    "open",
    "pages",
    "switch_page",
    "close_page",
    "session_status",
    "handoff",
    "present",
    "close",
)
_PAGE_API = (
    "goto",
    "go_back",
    "go_forward",
    "reload",
    "keep",
    "wait_for_load_state",
    "wait_for_timeout",
    "screenshot",
    "get_by_role",
    "get_by_text",
    "get_by_label",
    "get_by_placeholder",
    "locator",
    "frame_locator",
    "snapshot",
    "current_surface",
    "mouse",
    "keyboard",
)
_BLOCK_HEADER = (
    "QwenPaw Browser SDK — complete reference. This is QwenPaw's OWN "
    "internal\nSDK and this is the ENTIRE API; these are all the "
    "entrypoints. The SDK\nis already in scope as Browser — call the "
    "methods below directly. Write\nasync Python. Work in a loop: "
    "perceive → act → verify."
)
_BLOCK_EXAMPLE = (
    "# Copy this shape:\n"
    "browser = await Browser.connect()                  # connect once; "
    "reused all session\n"
    'page = await browser.open("https://example.com")   # open a page\n'
    "obs = await page.snapshot()                         # PERCEIVE — page "
    "text is obs.text\n"
    "if len(obs.text) < 6000:\n"
    "    print(obs.text)\n"
    "else:\n"
    "    # Large page: read selectively instead of dumping everything.\n"
    "    lines = [line for line in obs.text.splitlines()\n"
    '             if "keyword" in line]\n'
    '    print(f"{len(obs.text)} chars total; {len(lines)} matching lines:")\n'
    '    print("\\n".join(lines[:80]))\n'
    '# For a focused count, use: await page.snapshot(query="keyword")\n'
    'await page.get_by_role("textbox", name="Search").fill("laptop")   '
    "# ACT\n"
    'await page.get_by_role("button", name="Search").click()            '
    "# ACT\n"
    "obs = await page.snapshot()                         # VERIFY — "
    "re-perceive to confirm\n"
    'print("Verified; inspect obs.text with the selective pattern above.")'
)
_BLOCK_SESSION = (
    "Session state: this is a stateful session — variables you assign "
    "(browser,\npage) persist across calls, so connect once and reuse "
    "them. If a call\nreports the session was reset, re-run "
    "await Browser.connect()."
)
_BLOCK_CHROME = (
    "Chrome backend caveat: with backend=chrome you operate inside the "
    "user's\nreal browser. A session is a tab-ownership group — tabs are "
    "isolated per\nsession, but identity (cookies, logins, storage) is "
    "shared with the user's\nprofile and with every other session. Do "
    "not rely on session-level identity\nisolation on this backend."
)
_BLOCK_PLAYWRIGHT = (
    "page.get_by_* / page.locator(...) return a locator that mirrors a "
    "SUBSET\nof Playwright's Python locator API — the Playwright-shaped "
    "part of this\nSDK:\n"
    "  compose/scope (chainable): get_by_role/get_by_text/get_by_label/\n"
    "      get_by_placeholder, locator(sel), filter(...), nth(i), "
    "first, last (properties)\n"
    "  iframe scope: page.frame_locator(sel).locator(...) (one frame; "
    "no nested frames)\n"
    "  read (await): count()->int, inner_text()->str, "
    "text_content()->str|None,\n"
    "      all_text_contents()->list, get_attribute(name)->str|None,\n"
    "      input_value()->str, is_visible()->bool, is_enabled()->bool\n"
    "  act (await; returns a short evidence line — read .evidence): "
    "click(), fill(v),\n"
    "      type(t), press(key), check(), uncheck(), set_checked(b),\n"
    "      select_option(*v), hover(), dblclick(), scroll(),\n"
    "      focus(), blur(), clear(), wait_for(state), screenshot(),\n"
    '      bounding_box()->dict|None (viewport ["x"] ["y"] ["width"] '
    '["height"]; None when the element is not visible)\n'
    "  strict-mode\n      uniqueness is enforced — act only when the locator "
    "resolves to exactly\n      one element (use count() to check). "
    "element_handle / raw CDP unavailable."
)
_BLOCK_BACKENDS = (
    "Backend differences (chrome/cdp vs playwright): on chrome/cdp the\n"
    "accessible name is a heuristic (aria-labelledby > aria-label > alt >\n"
    "title > text content) - container elements may match\n"
    "get_by_role(name=) more broadly than under playwright, so\n"
    "strict-mode errors are more likely there; narrow with\n"
    "filter(has_text=) or a more specific role. is_enabled() reflects\n"
    "only the disabled property, not aria-disabled. press() supports a\n"
    "fixed key set: printable characters, Enter, Tab, Escape, Backspace,\n"
    "Delete, Arrow keys, Home/End/PageUp/PageDown, and\n"
    "Control/Shift/Alt/Meta combos - anything else fails with guidance.\n"
    "type() sets the value directly and fires an input event; editors that\n"
    "need real per-key events may not react - prefer fill() where possible."
)
_BLOCK_READING = (
    "Reading results (read these fields; the type names don't matter):\n"
    "  snapshot()        -> .text (page text), .match_count (when you pass "
    "query)\n"
    "  current_surface() -> .url, .title, .load_state\n"
    "  page refs         -> .id, .url, .title, .active\n"
    '  screenshot()      -> result dict; read ["path"]\n'
    '  bounding_box()    -> viewport ["x"] ["y"] ["width"] '
    '["height"]; None when the element is not visible\n'
    "  mouse.click()/keyboard.press() -> result dict; fields depend on the "
    "backend, so verify with snapshot()\n"
    "  actions           -> .evidence (a short line saying what happened)\n"
    "  locator reads return plain str/int/bool/list directly."
)
_BLOCK_LADDER = (
    "If a locator fails, step DOWN one rung (don't jump):\n"
    "  1. semantic  page.get_by_role/label/text            first choice\n"
    "  2. css       page.locator(css)                       role "
    "missing/unstable\n"
    "  3. coordinates use locator.bounding_box() first for an exact, "
    "low-cost viewport rectangle; use a screenshot to explore only when "
    "the element is absent from snapshot()\n"
    "For captcha/login/2FA or any human-only step: await "
    "browser.handoff(reason,\ninstructions) and stop — never automate "
    "them."
)
_RETURN_PHRASES = {
    "Observation": "observation (read .text; .match_count when you pass a "
    "query)",
    "CurrentSurface": "surface facts (.url, .title, .load_state)",
    "PageRef": "page ref (.id, .url, .title, .active)",
    "SessionStatus": "session status (.owner, .variant, .context, "
    ".connected)",
    "LocatorView": "locator",
    "FrameLocatorView": "frame locator",
    "_Input": "coordinate/keyboard input surface (see methods below)",
    "Page": "page",
    "Browser": "browser",
}


def _clean_type(text: str) -> str:
    text = text.strip().strip("'\"")
    if text.startswith("Literal[") and text.endswith("]"):
        inner = text[len("Literal[") : -1]
        parts = [part.strip().strip("'\"") for part in inner.split(",")]
        return "|".join(f'"{part}"' for part in parts)
    for class_name, phrase in _RETURN_PHRASES.items():
        text = text.replace(class_name, phrase)
    return text


def _render_return(annotation: object) -> str:
    if annotation is inspect.Signature.empty:
        return "none"
    text = str(annotation).strip().strip("'\"")
    for class_name, phrase in _RETURN_PHRASES.items():
        if class_name in text:
            return f"list of {phrase}" if text.startswith("list[") else phrase
    if text in ("None", "NoneType", ""):
        return "none"
    if text.startswith("dict"):
        return "a result dict"
    return text


def _render_method(prefix: str, name: str, member: object) -> list[str]:
    """Render a method or property from a static, descriptor-safe lookup."""
    if isinstance(member, property):
        getter = member.fget
        annotation = (
            inspect.Signature.empty
            if getter is None
            else inspect.signature(getter).return_annotation
        )
        header = f"{prefix}.{name} -> {_render_return(annotation)}"
        doc = inspect.getdoc(member) or ""
        return [header] + [
            f"    {line}" if line else "" for line in doc.splitlines()
        ]

    if isinstance(member, (staticmethod, classmethod)):
        member = member.__func__
    signature = inspect.signature(cast(Callable[..., object], member))
    pieces: list[str] = []
    star_emitted = False
    for param in signature.parameters.values():
        if param.name in ("self", "cls"):
            continue
        if param.kind is inspect.Parameter.KEYWORD_ONLY and not star_emitted:
            pieces.append("*")
            star_emitted = True
        annotation = (
            ""
            if param.annotation is inspect.Parameter.empty
            else _clean_type(str(param.annotation))
        )
        piece = param.name if not annotation else f"{param.name}: {annotation}"
        if param.default is not inspect.Parameter.empty:
            piece += (
                f' = "{param.default}"'
                if isinstance(param.default, str)
                else f" = {param.default!r}"
            )
        pieces.append(piece)
    awaited = "await " if inspect.iscoroutinefunction(member) else ""
    header = (
        f"{awaited}{prefix}.{name}({', '.join(pieces)}) "
        f"-> {_render_return(signature.return_annotation)}"
    )
    doc = inspect.getdoc(member) or ""
    return [header] + [
        f"    {line}" if line else "" for line in doc.splitlines()
    ]


class Browser:
    """Session, identity, and multi-page orchestration only."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def __repr__(self) -> str:
        ctx = get_execution_context()
        backend = ctx.resolved_backend if ctx is not None else "unknown"
        return (
            f"Browser(backend={backend}, "
            f"workspace={self._engine.session.workspace_id})"
        )

    @classmethod
    async def connect(  # pylint: disable=too-many-branches
        cls,
        *,
        identity: Literal["auto", "user", "avatar", "guest"] = "auto",
    ) -> "Browser":
        """Connect as an identity: user, avatar, guest, or auto.

        ``auto`` picks ``user`` when Chrome is connected, otherwise ``guest``.
        An unavailable explicit identity raises instead of substituting.
        """
        ctx = get_execution_context()
        if ctx is not None and ctx.browser is not None:
            active = ctx.browser._engine.session.identity
            if identity in ("auto", active):
                return ctx.browser
            raise BrowserError(
                category=ErrorCategory.RETRYABLE,
                cause=ErrorCause.API_MISUSE,
                suggested_action=(
                    "Close the current browser first: "
                    "await browser.close(), then reconnect: "
                    f"await Browser.connect(identity='{identity}')"
                ),
                reason="another browser identity is already active",
                detail=(
                    f"active identity is '{active}', requested '{identity}'"
                ),
            )
        if ctx is not None and ctx.browser_connecting is not None:
            browser = await ctx.browser_connecting
            active = browser._engine.session.identity
            if identity in ("auto", active):
                return browser
            raise BrowserError(
                category=ErrorCategory.RETRYABLE,
                cause=ErrorCause.API_MISUSE,
                suggested_action=(
                    "Close the current browser first: "
                    "await browser.close(), then reconnect: "
                    f"await Browser.connect(identity='{identity}')"
                ),
                reason="another browser identity is already active",
                detail=(
                    f"active identity is '{active}', requested '{identity}'"
                ),
            )
        owner = (
            ctx.owner
            if ctx is not None
            else Owner(
                workspace_id=uuid.uuid4().hex,
                session_id=uuid.uuid4().hex,
            )
        )
        connecting = (
            asyncio.get_running_loop().create_future()
            if ctx is not None
            else None
        )
        if ctx is not None:
            ctx.browser_connecting = connecting
        try:
            browser = cls(
                await Engine.connect(
                    identity=identity,
                    owner=owner,
                ),
            )
            if ctx is not None:
                if ctx.browser is not None:
                    browser = ctx.browser
                else:
                    ctx.browser = browser
                if connecting is not None and not connecting.done():
                    connecting.set_result(browser)
            return browser
        except Exception as exc:
            if connecting is not None and not connecting.done():
                connecting.set_exception(exc)
            raise
        finally:
            if ctx is not None and ctx.browser_connecting is connecting:
                ctx.browser_connecting = None

    async def close(self) -> None:
        """Close this session's browser and release its context."""
        await self._engine.close()
        ctx = get_execution_context()
        if ctx is not None:
            ctx.browser = None

    async def handoff(
        self,
        reason: str,
        instructions: str = "",
    ) -> dict[str, str]:
        """Hand a step back to a human (captcha, login, 2FA).

        Pass a short reason and instructions; the run stops on this signal —
        never automate these flows. The active cycle-scoped page is retained
        for one extra response cycle after the handoff.
        """
        if self._engine.is_headless():
            raise BrowserError(
                category=ErrorCategory.ASK_HUMAN,
                suggested_action=(
                    "Switch to a headed browser session by setting "
                    "config.browser.headless=false."
                ),
                reason="cannot hand off in a headless session",
                detail="no visible window for a human to take over",
            )
        if self._engine.session.page_id:
            await self._engine._carry_over(
                self._engine.session.page_id,
                cycles=2,
            )
        return {
            "status": "handoff",
            "reason": reason,
            "instructions": instructions,
        }

    async def session_status(self) -> SessionStatus:
        """Report the owner, variant, context, and connected state."""
        return self._engine.session_status()

    async def pages(self) -> list[PageRef]:
        """List open pages with URL, title, and active-state details."""
        return await self._engine.pages()

    async def open(self, url: str | None = None) -> "Page":
        """Open a page at ``url`` and return it.

        Reuses this session's active page when one exists; otherwise a
        new page is created. Pages are released when the response cycle ends;
        start each cycle by calling ``open(url)`` again.
        """
        from .page import Page

        page = await self._engine.open(url)
        return Page(self._engine, page.id)

    async def present(self, url: str | None = None) -> "Page":
        """Open a page retained for the chat lifetime."""
        from .page import Page

        page = await self._engine.present(url)
        return Page(self._engine, page.id)

    async def switch_page(self, page: PageRef) -> None:
        """Make the given page ref active for later operations."""
        await self._engine.switch_page(page)

    async def close_page(self, page: PageRef) -> None:
        """Close the given page ref in this session."""
        await self._engine.close_page(page)


def _build_manual_text() -> str:
    """Build the Browser SDK reference for materialization at build time."""
    from .page import Page

    lines: list[str] = [
        _BLOCK_HEADER,
        "",
        _BLOCK_EXAMPLE,
        "",
        _BLOCK_SESSION,
        "",
        _BLOCK_CHROME,
        "",
    ]
    lines.append("browser (orchestration):")
    for name in _ORCHESTRATION_API:
        member = inspect.getattr_static(Browser, name)
        prefix = (
            "Browser"
            if isinstance(member, (staticmethod, classmethod))
            else "browser"
        )
        lines += _render_method(prefix, name, member)
    lines.append("")
    lines.append("page (operation):")
    for name in _PAGE_API:
        lines += _render_method(
            "page",
            name,
            inspect.getattr_static(Page, name),
        )
    lines += [
        "",
        _BLOCK_PLAYWRIGHT,
        "",
        _BLOCK_BACKENDS,
        "",
        _BLOCK_READING,
        "",
        _BLOCK_LADDER,
    ]
    return "\n".join(lines)
