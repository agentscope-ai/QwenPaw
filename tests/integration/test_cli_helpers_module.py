# -*- coding: utf-8 -*-
"""Integration tests for CLI command helpers (providers/channels/
skills/plugins).

Covers small pure helpers in src/qwenpaw/cli/providers_cmd.py,
channels_cmd.py, skills_cmd.py, plugin_commands.py — API-key masking,
provider configured checks, channel secret masking, skill scope
resolution, frontmatter validation, Zip Slip protection.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import click
import pytest


# ------------------------------------------------------------------ #
# providers_cmd
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_mask_api_key_empty() -> None:
    """Empty key masks to empty string."""
    from qwenpaw.cli.providers_cmd import _mask_api_key

    assert _mask_api_key("") == ""


@pytest.mark.integration
@pytest.mark.p1
def test_mask_api_key_short_fully_masked() -> None:
    """Keys of 8 chars or fewer are fully masked."""
    from qwenpaw.cli.providers_cmd import _mask_api_key

    assert _mask_api_key("abcd") == "****"
    assert _mask_api_key("12345678") == "********"


@pytest.mark.integration
@pytest.mark.p1
def test_mask_api_key_long_keeps_edges() -> None:
    """Long keys keep first 4 and last 2 chars."""
    from qwenpaw.cli.providers_cmd import _mask_api_key

    masked = _mask_api_key("sk-abcdef1234567890xyz")
    assert masked.startswith("sk-a")
    assert masked.endswith("z")
    assert "..." in masked
    assert "abcdef1234567890" not in masked


# ------------------------------------------------------------------ #
# channels_cmd
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_channel_mask_empty() -> None:
    """Empty secret masks to (empty)."""
    from qwenpaw.cli.channels_cmd import _mask

    assert _mask("") == "(empty)"


@pytest.mark.integration
@pytest.mark.p1
def test_channel_mask_short_fully_hidden() -> None:
    """Secrets of 4 chars or fewer are fully hidden."""
    from qwenpaw.cli.channels_cmd import _mask

    assert _mask("ab") == "****"
    assert _mask("abcd") == "****"


@pytest.mark.integration
@pytest.mark.p1
def test_channel_mask_long_keeps_prefix() -> None:
    """Long secrets keep the first 4 chars."""
    from qwenpaw.cli.channels_cmd import _mask

    assert _mask("supersecrettoken") == "supe****"


@pytest.mark.integration
@pytest.mark.p1
def test_get_channel_names_returns_dict() -> None:
    """Channel name map returns strings for registered channels."""
    from qwenpaw.cli.channels_cmd import _get_channel_names

    names = _get_channel_names()
    assert isinstance(names, dict)
    for key, value in names.items():
        assert isinstance(key, str)
        assert isinstance(value, str)
        assert value


# ------------------------------------------------------------------ #
# skills_cmd
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_resolve_scope_pool_flag() -> None:
    """--pool resolves to None (shared pool)."""
    from qwenpaw.cli.skills_cmd import _resolve_scope

    assert _resolve_scope(None, pool=True) is None


@pytest.mark.integration
@pytest.mark.p1
def test_resolve_scope_pool_and_agent_conflict() -> None:
    """--pool together with an agent id is rejected."""
    from qwenpaw.cli.skills_cmd import _resolve_scope

    with pytest.raises(click.ClickException, match="mutually exclusive"):
        _resolve_scope("agent-x", pool=True)


@pytest.mark.integration
@pytest.mark.p1
def test_resolve_scope_default_agent() -> None:
    """No agent and no pool resolves to 'default'."""
    from qwenpaw.cli.skills_cmd import _resolve_scope

    assert _resolve_scope(None, pool=False) == "default"
    assert _resolve_scope("  ", pool=False) == "default"


@pytest.mark.integration
@pytest.mark.p1
def test_resolve_scope_explicit_agent() -> None:
    """Explicit agent id is normalized and returned."""
    from qwenpaw.cli.skills_cmd import _resolve_scope

    assert _resolve_scope("  agent-a  ", pool=False) == "agent-a"


@pytest.mark.integration
@pytest.mark.p1
def test_resolve_scope_default_pool_fallback() -> None:
    """default_pool=True with no agent resolves to pool (None)."""
    from qwenpaw.cli.skills_cmd import _resolve_scope

    assert _resolve_scope(None, pool=False, default_pool=True) is None


@pytest.mark.integration
@pytest.mark.p1
def test_validate_skill_frontmatter_missing_file(tmp_path: Path) -> None:
    """Missing SKILL.md raises a ClickException."""
    from qwenpaw.cli.skills_cmd import _validate_skill_frontmatter

    with pytest.raises(click.ClickException, match="Missing SKILL.md"):
        _validate_skill_frontmatter(tmp_path)


@pytest.mark.integration
@pytest.mark.p1
def test_validate_skill_frontmatter_valid(tmp_path: Path) -> None:
    """A valid SKILL.md frontmatter passes validation."""
    from qwenpaw.cli.skills_cmd import _validate_skill_frontmatter

    (tmp_path / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: A demo skill.\n---\nBody.\n",
        encoding="utf-8",
    )
    _validate_skill_frontmatter(tmp_path)  # must not raise


@pytest.mark.integration
@pytest.mark.p1
def test_validate_skill_frontmatter_invalid(tmp_path: Path) -> None:
    """Missing name/description fails validation."""
    from qwenpaw.cli.skills_cmd import _validate_skill_frontmatter

    (tmp_path / "SKILL.md").write_text(
        "---\nname: only-name\n---\nBody.\n",
        encoding="utf-8",
    )
    with pytest.raises(click.ClickException):
        _validate_skill_frontmatter(tmp_path)


@pytest.mark.integration
@pytest.mark.p1
def test_get_agent_workspace_empty_id_rejected() -> None:
    """Empty agent id raises a ClickException."""
    from qwenpaw.cli.skills_cmd import _get_agent_workspace

    with pytest.raises(click.ClickException, match="empty"):
        _get_agent_workspace("")


@pytest.mark.integration
@pytest.mark.p1
def test_raise_conflict_formats_suggested_name() -> None:
    """Conflict message includes suggested replacement name."""
    from qwenpaw.cli.skills_cmd import _raise_conflict
    from qwenpaw.exceptions import SkillConflictError

    exc = SkillConflictError(
        {"message": "already exists", "suggested_name": "skill-2"},
    )
    with pytest.raises(click.ClickException, match="skill-2"):
        _raise_conflict(exc)


# ------------------------------------------------------------------ #
# plugin_commands
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_safe_extract_zip_normal(tmp_path: Path) -> None:
    """Normal zip members extract successfully."""
    from qwenpaw.cli.plugin_commands import _safe_extract_zip

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a.txt", "hello")
        zf.writestr("sub/b.txt", "world")
    buf.seek(0)

    extract = tmp_path / "out"
    extract.mkdir()
    with zipfile.ZipFile(buf) as zf:
        _safe_extract_zip(zf, extract)

    assert (extract / "a.txt").read_text(encoding="utf-8") == "hello"
    assert (extract / "sub" / "b.txt").read_text(encoding="utf-8") == "world"


@pytest.mark.integration
@pytest.mark.p1
def test_safe_extract_zip_slip_blocked(tmp_path: Path) -> None:
    """Path-traversal members raise ValueError (Zip Slip guard)."""
    from qwenpaw.cli.plugin_commands import _safe_extract_zip

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.txt", "pwned")
    buf.seek(0)

    extract = tmp_path / "out"
    extract.mkdir()
    with zipfile.ZipFile(buf) as zf:
        with pytest.raises(ValueError, match="Zip Slip"):
            _safe_extract_zip(zf, extract)

    assert not (tmp_path / "evil.txt").exists()
