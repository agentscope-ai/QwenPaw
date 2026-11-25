# -*- coding: utf-8 -*-
"""Static CLI discovery and Click overlays shared by every command group."""

from copy import copy
from dataclasses import dataclass
from functools import wraps
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from ..plugins.architecture import CliDeclaration, PluginManifest
    from .plugin_session import PluginSession

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
    from ..config.utils import get_config_path, parse_config_data

    path = get_config_path()
    try:
        data, issue = parse_config_data(path.read_bytes())
        if data is None:
            raise ValueError(issue)
        settings = data.get("plugins", {})
        if not isinstance(settings, dict):
            raise ValueError("plugins must be an object")
        return settings
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise click.ClickException(
            f"Cannot read plugin settings: {exc}",
        ) from exc


@dataclass(frozen=True)
class Mount:
    manifest: "PluginManifest"
    source: Path
    declaration: "CliDeclaration"


class CliCatalog:
    """One invocation's metadata snapshot; command execution rechecks state."""

    def __init__(self):
        from ..config.utils import get_plugins_dir
        from ..plugins.discovery import DiscoveryIssue, discover_plugins
        from ..plugins.settings import is_plugin_enabled
        from ..plugins.updates import is_update_source_available
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
            try:
                if not is_update_source_available(manifest.id, source):
                    continue
            except (OSError, ValueError) as exc:
                self.issues += (DiscoveryIssue(source, str(exc)),)
                continue
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

    def has_descendants(self, path):
        depth = len(path)
        return any(
            candidate[:depth] == path and len(candidate) > depth
            for candidate in self.mounts
        )


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


def missing_cli_root_messages(ctx, catalog):
    """Diagnose missing top-level parents without building plugin groups."""
    root = ctx.find_root()
    if not isinstance(root.command, ExtensibleGroup):
        return ()
    available = set(root.command.list_commands(root))
    missing = {path[0] for path in catalog.mounts if path[0] not in available}
    return tuple(_missing_parent((name,)) for name in sorted(missing))


def _missing_parent(path):
    return f"Plugin CLI requires a parent command group at: {' '.join(path)}"


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
        native = self._list_builtin_commands(ctx)
        added = catalog_for(ctx).children(command_path(ctx)).difference(native)
        return [*native, *sorted(added)]

    def get_command(self, ctx, name):
        command = self._get_builtin_command(ctx, name)
        execution = getattr(self, "_plugin_execution", None)
        if command is not None and execution is None:
            return overlay(command)
        path = command_path(ctx) + (name,)
        catalog = catalog_for(ctx)
        mounts = catalog.mounts.get(path, ())
        if command is not None:
            return (
                UnavailableCommand(
                    name,
                    click.ClickException(f"CLI path conflict: {name}"),
                )
                if mounts
                else _execution_command(command, execution)
            )
        if mounts:
            return PluginCommand(name, mounts)
        if catalog.has_descendants(path):
            return UnavailableCommand(
                name,
                click.UsageError(_missing_parent(path), ctx),
            )
        return None


def overlay(command):
    if isinstance(command, click.Group) and not isinstance(
        command,
        ExtensibleGroup,
    ):
        # Preserve custom state and Click behavior on an invocation-local copy.
        # Empty slots keep the original instance layout for class assignment.
        group_type = type(
            "ExtensibleGroup",
            (ExtensibleGroup, type(command)),
            {"__slots__": (), "group_class": command.group_class},
        )
        command = copy(command)
        command.__class__ = group_type
    return command


@dataclass(frozen=True)
class _CliExecution:
    """Bind one registered contribution to commands resolved by Click."""

    session: "PluginSession"
    plugin_id: str
    reference: object


def _execution_command(command, execution):
    """Return an execution-bound command without modifying the original."""
    if getattr(command, "_plugin_execution", None) is execution:
        return command
    command = overlay(copy(command))
    command._plugin_execution = execution
    executing = False

    def wrap(callback, prepare=False):
        @wraps(callback)
        def execute(*args, **kwargs):
            ctx = click.get_current_context()
            try:
                if executing or (
                    prepare and ctx.invoked_subcommand is not None
                ):
                    return callback(*args, **kwargs)

                def invoke():
                    nonlocal executing
                    executing = True
                    try:
                        return callback(*args, **kwargs)
                    finally:
                        executing = False

                return execution.session.execute(
                    execution.plugin_id,
                    execution.reference,
                    invoke,
                )
            except (click.ClickException, click.exceptions.Exit, click.Abort):
                raise
            except Exception as exc:
                raise click.ClickException(
                    f"Plugin '{execution.plugin_id}': {exc}",
                ) from exc

        return execute

    if isinstance(command, click.Group):
        if command.callback is not None:
            command.callback = wrap(command.callback, prepare=True)
        if command._result_callback is not None:
            command._result_callback = wrap(command._result_callback)
        invoke = command.invoke
        if getattr(invoke, "__func__", invoke) is not click.Group.invoke:
            execute_default = wrap(invoke)

            @wraps(invoke)
            def invoke_group(ctx):
                # Click resolves child help during dispatch. A group with
                # no pending child can execute its own default action.
                pending = getattr(ctx, "_protected_args", None)
                if pending is None:
                    pending = ctx.protected_args  # Click 8.1
                if pending or not command.invoke_without_command:
                    return invoke(ctx)
                return execute_default(ctx)

            command.invoke = invoke_group
    else:
        command.invoke = wrap(command.invoke)
    return command


class UnavailableCommand(click.Command):
    """Explain why a plugin path cannot be invoked."""

    def __init__(self, name, error):
        super().__init__(name)
        self.error = error

    def make_context(self, info_name, args, parent=None, **extra):
        raise self.error


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
            session.load_registration(mount.manifest, mount.source)
            reference = session.loader.registry.get_cli(
                mount.manifest.id,
                mount.declaration.id,
            )
            if reference is None:
                raise click.ClickException(
                    f"CLI ID not registered: {mount.declaration.id}",
                )
            session.run(reference.admit())
            command = reference.spec.build(
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
            command = _execution_command(
                command,
                _CliExecution(
                    session,
                    mount.manifest.id,
                    reference,
                ),
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
