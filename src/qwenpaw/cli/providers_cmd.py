# -*- coding: utf-8 -*-
"""CLI commands for managing LLM providers."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import os
from typing import Optional

import click

from qwenpaw.exceptions import (
    AppBaseException,
)

from ..providers.hub_managed import PROVIDER_ID as HUB_PROVIDER_ID
from ..providers.provider import (
    ModelInfo,
    Provider,
    ProviderInfo,
    provider_identity_key,
)
from ..providers.provider_manager import ProviderManager
from .utils import prompt_choice


def _manager() -> ProviderManager:
    from .plugin_resources import ensure_resources

    ensure_resources("providers")
    return ProviderManager.get_instance()


def _mask_api_key(api_key: str) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return f"{api_key[:4]}...{api_key[-2:]}"


def _api_key_prefixes(provider: ProviderInfo) -> list[str]:
    if provider.api_key_prefixes:
        return provider.api_key_prefixes
    return [provider.api_key_prefix] if provider.api_key_prefix else []


def _is_configured(provider: ProviderInfo) -> bool:
    if provider.is_local:
        return True
    if provider.id == HUB_PROVIDER_ID:
        # The App exposes organization grants while keeping its endpoint private.
        return bool(provider.all_models())
    if not provider.base_url:
        return False
    if provider.require_api_key and not provider.api_key:
        return False
    return True


def _all_provider_objects(manager: ProviderManager) -> list[Provider]:
    objs: list[Provider] = []
    for info in asyncio.run(manager.list_provider_info()):
        provider = manager.get_provider(info.id)
        if provider is not None:
            objs.append(provider)
    return objs


def _get_ollama_host() -> str:
    manager = _manager()
    provider = manager.get_provider("ollama")
    if provider is None or not provider.base_url:
        return "http://127.0.0.1:11434"
    return provider.base_url


def _select_provider_interactive(
    prompt_text: str = "Select provider:",
    *,
    default_pid: str = "",
) -> str:
    """Prompt user to pick a provider. Returns provider_id."""
    return _choose_provider(
        _all_provider_objects(_manager()),
        prompt_text,
        default_pid,
    )


def _choose_provider(providers, prompt_text, default_pid=""):
    labels: list[str] = []
    ids: list[str] = []
    for provider in providers:
        mark = "✓" if _is_configured(provider) else "✗"
        labels.append(f"{provider.name} ({provider.id}) [{mark}]")
        ids.append(provider.id)

    default_label: Optional[str] = None
    if default_pid in ids:
        default_label = labels[ids.index(default_pid)]

    chosen_label = prompt_choice(
        prompt_text,
        options=labels,
        default=default_label,
    )
    return ids[labels.index(chosen_label)]


def configure_provider_api_key_interactive(
    provider_id: str | None = None,
) -> str:
    """Interactively configure a provider's API key. Returns provider_id."""
    with _model_setup_api() as api:
        return _configure_provider_api_key(provider_id, api)


def _configure_provider_api_key(provider_id, api):
    prompt = "Select provider to configure API key:"
    if api is not None:
        return _configure_runtime_provider(api, provider_id, prompt)
    manager = _manager()
    if provider_id is None:
        provider_id = _select_provider_interactive(prompt)
    provider = manager.get_provider(provider_id)
    saved = None
    if provider is None:
        saved = manager.saved_plugin_provider_infos().get(
            provider_identity_key(provider_id),
        )
        provider = saved
    if provider is None:
        click.echo(
            click.style(
                f"Error: provider '{provider_id}' not found.",
                fg="red",
            ),
        )
        raise SystemExit(1)

    changes = _prompt_provider_config(provider)
    if changes:
        if saved is not None:
            ok = (
                manager.update_saved_plugin_provider(provider_id, changes)
                is not None
            )
        else:
            ok = manager.update_provider(provider_id, changes)
        if not ok:
            click.echo(
                click.style(
                    f"Error: provider '{provider_id}' not found.",
                    fg="red",
                ),
            )
            raise SystemExit(1)
    _show_provider_config(provider, changes)
    return provider_id


def _configure_runtime_provider(api, provider_id, prompt):
    providers = None
    if provider_id is None:
        providers = _runtime_providers(api)
        provider_id = _choose_provider(providers, prompt)
    key = provider_identity_key(provider_id)
    path = f"models/{key}/config"
    response = api.get(path)
    if response.status_code == 405:
        # Older Apps only support PUT here and list active providers at /models.
        if providers is None:
            providers = _runtime_providers(api)
        provider = next(
            (p for p in providers if provider_identity_key(p.id) == key),
            None,
        )
        if provider is None:
            raise click.ClickException(
                f"Provider '{provider_id}' is unavailable on {api.base_url}.",
            )
    else:
        response.raise_for_status()
        provider = ProviderInfo.model_validate(response.json())
    changes = _prompt_provider_config(provider)
    if changes:
        api.put(
            path,
            json={**changes, "auto_discover": False},
        ).raise_for_status()
    _show_provider_config(provider, changes)
    return provider_id


@contextmanager
def _model_setup_api():
    from .http import (
        client,
        explicit_runtime_url,
        local_runtime_url,
    )
    from ..utils.http import is_loopback_url

    ctx = click.get_current_context(silent=True)
    explicit = explicit_runtime_url(ctx)
    standalone = not os.getenv("QWENPAW_RUNTIME_ID")
    local = (
        local_runtime_url()
        if ctx is not None
        and (explicit is None or (standalone and is_loopback_url(explicit)))
        else None
    )
    target = explicit or local

    if target is None:
        yield None
        return

    import httpx

    try:
        with client(target) as api:
            # Standalone commands also have permission to edit their profile
            # on disk. Choose that path before prompts or any API writes.
            if (
                standalone
                and target == local
                and is_loopback_url(target)
                and api.get("models").status_code == 401
            ):
                click.echo(
                    "The local App requires sign-in. Using this profile "
                    "on disk.",
                    err=True,
                )
                yield None
            else:
                yield api
    except httpx.HTTPError as exc:
        raise click.ClickException(
            f"Cannot access provider on {target}: {exc}",
        ) from exc


def _setup_provider(provider_id, api):
    if api is None:
        provider = _manager().get_provider(provider_id)
    else:
        provider = next(
            (p for p in _runtime_providers(api) if p.id == provider_id),
            None,
        )
    if provider is None:
        click.echo(
            click.style(
                f"Error: provider '{provider_id}' not found.",
                fg="red",
            ),
        )
        raise SystemExit(1)
    return provider


def _runtime_providers(api, view="stored"):
    response = api.get("models", params={"view": view})
    response.raise_for_status()
    return [ProviderInfo.model_validate(info) for info in response.json()]


def _prompt_provider_config(defn: ProviderInfo) -> dict[str, str]:
    changes = {}
    current_base, current_key = defn.base_url, defn.api_key

    base_url: Optional[str] = None
    if defn.freeze_url:
        if current_base:
            click.echo(f"Base URL: {current_base} (fixed, not editable)")
    else:
        azure_hint = (
            "Azure endpoint "
            "(e.g. https://<resource>.openai.azure.com/openai/v1)"
        )
        url_hint = (
            azure_hint
            if defn.id == "azure-openai"
            else "Base URL (OpenAI-compatible endpoint)"
        )
        base_url = click.prompt(
            url_hint,
            default=current_base or "",
            show_default=bool(current_base),
        ).strip()
        if not base_url and (defn.is_custom or not current_base):
            click.echo(click.style("Error: base_url is required.", fg="red"))
            raise SystemExit(1)
        if base_url and base_url != current_base:
            changes["base_url"] = base_url

    if not defn.require_api_key:
        return changes

    prefixes = _api_key_prefixes(defn)
    hint = f"prefix: {', '.join(prefixes)}" if prefixes else "optional"
    api_key = click.prompt(
        f"API key ({hint})",
        default="",
        hide_input=True,
        show_default=False,
        prompt_suffix=f" [{'set' if current_key else 'not set'}]: ",
    )

    if api_key and api_key != current_key:
        changes["api_key"] = api_key
    return changes


def _show_provider_config(provider, changes):
    if not changes:
        click.echo(f"{provider.name}: configuration unchanged.")
        return
    fields = []
    if "api_key" in changes:
        fields.append(f"API Key: {_mask_api_key(changes['api_key'])}")
    if "base_url" in changes:
        fields.append(f"Base URL: {changes['base_url']}")
    click.echo(f"✓ {provider.name} — " + ", ".join(fields))


def _add_models_interactive(provider_id: str, api) -> None:
    """Interactively add models to a provider after configuration."""
    defn = _setup_provider(provider_id, api)
    _prompt_add_models(provider_id, defn, api)


def _prompt_add_models(provider_id, defn, api):
    # Ollama models cannot be added manually - they come from Ollama daemon
    if provider_id == "ollama":
        return

    all_models = defn.all_models()

    if all_models:
        click.echo(f"\nCurrent models for {defn.name}:")
        for m in all_models:
            click.echo(f"  - {m.name} ({m.id})")
    else:
        click.echo(f"\nNo models configured for {defn.name}.")

    while click.confirm("Add a model?", default=not all_models):
        model_id = click.prompt("Model identifier").strip()
        if not model_id:
            click.echo(click.style("Error: model id is required.", fg="red"))
            continue
        model_name = click.prompt(
            "Model display name",
            default=model_id,
        ).strip()
        try:
            model = ModelInfo(id=model_id, name=model_name)
            _add_setup_model(provider_id, model, api)
            click.echo(f"✓ Model '{model_name}' ({model_id}) added.")
            all_models.append(model)
        except (ValueError, AppBaseException) as exc:
            click.echo(click.style(f"Error: {exc}", fg="red"))


def _add_setup_model(provider_id, model, api):
    if api is None:
        asyncio.run(_manager().add_model_to_provider(provider_id, model))
    else:
        response = api.post(
            f"models/{provider_identity_key(provider_id)}/models",
            json=model.model_dump(mode="json", exclude_unset=True),
        )
        if response.status_code in (404, 409):
            try:
                detail = response.json()["detail"]
            except (ValueError, TypeError, KeyError):
                detail = None
            # Older Apps used 404 for both missing providers and model rejections.
            if isinstance(detail, str) and (
                response.status_code == 409
                or detail == f"Model '{model.id}' already exists"
                or detail.startswith(f"Model '{model.id}' cannot be added:")
            ):
                raise ValueError(detail)
        response.raise_for_status()


def _pick_model_from_list(
    models: list[ModelInfo],
    prompt_text: str,
    current_model: str = "",
) -> str:
    labels = [m.name for m in models]
    ids = [m.id for m in models]

    default_label: Optional[str] = None
    if current_model in ids:
        default_label = labels[ids.index(current_model)]

    chosen = prompt_choice(prompt_text, options=labels, default=default_label)
    return ids[labels.index(chosen)]


def _pick_model_free_text(prompt_text: str, current_model: str = "") -> str:
    model = click.prompt(prompt_text, default=current_model or "").strip()
    if not model:
        click.echo(click.style("Error: model name is required.", fg="red"))
        raise SystemExit(1)
    return model


def _filter_eligible(all_providers):
    return [
        d
        for d in all_providers
        if _is_configured(d)
        and d.chat_model
        and (
            not d.all_models()
            or any(m.model_type == "chat" for m in d.all_models())
        )
    ]


def _select_llm_model(defn, pid, current_slot, use_defaults, api=None):
    """Pick a model for the given provider. Returns model id."""
    cur = (
        current_slot.model
        if current_slot and current_slot.provider_id == pid
        else ""
    )

    all_models = [m for m in defn.all_models() if m.model_type == "chat"]

    if use_defaults:
        return cur or (all_models[0].id if all_models else "")

    if pid == "ollama":
        if api is None:
            discovery = asyncio.run(
                _manager().discover_provider_models(pid, save=False),
            )
        else:
            from ..providers.provider_discovery import (
                ProviderModelDiscoveryResult,
            )

            response = api.post(
                f"models/{pid}/discover",
                params={"save": "false"},
            )
            response.raise_for_status()
            payload = response.json()
            discovery = ProviderModelDiscoveryResult.model_validate(
                {**payload, "error": payload.get("message")},
            )
        models = [m for m in discovery.models if m.model_type == "chat"]
        if not discovery.success or not models:
            reason = (
                f"Cannot discover Ollama models: {discovery.error}"
                if not discovery.success
                else "Ollama returned no chat models."
            )
            if not all_models:
                raise click.ClickException(reason)
            click.echo(f"{reason} Using configured models.", err=True)
            models = all_models
        selected = _pick_model_from_list(
            models,
            "Select LLM model:",
            current_model=cur,
        )
        # Discovery candidates are not configured models. Persist only the
        # user's selection, preserving overrides on an existing model.
        if not any(model.id == selected for model in defn.all_models()):
            model = next(m for m in models if m.id == selected)
            _add_setup_model(pid, model, api)
        return selected

    if all_models:
        return _pick_model_from_list(
            all_models,
            "Select LLM model:",
            current_model=cur,
        )
    return _pick_model_free_text(
        "LLM model name (required):",
        current_model=cur,
    )


def configure_llm_slot_interactive(*, use_defaults: bool = False) -> None:
    """Interactively configure the active LLM model slot."""
    with _model_setup_api() as api:
        _configure_llm_slot(use_defaults, api)


def _model_choices(api):
    if api is None:
        manager = _manager()
        return (
            _filter_eligible(_all_provider_objects(manager)),
            manager.get_active_model(),
        )
    return _filter_eligible(_runtime_providers(api)), _runtime_active_model(
        api,
    )


def _runtime_active_model(api):
    from ..config.config import ActiveModelsInfo

    response = api.get("models/active", params={"scope": "global"})
    response.raise_for_status()
    return ActiveModelsInfo.model_validate(response.json()).active_llm


def _configure_llm_slot(use_defaults, api):
    eligible, current_slot = _model_choices(api)
    if not eligible:
        if use_defaults:
            click.echo(
                "No LLM provider configured. Run 'qwenpaw models config' "
                "to configure later.",
            )
            return
        click.echo(
            click.style(
                "No providers are configured yet. Let's configure one now.",
                fg="yellow",
            ),
        )
        pid = _configure_provider_api_key(None, api)
        _add_models_interactive(pid, api)
        eligible, current_slot = _model_choices(api)
        if not eligible:
            click.echo(
                click.style("Error: provider configuration failed.", fg="red"),
            )
            raise SystemExit(1)

    ids = [d.id for d in eligible]
    if use_defaults:
        pid = (
            current_slot.provider_id
            if current_slot and current_slot.provider_id in ids
            else ids[0]
        )
    else:
        labels = [f"{d.name} ({d.id})" for d in eligible]
        default_label = (
            labels[ids.index(current_slot.provider_id)]
            if current_slot and current_slot.provider_id in ids
            else None
        )
        chosen_label = prompt_choice(
            "Select provider for LLM:",
            options=labels,
            default=default_label,
        )
        pid = ids[labels.index(chosen_label)]

    defn = _setup_provider(pid, api)
    try:
        model = _select_llm_model(
            defn,
            pid,
            current_slot,
            use_defaults=use_defaults,
            api=api,
        )
        if not model and use_defaults:
            click.echo(
                f"No default model for {defn.name}. "
                "Run 'qwenpaw models config' to set one.",
            )
            return
        if api is None:
            asyncio.run(_manager().activate_model(pid, model))
        else:
            api.put(
                "models/active",
                json={"scope": "global", "provider_id": pid, "model": model},
            ).raise_for_status()
    except (ValueError, AppBaseException) as exc:
        if use_defaults:
            click.echo(
                f"Skip default activation for {defn.name}: {exc}",
            )
            return
        click.echo(click.style(f"Error: {exc}", fg="red"))
        raise SystemExit(1) from exc
    click.echo(f"✓ LLM: {defn.name} / {model}")


def configure_providers_interactive(*, use_defaults: bool = False) -> None:
    """Full interactive setup: configure provider → add models →
    activate LLM."""
    with _model_setup_api() as api:
        if use_defaults:
            _configure_llm_slot(True, api)
            return
        click.echo("\n--- Provider Configuration ---")
        while True:
            pid = _configure_provider_api_key(None, api)
            defn = _setup_provider(pid, api)
            if defn.is_local or pid == "ollama":
                click.echo(f"\n--- Activate {defn.name} Model ---")
                _configure_llm_slot(False, api)
                return
            _prompt_add_models(pid, defn, api)
            if not click.confirm("Configure another provider?", default=False):
                break

        click.echo("\n--- Activate LLM Model ---")
        _configure_llm_slot(False, api)


@click.group("models")
def models_group() -> None:
    """Manage LLM models and provider configuration."""


@models_group.command("list")
def list_cmd() -> None:
    """Show all providers and their current configuration."""
    with _model_setup_api() as api:
        if api is None:
            manager = _manager()
            providers = _all_provider_objects(manager)
            unavailable = manager.saved_plugin_provider_infos().values()
            llm = manager.get_active_model()
        else:
            providers = _runtime_providers(api)
            # Older Apps ignore the view parameter and return registered providers.
            registered = {provider_identity_key(info.id) for info in providers}
            unavailable = [
                info
                for info in _runtime_providers(api, "unavailable")
                if provider_identity_key(info.id) not in registered
            ]
            llm = _runtime_active_model(api)

    click.echo("\n=== Providers ===")
    for defn in providers:
        cur_url, cur_key = defn.base_url, defn.api_key

        tag = (
            " [custom]"
            if defn.is_custom
            else " [local]"
            if defn.is_local
            else ""
        )
        click.echo(f"\n{'─' * 44}")
        click.echo(f"  {defn.name} ({defn.id}){tag}")
        click.echo(f"{'─' * 44}")

        all_models = defn.all_models()
        if defn.is_local:
            if all_models:
                click.echo(f"  {'models':16s}:")
                for m in all_models:
                    click.echo(f"    - {m.name}")
            else:
                click.echo("  No models configured.")
                click.echo(
                    "  Run 'qwenpaw models --help' for available commands.",
                )
        else:
            click.echo(f"  {'base_url':16s}: {cur_url or '(not set)'}")
            click.echo(
                f"  {'api_key':16s}: "
                f"{_mask_api_key(cur_key) or '(not set)'}",
            )
            prefixes = _api_key_prefixes(defn)
            if prefixes:
                click.echo(
                    f"  {'api_key_prefix':16s}: {', '.join(prefixes)}",
                )

            if all_models:
                click.echo(f"  {'models':16s}:")
                extra_ids = {m.id for m in defn.extra_models}
                for m in all_models:
                    label = " [user-added]" if m.id in extra_ids else ""
                    click.echo(f"    - {m.name} ({m.id}){label}")

    for info in unavailable:
        click.echo(f"\n  {info.name} ({info.id}) [plugin unavailable]")
        click.echo(f"  {'base_url':16s}: {info.base_url or '(not set)'}")
        click.echo(
            f"  {'api_key':16s}: {_mask_api_key(info.api_key) or '(not set)'}",
        )
        for model in info.all_models():
            click.echo(f"    - {model.name} ({model.id})")

    click.echo(f"\n{'═' * 44}")
    click.echo("  Active Model Slot")
    click.echo(f"{'═' * 44}")

    if llm and llm.provider_id and llm.model:
        click.echo(f"  {'LLM':16s}: {llm.provider_id} / {llm.model}")
    else:
        click.echo(f"  {'LLM':16s}: (not configured)")
    click.echo()


@models_group.command("config")
def config_cmd() -> None:
    """Interactively configure providers and active models."""
    configure_providers_interactive()


@models_group.command("config-key")
@click.argument("provider_id", required=False, default=None)
def config_key_cmd(provider_id: str | None) -> None:
    """Configure a provider's API key."""
    configure_provider_api_key_interactive(provider_id)


@models_group.command("set-llm")
def set_llm_cmd() -> None:
    """Interactively set the active LLM model."""
    configure_llm_slot_interactive()


@models_group.command("add-provider")
@click.argument("provider_id")
@click.option("--name", "-n", required=True, help="Human-readable name")
@click.option("--base-url", "-u", default="", help="Default API base URL")
@click.option("--api-key-prefix", default="", help="Expected API key prefix")
def add_provider_cmd(
    provider_id: str,
    name: str,
    base_url: str,
    api_key_prefix: str,
) -> None:
    """Add a new custom provider."""
    info = ProviderInfo(
        id=provider_id,
        name=name,
        base_url=base_url,
        api_key_prefix=api_key_prefix,
        is_custom=True,
    )
    try:
        with _model_setup_api() as api:
            if api is None:
                provider_info = asyncio.run(
                    _manager().add_custom_provider(info),
                )
            else:
                response = api.post(
                    "models/custom-providers",
                    json={
                        "id": info.id,
                        "name": info.name,
                        "default_base_url": info.base_url,
                        "api_key_prefix": info.api_key_prefix,
                        "auto_discover": False,
                    },
                )
                response.raise_for_status()
                provider_info = ProviderInfo.model_validate(response.json())
    except (ValueError, AppBaseException) as exc:
        click.echo(click.style(f"Error: {exc}", fg="red"))
        raise SystemExit(1) from exc
    click.echo(
        "✓ Custom provider "
        f"'{provider_info.name}' ({provider_info.id}) created.",
    )
    if provider_info.id != provider_id:
        click.echo(f"  requested id: {provider_id}")
    if base_url:
        click.echo(f"  base_url: {base_url}")
    click.echo(
        "  Run 'qwenpaw models add-model' to add models, "
        "then 'qwenpaw models config-key' to set the API key.",
    )


@models_group.command("remove-provider")
@click.argument("provider_id")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
def remove_provider_cmd(provider_id: str, yes: bool) -> None:
    """Remove a custom provider."""
    try:
        with _model_setup_api() as api:
            if api is None and provider_id in _manager().builtin_providers:
                raise ValueError(
                    f"'{provider_id}' is a built-in provider and cannot be removed.",
                )
            if not yes and not click.confirm(
                f"Delete custom provider '{provider_id}' and all its models?",
            ):
                return
            if api is None:
                if not _manager().remove_custom_provider(provider_id):
                    raise ValueError(
                        f"Custom provider '{provider_id}' not found.",
                    )
            else:
                api.delete(
                    f"models/custom-providers/{provider_identity_key(provider_id)}",
                ).raise_for_status()
    except (ValueError, AppBaseException) as exc:
        click.echo(click.style(f"Error: {exc}", fg="red"))
        raise SystemExit(1) from exc
    click.echo(f"✓ Custom provider '{provider_id}' deleted.")


@models_group.command("add-model")
@click.argument("provider_id")
@click.option("--model-id", "-m", required=True, help="Model identifier")
@click.option("--model-name", "-n", required=True, help="Model display name")
def add_model_cmd(provider_id: str, model_id: str, model_name: str) -> None:
    """Add a model to any provider (built-in or custom)."""
    # Prevent manual model addition for Ollama
    if provider_id == "ollama":
        click.echo(
            click.style(
                "Error: Ollama models cannot be added manually. "
                "Use 'ollama pull <model>' to download models.",
                fg="red",
            ),
        )
        raise SystemExit(1)

    try:
        with _model_setup_api() as api:
            _add_setup_model(
                provider_id,
                ModelInfo(id=model_id, name=model_name),
                api,
            )
    except (ValueError, AppBaseException) as exc:
        click.echo(click.style(f"Error: {exc}", fg="red"))
        raise SystemExit(1) from exc
    click.echo(
        f"✓ Model '{model_name}' ({model_id}) added to '{provider_id}'.",
    )


@models_group.command("remove-model")
@click.argument("provider_id")
@click.option("--model-id", "-m", required=True, help="Model identifier")
def remove_model_cmd(provider_id: str, model_id: str) -> None:
    """Remove a user-added model from any provider."""
    # Prevent manual model removal for Ollama
    if provider_id == "ollama":
        click.echo(
            click.style(
                "Error: Ollama models cannot be removed via this command. "
                "Use 'ollama rm <model>' to delete models.",
                fg="red",
            ),
        )
        raise SystemExit(1)

    try:
        with _model_setup_api() as api:
            if api is None:
                asyncio.run(
                    _manager().delete_model_from_provider(
                        provider_id,
                        model_id,
                    ),
                )
            else:
                from urllib.parse import quote

                api.delete(
                    f"models/{provider_identity_key(provider_id)}/models/"
                    f"{quote(model_id, safe='')}",
                ).raise_for_status()
        click.echo(f"✓ Model '{model_id}' removed from '{provider_id}'.")
    except (ValueError, AppBaseException) as exc:
        click.echo(click.style(f"Error: {exc}", fg="red"))
        raise SystemExit(1) from exc
