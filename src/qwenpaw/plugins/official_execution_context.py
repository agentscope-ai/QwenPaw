# -*- coding: utf-8 -*-
"""SDK-free host projection for explicitly selected official channel data.

The pure projection does not authorize a plugin. Automatic callers must first
match their trusted description's owner against the delivered official catalog.
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from ..config.channel_config_compat import absolute_execution_paths
from .execution.bootstrap import validate_private_environment

_PATH_FIELDS = {
    "imessage": ("db_path",),
    "mqtt": ("tls_ca_certs", "tls_certfile", "tls_keyfile"),
    "wechat": ("bot_token_file",),
}
_QQ_ENVIRONMENT = ("QQ_API_BASE", "QQ_TOKEN_URL", "QQ_PORTAL_HOST")


def project_official_execution(
    channel_key: str,
    config: Mapping,
    *,
    working_dir: Path,
    legacy_state_dir: Path,
    environment: Mapping[str, str],
    workspace_dir: Path | None = None,
    legacy_references: Mapping | None = None,
    matrix_binding: Mapping | None = None,
) -> tuple[dict, dict[str, str]]:
    """Detach known old paths/credentials without reading ambient host state."""
    values = dict(config)
    legacy_state_dir = Path(legacy_state_dir).expanduser()
    if not legacy_state_dir.is_absolute():
        legacy_state_dir = working_dir / legacy_state_dir
    private_env = {}
    if channel_key == "qq":
        private_env = {
            name: environment[name]
            for name in _QQ_ENVIRONMENT
            if name in environment
        }
    elif channel_key == "sip" and not values.get("dashscope_api_key"):
        values["dashscope_api_key"] = environment.get("DASHSCOPE_API_KEY", "")
    elif channel_key == "imessage":
        values["db_path"] = (
            values.get("db_path") or "~/Library/Messages/chat.db"
        )
        if not values.get("media_dir") and not workspace_dir:
            values["media_dir"] = str(legacy_state_dir / "media")
    elif channel_key == "wechat":
        values["bot_token_file"] = (
            values.get("bot_token_file")
            or legacy_state_dir / "wechat_bot_token"
        )
    if channel_key in {"matrix", "azure_bot"}:
        # Overwrite client claims; this field is execution-only, never saved.
        values["legacy_state_dir"] = str(legacy_state_dir)
    if channel_key == "azure_bot":
        from .azure_legacy import project_azure_legacy

        values["legacy_reference_owner"] = project_azure_legacy(
            legacy_references,
            {
                "workspace_dir": (
                    str(Path(workspace_dir).expanduser().resolve())
                    if workspace_dir is not None
                    else ""
                ),
                "app_id": values.get("app_id", ""),
                "tenant_id": values.get("tenant_id") or "botframework.com",
            },
        )
    if channel_key == "matrix":
        from .matrix_legacy import project_matrix_legacy

        values["legacy_state_owner"] = project_matrix_legacy(
            matrix_binding,
            homeserver=str(values.get("homeserver") or ""),
            workspace_dir=workspace_dir,
        )
    values = absolute_execution_paths(
        values,
        path_fields=("media_dir", *_PATH_FIELDS.get(channel_key, ())),
        working_dir=working_dir,
    )
    return values, validate_private_environment(private_env)


def prepare_official_execution(
    channel_key,
    config,
    *,
    official,
    working_dir,
    legacy_state_dir,
    environment,
    workspace_dir=None,
    legacy_references=None,
):
    """Read selected host context after the factory's official owner gate."""
    if legacy_references is not None and (
        official is None or channel_key != "azure_bot"
    ):
        raise ValueError("AZURE_LEGACY_CONTEXT_CHANNEL_INVALID")
    if official is None:
        return dict(config), {}
    matrix_binding = None
    if channel_key == "azure_bot" and legacy_references is None:
        from .azure_legacy import load_azure_legacy

        legacy_references = load_azure_legacy(
            legacy_state_dir=legacy_state_dir,
        )
    elif channel_key == "matrix":
        from .matrix_legacy import load_matrix_legacy

        matrix_binding = load_matrix_legacy(legacy_state_dir=legacy_state_dir)
    return project_official_execution(
        channel_key,
        config,
        working_dir=working_dir,
        legacy_state_dir=legacy_state_dir,
        environment=environment,
        workspace_dir=workspace_dir,
        legacy_references=legacy_references,
        matrix_binding=matrix_binding,
    )


def capture_official_legacy(*, config_path, legacy_state_dir, working_dir):
    """Isolate per-channel capture failures before config/default migration."""
    from .azure_legacy import AzureLegacyError, capture_azure_legacy
    from .matrix_legacy import MatrixLegacyError, capture_matrix_legacy

    failed = {}
    for key, capture in (
        ("azure_bot", capture_azure_legacy),
        ("matrix", capture_matrix_legacy),
    ):
        try:
            capture(
                config_path=config_path,
                legacy_state_dir=legacy_state_dir,
                working_dir=working_dir,
            )
        except (AzureLegacyError, MatrixLegacyError) as exc:
            failed[key] = str(exc)
    return failed
