# -*- coding: utf-8 -*-
"""Tests for per-request data-source runtime context."""
from __future__ import annotations

from plugin_datapaw.core.data_sources.models import DataSourceRecord
from plugin_datapaw.core.data_sources.runtime_context import (
    DataSourceRuntimeContext,
    format_data_source_prompt,
    resolve_data_source_context,
)
from plugin_datapaw.core.data_sources.store import DataSourceNotFoundError


MYSQL_CONFIG = {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "root",
    "password": "secret12345",
    "db": "demo",
}

ODPS_CONFIG = {
    "endpoint": "https://service.odps.aliyun.com/api",
    "project_name": "demo_project",
    "app_name": "datapaw",
    "access_id": "access-id",
    "access_key": "access-secret",
}


class FakeStore:
    def __init__(self, records):
        self.records = {record.id: record for record in records}

    def get(self, record_id: str, *, masked: bool = True):
        if record_id not in self.records:
            raise DataSourceNotFoundError(record_id)
        return self.records[record_id]


def _record(record_id: str, ds_type: str, name: str, config: dict):
    return DataSourceRecord(
        id=record_id,
        type=ds_type,
        name=name,
        config=config,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


def test_resolve_context_returns_safe_mysql_fields():
    store = FakeStore(
        [
            _record(
                "mysql-1",
                "mysql",
                "用户库",
                dict(MYSQL_CONFIG),
            ),
        ],
    )

    context = resolve_data_source_context(
        {"datasource_id": "mysql-1"},
        store=store,
    )

    assert context == DataSourceRuntimeContext(
        id="mysql-1",
        name="用户库",
        type="mysql",
        sql_dialect="mysql",
    )
    prompt = format_data_source_prompt(context)
    assert "secret12345" not in prompt
    assert "password" not in prompt
    assert "mysql" in prompt


def test_resolve_context_returns_none_for_missing_id():
    store = FakeStore([])

    assert (
        resolve_data_source_context(
            {"datasource_id": "missing"},
            store=store,
        )
        is None
    )


def test_resolve_context_returns_none_without_selection():
    store = FakeStore([])

    assert resolve_data_source_context({}, store=store) is None
    assert resolve_data_source_context(None, store=store) is None


def test_odps_prompt_mentions_related_skill_lookup():
    store = FakeStore(
        [
            _record(
                "odps-1",
                "odps",
                "ODPS Demo",
                dict(ODPS_CONFIG),
            ),
        ],
    )

    context = resolve_data_source_context(
        {"datasource_id": "odps-1"},
        store=store,
    )
    prompt = format_data_source_prompt(context)

    assert "sql_dialect: `odps`" in prompt
    assert "ODPS / MaxCompute" in prompt
    assert "access-secret" not in prompt
    assert "access_key" not in prompt
