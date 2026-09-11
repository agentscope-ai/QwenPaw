# -*- coding: utf-8 -*-
"""Native, side-effect-free tests invoked by the compatibility Agent."""

from __future__ import annotations

import ast
import inspect
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..agents.skill_system.store import (
    scan_skill_dir_or_raise,
    validate_skill_content,
)
from ..agents.skill_system import SkillService
from ..drivers.adapters.mcp_legacy_config import legacy_mcp_client_to_driver
from ..plugins.architecture import PluginManifest
from ..plugins.api import PluginApi
from ..plugins.loader import resolved_plugin_manifest_path
from .compatibility import (
    AssetType,
    CompatibilityAsset,
)
from .compatibility_safety import (
    mcp_inline_secret_risks,
    redact_sensitive_text,
)
from .codex_plugin_adapter import (
    ADAPTER as CODEX_PLUGIN_ADAPTER,
    stage_codex_content_plugin,
)
from .component_discovery import (
    ADAPTATION_TEXT_SUFFIXES,
    discover_components,
)
from .models import ProviderInventory
from .qoder_plugin_adapter import stage_qoder_skill_plugin
from .scheduled_tasks import build_imported_job, is_nonlocal_workspace


@dataclass(frozen=True)
class NativeTestResult:
    passed: bool
    summary: str
    evidence: list[str]


_CallbackContract = tuple[int | None, tuple[str, ...], str, str]

_CALLBACK_CONTRACTS: dict[str, dict[str, _CallbackContract]] = {
    "register_agent_stop_handler": {
        "handler": (
            1,
            (),
            "async",
            "async callable (ctx) -> StopHandlerResult",
        ),
    },
    "register_middleware": {
        "middleware_factory": (
            2,
            (),
            "sync",
            "sync callable (ctx, agent_config) -> MiddlewareBase | None",
        ),
    },
    "register_prompt_section": {
        "provider": (1, (), "sync", "sync callable (agent) -> str"),
        "condition": (1, (), "sync", "sync callable (agent) -> bool"),
    },
    "register_shutdown_hook": {
        "callback": (0, (), "either", "sync or async callable ()"),
    },
    "register_slash_command": {
        "handler": (
            2,
            (),
            "async",
            "async callable (ctx, args) -> Msg | None",
        ),
    },
    "register_startup_hook": {
        "callback": (0, (), "either", "sync or async callable ()"),
    },
    "register_tool": {
        "tool_func": (
            None,
            (),
            "either",
            "sync or async callable; parameters define the tool schema",
        ),
    },
    "register_uninstall_hook": {
        "callback": (
            0,
            ("plugin_id", "delete_files"),
            "either",
            "sync or async callable (*, plugin_id, delete_files)",
        ),
    },
    "register_workspace_created_hook": {
        "callback": (
            1,
            (),
            "either",
            "sync or async callable (workspace_info)",
        ),
    },
}
_HANDLER_CONTRACTS = {
    "register_control_command.handler": (
        "BaseControlCommandHandler instance with command_name and "
        "async handle(context)"
    ),
}


def _plugin_api_methods() -> dict[str, Any]:
    return {
        name: value
        for name, value in inspect.getmembers(PluginApi, inspect.isfunction)
        if not name.startswith("_") and name != "set_registry"
    }


def _public_signature(method: Any) -> inspect.Signature:
    signature = inspect.signature(method)
    parameters = list(signature.parameters.values())[1:]
    return signature.replace(
        parameters=[
            item.replace(annotation=inspect.Parameter.empty)
            for item in parameters
        ],
        return_annotation=inspect.Signature.empty,
    )


def _plugin_api_contract() -> dict[str, Any]:
    methods = _plugin_api_methods()
    return {
        "manifest": (
            "root plugin.json with id, version and at least one "
            "entry.backend/entry.frontend"
        ),
        "backend": (
            "Python entry exports plugin; the loader calls and may await "
            "register(api)"
        ),
        "api": [
            f"{name}{_public_signature(method)}"
            for name, method in methods.items()
        ],
        "callbacks": {
            f"{method}.{parameter}": contract[3]
            for method, parameters in _CALLBACK_CONTRACTS.items()
            for parameter, contract in parameters.items()
        }
        | _HANDLER_CONTRACTS,
    }


_FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda


def _ast_signature(
    function: _FunctionNode,
    *,
    bound_method: bool = False,
) -> inspect.Signature:
    arguments = function.args
    positional = [*arguments.posonlyargs, *arguments.args]
    defaults_at = len(positional) - len(arguments.defaults)
    parameters = []
    for index, argument in enumerate(positional):
        kind = (
            inspect.Parameter.POSITIONAL_ONLY
            if index < len(arguments.posonlyargs)
            else inspect.Parameter.POSITIONAL_OR_KEYWORD
        )
        default = inspect.Parameter.empty if index < defaults_at else object()
        parameters.append(
            inspect.Parameter(argument.arg, kind, default=default),
        )
    if bound_method:
        if not parameters:
            raise ValueError("bound callback has no self parameter")
        parameters.pop(0)
    if arguments.vararg:
        parameters.append(
            inspect.Parameter(
                arguments.vararg.arg,
                inspect.Parameter.VAR_POSITIONAL,
            ),
        )
    for argument, default_node in zip(
        arguments.kwonlyargs,
        arguments.kw_defaults,
    ):
        default = inspect.Parameter.empty if default_node is None else object()
        parameters.append(
            inspect.Parameter(
                argument.arg,
                inspect.Parameter.KEYWORD_ONLY,
                default=default,
            ),
        )
    if arguments.kwarg:
        parameters.append(
            inspect.Parameter(
                arguments.kwarg.arg,
                inspect.Parameter.VAR_KEYWORD,
            ),
        )
    return inspect.Signature(parameters)


def _call_argument(
    call: ast.Call,
    signature: inspect.Signature,
    name: str,
) -> ast.expr | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    position = list(signature.parameters).index(name)
    return call.args[position] if position < len(call.args) else None


def _callback_function(
    expression: ast.expr,
    register: ast.FunctionDef | ast.AsyncFunctionDef,
    owner: ast.ClassDef,
    globals_by_name: dict[str, _FunctionNode],
) -> tuple[_FunctionNode, bool]:
    local = {
        node.name: node
        for node in ast.walk(register)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node is not register
    }
    if isinstance(expression, ast.Name):
        function = local.get(expression.id) or globals_by_name.get(
            expression.id,
        )
        if function is not None:
            return function, False
    if (
        isinstance(expression, ast.Attribute)
        and isinstance(expression.value, ast.Name)
        and expression.value.id
        == [*register.args.posonlyargs, *register.args.args][0].arg
    ):
        for node in owner.body:
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == expression.attr
            ):
                decorators = {
                    item.id
                    for item in node.decorator_list
                    if isinstance(item, ast.Name)
                }
                return node, "staticmethod" not in decorators
    if isinstance(expression, ast.Lambda):
        return expression, False
    raise ValueError(
        "callback must reference a locally defined function or bound method",
    )


def _validate_callback(
    method_name: str,
    parameter_name: str,
    expression: ast.expr,
    register: ast.FunctionDef | ast.AsyncFunctionDef,
    owner: ast.ClassDef,
    globals_by_name: dict[str, _FunctionNode],
    contract: _CallbackContract,
) -> None:
    if isinstance(expression, ast.Constant) and expression.value is None:
        if parameter_name == "condition":
            return
        raise ValueError(f"{method_name}.{parameter_name} must be callable")
    function, bound = _callback_function(
        expression,
        register,
        owner,
        globals_by_name,
    )
    positional, keywords, async_kind, _description = contract
    is_async = isinstance(function, ast.AsyncFunctionDef)
    if async_kind == "async" and not is_async:
        raise ValueError(
            f"{method_name}.{parameter_name} must be an async callable",
        )
    if async_kind == "sync" and is_async:
        raise ValueError(
            f"{method_name}.{parameter_name} must be a sync callable",
        )
    if positional is None:
        return
    try:
        _ast_signature(function, bound_method=bound).bind(
            *([object()] * positional),
            **{name: object() for name in keywords},
        )
    except TypeError as exc:
        expected = [f"{positional} positional argument(s)"]
        if keywords:
            expected.append("keywords " + ", ".join(keywords))
        raise ValueError(
            f"{method_name}.{parameter_name} must accept "
            + " and ".join(expected),
        ) from exc


def _validate_control_handler(
    expression: ast.expr,
    classes: dict[str, ast.ClassDef],
) -> None:
    if not (
        isinstance(expression, ast.Call)
        and isinstance(expression.func, ast.Name)
        and expression.func.id in classes
    ):
        raise ValueError(
            "register_control_command.handler must be a local Handler()",
        )
    handler = classes[expression.func.id]
    has_name = any(
        isinstance(item, (ast.Assign, ast.AnnAssign))
        and any(
            isinstance(target, ast.Name) and target.id == "command_name"
            for target in (
                item.targets if isinstance(item, ast.Assign) else [item.target]
            )
        )
        for item in handler.body
    )
    methods = [
        item
        for item in handler.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        and item.name == "handle"
    ]
    if (
        not has_name
        or not methods
        or not isinstance(methods[0], ast.AsyncFunctionDef)
    ):
        raise ValueError(
            "register_control_command.handler needs command_name and "
            "async handle(context)",
        )
    try:
        _ast_signature(methods[0], bound_method=True).bind(object())
    except TypeError as exc:
        raise ValueError(
            "register_control_command.handler needs command_name and "
            "async handle(context)",
        ) from exc


def _validate_plugin_api_calls(  # pylint: disable=too-many-branches
    tree: ast.Module,
) -> int:
    methods = _plugin_api_methods()
    global_functions: dict[
        str,
        ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda,
    ] = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    global_classes = {
        node.name: node for node in tree.body if isinstance(node, ast.ClassDef)
    }
    plugin_classes = {
        node.value.func.id
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and any(
            isinstance(target, ast.Name) and target.id == "plugin"
            for target in (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
        )
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
    }
    validated = 0
    for owner in (
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name in plugin_classes
    ):
        for register in (
            node
            for node in owner.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "register"
        ):
            decorators = {
                item.id
                for item in register.decorator_list
                if isinstance(item, ast.Name)
            }
            bound = "staticmethod" not in decorators
            try:
                register_signature = _ast_signature(
                    register,
                    bound_method=bound,
                )
                register_signature.bind(object())
                api_parameter = next(
                    iter(register_signature.parameters.values()),
                )
                if api_parameter.kind not in {
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                }:
                    raise TypeError("api is not an explicit positional arg")
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "plugin register method must be callable as register(api)",
                ) from exc
            api_name = api_parameter.name
            api_receivers: set[int] = set()
            for call in (
                node
                for node in ast.walk(register)
                if isinstance(node, ast.Call)
            ):
                if not (
                    isinstance(call.func, ast.Attribute)
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id == api_name
                ):
                    continue
                api_receivers.add(id(call.func.value))
                method_name = call.func.attr
                method = methods.get(method_name)
                if method is None:
                    raise ValueError(
                        f"unknown PluginApi method: {method_name}",
                    )
                if any(
                    isinstance(item, ast.Starred) for item in call.args
                ) or any(item.arg is None for item in call.keywords):
                    raise ValueError(
                        f"{method_name} uses dynamic arguments that cannot "
                        "be compatibility-tested",
                    )
                signature = _public_signature(method)
                keyword_names = [
                    item.arg for item in call.keywords if item.arg is not None
                ]
                unexpected = set(keyword_names) - signature.parameters.keys()
                if unexpected and not any(
                    item.kind is inspect.Parameter.VAR_KEYWORD
                    for item in signature.parameters.values()
                ):
                    raise ValueError(
                        f"unexpected keyword(s) for {method_name}: "
                        + ", ".join(sorted(unexpected)),
                    )
                try:
                    signature.bind(
                        *([object()] * len(call.args)),
                        **{name: object() for name in keyword_names},
                    )
                except TypeError as exc:
                    raise ValueError(
                        "invalid PluginApi call "
                        f"{method_name}{signature}: {exc}",
                    ) from exc
                for parameter_name, contract in _CALLBACK_CONTRACTS.get(
                    method_name,
                    {},
                ).items():
                    expression = _call_argument(
                        call,
                        signature,
                        parameter_name,
                    )
                    if expression is not None:
                        _validate_callback(
                            method_name,
                            parameter_name,
                            expression,
                            register,
                            owner,
                            global_functions,
                            contract,
                        )
                if method_name == "register_control_command":
                    handler = _call_argument(call, signature, "handler")
                    assert handler is not None
                    _validate_control_handler(handler, global_classes)
                validated += 1
            escaped = any(
                isinstance(node, ast.Name)
                and isinstance(node.ctx, ast.Load)
                and node.id == api_name
                and id(node) not in api_receivers
                for node in ast.walk(register)
            )
            if escaped:
                raise ValueError(
                    "PluginApi value escapes register(api); call api methods "
                    "directly so every registration can be validated",
                )
    return validated


def find_source(
    inventory: ProviderInventory,
    asset: CompatibilityAsset,
) -> Any:
    groups = {
        AssetType.SKILL: inventory.skills,
        AssetType.MCP: inventory.mcp_servers,
        AssetType.PLUGIN: inventory.plugins,
        AssetType.SCHEDULED_TASK: inventory.scheduled_tasks,
    }
    matches = [
        item
        for item in groups[asset.asset_type]
        if item.source_id == asset.source_id
    ]
    if len(matches) != 1:
        raise KeyError(f"cannot resolve source asset {asset.asset_key}")
    return matches[0]


def _mcp_payload(server: Any) -> dict[str, Any]:
    return {
        "type": server.transport,
        "command": server.command,
        "args": server.args,
        "env": server.env,
        "cwd": server.cwd,
        "url": server.url,
        "headers": server.headers,
        "enabled": False,
    }


def _backend_exports_plugin(tree: ast.Module) -> bool:
    register_classes = {
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and any(
            isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
            and member.name == "register"
            for member in node.body
        )
    }
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
            if not any(
                isinstance(item, ast.Name) and item.id == "plugin"
                for item in targets
            ):
                continue
            value = node.value
            if (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id in register_classes
            ) or (isinstance(value, ast.Name) and value.id == "app"):
                return True
    return any(
        isinstance(node, ast.ImportFrom)
        and any(
            (alias.asname or alias.name) in {"plugin", "app"}
            for alias in node.names
        )
        for node in tree.body
    )


class CompatibilityTester:
    """Expose current-environment evidence without installing an asset."""

    def __init__(
        self,
        workspace: Any,
        inventory: ProviderInventory,
    ) -> None:
        self.workspace = workspace
        self.inventory = inventory

    def environment(self) -> dict[str, Any]:
        registry = getattr(
            getattr(self.workspace, "plugins", None),
            "tool_registry",
            None,
        )
        tools = registry.names() if registry is not None else []
        try:
            skills = [
                item.name
                for item in SkillService(
                    self.workspace.workspace_dir,
                ).list_all_skills()
            ]
        except Exception:  # pylint: disable=broad-except
            skills = []
        return {
            "platform_tools": tools,
            "existing_skills": skills,
            "workspace": str(Path(self.workspace.workspace_dir).resolve()),
            "plugin_contract": _plugin_api_contract(),
            "note": (
                "Tests validate against current QwenPaw models, adapters, "
                "and live PluginApi contracts without installing or "
                "executing imported source code."
            ),
        }

    def inspect(self, asset: CompatibilityAsset) -> dict[str, Any]:
        source = find_source(self.inventory, asset)
        detail = dict(asset.snapshot)
        if asset.asset_type is AssetType.MCP:
            risks = mcp_inline_secret_risks(
                source.command,
                source.args,
                source.url,
                source.env,
                source.headers,
                source.cwd,
            )
            if not risks:
                detail.update(
                    command=redact_sensitive_text(source.command),
                    args=[redact_sensitive_text(item) for item in source.args],
                    cwd=redact_sensitive_text(source.cwd),
                    url=redact_sensitive_text(source.url),
                )
        elif asset.asset_type is AssetType.SCHEDULED_TASK:
            # Keep the immutable manifest snapshot as provenance, while
            # returning the current mutable schedule to the Agent.  Otherwise
            # a successful update looks unchanged and triggers redundant
            # writes on the next inspect call.
            detail.update(
                schedule_type=redact_sensitive_text(
                    source.schedule_type,
                    limit=30,
                ),
                cron=redact_sensitive_text(source.cron, limit=200),
                run_at=source.run_at.isoformat() if source.run_at else "",
                timezone=redact_sensitive_text(source.timezone, limit=100),
                prompt=redact_sensitive_text(source.prompt),
                cwd=redact_sensitive_text(source.cwd),
            )
        return {
            "asset": asset.model_dump(mode="json"),
            "detail": detail,
            "environment": self.environment(),
        }

    def test(self, asset: CompatibilityAsset) -> NativeTestResult:
        source = find_source(self.inventory, asset)
        try:
            if asset.asset_type is AssetType.SKILL:
                result = self._test_skill(source)
            elif asset.asset_type is AssetType.MCP:
                result = self._test_mcp(source)
            elif asset.asset_type is AssetType.PLUGIN:
                result = self._test_plugin(source)
            else:
                result = self._test_schedule(source)
        except Exception as exc:  # pylint: disable=broad-except
            result = NativeTestResult(
                False,
                f"QwenPaw 原生兼容测试失败：{type(exc).__name__}",
                [redact_sensitive_text(exc, limit=1000)],
            )
        return result

    @staticmethod
    def _test_skill(skill: Any) -> NativeTestResult:
        root = Path(skill.directory)
        content = (root / "SKILL.md").read_text(encoding="utf-8")
        name, description = validate_skill_content(content)
        scan_skill_dir_or_raise(root, name)
        return NativeTestResult(
            True,
            "Skill 通过当前 QwenPaw 原生导入器测试。",
            [f"name={name}", f"description={description[:300]}"],
        )

    def _test_mcp(self, server: Any) -> NativeTestResult:
        risks = mcp_inline_secret_risks(
            server.command,
            server.args,
            server.url,
            server.env,
            server.headers,
            server.cwd,
        )
        if risks:
            return NativeTestResult(
                False,
                "MCP 含不能安全迁移的明文绑定。",
                ["unsafe=" + ",".join(risks)],
            )
        card, _credential = legacy_mcp_client_to_driver(
            server.name,
            _mcp_payload(server),
            force_encrypt_bindings=True,
        )
        evidence = [f"protocol={card.protocol}"]
        if server.transport == "stdio":
            executable = shutil.which(server.command)
            command_path = Path(server.command)
            plugin_id = str(server.metadata.get("source_plugin") or "")
            relative_cwd = str(
                server.metadata.get("source_plugin_relative_cwd") or "",
            )
            if plugin_id and relative_cwd and not command_path.is_absolute():
                plugin = next(
                    (
                        item
                        for item in self.inventory.plugins
                        if item.source_id == plugin_id
                    ),
                    None,
                )
                if plugin is not None:
                    runtime_root = (
                        Path(plugin.install_source) / relative_cwd
                    ).resolve()
                    candidate = (runtime_root / command_path).resolve()
                    if (
                        candidate.is_relative_to(
                            runtime_root,
                        )
                        and candidate.is_file()
                    ):
                        executable = str(candidate)
                        evidence.append(f"plugin_runtime={runtime_root}")
            if not executable and not command_path.is_file():
                return NativeTestResult(
                    False,
                    "当前环境找不到 MCP 启动程序。",
                    [f"command={redact_sensitive_text(server.command)}"],
                )
            evidence.append(f"executable={executable or server.command}")
        return NativeTestResult(
            True,
            "MCP 可由当前 QwenPaw DriverCard 适配器加载。",
            evidence,
        )

    @staticmethod
    def _test_plugin(plugin: Any) -> NativeTestResult:
        if plugin.metadata.get("adapter") == "qoder_skill_only_v1":
            wrapper = stage_qoder_skill_plugin(plugin)
            try:
                for skill_file in sorted(wrapper.rglob("SKILL.md")):
                    content = skill_file.read_text(encoding="utf-8")
                    name, _description = validate_skill_content(content)
                    scan_skill_dir_or_raise(skill_file.parent, name)
                result = CompatibilityTester._test_native_plugin(wrapper)
                return NativeTestResult(
                    result.passed,
                    "Qoder Skill-only 插件通过 QwenPaw 包装和加载测试。",
                    ["adapter=qoder_skill_only_v1", *result.evidence],
                )
            finally:
                shutil.rmtree(wrapper.parent, ignore_errors=True)
        if plugin.metadata.get("adapter") == CODEX_PLUGIN_ADAPTER:
            wrapper = stage_codex_content_plugin(plugin)
            try:
                for skill_file in sorted(wrapper.rglob("SKILL.md")):
                    content = skill_file.read_text(encoding="utf-8")
                    name, _description = validate_skill_content(content)
                    scan_skill_dir_or_raise(skill_file.parent, name)
                result = CompatibilityTester._test_native_plugin(wrapper)
                return NativeTestResult(
                    result.passed,
                    "Codex 内容插件通过 QwenPaw 包装和加载测试。",
                    [f"adapter={CODEX_PLUGIN_ADAPTER}", *result.evidence],
                )
            finally:
                shutil.rmtree(wrapper.parent, ignore_errors=True)
        source = str(plugin.install_source or "")
        if not source:
            raise ValueError("plugin has no independent install source")
        if source.startswith(("http://", "https://")):
            return NativeTestResult(
                False,
                "远程插件未下载，当前测试不能证明其可直接加载。",
                ["source=remote"],
            )
        return CompatibilityTester._test_native_plugin(Path(source))

    @staticmethod
    def _test_native_plugin(root: Path) -> NativeTestResult:
        manifest_path = resolved_plugin_manifest_path(root)
        if manifest_path.stat().st_size > 1024 * 1024:
            raise ValueError("plugin.json exceeds 1 MiB")
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = PluginManifest.from_dict(value)
        if not manifest.entry.backend and not manifest.entry.frontend:
            raise ValueError("plugin has no backend or frontend entry")
        for declared in (manifest.entry.backend, manifest.entry.frontend):
            if not declared:
                continue
            relative = Path(declared)
            target = root / relative
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or target.is_symlink()
                or not target.is_file()
                or not target.resolve().is_relative_to(root.resolve())
            ):
                raise ValueError(f"invalid plugin entry: {declared}")
        if manifest.entry.backend:
            backend = root / manifest.entry.backend
            tree = ast.parse(backend.read_text(encoding="utf-8"))
            if not _backend_exports_plugin(tree):
                raise ValueError(
                    "backend must export a plugin with register(api)",
                )
            api_calls = _validate_plugin_api_calls(tree)
        else:
            api_calls = 0
        evidence = [f"plugin_id={manifest.id}"]
        description = redact_sensitive_text(manifest.description)
        if description:
            evidence.append(f"description={description[:500]}")
        entries = [
            name
            for name, declared in (
                ("backend", manifest.entry.backend),
                ("frontend", manifest.entry.frontend),
            )
            if declared
        ]
        if entries:
            evidence.append("entry=" + ",".join(entries))
        if manifest.entry.backend:
            evidence.append(f"plugin_api_calls_validated={api_calls}")
        return NativeTestResult(
            True,
            "插件清单、入口和注册调用通过当前 QwenPaw 原生规范检查。",
            evidence,
        )

    def _test_schedule(self, task: Any) -> NativeTestResult:
        if is_nonlocal_workspace(task.metadata):
            return NativeTestResult(
                False,
                "来源任务绑定远程或未验证工作区，当前环境不能直接使用。",
                ["workspace=remote_or_unverified"],
            )
        if task.cwd and not Path(task.cwd).expanduser().is_dir():
            return NativeTestResult(
                False,
                "来源任务的工作目录在当前环境不存在。",
                ["workspace=missing"],
            )
        job = build_imported_job(self.inventory.provider_id, task)
        manager = getattr(self.workspace, "cron_manager", None)
        if manager is None:
            raise RuntimeError("Cron manager unavailable")
        manager.validate_job_spec(job)
        return NativeTestResult(
            True,
            "定时任务通过当前 QwenPaw Cron 模型和触发器测试。",
            [
                f"schedule_type={task.schedule_type}",
                f"timezone={task.timezone}",
            ],
        )


__all__ = [
    "ADAPTATION_TEXT_SUFFIXES",
    "CompatibilityTester",
    "NativeTestResult",
    "discover_components",
    "find_source",
]
