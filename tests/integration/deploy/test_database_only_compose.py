# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
COMPOSE_PATH = ROOT / "deploy" / "compose.database.yml"


def _compose() -> dict:
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


def test_database_only_compose_contains_no_application_service():
    compose = _compose()

    assert compose["name"] == "weldonagent-database"
    assert set(compose["services"]) == {"agent-pg"}
    assert "build" not in compose["services"]["agent-pg"]


def test_database_only_compose_publishes_postgres_to_loopback_by_default():
    database = _compose()["services"]["agent-pg"]

    assert database["ports"] == [
        "${WELDON_DB_BIND_ADDRESS:-127.0.0.1}:${WELDON_DB_PORT:-5432}:5432"
    ]


def test_database_only_compose_keeps_database_data_outside_source_tree():
    database = _compose()["services"]["agent-pg"]
    data_mount, init_mount = database["volumes"]

    assert data_mount["source"].startswith("${WELDON_DATA_ROOT")
    assert data_mount["source"].endswith("/postgres")
    assert data_mount["target"] == "/var/lib/postgresql/data"
    assert init_mount["source"] == "./postgres-init.sh"
    assert init_mount["read_only"] is True
