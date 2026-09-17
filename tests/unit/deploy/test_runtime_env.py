# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

from deploy.runtime_env import (
    ProductionSettings,
    build_database_url,
    build_internal_environment,
    validate_environment,
)


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "deploy" / "runtime_env.py"


def _environment(**overrides: str) -> dict[str, str]:
    values = {
        "WELDON_DB_NAME": "weldonagent",
        "WELDON_DB_SCHEMA": "weldonagent",
        "WELDON_DB_USER": "weldon",
        "WELDON_DB_PASSWORD": "correct-horse-battery-staple",
    }
    values.update(overrides)
    return values


def test_database_url_percent_encodes_password():
    settings = ProductionSettings(
        db_name="weldonagent",
        db_schema="weldonagent",
        db_user="weldon",
        db_password="a/b:c@d% password",
    )
    assert build_database_url(settings) == (
        "postgresql://weldon:a%2Fb%3Ac%40d%25%20password"
        "@agent-pg:5432/weldonagent"
    )


@pytest.mark.parametrize(
    "password",
    ["", "REPLACE_WITH_RANDOM_PASSWORD", "short", "bad\npassword-value"],
)
def test_insecure_password_is_rejected(password: str):
    with pytest.raises(ValueError, match="WELDON_DB_PASSWORD"):
        validate_environment(_environment(WELDON_DB_PASSWORD=password))


@pytest.mark.parametrize("name", ["bad-name", "two words", "schema.name", "1name"])
def test_invalid_schema_identifier_is_rejected(name: str):
    with pytest.raises(ValueError, match="WELDON_DB_SCHEMA"):
        validate_environment(_environment(WELDON_DB_SCHEMA=name))


def test_internal_environment_preserves_existing_runtime_contract():
    result = build_internal_environment(_environment())
    assert result["QWENPAW_MULTI_USER_ENABLED"] == "true"
    assert result["QWENPAW_STORAGE_MODE"] == "postgres"
    assert result["QWENPAW_DATABASE_SCHEMA"] == "weldonagent"
    assert result["QWENPAW_WORKING_DIR"] == "/data/working"
    assert result["QWENPAW_CUTOVER_POSTGRES_WRITES_DOMAINS"] == "all"


def test_check_output_never_contains_password_or_database_url():
    env = dict(os.environ)
    env.update(_environment())
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "check"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 0
    assert env["WELDON_DB_PASSWORD"] not in combined
    assert "postgresql://" not in combined
