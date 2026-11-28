# -*- coding: utf-8 -*-
"""Explicit SDK dependency checks. Static inspection never imports a plugin."""

import ast
import hashlib
import json
from datetime import datetime, timezone
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from types import MappingProxyType

from .architecture import PluginManifest
from .sdk_version import SDK_VERSION, validate_sdk

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
        "qwenpaw.plugins.context": ("RequestContext",),
        "qwenpaw.plugins.channel_workers": (
            "ChannelDefinition",
            "ChannelExclusiveResource",
            "ChannelDriver",
            "ChannelWorkerContext",
            "ChannelReceiveResult",
            "ChannelResponse",
            "ChannelContent",
            "ReplyTarget",
            "ChannelSendResult",
            "ChannelDeliveryError",
            "ResponsePolicy",
            "ChannelDelivery",
            "ChannelDeliveryStep",
            "ChannelAuth",
            "ChannelApproval",
            "ChannelApprovalAction",
            "ChannelApprovalResolution",
            "ChannelApprovals",
        ),
        "qwenpaw.plugins.channel_management": (
            "ChannelManagementRequest",
            "ChannelManagementResult",
            "ChannelQRCode",
            "ChannelAuthorization",
            "ChannelVerification",
            "ChannelManagementFailure",
        ),
        "qwenpaw.plugins.channel_ingress": (
            "ChannelIngressRoute",
            "ChannelIngressSpec",
            "ChannelIngressBinding",
            "ChannelIngress",
        ),
        "qwenpaw.plugins.workspace": ("WorkspaceService",),
        "qwenpaw.plugins.conversations": (
            "ConversationService",
            "ConversationMessage",
        ),
        "qwenpaw.plugins.stops": ("StopContext", "StopSpec", "StopResult"),
        "qwenpaw.plugins.shell": (
            "ShellBackendSpec",
            "ShellRequest",
            "ShellResult",
        ),
        "qwenpaw.plugins.workflows": (
            "WorkflowSpec",
            "WorkflowSchedule",
            "WorkflowContext",
            "WorkflowResult",
            "WorkflowNotification",
        ),
        "qwenpaw.plugins.models": (
            "ModelService",
            "ModelSelection",
            "ModelDescription",
        ),
        "qwenpaw.plugins.drivers": (
            "DriverSource",
            "DriverCapabilitySpec",
            "DriverCallResult",
            "DriverRequestContext",
            "DriverCredential",
            "DriverCredentialAccess",
            "DriverContext",
            "DriverConnection",
            "DriverProtocolSpec",
        ),
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
        "qwenpaw.plugins.cli": ("CliSpec", "CliContext"),
        "qwenpaw.plugins.doctor": (
            "DOCTOR",
            "DoctorSpec",
            "DoctorContext",
            "DoctorResult",
        ),
        "qwenpaw.plugins.extensions": ("ExtensionPoint",),
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
            "ProviderHandle",
        ),
        "qwenpaw.plugins.transcription": (
            "TranscriptionSpec",
            "TranscriptionContext",
            "TranscriptionResult",
            "TranscriptionStatus",
        ),
        "qwenpaw.plugins.memory": (
            "MemorySpec",
            "MemoryBackend",
            "MemoryContext",
            "MemoryTask",
        ),
        "qwenpaw.plugins.harnesses": (
            "HarnessSpec",
            "HarnessContext",
            "HarnessCallContext",
            "HarnessApprovalSummary",
            "HarnessApprovalDecision",
            "HarnessRunRequest",
            "HarnessEvent",
            "HarnessEventKind",
            "HarnessHistoryItem",
            "HarnessHistoryKind",
            "HarnessAttachment",
            "HarnessAttachmentKind",
            "HarnessCapabilities",
            "HarnessCommand",
            "HarnessApprovalPreset",
            "HarnessModel",
            "HarnessStatus",
            "HarnessLogin",
            "HarnessDiscoveredSkill",
            "HarnessDiscoveredMCPServer",
            "HarnessRuntimeCapabilities",
            "HarnessSkillDefinition",
            "HarnessMCPServerDefinition",
            "HarnessBackend",
            "HarnessArchiveBackend",
            "HarnessOperationNotSupportedError",
            "MCPTransport",
            "MCPToolPolicy",
        ),
        "qwenpaw.plugins.events": (
            "JSONValue",
            "JSONData",
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
            "UploadedFile",
            "FileResponse",
            "HttpResponse",
            "StreamingResponse",
            "AppContext",
            "PawApp",
            "WebSocket",
        ),
        "qwenpaw.plugins.checkpoints": (
            "CheckpointService",
            "CheckpointEntry",
            "SnapshotResult",
            "RestoreResult",
            "CheckpointError",
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
    # Relative member names, optionally followed by a parameter name.
    # Example: ("process.tree", "1.2.0") extends a 1.0.0 method.
    # A "parameter.default" entry versions a newly optional parameter.
    members: tuple[tuple[str, str], ...] = ()


_MEMBER_VERSIONS = {
    "qwenpaw.plugins.channel_workers.ChannelDriver": (
        ("response_policy_for", "1.2.0"),
    ),
    "qwenpaw.plugins.channel_workers.ResponsePolicy": (
        ("configured_prefix", "1.2.0"),
    ),
    "qwenpaw.plugins.channels.ChannelMessage": (
        ("sender_name", "1.2.0"),
        ("thread_id", "1.2.0"),
        ("actor_unknown", "1.2.0"),
    ),
    "qwenpaw.plugins.commands.CommandSpec": (("control", "1.2.0"),),
    "qwenpaw.plugins.apps.HttpRequest": (("form", "1.2.0"),),
    "qwenpaw.plugins.apps.PawApp": (
        ("route.body", "1.2.0"),
        ("route.max_body_bytes", "1.2.0"),
    ),
    "qwenpaw.plugins.apps.AppContext": (("conversations", "1.2.0"),),
    "qwenpaw.plugins.events.ChatEvent": (("to_dict", "1.2.0"),),
    "qwenpaw.plugins.storage.PluginStorage": (
        ("path", "1.2.0"),
        ("import_legacy", "1.2.0"),
        ("import_legacy_tree", "1.2.0"),
    ),
    "qwenpaw.plugins.modes.ModeContext": (("identity", "1.2.0"),),
    "qwenpaw.plugins.PluginContext": (
        ("register_harness", "1.1.0"),
        ("register_transcription", "1.1.0"),
        ("register_stop", "1.2.0"),
        ("register_shell_backend", "1.2.0"),
        ("register_workflow", "1.2.0"),
    ),
    "qwenpaw.plugins.tools.ToolContext": (
        ("identity", "1.2.0"),
        ("workspace_ops", "1.2.0"),
        ("checkpoints", "1.2.0"),
        ("select_shell_backend", "1.2.0"),
    ),
    "qwenpaw.plugins.prompts.PromptSpec": (
        ("render", "1.2.0"),
        ("text.default", "1.2.0"),
    ),
    "qwenpaw.plugins.hooks.HookContext": (("session_saved", "1.2.0"),),
    "qwenpaw.plugins.models.ModelService": (
        ("configured", "1.2.0"),
        ("catalog", "1.2.0"),
    ),
    "qwenpaw.plugins.resources.ResourceScope": (
        ("run_sync", "1.2.0"),
        ("async_process", "1.2.0"),
        ("process.tree", "1.2.0"),
        ("__aenter__", "1.2.0"),
        ("__aexit__", "1.2.0"),
    ),
    "qwenpaw.plugins.markets.MarketContext": (
        ("lang", "1.2.0"),
        ("category", "1.2.0"),
    ),
    "qwenpaw.plugins.testing.PluginTestHost": (
        ("list_harnesses", "1.1.0"),
        ("harness_status", "1.1.0"),
        ("run_harness", "1.1.0"),
        ("transcribe", "1.1.0"),
        ("transcription_status", "1.1.0"),
        ("process_channels", "1.2.0"),
        # Existing 1.0 keyword forwarding is now explicit in the signature.
        ("call_tool.workspace_id", "1.0.0"),
        ("call_tool.session_id", "1.0.0"),
        ("run_workflow", "1.2.0"),
        ("call_control_command", "1.2.0"),
        ("evaluate_stop", "1.2.0"),
        ("search_market.lang", "1.2.0"),
        ("search_market.category", "1.2.0"),
        *(
            (f"{method}.{parameter}", "1.2.0")
            for method in (
                "call_tool",
                "stream_tool",
                "call_command",
                "run_hooks",
                "build_prompt",
                "active_modes",
                "run_mode",
            )
            for parameter in ("user_id", "channel")
        ),
        ("run_hooks.session_saved", "1.2.0"),
    ),
    "qwenpaw.plugins.compliance.APIExport": (("members", "1.2.0"),),
}

_EXPORT_VERSIONS = {
    **{
        f"{module}.{name}": "1.1.0"
        for module in (
            "qwenpaw.plugins.harnesses",
            "qwenpaw.plugins.transcription",
        )
        for name in PUBLIC_API[module]
    },
    **{
        f"qwenpaw.plugins.channel_ingress.{name}": "1.2.0"
        for name in PUBLIC_API["qwenpaw.plugins.channel_ingress"]
    },
    **{
        f"qwenpaw.plugins.channel_management.{name}": "1.2.0"
        for name in PUBLIC_API["qwenpaw.plugins.channel_management"]
    },
    **{
        f"qwenpaw.plugins.channel_workers.{name}": "1.2.0"
        for name in PUBLIC_API["qwenpaw.plugins.channel_workers"]
    },
    **{
        f"qwenpaw.plugins.workflows.{name}": "1.2.0"
        for name in PUBLIC_API["qwenpaw.plugins.workflows"]
    },
    **{
        f"qwenpaw.plugins.drivers.{name}": "1.2.0"
        for name in PUBLIC_API["qwenpaw.plugins.drivers"]
    },
    "qwenpaw.plugins.providers.ProviderHandle": "1.2.0",
    **{
        f"qwenpaw.plugins.checkpoints.{name}": "1.2.0"
        for name in (
            "CheckpointService",
            "CheckpointEntry",
            "SnapshotResult",
            "RestoreResult",
            "CheckpointError",
        )
    },
    "qwenpaw.plugins.apps.UploadedFile": "1.2.0",
    "qwenpaw.plugins.apps.FileResponse": "1.2.0",
    "qwenpaw.plugins.conversations.ConversationService": "1.2.0",
    "qwenpaw.plugins.conversations.ConversationMessage": "1.2.0",
    "qwenpaw.plugins.workspace.WorkspaceService": "1.2.0",
    "qwenpaw.plugins.events.JSONData": "1.2.0",
    **{
        f"qwenpaw.plugins.stops.{name}": "1.2.0"
        for name in ("StopContext", "StopSpec", "StopResult")
    },
    "qwenpaw.plugins.context.RequestContext": "1.2.0",
    **{
        f"qwenpaw.plugins.shell.{name}": "1.2.0"
        for name in ("ShellBackendSpec", "ShellRequest", "ShellResult")
    },
    "qwenpaw.plugins.models.ModelSelection": "1.2.0",
    "qwenpaw.plugins.models.ModelDescription": "1.2.0",
    **{
        f"{module}.{name}": "1.2.0"
        for module in (
            "qwenpaw.plugins.cli",
            "qwenpaw.plugins.doctor",
            "qwenpaw.plugins.extensions",
        )
        for name in PUBLIC_API[module]
    },
}

API_EXPORTS = tuple(
    APIExport(
        module,
        symbol,
        since=_EXPORT_VERSIONS.get(f"{module}.{symbol}", "1.0.0"),
        stability="compatibility" if module == "qwenpaw.pawapp" else "stable",
        members=_MEMBER_VERSIONS.get(f"{module}.{symbol}", ()),
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
    sdk_version: str = SDK_VERSION
    rules_version: str = "1.2.0"
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
        elif file.suffix in {
            ".js",
            ".mjs",
            ".jsx",
            ".ts",
            ".tsx",
        } and not file.name.endswith(".d.ts"):
            uncovered.add(
                "Frontend types and minimum SDK version are not checked by "
                "this Python checker; run qwenpaw-sdk-check with the plugin "
                "manifest and author tsconfig.json",
            )
        digest.update(str(file.relative_to(directory)).encode() + b"\0")
        with file.open("rb") as stream:
            for chunk in iter(partial(stream.read, 1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    manifest = {}
    compatibility = "invalid"
    try:
        manifest = json.loads((directory / "plugin.json").read_text())
        from .dependency_gate import manifest_requirements

        parsed_manifest = PluginManifest.from_dict(manifest)
        validate_sdk(parsed_manifest.sdk, parsed_manifest.id)
        manifest_requirements(manifest)
        compatibility = (
            "compatible"
            if parsed_manifest.sdk is not None
            else "legacy-not-sdk"
        )
        if compatibility == "legacy-not-sdk":
            uncovered.add(
                "Manifest does not opt in to the SDK; legacy behavior was "
                "not migrated or disabled",
            )
        entry = parsed_manifest.entry.backend
        if entry and not (directory / entry).is_file():
            raise ValueError("Declared backend entry does not exist")
        if manifest.get("type") == "channel":
            from ._channel_check import check_channel_package

            findings.extend(check_channel_package(directory, parsed_manifest))
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

        def reject(node, code, message, _relative=relative):
            findings.append(
                CheckFinding(_relative, node.lineno, code, message),
            )

        def dependency(node, module, symbol=None, _reject=reject):
            dependencies.add(module + ("." + symbol if symbol else ""))
            if module == "qwenpaw" or module.startswith("qwenpaw."):
                full_module = module + "." + symbol if symbol else module
                if full_module in PUBLIC_API:
                    return full_module
                if (
                    module not in PUBLIC_API
                    or symbol not in PUBLIC_API[module]
                ):
                    _reject(
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

        from ._api_check import check_member_versions

        public_protocols = check_member_versions(
            tree,
            aliases,
            declaration.get("version", ""),
            _MEMBER_VERSIONS,
            {
                f"{entry.module}.{entry.symbol}": entry.since
                for entry in API_EXPORTS
            },
            reject,
        )

        def qualified(node, _lookup=aliases.get):
            parts = []
            while isinstance(node, ast.Attribute):
                parts.append(node.attr)
                node = node.value
            base = (
                _lookup(node.id, node.id) if isinstance(node, ast.Name) else ""
            )
            return ".".join((base, *reversed(parts)))

        parents = {
            child: parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }

        def host_context_member(node):
            if (
                not isinstance(node.value, ast.Name)
                or node.value.id not in contexts
            ):
                return False
            scope = node
            while scope in parents:
                scope = parents[scope]
                if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    arguments = scope.args.posonlyargs + scope.args.args
                    for index, argument in enumerate(arguments):
                        if argument.arg != node.value.id:
                            continue
                        click_parameter = index == 0 and any(
                            qualified(decorator)
                            in {"click.pass_context", "click.pass_obj"}
                            for decorator in scope.decorator_list
                        )
                        return not (
                            click_parameter
                            or qualified(argument.annotation)
                            == "click.Context"
                        )
            return True

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
                    and id(node) not in public_protocols
                    and host_context_member(node)
                ):
                    reject(
                        node,
                        "private-context",
                        f"Private context member: {node.attr}",
                    )
                if (
                    id(node) not in public_protocols
                    and name.startswith("qwenpaw.")
                    and any(part.startswith("_") for part in name.split("."))
                ):
                    reject(
                        node,
                        "private-member",
                        f"Private SDK member: {name}",
                    )
                if isinstance(node.ctx, ast.Store) and (
                    name.startswith("qwenpaw.") or host_context_member(node)
                ):
                    reject(
                        node,
                        "host-mutation",
                        f"Replacing a host/context member: {name}",
                    )
                elif (
                    node.attr.startswith("_")
                    and id(node) not in public_protocols
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
    return CheckReport(
        tuple(findings),
        tuple(sorted(dependencies)),
        tuple(sorted(uncovered)),
        package_hash=digest.hexdigest(),
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
