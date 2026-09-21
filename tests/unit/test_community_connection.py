# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Local PKCE, lifecycle races and read-only community polling contracts."""

import asyncio
import json
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from qwenpaw.app import community_connection as module
from qwenpaw.app import community_store as store


@pytest.fixture(autouse=True)
def private_state(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(store, "_LOCK", asyncio.Lock())


def service(handler, *, enabled=True):
    return module.CommunityConnectionService(
        module.ConnectionConfig(
            "test-approved-client",
            "test:messages",
            enabled,
        ),
        transport=httpx.MockTransport(handler),
    )


async def seed_connection(**changes):
    connection = {
        "account_id": "account-a",
        "display_name": "Alice",
        "connection_id": "connection-a",
        "access_token": "access-secret",
        "refresh_token": "refresh-secret",
        "expires_at": time.time() + 3600,
        "sync_enabled": True,
        **changes,
    }
    await store.save_connection(connection)
    return connection


def token_reply():
    return httpx.Response(
        200,
        json={
            "access_token": "new-access-secret",
            "refresh_token": "new-refresh-secret",
            "token_type": "Bearer",
            "expires_in": 3600,
        },
    )


@pytest.mark.asyncio
async def test_unconfigured_and_remote_do_not_start_authorization():
    unconfigured = module.CommunityConnectionService(module.ConnectionConfig())
    assert (await unconfigured.status(local=True))[
        "status"
    ] == "not_configured"
    with pytest.raises(
        module.CommunityConnectionError,
        match="not_configured",
    ):
        await unconfigured.start(local=True)
    configured = service(lambda request: httpx.Response(500))
    with pytest.raises(
        module.CommunityConnectionError,
        match="unsupported_remote",
    ):
        await configured.start(local=False)
    await seed_connection()
    status = await configured.status(local=False)
    assert status["status"] == "connected"
    assert status["local_login_supported"] is False
    assert status["supported_notifications"] == [
        "replies",
        "mentions",
        "resource_comments",
        "resource_questions",
        "interactions",
        "feedback",
        "notifications",
    ]
    assert "access-secret" not in json.dumps(status)
    assert "refresh-secret" not in json.dumps(status)


@pytest.mark.asyncio
async def test_actual_loopback_callback_checks_state_and_consumes_code_once():
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/api/cli/v1/oauth/token":
            body = json.loads(request.content)
            assert body["client_id"] == "test-approved-client"
            assert body["grant_type"] == "authorization_code"
            assert len(body["code_verifier"]) >= 43
            return token_reply()
        if request.url.path == "/api/cli/v1/auth/refresh":
            return token_reply()
        assert request.url.path == "/api/cli/v1/me"
        return httpx.Response(
            200,
            json={"user": {"id": "account-a", "display_name": "Alice"}},
        )

    connection_service = service(handler)
    try:
        auth = await connection_service.start(local=True)
        query = parse_qs(urlsplit(auth["authorize_url"]).query)
        assert query["code_challenge_method"] == ["S256"]
        assert query["source"] == ["qwenpaw-community"]
        callback = query["redirect_uri"][0]
        path = urlsplit(callback).path
        with pytest.raises(
            module.CommunityConnectionError,
            match="invalid_state",
        ):
            await connection_service.complete(
                path,
                {"state": ["wrong"], "code": ["code"]},
            )
        assert not requests
        async with httpx.AsyncClient(trust_env=False) as client:
            response = await client.get(
                callback,
                params={"state": query["state"][0], "code": "code"},
            )
        assert response.status_code == 200
        assert (
            await connection_service.authorization_status(auth["flow_id"])
        )["status"] == "completed"
        assert (await store.get_connection())["account_id"] == "account-a"
        with pytest.raises(
            module.CommunityConnectionError,
            match="authorization_expired",
        ):
            await connection_service.complete(
                path,
                {"state": query["state"], "code": ["code"]},
            )
        assert len(requests) == 3
    finally:
        await connection_service.close()


@pytest.mark.asyncio
async def test_cancelling_during_token_exchange_cannot_reconnect():
    entered, release = asyncio.Event(), asyncio.Event()

    async def handler(request):
        if request.url.path.endswith("/oauth/token"):
            entered.set()
            await release.wait()
            return token_reply()
        if request.url.path.endswith("/auth/refresh"):
            return token_reply()
        return httpx.Response(200, json={"user": {"id": "account-a"}})

    connection_service = service(handler)
    try:
        auth = await connection_service.start(local=True)
        query = parse_qs(urlsplit(auth["authorize_url"]).query)
        completion = asyncio.create_task(
            connection_service.complete(
                urlsplit(query["redirect_uri"][0]).path,
                {"state": query["state"], "code": ["code"]},
            ),
        )
        await entered.wait()
        await connection_service.cancel(auth["flow_id"])
        release.set()
        with pytest.raises(
            module.CommunityConnectionError,
            match="authorization_cancelled",
        ):
            await completion
        assert await store.get_connection() is None
    finally:
        release.set()
        await connection_service.close()


@pytest.mark.asyncio
async def test_refresh_uses_official_endpoint_and_preserves_connection_id():
    old = await seed_connection(expires_at=time.time() - 1)
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/auth/refresh"):
            assert json.loads(request.content) == {
                "refresh_token": "refresh-secret",
            }
            return token_reply()
        return httpx.Response(200, json={"user": {"id": "account-a"}})

    connection_service = service(handler)
    refreshed = await connection_service._fresh_connection()
    assert paths == ["/api/cli/v1/auth/refresh", "/api/cli/v1/me"]
    assert refreshed["connection_id"] == old["connection_id"]
    assert (await store.get_connection())[
        "access_token"
    ] == "new-access-secret"


@pytest.mark.asyncio
async def test_disconnect_during_refresh_rejects_stale_credentials():
    await seed_connection(expires_at=time.time() - 1)
    entered, release = asyncio.Event(), asyncio.Event()

    async def handler(request):
        if request.url.path.endswith("/auth/refresh"):
            entered.set()
            await release.wait()
            return token_reply()
        return httpx.Response(200, json={"user": {"id": "account-a"}})

    connection_service = service(handler)
    refresh = asyncio.create_task(connection_service._fresh_connection())
    await entered.wait()
    await connection_service.disconnect()
    release.set()
    with pytest.raises(
        module.CommunityConnectionError,
        match="connection_changed",
    ):
        await refresh
    assert await store.get_connection() is None


@pytest.mark.asyncio
async def test_readonly_sync_deduplicates_and_preserves_read_state():
    await seed_connection()
    round_number = 0
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET"
        assert request.url.params["mark_read"] == "false"
        if request.url.path.endswith("comment-replies"):
            items = [
                {
                    "reply_id": "r1",
                    "resource_name": "Report",
                    "reply_content": "Fixed",
                    "resource_link": "/community/report",
                    "has_unread": True,
                },
            ]
        else:
            items = [
                {
                    "mention_id": "m1",
                    "event_type": "comment_on_my_resource",
                    "source_title": "First",
                    "source_link": "https://evil.test",
                },
            ]
            if round_number:
                items.insert(
                    0,
                    {
                        "mention_id": "m2",
                        "source_title": "New",
                        "source_link": "/community/new",
                    },
                )
        return httpx.Response(
            200,
            json={"data": {"items": items, "total": len(items)}},
        )

    connection_service = service(handler)
    assert (await connection_service.sync_once())["inserted"] == 2
    first = {event["remote_id"]: event for event in await store.list_events()}
    assert first["mentions:m1"]["read"] is True
    assert first["mentions:m1"]["event_type"] == "mention"
    assert first["mentions:m1"]["payload"]["discussion_url"] is None
    assert first["comments:r1"]["read"] is False
    assert first["comments:r1"]["event_type"] == "reply"
    await store.mark_read([first["comments:r1"]["id"]])
    round_number = 1
    assert (await connection_service.sync_once())["inserted"] == 1
    latest = {event["remote_id"]: event for event in await store.list_events()}
    assert latest["comments:r1"]["read"] is True
    assert latest["mentions:m2"]["read"] is False
    assert latest["mentions:m2"]["event_type"] == "mention"
    assert latest["mentions:m2"]["payload"]["discussion_url"].startswith(
        module.PLATFORM,
    )
    assert len(calls) == 10


@pytest.mark.asyncio
@pytest.mark.parametrize("resource_type", ["skill", "plugin"])
async def test_resource_feedback_sync_preserves_reply_id_and_local_read_state(
    resource_type,
):
    await seed_connection()
    calls = []
    resource_id = f"{resource_type}-123"
    resource_link = f"/{resource_type}s/{resource_id}"
    item = {
        "reply_id": "resource-reply-1",
        "event_type": "comment_on_my_resource",
        "resource_type": resource_type,
        "resource_id": resource_id,
        "resource_name": "Maintained resource",
        "resource_link": resource_link,
        "reply_content": "This resource fails to load",
        "replier_display_name": "Bob",
        "has_unread": True,
    }

    def handler(request):
        calls.append(request)
        assert request.method == "GET"
        assert request.url.params["mark_read"] == "false"
        items = []
        if request.url.path.endswith("comment-replies"):
            # An older reply-shaped copy shares the original remote ID.
            items = [item, {**item, "event_type": "reply"}]
        return httpx.Response(
            200,
            json={"data": {"items": items, "total": len(items)}},
        )

    connection_service = service(handler)
    assert (await connection_service.sync_once())["inserted"] == 1
    events = await store.list_events()
    assert len(events) == 1
    event = events[0]
    assert event["remote_id"] == "comments:resource-reply-1"
    assert event["source_id"] == "comments:resource-reply-1"
    assert event["event_type"] == "resource_feedback"
    assert event["title"] == "Maintained resource"
    assert event["body"] == "This resource fails to load"
    assert event["payload"]["resource_type"] == resource_type
    assert event["payload"]["resource_id"] == resource_id
    assert event["payload"]["resource_name"] == "Maintained resource"
    assert (
        event["payload"]["discussion_url"] == module.PLATFORM + resource_link
    )
    assert event["payload"]["sender"]["name"] == "Bob"
    assert event["read"] is False
    assert await store.mark_read([event["id"]]) == 1

    assert (await connection_service.sync_once())["inserted"] == 0
    latest = await store.list_events()
    assert len(latest) == 1
    assert latest[0]["id"] == event["id"]
    assert latest[0]["remote_id"] == "comments:resource-reply-1"
    assert latest[0]["event_type"] == "resource_feedback"
    assert latest[0]["read"] is True
    assert len(calls) == 10


@pytest.mark.parametrize(
    "event_type",
    [None, "", "unknown", "comment_on_my_resource ", "COMMENT_ON_MY_RESOURCE"],
)
def test_unknown_or_missing_comment_event_type_remains_reply(event_type):
    item = {"reply_id": "r1"}
    if event_type is not None:
        item["event_type"] = event_type
    event = module.normalize_message("comments", item, initial=False)
    assert event["event_type"] == "reply"
    assert event["remote_id"] == "comments:r1"


@pytest.mark.parametrize(
    "resource_type",
    ["article", "question", None, "unknown"],
)
def test_comments_on_own_posts_are_replies_not_extension_feedback(
    resource_type,
):
    event = module.normalize_message(
        "comments",
        {
            "reply_id": "post-comment-1",
            "event_type": "comment_on_my_resource",
            "resource_type": resource_type,
        },
        initial=False,
    )
    assert event["event_type"] == "reply"
    assert event["remote_id"] == "comments:post-comment-1"


@pytest.mark.parametrize("resource_type", ["plugin", "skill"])
@pytest.mark.parametrize("content_type", ["question", "article"])
def test_platform_resource_mentions_preserve_context(
    resource_type,
    content_type,
):
    event = module.normalize_message(
        "mentions",
        {
            "mention_id": "community:post:resource",
            "event_type": "mention_my_resource",
            "source_type": "community",
            "content_type": content_type,
            "mentioned_resource_type": resource_type,
            "mentioned_resource_id": "resource-1",
            "created_at": "2026-09-08T12:00:00Z",
            "has_unread": True,
        },
        initial=True,
    )
    assert event["event_type"] == (
        "resource_feedback" if content_type == "question" else "mention"
    )
    assert event["remote_id"] == "mentions:community:post:resource"
    assert event["payload"]["resource_id"] == "resource-1"
    assert event["created_at"] == 1788868800
    assert event["read"] is False


@pytest.mark.asyncio
async def test_unauthorized_messages_refresh_once_then_retry():
    await seed_connection(expires_at=None)
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/auth/refresh"):
            return token_reply()
        if request.url.path.endswith("/me"):
            return httpx.Response(200, json={"user": {"id": "account-a"}})
        if request.headers.get("authorization") == "Bearer access-secret":
            return httpx.Response(401, json={"secret": "do-not-return-this"})
        return httpx.Response(200, json={"data": {"items": [], "total": 0}})

    result = await service(handler).sync_once()
    assert result["status"] == "synced"
    assert paths.count("/api/cli/v1/auth/refresh") == 1


@pytest.mark.asyncio
async def test_permission_failure_is_sanitized_and_does_not_mutate_remote():
    await seed_connection()
    connection_service = service(
        lambda request: httpx.Response(
            403,
            json={"detail": "secret-response-body"},
        ),
    )
    with pytest.raises(
        module.CommunityConnectionError,
        match="permission_not_granted",
    ):
        await connection_service.sync_once()
    status = await connection_service.status(local=True)
    assert status["last_error"] == "permission_not_granted"
    assert "secret-response-body" not in json.dumps(status)


@pytest.mark.asyncio
async def test_message_scope_is_separately_opted_in():
    await seed_connection()
    connection_service = service(
        lambda request: pytest.fail("Unexpected network"),
        enabled=False,
    )
    with pytest.raises(
        module.CommunityConnectionError,
        match="messages_not_configured",
    ):
        await connection_service.sync_once()
    assert (await connection_service.status(local=True))[
        "messages_enabled"
    ] is False


@pytest.mark.asyncio
async def test_expired_flow_closes_callback_and_discards_pkce_secret(
    monkeypatch,
):
    monkeypatch.setattr(module, "AUTH_TTL", 0.02)
    connection_service = service(
        lambda request: pytest.fail("Unexpected network"),
    )
    try:
        auth = await connection_service.start(local=True)
        await asyncio.sleep(0.05)
        status = await connection_service.authorization_status(auth["flow_id"])
        assert status["status"] == "expired"
        assert "verifier" not in connection_service._flow
        assert connection_service._server is None
    finally:
        await connection_service.close()


@pytest.mark.asyncio
async def test_pause_during_refresh_is_not_undone_by_token_save():
    await seed_connection(expires_at=time.time() - 1)
    entered, release = asyncio.Event(), asyncio.Event()

    async def handler(request):
        if request.url.path.endswith("/auth/refresh"):
            entered.set()
            await release.wait()
            return token_reply()
        return httpx.Response(200, json={"user": {"id": "account-a"}})

    connection_service = service(handler)
    refresh = asyncio.create_task(connection_service._fresh_connection())
    await entered.wait()
    await connection_service.set_sync(False)
    release.set()
    await refresh
    assert (await store.get_connection())["sync_enabled"] is False


@pytest.mark.asyncio
async def test_bounded_pagination_resumes_before_advancing_checkpoint(
    monkeypatch,
):
    await seed_connection()
    monkeypatch.setattr(module, "PAGE_SIZE", 2)
    monkeypatch.setattr(module, "PAGES_PER_SYNC", 1)
    requested_pages = []

    def handler(request):
        if not request.url.path.endswith("comment-replies"):
            return httpx.Response(
                200,
                json={"data": {"items": [], "total": 0}},
            )
        page = int(request.url.params["page"])
        requested_pages.append(page)
        items = [
            {"reply_id": str(index), "has_unread": True}
            for index in range(4, 0, -1)
        ]
        return httpx.Response(
            200,
            json={
                "data": {
                    "items": items[(page - 1) * 2 : page * 2],
                    "total": 4,
                },
            },
        )

    connection_service = service(handler)
    assert (await connection_service.sync_once())["catching_up"] is True
    cursor = (await store.get_sync_state())["cursor"]["comments"]
    assert cursor["next_page"] == 2
    assert cursor["checkpoint"] is None
    assert (await connection_service.sync_once())["catching_up"] is False
    cursor = (await store.get_sync_state())["cursor"]["comments"]
    assert cursor["checkpoint"] == "comments:4"
    assert len(await store.list_events()) == 4
    assert (await connection_service.sync_once())["inserted"] == 0
    assert requested_pages == [1, 2, 1]


def test_local_authorization_rejects_remote_and_hostile_origins(monkeypatch):
    from starlette.requests import Request
    from qwenpaw.app.routers.community_connection import is_local_request

    monkeypatch.delenv("QWENPAW_RUNTIME_INTERNAL_TOKEN", raising=False)

    def request(host="127.0.0.1", peer="127.0.0.1", origin=None):
        headers = [(b"host", host.encode())]
        if origin:
            headers.append((b"origin", origin.encode()))
        return Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/",
                "scheme": "http",
                "server": (host, 8088),
                "client": (peer, 9999),
                "headers": headers,
            },
        )

    assert is_local_request(request())
    for origin in (
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
    ):
        assert is_local_request(request(origin=origin))
    assert not is_local_request(request(host="public.example"))
    assert not is_local_request(request(peer="192.0.2.1"))
    assert not is_local_request(request(origin="https://evil.example"))
    assert not is_local_request(request(origin="https://[broken"))
    monkeypatch.setenv("QWENPAW_RUNTIME_INTERNAL_TOKEN", "test-hub-runtime")
    assert not is_local_request(request())


def test_default_community_client_and_operator_override(monkeypatch):
    monkeypatch.delenv("QWENPAW_COMMUNITY_CLIENT_ID", raising=False)
    monkeypatch.delenv("QWENPAW_COMMUNITY_SCOPES", raising=False)
    monkeypatch.delenv("QWENPAW_COMMUNITY_MESSAGES_ENABLED", raising=False)
    config = module.ConnectionConfig.from_environment()
    assert config.client_id == "agentscope-platform-cli"
    assert config.scopes == "platform:control"
    assert config.configured is True
    assert config.messages_enabled is True
    monkeypatch.setenv("QWENPAW_COMMUNITY_MESSAGES_ENABLED", "false")
    assert module.ConnectionConfig.from_environment().messages_enabled is False
    monkeypatch.setenv("QWENPAW_COMMUNITY_CLIENT_ID", "")
    assert module.ConnectionConfig.from_environment().configured is False


@pytest.mark.asyncio
@pytest.mark.parametrize("refresh_fails", [False, True])
async def test_platform_cli_finalize_login_refreshes_before_me(refresh_fails):
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/auth/refresh"):
            assert "authorization" not in request.headers
            assert json.loads(request.content) == {
                "refresh_token": "initial-refresh",
            }
            if refresh_fails:
                return httpx.Response(503)
            return token_reply()
        expected = "initial-access" if refresh_fails else "new-access-secret"
        assert request.headers["authorization"] == f"Bearer {expected}"
        return httpx.Response(200, json={"user_id": "account-a"})

    connection = await service(handler)._finalize_login(
        {"access_token": "initial-access", "refresh_token": "initial-refresh"},
    )
    assert paths == ["/api/cli/v1/auth/refresh", "/api/cli/v1/me"]
    assert connection["account_id"] == "account-a"
    assert connection["refresh_token"] == (
        "initial-refresh" if refresh_fails else "new-refresh-secret"
    )


@pytest.mark.asyncio
async def test_platform_cli_finalize_login_without_refresh_token():
    paths = []

    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200, json={"user_id": "account-a"})

    connection = await service(handler)._finalize_login(
        {"access_token": "initial-access"},
    )
    assert paths == ["/api/cli/v1/me"]
    assert connection["account_id"] == "account-a"


@pytest.mark.parametrize(
    "kind,item,event_type",
    [
        (
            "interactions",
            {
                "interaction_id": "i1",
                "action_type_label": "点赞了你的",
                "target_title": "Post",
                "target_link": (
                    "https://platform.agentscope.io/community/articles/p1"
                ),
                "has_unread": True,
            },
            "interaction",
        ),
        (
            "feedback",
            {
                "id": "f1",
                "description_preview": "Help",
                "last_comment_preview": "Fixed",
                "last_comment_at": "2026-09-09T10:00:00",
                "has_unread": True,
            },
            "platform_feedback",
        ),
        (
            "notifications",
            {
                "notification_id": "n1",
                "title": "Notice",
                "content": "Update",
                "link_url": "javascript:alert(1)",
                "has_unread": False,
            },
            "notification",
        ),
    ],
)
def test_all_platform_tabs_normalize(kind, item, event_type):
    event = module.normalize_message(kind, item, initial=True)
    assert event["event_type"] == event_type
    assert event["read"] is not item["has_unread"]
    assert event["remote_id"].startswith(kind + ":")
    if kind == "notifications":
        assert event["payload"]["discussion_url"] is None


def test_later_feedback_reply_is_a_new_event():
    first = {"id": "ticket", "last_comment_at": "2026-09-09T10:00:00"}
    second = {**first, "last_comment_at": "2026-09-09T11:00:00"}
    assert (
        module.normalize_message("feedback", first, initial=True)["remote_id"]
        != module.normalize_message("feedback", second, initial=False)[
            "remote_id"
        ]
    )


@pytest.mark.asyncio
async def test_community_comment_uses_connected_account_without_retry():
    await seed_connection()
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["authorization"] == "Bearer access-secret"
        assert json.loads(request.content)["content"] == "A comment"
        return httpx.Response(200, json={"data": {"id": "comment"}})

    connection_service = service(handler)
    with pytest.raises(
        module.CommunityConnectionError,
        match="connection_changed",
    ):
        await connection_service.community_request(
            "POST",
            "/api/v1/community/articles/post/comments",
            account_id="other",
            json={"content": "A comment"},
        )
    assert not calls
    assert await connection_service.community_request(
        "POST",
        "/api/v1/community/articles/post/comments",
        account_id="account-a",
        json={"content": "A comment"},
    ) == {"id": "comment"}
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_public_community_read_needs_no_connection():
    def handler(request):
        assert "authorization" not in request.headers
        return httpx.Response(200, json={"data": {"items": [], "total": 0}})

    assert (
        await service(handler).community_request(
            "GET",
            "/api/v1/community/articles",
        )
    )["total"] == 0


@pytest.mark.asyncio
async def test_selected_message_types_persist_and_limit_requests():
    await seed_connection()
    paths = []

    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200, json={"data": {"items": [], "total": 0}})

    connection_service = service(handler)
    await connection_service.set_sync(message_types=["comments", "feedback"])
    assert (await connection_service.status(local=True))["message_types"] == [
        "comments",
        "feedback",
    ]
    await connection_service.sync_once()
    assert paths == [
        "/api/v1/messages/comment-replies",
        "/api/v1/messages/feedback",
    ]
    await connection_service.set_sync(message_types=[])
    paths.clear()
    await connection_service.sync_once()
    assert not paths
    assert (await store.get_connection())["message_types"] == []


@pytest.mark.asyncio
async def test_disabled_type_rejects_late_events_and_cursor():
    connection = await seed_connection(message_types=["comments"])
    inserted = await store.ingest(
        connection["account_id"],
        [{"remote_id": "mentions:late", "title": "Late event"}],
        {"mentions": {"checkpoint": "mentions:late"}},
        connection_id=connection["connection_id"],
    )
    assert inserted == 0
    assert not await store.list_events()
    assert "mentions" not in (await store.get_sync_state())["cursor"]


@pytest.mark.asyncio
async def test_network_failure_preserves_connected_account_and_messages():
    await seed_connection()

    def offline(request):
        raise httpx.ConnectError("private-network-details", request=request)

    connection_service = service(offline)
    with pytest.raises(
        module.CommunityConnectionError,
        match="network_unavailable",
    ):
        await connection_service.sync_once()
    status = await connection_service.status(local=True)
    assert status["status"] == "connected"
    assert status["messages_enabled"] is True
    assert status["last_error"] == "network_unavailable"
    assert "private-network-details" not in json.dumps(status)
