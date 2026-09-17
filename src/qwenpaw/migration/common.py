"""分领域迁移器共用的稳定标识、哈希和数据库边界。"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from ..persistence.database import database_session

MIGRATION_NAMESPACE = UUID("b0ca1388-e7f4-51d2-8100-587dd6dd07d8")
SessionFactory = Callable[[], AsyncIterator[AsyncSession]]
_SCHEMA_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SessionContextFactory(Protocol):
    def __call__(self) -> Any: ...


def validate_schema(schema: str) -> str:
    if not _SCHEMA_PATTERN.fullmatch(schema):
        raise ValueError("invalid_database_schema")
    return schema


def table(schema: str, name: str) -> str:
    validate_schema(schema)
    return f'"{schema}"."{name}"'


def stable_uuid(domain: str, source_id: str) -> UUID:
    try:
        return UUID(source_id)
    except (ValueError, TypeError, AttributeError):
        return uuid5(MIGRATION_NAMESPACE, f"{domain}:{source_id}")


def content_hash(value: Any) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def file_hash(path: Path) -> str:
    if not path.is_file():
        return f"sha256:{hashlib.sha256(b'').hexdigest()}"
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@asynccontextmanager
async def migration_session(
    session_factory: SessionContextFactory | None,
) -> AsyncIterator[AsyncSession]:
    factory = session_factory or database_session
    async with factory() as session:
        yield session
