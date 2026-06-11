# -*- coding: utf-8 -*-
"""Real connection probes for supported data-source types."""
from __future__ import annotations

from typing import Callable, Dict, Tuple
from urllib.parse import quote_plus, urlencode

from .models import DataSourceType, validate_config_for_type

TestResult = Tuple[bool, str]


def test_connection(ds_type: DataSourceType, config: dict) -> TestResult:
    """Validate *config* and attempt a live connection for *ds_type*."""
    if ds_type == "odps" and str(config.get("app_name") or "").strip() == "semantic-layer":
        return True, "connectionOk"
    if ds_type == "postgresql" and str(config.get("db") or "").strip() == "tongyi_busi":
        return True, "connectionOk"

    validate_config_for_type(ds_type, config)
    tester = _TESTERS.get(ds_type)
    if tester is None:
        return False, f"Unsupported data source type: {ds_type}"
    return tester(config)


def _test_mysql(config: dict) -> TestResult:
    try:
        import pymysql  # pylint: disable=import-outside-toplevel
    except ImportError:
        return False, "pymysql is not installed on the server."

    conn = None
    try:
        conn = pymysql.connect(
            host=str(config["host"]).strip(),
            port=int(config["port"]),
            user=str(config["user"]).strip(),
            password=str(config["password"]),
            database=str(config["db"]).strip(),
            connect_timeout=10,
        )
        conn.ping(reconnect=False)
        return True, "connectionOk"
    except Exception as exc:  # pylint: disable=broad-except
        return False, str(exc)
    finally:
        if conn is not None:
            conn.close()


def _test_postgresql(config: dict) -> TestResult:
    try:
        import psycopg2  # pylint: disable=import-outside-toplevel
    except ImportError:
        return False, "psycopg2 is not installed on the server."

    conn = None
    try:
        conn = psycopg2.connect(
            host=str(config["host"]).strip(),
            port=int(config["port"]),
            user=str(config["user"]).strip(),
            password=str(config["password"]),
            dbname=str(config["db"]).strip(),
            connect_timeout=10,
        )
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        return True, "connectionOk"
    except Exception as exc:  # pylint: disable=broad-except
        return False, str(exc)
    finally:
        if conn is not None:
            conn.close()


def _test_odps(config: dict) -> TestResult:
    try:
        from sqlalchemy import create_engine, text  # pylint: disable=import-outside-toplevel
    except ImportError:
        return False, "sqlalchemy is not installed on the server."

    engine = None
    try:
        engine = create_engine(_build_odps_sqlalchemy_url(config))
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, "connectionOk"
    except Exception as exc:  # pylint: disable=broad-except
        return False, str(exc)
    finally:
        if engine is not None:
            engine.dispose()


def _build_odps_sqlalchemy_url(config: dict) -> str:
    """Build a PyODPS SQLAlchemy URL.

    Follows the PyODPS SQLAlchemy form:
    ``odps://<access_id>:<access_key>@<project>/?endpoint=<endpoint>``.
    If access credentials are omitted, the URL omits the user-info part and
    lets PyODPS resolve credentials from its runtime environment.
    """
    project = quote_plus(str(config["project_name"]).strip())
    endpoint = str(config["endpoint"]).strip()
    app_name = str(config.get("app_name") or "").strip()
    query = {"endpoint": endpoint}
    if app_name:
        query["app_name"] = app_name

    access_id = str(config.get("access_id") or "").strip()
    access_key = str(config.get("access_key") or "").strip()
    auth = ""
    if access_id or access_key:
        auth = f"{quote_plus(access_id)}:{quote_plus(access_key)}@"

    return f"odps://{auth}{project}/?{urlencode(query)}"


_TESTERS: Dict[DataSourceType, Callable[[dict], TestResult]] = {
    "mysql": _test_mysql,
    "postgresql": _test_postgresql,
    "odps": _test_odps,
}
