# -*- coding: utf-8 -*-
"""Per-request data-source context exposed to DataPaw agents."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .models import DataSourceType
from .store import DataSourceNotFoundError, DataSourceStore

logger = logging.getLogger(__name__)

SQL_DIALECT_BY_TYPE: dict[DataSourceType, str] = {
    "mysql": "mysql",
    "postgresql": "postgresql",
    "odps": "odps",
}


@dataclass(frozen=True)
class DataSourceRuntimeContext:
    """Non-sensitive data-source facts safe to expose in prompts."""

    id: str
    name: str
    type: DataSourceType
    sql_dialect: str


def resolve_data_source_context(
    request_context: dict[str, Any] | None,
    *,
    store: DataSourceStore | None = None,
) -> DataSourceRuntimeContext | None:
    """Resolve the selected data source from a request context.

    Secrets and connection config are intentionally ignored.  The agent only
    needs identity, display name, source type, and SQL dialect.
    """
    if not isinstance(request_context, dict):
        return None

    datasource_id = str(request_context.get("datasource_id") or "").strip()
    if not datasource_id:
        return None

    try:
        record = (store or DataSourceStore()).get(
            datasource_id,
            masked=True,
        )
    except DataSourceNotFoundError:
        logger.info("Selected data source not found: %s", datasource_id)
        return None
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "Failed to resolve selected data source: %s",
            datasource_id,
            exc_info=True,
        )
        return None

    return DataSourceRuntimeContext(
        id=record.id,
        name=record.name,
        type=record.type,
        sql_dialect=SQL_DIALECT_BY_TYPE[record.type],
    )


def format_data_source_prompt(
    context: DataSourceRuntimeContext | None,
) -> str:
    """Format the current data-source context as a system-prompt section."""
    if context is None:
        return (
            "<datapaw-selected-data-source>\n"
            "当前请求未解析到已选择的数据源。需要查询数据库 / 数仓时，"
            "先让用户选择数据源；不要沿用上一轮或其它请求的数据源。\n"
            "</datapaw-selected-data-source>"
        )

    lines = [
        "<datapaw-selected-data-source>",
        "当前请求已选择数据源：",
        f"- datasource_id: `{context.id}`",
        f"- name: `{context.name}`",
        f"- type: `{context.type}`",
        f"- sql_dialect: `{context.sql_dialect}`",
        "- 生成 SQL 时必须使用当前请求的数据源方言；不要用业务域或历史上下文覆盖该方言。",
    ]
    if context.type == "odps":
        lines.append(
            "- 当前是 ODPS 数据源。取数时需要同时调用 `query-odps` 与 `fetch-data` 两个 SKILL："
            "`query-odps` 为写 ODPS SQL / 执行查询必须遵守的规范，`fetch-data` 为取数必备流程。"
        )
    lines.append("</datapaw-selected-data-source>")
    return "\n".join(lines)
