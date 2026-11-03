# -*- coding: utf-8 -*-
"""Invocation-owned bridge between synchronous Click and plugin lifecycle."""

import asyncio
from contextlib import ExitStack
import inspect

import click

_retained_sessions = set()


class PluginSession:
    """Own loaded plugins and async resources until the root command closes.

    Synchronous Click callbacks enter the same Runner for async work.
    Cleanup must finish before source leases and the Runner are released.
    """

    def __init__(self):
        self.runner = asyncio.Runner()
        self.sources = ExitStack()
        self.loader = None
        self.records = {}
        self.admitted = set()
        self.closed = False

    def run(self, operation):
        """Run an awaitable, waiting for its cleanup when interrupted."""
        if self.closed:
            if inspect.iscoroutine(operation):
                operation.close()
            raise click.ClickException("Plugin session has closed")
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            if inspect.iscoroutine(operation):
                operation.close()
            raise RuntimeError(
                "CliContext.run must be called from synchronous command code",
            )

        async def await_operation():
            return await operation

        task = self.runner.get_loop().create_task(await_operation())

        async def wait_task():
            # Runner cancels its waiter on SIGINT; the operation owns cleanup.
            return await asyncio.shield(task)

        try:
            return self.runner.run(wait_task())
        except (KeyboardInterrupt, asyncio.CancelledError):
            task.cancel()
            while not task.done():
                try:
                    self.runner.run(wait_task())
                except KeyboardInterrupt:
                    continue
                except BaseException:
                    break
            try:
                task.result()
            except BaseException:
                pass
            raise click.Abort() from None

    async def _loader(self):
        from ..config.utils import get_plugins_dir
        from ..plugins.loader import PluginLoader

        if self.loader is None:
            # TODO: Extract shared interpreter and dependency-site selection
            # into common runtime bootstrap. CLI currently reuses channel
            # runtime settings without consuming channel send policy.
            from ..plugins.channel_bootstrap import (
                resolve_default_channel_runtime,
            )
            from ..utils.io_utils import run_sync_io

            runtime = await run_sync_io(
                resolve_default_channel_runtime,
                load_send_policy=False,
            )
            loader = await PluginLoader.create(
                [get_plugins_dir()],
                channel_runtime=runtime,
            )
            if loader.registry.get_plugin_http_app() is None:
                from fastapi import FastAPI

                loader.registry.set_plugin_http_app(FastAPI())
            self.loader = loader
        return self.loader

    def load(self, manifest, source, settings=None):
        for retained in tuple(_retained_sessions):
            if (
                retained.loader is not None
                and retained.loader.lifecycle.get_instance(manifest.id)
                is not None
            ):
                retained.close()
        key = manifest.id
        if key in self.records:
            return self.records[key]
        from ..plugins.source_usage import source_reader

        self.sources.enter_context(source_reader(source))
        result = self.run(self._load(manifest, source, settings))
        self.records[key] = result
        return result

    async def _load(self, manifest, source, settings):
        from ..plugins.discovery import read_manifest
        from .plugin_cli import read_settings

        fresh = read_manifest(source / "plugin.json")
        if fresh != manifest:
            raise click.ClickException("Plugin source changed; retry command")
        settings = (
            (read_settings().get(manifest.id) or {})
            if settings is None
            else settings
        )
        loader = await self._loader()
        binding = None
        if manifest.entry.backend:
            binding = loader.backend_resolver.resolve_registration(
                source,
                manifest,
            )
        if binding is not None:
            from ..plugins.dependency_maintenance import lease_environment
            from ..utils.io_utils import run_sync_io

            targets = await loader._python_backend.prepare_dependency_targets(
                binding.description,
            )
            await run_sync_io(lease_environment, targets.targets)
            targets.validate()
        record = await loader.load_plugin(
            fresh,
            source,
            settings,
            activate=False,
            allow_install=False,
            backend_binding=binding,
        )
        if record.status == "failed":
            raise click.ClickException(
                f"Plugin '{manifest.id}': " + "; ".join(record.diagnostics),
            )
        return record

    def context(self, plugin_id, click_ctx):
        from ..plugins.cli import CliContext

        sdk = self.loader.lifecycle.get_instance(plugin_id).sdk_context
        options = click_ctx.find_root().obj or {}
        return CliContext(
            plugin_id,
            sdk.config,
            sdk.storage,
            sdk.resources,
            sdk.logger,
            options.get("host", "127.0.0.1"),
            options.get("port", 8088),
            self.run,
        )

    def execute(self, plugin_id, registration, callback, /, *args, **kwargs):
        from .plugin_cli import read_settings

        if plugin_id not in self.admitted:
            settings = read_settings().get(plugin_id) or {}
            if not isinstance(settings, dict):
                raise click.ClickException("Plugin settings must be an object")
            if not settings.get("enabled", True):
                raise click.ClickException(f"Plugin '{plugin_id}' is disabled")
        loader = self.loader
        name, expected = registration
        if (
            loader.registry.cli_contributions.get((plugin_id, name))
            is not expected
        ):
            raise click.ClickException("CLI registration has been released")

        task = done = None

        async def enter():
            nonlocal task, done

            async with loader.plugin_lifecycle(plugin_id):
                instance = loader.lifecycle.get_instance(plugin_id)
                if not instance.activated:
                    await loader.run_plugin_startup_hooks(
                        plugin_id,
                        include_installation=False,
                    )
                    instance.activated = True
            ready = asyncio.Event()
            done = asyncio.Event()

            async def hold():
                with instance.activity.invocation():
                    ready.set()
                    await done.wait()

            task = asyncio.create_task(hold())
            await ready.wait()

        try:
            # Admission can be interrupted after creating its activity task.
            # Own that task through the same cleanup as the command callback.
            self.run(enter())
            self.admitted.add(plugin_id)
            return callback(*args, **kwargs)
        finally:
            if task is not None:

                async def leave():
                    done.set()
                    await task

                self.run(leave())

    def close(self):
        if self.closed:
            return

        async def dispose():
            from ..plugins.lifecycle import UnloadMode

            errors = []
            if self.loader is not None:
                reports = await self.loader.lifecycle.unload_all(
                    UnloadMode.UNLOAD,
                )
                for report in reports:
                    if (
                        not report.clean
                        or not report.quiescent
                        or report.needs_restart
                    ):
                        errors.extend(
                            report.errors or ["Plugin cleanup incomplete"],
                        )
            return errors

        try:
            errors = self.run(dispose())
        except BaseException:
            _retained_sessions.add(self)
            raise
        if errors:
            # Retain the Runner and source leases for a cleanup retry.
            _retained_sessions.add(self)
            raise click.ClickException("; ".join(errors))
        self.runner.close()
        self.sources.close()
        self.closed = True
        _retained_sessions.discard(self)


def session_for(ctx):
    root = ctx.find_root()
    if "plugin_session" not in root.meta:
        session = PluginSession()
        root.meta["plugin_session"] = session
        root.call_on_close(session.close)
    return root.meta["plugin_session"]
