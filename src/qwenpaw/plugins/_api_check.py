# -*- coding: utf-8 -*-
"""Conservative member-version inference; never imports plugin code.

This is a compatibility aid, not a substitute for an author's type checker.
Only known SDK values are inferred, so similarly named third-party methods
are not rejected. Unclassified values remain outside this analysis.
"""

import ast
import inspect
from functools import lru_cache
from importlib import import_module

from packaging.version import InvalidVersion, Version

_RESOURCE = "qwenpaw.plugins.resources.ResourceScope"
_PLUGIN = "qwenpaw.plugins.PluginContext"
_TOOL_CONTEXTS = {
    "qwenpaw.plugins.tools.ToolContext",
    "qwenpaw.plugins.apps.AppContext",
    "qwenpaw.plugins.markets.MarketContext",
    "qwenpaw.plugins.commands.CommandContext",
    "qwenpaw.plugins.hooks.HookContext",
    "qwenpaw.plugins.providers.ProviderContext",
    "qwenpaw.plugins.channels.ChannelContext",
    "qwenpaw.plugins.memory.MemoryContext",
    "qwenpaw.plugins.stops.StopContext",
    "qwenpaw.plugins.workflows.WorkflowContext",
}
_WORKER = "qwenpaw.plugins.channel_workers.ChannelWorkerContext"
_MODE = "qwenpaw.plugins.modes.ModeContext"
_SERVICES = {
    "resources": _RESOURCE,
    "storage": "qwenpaw.plugins.storage.PluginStorage",
    "media": "qwenpaw.plugins.storage.MediaStore",
    "logger": "qwenpaw.plugins.logging.PluginLogger",
    "config": "qwenpaw.plugins.storage.PluginConfig",
}
_TOOL_SERVICES = {
    **_SERVICES,
    "models": "qwenpaw.plugins.models.ModelService",
    "runs": "qwenpaw.plugins.runs.RunService",
    "workspace_ops": "qwenpaw.plugins.workspace.WorkspaceService",
    "checkpoints": "qwenpaw.plugins.checkpoints.CheckpointService",
    "identity": "qwenpaw.plugins.context.RequestContext",
}
_WORKER_SERVICES = {
    key: value for key, value in _SERVICES.items() if key != "config"
} | {
    "delivery": "qwenpaw.plugins.channel_workers.ChannelDelivery",
    "auth": "qwenpaw.plugins.channel_workers.ChannelAuth",
    "approvals": "qwenpaw.plugins.channel_workers.ChannelApprovals",
    "ingress": "qwenpaw.plugins.channel_ingress.ChannelIngress",
}
_CONTEXT_SERVICES = {
    **{context: _TOOL_SERVICES for context in _TOOL_CONTEXTS},
    _PLUGIN: _SERVICES,
    _WORKER: _WORKER_SERVICES,
    _MODE: {key: _TOOL_SERVICES[key] for key in ("config", "identity")},
}
_PROTOCOLS = {
    f"qwenpaw.plugins.{module}.{symbol}.{method}"
    for module, symbol, methods in (
        ("resources", "ResourceScope", ("__aenter__", "__aexit__")),
        ("resources", "Registration", ("__aenter__", "__aexit__")),
        ("testing", "TestFault", ("__enter__", "__exit__")),
        ("testing", "PluginTestHost", ("__aenter__", "__aexit__")),
        (
            "testing",
            "TestConnection",
            ("__aenter__", "__aexit__", "__aiter__", "__anext__"),
        ),
    )
    for method in methods
}
_RESULTS = {
    f"{_RESOURCE}.child": _RESOURCE,
    f"{_RESOURCE}.__aenter__": _RESOURCE,
}


@lru_cache(maxsize=256)
def _positional_parameters(symbol, member):
    """Inspect only caller-allowlisted SDK declarations, never plugin code."""
    module, _, name = symbol.rpartition(".")
    value = getattr(import_module(module), name)
    if member:
        value = getattr(value, member, None)
    try:
        return tuple(
            parameter.name
            for parameter in inspect.signature(value).parameters.values()
            if parameter.kind
            in {parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD}
            and parameter.name not in {"self", "cls"}
        )
    except (TypeError, ValueError):
        return ()


def check_member_versions(tree, aliases, declared, versions, exports, reject):
    public_protocols = set()
    try:
        minimum = Version(declared)
    except (InvalidVersion, TypeError):
        minimum = None  # The manifest validator reports malformed versions.
    types = {}

    def resolve(node, local):
        if isinstance(node, ast.Name):
            return local.get(node.id, aliases.get(node.id, ""))
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return aliases.get(node.value, node.value)
        if isinstance(node, ast.Await):
            return resolve(node.value, local)
        if isinstance(node, ast.Attribute):
            parent = resolve(node.value, local)
            services = _CONTEXT_SERVICES.get(parent, {})
            if node.attr in services:
                return services[node.attr]
            if (
                parent == "qwenpaw.plugins.apps.AppContext"
                and node.attr == "conversations"
            ):
                return "qwenpaw.plugins.conversations.ConversationService"
            return f"{parent}.{node.attr}" if parent else ""
        if isinstance(node, ast.Call):
            name = resolve(node.func, local)
            if (
                name in exports
                or name in versions
                or name in _CONTEXT_SERVICES
            ):
                return name
            return _RESULTS.get(name, "")
        return ""

    members = {
        f"{symbol}.{member}": since
        for symbol, items in versions.items()
        for member, since in items
    }

    def require(node, name):
        since = members.get(name, exports.get(name))
        if since is None and name.rpartition(".")[0] in _TOOL_CONTEXTS:
            since = members.get(
                "qwenpaw.plugins.tools.ToolContext." + name.rpartition(".")[2],
            )
        if since and minimum is not None and minimum < Version(since):
            reject(
                node,
                "sdk-version",
                f"{name} requires SDK >= {since}; declared {declared}",
            )

    def walk(node, local):
        if isinstance(node, ast.ImportFrom) and not node.level:
            for item in node.names:
                require(node, f"{node.module}.{item.name}")
        if isinstance(node, ast.Name):
            require(node, resolve(node, local))
        # Function-local types must not contaminate another callback that
        # happens to use the same variable name.
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            local = dict(local)
            arguments = (
                node.args.posonlyargs + node.args.args + node.args.kwonlyargs
            )
            for argument in arguments:
                local.pop(argument.arg, None)
                if argument.annotation:
                    local[argument.arg] = resolve(argument.annotation, local)
            if node.name == "register" and len(node.args.args) == 2:
                local[node.args.args[1].arg] = _PLUGIN
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
            value = resolve(node.value, local)
            if isinstance(node, ast.AnnAssign):
                value = resolve(node.annotation, local) or value
            for target in targets:
                if isinstance(target, ast.Name):
                    local[target.id] = value
        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                value = resolve(item.context_expr, local)
                if isinstance(node, ast.AsyncWith):
                    require(item.context_expr, f"{value}.__aenter__")
                if isinstance(item.optional_vars, ast.Name):
                    local[item.optional_vars.id] = value
        if isinstance(node, ast.Attribute):
            name = resolve(node, local)
            require(node, name)
            if name in _PROTOCOLS:
                public_protocols.add(id(node))
        if isinstance(node, ast.Call):
            name = resolve(node.func, local)
            for keyword in node.keywords:
                if keyword.arg:
                    require(node, f"{name}.{keyword.arg}")
            symbol, _, member = name.rpartition(".")
            if name in versions:
                symbol, member = name, ""
            if symbol in versions and symbol in exports:
                parameters = _positional_parameters(symbol, member)
                supplied = {keyword.arg for keyword in node.keywords}
                for argument, parameter in zip(node.args, parameters):
                    if isinstance(argument, ast.Starred):
                        break  # Unknown expansion must not shift later arguments.
                    supplied.add(parameter)
                    require(node, f"{name}.{parameter}")
                if None not in supplied and not any(
                    isinstance(argument, ast.Starred) for argument in node.args
                ):
                    for parameter in parameters:
                        if parameter not in supplied:
                            require(node, f"{name}.{parameter}.default")
        for child in ast.iter_child_nodes(node):
            walk(child, local)

    walk(tree, types)
    return public_protocols
