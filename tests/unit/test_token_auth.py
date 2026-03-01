# -*- coding: utf-8 -*-
"""Unit tests for the token authentication system.

Covers: TokenStore (create/verify/revoke/list/persistence),
        scope ranking, middleware dispatch, dependency enforcement.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from copaw.app.auth.models import Actor, TokenScope, scope_rank
from copaw.app.auth.store import TokenStore, _hash_token


# ── helpers ──────────────────────────────────────────────────────────


@pytest.fixture()
def store(tmp_path: Path) -> TokenStore:
    """A fresh TokenStore backed by a temp file."""
    return TokenStore(path=tmp_path / "tokens.json")


# ── scope_rank ───────────────────────────────────────────────────────


class TestScopeRank:
    def test_ordering(self):
        assert scope_rank(TokenScope.VIEWER) < scope_rank(TokenScope.COLLABORATOR)
        assert scope_rank(TokenScope.COLLABORATOR) < scope_rank(TokenScope.OWNER)

    def test_same_scope(self):
        assert scope_rank(TokenScope.OWNER) == scope_rank(TokenScope.OWNER)


# ── TokenStore ───────────────────────────────────────────────────────


class TestTokenStoreCreate:
    def test_create_returns_plaintext(self, store: TokenStore):
        token = store.create(scope=TokenScope.OWNER, label="test")
        assert token.startswith("cpw_")
        assert len(token) > 10

    def test_create_persists_to_file(self, store: TokenStore):
        store.create(scope=TokenScope.VIEWER, label="v1")
        data = json.loads(store._path.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["scope"] == "viewer"
        assert data[0]["label"] == "v1"
        # plaintext must NOT be in the file
        assert "cpw_" not in json.dumps(data)

    def test_hash_stored_not_plaintext(self, store: TokenStore):
        plaintext = store.create(scope=TokenScope.OWNER)
        data = json.loads(store._path.read_text(encoding="utf-8"))
        expected_hash = hashlib.sha256(plaintext.encode()).hexdigest()
        assert data[0]["hash"] == expected_hash

    def test_create_multiple(self, store: TokenStore):
        store.create(scope=TokenScope.OWNER, label="a")
        store.create(scope=TokenScope.COLLABORATOR, label="b")
        store.create(scope=TokenScope.VIEWER, label="c")
        assert len(store.list_tokens()) == 3


class TestTokenStoreVerify:
    def test_verify_valid(self, store: TokenStore):
        plaintext = store.create(scope=TokenScope.COLLABORATOR)
        scope = store.verify(plaintext)
        assert scope == TokenScope.COLLABORATOR

    def test_verify_invalid(self, store: TokenStore):
        store.create(scope=TokenScope.OWNER)
        assert store.verify("cpw_invalid_token") is None

    def test_verify_empty_store(self, store: TokenStore):
        assert store.verify("cpw_anything") is None

    def test_get_record_by_token(self, store: TokenStore):
        plaintext = store.create(scope=TokenScope.VIEWER, label="rec")
        record = store.get_record_by_token(plaintext)
        assert record is not None
        assert record.scope == TokenScope.VIEWER
        assert record.label == "rec"

    def test_get_record_by_token_invalid(self, store: TokenStore):
        assert store.get_record_by_token("cpw_nope") is None


class TestTokenStoreRevoke:
    def test_revoke_existing(self, store: TokenStore):
        plaintext = store.create(scope=TokenScope.OWNER, label="del")
        record = store.get_record_by_token(plaintext)
        assert store.revoke(record.id) is True
        assert store.verify(plaintext) is None
        assert len(store.list_tokens()) == 0

    def test_revoke_nonexistent(self, store: TokenStore):
        assert store.revoke("no_such_id") is False

    def test_revoke_preserves_others(self, store: TokenStore):
        t1 = store.create(scope=TokenScope.OWNER, label="keep")
        t2 = store.create(scope=TokenScope.VIEWER, label="drop")
        r2 = store.get_record_by_token(t2)
        store.revoke(r2.id)
        assert store.verify(t1) == TokenScope.OWNER
        assert store.verify(t2) is None
        assert len(store.list_tokens()) == 1


class TestTokenStoreList:
    def test_list_empty(self, store: TokenStore):
        assert store.list_tokens() == []

    def test_list_returns_copies(self, store: TokenStore):
        store.create(scope=TokenScope.OWNER)
        tokens = store.list_tokens()
        assert len(tokens) == 1
        # modifying the returned list doesn't affect the store
        tokens.clear()
        assert len(store.list_tokens()) == 1


class TestTokenStorePersistence:
    def test_reload_from_file(self, tmp_path: Path):
        path = tmp_path / "tokens.json"
        s1 = TokenStore(path=path)
        plaintext = s1.create(scope=TokenScope.COLLABORATOR, label="persist")

        # Create a new store instance reading the same file
        s2 = TokenStore(path=path)
        assert s2.verify(plaintext) == TokenScope.COLLABORATOR
        assert len(s2.list_tokens()) == 1

    def test_corrupted_file(self, tmp_path: Path):
        path = tmp_path / "tokens.json"
        path.write_text("not json!!!", encoding="utf-8")
        store = TokenStore(path=path)
        # Should gracefully handle corruption
        assert store.list_tokens() == []

    def test_missing_file(self, tmp_path: Path):
        path = tmp_path / "nonexistent" / "tokens.json"
        store = TokenStore(path=path)
        assert store.list_tokens() == []


# ── hash function ────────────────────────────────────────────────────


class TestHashToken:
    def test_deterministic(self):
        assert _hash_token("hello") == _hash_token("hello")

    def test_different_inputs(self):
        assert _hash_token("a") != _hash_token("b")

    def test_sha256(self):
        expected = hashlib.sha256(b"test").hexdigest()
        assert _hash_token("test") == expected


# ── Middleware ────────────────────────────────────────────────────────


class TestMiddleware:
    """Test TokenAuthMiddleware dispatch logic without full ASGI stack."""

    @pytest.fixture()
    def store_with_token(self, tmp_path: Path):
        store = TokenStore(path=tmp_path / "tokens.json")
        plaintext = store.create(scope=TokenScope.COLLABORATOR, label="mw")
        return store, plaintext

    def _make_request(self, path: str, auth_header: str = "") -> MagicMock:
        req = MagicMock()
        req.url.path = path
        headers = MagicMock()
        headers.get = MagicMock(
            side_effect=lambda key, default="": (
                auth_header if key == "authorization" else default
            ),
        )
        req.headers = headers
        req.state = SimpleNamespace()
        return req

    @pytest.mark.asyncio
    async def test_disabled_gives_anonymous_owner(self, store_with_token):
        from copaw.app.auth.middleware import TokenAuthMiddleware

        store, _token = store_with_token
        mw = TokenAuthMiddleware(app=MagicMock(), token_store=store, enabled=False)
        req = self._make_request("/api/something")
        called = []

        async def call_next(r):
            called.append(r)
            return MagicMock(status_code=200)

        await mw.dispatch(req, call_next)
        assert len(called) == 1
        assert req.state.actor.is_anonymous is True
        assert req.state.actor.scope == TokenScope.OWNER

    @pytest.mark.asyncio
    async def test_public_path_skips_auth(self, store_with_token):
        from copaw.app.auth.middleware import TokenAuthMiddleware

        store, _token = store_with_token
        mw = TokenAuthMiddleware(app=MagicMock(), token_store=store, enabled=True)
        req = self._make_request("/api/version")
        called = []

        async def call_next(r):
            called.append(r)
            return MagicMock(status_code=200)

        await mw.dispatch(req, call_next)
        assert len(called) == 1
        assert req.state.actor.is_anonymous is True

    @pytest.mark.asyncio
    async def test_missing_auth_header_returns_401(self, store_with_token):
        from copaw.app.auth.middleware import TokenAuthMiddleware

        store, _token = store_with_token
        mw = TokenAuthMiddleware(app=MagicMock(), token_store=store, enabled=True)
        req = self._make_request("/api/private")
        resp = await mw.dispatch(req, AsyncMock())
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_token_returns_401(self, store_with_token):
        from copaw.app.auth.middleware import TokenAuthMiddleware

        store, _token = store_with_token
        mw = TokenAuthMiddleware(app=MagicMock(), token_store=store, enabled=True)
        req = self._make_request("/api/private", "Bearer cpw_bad_token")
        resp = await mw.dispatch(req, AsyncMock())
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_valid_token_sets_actor(self, store_with_token):
        from copaw.app.auth.middleware import TokenAuthMiddleware

        store, token = store_with_token
        mw = TokenAuthMiddleware(app=MagicMock(), token_store=store, enabled=True)
        req = self._make_request("/api/private", f"Bearer {token}")
        called = []

        async def call_next(r):
            called.append(r)
            return MagicMock(status_code=200)

        await mw.dispatch(req, call_next)
        assert len(called) == 1
        assert req.state.actor.scope == TokenScope.COLLABORATOR
        assert req.state.actor.is_anonymous is False
        assert req.state.actor.token_id is not None

    @pytest.mark.asyncio
    async def test_assets_path_is_public(self, store_with_token):
        from copaw.app.auth.middleware import TokenAuthMiddleware

        store, _token = store_with_token
        mw = TokenAuthMiddleware(app=MagicMock(), token_store=store, enabled=True)
        req = self._make_request("/assets/js/app.js")
        called = []

        async def call_next(r):
            called.append(r)
            return MagicMock(status_code=200)

        await mw.dispatch(req, call_next)
        assert len(called) == 1


# ── Dependencies ─────────────────────────────────────────────────────


class TestRequireScope:
    def _make_request_with_actor(self, scope: TokenScope) -> MagicMock:
        req = MagicMock()
        req.state = SimpleNamespace(actor=Actor(scope=scope))
        return req

    def test_sufficient_scope(self):
        from copaw.app.auth.dependencies import require_scope

        dep = require_scope(TokenScope.VIEWER)
        # Depends wraps _check; extract the inner function
        inner = dep.dependency
        req = self._make_request_with_actor(TokenScope.OWNER)
        actor = inner(req)
        assert actor.scope == TokenScope.OWNER

    def test_exact_scope(self):
        from copaw.app.auth.dependencies import require_scope

        dep = require_scope(TokenScope.COLLABORATOR)
        inner = dep.dependency
        req = self._make_request_with_actor(TokenScope.COLLABORATOR)
        actor = inner(req)
        assert actor.scope == TokenScope.COLLABORATOR

    def test_insufficient_scope_raises_403(self):
        from fastapi import HTTPException

        from copaw.app.auth.dependencies import require_scope

        dep = require_scope(TokenScope.OWNER)
        inner = dep.dependency
        req = self._make_request_with_actor(TokenScope.VIEWER)
        with pytest.raises(HTTPException) as exc_info:
            inner(req)
        assert exc_info.value.status_code == 403

    def test_no_actor_raises_401(self):
        from fastapi import HTTPException

        from copaw.app.auth.dependencies import require_scope

        dep = require_scope(TokenScope.VIEWER)
        inner = dep.dependency
        req = MagicMock()
        req.state = SimpleNamespace()  # no actor
        with pytest.raises(HTTPException) as exc_info:
            inner(req)
        assert exc_info.value.status_code == 401
