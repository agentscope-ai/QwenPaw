# -*- coding: utf-8 -*-
"""Invocation-owned bridge between synchronous Click and plugin lifecycle."""

import asyncio
from contextlib import asynccontextmanager, ExitStack
import inspect

import click

_retained_sessions = set()


class PluginSession:
    """Own loaded plugins and async resources until the root command closes.

    Synchronous Click callbacks enter the same Runner for async work.
    Cleanup must finish before source leases and the Runner are released.
    """

    def __init__(self, include_channel_descriptors=False):
        self.include_channel_descriptors = include_channel_descriptors
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

    def get_loader(self):
        """Share one loader and event loop for the lifetime of the command."""
        if self.loader is not None:
            return self.loader
        from fastapi import FastAPI

        from ..config.utils import get_plugins_dir
        from ..plugins.loader import PluginLoader

        loader = self.run(
            PluginLoader.create_for_registration(
                [get_plugins_dir()],
                include_channel_descriptors=self.include_channel_descriptors,
            ),
        )
        if loader.registry.get_plugin_http_app() is None:
            loader.registry.set_plugin_http_app(FastAPI())
        self.loader = loader
        return self.loader

    def load_registration(self, manifest, source, settings=None):
        """Retain source custody and register an invocation's contributions."""
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
        from ..plugins.discovery import read_manifest
        from ..plugins.settings import read_plugin_intent
        from ..plugins.source_usage import source_reader
        from ..plugins.updates import is_update_source_available
        from .plugin_cli import read_settings

        self.sources.enter_context(source_reader(source))
        if read_plugin_intent(key, plugins_dir=source.parent):
            raise click.ClickException(f"Plugin '{key}' was uninstalled")
        if not is_update_source_available(key, source):
            raise click.ClickException(f"Plugin '{key}' update is incomplete")
        fresh = read_manifest(source / "plugin.json")
        if fresh != manifest:
            raise click.ClickException("Plugin source changed; retry command")
        settings = (
            (read_settings().get(manifest.id) or {})
            if settings is None
            else settings
        )
        loader = self.get_loader()
        record = self.run(
            loader.load_registration(
                fresh,
                source,
                settings,
                include_descriptor=self.include_channel_descriptors,
            ),
        )
        if record.status == "failed":
            raise click.ClickException(
                f"Plugin '{manifest.id}': " + "; ".join(record.diagnostics),
            )
        self.records[key] = record
        return record

    def context(self, plugin_id, click_ctx):
        from ..plugins.cli import CliContext
        from ..utils.io_utils import run_sync_io
        from ..utils.runtime_api import async_api_client
        from .http import local_runtime_url

        sdk = self.loader.lifecycle.get_instance(plugin_id).sdk_context
        options = click_ctx.find_root().obj or {}

        @asynccontextmanager
        async def local_runtime_api():
            target = await run_sync_io(
                local_runtime_url,
                require_verified=True,
            )
            if target is None:
                yield None
            else:
                async with async_api_client(f"{target}/api/") as client:
                    yield client

        return CliContext(
            plugin_id,
            sdk.config,
            sdk.storage,
            sdk.resources,
            sdk.logger,
            options.get("host", "127.0.0.1"),
            options.get("port", 8088),
            self.run,
            local_runtime_api,
        )

    def execute(self, plugin_id, reference, callback):
        from .plugin_cli import read_settings

        if plugin_id not in self.admitted:
            settings = read_settings().get(plugin_id) or {}
            if not isinstance(settings, dict):
                raise click.ClickException("Plugin settings must be an object")
            if not settings.get("enabled", True):
                raise click.ClickException(f"Plugin '{plugin_id}' is disabled")
        task = done = None

        async def enter():
            nonlocal task, done

            await reference.activate()
            ready = asyncio.get_running_loop().create_future()
            done = asyncio.Event()

            async def hold():
                try:
                    with reference.invocation():
                        ready.set_result(None)
                        await done.wait()
                except BaseException as exc:
                    if not ready.done():
                        ready.set_exception(exc)
                    raise

            task = asyncio.create_task(hold())
            await ready

        try:
            # Admission can be interrupted after creating its activity task.
            # Own that task through the same cleanup as the command callback.
            self.run(enter())
            self.admitted.add(plugin_id)
            return callback()
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


def session_for(ctx, include_channel_descriptors=False):
    root = ctx.find_root()
    if "plugin_session" not in root.meta:
        session = PluginSession(include_channel_descriptors)
        root.meta["plugin_session"] = session
        root.call_on_close(session.close)
    return root.meta["plugin_session"]
