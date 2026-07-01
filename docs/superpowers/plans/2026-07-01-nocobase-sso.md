# QwenPaw × NocoBase SSO 身份接入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 QwenPaw 对话接口接受"NocoBase 用户 token"作为逐请求身份来源,校验后写入 `request.state.user`,复用现有 ACL 门禁做按角色的频道准入。

**Architecture:** 在核心 auth 中间件开一个可插拔的"外部身份解析器"扩展点(仿现有 `_external_acl_checkers`);`nocobase_auth` 插件注册一个解析器:读 `X-NocoBase-Token` 头 → 调 NocoBase `auth:check` 校验(短 TTL 缓存)→ 取 email 作为 `sender_id`。ACL 门禁与判定逻辑零改动。

**Tech Stack:** Python 3.10–3.13、FastAPI/Starlette 中间件、httpx(`trust_env=False`)、pytest(`asyncio_mode=auto`)、pytest_httpx、black `--line-length=79`。

**设计依据:** `docs/superpowers/specs/2026-07-01-nocobase-sso-design.md`

---

## 文件结构

**核心(仓库)**
- Modify `src/qwenpaw/app/auth.py` — 新增身份解析器注册表 + helper;`AuthMiddleware.dispatch` 回退;`_should_skip_auth` 一处判断。
- Test `tests/unit/app/test_auth_identity_resolver.py` — 新建。

**插件 `plugins/bundle/nocobase_auth/`**
- Create `identity_cache.py` — 短 TTL token→身份 缓存。
- Create `identity_resolver.py` — 解析器工厂。
- Modify `nocobase_client.py` — 新增 `verify_user_token`。
- Modify `sync_engine.py` — 新增薄委托 `verify_user_token`。
- Modify `plugin.py` — 装配缓存+解析器,生命周期注册/注销。
- Test `tests/unit/plugins/test_nocobase_identity_cache.py` — 新建。
- Test `tests/unit/plugins/test_nocobase_identity_resolver.py` — 新建。
- Test `tests/unit/plugins/test_nocobase_client.py` — 追加 `verify_user_token` 用例。

**契约测试**
- Test `tests/unit/channels/test_console_sso_gate.py` — 新建:身份解析器 + console 门禁串起来验。

**文档**
- Modify `website/public/docs/` — SSO 接入 + header 契约 + 配置说明。

---

## Task 1: 核心 auth —— 外部身份解析器注册表 + helper

**Files:**
- Modify: `src/qwenpaw/app/auth.py`
- Test: `tests/unit/app/test_auth_identity_resolver.py`

- [ ] **Step 1: 写失败测试**

新建 `tests/unit/app/test_auth_identity_resolver.py`:

```python
# -*- coding: utf-8 -*-
"""Unit tests for the external identity resolver registry in auth.py."""
from __future__ import annotations

import pytest

from qwenpaw.app import auth as auth_mod
from qwenpaw.app.auth import (
    _external_identity_resolvers,
    _resolve_external_identity,
    has_external_identity_resolvers,
    register_external_identity_resolver,
    unregister_external_identity_resolver,
)


@pytest.fixture(autouse=True)
def _clear_resolvers():
    _external_identity_resolvers.clear()
    yield
    _external_identity_resolvers.clear()


def test_register_and_has():
    assert has_external_identity_resolvers() is False

    async def r(_request):
        return None

    register_external_identity_resolver(r)
    assert has_external_identity_resolvers() is True
    unregister_external_identity_resolver(r)
    assert has_external_identity_resolvers() is False


async def test_resolve_returns_first_non_none():
    async def r_none(_request):
        return None

    async def r_alice(_request):
        return "alice@example.com"

    register_external_identity_resolver(r_none)
    register_external_identity_resolver(r_alice)
    assert await _resolve_external_identity(object()) == "alice@example.com"


async def test_resolve_swallows_exceptions_and_continues():
    async def r_boom(_request):
        raise RuntimeError("boom")

    async def r_ok(_request):
        return "bob@example.com"

    register_external_identity_resolver(r_boom)
    register_external_identity_resolver(r_ok)
    assert await _resolve_external_identity(object()) == "bob@example.com"


async def test_resolve_all_none():
    async def r(_request):
        return None

    register_external_identity_resolver(r)
    assert await _resolve_external_identity(object()) is None
```

- [ ] **Step 2: 运行,确认失败**

Run: `pytest tests/unit/app/test_auth_identity_resolver.py -v`
Expected: FAIL(`ImportError: cannot import name '_external_identity_resolvers'`)

- [ ] **Step 3: 实现最小代码**

在 `src/qwenpaw/app/auth.py` 顶部 import 区补充(若缺):

```python
from typing import Awaitable, Callable, List, Optional
```

在模块级(`AuthMiddleware` 类定义之前、`_PUBLIC_PATHS` 附近)加入:

```python
# ---------------------------------------------------------------------------
# External identity resolvers (e.g. NocoBase SSO plugin)
# ---------------------------------------------------------------------------
# A resolver maps an incoming request to an identity string (the sender_id
# used by channel ACL) or None when it has no opinion. Mirrors the
# BaseChannel._external_acl_checkers pattern: the core stays ignorant of any
# specific identity provider; plugins fill this in.
IdentityResolver = Callable[["Request"], Awaitable[Optional[str]]]
_external_identity_resolvers: List[IdentityResolver] = []


def register_external_identity_resolver(resolver: IdentityResolver) -> None:
    """Register a resolver consulted when no valid QwenPaw token is present."""
    if resolver not in _external_identity_resolvers:
        _external_identity_resolvers.append(resolver)


def unregister_external_identity_resolver(
    resolver: IdentityResolver,
) -> None:
    """Remove a previously registered resolver (no-op if absent)."""
    if resolver in _external_identity_resolvers:
        _external_identity_resolvers.remove(resolver)


def has_external_identity_resolvers() -> bool:
    """Return True if at least one external identity resolver is registered."""
    return bool(_external_identity_resolvers)


async def _resolve_external_identity(request) -> Optional[str]:
    """Return the first non-empty identity from registered resolvers.

    A resolver that raises is logged and skipped so one bad plugin never
    fails the request pipeline.
    """
    for resolver in _external_identity_resolvers:
        try:
            identity = await resolver(request)
        except Exception:
            logger.exception("external identity resolver failed")
            continue
        if identity:
            return identity
    return None
```

- [ ] **Step 4: 运行,确认通过**

Run: `pytest tests/unit/app/test_auth_identity_resolver.py -v`
Expected: PASS(4 passed)

- [ ] **Step 5: 提交**

```bash
git add src/qwenpaw/app/auth.py tests/unit/app/test_auth_identity_resolver.py
git commit -m "feat(auth): add external identity resolver registry"
```

---

## Task 2: 核心 auth —— 中间件回退到解析器

**Files:**
- Modify: `src/qwenpaw/app/auth.py`(`AuthMiddleware.dispatch`,约 605-633)
- Test: `tests/unit/app/test_auth_identity_resolver.py`(追加)

- [ ] **Step 1: 写失败测试**

在 `tests/unit/app/test_auth_identity_resolver.py` 追加:

```python
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient


class _FakeSecurity:
    allow_no_auth_hosts: list = []


class _FakeConfig:
    security = _FakeSecurity()


def _build_client(monkeypatch) -> TestClient:
    # Force auth enforcement regardless of local registered users.
    monkeypatch.setattr(auth_mod, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(auth_mod, "has_registered_users", lambda: True)
    monkeypatch.setattr(auth_mod, "_get_config_cached", lambda: _FakeConfig())

    async def whoami(request):
        return JSONResponse({"user": getattr(request.state, "user", None)})

    app = Starlette(
        routes=[Route("/api/console/chat", whoami, methods=["POST"])],
    )
    app.add_middleware(auth_mod.AuthMiddleware)
    return TestClient(app)


def test_middleware_uses_resolver_when_no_qwenpaw_token(monkeypatch):
    async def r(request):
        if request.headers.get("X-NocoBase-Token"):
            return "carol@example.com"
        return None

    register_external_identity_resolver(r)
    client = _build_client(monkeypatch)
    resp = client.post(
        "/api/console/chat", headers={"X-NocoBase-Token": "tok"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"user": "carol@example.com"}


def test_middleware_401_when_no_token_and_no_resolver(monkeypatch):
    client = _build_client(monkeypatch)
    resp = client.post("/api/console/chat")
    assert resp.status_code == 401


def test_middleware_qwenpaw_token_wins_over_resolver(monkeypatch):
    calls = {"n": 0}

    async def r(_request):
        calls["n"] += 1
        return "should-not-be-used@example.com"

    register_external_identity_resolver(r)
    client = _build_client(monkeypatch)
    token = auth_mod.create_token("dave@example.com")
    resp = client.post(
        "/api/console/chat",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"user": "dave@example.com"}
    assert calls["n"] == 0  # resolver not consulted when token valid
```

- [ ] **Step 2: 运行,确认失败**

Run: `pytest tests/unit/app/test_auth_identity_resolver.py -k middleware -v`
Expected: FAIL(`test_middleware_uses_resolver...` 得 401,因回退未接)

- [ ] **Step 3: 实现最小代码**

把 `AuthMiddleware.dispatch`(`src/qwenpaw/app/auth.py:605-633`)的 token 校验段改为:

```python
        token = self._extract_token(request)
        user = verify_token(token) if token else None
        if user is None:
            user = await _resolve_external_identity(request)
        if user is None:
            detail = "Invalid or expired token" if token else (
                "Not authenticated"
            )
            return Response(
                content=json.dumps({"detail": detail}),
                status_code=401,
                media_type="application/json",
            )

        request.state.user = user
        return await call_next(request)
```

> 说明:保留原有两种 401 文案(有 token 但无效 vs 无 token),兼容既有断言。

- [ ] **Step 4: 运行,确认通过**

Run: `pytest tests/unit/app/test_auth_identity_resolver.py -v`
Expected: PASS(全部通过)

- [ ] **Step 5: 回归 + 提交**

Run: `pytest tests/integration/test_auth_real.py -v`(确认既有 auth 行为不破)
Expected: PASS(或原有跳过标记)

```bash
git add src/qwenpaw/app/auth.py tests/unit/app/test_auth_identity_resolver.py
git commit -m "feat(auth): fall back to identity resolvers when no QwenPaw token"
```

---

## Task 3: 核心 auth —— `_should_skip_auth` 在有解析器时强制鉴权

**Files:**
- Modify: `src/qwenpaw/app/auth.py`(`_should_skip_auth`,约 635-659)
- Test: `tests/unit/app/test_auth_identity_resolver.py`(追加)

- [ ] **Step 1: 写失败测试**

追加:

```python
from starlette.requests import Request as _Req


def _make_request(path="/api/console/chat", method="POST") -> _Req:
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "query_string": b"",
    }
    return _Req(scope)


def test_skip_auth_enforced_when_resolver_present_no_local_user(monkeypatch):
    monkeypatch.setattr(auth_mod, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(auth_mod, "has_registered_users", lambda: False)
    monkeypatch.setattr(auth_mod, "_get_config_cached", lambda: _FakeConfig())

    async def r(_request):
        return None

    register_external_identity_resolver(r)
    assert (
        auth_mod.AuthMiddleware._should_skip_auth(_make_request()) is False
    )


def test_skip_auth_skips_when_no_user_and_no_resolver(monkeypatch):
    monkeypatch.setattr(auth_mod, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(auth_mod, "has_registered_users", lambda: False)
    monkeypatch.setattr(auth_mod, "_get_config_cached", lambda: _FakeConfig())
    assert (
        auth_mod.AuthMiddleware._should_skip_auth(_make_request()) is True
    )


def test_skip_auth_public_path_always_skipped(monkeypatch):
    monkeypatch.setattr(auth_mod, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(auth_mod, "has_registered_users", lambda: True)
    monkeypatch.setattr(auth_mod, "_get_config_cached", lambda: _FakeConfig())

    async def r(_request):
        return None

    register_external_identity_resolver(r)
    req = _make_request(path="/api/auth/login", method="POST")
    assert auth_mod.AuthMiddleware._should_skip_auth(req) is True
```

- [ ] **Step 2: 运行,确认失败**

Run: `pytest tests/unit/app/test_auth_identity_resolver.py -k skip_auth -v`
Expected: FAIL(`test_skip_auth_enforced...` 得 True,因旧逻辑对无本地用户直接跳过)

- [ ] **Step 3: 实现最小代码**

把 `_should_skip_auth`(`src/qwenpaw/app/auth.py:636-638`)开头两句改为:

```python
    @staticmethod
    def _should_skip_auth(request: Request) -> bool:
        """Return ``True`` when the request does not require auth."""
        if not is_auth_enabled():
            return True
        # Enforce auth when SOMEONE can be authenticated: either a local
        # registered user OR an external identity provider (NocoBase SSO).
        # Only skip when neither exists — preserving first-user bootstrap in
        # local-only mode (register/login stay in _PUBLIC_PATHS regardless).
        if (
            not has_registered_users()
            and not has_external_identity_resolvers()
        ):
            return True
```

其余部分(OPTIONS、`_PUBLIC_PATHS`/`_PUBLIC_PREFIXES`、`/api/` 判断、`allow_no_auth_hosts`)保持不变。

- [ ] **Step 4: 运行,确认通过**

Run: `pytest tests/unit/app/test_auth_identity_resolver.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/qwenpaw/app/auth.py tests/unit/app/test_auth_identity_resolver.py
git commit -m "feat(auth): enforce auth when an external identity resolver is active"
```

---

## Task 4: 插件 —— `NocoBaseClient.verify_user_token`

**Files:**
- Modify: `plugins/bundle/nocobase_auth/nocobase_client.py`
- Test: `tests/unit/plugins/test_nocobase_client.py`(追加)

- [ ] **Step 1: 写失败测试**

在 `tests/unit/plugins/test_nocobase_client.py` 追加(沿用文件顶部已有的 `httpx_mock`/`NocoBaseClient` import;如需异常类型,补 `from nocobase_auth.nocobase_client import NocoBaseRequestError`):

```python
async def test_verify_user_token_success(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url="http://nb.local/api/auth:check",
        json={"data": {"id": 7, "email": "eve@example.com"}},
        status_code=200,
    )
    client = NocoBaseClient(base_url="http://nb.local", api_token="admin")
    user = await client.verify_user_token("user-tok")
    assert user is not None
    assert user["email"] == "eve@example.com"
    await client.close()


async def test_verify_user_token_invalid_returns_none(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url="http://nb.local/api/auth:check",
        json={"errors": [{"code": "INVALID_TOKEN"}]},
        status_code=401,
    )
    client = NocoBaseClient(base_url="http://nb.local", api_token="admin")
    assert await client.verify_user_token("bad") is None
    await client.close()


async def test_verify_user_token_network_error_raises(httpx_mock: HTTPXMock):
    httpx_mock.add_exception(httpx.ConnectError("down"))
    client = NocoBaseClient(base_url="http://nb.local", api_token="admin")
    with pytest.raises(NocoBaseRequestError):
        await client.verify_user_token("tok")
    await client.close()


async def test_verify_user_token_uses_user_token_not_admin(
    httpx_mock: HTTPXMock,
):
    httpx_mock.add_response(
        url="http://nb.local/api/auth:check",
        json={"data": {"id": 1, "email": "a@b.com"}},
        status_code=200,
    )
    client = NocoBaseClient(base_url="http://nb.local", api_token="ADMIN-TOK")
    await client.verify_user_token("USER-TOK")
    req = httpx_mock.get_requests()[-1]
    assert req.headers["Authorization"] == "Bearer USER-TOK"
    await client.close()
```

> 若文件顶部未 import `httpx`/`pytest`,补上 `import httpx` 与 `import pytest`。

- [ ] **Step 2: 运行,确认失败**

Run: `pytest tests/unit/plugins/test_nocobase_client.py -k verify_user_token -v`
Expected: FAIL(`AttributeError: 'NocoBaseClient' object has no attribute 'verify_user_token'`)

- [ ] **Step 3: 实现最小代码**

在 `plugins/bundle/nocobase_auth/nocobase_client.py` 的 `NocoBaseClient` 内新增(放在 `list_roles` 之后):

```python
    async def verify_user_token(
        self,
        user_token: str,
    ) -> Optional[Dict[str, Any]]:
        """Verify a NocoBase *user* token via ``auth:check``.

        Uses the caller's own token (not the plugin's admin api_token), so a
        one-off client is created rather than reusing ``_get_client()``.

        Returns:
            The user dict on success; ``None`` when the token is invalid
            (HTTP 401). Raises :class:`NocoBaseRequestError` on network or
            server errors so the caller can treat "could not verify" as a
            non-cacheable outcome.
        """
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                headers={"Authorization": f"Bearer {user_token}"},
                timeout=self.timeout,
                follow_redirects=True,
                trust_env=False,
            ) as client:
                response = await client.get("/api/auth:check")
        except httpx.HTTPError as exc:
            raise NocoBaseRequestError(
                f"auth:check request failed: {exc}",
            ) from exc

        if response.status_code == 401:
            return None
        if response.status_code >= 400:
            raise NocoBaseRequestError(
                f"auth:check failed: {response.status_code}",
                status_code=response.status_code,
            )
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        return data if isinstance(data, dict) else None
```

- [ ] **Step 4: 运行,确认通过**

Run: `pytest tests/unit/plugins/test_nocobase_client.py -v`
Expected: PASS(含既有用例)

- [ ] **Step 5: 提交**

```bash
git add plugins/bundle/nocobase_auth/nocobase_client.py tests/unit/plugins/test_nocobase_client.py
git commit -m "feat(nocobase-auth): add verify_user_token via auth:check"
```

---

## Task 5: 插件 —— `TokenIdentityCache`(短 TTL,可注入时钟)

**Files:**
- Create: `plugins/bundle/nocobase_auth/identity_cache.py`
- Test: `tests/unit/plugins/test_nocobase_identity_cache.py`

- [ ] **Step 1: 写失败测试**

新建 `tests/unit/plugins/test_nocobase_identity_cache.py`:

```python
# -*- coding: utf-8 -*-
"""Unit tests for TokenIdentityCache."""
from __future__ import annotations

from nocobase_auth.identity_cache import TokenIdentityCache


def test_miss_returns_false():
    c = TokenIdentityCache(ttl_seconds=60, time_fn=lambda: 100.0)
    assert c.get("t") == (False, None)


def test_positive_hit_within_ttl():
    now = {"t": 100.0}
    c = TokenIdentityCache(ttl_seconds=60, time_fn=lambda: now["t"])
    c.put("t", "alice@example.com")
    now["t"] = 159.0
    assert c.get("t") == (True, "alice@example.com")


def test_expired_is_miss():
    now = {"t": 100.0}
    c = TokenIdentityCache(ttl_seconds=60, time_fn=lambda: now["t"])
    c.put("t", "alice@example.com")
    now["t"] = 161.0
    assert c.get("t") == (False, None)


def test_negative_entry_is_hit_with_none():
    c = TokenIdentityCache(ttl_seconds=60, time_fn=lambda: 100.0)
    c.put("bad", None)
    assert c.get("bad") == (True, None)
```

- [ ] **Step 2: 运行,确认失败**

Run: `pytest tests/unit/plugins/test_nocobase_identity_cache.py -v`
Expected: FAIL(`ModuleNotFoundError: nocobase_auth.identity_cache`)

- [ ] **Step 3: 实现最小代码**

新建 `plugins/bundle/nocobase_auth/identity_cache.py`:

```python
# -*- coding: utf-8 -*-
"""Short-TTL cache mapping a NocoBase user token to a resolved identity."""
from __future__ import annotations

import time
from typing import Callable, Dict, Optional, Tuple


class TokenIdentityCache:
    """Cache ``token -> sender_id`` with a short TTL and lazy expiry.

    A cached value of ``None`` is a *negative* entry (token was definitively
    invalid), distinct from a miss. ``time_fn`` is injectable for tests.
    """

    def __init__(
        self,
        ttl_seconds: float = 60.0,
        time_fn: Callable[[], float] = time.time,
    ) -> None:
        self._ttl = ttl_seconds
        self._time = time_fn
        self._entries: Dict[str, Tuple[Optional[str], float]] = {}

    def get(self, token: str) -> Tuple[bool, Optional[str]]:
        """Return ``(hit, value)``; ``hit`` is False on miss or expiry."""
        entry = self._entries.get(token)
        if entry is None:
            return (False, None)
        value, expires_at = entry
        if self._time() >= expires_at:
            self._entries.pop(token, None)
            return (False, None)
        return (True, value)

    def put(self, token: str, value: Optional[str]) -> None:
        """Cache ``value`` (an identity, or ``None`` for a negative entry)."""
        self._entries[token] = (value, self._time() + self._ttl)
```

- [ ] **Step 4: 运行,确认通过**

Run: `pytest tests/unit/plugins/test_nocobase_identity_cache.py -v`
Expected: PASS(4 passed)

- [ ] **Step 5: 提交**

```bash
git add plugins/bundle/nocobase_auth/identity_cache.py tests/unit/plugins/test_nocobase_identity_cache.py
git commit -m "feat(nocobase-auth): add short-TTL token identity cache"
```

---

## Task 6: 插件 —— `SyncEngine.verify_user_token` 薄委托

**Files:**
- Modify: `plugins/bundle/nocobase_auth/sync_engine.py`
- Test: `tests/unit/plugins/test_nocobase_identity_resolver.py`(在 Task 7 建立;此处仅加委托代码,行为由 Task 7 覆盖)

- [ ] **Step 1: 实现委托方法**

在 `plugins/bundle/nocobase_auth/sync_engine.py` 的 `SyncEngine` 内新增(放在 `test_connection` 之后):

```python
    async def verify_user_token(
        self,
        user_token: str,
    ) -> Optional[Dict[str, Any]]:
        """Verify a NocoBase user token, delegating to the client.

        Returns ``None`` when the integration is not configured or the token
        is invalid; propagates :class:`NocoBaseClientError` on network errors
        so the resolver can avoid caching a "could not verify" outcome.
        """
        client = self._get_client()
        if client is None:
            return None
        return await client.verify_user_token(user_token)
```

- [ ] **Step 2: 运行,确认不破坏既有**

Run: `pytest tests/unit/plugins/ -v`
Expected: PASS(既有全过;本方法行为在 Task 7 覆盖)

- [ ] **Step 3: 提交**

```bash
git add plugins/bundle/nocobase_auth/sync_engine.py
git commit -m "feat(nocobase-auth): expose verify_user_token on SyncEngine"
```

---

## Task 7: 插件 —— `identity_resolver.build_identity_resolver`

**Files:**
- Create: `plugins/bundle/nocobase_auth/identity_resolver.py`
- Test: `tests/unit/plugins/test_nocobase_identity_resolver.py`

- [ ] **Step 1: 写失败测试**

新建 `tests/unit/plugins/test_nocobase_identity_resolver.py`:

```python
# -*- coding: utf-8 -*-
"""Unit tests for the NocoBase identity resolver."""
from __future__ import annotations

import pytest

from nocobase_auth.identity_cache import TokenIdentityCache
from nocobase_auth.identity_resolver import build_identity_resolver
from nocobase_auth.nocobase_client import NocoBaseRequestError


class _Cfg:
    def __init__(self, enabled=True, user_id_field="email"):
        self.enabled = enabled
        self.user_id_field = user_id_field


class _FakeEngine:
    def __init__(self, cfg, user=None, exc=None):
        self.config = cfg
        self._user = user
        self._exc = exc
        self.calls = 0

    async def verify_user_token(self, token):
        self.calls += 1
        if self._exc is not None:
            raise self._exc
        return self._user


class _Req:
    def __init__(self, headers):
        self.headers = headers


def _cache():
    return TokenIdentityCache(ttl_seconds=60, time_fn=lambda: 0.0)


async def test_disabled_returns_none():
    eng = _FakeEngine(_Cfg(enabled=False))
    resolve = build_identity_resolver(eng, _cache())
    assert await resolve(_Req({"X-NocoBase-Token": "t"})) is None


async def test_no_header_returns_none():
    eng = _FakeEngine(_Cfg())
    resolve = build_identity_resolver(eng, _cache())
    assert await resolve(_Req({})) is None
    assert eng.calls == 0


async def test_success_extracts_email_and_caches():
    eng = _FakeEngine(_Cfg(), user={"id": 1, "email": "eve@example.com"})
    cache = _cache()
    resolve = build_identity_resolver(eng, cache)
    req = _Req({"X-NocoBase-Token": "t"})
    assert await resolve(req) == "eve@example.com"
    # second call served from cache, no extra verify
    assert await resolve(req) == "eve@example.com"
    assert eng.calls == 1


async def test_invalid_token_negative_cached():
    eng = _FakeEngine(_Cfg(), user=None)
    cache = _cache()
    resolve = build_identity_resolver(eng, cache)
    req = _Req({"X-NocoBase-Token": "bad"})
    assert await resolve(req) is None
    assert await resolve(req) is None
    assert eng.calls == 1  # negative-cached, not re-verified


async def test_network_error_not_cached():
    eng = _FakeEngine(_Cfg(), exc=NocoBaseRequestError("down"))
    cache = _cache()
    resolve = build_identity_resolver(eng, cache)
    req = _Req({"X-NocoBase-Token": "t"})
    assert await resolve(req) is None
    assert await resolve(req) is None
    assert eng.calls == 2  # retried, not cached
```

- [ ] **Step 2: 运行,确认失败**

Run: `pytest tests/unit/plugins/test_nocobase_identity_resolver.py -v`
Expected: FAIL(`ModuleNotFoundError: nocobase_auth.identity_resolver`)

- [ ] **Step 3: 实现最小代码**

新建 `plugins/bundle/nocobase_auth/identity_resolver.py`:

```python
# -*- coding: utf-8 -*-
"""Resolve a NocoBase user token into an ACL sender_id."""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Optional

from .identity_cache import TokenIdentityCache
from .nocobase_client import NocoBaseClient

logger = logging.getLogger(__name__)

NOCOBASE_TOKEN_HEADER = "X-NocoBase-Token"

IdentityResolver = Callable[[Any], Awaitable[Optional[str]]]


def build_identity_resolver(
    engine: Any,
    cache: TokenIdentityCache,
) -> IdentityResolver:
    """Return an async resolver reading ``X-NocoBase-Token`` from a request.

    Contract: returns the user's ``sender_id`` (per ``user_id_field``) or
    ``None`` (no opinion / invalid). Never raises. Positive and definitively
    invalid results are cached; "could not verify" (network error) is not.
    """

    async def resolve(request: Any) -> Optional[str]:
        config = getattr(engine, "config", None)
        if not (config and getattr(config, "enabled", False)):
            return None
        token = request.headers.get(NOCOBASE_TOKEN_HEADER)
        if not token:
            return None

        hit, value = cache.get(token)
        if hit:
            return value

        try:
            user = await engine.verify_user_token(token)
        except Exception:
            logger.warning(
                "NocoBase auth:check errored; not caching this token",
            )
            return None

        if user is None:
            cache.put(token, None)  # definitively invalid → negative cache
            return None

        sender_id = NocoBaseClient._extract_sender_id(
            user, config.user_id_field,
        )
        if not sender_id:
            cache.put(token, None)
            return None
        cache.put(token, sender_id)
        return sender_id

    return resolve
```

- [ ] **Step 4: 运行,确认通过**

Run: `pytest tests/unit/plugins/test_nocobase_identity_resolver.py -v`
Expected: PASS(5 passed)

- [ ] **Step 5: 提交**

```bash
git add plugins/bundle/nocobase_auth/identity_resolver.py tests/unit/plugins/test_nocobase_identity_resolver.py
git commit -m "feat(nocobase-auth): add identity resolver from X-NocoBase-Token"
```

---

## Task 8: 插件 —— 装配解析器(生命周期注册/注销)

**Files:**
- Modify: `plugins/bundle/nocobase_auth/plugin.py`
- Test: `tests/unit/plugins/test_nocobase_plugin_wiring.py`

- [ ] **Step 1: 写失败测试**

新建 `tests/unit/plugins/test_nocobase_plugin_wiring.py`:

```python
# -*- coding: utf-8 -*-
"""The plugin registers/unregisters an identity resolver with core auth."""
from __future__ import annotations

import pytest

from qwenpaw.app import auth as auth_mod


@pytest.fixture(autouse=True)
def _clear():
    auth_mod._external_identity_resolvers.clear()
    yield
    auth_mod._external_identity_resolvers.clear()


async def test_startup_registers_and_uninstall_removes(monkeypatch):
    from nocobase_auth.plugin import NocoBaseAuthPlugin

    # Avoid real network sync: stub SyncEngine.start.
    from nocobase_auth import sync_engine as se

    async def _noop_start(self):
        return None

    monkeypatch.setattr(se.SyncEngine, "start", _noop_start)

    plugin = NocoBaseAuthPlugin()
    await plugin._on_startup()
    assert auth_mod.has_external_identity_resolvers() is True

    await plugin._on_uninstall("nocobase-auth", delete_files=False)
    assert auth_mod.has_external_identity_resolvers() is False
```

- [ ] **Step 2: 运行,确认失败**

Run: `pytest tests/unit/plugins/test_nocobase_plugin_wiring.py -v`
Expected: FAIL(启动后 `has_external_identity_resolvers()` 仍为 False)

- [ ] **Step 3: 实现最小代码**

修改 `plugins/bundle/nocobase_auth/plugin.py`:

1) 在 `__init__` 里增加解析器句柄:

```python
    def __init__(self):
        self._checker: Optional[
            Callable[[str, str, dict], Optional[str]]
        ] = None
        self._identity_resolver: Optional[Callable[..., Any]] = None
        self._sync_engine: Optional[Any] = None
```

2) 在 `_on_startup` 里,注册 ACL checker 之后追加(与其对称):

```python
        try:
            from qwenpaw.app.auth import (
                register_external_identity_resolver,
            )

            from .identity_cache import TokenIdentityCache
            from .identity_resolver import build_identity_resolver

            cache = TokenIdentityCache()
            self._identity_resolver = build_identity_resolver(engine, cache)
            register_external_identity_resolver(self._identity_resolver)
            logger.info("NocoBase auth identity resolver registered")
        except Exception as exc:
            logger.error(
                "Failed to register identity resolver: %s", exc,
            )
```

3) 在 `_on_uninstall` 里,注销 ACL checker 之后追加:

```python
        if self._identity_resolver is not None:
            try:
                from qwenpaw.app.auth import (
                    unregister_external_identity_resolver,
                )

                unregister_external_identity_resolver(
                    self._identity_resolver,
                )
                logger.info("NocoBase auth identity resolver removed")
            except Exception as exc:
                logger.error(
                    "Failed to unregister identity resolver: %s", exc,
                )
            self._identity_resolver = None
```

- [ ] **Step 4: 运行,确认通过**

Run: `pytest tests/unit/plugins/test_nocobase_plugin_wiring.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add plugins/bundle/nocobase_auth/plugin.py tests/unit/plugins/test_nocobase_plugin_wiring.py
git commit -m "feat(nocobase-auth): wire identity resolver into plugin lifecycle"
```

---

## Task 9: 契约测试 —— 身份解析器 + console 门禁端到端

**Files:**
- Test: `tests/unit/channels/test_console_sso_gate.py`
- (可能 Read 参考:`tests/unit/channels/test_console.py:600-700` 的 checker 注册模式)

- [ ] **Step 1: 写测试**

新建 `tests/unit/channels/test_console_sso_gate.py`。目标:身份解析器解析出的用户,经 NocoBase checker 判定,member→拒、放行角色→过。直接组合真实的 `build_checker` + `build_identity_resolver` + `PermissionStore`,mock `engine.verify_user_token`:

```python
# -*- coding: utf-8 -*-
"""Identity resolver + NocoBase channel gate, wired together."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from nocobase_auth.channel_gate import build_checker
from nocobase_auth.identity_cache import TokenIdentityCache
from nocobase_auth.identity_resolver import build_identity_resolver
from nocobase_auth.permission_store import PermissionStore


class _Cfg:
    enabled = True
    user_id_field = "email"


class _Engine:
    def __init__(self, user):
        self.config = _Cfg()
        self._user = user

    async def verify_user_token(self, _token):
        return self._user


class _Req:
    def __init__(self, headers):
        self.headers = headers


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as tmp:
        s = PermissionStore(path=Path(tmp) / "perms.json")
        s.update_from_sync(
            users=[
                {"id": "1", "sender_id": "member@x.com", "roles": ["member"]},
                {"id": "2", "sender_id": "boss@x.com", "roles": ["admin"]},
            ],
            roles=[
                {"id": "1", "name": "member", "title": "Member"},
                {"id": "2", "name": "admin", "title": "Admin"},
            ],
            role_channel_map={
                "member": {"allowed": [], "denied": ["console"]},
                "admin": {"allowed": ["console"], "denied": []},
            },
        )
        yield s


async def _resolved_verdict(store, user):
    resolver = build_identity_resolver(
        _Engine(user), TokenIdentityCache(ttl_seconds=60, time_fn=lambda: 0.0),
    )
    sender_id = await resolver(_Req({"X-NocoBase-Token": "t"}))
    checker = build_checker(store, lambda: True)
    return checker("console", sender_id or "", {})


async def test_member_denied(store):
    verdict = await _resolved_verdict(
        store, {"id": "1", "email": "member@x.com"},
    )
    assert verdict == "deny"


async def test_admin_allowed(store):
    verdict = await _resolved_verdict(
        store, {"id": "2", "email": "boss@x.com"},
    )
    assert verdict == "allow"


async def test_unknown_user_denied_fail_closed(store):
    verdict = await _resolved_verdict(
        store, {"id": "9", "email": "ghost@x.com"},
    )
    assert verdict == "deny"  # console fail-closed for unknown
```

- [ ] **Step 2: 运行,确认通过**

Run: `pytest tests/unit/channels/test_console_sso_gate.py -v`
Expected: PASS(3 passed)。若失败,依据断言定位是解析器取 email 还是 checker 判定的问题。

- [ ] **Step 3: 标记 p0(安全关键)**

在文件三个测试函数上各加 `@pytest.mark.p0`(与既有安全用例一致);顶部无需额外 import(`pytest` 已导入)。

- [ ] **Step 4: 重新运行 + 提交**

Run: `pytest tests/unit/channels/test_console_sso_gate.py -v -m p0`
Expected: PASS

```bash
git add tests/unit/channels/test_console_sso_gate.py
git commit -m "test(nocobase-auth): p0 contract test for SSO identity + console gate"
```

---

## Task 10: 文档 —— SSO 接入与配置

**Files:**
- Modify/Create: `website/public/docs/`(按现有文档组织选定文件,如 `nocobase-auth.md` 或安全/鉴权章节)

- [ ] **Step 1: 先定位现有文档位置**

Run: `ls website/public/docs/ && grep -rl "nocobase\|QWENPAW_AUTH_ENABLED\|allow_no_auth_hosts" website/public/docs/ 2>/dev/null`
Expected: 找到现有 NocoBase/鉴权文档,决定是新增还是追加章节。

- [ ] **Step 2: 写入"SSO 身份接入"章节**

内容需覆盖(用简体中文,与站点其余文档一致):
- **前置**:`QWENPAW_AUTH_ENABLED=true`;`allow_no_auth_hosts` 保持 `[]`;把封装页面 origin 加入 `CORS_ORIGINS`。
- **调用契约**:封装页面调 `POST /api/console/chat` 时带请求头 `X-NocoBase-Token: <NocoBase 用户 token>`;不要放进 `Authorization`(那是 QwenPaw 自己的 token 位)。
- **响应语义**:`401` = 未认证(引导重新登录 NocoBase);`200 + SSE error「您已被禁止访问此智能体。」` = 已认证但角色无 console 权限。
- **角色映射**:`member` 默认拒 console;deny 优先(用户若同时挂 member 与其它角色仍会被拒),在插件配置页维护 role→channel 映射。
- **时效**:身份校验有约 60s 缓存,NocoBase 登出后最多 ≤60s 生效。

- [ ] **Step 3: 提交**

```bash
git add website/public/docs/
git commit -m "docs(nocobase-auth): document SSO identity injection and config"
```

---

## 收尾:全量校验

- [ ] **Step 1: 跑相关测试**

Run: `pytest tests/unit/app/test_auth_identity_resolver.py tests/unit/plugins/ tests/unit/channels/test_console_sso_gate.py -v`
Expected: 全 PASS

- [ ] **Step 2: 跑 pre-commit 门禁**

Run: `pre-commit run --all-files`
Expected: black/flake8/pylint/mypy 全过(line-length=79)。若 hook 改动文件,提交改动并重跑至干净。

- [ ] **Step 3: 手动端到端复验(可选,需真 NocoBase)**

按 spec 第 4 节:`QWENPAW_AUTH_ENABLED=true` 起后端,用带 `X-NocoBase-Token`(member 用户)的请求打 `/api/console/chat`,预期后端日志 `console external ACL blocked: sender=<email>`;放行角色则进 agent。

---

## Self-Review(计划自审记录)

- **Spec 覆盖**:①扩展点=Task1-2;②鉴权开关=Task3;③verify_user_token=Task4;④缓存=Task5;⑤engine 委托=Task6;⑥解析器=Task7;⑦装配=Task8;⑧错误/安全(fail-closed、优先级、负缓存不缓存网络错误)=Task4/7/9;⑨测试策略三层+ p0 守卫=Task1-3/7/9;⑩CORS/文档=Task10。均有对应任务。
- **类型一致**:`IdentityResolver`(auth.py 与插件各自定义,签名一致)、`register/unregister/has_external_identity_resolvers`、`_resolve_external_identity`、`TokenIdentityCache.get→(bool,Optional[str])`/`put(token,value)`、`verify_user_token→Optional[Dict]`(client 与 engine 同签名)、`NOCOBASE_TOKEN_HEADER="X-NocoBase-Token"` 全程一致。
- **无占位符**:每步含可运行代码与确切命令。
- **待实现期留意**:Task4 的 `auth:check` 若该 NocoBase 实例需 `X-App`/`X-Authenticator` 头,在 `verify_user_token` 的 `headers` 中补充(spec 第 9 节)。
