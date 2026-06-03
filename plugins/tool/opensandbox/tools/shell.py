# -*- coding: utf-8 -*-
"""Shell command execution through OpenSandbox."""

from __future__ import annotations

import json
import logging
import os
from datetime import timedelta
from typing import Any, NamedTuple
from urllib.parse import urlparse

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse
from qwenpaw.plugins import get_tool_config

logger = logging.getLogger(__name__)

_TOOL_NAME = "execute_opensandbox_command"

_DEFAULT_DOMAIN = "127.0.0.1:8080"
_DEFAULT_PROTOCOL = "http"
_DEFAULT_API_KEY_ENV = "OPEN_SANDBOX_API_KEY"
_DEFAULT_IMAGE = "opensandbox/code-interpreter:v1.0.2"
_DEFAULT_ENTRYPOINT = ["/opt/opensandbox/code-interpreter.sh"]
_DEFAULT_ENV = {"PYTHON_VERSION": "3.11"}
_DEFAULT_RESOURCE = {"cpu": "500m", "memory": "512Mi"}
_DEFAULT_WORKDIR = "/workspace"


class _RuntimeOptions(NamedTuple):
    domain: str
    protocol: str
    request_timeout: float
    ready_timeout: float
    sandbox_timeout: float
    command_timeout: float
    sandbox_cwd: str
    entrypoint: list[Any]
    env: dict[str, Any]
    resource: dict[str, Any]


def _text_response(text: str) -> ToolResponse:
    return ToolResponse(content=[TextBlock(type="text", text=text)])


def _config_value(config: dict[str, Any], key: str, default: Any) -> Any:
    value = config.get(key)
    if value is None or value == "":
        return default
    return value


def _float_config(
    config: dict[str, Any],
    key: str,
    default: float,
    *,
    minimum: float | None = None,
) -> float:
    value = _config_value(config, key, default)
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None and parsed < minimum:
        return minimum
    return parsed


def _bool_config(config: dict[str, Any], key: str, default: bool) -> bool:
    value = _config_value(config, key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _command_timeout(value: Any, default: float = 60.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(parsed, 1.0)


def _json_config(
    config: dict[str, Any],
    key: str,
    default: Any,
    expected_type: type,
    warnings: list[str],
) -> Any:
    value = _config_value(config, key, default)
    if isinstance(value, expected_type):
        return value
    if not isinstance(value, str):
        warnings.append(f"{key} is not valid JSON; using default.")
        return default
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        warnings.append(f"{key} is not valid JSON; using default.")
        return default
    if not isinstance(parsed, expected_type):
        warnings.append(f"{key} has the wrong JSON type; using default.")
        return default
    return parsed


def _normalize_connection(
    raw_domain: str,
    raw_protocol: str,
) -> tuple[str, str]:
    domain = raw_domain.strip()
    protocol = raw_protocol.strip().lower() or _DEFAULT_PROTOCOL
    if domain.startswith(("http://", "https://")):
        parsed = urlparse(domain)
        if parsed.scheme:
            protocol = parsed.scheme
        if parsed.netloc:
            domain = parsed.netloc
    if protocol not in {"http", "https"}:
        protocol = _DEFAULT_PROTOCOL
    return domain or _DEFAULT_DOMAIN, protocol


def _normalize_cwd(
    requested_cwd: str,
    default_cwd: str,
) -> tuple[str, str | None]:
    cwd = (requested_cwd or "").strip() or default_cwd
    # Host paths are not mounted in the zero-core MVP. Avoid passing Windows
    # paths into a Linux sandbox where they are guaranteed to fail.
    if "\\" in cwd or (len(cwd) >= 2 and cwd[1] == ":"):
        return (
            default_cwd,
            f"Host cwd '{cwd}' was ignored; "
            f"using sandbox cwd '{default_cwd}'.",
        )
    return cwd, None


def _join_output_chunks(items: Any) -> str:
    """Join OpenSandbox output messages into readable text."""
    if not items:
        return ""
    if isinstance(items, str):
        return items.strip("\n")

    chunks: list[str] = []
    for item in items:
        text = str(getattr(item, "text", item))
        if text:
            chunks.append(text)
    if not chunks:
        return ""

    result = ""
    for chunk in chunks:
        if (
            result
            and not result.endswith(("\n", "\r"))
            and not chunk.startswith(("\n", "\r"))
        ):
            result += "\n"
        result += chunk
    return result.strip("\n")


def _format_command_result(
    *,
    command: str,
    sandbox_id: str,
    exit_code: int,
    stdout: str,
    stderr: str,
    warnings: list[str],
) -> str:
    parts = [
        f"OpenSandbox sandbox: {sandbox_id}",
        f"Command: {command}",
        f"Exit code: {exit_code}",
    ]
    if warnings:
        parts.append(
            "Warnings:\n" + "\n".join(f"- {item}" for item in warnings),
        )
    if stdout:
        parts.append("STDOUT:\n" + stdout)
    if stderr:
        parts.append("STDERR:\n" + stderr)
    if not stdout and not stderr and exit_code == 0:
        parts.append("Command executed successfully (no output).")
    elif not stdout and not stderr:
        parts.append("Command finished with no output.")
    return "\n".join(parts)


def _resolve_api_key(config: dict[str, Any]) -> str:
    api_key_env = str(
        _config_value(config, "api_key_env", _DEFAULT_API_KEY_ENV),
    ).strip()
    configured_api_key = str(config.get("api_key") or "")
    if configured_api_key == "***":
        configured_api_key = ""
    env_api_key = os.getenv(api_key_env, "") if api_key_env else ""
    return configured_api_key or env_api_key


def _runtime_options(
    config: dict[str, Any],
    cwd: str,
    timeout: float,
    warnings: list[str],
) -> _RuntimeOptions:
    domain, protocol = _normalize_connection(
        str(_config_value(config, "domain", _DEFAULT_DOMAIN)),
        str(_config_value(config, "protocol", _DEFAULT_PROTOCOL)),
    )
    default_cwd = str(
        _config_value(config, "command_working_directory", _DEFAULT_WORKDIR),
    )
    sandbox_cwd, cwd_warning = _normalize_cwd(cwd, default_cwd)
    if cwd_warning:
        warnings.append(cwd_warning)

    entrypoint = _json_config(
        config,
        "entrypoint_json",
        _DEFAULT_ENTRYPOINT,
        list,
        warnings,
    )
    env = _json_config(config, "env_json", _DEFAULT_ENV, dict, warnings)
    resource = _json_config(
        config,
        "resource_json",
        _DEFAULT_RESOURCE,
        dict,
        warnings,
    )

    return _RuntimeOptions(
        domain=domain,
        protocol=protocol,
        request_timeout=_float_config(
            config,
            "request_timeout_seconds",
            60.0,
            minimum=1.0,
        ),
        ready_timeout=_float_config(
            config,
            "ready_timeout_seconds",
            120.0,
            minimum=1.0,
        ),
        sandbox_timeout=_float_config(
            config,
            "sandbox_timeout_seconds",
            300.0,
            minimum=60.0,
        ),
        command_timeout=_command_timeout(timeout),
        sandbox_cwd=sandbox_cwd,
        entrypoint=entrypoint,
        env=env,
        resource=resource,
    )


def _load_opensandbox_sdk() -> tuple[Any, Any, Any]:
    from opensandbox.config import ConnectionConfig
    from opensandbox.models.execd import RunCommandOpts
    from opensandbox.sandbox import Sandbox

    return ConnectionConfig, RunCommandOpts, Sandbox


def _connection_config(
    connection_config_cls: Any,
    config: dict[str, Any],
    options: _RuntimeOptions,
    api_key: str,
) -> Any:
    connection_kwargs = {
        "domain": options.domain,
        "protocol": options.protocol,
        "request_timeout": timedelta(seconds=options.request_timeout),
        "use_server_proxy": _bool_config(config, "use_server_proxy", False),
    }
    if api_key:
        connection_kwargs["api_key"] = api_key
    return connection_config_cls(**connection_kwargs)


async def _create_sandbox(
    sandbox_cls: Any,
    config: dict[str, Any],
    connection_config: Any,
    options: _RuntimeOptions,
) -> Any:
    return await sandbox_cls.create(
        str(_config_value(config, "image", _DEFAULT_IMAGE)),
        connection_config=connection_config,
        entrypoint=[str(item) for item in options.entrypoint],
        env={str(key): str(value) for key, value in options.env.items()},
        timeout=timedelta(seconds=options.sandbox_timeout),
        ready_timeout=timedelta(seconds=options.ready_timeout),
        resource={
            str(key): str(value) for key, value in options.resource.items()
        },
        metadata={
            "project": "qwenpaw",
            "plugin": "opensandbox",
            "tool": _TOOL_NAME,
        },
    )


def _sandbox_id(sandbox: Any) -> str:
    return str(
        getattr(sandbox, "id", None)
        or getattr(sandbox, "sandbox_id", None)
        or "unknown",
    )


async def _run_command(
    sandbox: Any,
    run_command_opts_cls: Any,
    command: str,
    options: _RuntimeOptions,
) -> Any:
    return await sandbox.commands.run(
        command,
        opts=run_command_opts_cls(
            working_directory=options.sandbox_cwd,
            timeout=timedelta(seconds=options.command_timeout),
        ),
    )


def _execution_outputs(execution: Any) -> tuple[int, str, str]:
    logs = getattr(execution, "logs", None)
    stdout = _join_output_chunks(getattr(logs, "stdout", None))
    stderr = _join_output_chunks(getattr(logs, "stderr", None))
    error = getattr(execution, "error", None)
    if error is not None:
        error_text = (
            f"{getattr(error, 'name', 'ERROR')}: "
            f"{getattr(error, 'value', error)}"
        )
        stderr = f"{stderr}\n{error_text}" if stderr else error_text

    exit_code = getattr(execution, "exit_code", None)
    if exit_code is None:
        exit_code = 0 if not stderr else -1

    try:
        return int(exit_code), stdout, stderr
    except (TypeError, ValueError):
        return -1, stdout, stderr


async def _cleanup_sandbox(sandbox: Any) -> None:
    if sandbox is None:
        return
    try:
        await sandbox.kill()
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.debug("OpenSandbox kill failed: %s", exc)
    try:
        await sandbox.close()
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.debug("OpenSandbox close failed: %s", exc)


async def execute_opensandbox_command(
    command: str,
    cwd: str = "",
    timeout: float = 60.0,
) -> ToolResponse:
    """Execute a shell command inside an OpenSandbox sandbox.

    Args:
        command: Shell command to run in the sandbox.
        cwd: Working directory inside the sandbox. Host Windows paths are not
            mounted in this MVP and will be ignored.
        timeout: Command timeout in seconds.

    Returns:
        ToolResponse containing sandbox id, exit code, stdout and stderr.
    """
    if not command or not command.strip():
        return _text_response("Error: command is required.")

    config = get_tool_config(_TOOL_NAME) or {}
    warnings: list[str] = []
    api_key = _resolve_api_key(config)
    options = _runtime_options(config, cwd, timeout, warnings)

    try:
        (
            connection_config_cls,
            run_command_opts_cls,
            sandbox_cls,
        ) = _load_opensandbox_sdk()
    except ImportError as exc:
        return _text_response(
            "Error: OpenSandbox SDK is not installed. Install or reload the "
            "OpenSandbox plugin dependencies first. "
            f"Import error: {exc}",
        )

    connection_config = _connection_config(
        connection_config_cls,
        config,
        options,
        api_key,
    )

    sandbox = None
    sandbox_id = "unknown"
    try:
        sandbox = await _create_sandbox(
            sandbox_cls,
            config,
            connection_config,
            options,
        )
        sandbox_id = _sandbox_id(sandbox)
        execution = await _run_command(
            sandbox,
            run_command_opts_cls,
            command,
            options,
        )
        exit_code, stdout, stderr = _execution_outputs(execution)

        return _text_response(
            _format_command_result(
                command=command,
                sandbox_id=sandbox_id,
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
                warnings=warnings,
            ),
        )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error(
            "OpenSandbox command execution failed: %s",
            exc,
            exc_info=True,
        )
        return _text_response(
            "Error: OpenSandbox command execution failed. "
            f"Sandbox: {sandbox_id}. Detail: {exc}",
        )
    finally:
        await _cleanup_sandbox(sandbox)
