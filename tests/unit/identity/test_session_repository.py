# -*- coding: utf-8 -*-
"""PostgreSQL 会话 Repository 的用户资料映射契约。"""

from datetime import UTC, datetime
from uuid import uuid4

from qwenpaw.identity.session_repository import (
    PostgresSessionRepository,
    _authenticated_from_row,
)


def test_joined_session_query_includes_user_profile_columns() -> None:
    query = PostgresSessionRepository()._select_joined("TRUE")

    for column in (
        "display_name",
        "email",
        "phone",
        "department",
        "job_title",
        "remark",
        "last_login_at",
    ):
        assert f"u.{column}" in query


def test_authenticated_session_maps_user_profile() -> None:
    now = datetime(2026, 9, 9, tzinfo=UTC)
    row = {
        "session_id": uuid4(),
        "user_id": uuid4(),
        "client_info": {},
        "created_at": now,
        "last_seen_at": now,
        "access_expires_at": now,
        "refresh_expires_at": now,
        "revoked_at": None,
        "id": uuid4(),
        "username": "alice",
        "display_name": "Alice Chen",
        "email": "alice@example.com",
        "phone": "13800000000",
        "department": "研发部",
        "job_title": "平台工程师",
        "remark": "核心平台",
        "platform_role": "member",
        "status": "active",
        "user_created_at": now,
        "user_updated_at": now,
        "last_login_at": now,
    }

    authenticated = _authenticated_from_row(row)

    assert authenticated.user.display_name == "Alice Chen"
    assert authenticated.user.department == "研发部"
    assert authenticated.user.created_at == now
