# -*- coding: utf-8 -*-
"""CLI commands for managing LLM providers."""
from __future__ import annotations

from typing import Optional

import click

from ..providers import (
    ModelInfo,
    PROVIDERS,
    add_model,
    create_custom_provider,
    delete_custom_provider,
    get_provider,
    is_builtin,
    list_providers,
    load_providers_json,
    mask_api_key,
    remove_model,
    set_active_llm,
    update_provider_settings,
)
from .utils import prompt_choice


def _select_provider_interactive(
    prompt_text: str = "Select provider:",
    *,
    default_pid: str = "",
) -> str:
    """Prompt user to pick a provider. Returns provider_id."""
    data = load_providers_json()
    all_providers = list_providers()

    labels: list[str] = []
    ids: list[str] = []
    for d in all_providers:
        mark = "✓" if data.is_configured(d) else "✗"
        labels.append(f"{d.name} ({d.id}) [{mark}]")
        ids.append(d.id)

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
    data = load_providers_json()

    if provider_id is None:
        provider_id = _select_provider_interactive(
            "Select provider to configure API key:",
        )

    defn = get_provider(provider_id)
    if defn is None:
        available = ", ".join(d.id for d in list_providers())
        click.echo(
            click.style(
                f"Error: unknown provider '{provider_id}'. "
                f"Available providers: {available}",
                fg="red",
            ),
        )
        click.echo(
            "To add a custom provider, first run:\n"
            f"  copaw models add-provider {provider_id} "
            f'-n "My Provider"',
        )
        raise SystemExit(1)

    # Local providers (llamacpp, mlx) don't need API key configuration
    if defn.is_local:
        click.echo(f"{defn.name} does not require API key configuration.")
        click.echo(
            "Use 'copaw models download' to add models, "
            "then 'copaw models set-llm' to activate.",
        )
        return provider_id

    # Ollama provider is local-like (no API key needed)
    if provider_id == "ollama":
        return provider_id

    current_base, current_key = data.get_credentials(provider_id)

    base_url: Optional[str] = None
    # Prompt for base_url if the provider is custom or has no default URL
    # (e.g. Azure OpenAI requires user to provide their endpoint).
    if defn.is_custom or not defn.default_base_url:
        azure_hint = (
            "Azure endpoint "
            "(e.g. https://<resource>.openai.azure.com/openai/v1)"
        )
        url_hint = (
            azure_hint
            if provider_id == "azure-openai"
            else "Base URL (OpenAI-compatible endpoint)"
        )
        base_url = click.prompt(
            url_hint,
            default=current_base or "",
            show_default=bool(current_base),
        ).strip()
        if not base_url:
            click.echo(click.style("Error: base_url is required.", fg="red"))
            raise SystemExit(1)

    hint = (
        f"prefix: {defn.api_key_prefix}" if defn.api_key_prefix else "optional"
    )
    api_key = click.prompt(
        f"API key ({hint})",
        default=current_key or "",
        hide_input=True,
        show_default=False,
        prompt_suffix=f" [{'set' if current_key else 'not set'}]: ",
    )

    update_provider_settings(
        provider_id,
        api_key=api_key if api_key else None,
        base_url=base_url,
    )

    click.echo(
        f"✓ {defn.name} — API Key: {mask_api_key(api_key) or '(not set)'}"
        + (f", Base URL: {base_url}" if base_url else ""),
    )
    return provider_id


def _add_models_interactive(provider_id: str) -> None:
    """Interactively add models to a provider after configuration."""
    defn = PROVIDERS[provider_id]
    data = load_providers_json()

    # Ollama models cannot be added manually - they come from Ollama daemon
    if provider_id == "ollama":
        return

    settings = data.providers.get(provider_id)
    extra = (
        list(settings.extra_models) if settings and not defn.is_custom else []
    )
    all_models = list(defn.models) + extra

    if all_models:
        click.echo(f"\nCurrent models for {defn.name}:")
        for m in all_models:
            click.echo(f"  - {m.name} ({m.id})")
    else:
        click.echo(f"\nNo models configured for {defn.name}.")

    # Default to yes if there are no models at all
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
            add_model(provider_id, ModelInfo(id=model_id, name=model_name))
            click.echo(f"✓ Model '{model_name}' ({model_id}) added.")
            all_models.append(ModelInfo(id=model_id, name=model_name))
        except ValueError as exc:
            click.echo(click.style(f"Error: {exc}", fg="red"))


def _pick_model_from_list(
    models: list,
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


def _filter_eligible(data, all_providers):
    return [d for d in all_providers if data.is_configured(d)]


def _select_llm_model(defn, pid, current_slot, data, *, use_defaults):
    """Pick a model for the given provider. Returns model id."""
    cur = current_slot.model if current_slot.provider_id == pid else ""

    settings = data.providers.get(pid)
    extra = (
        list(settings.extra_models) if settings and not defn.is_custom else []
    )
    all_models = list(defn.models) + extra

    if use_defaults:
        return cur or (all_models[0].id if all_models else "")

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
    data = load_providers_json()
    all_providers = list_providers()
    current_slot = data.active_llm

    eligible = _filter_eligible(data, all_providers)

    if not eligible:
        if use_defaults:
            click.echo(
                "No LLM provider configured. Run 'copaw models config' "
                "to configure later.",
            )
            return
        click.echo(
            click.style(
                "No providers are configured yet. Let's configure one now.",
                fg="yellow",
            ),
        )
        pid = configure_provider_api_key_interactive()
        _add_models_interactive(pid)
        data = load_providers_json()
        current_slot = data.active_llm
        eligible = _filter_eligible(data, all_providers)
        if not eligible:
            click.echo(
                click.style("Error: provider configuration failed.", fg="red"),
            )
            raise SystemExit(1)

    ids = [d.id for d in eligible]
    if use_defaults:
        pid = (
            current_slot.provider_id
            if current_slot.provider_id in ids
            else ids[0]
        )
    else:
        labels = [f"{d.name} ({d.id})" for d in eligible]
        default_label = (
            labels[ids.index(current_slot.provider_id)]
            if current_slot.provider_id in ids
            else None
        )
        chosen_label = prompt_choice(
            "Select provider for LLM:",
            options=labels,
            default=default_label,
        )
        pid = ids[labels.index(chosen_label)]

    defn = PROVIDERS[pid]
    model = _select_llm_model(
        defn,
        pid,
        current_slot,
        data,
        use_defaults=use_defaults,
    )
    if not model and use_defaults:
        click.echo(
            f"No default model for {defn.name}. "
            "Run 'copaw models config' to set one.",
        )
        return
    set_active_llm(pid, model)
    click.echo(f"✓ LLM: {defn.name} / {model}")


def configure_providers_interactive(*, use_defaults: bool = False) -> None:
    """Full interactive setup: configure provider → add models →
    activate LLM."""
    if use_defaults:
        configure_llm_slot_interactive(use_defaults=True)
        return

    click.echo("\n--- Provider Configuration ---")
    while True:
        pid = configure_provider_api_key_interactive()

        # For local providers (llamacpp, mlx, ollama),
        # skip to model activation directly
        defn = PROVIDERS[pid]
        if defn.is_local or pid == "ollama":
            click.echo(f"\n--- Activate {defn.name} Model ---")
            configure_llm_slot_interactive()
            return

        _add_models_interactive(pid)
        if not click.confirm("Configure another provider?", default=False):
            break

    click.echo("\n--- Activate LLM Model ---")
    configure_llm_slot_interactive()


@click.group("models")
def models_group() -> None:
    """Manage LLM models and provider configuration."""


@models_group.command("list")
def list_cmd() -> None:
    """Show all providers and their current configuration."""
    data = load_providers_json()

    click.echo("\n=== Providers ===")
    for defn in list_providers():
        cur_url, cur_key = data.get_credentials(defn.id)
        settings = data.providers.get(defn.id)

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

        if defn.is_local:
            all_models = list(defn.models)
            if all_models:
                click.echo(f"  {'models':16s}:")
                for m in all_models:
                    click.echo(f"    - {m.name}")
            else:
                click.echo("  No models downloaded.")
                click.echo("  Use 'copaw models download' to add models.")
        else:
            if defn.is_custom or not defn.default_base_url:
                click.echo(f"  {'base_url':16s}: {cur_url or '(not set)'}")
            click.echo(
                f"  {'api_key':16s}: "
                f"{mask_api_key(cur_key) or '(not set)'}",
            )
            if defn.api_key_prefix:
                click.echo(
                    f"  {'api_key_prefix':16s}: {defn.api_key_prefix}",
                )

            extra = (
                list(settings.extra_models)
                if settings and not defn.is_custom
                else []
            )
            all_models = list(defn.models) + extra
            if all_models:
                click.echo(f"  {'models':16s}:")
                for m in all_models:
                    label = " [user-added]" if m in extra else ""
                    click.echo(f"    - {m.name} ({m.id}){label}")

    click.echo(f"\n{'═' * 44}")
    click.echo("  Active Model Slot")
    click.echo(f"{'═' * 44}")

    llm = data.active_llm
    if llm.provider_id and llm.model:
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
    try:
        create_custom_provider(
            provider_id,
            name,
            default_base_url=base_url,
            api_key_prefix=api_key_prefix,
        )
    except ValueError as exc:
        click.echo(click.style(f"Error: {exc}", fg="red"))
        raise SystemExit(1) from exc
    click.echo(f"✓ Custom provider '{name}' ({provider_id}) created.")
    if base_url:
        click.echo(f"  base_url: {base_url}")
    click.echo(
        "  Run 'copaw models add-model' to add models, "
        "then 'copaw models config-key' to set the API key.",
    )


@models_group.command("remove-provider")
@click.argument("provider_id")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
def remove_provider_cmd(provider_id: str, yes: bool) -> None:
    """Remove a custom provider."""
    if is_builtin(provider_id):
        click.echo(
            click.style(
                f"Error: '{provider_id}' is a built-in provider and "
                "cannot be removed.",
                fg="red",
            ),
        )
        raise SystemExit(1)
    if not yes:
        if not click.confirm(
            f"Delete custom provider '{provider_id}' and all its models?",
        ):
            return
    try:
        delete_custom_provider(provider_id)
    except ValueError as exc:
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
        add_model(provider_id, ModelInfo(id=model_id, name=model_name))
    except ValueError as exc:
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
        remove_model(provider_id, model_id)
    except ValueError as exc:
        click.echo(click.style(f"Error: {exc}", fg="red"))
        raise SystemExit(1) from exc
    click.echo(f"✓ Model '{model_id}' removed from '{provider_id}'.")


# ---------------------------------------------------------------------------
# Local model management commands
# ---------------------------------------------------------------------------


@models_group.command("download")
@click.argument("repo_id")
@click.option(
    "--file",
    "-f",
    "filename",
    default=None,
    help="Specific file to download (e.g., 'model.Q4_K_M.gguf')",
)
@click.option(
    "--backend",
    "-b",
    type=click.Choice(["llamacpp", "mlx"]),
    default="llamacpp",
    help="Target backend",
)
@click.option(
    "--source",
    "-s",
    type=click.Choice(["huggingface", "modelscope"]),
    default="huggingface",
    help="Download source",
)
def download_cmd(
    repo_id: str,
    filename: str | None,
    backend: str,
    source: str,
) -> None:
    """Download a model from Hugging Face Hub or ModelScope.

    \b
    Examples:
      copaw models download TheBloke/Mistral-7B-Instruct-v0.2-GGUF
      copaw models download TheBloke/Mistral-7B-Instruct-v0.2-GGUF \\
          -f mistral-7b-instruct-v0.2.Q4_K_M.gguf
      copaw models download Qwen/Qwen2-0.5B-Instruct-GGUF --source modelscope
    """
    try:
        from ..local_models import (
            LocalModelManager,
            BackendType,
            DownloadSource,
        )
    except ImportError as exc:
        click.echo(
            click.style(
                "Local model dependencies not installed. "
                "Install with: pip install 'copaw[local]'",
                fg="red",
            ),
        )
        raise SystemExit(1) from exc

    backend_type = BackendType(backend)
    source_type = DownloadSource(source)

    suffix = f" ({filename})" if filename else ""
    click.echo(f"Downloading {repo_id}{suffix} from {source}...")

    try:
        info = LocalModelManager.download_model_sync(
            repo_id=repo_id,
            filename=filename,
            backend=backend_type,
            source=source_type,
        )
    except ImportError as exc:
        click.echo(click.style(f"Error: {exc}", fg="red"))
        raise SystemExit(1) from exc
    except Exception as exc:
        click.echo(click.style(f"Download failed: {exc}", fg="red"))
        raise SystemExit(1) from exc

    size_mb = info.file_size / (1024 * 1024)
    click.echo(f"Done! Model saved to: {info.local_path}")
    click.echo(f"  Size: {size_mb:.1f} MB")
    click.echo(f"  ID: {info.id}")
    click.echo(f"  Backend: {info.backend.value}")
    click.echo(
        f"\nTo use this model, run:\n"
        f"  copaw models set-llm  (select '{backend}' provider)",
    )


@models_group.command("local")
@click.option(
    "--backend",
    "-b",
    type=click.Choice(["llamacpp", "mlx"]),
    default=None,
    help="Filter by backend",
)
def list_local_cmd(backend: str | None) -> None:
    """List all downloaded local models."""
    try:
        from ..local_models import list_local_models, BackendType
    except ImportError:
        click.echo(
            "Local model support not installed. "
            "Install with: pip install 'copaw[local]'",
        )
        return

    backend_type = BackendType(backend) if backend else None
    models = list_local_models(backend=backend_type)

    if not models:
        click.echo("No local models downloaded.")
        click.echo("Use 'copaw models download <repo_id>' to download one.")
        return

    click.echo(f"\n=== Local Models ({len(models)}) ===")
    for m in models:
        size_mb = m.file_size / (1024 * 1024)
        click.echo(f"\n{'─' * 44}")
        click.echo(f"  {m.display_name}")
        click.echo(f"  ID:      {m.id}")
        click.echo(f"  Backend: {m.backend.value}")
        click.echo(f"  Source:  {m.source.value}")
        click.echo(f"  Size:    {size_mb:.1f} MB")
        click.echo(f"  Path:    {m.local_path}")
    click.echo()


@models_group.command("remove-local")
@click.argument("model_id")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
def remove_local_cmd(model_id: str, yes: bool) -> None:
    """Remove a downloaded local model."""
    try:
        from ..local_models import delete_local_model
    except ImportError as exc:
        click.echo(
            click.style(
                "Local model support not installed. "
                "Install with: pip install 'copaw[local]'",
                fg="red",
            ),
        )
        raise SystemExit(1) from exc

    if not yes:
        if not click.confirm(f"Delete local model '{model_id}'?"):
            return
    try:
        delete_local_model(model_id)
    except ValueError as exc:
        click.echo(click.style(f"Error: {exc}", fg="red"))
        raise SystemExit(1) from exc
    click.echo(f"Done! Model '{model_id}' deleted.")


# ---------------------------------------------------------------------------
# Ollama model management commands
# ---------------------------------------------------------------------------


@models_group.command("ollama-pull")
@click.argument("model_name")
def ollama_pull_cmd(model_name: str) -> None:
    """Download an Ollama model.

    \b
    Examples:
      copaw models ollama-pull mistral:7b
      copaw models ollama-pull qwen2.5:3b
    """
    from ..providers.ollama_manager import OllamaModelManager
    from ..providers.store import get_ollama_host

    click.echo(f"Downloading Ollama model: {model_name}...")
    try:
        host = get_ollama_host()
        OllamaModelManager.pull_model(model_name, host=host)
        click.echo(f"✓ Model '{model_name}' downloaded successfully.")
        click.echo("\nTo use this model, run:\n  copaw models set-llm")
    except ImportError as exc:
        click.echo(
            click.style(
                str(exc),
                fg="red",
            ),
        )
        raise SystemExit(1) from exc
    except Exception as exc:
        click.echo(click.style(f"Download failed: {exc}", fg="red"))
        raise SystemExit(1) from exc


@models_group.command("ollama-list")
def ollama_list_cmd() -> None:
    """List all Ollama models."""
    from ..providers.ollama_manager import OllamaModelManager
    from ..providers.store import get_ollama_host

    try:
        host = get_ollama_host()
        models = OllamaModelManager.list_models(host=host)
    except ImportError as exc:
        click.echo(
            click.style(
                str(exc),
                fg="red",
            ),
        )
        raise SystemExit(1) from exc
    except Exception as exc:
        click.echo(click.style(f"Error: {exc}", fg="red"))
        raise SystemExit(1) from exc

    if not models:
        click.echo("No Ollama models found.")
        click.echo("Use 'copaw models ollama-pull <model>' to download one.")
        return

    click.echo(f"\n=== Ollama Models ({len(models)}) ===")
    for m in models:
        size_gb = m.size / (1024 * 1024 * 1024)
        click.echo(f"\n{'─' * 44}")
        click.echo(f"  {m.name}")
        if m.size > 0:
            click.echo(f"  Size:    {size_gb:.2f} GB")
        if m.digest:
            click.echo(f"  Digest:  {m.digest[:16]}...")
    click.echo()


@models_group.command("ollama-remove")
@click.argument("model_name")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
def ollama_remove_cmd(model_name: str, yes: bool) -> None:
    """Remove an Ollama model.

    \b
    Examples:
      copaw models ollama-remove mistral:7b
      copaw models ollama-remove qwen2.5:3b -y
    """
    from ..providers.ollama_manager import OllamaModelManager
    from ..providers.store import get_ollama_host

    if not yes:
        if not click.confirm(f"Delete Ollama model '{model_name}'?"):
            return

    try:
        host = get_ollama_host()
        OllamaModelManager.delete_model(model_name, host=host)
        click.echo(f"✓ Model '{model_name}' deleted.")
    except ImportError as exc:
        click.echo(
            click.style(
                str(exc),
                fg="red",
            ),
        )
        raise SystemExit(1) from exc
    except Exception as exc:
        click.echo(click.style(f"Error: {exc}", fg="red"))
        raise SystemExit(1) from exc
