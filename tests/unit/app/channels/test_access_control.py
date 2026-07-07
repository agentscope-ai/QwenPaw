# -*- coding: utf-8 -*-
"""Unit tests for qwenpaw.app.channels.access_control."""

from __future__ import annotations

# pylint: disable=protected-access,redefined-outer-name,unused-argument,use-implicit-booleaness-not-comparison,unused-import  # noqa: E501

import json
import time
from pathlib import Path

import pytest

from qwenpaw.app.channels.access_control import (
    ACCESS_CONTROL_FILE,
    AccessControlStore,
    ChannelACL,
    PendingEntry,
    UserInfo,
)

# ---------------------------------------------------------------------------
# UserInfo
# ---------------------------------------------------------------------------


class TestUserInfo:
    def test_defaults(self):
        u = UserInfo()
        assert u.remark == ""
        assert u.username == ""

    def test_to_dict_roundtrip(self):
        u = UserInfo(remark="boss", username="alice")
        d = u.to_dict()
        assert d == {"remark": "boss", "username": "alice"}
        u2 = UserInfo.from_dict(d)
        assert u2.remark == "boss"
        assert u2.username == "alice"

    def test_from_dict_legacy_string(self):
        u = UserInfo.from_dict("just a remark")
        assert u.remark == "just a remark"
        assert u.username == ""

    def test_from_dict_none(self):
        u = UserInfo.from_dict(None)
        assert u.remark == ""
        assert u.username == ""

    def test_from_dict_missing_keys(self):
        u = UserInfo.from_dict({"username": "x"})
        assert u.username == "x"
        assert u.remark == ""


# ---------------------------------------------------------------------------
# PendingEntry
# ---------------------------------------------------------------------------


class TestPendingEntry:
    def test_to_dict_roundtrip(self):
        p = PendingEntry(
            user_id="u1",
            channel="console",
            timestamp=123.0,
            first_message="hi",
            remark="r",
            username="alice",
        )
        d = p.to_dict()
        assert d["user_id"] == "u1"
        p2 = PendingEntry.from_dict(d)
        assert p2.user_id == "u1"
        assert p2.first_message == "hi"
        assert p2.timestamp == 123.0

    def test_from_dict_defaults(self):
        p = PendingEntry.from_dict({"user_id": "u2", "channel": "feishu"})
        assert p.timestamp == 0.0
        assert p.first_message == ""
        assert p.remark == ""
        assert p.username == ""


# ---------------------------------------------------------------------------
# ChannelACL serialization / parsing
# ---------------------------------------------------------------------------


class TestChannelACL:
    def test_empty(self):
        acl = ChannelACL()
        d = acl.to_dict()
        assert d == {"whitelist": {}, "blacklist": {}, "pending": []}
        acl2 = ChannelACL.from_dict(d)
        assert acl2.whitelist == {}
        assert acl2.blacklist == {}
        assert acl2.pending == []

    def test_parse_user_map_legacy_string_values(self):
        acl = ChannelACL.from_dict(
            {"whitelist": {"u1": "remark1"}, "blacklist": {}, "pending": []},
        )
        assert acl.whitelist["u1"].remark == "remark1"

    def test_parse_user_map_list_format(self):
        acl = ChannelACL.from_dict(
            {"whitelist": ["u1", "u2"], "blacklist": [], "pending": []},
        )
        assert set(acl.whitelist.keys()) == {"u1", "u2"}

    def test_parse_user_map_current_dict_values(self):
        acl = ChannelACL.from_dict(
            {
                "whitelist": {"u1": {"remark": "r", "username": "n"}},
                "blacklist": {},
                "pending": [],
            },
        )
        assert acl.whitelist["u1"].remark == "r"
        assert acl.whitelist["u1"].username == "n"

    def test_parse_user_map_non_dict_returns_empty(self):
        acl = ChannelACL.from_dict(
            {"whitelist": 123, "blacklist": {}, "pending": []},
        )
        assert acl.whitelist == {}


# ---------------------------------------------------------------------------
# AccessControlStore — persistence + allow/deny + isolation
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> AccessControlStore:
    return AccessControlStore(tmp_path / ACCESS_CONTROL_FILE)


class TestAccessControlStore:  # pylint: disable=too-many-public-methods
    def test_whitelist_add_and_query(self, store: AccessControlStore):
        store.add_to_whitelist("console", "u1")
        assert store.is_whitelisted("console", "u1")
        assert not store.is_whitelisted("console", "u2")

    def test_blacklist_add_and_query(self, store: AccessControlStore):
        store.add_to_blacklist("console", "u1")
        assert store.is_blacklisted("console", "u1")
        assert not store.is_blacklisted("console", "u2")

    def test_add_to_whitelist_removes_from_blacklist(
        self,
        store: AccessControlStore,
    ):
        store.add_to_blacklist("console", "u1")
        store.add_to_whitelist("console", "u1")
        assert store.is_whitelisted("console", "u1")
        assert not store.is_blacklisted("console", "u1")

    def test_add_to_blacklist_removes_from_whitelist(
        self,
        store: AccessControlStore,
    ):
        store.add_to_whitelist("console", "u1")
        store.add_to_blacklist("console", "u1")
        assert store.is_blacklisted("console", "u1")
        assert not store.is_whitelisted("console", "u1")

    def test_per_channel_isolation(self, store: AccessControlStore):
        store.add_to_whitelist("console", "u1")
        assert store.is_whitelisted("console", "u1")
        assert not store.is_whitelisted("feishu", "u1")
        assert not store.is_blacklisted("feishu", "u1")

    def test_remove_from_whitelist(self, store: AccessControlStore):
        store.add_to_whitelist("console", "u1")
        store.remove_from_whitelist("console", "u1")
        assert not store.is_whitelisted("console", "u1")

    def test_remove_from_blacklist(self, store: AccessControlStore):
        store.add_to_blacklist("console", "u1")
        store.remove_from_blacklist("console", "u1")
        assert not store.is_blacklisted("console", "u1")

    def test_set_whitelist_replaces(self, store: AccessControlStore):
        store.add_to_whitelist("console", "u1", remark="keep")
        store.set_whitelist("console", ["u2", "u1"])
        assert store.is_whitelisted("console", "u1")
        assert store.is_whitelisted("console", "u2")
        # Remark preserved for retained IDs
        assert store.get_acl("console")["whitelist"]["u1"]["remark"] == "keep"

    def test_set_blacklist_replaces(self, store: AccessControlStore):
        store.add_to_blacklist("console", "u1")
        store.set_blacklist("console", ["u2"])
        assert not store.is_blacklisted("console", "u1")
        assert store.is_blacklisted("console", "u2")

    def test_blacklist_overrides_whitelist_via_check(
        self,
        store: AccessControlStore,
    ):
        # Mimic caller precedence: blacklist takes precedence over whitelist
        store.add_to_whitelist("console", "u1")
        store.add_to_blacklist("console", "u1")
        assert store.is_blacklisted("console", "u1")
        assert not store.is_whitelisted("console", "u1")

    def test_persistence_roundtrip(self, tmp_path: Path):
        path = tmp_path / ACCESS_CONTROL_FILE
        s1 = AccessControlStore(path)
        s1.add_to_whitelist("console", "u1", remark="r")
        s1.add_to_blacklist("console", "u2")
        s1.add_pending("console", "u3", first_message="hi")
        assert path.exists()

        s2 = AccessControlStore(path)
        assert s2.is_whitelisted("console", "u1")
        assert s2.is_blacklisted("console", "u2")
        pendings = s2.get_all_pending()
        assert len(pendings) == 1
        assert pendings[0]["user_id"] == "u3"

    def test_update_remark_whitelist(self, store: AccessControlStore):
        store.add_to_whitelist("console", "u1")
        assert store.update_remark("console", "u1", "new")
        assert store.get_acl("console")["whitelist"]["u1"]["remark"] == "new"

    def test_update_remark_blacklist(self, store: AccessControlStore):
        store.add_to_blacklist("console", "u1")
        assert store.update_remark("console", "u1", "blocked")
        assert (
            store.get_acl("console")["blacklist"]["u1"]["remark"] == "blocked"
        )

    def test_update_remark_unknown_user(self, store: AccessControlStore):
        assert not store.update_remark("console", "nobody", "x")

    def test_update_username_propagates_to_pending(
        self,
        store: AccessControlStore,
    ):
        store.add_pending("console", "u1", username="")
        assert store.update_username("console", "u1", "alice")
        pending = store.get_all_pending()
        assert pending[0]["username"] == "alice"

    def test_update_username_unknown(self, store: AccessControlStore):
        assert not store.update_username("console", "nobody", "x")

    def test_add_pending_idempotent(self, store: AccessControlStore):
        store.add_pending("console", "u1", first_message="a")
        store.add_pending("console", "u1", first_message="b")
        pendings = store.get_all_pending()
        assert len(pendings) == 1
        # First-message kept, not overwritten
        assert pendings[0]["first_message"] == "a"

    def test_add_pending_truncates_first_message(
        self,
        store: AccessControlStore,
    ):
        long = "x" * 500
        store.add_pending("console", "u1", first_message=long)
        p = store.get_all_pending()[0]
        assert len(p["first_message"]) == 200

    def test_approve_pending_moves_to_whitelist(
        self,
        store: AccessControlStore,
    ):
        store.add_pending(
            "console",
            "u1",
            username="alice",
            first_message="hi",
        )
        assert store.approve_pending("console", "u1", remark="ok")
        assert store.is_whitelisted("console", "u1")
        assert (
            store.get_acl("console")["whitelist"]["u1"]["username"] == "alice"
        )
        assert store.get_all_pending() == []

    def test_deny_pending_moves_to_blacklist(self, store: AccessControlStore):
        store.add_pending("console", "u1", username="alice")
        assert store.deny_pending("console", "u1")
        assert store.is_blacklisted("console", "u1")
        assert (
            store.get_acl("console")["blacklist"]["u1"]["username"] == "alice"
        )
        assert store.get_all_pending() == []

    def test_dismiss_pending_removes_without_listing(
        self,
        store: AccessControlStore,
    ):
        store.add_pending("console", "u1")
        assert store.dismiss_pending("console", "u1")
        assert store.get_all_pending() == []
        assert not store.is_whitelisted("console", "u1")
        assert not store.is_blacklisted("console", "u1")

    def test_dismiss_pending_unknown_returns_false(
        self,
        store: AccessControlStore,
    ):
        assert not store.dismiss_pending("console", "nobody")

    def test_approve_pending_carries_remark_when_blank(
        self,
        store: AccessControlStore,
    ):
        store.add_pending("console", "u1")
        store.update_pending_remark("console", "u1", "from-pending")
        store.approve_pending("console", "u1")
        assert (
            store.get_acl("console")["whitelist"]["u1"]["remark"]
            == "from-pending"
        )

    def test_get_all_pending_sorted_descending(
        self,
        store: AccessControlStore,
    ):
        store.add_pending("console", "u1")
        time.sleep(0.005)
        store.add_pending("console", "u2")
        pendings = store.get_all_pending()
        assert pendings[0]["user_id"] == "u2"
        assert pendings[1]["user_id"] == "u1"

    def test_get_all_acls_returns_all_channels(
        self,
        store: AccessControlStore,
    ):
        store.add_to_whitelist("console", "u1")
        store.add_to_blacklist("feishu", "u2")
        all_acls = store.get_all_acls()
        assert "console" in all_acls
        assert "feishu" in all_acls

    def test_import_allow_from_skips_existing(
        self,
        store: AccessControlStore,
    ):
        store.add_to_whitelist("console", "u1", remark="kept")
        store.import_allow_from("console", {"u1", "u2", "u3"})
        wl = store.get_acl("console")["whitelist"]
        assert set(wl.keys()) == {"u1", "u2", "u3"}
        # Existing user remark preserved
        assert wl["u1"]["remark"] == "kept"

    def test_import_allow_from_empty_is_noop(self, store: AccessControlStore):
        store.import_allow_from("console", set())
        assert store.get_all_acls() == {}

    def test_reload_if_stale_picks_up_external_change(
        self,
        tmp_path: Path,
    ):
        path = tmp_path / ACCESS_CONTROL_FILE
        store = AccessControlStore(path)
        # At init, file does not exist → _last_mtime stays 0.0
        assert store._last_mtime == 0.0
        # External write bumps mtime to "now" — definitely > 0
        path.write_text(
            json.dumps(
                {
                    "console": {
                        "whitelist": {"u1": {"remark": "", "username": ""}},
                        "blacklist": {},
                        "pending": [],
                    },
                },
            ),
            encoding="utf-8",
        )
        assert path.stat().st_mtime > 0
        assert store.is_whitelisted("console", "u1")

    def test_corrupt_file_does_not_crash(self, tmp_path: Path):
        path = tmp_path / ACCESS_CONTROL_FILE
        path.write_text("not-json", encoding="utf-8")
        store = AccessControlStore(path)
        assert store.get_all_acls() == {}
