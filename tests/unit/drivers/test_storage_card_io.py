# -*- coding: utf-8 -*-
"""Unit tests for DriverCard YAML storage helpers.

Covers load/dump round trips, mapping-to-model conversion error paths
(card / policy / condition / time-range), the filesystem snapshot with
duplicate-name detection, and the card deletion helpers.
"""
# pylint: disable=protected-access,redefined-outer-name,use-implicit-booleaness-not-comparison  # noqa: E501
from __future__ import annotations

from pathlib import Path

import pytest

from qwenpaw.drivers.contracts import DriverCard, CredentialRef
from qwenpaw.drivers.errors import DriverCardError
from qwenpaw.drivers.policy_types import DriverPolicy
from qwenpaw.drivers.storage import (
    AsyncDriverCardStore,
    _card_from_mapping,
    _condition_from_mapping,
    _time_range_from_mapping,
    card_paths_for_name,
    delete_card,
    delete_card_paths_for_name,
    dump_card,
    load_card,
)


def _minimal_card(**overrides) -> DriverCard:
    data = {
        "name": "demo",
        "protocol": "mcp",
        "endpoint": {"url": "http://127.0.0.1:9"},
    }
    data.update(overrides)
    return _card_from_mapping(data, Path("demo.yaml"))


# ---------------------------------------------------------------------------
# _card_from_mapping
# ---------------------------------------------------------------------------


class TestCardFromMapping:
    def test_missing_required_fields_raise(self):
        with pytest.raises(DriverCardError, match="missing required"):
            _card_from_mapping({"name": "x"}, Path("x.yaml"))

    def test_non_mapping_credentials_raise(self):
        with pytest.raises(DriverCardError, match="credentials"):
            _card_from_mapping(
                {
                    "name": "x",
                    "protocol": "mcp",
                    "endpoint": {"url": "u"},
                    "credentials": "oops",
                },
                Path("x.yaml"),
            )

    def test_none_credentials_default_empty(self):
        card = _card_from_mapping(
            {
                "name": "x",
                "protocol": "mcp",
                "endpoint": {"url": "u"},
                "credentials": None,
            },
            Path("x.yaml"),
        )
        assert card.credentials == {}

    def test_non_mapping_endpoint_raises(self):
        with pytest.raises(DriverCardError, match="endpoint"):
            _card_from_mapping(
                {"name": "x", "protocol": "mcp", "endpoint": "str"},
                Path("x.yaml"),
            )

    def test_non_mapping_config_raises(self):
        with pytest.raises(DriverCardError, match="config"):
            _card_from_mapping(
                {
                    "name": "x",
                    "protocol": "mcp",
                    "endpoint": {"url": "u"},
                    "config": [1, 2],
                },
                Path("x.yaml"),
            )

    def test_full_mapping_builds_card(self):
        card = _card_from_mapping(
            {
                "name": "svc",
                "protocol": "mcp",
                "endpoint": {"url": "http://x"},
                "credentials": {
                    "api": {"kind": "env", "ref": "API_KEY"},
                    "junk": "not-a-dict",
                },
                "config": {"timeout": 5},
                "enabled": False,
            },
            Path("svc.yaml"),
        )
        assert card.name == "svc"
        assert card.enabled is False
        assert card.credentials == {
            "api": CredentialRef(kind="env", ref="API_KEY"),
        }
        assert card.config == {"timeout": 5}
        assert card.policy == DriverPolicy()


# ---------------------------------------------------------------------------
# _condition_from_mapping / _time_range_from_mapping
# ---------------------------------------------------------------------------


class TestConditionAndTimeRange:
    def test_condition_none_returns_none(self):
        assert _condition_from_mapping(None, Path("p")) is None

    def test_condition_non_mapping_raises(self):
        with pytest.raises(DriverCardError, match="condition"):
            _condition_from_mapping("x", Path("p"))

    def test_condition_rate_limit_unsupported(self):
        with pytest.raises(DriverCardError, match="rate_limit"):
            _condition_from_mapping({"rate_limit": 1}, Path("p"))

    def test_condition_with_time_range(self):
        condition = _condition_from_mapping(
            {"time_range": {"after": "09:00", "before": "18:00"}},
            Path("p"),
        )
        assert condition is not None
        assert condition.time_range.after == "09:00"
        assert condition.time_range.before == "18:00"

    def test_time_range_none_returns_none(self):
        assert _time_range_from_mapping(None, Path("p")) is None

    def test_time_range_non_mapping_raises(self):
        with pytest.raises(DriverCardError, match="time_range"):
            _time_range_from_mapping("bad", Path("p"))

    def test_time_range_with_weekdays(self):
        tr = _time_range_from_mapping(
            {"after": "1", "before": "2", "weekdays": ["mon", "fri"]},
            Path("p"),
        )
        assert tr.weekdays == ["mon", "fri"]


# ---------------------------------------------------------------------------
# _policy_from_mapping
# ---------------------------------------------------------------------------


class TestPolicyFromMapping:
    def test_none_returns_default_policy(self):
        from qwenpaw.drivers.storage import _policy_from_mapping

        assert _policy_from_mapping(None, Path("p")) == DriverPolicy()

    def test_non_mapping_non_list_raises(self):
        from qwenpaw.drivers.storage import _policy_from_mapping

        with pytest.raises(DriverCardError, match="policy"):
            _policy_from_mapping("bad", Path("p"))

    def test_legacy_list_defaults_deny(self):
        from qwenpaw.drivers.storage import _policy_from_mapping
        from qwenpaw.drivers.constants import POLICY_EFFECT_DENY

        policy = _policy_from_mapping([{"subject": "s"}], Path("p"))
        assert policy.default_effect == POLICY_EFFECT_DENY
        assert len(policy.rules) == 1

    def test_rules_non_list_raises(self):
        from qwenpaw.drivers.storage import _policy_from_mapping

        with pytest.raises(DriverCardError, match="policy.rules"):
            _policy_from_mapping({"rules": "bad"}, Path("p"))

    def test_rule_non_mapping_raises(self):
        from qwenpaw.drivers.storage import _policy_rule_from_mapping

        with pytest.raises(DriverCardError, match="policy rule"):
            _policy_rule_from_mapping("bad", Path("p"))

    def test_rule_defaults(self):
        from qwenpaw.drivers.storage import _policy_rule_from_mapping
        from qwenpaw.drivers.constants import (
            POLICY_EFFECT_ASK,
            POLICY_TARGET_WILDCARD,
        )

        rule = _policy_rule_from_mapping({}, Path("p"))
        assert rule.subject == POLICY_TARGET_WILDCARD
        assert rule.effect == POLICY_EFFECT_ASK

    def test_target_non_mapping_raises(self):
        from qwenpaw.drivers.storage import _policy_target_from_mapping

        with pytest.raises(DriverCardError, match="policy target"):
            _policy_target_from_mapping("bad", Path("p"))


# ---------------------------------------------------------------------------
# load_card / dump_card round trip
# ---------------------------------------------------------------------------


class TestLoadDumpCard:
    def test_round_trip(self, tmp_path):
        card = _minimal_card()
        path = tmp_path / "demo.yaml"
        dump_card(card, path)
        loaded = load_card(path)
        assert loaded.name == "demo"
        assert loaded.protocol == "mcp"
        assert loaded.endpoint == {"url": "http://127.0.0.1:9"}

    def test_load_missing_file_raises(self, tmp_path):
        with pytest.raises(DriverCardError, match="Failed to read"):
            load_card(tmp_path / "ghost.yaml")

    def test_load_bad_yaml_raises(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text("key: [unclosed\n\t- broken", encoding="utf-8")
        with pytest.raises(DriverCardError, match="Failed to parse"):
            load_card(path)

    def test_load_non_mapping_yaml_raises(self, tmp_path):
        path = tmp_path / "list.yaml"
        path.write_text("- a\n- b\n", encoding="utf-8")
        with pytest.raises(DriverCardError, match="mapping"):
            load_card(path)

    def test_dump_creates_parent_dirs(self, tmp_path):
        card = _minimal_card()
        path = tmp_path / "nested" / "deep" / "demo.yaml"
        dump_card(card, path)
        assert path.exists()


# ---------------------------------------------------------------------------
# store snapshot + deletion helpers
# ---------------------------------------------------------------------------


class TestStoreSnapshotAndDelete:
    def test_snapshot_maps_names_to_mtimes(self, tmp_path):
        cards_dir = tmp_path / "cards"
        cards_dir.mkdir()
        store = AsyncDriverCardStore(cards_dir)
        path = store.path_for("demo", protocol="mcp")
        dump_card(_minimal_card(), path)

        snapshot = store._snapshot_sync()

        assert list(snapshot) == ["mcp/demo.yaml"]
        name, mtime = snapshot["mcp/demo.yaml"]
        assert name == "demo"
        assert mtime > 0

    def test_snapshot_warns_on_duplicate_names(self, tmp_path):
        cards_dir = tmp_path / "cards"
        store = AsyncDriverCardStore(cards_dir)
        first = store.path_for("demo", protocol="mcp")
        dump_card(_minimal_card(), first)
        # Same card name under a different protocol dir -> duplicate name.
        second = store.path_for("demo", protocol="http")
        dump_card(_minimal_card(protocol="http"), second)

        snapshot = store._snapshot_sync()

        assert "http/demo.yaml" in snapshot
        assert "mcp/demo.yaml" in snapshot

    def test_delete_card_removes_file(self, tmp_path):
        path = tmp_path / "x.yaml"
        path.write_text("name: x", encoding="utf-8")
        delete_card(path)
        assert not path.exists()

    def test_delete_card_missing_is_noop(self, tmp_path):
        delete_card(tmp_path / "ghost.yaml")

    def test_delete_card_paths_for_name_keeps_target(self, tmp_path):
        cards_dir = tmp_path / "cards"
        store = AsyncDriverCardStore(cards_dir)
        keep = store.path_for("demo", protocol="mcp")
        dump_card(_minimal_card(), keep)
        other = store.path_for("demo", protocol="http")
        dump_card(_minimal_card(protocol="http"), other)

        delete_card_paths_for_name(cards_dir, "demo", keep=keep)

        assert keep.exists()
        assert not other.exists()

    def test_card_paths_for_name(self, tmp_path):
        cards_dir = tmp_path / "cards"
        store = AsyncDriverCardStore(cards_dir)
        target = store.path_for("demo", protocol="mcp")
        dump_card(_minimal_card(), target)
        dump_card(
            _minimal_card(name="other", protocol="http"),
            store.path_for("other", protocol="http"),
        )
        assert card_paths_for_name(cards_dir, "demo") == [target]
