# -*- coding: utf-8 -*-
"""App sessions support manifest IDs and explicit registered prefixes."""

import pytest
from fastapi import Request, Response

from qwenpaw.hub.auth import HubAuthService
from qwenpaw.hub.credentials import TenantCredentialVault
from qwenpaw.hub.pawapp_access import issue_session, read_session, cookie_name
from tests.unit.hub.factories import runtime_record


@pytest.mark.parametrize("app_id", ["my_app", "My.App", "应用"])
def test_session_uses_registered_prefix_and_safe_cookie(tmp_path, app_id):
    database = tmp_path / "hub.db"
    auth = HubAuthService(
        database,
        TenantCredentialVault(
            database,
            tmp_path / "key",
        ),
    )
    user, _ = auth.register("owner", "safe-password")
    record = runtime_record(tmp_path, owner_user_id=user.user_id)
    response = Response()
    issue_session(
        auth,
        user,
        record,
        app_id,
        response,
        secure=False,
        prefixes=["app-api"],
    )
    cookie = response.headers["set-cookie"].split(";", 1)[0]
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/app-api/file",
            "headers": [(b"cookie", cookie.encode())],
        },
    )
    assert read_session(auth, request, "app-api/file") is not None
    assert read_session(auth, request, "app-api-other/file") is None
    assert read_session(auth, request, "agents/memory/backends") is None
    assert read_session(auth, request, "app-api/../agents") is None
    assert read_session(auth, request, "app-api/%2e%2e/agents") is None
    assert len(cookie_name(app_id)) < 100
    token = cookie.split("=", 1)[1]
    assert auth.verify_token(token) is None
    request.scope["method"] = "POST"
    assert read_session(auth, request, "app-api/file") is None
