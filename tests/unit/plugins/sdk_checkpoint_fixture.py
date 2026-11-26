# -*- coding: utf-8 -*-
"""Minimal command and HTTP adapters to exercise the real restore engine."""

from .sdk_author_fixture import make_plugin

SOURCE = """
import json
from dataclasses import asdict
from qwenpaw.plugins.apps import PawApp
from qwenpaw.plugins.commands import CommandSpec, CommandResult
from qwenpaw.plugins.messages import Message, ContentBlock

class Plugin:
    def register(self, ctx):
        async def command(call, args):
            action, _, value = args.partition(' ')
            if action == 'timeline':
                result = [asdict(item) for item in await call.checkpoints.timeline()]
            elif action == 'snapshot':
                result = asdict(await call.checkpoints.snapshot(name=value))
            else:
                result = asdict(await call.checkpoints.restore(value, dry_run=action == 'preview'))
            return CommandResult('reply', Message('assistant', (ContentBlock(text=json.dumps(result)),)))
        ctx.register_command(CommandSpec('contract-checkpoint', command, control=True))
        ctx.register_app(PawApp(app_id='checkpoint-contract').enable_standard_capabilities())
plugin = Plugin()
"""


def make_checkpoint_plugin(tmp_path):
    return make_plugin(
        tmp_path,
        SOURCE,
        ["apps", "commands"],
        plugin_id="checkpoint-contract",
        sdk_version="1.2",
    )
