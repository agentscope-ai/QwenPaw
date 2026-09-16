# -*- coding: utf-8 -*-
"""事务级 PostgreSQL 用户上下文测试。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from qwenpaw.persistence.database import set_request_user


@pytest.mark.asyncio
async def test_set_request_user_uses_transaction_local_setting():
    session = SimpleNamespace(execute=AsyncMock())
    user_id = uuid4()

    await set_request_user(session, user_id)

    statement, parameters = session.execute.await_args.args
    assert "set_config" in str(statement)
    assert parameters == {"user_id": str(user_id)}
    assert "true" in str(statement).lower()

