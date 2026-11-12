# -*- coding: utf-8 -*-
"""Terminal consumers of existing provider, channel and diagnostic services."""

import inspect
import logging
from copy import deepcopy

import click

logger = logging.getLogger(__name__)


def saved_provider_infos(manager):
    """Read retained plugin settings as data, without executable providers."""
    import json
    from ..providers.provider import ProviderInfo, provider_identity_key
    from ..security.secret_store import (
        PROVIDER_SECRET_FIELDS,
        decrypt_dict_fields,
    )

    result = {}
    directory = getattr(manager, "plugin_path", None)
    if directory is None:
        return result
    for path in directory.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            info = ProviderInfo.model_validate(
                decrypt_dict_fields(data, PROVIDER_SECRET_FIELDS),
            )
            if info.id not in getattr(manager, "plugin_providers", {}):
                result[provider_identity_key(info.id)] = (info, path)
        except (OSError, ValueError, TypeError) as exc:
            logger.warning(
                "Cannot read plugin provider snapshot %s: %s",
                path,
                exc,
            )
    return result


def update_provider_config(manager, provider_id, values, saved=None):
    """Use a live plugin's API, or the same persisted settings offline.

    Built-in and custom providers retain their existing CLI behavior.
    Retained snapshots never become executable provider registrations.
    """
    from ..config.utils import is_qwenpaw_running
    from ..providers.provider import provider_identity_key

    provider_key = provider_identity_key(provider_id)
    is_plugin = (
        provider_key in getattr(manager, "plugin_providers", {})
        or saved is not None
    )
    ctx = click.get_current_context(silent=True)
    root = ctx.find_root() if ctx is not None else None
    explicit = root is not None and any(
        root.get_parameter_source(option)
        is click.core.ParameterSource.COMMANDLINE
        for option in ("host", "port")
    )
    if is_plugin and (explicit or is_qwenpaw_running()):
        import httpx
        from .http import client, resolve_base_url

        try:
            with client(resolve_base_url(ctx, None)) as api:
                response = api.put(
                    f"models/{provider_key}/config",
                    json=values,
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise click.ClickException(
                f"Cannot update plugin provider: {exc}",
            ) from exc
        return True
    if saved is None:
        return manager.update_provider(provider_id, values)
    import json
    from ..providers.provider import ProviderInfo
    from ..providers.provider_manager import ProviderManager
    from ..providers.model_sync import invalidate_api_metadata
    from ..providers.provider_update_fields import CONNECTION_CONFIG_FIELDS
    from ..providers.provider_persistence import write_snapshot_payload
    from ..security.secret_store import (
        PROVIDER_SECRET_FIELDS,
        decrypt_dict_fields,
        encrypt_dict_fields,
    )
    from ..utils.io_utils import get_sync_path_lock

    _, path = saved
    with get_sync_path_lock(path):
        raw = json.loads(path.read_text(encoding="utf-8"))
        current = decrypt_dict_fields(raw, PROVIDER_SECRET_FIELDS)
        updates = {
            key: value for key, value in values.items() if value is not None
        }
        before = ProviderInfo.model_validate(current)
        candidate = ProviderInfo.model_validate({**current, **updates})
        changed = {
            key
            for key in CONNECTION_CONFIG_FIELDS.intersection(updates)
            if getattr(before, key, None) != getattr(candidate, key, None)
        }
        if changed:
            ProviderManager._reset_model_availability(candidate)
            invalidate_api_metadata(candidate)
            candidate.models_syncing = False
            for key in ("models", "extra_models"):
                updates[key] = [
                    {**original, **model.model_dump(mode="json")}
                    for original, model in zip(
                        current.get(key, ()),
                        getattr(candidate, key),
                    )
                ]
            for key in (
                "discovered_models",
                "models_last_synced_at",
                "models_last_sync_error",
                "models_syncing",
            ):
                updates[key] = getattr(candidate, key)
        secured = encrypt_dict_fields(updates, PROVIDER_SECRET_FIELDS)
        write_snapshot_payload({**raw, **secured}, path)
    return True


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
            session.load(manifest, source)
            if capability == "providers":
                session.run(session.loader._project_providers(manifest.id))
        except (click.Abort, click.exceptions.Exit):
            raise
        except Exception as exc:  # noqa: BLE001
            reason = str(exc) or type(exc).__name__
            click.echo(
                f"Plugin '{manifest.id}' unavailable: {reason}",
                err=True,
            )


def doctor_contributions(context):
    """Adapt plugin-owned diagnostic notes to the legacy doctor envelope."""
    ctx = click.get_current_context(silent=True)
    if ctx is None:
        return []
    from .plugin_cli import catalog_for
    from .plugin_session import session_for
    from ..plugins.doctor import DOCTOR, DoctorContext
    from ..utils.io_utils import run_sync_io

    catalog = catalog_for(ctx)
    result = [
        (issue.source_path.name, [f"(discovery error) {issue.message}"])
        for issue in catalog.issues
    ]
    for path, mounts in catalog.mounts.items():
        if len(mounts) > 1:
            result.append(("cli", [f"CLI path conflict: {' '.join(path)}"]))
    for manifest, source in catalog.enabled_plugins:
        if not manifest.declares_extension(DOCTOR.id):
            continue
        session = session_for(ctx)
        try:
            session.load(manifest, source)
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
                                isinstance(n, str) for n in notes
                            ):
                                raise TypeError(
                                    "Diagnostic must return a list of strings",
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
