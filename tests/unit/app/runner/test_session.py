# -*- coding: utf-8 -*-
"""Unit tests for ``qwenpaw.app.runner.session``.

Covers:
- ``_safe_json_loads`` recovery from corrupted JSON
- ``sanitize_filename`` Windows-illegal-character replacement
- ``SafeJSONSession`` save / load / update / get round-trip
- ``SafeJSONSession`` cross-channel migration helper
- ``migrate_legacy_weixin_session_files`` weixin -> wechat rename
- ``AgentStateError`` raised for missing-file ``allow_not_exist=False``
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

import json
from pathlib import Path

import pytest

from qwenpaw.app.runner import session as session_mod
from qwenpaw.app.runner.session import (
    SafeJSONSession,
    _safe_json_loads,
    migrate_legacy_weixin_session_files,
    sanitize_filename,
)
from qwenpaw.exceptions import AgentStateError


class _StateModule:
    """Minimal state module compatible with SessionBase APIs."""

    def __init__(self, state: dict) -> None:
        self._state = dict(state)

    def state_dict(self) -> dict:
        return dict(self._state)

    def load_state_dict(self, state: dict) -> None:
        self._state = dict(state)


# ---------------------------------------------------------------------------
# _safe_json_loads
# ---------------------------------------------------------------------------


def test_safe_json_loads_valid_json():
    assert _safe_json_loads('{"a": 1, "b": "x"}') == {"a": 1, "b": "x"}


def test_safe_json_loads_recovers_trailing_garbage():
    # A common concurrent-write artefact: a complete object followed by
    # an unrelated tail.  ``raw_decode`` should pull out the first object.
    content = '{"k": "v"}garbage'

    assert _safe_json_loads(content) == {"k": "v"}


def test_safe_json_loads_completely_corrupted_returns_empty_dict():
    # Contract: unparseable content returns {} rather than raising. The
    # function also logs a warning, but the warning message is an
    # implementation detail not worth asserting against.
    assert _safe_json_loads("this is not json", filepath="bad.json") == {}


# ---------------------------------------------------------------------------
# sanitize_filename
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("normal-name", "normal-name"),
        ("discord:dm:12345", "discord--dm--12345"),
        # Each unsafe character (\\, /, :, *, ?, ", <, >, |) is replaced.
        ('a/b\\c:d*e?f"g<h>i|j', "a--b--c--d--e--f--g--h--i--j"),
        # Safe characters are preserved.
        ("user_42@host", "user_42@host"),
    ],
)
def test_sanitize_filename(raw, expected):
    assert sanitize_filename(raw) == expected


# ---------------------------------------------------------------------------
# SafeJSONSession — save / load round-trip
# ---------------------------------------------------------------------------


@pytest.fixture
def session(tmp_path: Path) -> SafeJSONSession:
    return SafeJSONSession(save_dir=str(tmp_path))


@pytest.mark.asyncio
async def test_save_and_load_round_trip(session, tmp_path: Path):
    state = _StateModule({"value": 7})

    await session.save_session_state(
        session_id="sess-1",
        user_id="user-1",
        agent=state,
    )

    target = tmp_path / "user-1_sess-1.json"
    assert target.exists(), "session file should be written"
    saved = json.loads(target.read_text("utf-8"))
    assert saved == {"agent": {"value": 7}}

    restored = _StateModule({})
    await session.load_session_state(
        session_id="sess-1",
        user_id="user-1",
        agent=restored,
    )
    assert restored.state_dict() == {"value": 7}


@pytest.mark.asyncio
async def test_load_missing_session_allow_not_exist(session):
    state = _StateModule({"untouched": True})

    # Should NOT raise — and should leave the state untouched.
    await session.load_session_state(
        session_id="missing",
        user_id="u",
        agent=state,
        allow_not_exist=True,
    )
    assert state.state_dict() == {"untouched": True}


@pytest.mark.asyncio
async def test_load_missing_session_raises_when_not_allowed(session):
    with pytest.raises(AgentStateError):
        await session.load_session_state(
            session_id="missing",
            user_id="u",
            allow_not_exist=False,
            agent=_StateModule({}),
        )


# ---------------------------------------------------------------------------
# update_session_state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_session_state_creates_file(session, tmp_path: Path):
    await session.update_session_state(
        session_id="sess-2",
        key="agent.memory.x",
        value=[1, 2, 3],
        user_id="u",
    )

    saved = json.loads((tmp_path / "u_sess-2.json").read_text("utf-8"))
    assert saved == {"agent": {"memory": {"x": [1, 2, 3]}}}


@pytest.mark.asyncio
async def test_update_session_state_appends_to_existing(
    session,
    tmp_path: Path,
):
    path = tmp_path / "u_sess-3.json"
    path.write_text(
        json.dumps({"agent": {"memory": {"x": "old"}, "other": 1}}),
        encoding="utf-8",
    )

    await session.update_session_state(
        session_id="sess-3",
        key=("agent", "memory", "x"),
        value="new",
        user_id="u",
    )

    saved = json.loads(path.read_text("utf-8"))
    assert saved == {"agent": {"memory": {"x": "new"}, "other": 1}}


@pytest.mark.asyncio
async def test_update_session_state_missing_file_disallowed(session):
    with pytest.raises(AgentStateError):
        await session.update_session_state(
            session_id="ghost",
            key="agent.x",
            value=1,
            user_id="u",
            create_if_not_exist=False,
        )


@pytest.mark.asyncio
async def test_update_session_state_empty_key_path_rejected(session, tmp_path):
    # Empty sequence ``key`` triggers the "key path is empty" guard.
    # Create the file so the empty-key check runs *after* the file-exists
    # branch (the guard is reached either way, but we keep the path
    # exercise deterministic).
    (tmp_path / "u_sess-4.json").write_text("{}", encoding="utf-8")

    from agentscope_runtime.engine.schemas.exception import (
        ConfigurationException,
    )

    with pytest.raises(ConfigurationException):
        await session.update_session_state(
            session_id="sess-4",
            key=[],  # empty path
            value="anything",
            user_id="u",
        )


# ---------------------------------------------------------------------------
# get_session_state_dict
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_session_state_dict_empty_when_missing(session):
    result = await session.get_session_state_dict(
        session_id="nope",
        user_id="u",
    )

    assert result == {}


@pytest.mark.asyncio
async def test_get_session_state_dict_raises_when_required(session):
    with pytest.raises(AgentStateError):
        await session.get_session_state_dict(
            session_id="nope",
            user_id="u",
            allow_not_exist=False,
        )


@pytest.mark.asyncio
async def test_get_session_state_dict_recovers_from_corruption(
    session,
    tmp_path: Path,
):
    # File contains a recoverable object followed by trailing garbage.
    (tmp_path / "u_sess-5.json").write_text(
        '{"agent": {"a": 1}}garbage',
        encoding="utf-8",
    )

    result = await session.get_session_state_dict(
        session_id="sess-5",
        user_id="u",
    )

    assert result == {"agent": {"a": 1}}


# ---------------------------------------------------------------------------
# Channel sub-directory + cross-channel migration
# ---------------------------------------------------------------------------


def test_get_save_path_uses_channel_subdir(session, tmp_path: Path):
    path = session._get_save_path(
        session_id="sess",
        user_id="u",
        channel="console",
    )

    assert Path(path) == tmp_path / "console" / "u_sess.json"
    assert (tmp_path / "console").is_dir()


def test_get_save_path_migrates_legacy_session_into_channel(
    session,
    tmp_path: Path,
):
    legacy = tmp_path / "u_old-sess.json"
    legacy.write_text('{"legacy": true}', encoding="utf-8")

    path = session._get_save_path(
        session_id="old-sess",
        user_id="u",
        channel="discord",
    )

    target = tmp_path / "discord" / "u_old-sess.json"
    assert Path(path) == target
    assert target.exists(), "legacy session should be copied into channel dir"
    assert json.loads(target.read_text("utf-8")) == {"legacy": True}


# ---------------------------------------------------------------------------
# migrate_legacy_weixin_session_files
# ---------------------------------------------------------------------------


def test_migrate_legacy_weixin_session_files_renames_and_archives(
    tmp_path: Path,
):
    # ``user_42_weixin--sid@im.wechat.json`` is the legacy form.
    legacy_name = "user_42_weixin--sid@im.wechat.json"
    canonical_name = "user_42_wechat--sid@im.wechat.json"
    (tmp_path / legacy_name).write_text('{"v": 1}', encoding="utf-8")

    migrate_legacy_weixin_session_files(str(tmp_path))

    assert (tmp_path / canonical_name).exists()
    archive = tmp_path / ".weixin-legacy" / legacy_name
    assert archive.exists(), "original legacy file should be archived"
    # Live file should NOT remain at the legacy path.
    assert not (tmp_path / legacy_name).exists()


def test_migrate_legacy_weixin_session_files_archives_only_when_present(
    tmp_path: Path,
):
    legacy_name = "u_weixin--sid.json"
    canonical_name = "u_wechat--sid.json"
    legacy = tmp_path / legacy_name
    legacy.write_text('{"legacy": true}', encoding="utf-8")
    # Canonical already exists with different content — must stay intact.
    (tmp_path / canonical_name).write_text(
        '{"live": true}',
        encoding="utf-8",
    )

    migrate_legacy_weixin_session_files(str(tmp_path))

    canonical = json.loads(
        (tmp_path / canonical_name).read_text("utf-8"),
    )
    assert canonical == {
        "live": True,
    }, "live canonical file must not be overwritten"
    assert (tmp_path / ".weixin-legacy" / legacy_name).exists()
    assert not legacy.exists()


def test_migrate_legacy_weixin_session_files_noop_on_missing_dir():
    # Must not raise when the directory does not exist.
    migrate_legacy_weixin_session_files("/path/that/does/not/exist/xyz")


def test_migrate_legacy_weixin_session_files_noop_when_no_legacy(
    tmp_path: Path,
):
    (tmp_path / "u_wechat--sid.json").write_text("{}", encoding="utf-8")

    migrate_legacy_weixin_session_files(str(tmp_path))

    # No archive dir created when there is nothing to migrate.
    assert not (tmp_path / ".weixin-legacy").exists()


# ---------------------------------------------------------------------------
# Module exports — defensive check for the migration constant.
# ---------------------------------------------------------------------------


def test_archive_dir_constant_excluded_from_session_scans():
    # Callers list ``*.json`` non-recursively; the archive dir lives one
    # level down so it must not start with a dot-stripped name that
    # collides with session files.
    assert session_mod._WEIXIN_LEGACY_ARCHIVE_DIR.startswith(".")
