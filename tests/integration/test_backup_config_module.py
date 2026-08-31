# -*- coding: utf-8 -*-
"""Integration tests for backup restore helpers + config agent ids.

Covers src/qwenpaw/backup/_ops/restore.py (145 uncovered) and
src/qwenpaw/config/config.py agent-id helpers (167 uncovered).
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest


# ------------------------------------------------------------------ #
# backup restore helpers
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_zip_has_prefix(tmp_path) -> None:
    """_zip_has_prefix detects a member prefix."""
    from qwenpaw.backup._ops.restore import _zip_has_prefix

    zip_path = tmp_path / "x.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("agents/default/agent.json", "{}")
    with zipfile.ZipFile(zip_path) as zf:
        assert _zip_has_prefix(zf, "agents/") is True
        assert _zip_has_prefix(zf, "missing/") is False


@pytest.mark.integration
@pytest.mark.p1
def test_dedupe_restore_targets() -> None:
    """_dedupe_restore_targets removes duplicates."""
    from qwenpaw.backup._ops.restore import _dedupe_restore_targets

    targets = [Path("/a"), Path("/a"), Path("/b")]
    deduped = _dedupe_restore_targets(targets)
    assert len(deduped) == 2


@pytest.mark.integration
@pytest.mark.p1
def test_assert_restore_targets_available(tmp_path) -> None:
    """_assert_restore_targets_available passes for existing dirs."""
    from qwenpaw.backup._ops.restore import (
        _assert_restore_targets_available,
    )

    _assert_restore_targets_available([tmp_path])


# ------------------------------------------------------------------ #
# config agent id helpers
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_generate_short_agent_id() -> None:
    """generate_short_agent_id returns a short unique id."""
    from qwenpaw.config.config import generate_short_agent_id

    a = generate_short_agent_id()
    b = generate_short_agent_id()
    assert isinstance(a, str)
    assert a != b


@pytest.mark.integration
@pytest.mark.p1
def test_sanitize_agent_id() -> None:
    """sanitize_agent_id normalizes raw ids."""
    from qwenpaw.config.config import sanitize_agent_id

    sanitized = sanitize_agent_id("My Agent!")
    assert isinstance(sanitized, str)
    assert sanitized != ""


@pytest.mark.integration
@pytest.mark.p1
def test_validate_agent_id_valid() -> None:
    """validate_agent_id accepts a well-formed id."""
    from qwenpaw.config.config import validate_agent_id

    validate_agent_id("my-agent-1", set())  # must not raise


@pytest.mark.integration
@pytest.mark.p1
def test_validate_agent_id_invalid() -> None:
    """validate_agent_id rejects malformed ids."""
    from qwenpaw.config.config import validate_agent_id

    with pytest.raises(ValueError):
        validate_agent_id("", set())
    with pytest.raises(ValueError):
        validate_agent_id("bad id!", set())


@pytest.mark.integration
@pytest.mark.p1
def test_default_acp_agents() -> None:
    """_get_default_acp_agents returns the default set."""
    from qwenpaw.config.config import _get_default_acp_agents

    agents = _get_default_acp_agents()
    assert isinstance(agents, dict)
