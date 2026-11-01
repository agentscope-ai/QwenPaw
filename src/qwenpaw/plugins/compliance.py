# -*- coding: utf-8 -*-
"""Explicit SDK dependency checks. Static inspection never imports a plugin."""

import ast
import hashlib
import json
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

PUBLIC_API = MappingProxyType(
    {
        "qwenpaw.plugins": (
            "Plugin",
            "PluginContext",
            "SDK_VERSION",
            "SDK_CAPABILITIES",
            "SDKError",
            "SDKAccessError",
            "SDKCompatibilityError",
            "SDKRestartRequiredError",
            "StaleContextError",
            "ResourceError",
            "ToolInputError",
            "PluginBusyError",
        ),
        "qwenpaw.plugins.logging": ("PluginLogger",),
        "qwenpaw.plugins.models": ("ModelService",),
        "qwenpaw.plugins.messages": ("Message", "ContentBlock", "Attachment"),
        "qwenpaw.plugins.tools": (
            "ToolSpec",
            "ToolContext",
            "ToolResult",
            "ToolEvent",
            "ConfigField",
        ),
        "qwenpaw.plugins.resources": (
            "ResourceOwner",
            "Registration",
            "ResourceScope",
        ),
        "qwenpaw.plugins.storage": (
            "PluginStorage",
            "MediaStore",
            "PluginConfig",
        ),
        "qwenpaw.plugins.commands": (
            "CommandSpec",
            "CommandContext",
            "CommandResult",
        ),
        "qwenpaw.plugins.hooks": (
            "HookPhase",
            "HookSpec",
            "HookContext",
            "HookResult",
            "ContextInjection",
        ),
        "qwenpaw.plugins.prompts": ("PromptSpec",),
        "qwenpaw.plugins.modes": ("ModeSpec", "ModeContext"),
        "qwenpaw.plugins.skills": ("SkillSpec",),
        "qwenpaw.plugins.markets": (
            "MarketSpec",
            "MarketContext",
            "MarketResult",
            "SearchPage",
            "SkillBundle",
            "Availability",
        ),
        "qwenpaw.plugins.providers": (
            "ModelInfo",
            "ModelUsage",
            "ModelToolChoice",
            "ModelRequest",
            "ModelChunk",
            "ProviderContext",
            "ConnectionResult",
            "ProviderSpec",
        ),
        "qwenpaw.plugins.memory": (
            "MemorySpec",
            "MemoryBackend",
            "MemoryContext",
            "MemoryTask",
        ),
        "qwenpaw.plugins.events": (
            "JSONValue",
            "StreamContent",
            "StreamMessage",
            "ChatEvent",
            "ApprovalDisplay",
            "ApprovalSnapshot",
            "RunEvent",
            "ApprovalEvent",
            "SubscriptionGap",
            "Observation",
            "EventSubscription",
        ),
        "qwenpaw.plugins.apps": (
            "JSONBody",
            "RouteResult",
            "RouteHandler",
            "WebSocketHandler",
            "ChatRequest",
            "ChatReply",
            "SessionSummary",
            "WorkspaceSummary",
            "TaskSnapshot",
            "CancelResult",
            "HttpRequest",
            "HttpResponse",
            "StreamingResponse",
            "AppContext",
            "PawApp",
            "WebSocket",
        ),
        "qwenpaw.plugins.channels": (
            "ChannelMessage",
            "OutgoingMessage",
            "ChannelStreamEvent",
            "ChannelRunEvent",
            "ChannelHealth",
            "RunAwareChannelBackend",
            "ChannelContext",
            "ChannelBackend",
            "StreamingChannelBackend",
            "ChannelSpec",
        ),
        "qwenpaw.plugins.results": (
            "InstallResult",
            "EnableResult",
            "UnloadResult",
            "ReloadResult",
            "ConfigUpdateResult",
        ),
        "qwenpaw.plugins.testing": (
            "TestFault",
            "PluginTestHost",
            "TestModel",
            "TestApproval",
            "TestHttpResponse",
            "TestConnection",
        ),
        "qwenpaw.plugins.compliance": (
            "PUBLIC_API",
            "APIExport",
            "API_EXPORTS",
            "CheckFinding",
            "CheckReport",
            "check_plugin",
        ),
        "qwenpaw.pawapp": ("PawApp",),
    },
)


@dataclass(frozen=True)
class APIExport:
    module: str
    symbol: str
    since: str = "1.0.0"
    stability: str = "stable"


API_EXPORTS = tuple(
    APIExport(
        module,
        symbol,
        stability="compatibility" if module == "qwenpaw.pawapp" else "stable",
    )
    for module, symbols in PUBLIC_API.items()
    for symbol in symbols
)


@dataclass(frozen=True)
class CheckFinding:
    file: str
    line: int
    code: str
    message: str
    severity: str = "error"


@dataclass(frozen=True)
class CheckReport:
    findings: tuple[CheckFinding, ...]
    dependencies: tuple[str, ...]
    uncovered: tuple[str, ...]
    runtime_checked: bool = False
    package_hash: str = ""
    sdk_version: str = "1.0.0"
    rules_version: str = "1.0.0"
    checked_at: str = ""
    plugin_id: str = ""
    declared_sdk_version: str = ""
    capabilities: tuple[str, ...] = ()
    compatibility: str = "not-checked"
    permissions: tuple[str, ...] = ()
    permission_review: str = "not-run"
    permission_declarations: tuple[tuple[str, str], ...] = ()
    lifecycle_checks: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not any(item.severity == "error" for item in self.findings)


# Keep the static scan together; its per-file closures never escape the loop.
# pylint: disable-next=too-many-branches,too-many-statements
def check_plugin(directory: str | Path) -> CheckReport:
    """Inspect Python sources against exact public modules and symbols.

    Third-party imports are dependencies, not SDK violations. Dynamic code is
    reported as unverified; this is an author aid, never a security sandbox.
    """
    # pylint: disable=cell-var-from-loop,too-many-nested-blocks
    directory = Path(directory).resolve()
    findings, dependencies, uncovered = [], set(), set()
    digest = hashlib.sha256()
    sources = []
    for file in sorted(directory.rglob("*")):
        if any(
            part in {".git", "__pycache__"}
            for part in file.relative_to(directory).parts
        ):
            continue
        if file.is_symlink():
            digest.update(
                str(file.relative_to(directory)).encode() + b"\0symlink\0",
            )
            digest.update(str(file.readlink()).encode() + b"\0")
            findings.append(
                CheckFinding(
                    str(file.relative_to(directory)),
                    1,
                    "external-source",
                    "Package symlinks require explicit review",
                ),
            )
            continue
        if not file.is_file():
            continue
        if file.suffix == ".py":
            sources.append(file)
        digest.update(str(file.relative_to(directory)).encode() + b"\0")
        with file.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    manifest = {}
    compatibility = "invalid"
    try:
        manifest = json.loads((directory / "plugin.json").read_text())
        if (
            not isinstance(manifest, dict)
            or not manifest.get("id")
            or not manifest.get("version")
        ):
            raise ValueError("Manifest requires id and version")
        from .sdk_version import validate_sdk
        from .dependency_gate import manifest_requirements

        validate_sdk(manifest.get("sdk"), manifest["id"])
        manifest_requirements(manifest)
        compatibility = (
            "compatible"
            if manifest.get("sdk") is not None
            else "legacy-not-sdk"
        )
        if compatibility == "legacy-not-sdk":
            uncovered.add(
                "Manifest does not opt in to the SDK; legacy behavior was "
                "not migrated or disabled",
            )
        entry = (manifest.get("entry") or {}).get("backend") or manifest.get(
            "entry_point",
        )
        if entry and not (directory / entry).is_file():
            raise ValueError("Declared backend entry does not exist")
    except (
        OSError,
        ValueError,
        TypeError,
        AttributeError,
        RuntimeError,
    ) as exc:
        findings.append(
            CheckFinding("plugin.json", 1, "invalid-input", str(exc)),
        )
    if not isinstance(manifest, dict):
        manifest = {}
    declaration = (
        manifest.get("sdk") if isinstance(manifest.get("sdk"), dict) else {}
    )

    for path in sources:
        if path.is_symlink() or not path.resolve().is_relative_to(directory):
            findings.append(
                CheckFinding(
                    str(path.relative_to(directory)),
                    1,
                    "external-source",
                    "Source escapes the plugin directory",
                ),
            )
            continue
        relative = str(path.relative_to(directory))
        try:
            tree = ast.parse(path.read_text(), filename=relative)
        except (SyntaxError, UnicodeError) as exc:
            findings.append(
                CheckFinding(
                    relative,
                    getattr(exc, "lineno", 1),
                    "syntax",
                    str(exc),
                ),
            )
            continue
        aliases = {}

        def reject(node, code, message):
            findings.append(CheckFinding(relative, node.lineno, code, message))

        def dependency(node, module, symbol=None):
            dependencies.add(module + ("." + symbol if symbol else ""))
            if module == "qwenpaw" or module.startswith("qwenpaw."):
                full_module = module + "." + symbol if symbol else module
                if full_module in PUBLIC_API:
                    return full_module
                if (
                    module not in PUBLIC_API
                    or symbol not in PUBLIC_API[module]
                ):
                    reject(
                        node,
                        "private-import",
                        f"Not a public SDK dependency: {full_module}",
                    )
                return full_module
            return module + ("." + symbol if symbol else "")

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for item in node.names:
                    dependency(node, item.name)
                    aliases[item.asname or item.name.split(".")[0]] = (
                        item.name if item.asname else item.name.split(".")[0]
                    )
            elif isinstance(node, ast.ImportFrom) and not node.level:
                for item in node.names:
                    aliases[item.asname or item.name] = dependency(
                        node,
                        node.module or "",
                        item.name,
                    )

        def qualified(node):
            if isinstance(node, ast.Name):
                return aliases.get(node.id, node.id)
            if isinstance(node, ast.Attribute):
                return qualified(node.value) + "." + node.attr
            return ""

        contexts = {"ctx", "context", "call", "api"}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                arguments = node.args.posonlyargs + node.args.args
                if node.name == "register" and len(arguments) > 1:
                    contexts.add(arguments[1].arg)
                for argument in arguments:
                    if argument.annotation and qualified(
                        argument.annotation,
                    ).endswith(
                        "Context",
                    ):
                        contexts.add(argument.arg)
        # Resolve simple aliases without relying on author spelling.
        for _ in range(len(tuple(ast.walk(tree)))):
            before = (len(contexts), dict(aliases))
            for node in ast.walk(tree):
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    targets = (
                        node.targets
                        if isinstance(node, ast.Assign)
                        else [node.target]
                    )
                    if (
                        isinstance(node.value, ast.Name)
                        and node.value.id in contexts
                    ):
                        contexts.update(
                            target.id
                            for target in targets
                            if isinstance(target, ast.Name)
                        )
                    if isinstance(node.value, (ast.Name, ast.Attribute)):
                        resolved = qualified(node.value)
                        for target in targets:
                            if (
                                isinstance(target, ast.Name)
                                and "." in resolved
                            ):
                                aliases[target.id] = resolved
            if (len(contexts), aliases) == before:
                break

        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                name = qualified(node)
                parent, _, member = name.rpartition(".")
                if (
                    parent in PUBLIC_API
                    and member not in PUBLIC_API[parent]
                    and name not in PUBLIC_API
                ):
                    reject(
                        node,
                        "private-symbol",
                        f"Not a public SDK symbol: {name}",
                    )
                if (
                    node.attr.startswith("_")
                    and isinstance(node.value, ast.Name)
                    and node.value.id in contexts
                ):
                    reject(
                        node,
                        "private-context",
                        f"Private context member: {node.attr}",
                    )
                if name.startswith("qwenpaw.") and any(
                    part.startswith("_") for part in name.split(".")
                ):
                    reject(
                        node,
                        "private-member",
                        f"Private SDK member: {name}",
                    )
                if isinstance(node.ctx, ast.Store) and (
                    name.startswith("qwenpaw.")
                    or (
                        isinstance(node.value, ast.Name)
                        and node.value.id in contexts
                    )
                ):
                    reject(
                        node,
                        "host-mutation",
                        f"Replacing a host/context member: {name}",
                    )
                elif (
                    node.attr.startswith("_")
                    and isinstance(node.value, ast.Name)
                    and node.value.id not in contexts | {"self", "cls"}
                ):
                    uncovered.add(
                        f"{relative}:{node.lineno}: private attribute on "
                        f"unclassified object {node.value.id}",
                    )
            elif isinstance(node, ast.Call):
                name = qualified(node.func)
                if name in {
                    "asyncio.create_task",
                    "asyncio.ensure_future",
                    "threading.Thread",
                    "subprocess.Popen",
                    "asyncio.create_subprocess_exec",
                    "asyncio.create_subprocess_shell",
                }:
                    findings.append(
                        CheckFinding(
                            relative,
                            node.lineno,
                            "unmanaged-resource",
                            f"Use ResourceScope or prove ownership for {name}",
                            "warning",
                        ),
                    )
                    uncovered.add(
                        f"{relative}:{node.lineno}: "
                        "unmanaged resource ownership",
                    )
                if name in {"importlib.import_module", "__import__"}:
                    uncovered.add(
                        f"{relative}:{node.lineno}: "
                        "dynamic import result/member access",
                    )
                    if (
                        node.args
                        and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)
                    ):
                        dependency(node, node.args[0].value)
                    else:
                        uncovered.add(
                            f"{relative}:{node.lineno}: dynamic import",
                        )
                elif name in {
                    "eval",
                    "exec",
                    "getattr",
                    "setattr",
                    "globals",
                    "locals",
                }:
                    uncovered.add(f"{relative}:{node.lineno}: {name}")
                    if (
                        name in {"getattr", "setattr"}
                        and len(node.args) > 1
                        and isinstance(node.args[1], ast.Constant)
                        and isinstance(node.args[1].value, str)
                        and node.args[1].value.startswith("_")
                    ):
                        target = node.args[0]
                        if (
                            isinstance(target, ast.Name)
                            and target.id in contexts
                        ):
                            reject(
                                node,
                                "private-context",
                                "Private context member: "
                                f"{node.args[1].value}",
                            )
    from .sdk_version import SDK_VERSION

    return CheckReport(
        tuple(findings),
        tuple(sorted(dependencies)),
        tuple(sorted(uncovered)),
        package_hash=digest.hexdigest(),
        sdk_version=SDK_VERSION,
        checked_at=datetime.now(timezone.utc).isoformat(),
        plugin_id=str(manifest.get("id", "")),
        declared_sdk_version=str(declaration.get("version", "")),
        capabilities=(
            tuple(str(item) for item in declaration.get("capabilities", ()))
            if isinstance(declaration.get("capabilities"), (list, tuple))
            else ()
        ),
        compatibility=compatibility,
        permissions=(
            tuple(str(item) for item in manifest.get("permissions", ()))
            if isinstance(manifest.get("permissions"), (list, tuple))
            else ()
        ),
        permission_declarations=tuple(
            (
                prefix + "permissions",
                json.dumps(
                    container["permissions"],
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            )
            for prefix, container in (
                ("", manifest),
                ("meta.", manifest.get("meta")),
            )
            if isinstance(container, dict) and "permissions" in container
        ),
    )
