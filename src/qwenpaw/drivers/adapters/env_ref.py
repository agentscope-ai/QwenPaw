# -*- coding: utf-8 -*-
"""Parse ${VAR} environment references embedded in legacy MCP values.

Legacy ``agent.json`` MCP clients may embed process-environment references in
header/env values (e.g. ``Authorization: "Bearer ${API_KEY}"``). The Driver
model represents such a reference structurally as an ``env:`` credential ref
resolved at runtime, instead of persisting the literal ``${VAR}`` text. These
helpers detect ``${VAR}`` references and describe how to rewrite one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ${VAR}: a standard environment variable name (letter/underscore first).
# A bare "$" (e.g. "$PATH", "p@$$w0rd") never matches, so literal secrets
# that merely contain "$" are left untouched.
_ENV_REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


@dataclass(frozen=True)
class EnvTemplate:
    """A value that embeds one or more ${VAR} references.

    ``format`` replaces every reference with the ``{value}`` placeholder that
    the credential binding resolver understands; it is only meaningful when a
    single reference is present (see :attr:`is_single`).
    """

    format: str
    var_names: tuple[str, ...]

    @property
    def is_single(self) -> bool:
        """True when exactly one ${VAR} reference was found."""
        return len(self.var_names) == 1


def parse_env_template(value: str) -> EnvTemplate | None:
    """Return an EnvTemplate if ``value`` embeds ${VAR}, else ``None``."""
    if "$" not in value:
        return None
    names = _ENV_REF_RE.findall(value)
    if not names:
        return None
    fmt = _ENV_REF_RE.sub("{value}", value)
    return EnvTemplate(format=fmt, var_names=tuple(names))


def env_alias(var_name: str) -> str:
    """Return the deterministic credential alias for an env-backed value."""
    return f"env_{var_name.strip().lower()}"


def env_ref(var_name: str) -> str:
    """Return the ``env:`` credential store ref for a variable name."""
    return f"env:{var_name.strip()}"
