# -*- coding: utf-8 -*-
"""Discover plugin resources for built-in terminal commands."""


import click


def ensure_resources(capability):
    """Register relevant definitions without activating backend resources."""
    ctx = click.get_current_context(silent=True)
    if ctx is None:
        return
    from .plugin_cli import catalog_for
    from .plugin_session import session_for

    root = ctx.find_root()
    loaded = root.meta.setdefault("plugin_resource_capabilities", set())
    if capability in loaded:
        return
    loaded.add(capability)
    catalog = catalog_for(ctx)
    plugins = (
        catalog.plugins
        if capability == "channels"
        else catalog.enabled_plugins
    )
    candidates = [
        (manifest, source)
        for manifest, source in plugins
        if not (capability == "channels" and manifest.entry.descriptor)
        and (
            capability in (manifest.sdk or {}).get("capabilities", ())
            or manifest.plugin_type.value
            == {"providers": "provider", "channels": "channel"}.get(capability)
        )
    ]
    if not candidates:
        return
    session = session_for(ctx)
    for manifest, source in candidates:
        try:
            session.load_registration(manifest, source)
            if capability == "providers":
                session.run(
                    session.loader.publish_provider_definitions(
                        manifest.id,
                        persist_migrations=False,
                    ),
                )
        except (click.Abort, click.exceptions.Exit):
            raise
        except Exception as exc:  # noqa: BLE001
            reason = str(exc) or type(exc).__name__
            click.echo(
                f"Plugin '{manifest.id}' unavailable: {reason}",
                err=True,
            )
