# -*- coding: utf-8 -*-
"""Provider- and engine-independent Unified Browser SDK contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

# LocatorView deliberately exposes the complete SDK facade while delegating
# through the execution engine's private protocol.
# pylint: disable=protected-access,too-many-public-methods


class Coverage(StrEnum):
    """Completeness of one browser observation."""

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class ActionLevel(StrEnum):
    """Internal-only action receipt levels; not surfaced to the LLM."""

    DISPATCHED = "DISPATCHED"
    RECEIVED = "RECEIVED"


class Variant(StrEnum):
    """Which browser mechanism is being controlled (ADR D4)."""

    PLAYWRIGHT = "playwright"
    CHROME = "chrome"
    CDP = "cdp"


class Context(StrEnum):
    """Whether a browser identity is persistent, independent of variant."""

    AUTO = "auto"
    INCOGNITO = "incognito"
    PROFILE = "profile"


@dataclass(frozen=True)
class ContextVersion:
    """Opaque version stamp for one session-context observation."""

    token: str


@dataclass(frozen=True)
class LocatorStep:
    """One replayable operation in a lazy locator chain."""

    method: str
    args: tuple[Any, ...] = ()
    kwargs: tuple[tuple[str, Any], ...] = ()


class LocatorView:
    """Restricted, lazy, chainable projection of a Playwright locator."""

    __slots__ = ("_engine", "spec")

    def __init__(
        self,
        engine: Any = None,
        spec: tuple[LocatorStep, ...] = (),
    ) -> None:
        self._engine = engine
        self.spec = tuple(spec)

    def _extend(self, method: str, *args: Any, **kwargs: Any) -> "LocatorView":
        step = LocatorStep(method, tuple(args), tuple(sorted(kwargs.items())))
        return LocatorView(self._engine, self.spec + (step,))

    def get_by_role(
        self,
        role: str,
        *,
        name: str | None = None,
    ) -> "LocatorView":
        return self._extend("get_by_role", role, name=name)

    def get_by_text(self, text: str) -> "LocatorView":
        return self._extend("get_by_text", text)

    def get_by_label(self, text: str) -> "LocatorView":
        return self._extend("get_by_label", text)

    def get_by_placeholder(self, text: str) -> "LocatorView":
        return self._extend("get_by_placeholder", text)

    def locator(self, selector: str) -> "LocatorView":
        return self._extend("locator", selector)

    def filter(self, *, has_text: str) -> "LocatorView":
        """Keep only elements whose text contains ``has_text``.

        Matching is case-insensitive on every backend. This is the only
        filter this SDK supports; other Playwright filter options
        (``has``, ``has_not``, ...) do not exist here.
        """
        return self._extend("filter", has_text=has_text)

    def nth(self, index: int) -> "LocatorView":
        return self._extend("nth", index)

    @property
    def first(self) -> "LocatorView":
        return self._extend("first")

    @property
    def last(self) -> "LocatorView":
        return self._extend("last")

    async def count(self) -> int:
        return await self._engine._count(self.spec)

    async def _read(self, prop: str, *args: Any) -> Any:
        return await self._engine._read(self.spec, prop, *args)

    async def all_text_contents(self) -> list[str]:
        return await self._read("all_text_contents")

    async def text_content(self) -> str | None:
        return await self._read("text_content")

    async def inner_text(self) -> str:
        return await self._read("inner_text")

    async def is_visible(self) -> bool:
        return await self._read("is_visible")

    async def is_enabled(self) -> bool:
        return await self._read("is_enabled")

    async def get_attribute(self, name: str) -> str | None:
        return await self._read("get_attribute", name)

    async def input_value(self) -> str:
        return await self._read("input_value")

    async def wait_for(
        self,
        state: str = "visible",
        *,
        timeout: float = 30_000,
    ) -> None:
        """Wait until this locator reaches ``state`` or times out."""
        await self._engine._locator_wait_for(self.spec, state, timeout)

    async def _do(self, action: str, **params: Any) -> "ActionResult":
        return await self._engine._locator_action(self.spec, action, **params)

    async def click(self) -> "ActionResult":
        """Dispatch a click event.

        Confirm its intended effect with ``page.snapshot()``; returned
        evidence confirms only dispatch.
        """
        return await self._do("click")

    async def fill(self, value: str) -> "ActionResult":
        return await self._do("fill", value=value)

    async def type(self, text: str) -> "ActionResult":
        return await self._do("type_text", text=text)

    async def press(self, key: str) -> "ActionResult":
        return await self._do("press_key", key=key)

    async def check(self) -> "ActionResult":
        return await self._do("set_checked", checked=True)

    async def uncheck(self) -> "ActionResult":
        return await self._do("set_checked", checked=False)

    async def select_option(self, *values: str) -> "ActionResult":
        return await self._do("select_option", values=list(values))

    async def hover(self) -> "ActionResult":
        return await self._do("hover")

    async def dblclick(self) -> "ActionResult":
        """Dispatch a double-click.

        Confirm its intended effect with ``page.snapshot()``; returned
        evidence confirms only dispatch.
        """
        return await self._do("double_click")

    async def scroll(self) -> "ActionResult":
        return await self._do("scroll")

    async def focus(self) -> "ActionResult":
        """Focus this locator's unique element."""
        return await self._do("focus")

    async def blur(self) -> "ActionResult":
        """Remove focus from this locator's unique element."""
        return await self._do("blur")

    async def clear(self) -> "ActionResult":
        """Clear the value of this locator's unique input or textarea."""
        return await self._do("clear")

    async def screenshot(self) -> dict[str, str]:
        """Capture this locator's bounding rectangle to a workspace PNG."""
        return await self._engine._locator_screenshot(self.spec)

    async def bounding_box(self) -> dict[str, float] | None:
        """Return viewport ``x/y/width/height`` or ``None`` when hidden."""
        return await self._engine._locator_bounding_box(self.spec)

    async def set_checked(self, checked: bool) -> "ActionResult":
        return await self._do("set_checked", checked=checked)


class FrameLocatorView(LocatorView):
    """A lazy locator rooted in one iframe selected from the top document."""

    __slots__ = ()

    def __init__(self, engine: Any, selector: str) -> None:
        super().__init__(
            engine,
            (LocatorStep("frame_locator", (selector,), ()),),
        )


@dataclass(frozen=True)
class ObservedElement:
    """A safe, provider-neutral element summary."""

    role: str
    name: str
    text: str = ""
    ref_id: str | None = None


@dataclass(frozen=True)
class CoverageGap:
    """An explicit reason why an observation cannot be complete."""

    stage: Literal["CAPTURE", "SELECTION", "DELIVERY"]
    source: str
    reason: str
    examined: int
    omitted: int
    cursor: str | None = None
    frame: str | None = None
    requested: int | None = None
    effective: int | None = None


@dataclass(frozen=True)
class Observation:
    """A structural page observation with explicit evidence boundaries."""

    elements: tuple[ObservedElement, ...]
    coverage: Coverage
    gaps: tuple[CoverageGap, ...]
    context_version: ContextVersion
    cursor: str | None
    text: str
    match_count: int | None = None
    coverage_note: str = ""


@dataclass(frozen=True)
class ReadSegment:
    """One readable segment returned from a browser surface."""

    kind: str
    text: str


@dataclass(frozen=True)
class ReadResult:
    """Read output and its coverage evidence."""

    segments: tuple[ReadSegment, ...]
    coverage: Coverage
    gaps: tuple[CoverageGap, ...]
    cursor: str | None


@dataclass(frozen=True)
class CurrentSurface:
    """The current browser page summary."""

    url: str
    title: str
    page_id: str
    load_state: str


@dataclass(frozen=True)
class RegionSummary:
    """Summary of a browser region exposed to the caller."""

    kind: str
    boundary: str
    accessible: bool


@dataclass(frozen=True)
class DialogInfo:
    """A pending browser dialog exposed as raw mechanism information."""

    kind: str
    message: str


@dataclass(frozen=True)
class FileChooserInfo:
    """A pending file chooser exposed as raw mechanism information."""

    multiple: bool


@dataclass(frozen=True)
class ActionResult:
    """Evidence level and pending side effects of one browser action."""

    level: ActionLevel
    evidence: str
    pending_dialog: DialogInfo | None = None
    pending_file_chooser: FileChooserInfo | None = None


@dataclass(frozen=True)
class CapabilityVerdict:
    """A declared capability answer without executing browser behavior."""

    value: Literal["yes", "no", "blocked"]
    reason: str


@dataclass(frozen=True)
class Owner:
    """Execution identity: workspace profile plus session-context key."""

    workspace_id: str
    session_id: str

    def is_valid(self) -> bool:
        """Return whether this owner can cross the broker boundary."""
        return bool(self.workspace_id and self.session_id)


@dataclass(frozen=True)
class PageRef:
    """A safe reference to one page in a session-context."""

    id: str
    url: str
    title: str
    active: bool


@dataclass(frozen=True)
class SessionStatus:
    """Connection state for one browser session-context."""

    owner: Owner
    variant: Variant
    context: Context
    identity: str
    connected: bool


@dataclass(frozen=True)
class ResourceHandle:
    """Opaque handle to a provider resource."""

    id: str


@dataclass(frozen=True)
class NetworkResponse:
    """A normalized network response summary."""

    status: int
    url: str
    headers: dict[str, str]


@dataclass(frozen=True)
class Condition:
    """A declarative condition consumed by the later semantic runtime."""

    kind: str
    params: dict[str, Any] = field(default_factory=dict)
