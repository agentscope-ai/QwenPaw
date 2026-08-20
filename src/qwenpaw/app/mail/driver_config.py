# -*- coding: utf-8 -*-
"""Secret-free qwenpawmail DriverCard generation."""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
from pathlib import Path
from typing import Any

import yaml
from qwenpawmail_mcp.providers import ENTERPRISE_PROVIDERS

from ...config.config import (
    AGENT_MAIL_CREDENTIAL_REF,
    AgentMailConfig,
    save_agent_mail_credentials,
)
from ...drivers.contracts import CredentialRef, DriverCard, DriverPolicy
from ...drivers.errors import DriverCardError
from ...drivers.storage import dump_card, load_card
from ...utils.logging import sanitize_log_value

logger = logging.getLogger(__name__)


# Compatibility alias used by the agent router for provider validation.
ENTERPRISE_MAIL_PROVIDERS = ENTERPRISE_PROVIDERS

_MAIL_MCP_MODULE_ARGS = ["-m", "qwenpawmail_mcp"]
_INTERNAL_MAIL_MCP_ARGS = ["--internal-mail-mcp"]


def is_managed_qwenpawmail_card(path: Path) -> bool:
    """Return whether *path* is a QwenPaw-generated mail DriverCard."""
    if not path.is_file():
        return False
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return False
    if not isinstance(raw, dict):
        return False
    config = raw.get("config")
    if isinstance(config, dict) and config.get("managed_by") == "agent_mail":
        return True
    endpoint = raw.get("endpoint")
    return bool(
        isinstance(endpoint, dict)
        and endpoint.get("args") == ["-m", "qwenpawmail_mcp"],
    )


def resolve_qwenpawmail_endpoint() -> tuple[str, list[str]]:
    """Resolve the command and arguments for the qwenpawmail MCP server."""
    override = os.environ.get("QWENPAWMAIL_PYTHON", "").strip()
    if override:
        return override, list(_MAIL_MCP_MODULE_ARGS)
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable)
        cli_executable = executable.with_name(f"qwenpaw{executable.suffix}")
        return str(cli_executable), list(_INTERNAL_MAIL_MCP_ARGS)
    try:
        if importlib.util.find_spec("qwenpawmail_mcp") is not None:
            return sys.executable, list(_MAIL_MCP_MODULE_ARGS)
    except (ImportError, ValueError):
        pass
    return "python", list(_MAIL_MCP_MODULE_ARGS)


def resolve_qwenpawmail_command() -> str:
    """Resolve the executable used to launch the qwenpawmail MCP server."""
    return resolve_qwenpawmail_endpoint()[0]


def _load_managed_qwenpawmail_card(path: Path) -> DriverCard | None:
    """Load an existing managed card whose user policy must be retained."""
    if not is_managed_qwenpawmail_card(path):
        return None
    try:
        return load_card(path)
    except DriverCardError as exc:
        logger.warning(
            "Failed to preserve invalid qwenpawmail DriverCard %s: %s",
            sanitize_log_value(path),
            sanitize_log_value(exc),
        )
        return None


def build_qwenpawmail_env(
    mail: AgentMailConfig | None,
    workspace_dir: Path | None = None,
) -> dict[str, Any]:
    """Build secret-free DriverCard env bindings for qwenpawmail.

    Public endpoint values remain literals.  The authorization code is a
    runtime credential binding resolved from encrypted ``credentials.yaml``
    immediately before the MCP subprocess starts.
    """
    if mail is None or mail.is_new_account:
        return {}
    credential = mail.credential
    if not credential.name or not credential.auth_code:
        return {}

    env: dict[str, Any] = {
        "QWENPAWMAIL_EMAIL": f"{credential.name}@{credential.domain}",
        "QWENPAWMAIL_AUTH_CODE": {
            "source": "credential",
            "credential": "mail",
            "field": "auth_code",
        },
    }
    provider = (credential.provider or "").strip()
    profile = ENTERPRISE_MAIL_PROVIDERS.get(provider)
    if profile is not None:
        env["QWENPAWMAIL_IMAP_HOST"] = profile.imap_host
        env["QWENPAWMAIL_IMAP_PORT"] = str(profile.imap_port)
        env["QWENPAWMAIL_SMTP_HOST"] = profile.smtp_host
        env["QWENPAWMAIL_SMTP_PORT"] = str(profile.smtp_port)
    if workspace_dir is not None:
        env["QWENPAWMAIL_STATE_DIR"] = str(workspace_dir / "mail_state")
        env["QWENPAWMAIL_WORKSPACE_DIR"] = str(workspace_dir)
    return env


def generate_qwenpawmail_driver_card(
    workspace_dir: Path,
    mail: AgentMailConfig | None = None,
) -> bool:
    """Persist mail secrets and publish a secret-free qwenpawmail card."""
    try:
        card_path = workspace_dir / "drivers" / "mcp" / "qwenpawmail.yaml"
        existing = _load_managed_qwenpawmail_card(card_path)
        (workspace_dir / "mail_state").mkdir(parents=True, exist_ok=True)
        save_agent_mail_credentials(workspace_dir, mail)
        env = build_qwenpawmail_env(mail, workspace_dir)
        command, args = resolve_qwenpawmail_endpoint()
        has_runtime_mail_credential = bool(
            mail is not None
            and not mail.is_new_account
            and mail.credential.name
            and mail.credential.auth_code,
        )
        card = DriverCard(
            name="qwenpawmail",
            protocol="mcp",
            endpoint={
                "transport": "stdio",
                "command": command,
                "args": args,
                "env": env,
            },
            credentials=(
                {
                    "mail": CredentialRef(
                        kind="static",
                        ref=AGENT_MAIL_CREDENTIAL_REF,
                    ),
                }
                if has_runtime_mail_credential
                else {}
            ),
            config=(
                {
                    **existing.config,
                    "managed_by": "agent_mail",
                }
                if existing is not None
                else {
                    "display_name": "qwenpawmail",
                    "description": "",
                    "tools": None,
                    "managed_by": "agent_mail",
                }
            ),
            enabled=existing.enabled if existing is not None else True,
            policy=(
                existing.policy
                if existing is not None
                else DriverPolicy(default_effect="ask", rules=[])
            ),
        )
        dump_card(card, card_path)
        return True
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning(
            "Failed to generate qwenpawmail driver card for %s: %s",
            sanitize_log_value(workspace_dir),
            sanitize_log_value(exc),
        )
        return False


def sync_qwenpawmail_driver_card(
    workspace_dir: Path,
    mail: AgentMailConfig | None,
    backend: str,
    *,
    force_rewrite: bool = False,
) -> bool:
    """Keep the encrypted record and generated card in lockstep.

    The card is generated on every synchronization attempt; ``dump_card``
    avoids replacing an unchanged file.  This also upgrades old cards that
    embedded ``QWENPAWMAIL_AUTH_CODE`` as a plaintext scalar.
    """
    del force_rewrite  # Compatibility with existing callers.
    driver_card = workspace_dir / "drivers" / "mcp" / "qwenpawmail.yaml"
    if backend != "qwenpaw" or mail is None:
        driver_card.unlink(missing_ok=True)
        save_agent_mail_credentials(workspace_dir, None)
        return True
    if not generate_qwenpawmail_driver_card(workspace_dir, mail):
        # Never leave an enabled card containing superseded credentials when
        # publication fails.  The encrypted credential remains available for
        # rollback/retry, while the external capability fails closed.
        driver_card.unlink(missing_ok=True)
        return False
    return True
