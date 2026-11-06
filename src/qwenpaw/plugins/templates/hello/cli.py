# -*- coding: utf-8 -*-
"""Terminal example sharing the public SDK's owned storage and lifecycle."""

import click

from qwenpaw.plugins.cli import CliContext


def build_cli(call: CliContext) -> click.Group:
    @click.group(invoke_without_command=True)
    @click.option("--name", default="world", show_default=True)
    @click.pass_context
    def hello(ctx, name):
        """Greet someone from a managed terminal invocation."""
        ctx.obj = {"name": name}
        if ctx.invoked_subcommand is None:
            click.echo(ctx.get_help())

    @hello.command()
    @click.pass_context
    def greet(ctx):
        """Count and display terminal greetings."""

        async def increment():
            count = await call.storage.aread_json("cli-count.json", 0) + 1
            await call.storage.awrite_json("cli-count.json", count)
            return count

        count = call.run(increment())
        click.echo(f"Hello {ctx.obj['name']} ({count})")

    return hello
