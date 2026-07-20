# -*- coding: utf-8 -*-
"""Session-keyed projection of raw provider observations."""

from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any

from ...errors import BrowserError, ErrorCategory
from ...sdk.execution_context import record_perception
from ...sdk.contracts import (
    ContextVersion,
    Coverage,
    CoverageGap,
    CurrentSurface,
    Observation,
    ObservedElement,
    Owner,
    ReadResult,
    ReadSegment,
    RegionSummary,
)

_CAVEAT = (
    "Caveat: this snapshot captures the accessibility tree plus visible DOM "
    "text; visual-only, off-screen, closed-shadow-root, and cross-iframe "
    "completeness is unverified. Never treat 'not found' as final: "
    "scroll or try another locator before concluding."
)


def _triage_value(value: str) -> str:
    """Fold opaque ``data:`` payloads into an honest observation handle."""
    if not value.startswith("data:"):
        return value
    header, _, payload = value.partition(",")
    mime = header[5:].split(";", 1)[0] or "unknown"
    size_kb = len(payload) / 1024.0
    label = "image " if mime.startswith("image/") else ""
    return f"[{label}data:{mime}, {size_kb:.1f}KB elided]"


def _triage_state(state: object) -> str:
    """Apply URI triage to the value portion of one AX state."""
    name, separator, value = str(state).partition("=")
    return f"{name}={_triage_value(value)}" if separator else name


def _has_information(node: Mapping[str, Any]) -> bool:
    """Return whether an AX node has user-meaningful locator evidence."""
    return bool(
        str(node.get("name", ""))
        or str(node.get("text", ""))
        or node.get("states")
        or node.get("attrs"),
    )


def _clean_tree(
    node: Mapping[str, Any],
) -> tuple[list[Mapping[str, Any]], int]:
    """Prune empty leaves and flatten anonymous single-child chains."""
    children: list[Mapping[str, Any]] = []
    omitted = 0
    for child in node.get("children") or []:
        if isinstance(child, Mapping):
            cleaned, child_omitted = _clean_tree(child)
            children.extend(cleaned)
            omitted += child_omitted

    if not _has_information(node):
        if not children:
            return [], omitted + 1
        if len(children) == 1:
            return children, omitted + 1

    return [{**node, "children": children}], omitted


def _capture_gap(examined: int) -> CoverageGap:
    """Describe the known limits of the tree and DOM text capture."""
    return CoverageGap(
        stage="CAPTURE",
        source="ax_tree",
        reason=(
            "visual-only, off-screen, closed-shadow-root, and cross-iframe "
            "content not verified"
        ),
        examined=examined,
        omitted=0,
    )


def _project_tree(node: Any) -> tuple[list[ObservedElement], str]:
    """Project an enriched AX/DOM tree into elements and annotated text."""
    elements: list[ObservedElement] = []
    lines: list[str] = []

    def render_attrs(current: Mapping[str, Any]) -> str:
        parts = [_triage_state(state) for state in current.get("states") or []]
        parts.extend(
            f"{key}={_triage_value(str(value))}"
            for key, value in (current.get("attrs") or {}).items()
        )
        return f" [{', '.join(parts)}]" if parts else ""

    def walk(current: Mapping[str, Any], depth: int = 0) -> None:
        role = str(current.get("role", ""))
        name = str(current.get("name", ""))
        text = str(current.get("text", ""))
        elements.append(
            ObservedElement(
                role=role,
                name=name,
                text=text,
            ),
        )
        lines.append(
            (
                f'{"  " * depth}- {role} "{name}"{render_attrs(current)}'
                f" text={json.dumps(text, ensure_ascii=False)}"
                if text and text != name
                else f'{"  " * depth}- {role} "{name}"{render_attrs(current)}'
            ).rstrip(),
        )
        for child in current.get("children") or []:
            if isinstance(child, Mapping):
                walk(child, depth + 1)

    omitted = 0
    if isinstance(node, Mapping):
        roots, omitted = _clean_tree(node)
        for root in roots:
            walk(root)
    if omitted:
        lines.append(
            "note: "
            f"{omitted} structural nodes without name, text, state, or "
            "attributes "
            "were omitted from this view",
        )
    return elements, "\n".join(lines)


def _project_ax_text(ax: Any) -> tuple[list[ObservedElement], str]:
    """Keep the chrome variant's legacy string observation compatible."""
    return [], str(ax or "")


class ObservationDomain:
    """Build shallow, explicit observations from raw session provider facts."""

    def __init__(
        self,
        link: Any,
        owner: Owner,
        page_id: str,
        engine: Any,
    ) -> None:
        self.link = link
        self._owner = owner
        self._page_id = page_id
        self.engine = engine

    def _params(self, **rest: Any) -> dict[str, Any]:
        """Build every provider request with this page's full identity."""
        return {
            "workspace_id": self._owner.workspace_id,
            "session_id": self._owner.session_id,
            "page_id": self._page_id,
            **rest,
        }

    async def snapshot(
        self,
        scope: str | None = None,
        query: str | None = None,
        cursor: str | None = None,
    ) -> Observation:
        """Return a complete skeleton observation with query count evidence."""
        record_perception()
        del cursor
        if scope is not None:
            raise BrowserError(
                category=ErrorCategory.FATAL,
                suggested_action="fatal",
                reason=(
                    "scope-limited snapshot is not available; call "
                    "snapshot() with no scope for the full page"
                ),
                detail=str(scope),
            )
        raw = await self.link.request(
            "capture_tree",
            self._params(),
        )
        elements, text = (
            _project_tree(raw.get("tree"))
            if "tree" in raw
            else _project_ax_text(raw.get("ax"))
        )
        match_count: int | None = None
        if query:
            match_count = (
                await self.engine.locator_for(
                    self._page_id,
                )
                .get_by_text(query)
                .count()
            )
        text = f"{text}\n\n{_CAVEAT}" if text else _CAVEAT
        return Observation(
            elements=tuple(elements),
            coverage=Coverage.PARTIAL,
            gaps=(_capture_gap(len(elements)),),
            context_version=ContextVersion(token=str(raw.get("url", ""))),
            cursor=None,
            text=text,
            match_count=match_count,
            coverage_note=_CAVEAT,
        )

    async def read(
        self,
        scope: str | None = None,
        query: str | None = None,
        cursor: str | None = None,
    ) -> ReadResult:
        """Return the full accessibility text as one skeleton read segment."""
        del scope, query, cursor
        raw = await self.link.request(
            "capture_tree",
            self._params(),
        )
        elements, text = (
            _project_tree(raw.get("tree"))
            if "tree" in raw
            else _project_ax_text(raw.get("ax"))
        )
        text = f"{text}\n\n{_CAVEAT}" if text else _CAVEAT
        return ReadResult(
            segments=(ReadSegment(kind="ax", text=text),),
            coverage=Coverage.PARTIAL,
            gaps=(_capture_gap(len(elements)),),
            cursor=None,
        )

    async def current_surface(self) -> CurrentSurface:
        """Return the current surface facts reported by the provider."""
        raw = await self.link.request(
            "current_surface",
            self._params(),
        )
        return CurrentSurface(
            url=str(raw.get("url", "")),
            title=str(raw.get("title", "")),
            page_id=self._page_id,
            load_state="load",
        )

    async def regions(
        self,
        scope: str | None = None,
    ) -> tuple[RegionSummary, ...]:
        """Return no region segmentation until the later observation SPEC."""
        del scope
        return ()
