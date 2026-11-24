# -*- coding: utf-8 -*-
"""Discover terminal resources and route provider updates to their owner."""

import asyncio
from contextlib import contextmanager

import click


def plugin_provider_url(manager, provider_id, saved=None):
    """Find the runtime responsible for a registered or saved plugin provider."""
    from ..providers.provider import provider_identity_key
    from .http import selected_runtime_url

    provider_key = provider_identity_key(provider_id)
    is_plugin = (
        provider_key in getattr(manager, "plugin_providers", {})
        or saved is not None
    )
    return (
        selected_runtime_url(click.get_current_context(silent=True))
        if is_plugin
        else None
    )


@contextmanager
def provider_api(target):
    from .http import client

    if target is None:
        yield None
        return

    import httpx

    try:
        with client(target) as api:
            yield api
    except httpx.HTTPError as exc:
        raise click.ClickException(
            f"Cannot access provider on {target}: {exc}",
        ) from exc


def add_provider_model(manager, provider_id, model):
    """Submit a model addition to the provider owner."""
    with provider_api(plugin_provider_url(manager, provider_id)) as api:
        if api is not None:
            post_provider_model(api, provider_id, model)
            return
    asyncio.run(manager.add_model_to_provider(provider_id, model))


def post_provider_model(api, provider_id, model):
    from ..providers.provider import provider_identity_key

    api.post(
        f"models/{provider_identity_key(provider_id)}/models",
        json=model.model_dump(mode="json", exclude_unset=True),
    ).raise_for_status()


def delete_provider_model(manager, provider_id, model_id):
    """Submit a model removal to the provider owner."""
    from urllib.parse import quote
    from ..providers.provider import provider_identity_key

    with provider_api(plugin_provider_url(manager, provider_id)) as api:
        if api is not None:
            response = api.delete(
                f"models/{provider_identity_key(provider_id)}/models/"
                f"{quote(model_id, safe='')}",
            )
            response.raise_for_status()
            return
    asyncio.run(manager.delete_model_from_provider(provider_id, model_id))


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
                    session.loader.publish_provider_definitions(manifest.id),
                )
        except (click.Abort, click.exceptions.Exit):
            raise
        except Exception as exc:  # noqa: BLE001
            reason = str(exc) or type(exc).__name__
            click.echo(
                f"Plugin '{manifest.id}' unavailable: {reason}",
                err=True,
            )
