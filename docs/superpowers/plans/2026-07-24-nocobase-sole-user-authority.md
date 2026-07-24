# NocoBase 唯一用户权威源 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 NocoBase 成为用户与权限的唯一权威源——删除 QwenPaw 侧的用户镜像缓存与本地账户，console/API 的身份与角色改为用「用户自己的 token」实时查询 NocoBase。

**Architecture:** 主包 `auth.py` 只保留可插拔的外部认证中间件骨架；NocoBase 插件的身份解析器在 `auth:check` 时连角色一起解析并进 60s 缓存；console 门禁改为「已验证身份 + 实时角色比 `role_channel_map`」；删除 `SyncEngine`/镜像/本地账户；NocoBase 连接用环境变量首次种子化。外部聊天渠道的本地 ACL 与 per-user token 用量归属保持不动。

**Tech Stack:** Python 3.10–3.13、FastAPI、Starlette middleware、pydantic、httpx、pytest（`asyncio_mode=auto`）；前端 React 18 + Vite + TS + Ant Design + vitest。

**参考 spec：** `docs/superpowers/specs/2026-07-24-nocobase-sole-user-authority-design.md`

---

## 前置说明与关键类型

- 本计划引入一个跨主包/插件共享的身份类型 `ResolvedIdentity`，定义在主包 `src/qwenpaw/app/auth.py`：

  ```python
  @dataclass
  class ResolvedIdentity:
      """一次外部身份解析的结果：稳定身份串 + 该用户的 NocoBase 角色名列表。"""

      sender_id: str
      roles: list[str] = field(default_factory=list)
  ```

- 身份解析器契约由 `Callable[[Request], Awaitable[Optional[str]]]` 改为
  `Callable[[Request], Awaitable[Optional[ResolvedIdentity]]]`。
- `role_channel_map` 的权威源是 `NocoBaseAuthConfig.role_channel_map`（`List[RoleChannelMapping]`），门禁直接读它，不再经过任何本地镜像。

**Lint 门禁（每次 commit 前必过）：** `pre-commit run --all-files`（black `--line-length=79`、flake8、pylint、mypy、prettier）。若钩子改了文件，`git add` 后重跑至干净。

**执行环境建议：** 在独立 worktree 中执行（`superpowers:using-git-worktrees`）。

---

## 文件结构（改动地图）

**主包 `src/qwenpaw/`**
- `app/auth.py` — 删本地账户实现；加 `ResolvedIdentity`；中间件纯外部路径；`_should_skip_auth` fail-closed 兜底。
- `app/routers/auth.py` — 删 register/update-profile/revoke-*；login 走外部；status/verify 契约调整。
- `app/routers/console.py` — 注入 `acl_roles`（来自 `request.state.user_roles`）。
- `app/_app.py` — 删 `auto_register_from_env()` 调用。
- `cli/doctor_cmd.py` — `_check_web_auth` 去掉对 `has_registered_users` 的依赖。

**插件 `plugins/bundle/nocobase_auth/`**
- `nocobase_client.py` — `verify_user_token` 带 `appends=roles`；新增 `verify_user_identity` 返回 `(sender_id, roles)`。
- `identity_cache.py` — 缓存值类型泛化为 `Optional[Any]`（存 `ResolvedIdentity`）。
- `identity_resolver.py` — 返回 `ResolvedIdentity`；从 `auth:check` 结果取角色。
- `role_policy.py`（**新建**）— 纯函数 `evaluate_role_channel(roles, channel_key, mappings)`。
- `channel_gate.py` — 用 `meta["acl_roles"]` + config 的 `role_channel_map` 判定；删 `is_known_user` 依赖。
- `engine.py`（**新建，取代 `sync_engine.py`**）— `NocoBaseEngine`：持 config + verify + authenticate + test_connection + update_config + 实时 list_users/list_roles；无镜像。
- `routers.py` — 删 sync/webhook；users/roles 改实时透传并在失败时报错；status 改读 engine。
- `config.py` — 新增 `seed_from_env()` 首次种子化。
- `plugin.py` — 用 `NocoBaseEngine` 替 `SyncEngine`；startup 自检告警。
- 删除：`sync_engine.py`、`permission_store.py`。

**前端 `console/src/`**
- `api/modules/auth.ts` — 删 `register`/`updateProfile`；`AuthStatusResponse` 改 `{enabled, mode}`。
- `pages/Login/index.tsx` — 删注册分支。
- `layouts/Sidebar.tsx` — 删改密入口。
- `api/modules/auth.test.ts` — 更新。

---

## Stage 1 — 插件实时化（角色随身份解析 + 门禁改造 + 引擎瘦身）

> 本阶段结束后：身份解析连角色一起返回并缓存；console 门禁用实时角色判定；`SyncEngine`/镜像删除；列表端点实时透传。主包尚未改，插件独立可测。

### Task 1.1: `nocobase_client` 在 `auth:check` 时带回角色

**Files:**
- Modify: `plugins/bundle/nocobase_auth/nocobase_client.py:156-194`（`verify_user_token`）
- Test: `tests/unit/plugins/test_nocobase_client.py`

- [ ] **Step 1: 写失败测试** — 追加到 `tests/unit/plugins/test_nocobase_client.py`

```python
import httpx
import pytest

from nocobase_auth.nocobase_client import NocoBaseClient


def _client_with(handler):
    transport = httpx.MockTransport(handler)
    return NocoBaseClient(
        base_url="http://nb.local",
        api_token="admin-token",
        transport=transport,
    )


@pytest.mark.asyncio
async def test_verify_user_token_returns_roles_via_appends():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(
            200,
            json={
                "data": {
                    "id": 7,
                    "email": "u@x.io",
                    "roles": [{"name": "admin"}, "member"],
                }
            },
        )

    # verify_user_token uses a one-off client with the *caller's* token,
    # so the MockTransport must be injected via the httpx client it builds.
    # NocoBaseClient.verify_user_token builds its own client; to test it we
    # pass the transport through and assert appends=roles is requested.
    client = _client_with(handler)
    user = await client.verify_user_token("user-jwt")
    assert seen["auth"] == "Bearer user-jwt"
    assert "appends=roles" in seen["url"]
    roles = NocoBaseClient._extract_roles(user)
    assert roles == ["admin", "member"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/plugins/test_nocobase_client.py::test_verify_user_token_returns_roles_via_appends -v`
Expected: FAIL —`verify_user_token` 目前不带 `appends`，且它内部新建的 `httpx.AsyncClient` 未使用注入的 `transport`。

- [ ] **Step 3: 让 `verify_user_token` 使用注入的 transport 并请求角色**

将 `nocobase_client.py` 中 `verify_user_token`（当前 156-194 行）替换为：

```python
    async def verify_user_token(
        self,
        user_token: str,
    ) -> Optional[Dict[str, Any]]:
        """Verify a NocoBase *user* token via ``auth:check``.

        Uses the caller's own token (not the plugin's admin api_token), so a
        one-off client is created rather than reusing ``_get_client()``. The
        current user is requested with ``appends=roles`` so the caller's roles
        come back on the hot path without needing the admin token.

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
                transport=self.transport,
            ) as client:
                response = await client.get(
                    "/api/auth:check",
                    params={"appends": "roles"},
                )
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

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/unit/plugins/test_nocobase_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add plugins/bundle/nocobase_auth/nocobase_client.py tests/unit/plugins/test_nocobase_client.py
git commit -m "feat(nocobase): return roles from auth:check via appends"
```

> **⚠️ 实现前验证点（spec §12.1）：** 在真实 NocoBase 上确认 `GET /api/auth:check?appends=roles` 会用「用户自己的 token」返回 `data.roles`。手动验证：
> `curl -H "Authorization: Bearer <某用户登录后的token>" "http://<nocobase>/api/auth:check?appends=roles"`，检查响应 `data.roles` 是否存在。
> 若不返回角色：`role_channel_map` 为空时默认放行不受影响（角色为空即走默认允许）；但**基于角色的限制会静默失效**。届时需改取角色方式（如 `roles:check`），并保持「管理员 api_token 不进鉴权关键路径」。若验证失败，暂停并向用户汇报。

---

### Task 1.2: `identity_cache` 缓存值泛化为可存 `ResolvedIdentity`

**Files:**
- Modify: `plugins/bundle/nocobase_auth/identity_cache.py`
- Test: `tests/unit/plugins/test_identity_cache.py`（若不存在则创建）

- [ ] **Step 1: 写失败测试** — 创建/追加 `tests/unit/plugins/test_identity_cache.py`

```python
from nocobase_auth.identity_cache import TokenIdentityCache


def test_cache_stores_arbitrary_object_value():
    ticks = [100.0]
    cache = TokenIdentityCache(ttl_seconds=10, time_fn=lambda: ticks[0])
    obj = object()
    cache.put("tok", obj)
    hit, value = cache.get("tok")
    assert hit is True
    assert value is obj


def test_cache_negative_entry_distinct_from_miss():
    cache = TokenIdentityCache(ttl_seconds=10, time_fn=lambda: 0.0)
    cache.put("bad", None)
    assert cache.get("bad") == (True, None)
    assert cache.get("never") == (False, None)
```

- [ ] **Step 2: 跑测试确认失败/通过基线**

Run: `pytest tests/unit/plugins/test_identity_cache.py -v`
Expected: 若旧实现已可存对象，`test_cache_stores_arbitrary_object_value` 可能已 PASS；本步主要锁定行为。若 FAIL 继续 Step 3。

- [ ] **Step 3: 泛化类型注解** — 编辑 `identity_cache.py`，把 `Optional[str]` 值类型改为 `Optional[Any]`

将文件顶部 import 与类型改为：

```python
from typing import Any, Callable, Dict, Optional, Tuple


class TokenIdentityCache:
    """Cache ``token -> resolved identity`` with a short TTL and lazy expiry.

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
        self._entries: Dict[str, Tuple[Optional[Any], float]] = {}

    def get(self, token: str) -> Tuple[bool, Optional[Any]]:
        """Return ``(hit, value)``; ``hit`` is False on miss or expiry."""
        entry = self._entries.get(token)
        if entry is None:
            return (False, None)
        value, expires_at = entry
        if self._time() >= expires_at:
            self._entries.pop(token, None)
            return (False, None)
        return (True, value)

    def put(self, token: str, value: Optional[Any]) -> None:
        """Cache ``value`` (a resolved identity, or ``None`` negative entry)."""
        self._entries[token] = (value, self._time() + self._ttl)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/unit/plugins/test_identity_cache.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add plugins/bundle/nocobase_auth/identity_cache.py tests/unit/plugins/test_identity_cache.py
git commit -m "refactor(nocobase): allow identity cache to store resolved identity objects"
```

---

### Task 1.3: 主包新增 `ResolvedIdentity`（供插件与中间件共享）

> 该类型放在主包，Stage 2 的中间件也用它。本 Task 只加类型，不改行为。

**Files:**
- Modify: `src/qwenpaw/app/auth.py`（顶部 import 与 external-identity 区块，84-96 附近）
- Test: `tests/unit/app/test_resolved_identity.py`（新建）

- [ ] **Step 1: 写失败测试** — 创建 `tests/unit/app/test_resolved_identity.py`

```python
from qwenpaw.app.auth import ResolvedIdentity


def test_resolved_identity_defaults_roles_to_empty_list():
    ident = ResolvedIdentity(sender_id="u@x.io")
    assert ident.sender_id == "u@x.io"
    assert ident.roles == []


def test_resolved_identity_carries_roles():
    ident = ResolvedIdentity(sender_id="u@x.io", roles=["admin"])
    assert ident.roles == ["admin"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/app/test_resolved_identity.py -v`
Expected: FAIL — `ImportError: cannot import name 'ResolvedIdentity'`

- [ ] **Step 3: 添加类型** — 编辑 `src/qwenpaw/app/auth.py`

将顶部 dataclass import 改为含 `field`：

```python
from dataclasses import dataclass, field
```

在 `_external_identity_resolvers` 定义之前（当前 84 行 `IdentityResolver = ...` 之上）插入：

```python
@dataclass
class ResolvedIdentity:
    """Result of one external identity resolution.

    ``sender_id`` is the stable identity string (per ``user_id_field``) used by
    channel ACL and token-usage attribution. ``roles`` are the caller's
    NocoBase role names, resolved live so the console gate can evaluate the
    role→channel map without any local user mirror.
    """

    sender_id: str
    roles: list[str] = field(default_factory=list)
```

并把 `IdentityResolver` 契约改为：

```python
IdentityResolver = Callable[["Request"], Awaitable[Optional["ResolvedIdentity"]]]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/unit/app/test_resolved_identity.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/qwenpaw/app/auth.py tests/unit/app/test_resolved_identity.py
git commit -m "feat(auth): add ResolvedIdentity type for identity+roles resolution"
```

---

### Task 1.4: 身份解析器返回 `ResolvedIdentity`（含角色）

**Files:**
- Modify: `plugins/bundle/nocobase_auth/identity_resolver.py`
- Test: `tests/unit/app/test_auth_identity_resolver.py`（现有，需更新断言）+ 新增插件级测试 `tests/unit/plugins/test_identity_resolver.py`

- [ ] **Step 1: 写失败测试** — 创建 `tests/unit/plugins/test_identity_resolver.py`

```python
import pytest

from qwenpaw.app.auth import ResolvedIdentity
from nocobase_auth.identity_cache import TokenIdentityCache
from nocobase_auth.identity_resolver import build_identity_resolver


class _Cfg:
    enabled = True
    user_id_field = "email"


class _Engine:
    def __init__(self, user):
        self.config = _Cfg()
        self._user = user

    async def verify_user_token(self, token):
        return self._user


class _Req:
    def __init__(self, token):
        self.headers = {"X-NocoBase-Token": token}
        self.query_params = {}


@pytest.mark.asyncio
async def test_resolver_returns_identity_with_roles():
    engine = _Engine(
        {"email": "u@x.io", "roles": [{"name": "admin"}, "member"]}
    )
    resolver = build_identity_resolver(engine, TokenIdentityCache())
    result = await resolver(_Req("tok"))
    assert isinstance(result, ResolvedIdentity)
    assert result.sender_id == "u@x.io"
    assert result.roles == ["admin", "member"]


@pytest.mark.asyncio
async def test_resolver_caches_and_negative_caches():
    engine = _Engine({"email": "u@x.io", "roles": []})
    cache = TokenIdentityCache()
    resolver = build_identity_resolver(engine, cache)
    first = await resolver(_Req("tok"))
    hit, cached = cache.get("tok")
    assert hit and cached is first

    engine._user = None
    none_result = await resolver(_Req("bad"))
    assert none_result is None
    assert cache.get("bad") == (True, None)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/plugins/test_identity_resolver.py -v`
Expected: FAIL — 解析器目前返回 `str` 而非 `ResolvedIdentity`。

- [ ] **Step 3: 改写解析器** — 替换 `identity_resolver.py` 的 import 与 `resolve` 主体

顶部改为（新增导入 `ResolvedIdentity` 与角色抽取）：

```python
from typing import Any, Awaitable, Callable, Optional

from qwenpaw.app.auth import ResolvedIdentity

from .identity_cache import TokenIdentityCache
from .nocobase_client import NocoBaseClient

logger = logging.getLogger(__name__)

NOCOBASE_TOKEN_HEADER = "X-NocoBase-Token"

IdentityResolver = Callable[[Any], Awaitable[Optional[ResolvedIdentity]]]
```

把 `resolve` 内自 `try/except` 之后的部分（当前 61-81 行）替换为：

```python
        try:
            user = await engine.verify_user_token(token)
        except Exception:
            logger.warning(
                "NocoBase auth: token check errored; not caching this token",
            )
            return None

        if user is None:
            cache.put(token, None)  # definitively invalid -> negative cache
            return None

        sender_id = NocoBaseClient.extract_sender_id(
            user,
            config.user_id_field,
        )
        if not sender_id:
            cache.put(token, None)
            return None
        identity = ResolvedIdentity(
            sender_id=sender_id,
            roles=NocoBaseClient._extract_roles(user),
        )
        cache.put(token, identity)
        return identity
```

并把 `resolve` 的返回注解由 `Optional[str]` 改为 `Optional[ResolvedIdentity]`；cache 命中分支 `return value` 保持不变（现在 value 是 `ResolvedIdentity`）。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/unit/plugins/test_identity_resolver.py -v`
Expected: PASS

- [ ] **Step 5: 更新现有解析器测试** — 打开 `tests/unit/app/test_auth_identity_resolver.py`，把断言「解析结果等于 sender_id 字符串」改为「`result.sender_id == <期望>` 且 `isinstance(result, ResolvedIdentity)`」。运行：

Run: `pytest tests/unit/app/test_auth_identity_resolver.py -v`
Expected: PASS（改完后）

- [ ] **Step 6: Commit**

```bash
git add plugins/bundle/nocobase_auth/identity_resolver.py tests/unit/plugins/test_identity_resolver.py tests/unit/app/test_auth_identity_resolver.py
git commit -m "feat(nocobase): resolve identity with live roles into ResolvedIdentity"
```

---

### Task 1.5: 新建 `role_policy` 纯函数评估角色→channel

**Files:**
- Create: `plugins/bundle/nocobase_auth/role_policy.py`
- Test: `tests/unit/plugins/test_role_policy.py`（新建）

- [ ] **Step 1: 写失败测试** — 创建 `tests/unit/plugins/test_role_policy.py`

```python
from nocobase_auth.config import RoleChannelMapping
from nocobase_auth.role_policy import evaluate_role_channel


def _map():
    return [
        RoleChannelMapping(
            role_name="admin", allowed_channels=["console"]
        ),
        RoleChannelMapping(
            role_name="banned", denied_channels=["console"]
        ),
    ]


def test_empty_map_returns_none():
    assert evaluate_role_channel(["admin"], "console", []) is None


def test_allowed_role_returns_true():
    assert evaluate_role_channel(["admin"], "console", _map()) is True


def test_denied_role_returns_false():
    assert evaluate_role_channel(["banned"], "console", _map()) is False


def test_deny_precedes_allow():
    assert (
        evaluate_role_channel(["admin", "banned"], "console", _map())
        is False
    )


def test_unmentioned_channel_returns_none():
    assert evaluate_role_channel(["admin"], "feishu", _map()) is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/plugins/test_role_policy.py -v`
Expected: FAIL — 模块不存在。

- [ ] **Step 3: 实现** — 创建 `plugins/bundle/nocobase_auth/role_policy.py`

```python
# -*- coding: utf-8 -*-
"""Pure evaluation of the NocoBase role→channel access policy."""
from __future__ import annotations

from typing import List, Optional

from .config import RoleChannelMapping


def evaluate_role_channel(
    roles: List[str],
    channel_key: str,
    mappings: List[RoleChannelMapping],
) -> Optional[bool]:
    """Return an access opinion for ``channel_key`` given the caller's roles.

    - Any matching role denies the channel -> ``False`` (deny wins).
    - Else any matching role allows the channel -> ``True``.
    - No mapping mentions the channel for these roles -> ``None`` (no opinion).
    """
    role_set = set(roles or [])
    allowed = False
    denied = False
    for mapping in mappings:
        if mapping.role_name not in role_set:
            continue
        if channel_key in mapping.denied_channels:
            denied = True
        if channel_key in mapping.allowed_channels:
            allowed = True
    if denied:
        return False
    if allowed:
        return True
    return None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/unit/plugins/test_role_policy.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add plugins/bundle/nocobase_auth/role_policy.py tests/unit/plugins/test_role_policy.py
git commit -m "feat(nocobase): add pure role→channel policy evaluation"
```

---

### Task 1.6: 门禁 `channel_gate` 改用实时角色（删镜像依赖）

**Files:**
- Modify: `plugins/bundle/nocobase_auth/channel_gate.py`
- Test: `tests/unit/plugins/test_channel_gate.py`（新建）

- [ ] **Step 1: 写失败测试** — 创建 `tests/unit/plugins/test_channel_gate.py`

```python
from nocobase_auth.channel_gate import build_checker
from nocobase_auth.config import NocoBaseAuthConfig, RoleChannelMapping


def _checker(mappings, enabled=True):
    config = NocoBaseAuthConfig(enabled=enabled, role_channel_map=mappings)
    return build_checker(lambda: config, is_enabled=lambda: enabled)


def test_console_no_identity_denies_when_enabled():
    checker = _checker([])
    assert checker("console", "", {}) == "deny"


def test_console_known_user_default_allows():
    checker = _checker([])
    assert checker("console", "u@x.io", {"acl_roles": ["member"]}) == "allow"


def test_console_denied_role_blocks():
    checker = _checker(
        [RoleChannelMapping(role_name="banned", denied_channels=["console"])]
    )
    assert (
        checker("console", "u@x.io", {"acl_roles": ["banned"]}) == "deny"
    )


def test_console_allow_list_excludes_other_roles():
    checker = _checker(
        [RoleChannelMapping(role_name="admin", allowed_channels=["console"])]
    )
    # allow-list exists for console but caller lacks the role -> no explicit
    # opinion -> fail-closed channel still allows a known (authenticated) user.
    assert checker("console", "u@x.io", {"acl_roles": ["member"]}) == "allow"


def test_disabled_plugin_never_blocks():
    checker = _checker([], enabled=False)
    assert checker("console", "", {}) is None


def test_non_failclosed_channel_no_opinion_falls_through():
    checker = _checker([])
    assert checker("feishu", "someone", {"acl_roles": []}) is None
```

> 说明：与 spec §5 一致——`role_channel_map` 为空或对该角色无明确意见时，fail-closed 渠道上「有身份=已认证」即放行；仅当命中 denied 才拒。allow-list 语义按 spec：存在 allow 但角色不在内且无 deny → 无明确意见 → 已认证用户仍放行（与旧 `is_channel_allowed` 返回 None 的落点一致）。

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/plugins/test_channel_gate.py -v`
Expected: FAIL — `build_checker` 目前签名是 `(store, is_enabled)` 且依赖 `store.is_known_user` / `store.is_channel_allowed`。

- [ ] **Step 3: 改写 `channel_gate.py`**

整文件替换为：

```python
# -*- coding: utf-8 -*-
"""External ACL checker that evaluates NocoBase role→channel policy live."""
from __future__ import annotations

import logging
from typing import Callable, Optional

from .config import NocoBaseAuthConfig
from .role_policy import evaluate_role_channel

logger = logging.getLogger(__name__)


AclResult = Optional[str]
AclChecker = Callable[[str, str, dict], AclResult]

# Channels that fail closed: when the integration is enabled, a request with no
# resolved NocoBase identity is denied instead of falling through. The console
# is the QwenPaw web UI whose caller identity is the authenticated login user;
# requiring a resolved NocoBase identity enforces "no NocoBase login, no
# access".
FAIL_CLOSED_CHANNELS = frozenset({"console"})


def build_checker(
    get_config: Callable[[], NocoBaseAuthConfig],
    is_enabled: Callable[[], bool],
) -> AclChecker:
    """Return a checker callable for BaseChannel._external_acl_checkers.

    The checker receives (channel_key, sender_id, meta) and returns:
      - "allow": permitted (explicit role allow, or authenticated user on a
                 fail-closed channel with no explicit opinion).
      - "deny":  explicit role deny, or — on a fail-closed channel while the
                 integration is enabled — no resolved identity.
      - None:    no opinion; fall through to native ACL.

    Roles are read from ``meta['acl_roles']`` (injected by the HTTP layer from
    the live-resolved identity). ``role_channel_map`` comes from config.
    """

    def _safe_enabled() -> bool:
        try:
            return bool(is_enabled())
        except Exception as exc:
            logger.warning("NocoBase enabled-state check failed: %s", exc)
            return False

    def checker(
        channel_key: str,
        sender_id: str,
        meta: dict,
    ) -> AclResult:
        fail_closed = channel_key in FAIL_CLOSED_CHANNELS and _safe_enabled()

        # No identity: "not logged in" -> deny on a fail-closed channel.
        if not sender_id:
            return "deny" if fail_closed else None

        roles = meta.get("acl_roles") if isinstance(meta, dict) else None
        if not isinstance(roles, list):
            roles = []

        try:
            mappings = get_config().role_channel_map
            result = evaluate_role_channel(roles, channel_key, mappings)
        except Exception as exc:
            logger.warning("NocoBase ACL evaluation failed: %s", exc)
            return None

        if result is not None:
            return "allow" if result else "deny"

        # No explicit opinion. On a fail-closed channel, an authenticated
        # (identity present) NocoBase user is allowed.
        if not fail_closed:
            return None
        return "allow"

    return checker
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/unit/plugins/test_channel_gate.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add plugins/bundle/nocobase_auth/channel_gate.py tests/unit/plugins/test_channel_gate.py
git commit -m "refactor(nocobase): gate on live roles + config policy, drop mirror lookup"
```

---

### Task 1.7: 新建 `NocoBaseEngine`（取代 `SyncEngine`，去镜像）

**Files:**
- Create: `plugins/bundle/nocobase_auth/engine.py`
- Test: `tests/unit/plugins/test_engine.py`（新建）

- [ ] **Step 1: 写失败测试** — 创建 `tests/unit/plugins/test_engine.py`

```python
import httpx
import pytest

from nocobase_auth.config import NocoBaseAuthConfig
from nocobase_auth.engine import NocoBaseEngine, get_engine, set_engine


def _cfg(**kw):
    base = dict(enabled=True, base_url="http://nb.local", api_token="admin")
    base.update(kw)
    return NocoBaseAuthConfig(**base)


@pytest.mark.asyncio
async def test_global_accessor_roundtrip():
    engine = NocoBaseEngine(config=_cfg())
    set_engine(engine)
    assert get_engine() is engine
    set_engine(None)
    assert get_engine() is None


@pytest.mark.asyncio
async def test_list_users_live_passthrough():
    def handler(request):
        if request.url.path == "/api/users:list":
            return httpx.Response(
                200, json={"data": [{"id": 1, "email": "a@x.io", "roles": []}]}
            )
        return httpx.Response(404)

    engine = NocoBaseEngine(
        config=_cfg(), transport=httpx.MockTransport(handler)
    )
    users = await engine.list_users()
    assert users[0]["sender_id"] == "a@x.io"


@pytest.mark.asyncio
async def test_list_users_raises_when_unconfigured():
    engine = NocoBaseEngine(config=_cfg(api_token=""))
    with pytest.raises(RuntimeError):
        await engine.list_users()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/plugins/test_engine.py -v`
Expected: FAIL — 模块不存在。

- [ ] **Step 3: 实现 `engine.py`**

```python
# -*- coding: utf-8 -*-
"""NocoBase engine: config + live identity/credential verification.

Replaces the former SyncEngine. Holds no local user mirror: users/roles are
queried live and identity is resolved per-request via the caller's own token.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from .config import NocoBaseAuthConfig
from .nocobase_client import NocoBaseClient, NocoBaseClientError

logger = logging.getLogger(__name__)

_engine: Optional["NocoBaseEngine"] = None


def set_engine(engine: Optional["NocoBaseEngine"]) -> None:
    """Set the global engine instance used by routers."""
    global _engine  # noqa: PLW0603
    _engine = engine


def get_engine() -> Optional["NocoBaseEngine"]:
    """Return the global engine instance, if initialized."""
    return _engine


class NocoBaseEngine:
    """Owns config and NocoBase verification; no local mirror."""

    def __init__(
        self,
        config: Optional[NocoBaseAuthConfig] = None,
        *,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        self.config = config if config is not None else NocoBaseAuthConfig.load()
        self._transport = transport
        self._client: Optional[NocoBaseClient] = None
        set_engine(self)

    async def start(self) -> None:
        """Startup self-check: warn loudly if enabled but unreachable."""
        if not self.config.enabled:
            logger.info("NocoBase auth is disabled")
            return
        if not self.config.base_url:
            logger.warning(
                "NocoBase auth enabled but base_url is empty; console will "
                "fail closed until configured",
            )
            return
        ok = await self.test_connection()
        if not ok.get("ok"):
            logger.warning(
                "NocoBase auth enabled but connection check failed: %s. "
                "Console stays fail-closed until NocoBase is reachable.",
                ok.get("error"),
            )

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    def _admin_client(self) -> Optional[NocoBaseClient]:
        """Client using the admin api_token; only for /users and /roles."""
        if (
            not self.config.enabled
            or not self.config.base_url
            or not self.config.api_token
        ):
            return None
        if self._client is None:
            self._client = NocoBaseClient(
                base_url=self.config.base_url,
                api_token=self.config.api_token,
                transport=self._transport,
            )
        return self._client

    def update_config(self, config: NocoBaseAuthConfig) -> None:
        """Update runtime config and reset the client so new settings apply."""
        self.config = config
        self._client = None
        self.config.save()

    async def verify_user_token(
        self,
        user_token: str,
    ) -> Optional[Dict[str, Any]]:
        """Verify a NocoBase user token via the caller's own token.

        Returns ``None`` when unconfigured or the token is invalid; propagates
        :class:`NocoBaseClientError` on network errors so the resolver avoids
        caching a "could not verify" outcome. Does NOT require api_token.
        """
        if not self.config.enabled or not self.config.base_url:
            return None
        client = NocoBaseClient(
            base_url=self.config.base_url,
            api_token="",  # auth:check uses the user token, not admin token
            transport=self._transport,
        )
        try:
            return await client.verify_user_token(user_token)
        finally:
            await client.close()

    async def authenticate_credentials(
        self,
        username: str,
        password: str,
    ) -> Optional[tuple[str, Optional[str]]]:
        """Authenticate NocoBase credentials; return ``(sender_id, token)``."""
        if not self.config.enabled or not self.config.base_url:
            return None
        client = NocoBaseClient(
            base_url=self.config.base_url,
            api_token=self.config.api_token,
            transport=self._transport,
        )
        try:
            user = await client.sign_in(
                username,
                password,
                authenticator=self.config.authenticator or "basic",
            )
            if user is None:
                return None
            sender_id = self._extract_login_identity(user)
            token = user.get("token")
            if not isinstance(token, str) or not token:
                token = None
            if not sender_id and token:
                checked = await client.verify_user_token(token)
                if checked:
                    sender_id = self._extract_login_identity(checked)
            if not sender_id:
                return None
            return sender_id, token
        finally:
            await client.close()

    def _extract_login_identity(self, payload: Dict[str, Any]) -> str:
        user = payload.get("user")
        row = user if isinstance(user, dict) else payload
        sender_id = NocoBaseClient.extract_sender_id(
            row, self.config.user_id_field
        )
        if sender_id:
            return sender_id
        for fallback in ("username", "email", "phone", "nickname", "id"):
            sender_id = NocoBaseClient.extract_sender_id(row, fallback)
            if sender_id:
                return sender_id
        return ""

    async def test_connection(self) -> Dict[str, Any]:
        client = self._admin_client()
        if client is None:
            return {"ok": False, "error": "NocoBase auth not configured"}
        try:
            ok = await client.health_check()
            return (
                {"ok": True, "error": ""}
                if ok
                else {"ok": False, "error": "NocoBase health check failed"}
            )
        except NocoBaseClientError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            logger.exception("NocoBase connection test failed")
            return {"ok": False, "error": str(exc)}

    async def list_users(self) -> List[Dict[str, Any]]:
        """Live passthrough of NocoBase users (admin token). Raises if down."""
        client = self._admin_client()
        if client is None:
            raise RuntimeError("NocoBase auth not configured")
        return await client.list_users(self.config.user_id_field)

    async def list_roles(self) -> List[Dict[str, Any]]:
        """Live passthrough of NocoBase roles (admin token). Raises if down."""
        client = self._admin_client()
        if client is None:
            raise RuntimeError("NocoBase auth not configured")
        return await client.list_roles()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/unit/plugins/test_engine.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add plugins/bundle/nocobase_auth/engine.py tests/unit/plugins/test_engine.py
git commit -m "feat(nocobase): add NocoBaseEngine (no mirror) to replace SyncEngine"
```

---

### Task 1.8: 路由改为实时透传 + 删 sync/webhook

**Files:**
- Modify: `plugins/bundle/nocobase_auth/routers.py`
- Test: `tests/unit/plugins/test_routers.py`（新建）

- [ ] **Step 1: 写失败测试** — 创建 `tests/unit/plugins/test_routers.py`

```python
import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from nocobase_auth.config import NocoBaseAuthConfig
from nocobase_auth.engine import NocoBaseEngine, set_engine
from nocobase_auth.routers import build_router


def _app(engine):
    set_engine(engine)
    app = FastAPI()
    app.include_router(build_router(), prefix="/nocobase-auth")
    return app


@pytest.mark.asyncio
async def test_users_live_passthrough():
    def nb(request):
        return httpx.Response(
            200, json={"data": [{"id": 1, "email": "a@x.io", "roles": []}]}
        )

    engine = NocoBaseEngine(
        config=NocoBaseAuthConfig(
            enabled=True, base_url="http://nb.local", api_token="admin"
        ),
        transport=httpx.MockTransport(nb),
    )
    app = _app(engine)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://t"
    ) as c:
        resp = await c.get("/nocobase-auth/users")
    assert resp.status_code == 200
    assert resp.json()[0]["sender_id"] == "a@x.io"


@pytest.mark.asyncio
async def test_users_errors_not_silent_empty_when_down():
    engine = NocoBaseEngine(
        config=NocoBaseAuthConfig(enabled=True, base_url="http://nb.local")
    )  # no api_token -> unconfigured
    app = _app(engine)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://t"
    ) as c:
        resp = await c.get("/nocobase-auth/users")
    assert resp.status_code == 503  # explicit error, NOT [] with 200


@pytest.mark.asyncio
async def test_sync_and_webhook_routes_removed():
    engine = NocoBaseEngine(config=NocoBaseAuthConfig())
    app = _app(engine)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://t"
    ) as c:
        assert (await c.post("/nocobase-auth/sync")).status_code == 404
        assert (
            await c.post("/nocobase-auth/webhook", json={})
        ).status_code == 404
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/plugins/test_routers.py -v`
Expected: FAIL — 现有 `/sync`、`/webhook` 仍在；`/users` 读镜像；import `get_sync_engine`。

- [ ] **Step 3: 改写 `routers.py`**

整文件替换为：

```python
# -*- coding: utf-8 -*-
"""FastAPI routers for the NocoBase auth plugin."""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from .config import NocoBaseAuthConfig
from .engine import get_engine

logger = logging.getLogger(__name__)


def _require_engine():
    engine = get_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="Plugin not initialized")
    return engine


def build_router() -> APIRouter:
    """Build and return the plugin API router."""
    router = APIRouter(tags=["nocobase-auth"])

    @router.get("/status")
    async def status() -> Dict[str, Any]:
        engine = get_engine()
        if engine is None:
            return {
                "enabled": False,
                "configured": False,
                "error": "Plugin not initialized",
            }
        config = engine.config
        return {
            "enabled": config.enabled,
            "configured": bool(config.base_url and config.api_token),
            "base_url": config.base_url,
            "user_id_field": config.user_id_field,
        }

    @router.get("/users")
    async def list_users() -> List[Dict[str, Any]]:
        """Return NocoBase users, queried live. Errors instead of empty."""
        engine = _require_engine()
        try:
            return await engine.list_users()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=502,
                detail=f"Failed to query NocoBase users: {exc}",
            ) from exc

    @router.get("/roles")
    async def list_roles() -> List[Dict[str, Any]]:
        """Return NocoBase roles, queried live. Errors instead of empty."""
        engine = _require_engine()
        try:
            return await engine.list_roles()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=502,
                detail=f"Failed to query NocoBase roles: {exc}",
            ) from exc

    @router.get("/config")
    async def get_config() -> Dict[str, Any]:
        engine = _require_engine()
        return engine.config.to_dict()

    @router.put("/config")
    async def update_config(request: Request) -> Dict[str, Any]:
        engine = _require_engine()
        data = await request.json()
        try:
            config = NocoBaseAuthConfig.from_dict(data)
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        engine.update_config(config)
        return {"status": "ok"}

    @router.post("/test-connection")
    async def test_connection() -> Dict[str, Any]:
        engine = _require_engine()
        return await engine.test_connection()

    return router
```

> 注意：`list_users`/`list_roles` 里 `engine.list_users()` 对「未配置」抛 `RuntimeError`，被 `except Exception` 捕获后转 502。但测试 `test_users_errors_not_silent_empty_when_down` 期望 503。**统一处理：** 把 engine 的「未配置」错误映射为 503，其它网络错误为 502。将两个端点的 except 改为：

```python
        except RuntimeError as exc:  # unconfigured
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001  # network/server error
            raise HTTPException(
                status_code=502,
                detail=f"Failed to query NocoBase: {exc}",
            ) from exc
```

（对 `list_users` 与 `list_roles` 各写一份。）

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/unit/plugins/test_routers.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add plugins/bundle/nocobase_auth/routers.py tests/unit/plugins/test_routers.py
git commit -m "refactor(nocobase): live users/roles passthrough; drop sync/webhook routes"
```

---

### Task 1.9: `plugin.py` 切换到 `NocoBaseEngine` + 删镜像相关删除文件

**Files:**
- Modify: `plugins/bundle/nocobase_auth/plugin.py`
- Delete: `plugins/bundle/nocobase_auth/sync_engine.py`, `plugins/bundle/nocobase_auth/permission_store.py`
- Test: `tests/integration/test_nocobase_plugin.py`（现有，需更新）

- [ ] **Step 1: 改 `plugin.py` 的 startup/uninstall**

在 `_on_startup` 中，替换 SyncEngine 相关段落（当前 48-90 行区间）为：

```python
    async def _on_startup(self) -> None:
        """Initialize the engine and register identity/login/gate hooks."""
        from .channel_gate import build_checker
        from .config import NocoBaseAuthConfig
        from .engine import NocoBaseEngine

        logger.info("NocoBase auth plugin starting up...")

        NocoBaseAuthConfig.seed_from_env()  # first-run bootstrap (Task 3.x)
        self._engine = NocoBaseEngine()
        await self._engine.start()

        engine = self._engine
        self._checker = build_checker(
            get_config=lambda: engine.config,
            is_enabled=lambda: bool(engine.config and engine.config.enabled),
        )
        try:
            from qwenpaw.app.channels.base import BaseChannel

            BaseChannel.register_external_acl_checker(self._checker)
            logger.info("NocoBase auth channel gate checker registered")
        except Exception as exc:
            logger.error("Failed to register channel gate checker: %s", exc)
```

- [ ] **Step 2: 更新 `__init__` 与 `_on_uninstall`**

- 把 `self._sync_engine` 字段改名为 `self._engine`（`__init__` 与 `_on_uninstall` 内所有引用）。
- `_on_uninstall` 中把
  ```python
          if self._sync_engine is not None:
              from .sync_engine import set_sync_engine
              await self._sync_engine.stop()
              self._sync_engine = None
              set_sync_engine(None)
  ```
  改为
  ```python
          if self._engine is not None:
              from .engine import set_engine
              await self._engine.stop()
              self._engine = None
              set_engine(None)
  ```
- 登录认证器闭包 `_login_with_console_acl` 中 `engine.authenticate_credentials(...)` 保持不变（`NocoBaseEngine` 同名方法已提供）。

- [ ] **Step 3: 删除镜像文件**

```bash
git rm plugins/bundle/nocobase_auth/sync_engine.py plugins/bundle/nocobase_auth/permission_store.py
```

- [ ] **Step 4: 更新集成测试** — 打开 `tests/integration/test_nocobase_plugin.py`

- 删除/替换所有对 `SyncEngine`、`PermissionStore`、`engine.store`、`engine.sync()`、`/sync`、`/webhook`、`update_from_sync`、`is_known_user` 的引用。
- 断言点改为：插件启动后 `get_engine()` 返回引擎；`/nocobase-auth/users` 命中实时透传（用 MockTransport 或跳过需真连的用例，标 `@pytest.mark.integration`）。
- 门禁用例改为通过 `meta['acl_roles']` 驱动（参考 Task 1.6 测试）。

- [ ] **Step 5: 跑插件全量测试**

Run: `pytest tests/unit/plugins tests/integration/test_nocobase_plugin.py -v`
Expected: PASS（或 integration 用例按标记跳过）

- [ ] **Step 6: Commit**

```bash
git add plugins/bundle/nocobase_auth/plugin.py tests/integration/test_nocobase_plugin.py
git commit -m "refactor(nocobase): wire NocoBaseEngine; remove SyncEngine + permission mirror"
```

---

## Stage 2 — 主包去本地账户（NocoBase 强制）

> 本阶段结束后：`auth.py` 不再有本地账户；中间件纯外部路径并带回角色；`_should_skip_auth` 有 fail-closed 兜底；相关端点删除；`console.py` 注入 `acl_roles`。

### Task 2.1: 中间件纯外部路径 + 写入 `user_roles`

**Files:**
- Modify: `src/qwenpaw/app/auth.py`（`AuthMiddleware.dispatch` 759-788；`_resolve_external_identity` 200-217）
- Test: `tests/unit/app/test_auth_middleware.py`（新建）

- [ ] **Step 1: 写失败测试** — 创建 `tests/unit/app/test_auth_middleware.py`

```python
import json

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

import qwenpaw.app.auth as auth
from qwenpaw.app.auth import AuthMiddleware, ResolvedIdentity


@pytest.fixture(autouse=True)
def _clear_resolvers():
    auth._external_identity_resolvers.clear()
    auth._external_login_authenticators.clear()
    yield
    auth._external_identity_resolvers.clear()
    auth._external_login_authenticators.clear()


def _app():
    async def whoami(request: Request):
        return JSONResponse(
            {
                "user": getattr(request.state, "user", None),
                "roles": getattr(request.state, "user_roles", None),
            }
        )

    app = Starlette(routes=[Route("/api/whoami", whoami)])
    app.add_middleware(AuthMiddleware)
    return app


def test_resolved_identity_sets_user_and_roles(monkeypatch):
    monkeypatch.setenv("QWENPAW_AUTH_ENABLED", "true")

    async def resolver(_req):
        return ResolvedIdentity(sender_id="u@x.io", roles=["admin"])

    auth.register_external_identity_resolver(resolver)
    client = TestClient(_app())
    resp = client.get("/api/whoami", headers={"Authorization": "Bearer t"})
    assert resp.status_code == 200
    assert resp.json() == {"user": "u@x.io", "roles": ["admin"]}


def test_no_identity_returns_401(monkeypatch):
    monkeypatch.setenv("QWENPAW_AUTH_ENABLED", "true")

    async def resolver(_req):
        return None

    auth.register_external_identity_resolver(resolver)
    client = TestClient(_app())
    resp = client.get("/api/whoami", headers={"Authorization": "Bearer t"})
    assert resp.status_code == 401
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/app/test_auth_middleware.py -v`
Expected: FAIL — 中间件仍走 `verify_token` 分支、未写 `user_roles`。

- [ ] **Step 3: 改 `_resolve_external_identity` 返回类型**

替换 `auth.py:200-217` 的函数体为返回 `Optional[ResolvedIdentity]`：

```python
async def _resolve_external_identity(
    request: Request,
) -> Optional[ResolvedIdentity]:
    """Return the first identity from registered resolvers.

    A resolver that raises is logged and skipped so one bad plugin never
    fails the request pipeline.
    """
    for resolver in _external_identity_resolvers:
        try:
            identity = await resolver(request)
        except Exception:
            logger.exception(
                "external identity resolver %s failed",
                getattr(resolver, "__qualname__", repr(resolver)),
            )
            continue
        if identity and identity.sender_id:
            return identity
    return None
```

- [ ] **Step 4: 改 `AuthMiddleware.dispatch`**

替换 `auth.py:759-788` 的 `dispatch` 主体为（删掉本地 `verify_token` 分支）：

```python
    async def dispatch(
        self,
        request: Request,
        call_next,
    ) -> Response:
        """Resolve identity via external providers on protected API routes."""
        if self._should_skip_auth(request):
            return await call_next(request)

        identity = await _resolve_external_identity(request)
        if identity is None:
            token = self._extract_token(request)
            detail = (
                "Invalid or expired token" if token else "Not authenticated"
            )
            return Response(
                content=json.dumps({"detail": detail}),
                status_code=401,
                media_type="application/json",
            )

        request.state.user = identity.sender_id
        request.state.user_roles = identity.roles
        return await call_next(request)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `pytest tests/unit/app/test_auth_middleware.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/qwenpaw/app/auth.py tests/unit/app/test_auth_middleware.py
git commit -m "refactor(auth): middleware resolves external identity+roles only"
```

---

### Task 2.2: `_should_skip_auth` fail-closed 兜底

**Files:**
- Modify: `src/qwenpaw/app/auth.py`（`_should_skip_auth` 790-824）
- Test: `tests/unit/app/test_auth_middleware.py`（追加）

- [ ] **Step 1: 写失败测试** — 追加到 `tests/unit/app/test_auth_middleware.py`

```python
def test_auth_enabled_without_resolver_fails_closed(monkeypatch):
    # auth on, but NO external resolver registered (plugin failed to load):
    # every /api/ route must be denied, never fail-open.
    monkeypatch.setenv("QWENPAW_AUTH_ENABLED", "true")
    client = TestClient(_app())
    resp = client.get("/api/whoami")
    assert resp.status_code == 401
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/app/test_auth_middleware.py::test_auth_enabled_without_resolver_fails_closed -v`
Expected: FAIL — 旧 bootstrap 逃逸在「无 resolver」时 `return True`（skip）→ 200。

- [ ] **Step 3: 改 `_should_skip_auth`**

替换 790-824 的方法体为（删掉「无本地用户」bootstrap 逃逸；新增无 resolver → 不 skip）：

```python
    @staticmethod
    def _should_skip_auth(request: Request) -> bool:
        """Return ``True`` when the request does not require auth."""
        if not is_auth_enabled():
            return True

        path = request.url.path

        if request.method == "OPTIONS":
            return True

        if path in _PUBLIC_PATHS or any(
            path.startswith(p) for p in _PUBLIC_PREFIXES
        ):
            return True

        # Only protect /api/ routes.
        if not path.startswith("/api/"):
            return True

        # Explicit escape hatch (default empty): loopback/LAN hosts.
        client_host = resolve_client_ip(request)
        config = _get_config_cached()
        allowed_hosts = config.security.allow_no_auth_hosts
        if client_host in allowed_hosts:
            return True

        # Fail closed: auth is on and no external provider is registered
        # (plugin missing / failed to load). Deny rather than fall open.
        # dispatch() then returns 401 because _resolve_external_identity
        # yields None. We log once at WARNING for operability.
        if not has_external_identity_resolvers():
            logger.warning(
                "Auth enabled but no external identity resolver registered; "
                "denying %s (fail-closed)",
                path,
            )
        return False
```

> 说明：登录/注册页仍在 `_PUBLIC_PATHS`；`/api/auth/register` 会在 Task 2.3 从 `_PUBLIC_PATHS` 移除。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/unit/app/test_auth_middleware.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/qwenpaw/app/auth.py tests/unit/app/test_auth_middleware.py
git commit -m "fix(auth): fail closed when auth enabled but no resolver registered"
```

---

### Task 2.3: 删除本地账户实现与端点

**Files:**
- Modify: `src/qwenpaw/app/auth.py`（删除本地账户函数）
- Modify: `src/qwenpaw/app/routers/auth.py`（删端点、改 login/status/verify）
- Modify: `src/qwenpaw/app/_app.py`（删 `auto_register_from_env`）
- Modify: `src/qwenpaw/cli/doctor_cmd.py`（`_check_web_auth` 去 `has_registered_users`）
- Test: `tests/unit/app/test_auth_login_route.py`（现有，需重写）

- [ ] **Step 1: 写/改失败测试** — 重写 `tests/unit/app/test_auth_login_route.py` 关键用例

```python
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import qwenpaw.app.auth as auth
from qwenpaw.app.auth import ExternalLogin
from qwenpaw.app.routers.auth import router


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setenv("QWENPAW_AUTH_ENABLED", "true")
    auth._external_login_authenticators.clear()
    auth._external_identity_resolvers.clear()
    yield
    auth._external_login_authenticators.clear()
    auth._external_identity_resolvers.clear()


def _client():
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return AsyncClient(
        transport=ASGITransport(app=app), base_url="http://t"
    )


@pytest.mark.asyncio
async def test_login_uses_external_authenticator():
    async def authn(username, password):
        return ExternalLogin(identity="u@x.io", token="nb-jwt")

    auth.register_external_login_authenticator(authn)
    async with _client() as c:
        resp = await c.post(
            "/api/auth/login", json={"username": "u", "password": "p"}
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token"] == "nb-jwt"
    assert body["username"] == "u@x.io"


@pytest.mark.asyncio
async def test_register_route_removed():
    async with _client() as c:
        resp = await c.post(
            "/api/auth/register", json={"username": "u", "password": "p"}
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_status_reports_nocobase_mode():
    async with _client() as c:
        resp = await c.get("/api/auth/status")
    assert resp.status_code == 200
    assert resp.json() == {"enabled": True, "mode": "nocobase"}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/app/test_auth_login_route.py -v`
Expected: FAIL — register 仍存在；status 返回 `has_users`。

- [ ] **Step 3: 删 `auth.py` 本地账户函数**

从 `src/qwenpaw/app/auth.py` 删除以下定义（连同其 section 注释）：
- `_hash_password`、`verify_password`（242-256）
- `_get_jwt_secret`、`create_token`、`verify_token`（264-347）
- `_load_auth_data`、`_save_auth_data`（355-402）
- 撤销名单：`_is_token_revoked`、`_add_to_revocation_list`、`_clean_expired_revocations`（410-475 区间全部）
- `has_registered_users`（490-493）
- `register_user`（501-534）、`auto_register_from_env`（537-566）、`update_credentials`（569-610）、`authenticate`（618-644）、`revoke_token`（647-681）、`revoke_all_tokens`（684-708）

保留：`ResolvedIdentity`、外部 resolver/authenticator 注册表与 `authenticate_external_login`、`_resolve_external_identity`、`resolve_external_identity` 别名、`_chmod_best_effort`/`_prepare_secret_parent`（若无其它引用可一并删）、`is_auth_enabled`、`_resolve_client_ip`/`resolve_client_ip`、`_get_config_cached`、`AuthMiddleware`。

顶部清理不再使用的 import：`hashlib`、`hmac`、`secrets`、`time`、`AUTH_SECRET_FIELDS`/`decrypt_dict_fields`/`encrypt_dict_fields`/`is_encrypted`、`SECRET_DIR`、`AUTH_FILE` 常量、`TOKEN_EXPIRY_*` 常量。（`json` 仍用于中间件 401 响应，保留。）

从 `_PUBLIC_PATHS` 移除 `"/api/auth/register"`。

> 用 grep 复核无悬空引用：`grep -rn "verify_token\|create_token\|register_user\|update_credentials\|revoke_token\|revoke_all_tokens\|has_registered_users\|auto_register_from_env\|authenticate\b" src plugins --include=*.py`（仅应命中已改写处）。

- [ ] **Step 4: 改 `routers/auth.py`**

- import 改为仅保留在用符号：
  ```python
  from ..auth import (
      ExternalLoginDenied,
      authenticate_external_login,
      is_auth_enabled,
      resolve_external_identity,
      resolve_client_ip,
  )
  ```
- `login`：删掉本地 `authenticate(...)` 一步与本地 `create_token` fallback，直接走外部：

  ```python
      # Attempt authentication via the external provider (NocoBase).
      try:
          external_login = await authenticate_external_login(
              req.username,
              req.password,
          )
      except ExternalLoginDenied as exc:
          rate_limiter.record_login_attempt(
              client_ip, req.username, success=False
          )
          raise HTTPException(status_code=403, detail=exc.detail) from exc

      if not external_login or not external_login.token:
          rate_limiter.record_login_attempt(
              client_ip, req.username, success=False
          )
          raise HTTPException(
              status_code=401, detail="Invalid username or password"
          )

      rate_limiter.record_login_attempt(
          client_ip, req.username, success=True
      )
      return LoginResponse(
          token=external_login.token, username=external_login.identity
      )
  ```
  （保留前面 `is_auth_enabled` 短路与 rate-limit 检查不变。）
- 删除 `register`、`update_profile`、`revoke_single_token`、`revoke_all_sessions` 四个路由及其请求模型 `RegisterRequest`、`UpdateProfileRequest`、`RevokeTokenRequest`。
- `AuthStatusResponse` 改为：
  ```python
  class AuthStatusResponse(BaseModel):
      enabled: bool
      mode: str
  ```
- `auth_status` 改为：
  ```python
  @router.get("/status")
  async def auth_status():
      """Report auth mode. Users are owned by the external provider."""
      return AuthStatusResponse(
          enabled=is_auth_enabled(), mode="nocobase"
      )
  ```
- `verify` 改为用 `resolve_external_identity` 且读 `.sender_id`：
  ```python
  @router.get("/verify")
  async def verify(request: Request):
      """Verify that the caller's external token is still valid."""
      if not is_auth_enabled():
          return {"valid": True, "username": ""}
      identity = await resolve_external_identity(request)
      if identity is None:
          raise HTTPException(
              status_code=401, detail="Invalid or expired token"
          )
      return {"valid": True, "username": identity.sender_id}
  ```

- [ ] **Step 5: 改 `_app.py` 与 `doctor_cmd.py`**

- `src/qwenpaw/app/_app.py`：删第 36 行 import 里的 `auto_register_from_env`，删第 182 行 `auto_register_from_env()` 调用。
- `src/qwenpaw/cli/doctor_cmd.py`：`_check_web_auth`（211 起）去掉 `has_registered_users` 分支。改为：
  ```python
  def _check_web_auth(base: str) -> tuple[bool, str]:
      if not is_auth_enabled():
          return True, "disabled (default) — open the console without logging in"
      return (
          True,
          "enabled — sign in with your NocoBase account. Configure the "
          "NocoBase connection via QWENPAW_NOCOBASE_BASE_URL / "
          "QWENPAW_NOCOBASE_API_TOKEN or the console settings page.",
      )
  ```
  并把第 19 行 import 改为 `from ..app.auth import is_auth_enabled`（去掉 `has_registered_users`）。

- [ ] **Step 6: 跑相关测试**

Run: `pytest tests/unit/app/test_auth_login_route.py tests/unit/app -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/qwenpaw/app/auth.py src/qwenpaw/app/routers/auth.py src/qwenpaw/app/_app.py src/qwenpaw/cli/doctor_cmd.py tests/unit/app/test_auth_login_route.py
git commit -m "feat(auth)!: remove local account; NocoBase owns users end-to-end"
```

---

### Task 2.4: `console.py` 注入 `acl_roles`

**Files:**
- Modify: `src/qwenpaw/app/routers/console.py`（`_extract_session_and_payload` 103-162；`post_console_chat` 216-221）
- Test: `tests/unit/routers/test_console_placeholder.py` 同目录新增 `tests/unit/routers/test_console_acl_roles.py`

- [ ] **Step 1: 写失败测试** — 创建 `tests/unit/routers/test_console_acl_roles.py`

```python
from qwenpaw.app.routers.console import _extract_session_and_payload


def test_acl_roles_injected_into_meta():
    payload = _extract_session_and_payload(
        {"user_id": "x", "session_id": "s", "input": []},
        acl_sender_id="u@x.io",
        acl_roles=["admin", "member"],
    )
    assert payload["acl_sender_id"] == "u@x.io"
    assert payload["meta"]["acl_sender_id"] == "u@x.io"
    assert payload["meta"]["acl_roles"] == ["admin", "member"]


def test_no_roles_defaults_absent_or_empty():
    payload = _extract_session_and_payload(
        {"user_id": "x", "session_id": "s", "input": []},
        acl_sender_id="u@x.io",
    )
    assert payload["meta"].get("acl_roles", []) == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/routers/test_console_acl_roles.py -v`
Expected: FAIL — `_extract_session_and_payload` 无 `acl_roles` 参数。

- [ ] **Step 3: 改 `_extract_session_and_payload` 签名与注入**

- 函数签名（105 行）改为：
  ```python
  def _extract_session_and_payload(
      request_data: Union[AgentRequest, dict],
      acl_sender_id: str = "",
      acl_roles: Optional[list] = None,
  ):
  ```
  （确保文件已 `from typing import Optional`；若未导入则补上。）
- 在末尾注入块（当前 159-162）改为：
  ```python
      if acl_sender_id:
          native_payload["acl_sender_id"] = acl_sender_id
          meta["acl_sender_id"] = acl_sender_id
      if acl_roles:
          meta["acl_roles"] = list(acl_roles)
      return native_payload
  ```

- [ ] **Step 4: 在 `post_console_chat` 读取并传入角色**

`console.py:216-221` 改为：

```python
    acl_sender_id = getattr(request.state, "user", "") or ""
    acl_roles = getattr(request.state, "user_roles", None) or []
    try:
        native_payload = _extract_session_and_payload(
            request_data,
            acl_sender_id=acl_sender_id,
            acl_roles=acl_roles,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
```

> 复核：若 console 还有其它调用 `_extract_session_and_payload` 的地方（如 WebSocket / reconnect handler），一并补 `acl_roles=getattr(request.state, "user_roles", None) or []`。用 `grep -n "_extract_session_and_payload" src/qwenpaw/app/routers/console.py` 检查全部调用点。

- [ ] **Step 5: 跑测试确认通过**

Run: `pytest tests/unit/routers/test_console_acl_roles.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/qwenpaw/app/routers/console.py tests/unit/routers/test_console_acl_roles.py
git commit -m "feat(console): inject acl_roles from resolved identity for the gate"
```

---

### Task 2.5: 更新 console SSO 门禁集成测试

**Files:**
- Modify: `tests/unit/channels/test_console_sso_gate.py`
- Modify: `tests/integration/test_auth_real.py`（若断言本地注册/登录，改为外部登录 mock）

- [ ] **Step 1: 更新门禁测试** — 打开 `tests/unit/channels/test_console_sso_gate.py`

- 把「注册一个 checker，基于 `is_known_user` 判定」的旧构造，改为按 Task 1.6 的 `build_checker(get_config, is_enabled)` 构造，并通过 `payload["meta"]["acl_roles"]` 提供角色。
- 保留「有 `acl_sender_id` 才门禁、无身份 fail-closed 拒」的行为断言。

- [ ] **Step 2: 跑测试**

Run: `pytest tests/unit/channels/test_console_sso_gate.py tests/integration/test_auth_real.py -v`
Expected: PASS（integration 若需真实后端，按 `@pytest.mark.integration` 跳过）

- [ ] **Step 3: Commit**

```bash
git add tests/unit/channels/test_console_sso_gate.py tests/integration/test_auth_real.py
git commit -m "test: update console SSO gate tests for live-role gating"
```

---

## Stage 3 — Bootstrap（环境变量种子化 NocoBase 配置）

> 本阶段结束后：`nocobase_auth_config.json` 缺失/为空时从 `QWENPAW_NOCOBASE_*` 种子化，容器开机即接好 NocoBase；已存在配置不被覆盖。

### Task 3.1: `NocoBaseAuthConfig.seed_from_env`

**Files:**
- Modify: `plugins/bundle/nocobase_auth/config.py`
- Test: `tests/unit/plugins/test_config_seed.py`（新建）

- [ ] **Step 1: 写失败测试** — 创建 `tests/unit/plugins/test_config_seed.py`

```python
import json

from nocobase_auth.config import NocoBaseAuthConfig


def test_seed_from_env_writes_when_missing(tmp_path, monkeypatch):
    target = tmp_path / "nocobase_auth_config.json"
    monkeypatch.setenv("QWENPAW_NOCOBASE_ENABLED", "true")
    monkeypatch.setenv("QWENPAW_NOCOBASE_BASE_URL", "http://nb.local")
    monkeypatch.setenv("QWENPAW_NOCOBASE_API_TOKEN", "admin-tok")
    monkeypatch.setenv("QWENPAW_NOCOBASE_USER_ID_FIELD", "email")

    NocoBaseAuthConfig.seed_from_env(path=target)

    assert target.exists()
    cfg = NocoBaseAuthConfig.load(path=target)
    assert cfg.enabled is True
    assert cfg.base_url == "http://nb.local"
    assert cfg.api_token == "admin-tok"  # decrypted on load


def test_seed_from_env_does_not_overwrite_existing(tmp_path, monkeypatch):
    target = tmp_path / "nocobase_auth_config.json"
    NocoBaseAuthConfig(
        enabled=True, base_url="http://existing", api_token="keep"
    ).save(path=target)

    monkeypatch.setenv("QWENPAW_NOCOBASE_BASE_URL", "http://override")
    NocoBaseAuthConfig.seed_from_env(path=target)

    cfg = NocoBaseAuthConfig.load(path=target)
    assert cfg.base_url == "http://existing"


def test_seed_from_env_noop_when_no_vars(tmp_path, monkeypatch):
    target = tmp_path / "nocobase_auth_config.json"
    for var in (
        "QWENPAW_NOCOBASE_ENABLED",
        "QWENPAW_NOCOBASE_BASE_URL",
        "QWENPAW_NOCOBASE_API_TOKEN",
    ):
        monkeypatch.delenv(var, raising=False)
    NocoBaseAuthConfig.seed_from_env(path=target)
    assert not target.exists()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/plugins/test_config_seed.py -v`
Expected: FAIL — 无 `seed_from_env`。

- [ ] **Step 3: 实现 `seed_from_env`** — 在 `config.py` 的 `NocoBaseAuthConfig` 内、`save` 之后追加

```python
    @classmethod
    def seed_from_env(cls, path: Optional[Path] = None) -> bool:
        """First-run bootstrap: write config from ``QWENPAW_NOCOBASE_*``.

        No-op when the config file already exists (admin edits win) or when no
        relevant env vars are set. Returns True when a file was written.
        """
        target = path or WORKING_DIR / CONFIG_FILE
        if target.exists():
            return False

        base_url = os.getenv("QWENPAW_NOCOBASE_BASE_URL", "").strip()
        api_token = os.getenv("QWENPAW_NOCOBASE_API_TOKEN", "").strip()
        enabled_raw = os.getenv("QWENPAW_NOCOBASE_ENABLED", "").strip().lower()
        user_id_field = os.getenv(
            "QWENPAW_NOCOBASE_USER_ID_FIELD", ""
        ).strip()
        authenticator = os.getenv(
            "QWENPAW_NOCOBASE_AUTHENTICATOR", ""
        ).strip()

        if not any([base_url, api_token, enabled_raw]):
            return False

        cfg = cls(
            enabled=enabled_raw in ("true", "1", "yes"),
            base_url=base_url,
            api_token=api_token,
            user_id_field=user_id_field or "email",
            authenticator=authenticator or "basic",
        )
        cfg.save(path=target)
        logger.info("Seeded NocoBase auth config from environment")
        return True
```

（确保 `config.py` 顶部已 `import os` —— 现有文件已导入。）

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/unit/plugins/test_config_seed.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add plugins/bundle/nocobase_auth/config.py tests/unit/plugins/test_config_seed.py
git commit -m "feat(nocobase): seed connection config from env on first run"
```

> `plugin.py` 的 `_on_startup` 已在 Task 1.9 Step 1 调用 `NocoBaseAuthConfig.seed_from_env()`（无参 → 默认 `WORKING_DIR` 路径）。确认该调用在 `NocoBaseEngine()` 构造之前，使引擎加载到刚种子化的配置。

---

## Stage 4 — 前端（去注册/去改密 + 状态契约）

> 本阶段结束后：登录页仅登录；侧栏无改密入口；`auth.ts` 契约与后端一致。

### Task 4.1: `auth.ts` 去 register/updateProfile + 状态契约

**Files:**
- Modify: `console/src/api/modules/auth.ts`
- Test: `console/src/api/modules/auth.test.ts`

- [ ] **Step 1: 改 `auth.test.ts`** — 删除 `register`/`update-profile` 用例；保留/调整 `login`、`getStatus` 用例；新增 status 形状断言：

```ts
it("getStatus returns enabled + mode", async () => {
  (global.fetch as unknown as vi.Mock).mockResolvedValueOnce({
    ok: true,
    json: async () => ({ enabled: true, mode: "nocobase" }),
  });
  const res = await authApi.getStatus();
  expect(res).toEqual({ enabled: true, mode: "nocobase" });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd console && npx vitest run src/api/modules/auth.test.ts`
Expected: FAIL — `register`/`updateProfile` 仍被引用；`AuthStatusResponse` 含 `has_users`。

- [ ] **Step 3: 改 `auth.ts`**

- `AuthStatusResponse` 改为：
  ```ts
  export interface AuthStatusResponse {
    enabled: boolean;
    mode?: string;
  }
  ```
- 删除 `register` 与 `updateProfile` 方法，`authApi` 仅保留 `login` 与 `getStatus`。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd console && npx vitest run src/api/modules/auth.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add console/src/api/modules/auth.ts console/src/api/modules/auth.test.ts
git commit -m "feat(console): drop register/updateProfile from auth API client"
```

---

### Task 4.2: 登录页去注册分支

**Files:**
- Modify: `console/src/pages/Login/index.tsx`

- [ ] **Step 1: 简化登录页** — 编辑 `Login/index.tsx`

- 删除 `isRegister`、`hasUsers` state 与所有分支。
- `useEffect` 里 `getStatus` 仅用于「未启用 auth → 跳 /chat」；删除 `setHasUsers`/`setIsRegister`。
- `onFinish` 只保留 `authApi.login(...)` 分支；标题/按钮文案固定为登录（`t("login.title")` / `t("login.submit")`）。
- 删除对 `authApi.register` 的调用与 `login.register*` 文案引用（i18n 键保留不清理即可，未用不报错）。

- [ ] **Step 2: 类型检查 + 构建**

Run: `cd console && npm run format && npx tsc --noEmit`
Expected: 无类型错误（`register` 已从 `authApi` 移除，登录页不再引用）。

- [ ] **Step 3: Commit**

```bash
git add console/src/pages/Login/index.tsx
git commit -m "feat(console): login page is sign-in only (NocoBase owns accounts)"
```

---

### Task 4.3: 侧栏去改密入口

**Files:**
- Modify: `console/src/layouts/Sidebar.tsx`（167、361 附近使用 `authApi`）

- [ ] **Step 1: 移除改密 UI** — 编辑 `Sidebar.tsx`

- 删除调用 `authApi.updateProfile(...)`（约 361 行）的「修改用户名/密码」菜单项/弹窗及其处理函数与相关 state。
- 若 167 行处使用 `authApi`（如登出/verify），保留；仅移除 `updateProfile` 相关部分。
- 移除对应 i18n 文案引用（键可保留）。

- [ ] **Step 2: 类型检查**

Run: `cd console && npm run format && npx tsc --noEmit`
Expected: 无类型错误（`updateProfile` 已从 `authApi` 移除）。

- [ ] **Step 3: 跑前端单测**

Run: `cd console && npm run test:run`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add console/src/layouts/Sidebar.tsx
git commit -m "feat(console): remove password-change UI (managed in NocoBase)"
```

---

## Stage 5 — 清理、全量校验与文档

### Task 5.1: 全量后端测试 + lint 门禁

**Files:** 无新增；跑校验。

- [ ] **Step 1: 后端全量单测**

Run: `pytest tests/unit tests/contract -q`
Expected: PASS（如有个别 integration 需真实后端，用 `-m "not integration"` 或按标记跳过）

- [ ] **Step 2: 悬空引用复核**

Run:
```bash
grep -rn "SyncEngine\|permission_store\|is_known_user\|update_from_sync\|nocobase_permissions\|has_registered_users\|verify_token\|create_token\|register_user\|revoke_token\|auto_register_from_env" src plugins tests --include=*.py | grep -v "/test_"
```
Expected: 仅剩文档/迁移说明类命中；无生产代码引用。发现残留则修复。

- [ ] **Step 3: lint**

Run: `pre-commit run --all-files`
Expected: 全绿；若钩子改文件，`git add` 后重跑至干净。

- [ ] **Step 4: Commit（若 lint 有自动修复）**

```bash
git add -A
git commit -m "chore: satisfy lint after NocoBase-sole-authority refactor"
```

---

### Task 5.2: 文档与遗留文件说明

**Files:**
- Modify: `website/public/docs/*`（NocoBase / 认证相关页；若无则新建一节）
- Modify: `plugins/bundle/nocobase_auth/README.md`

- [ ] **Step 1: 更新用户文档**

- 说明：认证由 NocoBase 独占；无本地账户；用 `QWENPAW_NOCOBASE_BASE_URL` / `QWENPAW_NOCOBASE_API_TOKEN`（可选）/ `QWENPAW_NOCOBASE_ENABLED` / `QWENPAW_NOCOBASE_USER_ID_FIELD` / `QWENPAW_NOCOBASE_AUTHENTICATOR` 首次种子化连接。
- 说明：`api_token` 仅用于后台「用户/角色列表」；登录与门禁不依赖它。
- **升级须知（数据清理）：** 升级后 `nocobase_permissions.json` 与 `SECRET_DIR/auth.json` 不再被读取，可手动删除；**不要**删 `access_control.json`、`nocobase_auth_config.json` 与 token 用量数据。系统不会自动删除任何用户数据文件。
- `role_channel_map` 为空时默认放行所有合法 NocoBase 用户；用 denied/allowed 做角色级限制。

- [ ] **Step 2: 更新插件 README**

删除 SyncEngine/webhook/手动 sync 的描述，改为「实时解析 + 60s 缓存」模型。

- [ ] **Step 3: Commit**

```bash
git add website/public/docs plugins/bundle/nocobase_auth/README.md
git commit -m "docs: NocoBase-sole-authority auth model and env-based bootstrap"
```

---

## Self-Review 记录（作者自查，已核对）

- **Spec 覆盖：** §4 组件表 ↔ Stage1-4；§5 数据流 ↔ Task1.4/1.6/2.1/2.4；§6 文件级改动 ↔ 各 Task；§7 bootstrap ↔ Stage3；§8 容错 ↔ Task1.8（列表报错）/Task2.2（fail-closed）/Task1.7（start 自检）；§9 契约 ↔ Task2.3；§10 清理 ↔ Task5.2；§11 测试 ↔ 各 Task 测试步 + Task5.1；§12 风险 ↔ Task1.1 验证注记。
- **类型一致性：** `ResolvedIdentity(sender_id, roles)` 在主包定义（Task1.3），插件解析器（1.4）与中间件（2.1）一致使用；`build_checker(get_config, is_enabled)` 新签名在 1.6 定义、1.9 调用一致；`NocoBaseEngine` 方法名（verify_user_token / authenticate_credentials / list_users / list_roles / test_connection / update_config / start / stop）在 1.7 定义、1.8/1.9 调用一致；`get_engine/set_engine` 命名一致。
- **占位符扫描：** 无 TBD/TODO；每个改动步给出完整代码或精确删除清单与 grep 复核。
- **已知外部依赖风险：** Task1.1 的 `auth:check?appends=roles` 需真实环境验证（spec §12.1）；已在计划中标注「验证失败则暂停汇报」。
