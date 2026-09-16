# -*- coding: utf-8 -*-
"""A control link that records what the agent did, without changing the SDK.

Every SDK operation reaches the browser as one raw wire request, so wrapping
that boundary captures the facts a take needs — which action, at which
instant, over which rectangle — while the SDK above stays untouched: the
model writes ordinary Browser SDK code and carries no recording burden.

Only operations that change the screen are treated as facts. Reads and
snapshots pass through unrecorded so that perceiving a page never inflates
the manifest of a take.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Mapping, Sequence

from .manifest import ActionFact, BoundingBox

logger = logging.getLogger(__name__)

# Wire verbs that visibly act on the page. ``locator_action`` carries its own
# verb in ``action``; the rest are self-describing.
_ACTION_METHOD = "locator_action"
_NAVIGATION_METHODS = frozenset(
    {"navigate", "reload", "go_back", "go_forward"},
)
_INPUT_METHOD = "input"
_SCREENSHOT_METHODS = frozenset({"screenshot", "locator_screenshot"})
# A pre-action rectangle must not become the reason an operation fails, so the
# probe is short and its failure is simply "no coordinates for this fact".
# Wire timeouts are milliseconds, matching the provider's own action budget.
_BBOX_PROBE_TIMEOUT_MS = 4_000.0


class RecordingControlLink:
    """Wrap one control link, recording action facts while a take runs."""

    def __init__(
        self,
        inner: Any,
        *,
        manifest_source: Callable[[], Any],
        elapsed_ms: Callable[[], int],
    ) -> None:
        self._inner = inner
        self._manifest_source = manifest_source
        self._elapsed_ms = elapsed_ms
        self._last_page_id: str = ""
        self._screenshots: list[str] = []

    # ─── ControlLink surface ────────────────────────────────────────

    @property
    def variant(self) -> str:
        return str(getattr(self._inner, "variant", "playwright"))

    @property
    def inner(self) -> Any:
        """The provider owned by this run-scoped decorator."""
        return self._inner

    def is_available(self) -> bool:
        return bool(self._inner.is_available())

    def on_event(self, sink: Any) -> Callable[[], None]:
        return self._inner.on_event(sink)

    def __getattr__(self, name: str) -> Any:
        """Delegate everything else, including provider-owned internals."""
        return getattr(self._inner, name)

    async def request(
        self,
        method: str,
        params: Mapping[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        """Forward one wire request, recording it when a take is running."""
        page_id = str(params.get("page_id") or "")
        if page_id:
            self._last_page_id = page_id
        manifest = self._manifest_source()
        if manifest is None:
            result = await self._inner.request(method, params, timeout=timeout)
            self._remember_screenshot(method, result)
            return result

        op = _operation_name(method, params)
        if op is None:
            result = await self._inner.request(method, params, timeout=timeout)
            self._remember_screenshot(method, result)
            return result

        bbox = await self._probe_bbox(method, params)
        started_ms = self._elapsed_ms()
        failed = False
        try:
            result = await self._inner.request(method, params, timeout=timeout)
        except BaseException:
            failed = True
            raise
        finally:
            current = self._manifest_source()
            ended_ms = self._elapsed_ms()
            if current is manifest:
                manifest.record(
                    ActionFact(
                        op=op,
                        t_start_ms=started_ms,
                        t_end_ms=max(ended_ms, started_ms),
                        target=_target_description(method, params),
                        bbox=bbox,
                        failed=failed,
                    ),
                )
            elif manifest.duration_ms and started_ms < manifest.duration_ms:
                # The hard duration watchdog can finish while an operation is
                # in flight. Keep the visible portion of that action, bounded
                # to the media that was actually written.
                manifest.record(
                    ActionFact(
                        op=op,
                        t_start_ms=started_ms,
                        t_end_ms=manifest.duration_ms,
                        target=_target_description(method, params),
                        bbox=bbox,
                        failed=failed,
                    ),
                )
        self._remember_screenshot(method, result)
        return result

    # ─── recording helpers ─────────────────────────────────────────

    @property
    def last_page_id(self) -> str:
        """The page the agent operated most recently, for filming."""
        return self._last_page_id

    @property
    def screenshots(self) -> list[str]:
        """Paths of images the agent captured during this run."""
        return list(self._screenshots)

    async def _probe_bbox(
        self,
        method: str,
        params: Mapping[str, Any],
    ) -> BoundingBox | None:
        """Read the target rectangle before the action changes the page.

        Afterwards is too late: a click that navigates leaves nothing to
        measure, which is exactly the case emphasis needs coordinates for.
        """
        if method != _ACTION_METHOD or "spec" not in params:
            return None
        # A locator scroll targets the scroll container (often ``body``), not
        # a point the user acted on.  Its box can be the full document and
        # produce locations many screens outside the captured viewport, which
        # is actively misleading to later motion-design placement.
        if str(params.get("action") or "") == "scroll":
            return None
        probe = {
            key: value
            for key, value in params.items()
            if key in {"workspace_id", "session_id", "page_id", "spec"}
        }
        try:
            raw = await self._inner.request(
                "locator_bounding_box",
                probe,
                timeout=_BBOX_PROBE_TIMEOUT_MS,
            )
        except BaseException:  # noqa: BLE001 - facts are best-effort
            logger.debug("bbox probe failed", exc_info=True)
            return None
        return BoundingBox.from_raw(
            raw.get("value") if isinstance(raw, Mapping) else None,
        )

    def _remember_screenshot(self, method: str, result: Any) -> None:
        if method not in _SCREENSHOT_METHODS:
            return
        path = result.get("path") if isinstance(result, Mapping) else None
        if isinstance(path, str) and path and path not in self._screenshots:
            self._screenshots.append(path)


def _operation_name(method: str, params: Mapping[str, Any]) -> str | None:
    """Name the recorded operation, or ``None`` when it changes nothing."""
    if method == _ACTION_METHOD:
        action = str(params.get("action") or "").strip()
        return action or "action"
    if method in _NAVIGATION_METHODS:
        return method
    if method == _INPUT_METHOD:
        kind = str(params.get("kind") or "input")
        action = str(params.get("action") or "")
        return f"{kind}_{action}".strip("_")
    return None


def _target_description(method: str, params: Mapping[str, Any]) -> str:
    """Describe the operation target in the model's own vocabulary."""
    if method == "navigate":
        return str(params.get("url") or "")
    if method == _ACTION_METHOD:
        return _spec_description(params.get("spec"))
    return ""


def _spec_description(spec: Any) -> str:
    """Render a locator spec back into the call that produced it."""
    if not isinstance(spec, Sequence):
        return ""
    parts: list[str] = []
    for step in spec:
        if not isinstance(step, Mapping):
            continue
        name = str(step.get("method") or "")
        if not name:
            continue
        args = [_render_value(item) for item in step.get("args") or ()]
        for pair in step.get("kwargs") or ():
            if not isinstance(pair, Sequence) or len(pair) != 2:
                continue
            # Unset optional arguments are noise in a fact the model reads.
            if pair[1] is None:
                continue
            args.append(f"{pair[0]}={_render_value(pair[1])}")
        parts.append(f"{name}({', '.join(args)})")
    return ".".join(parts)[:200]


def _render_value(value: Any) -> str:
    if isinstance(value, str):
        return f'"{value}"'
    return str(value)


__all__ = ["RecordingControlLink"]
