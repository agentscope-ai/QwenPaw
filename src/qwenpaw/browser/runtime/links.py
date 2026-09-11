# -*- coding: utf-8 -*-
"""Variant-to-control-link registry."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Iterable

if TYPE_CHECKING:
    from .ports import ControlLink


_local: list["ControlLink"] = []
_external: Callable[[], Iterable["ControlLink"]] = lambda: ()


def register_local(link: "ControlLink", *, priority: bool = False) -> None:
    """Register a first-party control link, optionally ahead of defaults."""
    if priority:
        _local.insert(0, link)
    else:
        _local.append(link)


def unregister_local(link: "ControlLink") -> None:
    """Remove a temporary first-party control link from the registry."""
    try:
        _local.remove(link)
    except ValueError:
        pass


def bind_external(
    source: Callable[[], Iterable["ControlLink"]],
) -> None:
    """Bind a live source of externally contributed control links."""
    global _external
    _external = source


def registered_links() -> tuple["ControlLink", ...]:
    """Snapshot every currently registered control link."""
    return (*_local, *_external())


def link_for(variant: str) -> "ControlLink | None":
    """Return the current control link for a browser variant, if any."""
    for link in registered_links():
        if link is not None and getattr(link, "variant", None) == variant:
            return link
    return None


async def availability() -> dict[str, bool]:
    """Return the current provider facts for identity adjudication."""
    for link in registered_links():
        probe = getattr(link, "probe_availability", None)
        if callable(probe):
            return dict(await probe())
    return {
        variant: bool(
            link_for(variant) is not None and link_for(variant).is_available(),
        )
        for variant in ("chrome", "cdp", "playwright")
    }
