# -*- coding: utf-8 -*-
"""Manage local resources through Plugin v2. Inference stays in the host."""

from functools import partial

from qwenpaw.plugins import PluginContext
from qwenpaw.plugins.cli import CliSpec
from qwenpaw.plugins.doctor import DOCTOR, DoctorSpec
from qwenpaw.plugins.providers import ProviderSpec

from .provider import LocalProvider
from .app import create_app


def build_cli(name, provider, call):
    from .cli import build_cli as build

    return build(name, provider, call)


async def check_local_files(provider, call):
    from .doctor import check_local_files as check

    return await check(provider, call)


async def check_local_server(call):
    from .doctor import check_local_server as check

    return await check(call)


class Plugin:
    def register(self, ctx: PluginContext):
        provider = LocalProvider(ctx)
        provider.handle = ctx.register_provider(
            ProviderSpec(
                id="qwenpaw-local",
                label="QwenPaw Local",
                protocol="openai-chat",
                connect=provider.connect,
                require_api_key=False,
                is_local=True,
            ),
        )
        ctx.on_activate(provider.activate)
        ctx.register_app(create_app(provider))
        for name in ("download", "local", "remove-local"):
            ctx.register_cli(CliSpec(name, partial(build_cli, name, provider)))
        ctx.register_extension(
            DOCTOR,
            DoctorSpec("local-model", partial(check_local_files, provider)),
        )
        ctx.register_extension(
            DOCTOR,
            DoctorSpec("local-server", check_local_server),
        )


plugin = Plugin()
