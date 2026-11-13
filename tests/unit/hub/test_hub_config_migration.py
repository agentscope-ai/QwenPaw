# -*- coding: utf-8 -*-
"""Behavioural tests for the persisted Hub registration upgrades.

``qwenpaw.hub.config_migration`` owns three one-time upgrades that run
inside the caller's initialization transaction:

* ``legacy_registration_mode`` translates the deprecated boolean
  registration flag into one of the three published modes;
* ``upgrade_registration`` normalises the same field in an in-memory
  config document without rewriting the file;
* ``migrate_hub_settings`` rewrites the settings rows themselves.

All three are module-level pure functions over a sqlite connection, so
they are driven against a real initialized Hub database in ``tmp_path``.
Nothing here double-checks the SQL text; every assertion is about what
ends up in the rows, what is returned, or what is raised.

The mode-resolution precedence is the part worth pinning: an explicit
``registration_mode`` row wins over the mode carried inside
``hub_config``, which in turn wins over the legacy boolean, and only the
legacy boolean is allowed to be absent.
"""
# pylint: disable=redefined-outer-name,unused-argument,use-implicit-booleaness-not-comparison  # noqa: E501
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from qwenpaw.hub import config_migration as cm
from qwenpaw.hub.database import connect_hub_database, initialize_hub_database

NOW = "2026-09-17T20:00:00+00:00"
MODE_KEYS = ("registration_mode", "registration_enabled", "hub_config")


def _open(tmp_path: Path) -> Path:
    database = tmp_path / "control.db"
    initialize_hub_database(database)
    return database


def _seed(
    database: Path,
    settings: dict[str, Any] | None = None,
    *,
    drop_mode_row: bool = False,
) -> None:
    """Pre-load legacy rows on top of a freshly initialized database."""
    with connect_hub_database(database) as db:
        db.execute("BEGIN")
        if drop_mode_row:
            db.execute(
                "DELETE FROM hub_settings WHERE key = 'registration_mode'",
            )
        for key, value in (settings or {}).items():
            # initialize_hub_database already seeds registration_mode, so
            # seeding it again has to replace rather than insert.
            db.execute(
                "INSERT INTO hub_settings(key, value_json, updated_at) "
                "VALUES (?, ?, '2020-01-01T00:00:00+00:00') "
                "ON CONFLICT(key) DO UPDATE SET "
                "value_json = excluded.value_json, "
                "updated_at = excluded.updated_at",
                (key, json.dumps(value)),
            )


def _rows(database: Path) -> dict[str, dict[str, Any]]:
    """Read back the three migration-relevant settings rows."""
    out: dict[str, dict[str, Any]] = {}
    with connect_hub_database(database) as db:
        db.execute("BEGIN")
        cursor = db.execute(
            "SELECT key, value_json, revision, updated_at "
            "FROM hub_settings WHERE key IN (?, ?, ?)",
            MODE_KEYS,
        )
        for row in cursor.fetchall():
            out[str(row["key"])] = {
                "value": json.loads(str(row["value_json"])),
                "revision": int(row["revision"]),
                "updated_at": str(row["updated_at"]),
            }
    return out


def _migrate(database: Path) -> bool:
    """Run the migration the way initialize_hub_database does."""
    with connect_hub_database(database) as db:
        db.execute("BEGIN IMMEDIATE")
        return cm.migrate_hub_settings(db, NOW)


class TestLegacyRegistrationMode:
    @pytest.mark.parametrize(
        "enabled,expected",
        [(True, "open"), (False, "closed"), (None, "closed")],
    )
    def test_booleans_and_absence_map_to_a_mode(
        self,
        enabled: Any,
        expected: str,
    ) -> None:
        assert cm.legacy_registration_mode(enabled) == expected

    @pytest.mark.parametrize("value", ["open", "closed", [], {}, "True"])
    def test_non_booleans_are_refused(self, value: Any) -> None:
        with pytest.raises(ValueError) as excinfo:
            cm.legacy_registration_mode(value)
        assert excinfo.value.args[0] == (
            "Legacy Hub registration flag must be boolean"
        )

    @pytest.mark.parametrize("value", [1, 0])
    def test_ints_are_refused_even_though_they_are_truthy(
        self,
        value: int,
    ) -> None:
        # ``isinstance(1, bool)`` is False, so the guard rejects it rather
        # than reading it as a yes/no answer.
        with pytest.raises(ValueError):
            cm.legacy_registration_mode(value)


class TestUpgradeRegistration:
    @pytest.mark.parametrize(
        "config",
        [
            {},
            {"control_plane": "notadict"},
            {"control_plane": {}},
            {"control_plane": {"registration": "notadict"}},
            {"control_plane": {"registration": {"mode": "invite"}}},
        ],
    )
    def test_configs_without_the_legacy_field_are_returned_untouched(
        self,
        config: dict,
    ) -> None:
        before = json.dumps(config, sort_keys=True)

        upgraded, changed = cm.upgrade_registration(config)

        assert changed is False
        assert json.dumps(config, sort_keys=True) == before
        # The caller relies on identity to skip a pointless rewrite.
        assert upgraded is config

    def test_the_legacy_flag_becomes_a_mode(self) -> None:
        config: dict[str, Any] = {
            "control_plane": {
                "registration": {"enabled": True, "note": "x"},
            },
        }

        upgraded, changed = cm.upgrade_registration(config)

        assert changed is True
        assert upgraded == {
            "control_plane": {"registration": {"note": "x", "mode": "open"}},
        }

    def test_a_false_flag_becomes_closed(self) -> None:
        config: dict[str, Any] = {
            "control_plane": {"registration": {"enabled": False}},
        }

        upgraded, changed = cm.upgrade_registration(config)

        assert changed is True
        assert upgraded["control_plane"]["registration"] == {"mode": "closed"}

    def test_the_original_document_is_never_mutated(self) -> None:
        config: dict[str, Any] = {
            "control_plane": {
                "registration": {"enabled": True, "note": "x"},
            },
        }

        upgraded, _ = cm.upgrade_registration(config)

        assert config == {
            "control_plane": {
                "registration": {"enabled": True, "note": "x"},
            },
        }
        assert upgraded is not config
        assert (
            upgraded["control_plane"]["registration"]
            is not config["control_plane"]["registration"]
        )

    def test_an_explicit_null_flag_drops_the_field_without_guessing(
        self,
    ) -> None:
        config: dict[str, Any] = {
            "control_plane": {"registration": {"enabled": None}},
        }

        upgraded, changed = cm.upgrade_registration(config)

        assert changed is True
        # No mode is invented from an absent answer.
        assert upgraded == {"control_plane": {"registration": {}}}

    def test_an_existing_mode_wins_over_the_legacy_flag(self) -> None:
        config: dict[str, Any] = {
            "control_plane": {
                "registration": {"enabled": True, "mode": "invite"},
            },
        }

        upgraded, changed = cm.upgrade_registration(config)

        assert changed is True
        assert upgraded["control_plane"]["registration"] == {"mode": "invite"}

    def test_a_non_boolean_flag_raises_through_the_upgrade(self) -> None:
        config: dict[str, Any] = {
            "control_plane": {"registration": {"enabled": "bad"}},
        }

        with pytest.raises(ValueError) as excinfo:
            cm.upgrade_registration(config)
        assert excinfo.value.args[0] == (
            "Legacy Hub registration flag must be boolean"
        )


class TestMigrateHubSettingsNoOp:
    def test_a_clean_database_is_left_alone(self, tmp_path: Path) -> None:
        database = _open(tmp_path)

        assert _migrate(database) is False
        assert _rows(database)["registration_mode"]["value"] == "closed"

    def test_a_clean_database_without_the_seeded_mode_is_left_alone(
        self,
        tmp_path: Path,
    ) -> None:
        database = _open(tmp_path)
        _seed(database, drop_mode_row=True)

        assert _migrate(database) is False
        assert _rows(database) == {}

    def test_a_non_legacy_hub_config_alone_is_not_a_migration(
        self,
        tmp_path: Path,
    ) -> None:
        database = _open(tmp_path)
        _seed(
            database,
            {
                "hub_config": {
                    "control_plane": {"registration": {"mode": "invite"}},
                },
            },
            drop_mode_row=True,
        )

        assert _migrate(database) is False
        assert _rows(database)["hub_config"]["value"] == {
            "control_plane": {"registration": {"mode": "invite"}},
        }

    def test_running_twice_reports_no_second_upgrade(
        self,
        tmp_path: Path,
    ) -> None:
        database = _open(tmp_path)
        _seed(database, {"registration_enabled": True}, drop_mode_row=True)

        assert _migrate(database) is True
        first = _rows(database)
        assert _migrate(database) is False
        assert _rows(database) == first


class TestMigrateHubSettingsModeResolution:
    def test_the_legacy_boolean_row_decides_the_mode(
        self,
        tmp_path: Path,
    ) -> None:
        database = _open(tmp_path)
        _seed(database, {"registration_enabled": True}, drop_mode_row=True)

        assert _migrate(database) is True
        assert _rows(database)["registration_mode"]["value"] == "open"

    def test_a_false_legacy_row_yields_closed(self, tmp_path: Path) -> None:
        database = _open(tmp_path)
        _seed(database, {"registration_enabled": False}, drop_mode_row=True)

        assert _migrate(database) is True
        assert _rows(database)["registration_mode"]["value"] == "closed"

    def test_the_mode_inside_hub_config_beats_the_legacy_row(
        self,
        tmp_path: Path,
    ) -> None:
        database = _open(tmp_path)
        _seed(
            database,
            {
                "hub_config": {
                    "control_plane": {
                        "registration": {"enabled": False, "mode": "open"},
                    },
                },
                "registration_enabled": False,
            },
            drop_mode_row=True,
        )

        assert _migrate(database) is True
        assert _rows(database)["registration_mode"]["value"] == "open"

    def test_the_mode_inside_hub_config_beats_the_nested_legacy_flag(
        self,
        tmp_path: Path,
    ) -> None:
        database = _open(tmp_path)
        _seed(
            database,
            {
                "hub_config": {
                    "control_plane": {
                        "registration": {"enabled": False, "mode": "invite"},
                    },
                },
            },
            drop_mode_row=True,
        )

        assert _migrate(database) is True
        rows = _rows(database)
        assert rows["registration_mode"]["value"] == "invite"
        assert rows["hub_config"]["value"] == {
            "control_plane": {"registration": {"mode": "invite"}},
        }

    def test_an_explicit_mode_row_beats_everything_inside_hub_config(
        self,
        tmp_path: Path,
    ) -> None:
        database = _open(tmp_path)
        _seed(
            database,
            {
                "hub_config": {
                    "control_plane": {"registration": {"enabled": True}},
                },
                "registration_mode": "invite",
            },
        )

        assert _migrate(database) is True
        rows = _rows(database)
        assert rows["registration_mode"]["value"] == "invite"
        # The legacy flag is still rewritten into the winning mode.
        assert rows["hub_config"]["value"] == {
            "control_plane": {"registration": {"mode": "invite"}},
        }


class TestMigrateHubSettingsWrites:
    def test_the_legacy_flag_is_removed_from_hub_config(
        self,
        tmp_path: Path,
    ) -> None:
        database = _open(tmp_path)
        _seed(
            database,
            {
                "hub_config": {
                    "control_plane": {
                        "registration": {"enabled": True, "note": "keep"},
                    },
                },
            },
            drop_mode_row=True,
        )

        assert _migrate(database) is True

        rows = _rows(database)
        assert rows["hub_config"]["value"] == {
            "control_plane": {
                "registration": {"note": "keep", "mode": "open"},
            },
        }
        assert rows["hub_config"]["revision"] == 2
        assert rows["hub_config"]["updated_at"] == NOW
        assert rows["registration_mode"]["value"] == "open"
        assert rows["registration_mode"]["updated_at"] == NOW

    def test_the_legacy_settings_row_is_deleted(
        self,
        tmp_path: Path,
    ) -> None:
        database = _open(tmp_path)
        _seed(database, {"registration_enabled": True}, drop_mode_row=True)

        assert _migrate(database) is True

        assert "registration_enabled" not in _rows(database)

    def test_an_unrelated_hub_config_is_not_bumped(
        self,
        tmp_path: Path,
    ) -> None:
        database = _open(tmp_path)
        _seed(
            database,
            {
                "hub_config": {
                    "control_plane": {"registration": {"mode": "open"}},
                },
                "registration_enabled": True,
            },
            drop_mode_row=True,
        )

        assert _migrate(database) is True

        rows = _rows(database)
        # Nothing legacy lived inside hub_config, so it keeps revision 1.
        assert rows["hub_config"]["revision"] == 1
        assert rows["registration_mode"]["value"] == "open"

    def test_a_seeded_mode_row_equal_to_the_result_is_not_rewritten(
        self,
        tmp_path: Path,
    ) -> None:
        database = _open(tmp_path)
        _seed(database, {"registration_enabled": True})
        before = _rows(database)["registration_mode"]

        assert _migrate(database) is True

        after = _rows(database)["registration_mode"]
        assert after["value"] == before["value"]
        assert after["revision"] == before["revision"]
        assert after["updated_at"] == before["updated_at"]


class TestMigrateHubSettingsRejections:
    def test_a_non_object_hub_config_is_refused(self, tmp_path: Path) -> None:
        database = _open(tmp_path)
        _seed(database, {"hub_config": [1, 2]})

        with pytest.raises(ValueError) as excinfo:
            _migrate(database)

        assert excinfo.value.args[0] == (
            "Persisted Hub config must be an object"
        )

    @pytest.mark.parametrize("bad", ["bogus", "", "OPEN", 5, None])
    def test_an_unusable_mode_is_refused(
        self,
        tmp_path: Path,
        bad: Any,
    ) -> None:
        database = _open(tmp_path)
        _seed(
            database,
            {"registration_enabled": True, "registration_mode": bad},
        )

        with pytest.raises(ValueError) as excinfo:
            _migrate(database)

        assert excinfo.value.args[0] == (
            "Invalid Hub registration mode during migration"
        )

    def test_a_non_boolean_legacy_flag_is_refused(
        self,
        tmp_path: Path,
    ) -> None:
        database = _open(tmp_path)
        _seed(
            database,
            {
                "hub_config": {
                    "control_plane": {"registration": {"enabled": "bad"}},
                },
            },
            drop_mode_row=True,
        )

        with pytest.raises(ValueError) as excinfo:
            _migrate(database)

        assert excinfo.value.args[0] == (
            "Legacy Hub registration flag must be boolean"
        )

    def test_a_refused_migration_leaves_the_rows_untouched(
        self,
        tmp_path: Path,
    ) -> None:
        database = _open(tmp_path)
        _seed(database, {"registration_enabled": True})
        with connect_hub_database(database) as db:
            db.execute("BEGIN")
            db.execute(
                "UPDATE hub_settings SET value_json = ? "
                "WHERE key = 'registration_mode'",
                ('"bogus"',),
            )
        before = _rows(database)

        with pytest.raises(ValueError):
            _migrate(database)

        # The caller's transaction rolls back, so the legacy row survives
        # and nothing was half-written.
        assert _rows(database) == before
        assert "registration_enabled" in _rows(database)


class TestMigrateHubSettingsTolerances:
    def test_a_malformed_registration_block_is_ignored_not_fatal(
        self,
        tmp_path: Path,
    ) -> None:
        database = _open(tmp_path)
        _seed(
            database,
            {
                "hub_config": {
                    "control_plane": {"registration": "weird"},
                },
                "registration_enabled": True,
            },
            drop_mode_row=True,
        )

        assert _migrate(database) is True

        rows = _rows(database)
        # The odd block is left exactly as it was; the mode comes from the
        # legacy row instead.
        assert rows["hub_config"]["value"] == {
            "control_plane": {"registration": "weird"},
        }
        assert rows["registration_mode"]["value"] == "open"

    def test_a_hub_config_without_a_control_plane_is_ignored(
        self,
        tmp_path: Path,
    ) -> None:
        database = _open(tmp_path)
        _seed(
            database,
            {"hub_config": {"other": 1}, "registration_enabled": False},
            drop_mode_row=True,
        )

        assert _migrate(database) is True
        assert _rows(database)["registration_mode"]["value"] == "closed"

    @pytest.mark.parametrize("mode", ["open", "invite", "closed"])
    def test_every_published_mode_is_accepted(
        self,
        tmp_path: Path,
        mode: str,
    ) -> None:
        database = _open(tmp_path)
        _seed(
            database,
            {
                "hub_config": {
                    "control_plane": {
                        "registration": {"enabled": True, "mode": mode},
                    },
                },
            },
            drop_mode_row=True,
        )

        assert _migrate(database) is True
        assert _rows(database)["registration_mode"]["value"] == mode


class TestMigrateHubSettingsTransactionShape:
    def test_it_runs_inside_the_callers_transaction(
        self,
        tmp_path: Path,
    ) -> None:
        database = _open(tmp_path)
        _seed(database, {"registration_enabled": True}, drop_mode_row=True)

        connection = connect_hub_database(database)
        try:
            assert connection.in_transaction is False
            connection.execute("BEGIN IMMEDIATE")
            migrated = cm.migrate_hub_settings(connection, NOW)
            assert migrated is True
            # Visible to the same transaction before any commit.
            visible = connection.execute(
                "SELECT key FROM hub_settings WHERE key = 'registration_mode'",
            ).fetchone()
            assert visible is not None
            assert connection.in_transaction is True
            connection.rollback()
        finally:
            connection.close()

        # Rolled back, so the file still holds the legacy row.
        assert "registration_enabled" in _rows(database)

    def test_the_connection_it_is_given_is_not_closed(
        self,
        tmp_path: Path,
    ) -> None:
        database = _open(tmp_path)
        connection = connect_hub_database(database)
        try:
            connection.execute("BEGIN IMMEDIATE")
            cm.migrate_hub_settings(connection, NOW)
            connection.commit()
            # Still usable by the caller, which continues its own work.
            probe = connection.execute("SELECT 1 AS ok").fetchone()
            assert int(probe["ok"]) == 1
        finally:
            connection.close()
