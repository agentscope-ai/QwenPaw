# -*- coding: utf-8 -*-
"""Static CLI discovery and Click overlays shared by every command group."""

from copy import copy
from dataclasses import dataclass
from functools import wraps
import json
import logging

import click

logger = logging.getLogger(__name__)
_ALIASES = {
    "channel": "channels",
    "chat": "chats",
    "agent": "agents",
    "plugins": "plugin",
}


def canonical(path):
    return (
        ((_ALIASES.get(path[0], path[0]),) + tuple(path[1:])) if path else ()
    )


def read_settings():
    """Read plugin intent without config migration, writes or app startup."""
    from ..config.utils import get_config_path

    path = get_config_path()
    try:
        if not path.exists():
            return {}
        raw = path.read_text(encoding="utf-8")
        try:
            data = json.loads(raw)
        except ValueError:
            from json_repair import repair_json

            data = repair_json(raw, return_objects=True)
        if not isinstance(data, dict) or not isinstance(
            data.get("plugins", {}),
            dict,
        ):
            raise ValueError("plugins must be an object")
        return data.get("plugins", {})
    except (OSError, ValueError) as exc:
        raise click.ClickException(
            f"Cannot read plugin settings: {exc}",
        ) from exc


@dataclass(frozen=True)
class Mount:
    manifest: object
    source: object
    declaration: object


class CliCatalog:
    """One invocation's metadata snapshot; command execution rechecks state."""

    def __init__(self):
        from ..config.utils import get_plugins_dir
        from ..plugins.discovery import DiscoveryIssue, discover_plugins
        from ..plugins.settings import is_plugin_enabled
        from .._version_compat import check_plugin_version_compat

        self.mounts = {}
        self.plugins = []
        self.enabled_plugins = []
        self.issues = ()
        try:
            self.settings = read_settings()
        except click.ClickException as exc:
            logger.debug("Plugin discovery unavailable: %s", exc)
            self.settings = {}
            return
        discovered = discover_plugins([get_plugins_dir()])
        self.issues = discovered.issues
        for manifest, source in discovered.plugins:
            raw = self.settings.get(manifest.id)
            if raw is not None and not isinstance(raw, dict):
                self.issues += (
                    DiscoveryIssue(
                        source,
                        "Plugin settings must be an object",
                    ),
                )
                continue
            try:
                compatible, _ = check_plugin_version_compat(manifest)
            except ValueError as exc:
                self.issues += (
                    DiscoveryIssue(
                        source,
                        f"Invalid host-version requirement: {exc}",
                    ),
                )
                continue
            if not compatible:
                continue
            self.plugins.append((manifest, source))
            if not is_plugin_enabled(self.settings.get(manifest.id)):
                continue
            self.enabled_plugins.append((manifest, source))
            for declaration in manifest.cli:
                self.mounts.setdefault(canonical(declaration.path), []).append(
                    Mount(manifest, source, declaration),
                )

    def children(self, path):
        return {p[-1] for p in self.mounts if p[:-1] == path}


def catalog_for(ctx):
    root = ctx.find_root()
    if "plugin_cli_catalog" not in root.meta:
        root.meta["plugin_cli_catalog"] = CliCatalog()
    return root.meta["plugin_cli_catalog"]


def command_path(ctx):
    parts = []
    while ctx.parent is not None:
        parts.append(ctx.command.name or ctx.info_name)
        ctx = ctx.parent
    return canonical(tuple(reversed(parts)))


class ExtensibleGroup(click.Group):
    """Host command lookup combining native commands and plugin mounts.

    Native commands keep precedence. Plugin-owned paths reject competing
    mounts, and child groups resolve extensions in the same invocation.
    """

    group_class = type

    def _list_builtin_commands(self, ctx):
        return super().list_commands(ctx)

    def _get_builtin_command(self, ctx, name):
        return super().get_command(ctx, name)

    def list_commands(self, ctx):
        return sorted(
            set(self._list_builtin_commands(ctx))
            | catalog_for(ctx).children(command_path(ctx)),
        )

    def get_command(self, ctx, name):
        command = self._get_builtin_command(ctx, name)
        if (
            command is not None
            and getattr(self, "_plugin_owner_id", None) is None
        ):
            return overlay(command)
        path = command_path(ctx) + (name,)
        mounts = catalog_for(ctx).mounts.get(path, ())
        if command is not None:
            return ConflictingCommand(name) if mounts else overlay(command)
        return PluginCommand(name, mounts) if mounts else None


class GroupOverlay(ExtensibleGroup):
    """Invocation-local child mounting without mutating cached Click groups."""

    def __init__(self, group):
        self.__dict__ = group.__dict__.copy()
        self.original = group

    def _list_builtin_commands(self, ctx):
        return self.original.list_commands(ctx)

    def _get_builtin_command(self, ctx, name):
        return self.original.get_command(ctx, name)


def overlay(command):
    if isinstance(command, click.Group) and not isinstance(
        command,
        ExtensibleGroup,
    ):
        return GroupOverlay(command)
    return command


def _execution_tree(command, session, plugin_id, registration):
    command = copy(command)
    command._plugin_owner_id = plugin_id

    def wrap(callback, prepare=False):
        @wraps(callback)
        def execute(*args, **kwargs):
            ctx = click.get_current_context()
            try:
                if prepare and ctx.invoked_subcommand is not None:
                    return callback(*args, **kwargs)
                return session.execute(
                    plugin_id,
                    registration,
                    callback,
                    *args,
                    **kwargs,
                )
            except (click.ClickException, click.exceptions.Exit, click.Abort):
                raise
            except Exception as exc:
                raise click.ClickException(
                    f"Plugin '{plugin_id}': {exc}",
                ) from exc

        return execute

    if command.callback is not None:
        command.callback = wrap(
            command.callback,
            prepare=isinstance(command, click.Group),
        )
    if isinstance(command, click.Group):
        if command._result_callback is not None:
            command._result_callback = wrap(command._result_callback)
        command.commands = {
            name: _execution_tree(child, session, plugin_id, registration)
            for name, child in command.commands.items()
        }
    return overlay(command)


class ConflictingCommand(click.Command):
    """Keep help usable while refusing an ambiguous plugin-owned path."""

    def make_context(self, info_name, args, parent=None, **extra):
        raise click.ClickException(f"CLI path conflict: {info_name}")


class PluginCommand(click.Command):
    """A metadata-only placeholder until Click parses this command's args."""

    def __init__(self, name, mounts):
        self.mounts = mounts
        super().__init__(name, help=mounts[0].declaration.help)

    def make_context(self, info_name, args, parent=None, **extra):
        from .plugin_session import session_for
        from ..plugins.settings import is_plugin_enabled

        if len(self.mounts) != 1:
            owners = ", ".join(m.manifest.id for m in self.mounts)
            raise click.ClickException(f"CLI path conflict: {owners}")
        mount = self.mounts[0]
        if not is_plugin_enabled(read_settings().get(mount.manifest.id)):
            raise click.ClickException(
                f"Plugin '{mount.manifest.id}' is disabled",
            )
        session = session_for(parent)
        try:
            session.load(mount.manifest, mount.source)
            contributions = session.loader.registry.cli_contributions
            row = contributions.get((mount.manifest.id, mount.declaration.id))
            if row is None:
                raise click.ClickException(
                    f"CLI ID not registered: {mount.declaration.id}",
                )
            session.run(row.admit())
            command = row.spec.build(
                session.context(mount.manifest.id, parent),
            )
            if not isinstance(command, click.Command):
                raise click.ClickException(
                    "CLI factory must return a Click command",
                )
            if isinstance(command, click.Group) != (
                mount.declaration.kind == "group"
            ):
                raise click.ClickException(
                    "CLI factory kind differs from manifest",
                )
            command = _execution_tree(
                command,
                session,
                mount.manifest.id,
                (mount.declaration.id, row),
            )
            command.name = mount.declaration.path[-1]
            return command.make_context(
                info_name,
                args,
                parent=parent,
                **extra,
            )
        except (click.ClickException, click.exceptions.Exit, click.Abort):
            raise
        except Exception as exc:
            raise click.ClickException(
                f"Plugin '{mount.manifest.id}': {exc}",
            ) from exc
