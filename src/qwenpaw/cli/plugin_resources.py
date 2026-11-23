# -*- coding: utf-8 -*-
"""Terminal consumers of existing provider, channel and diagnostic services."""

import asyncio
import inspect
from copy import deepcopy
from contextlib import contextmanager

import click


@contextmanager
def _provider_api(manager, provider_id, saved=None):
    """Route plugin mutations to their live owner or the local operation."""
    from ..providers.provider import provider_identity_key
    from .http import client, selected_runtime_url

    provider_key = provider_identity_key(provider_id)
    is_plugin = (
        provider_key in getattr(manager, "plugin_providers", {})
        or saved is not None
    )
    target = (
        selected_runtime_url(click.get_current_context(silent=True))
        if is_plugin
        else None
    )
    if target is None:
        yield None
        return

    import httpx

    try:
        with client(target) as api:
            yield api
    except httpx.HTTPError as exc:
        raise click.ClickException(
            f"Cannot update plugin provider: {exc}",
        ) from exc


def update_provider_config(manager, provider_id, values, saved=None):
    """Update settings through the owning runtime or retained local snapshot."""
    from ..providers.provider import provider_identity_key

    with _provider_api(manager, provider_id, saved) as api:
        if api is not None:
            response = api.put(
                f"models/{provider_identity_key(provider_id)}/config",
                json=values,
            )
            response.raise_for_status()
            return True
    if saved is not None:
        return manager.update_saved_plugin_provider(provider_id, values)
    return manager.update_provider(provider_id, values)


def add_provider_model(manager, provider_id, model):
    """Submit a model addition to the provider owner."""
    from ..providers.provider import provider_identity_key

    with _provider_api(manager, provider_id) as api:
        if api is not None:
            response = api.post(
                f"models/{provider_identity_key(provider_id)}/models",
                json=model.model_dump(mode="json", exclude_unset=True),
            )
            response.raise_for_status()
            return
    asyncio.run(manager.add_model_to_provider(provider_id, model))


def delete_provider_model(manager, provider_id, model_id):
    """Submit a model removal to the provider owner."""
    from urllib.parse import quote
    from ..providers.provider import provider_identity_key

    with _provider_api(manager, provider_id) as api:
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


def doctor_contributions(context):
    """Run owned diagnostic checks and bind the selected runtime transport."""
    ctx = click.get_current_context(silent=True)
    if ctx is None:
        return []
    from .plugin_cli import catalog_for, missing_cli_root_messages
    from .plugin_session import session_for
    from .doctor_checks import selected_provider_ids
    from ..plugins.doctor import DOCTOR, DoctorContext, DoctorResult
    from ..plugins.errors import SDKError
    from ..utils.io_utils import run_sync_io

    catalog = catalog_for(ctx)

    async def get_runtime(path):
        from urllib.parse import urlsplit
        import httpx
        from ..utils.runtime_api import async_api_client

        target = urlsplit(path)
        if target.scheme or target.netloc or path.startswith("/"):
            raise SDKError("Runtime API path must be relative")
        try:
            async with async_api_client(
                context.cli_base_url.rstrip("/") + "/api/",
            ) as client:
                response = await client.get(path, timeout=context.timeout)
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SDKError(f"Runtime API read failed: {exc}") from exc

    result = [
        (issue.source_path.name, [f"(discovery error) {issue.message}"])
        for issue in catalog.issues
    ]
    for message in missing_cli_root_messages(ctx, catalog):
        result.append(("cli", [message]))
    for path, mounts in catalog.mounts.items():
        if len(mounts) > 1:
            result.append(("cli", [f"CLI path conflict: {' '.join(path)}"]))
    selected_providers = None
    for manifest, source in catalog.enabled_plugins:
        if not manifest.declares_extension(DOCTOR.id):
            continue
        session = session_for(ctx)
        try:
            session.load_registration(manifest, source)
            if selected_providers is None:
                selected_providers = session.run(
                    run_sync_io(selected_provider_ids, context.cfg),
                )
            checks = session.loader.registry.get_extensions(DOCTOR)
            for contribution in checks:
                owner, name = contribution.plugin_id, contribution.id
                if owner != manifest.id:
                    continue
                call = DoctorContext(
                    context.cfg.model_dump(mode="json")
                    if context.cfg is not None
                    else None,
                    deepcopy(context.raw_cfg),
                    context.cli_base_url,
                    context.timeout,
                    context.deep,
                    get_runtime,
                    selected_providers=selected_providers,
                )

                async def check(contribution=contribution, call=call):
                    import asyncio

                    async def invoke():
                        await contribution.admit()
                        with contribution.invocation() as spec:
                            notes = (
                                await spec.check(call)
                                if inspect.iscoroutinefunction(spec.check)
                                else await run_sync_io(spec.check, call)
                            )
                            if inspect.isawaitable(notes):
                                notes = await notes
                            if not isinstance(notes, list) or not all(
                                isinstance(n, (str, DoctorResult))
                                for n in notes
                            ):
                                raise TypeError(
                                    "Diagnostic must return notes or DoctorResult values",
                                )
                            return notes

                    return await asyncio.wait_for(
                        invoke(),
                        timeout=context.timeout,
                    )

                try:
                    result.append((f"{owner}:{name}", session.run(check())))
                except (click.Abort, click.exceptions.Exit):
                    raise
                except Exception as exc:  # noqa: BLE001
                    reason = str(exc) or type(exc).__name__
                    result.append(
                        (f"{owner}:{name}", [f"(extension error) {reason}"]),
                    )
        except (click.Abort, click.exceptions.Exit):
            raise
        except Exception as exc:  # noqa: BLE001
            reason = str(exc) or type(exc).__name__
            result.append((manifest.id, [f"(extension error) {reason}"]))
    return result
