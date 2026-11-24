# -*- coding: utf-8 -*-
"""Local model commands using the plugin's owned management operations."""

import asyncio
import shlex

import click
import httpx

from qwenpaw.plugins import SDKError

from .io_helpers import finish, run_io
from .model_types import DownloadSource, PICCOLO_REPO_IDS


async def download_model(provider, model_id, source, timeout=7200.0):
    """Wait for a download and finish cancellation before releasing its owner."""
    started = False

    async def start():
        nonlocal started
        await provider.start_model_download(model_id, source=source)
        started = True

    try:
        await finish(start())
        manager = await provider.manager()
        async with asyncio.timeout(timeout):
            while True:
                progress = manager.get_model_download_progress()
                if progress["status"] in {"completed", "failed", "cancelled"}:
                    return progress
                await asyncio.sleep(0.5)
    except BaseException:
        if started:
            await finish(provider.cancel_model_download())
        raise


async def remove_model(provider, call, model_id):
    async with call.local_runtime_api() as api:
        if api is None:
            await provider.remove_downloaded_model(model_id)
            return
        response = await api.delete(
            "local-models/models",
            params={"model_id": model_id},
        )
        if response.is_error:
            try:
                detail = response.json().get("detail")
            except (ValueError, AttributeError):
                detail = None
            if detail:
                raise SDKError(str(detail))
        response.raise_for_status()


def build_cli(name, provider, call):
    """Build command definitions without opening model or download resources."""

    @click.command("download")
    @click.argument("repo_id")
    @click.option(
        "--file",
        "-f",
        "filename",
        default=None,
        help="Deprecated in the new local-model architecture",
    )
    @click.option(
        "--source",
        "-s",
        type=click.Choice(["huggingface", "modelscope"]),
        default="huggingface",
        help="Download source",
    )
    def download(repo_id, filename, source):
        """Download a local model repository.

        \b
        Examples:
          qwenpaw models download TheBloke/Mistral-7B-Instruct-v0.2-GGUF
          qwenpaw models download Qwen/Qwen2-0.5B-Instruct-GGUF --source modelscope
        """
        if filename:
            click.echo(
                click.style(
                    "Error: --file is no longer supported. "
                    "The current local-model architecture downloads whole repos.",
                    fg="red",
                ),
            )
            raise SystemExit(1)
        click.echo(f"Downloading {repo_id} from {source}...")
        try:
            progress = call.run(
                download_model(
                    provider,
                    repo_id,
                    DownloadSource(source),
                ),
            )
        except TimeoutError as exc:
            raise click.ClickException(
                "Timed out while waiting for the local model download to "
                "complete. The download has been cancelled; please try again.",
            ) from exc
        except click.Abort:
            raise
        except (ImportError, RuntimeError, ValueError, SDKError) as exc:
            click.echo(click.style(f"Download failed: {exc}", fg="red"))
            raise SystemExit(1) from exc
        if progress.get("status") != "completed":
            error = progress.get("error") or "unknown error"
            click.echo(click.style(f"Download failed: {error}", fg="red"))
            raise SystemExit(1)
        raw_size = progress.get("downloaded_bytes")
        size = raw_size if isinstance(raw_size, int) else 0
        click.echo(f"Done! Model saved to: {progress.get('local_path') or ''}")
        click.echo(f"  Size: {size / (1024 * 1024):.1f} MB")
        model_id = progress.get("model_name") or repo_id
        click.echo(f"  Name: {model_id}")
        if model_id in PICCOLO_REPO_IDS:
            click.echo(
                "Start this decision model from Local Models in the Console.",
            )
            return
        argument = shlex.quote(model_id)
        click.echo(
            "\nIf this model is not configured yet, run:\n"
            f"  qwenpaw models add-model qwenpaw-local "
            f"-m {argument} -n {argument}\n"
            "Then select it under QwenPaw Local:\n"
            "  qwenpaw models set-llm",
        )

    @click.command("local")
    def list_local():
        """List all downloaded local models."""

        async def read():
            manager = await provider.manager()
            return await run_io(manager.list_downloaded_models)

        models = call.run(read())
        if not models:
            click.echo("No local models downloaded.")
            click.echo(
                "Use 'qwenpaw models download <repo_id>' to download one.",
            )
            return
        click.echo(f"\n=== Local Models ({len(models)}) ===")
        for model in models:
            click.echo(f"\n{'─' * 44}")
            click.echo(f"  {model.name}")
            click.echo(f"  ID:      {model.id}")
            click.echo(f"  Size:    {model.size_bytes / (1024 * 1024):.1f} MB")
        click.echo()

    @click.command("remove-local")
    @click.argument("model_id")
    @click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
    def remove_local(model_id, yes):
        """Remove a downloaded local model."""
        if not yes and not click.confirm(f"Delete local model '{model_id}'?"):
            return
        try:
            call.run(remove_model(provider, call, model_id))
        except (ValueError, SDKError, httpx.HTTPError) as exc:
            click.echo(click.style(f"Error: {exc}", fg="red"))
            raise SystemExit(1) from exc
        click.echo(f"Done! Model '{model_id}' deleted.")

    return {
        "download": download,
        "local": list_local,
        "remove-local": remove_local,
    }[name]
