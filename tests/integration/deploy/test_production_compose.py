# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
COMPOSE_PATH = ROOT / "deploy" / "compose.production.yml"


def _compose() -> dict:
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


def test_production_compose_has_expected_services():
    compose = _compose()
    assert compose["name"] == "weldonagent"
    assert set(compose["services"]) == {
        "agent-pg",
        "agent-init",
        "agent-app",
        "agent-maintenance",
    }
    assert compose["services"]["agent-pg"]["container_name"] == "agent-pg"
    assert compose["services"]["agent-app"]["container_name"] == "agent-app"


def test_postgres_is_not_published_to_host():
    database = _compose()["services"]["agent-pg"]
    assert "ports" not in database
    assert database["healthcheck"]["test"][0] == "CMD-SHELL"


def test_production_data_uses_external_bind_mounts():
    compose = _compose()
    app_mount = compose["services"]["agent-app"]["volumes"][0]
    database_mount = compose["services"]["agent-pg"]["volumes"][0]
    assert app_mount["source"].startswith("${WELDON_DATA_ROOT")
    assert app_mount["target"] == "/data"
    assert database_mount["source"].endswith("/postgres")
    assert database_mount["target"] == "/var/lib/postgresql/data"


def test_initialization_is_explicit_and_application_does_not_run_migrations():
    compose = _compose()
    init_command = " ".join(compose["services"]["agent-init"]["command"])
    app_command = " ".join(compose["services"]["agent-app"]["command"])
    assert "database-upgrade" in init_command
    assert "init --defaults --accept-security" in init_command
    assert "database-upgrade" not in app_command


def test_default_web_binding_is_loopback_only():
    ports = _compose()["services"]["agent-app"]["ports"]
    assert ports == [
        "${WELDON_BIND_ADDRESS:-127.0.0.1}:${WELDON_PORT:-18089}:18089"
    ]


def test_maintenance_service_is_private_and_uses_internal_backup_cli():
    service = _compose()["services"]["agent-maintenance"]
    assert service["profiles"] == ["maintenance"]
    assert "ports" not in service
    assert service["entrypoint"][-1] == "deployment-backup"
    assert service["volumes"][0]["target"] == "/data"
