# -*- coding: utf-8 -*-
"""Registry of coding CLIs managed by the worker management surface."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CliSpec:
    """Static description of one managed coding CLI.

    Attributes:
        id: URL/registry identifier, e.g. ``qwen-code``.
        name: Human-readable display name.
        npm_package: npm package installed with ``npm install -g``.
        bin_name: Executable name expected on PATH.
        settings_path: Main settings file, ``~`` expanded at use time.
        auth_paths: Dot-paths inside ``settings_path`` that hold
            credentials (redacted on read, ``***`` preserves on write).
        extra_auth_files: Additional credential files (entire file
            treated as secret).
        auth_env_vars: Env vars whose non-empty value counts as
            configured auth (reported as method ``env``; values are
            never echoed). Checked before auth_paths/extra_auth_files,
            matching Qoder's PAT-over-login precedence.
        requires: Binaries that must exist for install to be possible.
    """

    id: str
    name: str
    npm_package: str
    bin_name: str
    settings_path: str
    auth_paths: tuple[str, ...] = ()
    extra_auth_files: tuple[str, ...] = ()
    auth_env_vars: tuple[str, ...] = ()
    requires: tuple[str, ...] = ("npm",)
    defaults: dict[str, Any] = field(default_factory=dict)


CLIS: dict[str, CliSpec] = {
    spec.id: spec
    for spec in (
        CliSpec(
            id="qwen-code",
            name="Qwen Code",
            npm_package="@qwen-code/qwen-code",
            bin_name="qwen",
            settings_path="~/.qwen/settings.json",
            auth_paths=("security.auth.apiKey",),
        ),
        CliSpec(
            id="opencode",
            name="OpenCode",
            npm_package="opencode-ai",
            bin_name="opencode",
            settings_path="~/.config/opencode/opencode.json",
            extra_auth_files=("~/.local/share/opencode/auth.json",),
        ),
        CliSpec(
            id="qoder",
            name="Qoder",
            npm_package="@qoder-ai/qodercli",
            bin_name="qoder",
            settings_path="~/.qoder/settings.json",
            # Qoder auth is not an OpenAI-style settings dot-path:
            # headless/CI auth is the QODER_PERSONAL_ACCESS_TOKEN env
            # var; interactive /login keeps an auto-refreshed token in
            # its config dir (no documented stable file name, not
            # probed). Settings still manages model/tools/mcp.
            auth_env_vars=("QODER_PERSONAL_ACCESS_TOKEN",),
        ),
    )
}

#: Placeholder that means "keep the existing value" on settings write.
PRESERVE = "***"


def get_cli(cli_id: str) -> CliSpec | None:
    """Return the spec for ``cli_id`` or ``None`` when unknown."""
    return CLIS.get(cli_id)


def known_cli_ids() -> list[str]:
    """All registered CLI ids in registry order."""
    return list(CLIS)


__all__ = ["CLIS", "PRESERVE", "CliSpec", "get_cli", "known_cli_ids"]
