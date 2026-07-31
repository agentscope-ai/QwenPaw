# -*- coding: utf-8 -*-
"""Single-axis browser identity adjudication (user | avatar | guest)."""

from dataclasses import dataclass

_ENGINE_VARIANT = {
    "auto": "playwright",
    "launch": "playwright",
    "managed_cdp": "cdp",
    "connect_cdp": "cdp",
}


@dataclass(frozen=True)
class IdentityResolution:
    """The identity decision and concrete execution requirements."""

    requested: str
    identity: str
    source: str
    variant: str
    context: str


def resolve_identity(
    *,
    model_identity: str,
    config_identity: str,
    chrome_available: bool,
    engine_backend: str,
) -> IdentityResolution:
    """Adjudicate identity once: model > config > auto rule."""
    if model_identity != "auto":
        identity, source = model_identity, "model"
    elif config_identity != "auto":
        identity, source = config_identity, "config"
    else:
        identity = "user" if chrome_available else "guest"
        source = "auto"
    engine = _ENGINE_VARIANT.get(engine_backend, "playwright")
    variant, context = {
        "user": ("chrome", "profile"),
        "avatar": (engine, "profile"),
        "guest": (engine, "incognito"),
    }[identity]
    return IdentityResolution(
        requested=model_identity,
        identity=identity,
        source=source,
        variant=variant,
        context=context,
    )
