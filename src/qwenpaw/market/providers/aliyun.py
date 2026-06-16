# -*- coding: utf-8 -*-
"""Aliyun AgentExplorer market provider.

REST + V3 ACS3-HMAC-SHA256 signing via `do_request_async`:

    GET /openapi/skills/{skillName}          GetSkillContent
    GET /openapi/skills?keyword=&maxResults= SearchSkills
    GET /openapi/categories                  ListCategories

"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any
from urllib.parse import quote

from ..schema import MarketResult
from .base import MARKET_SEARCH_TIMEOUT_S


logger = logging.getLogger(__name__)


_BASE_URL = "https://api.aliyun.com"
_ENDPOINT = os.environ.get(
    "ALIYUN_AGENTEXPLORER_ENDPOINT",
    "agentexplorer.aliyuncs.com",
)
_API_VERSION = "2026-03-17"
_DETAIL_HOMEPAGE = f"{_BASE_URL}/agentexplorer/skills"

# Aliyun SearchSkills is cursor-paginated: each response returns a batch of
# up to `maxResults` items plus a `nextToken` string (null when exhausted).
# To translate to the page-based contract used by the market service, we
# walk tokens forward from page 1 to the caller's page. Each walk step is
# one signed HTTP round-trip, so `_MAX_PAGE_WALK` caps the worst-case cost.
_UPSTREAM_PAGE_SIZE = 100
_MAX_PAGE_WALK = 50

_CRED_ENV_KEYS = (
    "ALIBABA_CLOUD_ACCESS_KEY_ID",
    "ALIBABA_CLOUD_ACCESS_KEY_SECRET",
)


# ─── Lazy SDK client (cached, thread-safe) ───────────────────────────────


_client_lock = threading.Lock()
_client_cache: Any | None = None


def _build_client() -> Any:
    """Construct the tea_openapi Client."""
    import signal as _signal

    from alibabacloud_credentials.client import Client as CredentialClient
    from alibabacloud_tea_openapi.client import Client as OpenApiClient
    from alibabacloud_tea_openapi import models as open_api_models

    prev_int = _signal.getsignal(_signal.SIGINT)
    prev_term = _signal.getsignal(_signal.SIGTERM)
    try:
        config = open_api_models.Config(credential=CredentialClient())
        config.endpoint = _ENDPOINT
        config.signature_algorithm = "ACS3-HMAC-SHA256"
        return OpenApiClient(config)
    finally:
        _signal.signal(_signal.SIGINT, prev_int)
        _signal.signal(_signal.SIGTERM, prev_term)


def _get_client() -> Any:
    global _client_cache
    if _client_cache is not None:
        return _client_cache
    with _client_lock:
        if _client_cache is None:
            _client_cache = _build_client()
        return _client_cache


def _unwrap(resp: Any) -> Any:
    """tea_openapi returns {"body": <parsed>, "headers": ..., "statusCode"}."""
    if isinstance(resp, dict) and "body" in resp:
        return resp["body"]
    return resp


def _make_params(action: str, pathname: str, method: str) -> Any:
    from alibabacloud_tea_openapi.utils_models._params import Params

    return Params(
        action=action,
        version=_API_VERSION,
        protocol="HTTPS",
        pathname=pathname,
        method=method,
        auth_type="AK",
        style="ROA",
        req_body_type="json",
        body_type="json",
    )


def _build_runtime(timeout_s: float | None) -> Any:
    from alibabacloud_tea_util import models as util_models

    if timeout_s is None:
        return util_models.RuntimeOptions()
    ms = max(1, int(timeout_s * 1000))
    return util_models.RuntimeOptions(
        connect_timeout=ms,
        read_timeout=ms,
    )


async def call_aliyun_action_async(
    *,
    action: str,
    pathname: str,
    method: str = "GET",
    query: dict[str, Any] | None = None,
    timeout_s: float | None = None,
) -> Any:
    from alibabacloud_tea_openapi import models as open_api_models

    runtime = _build_runtime(timeout_s)
    request = open_api_models.OpenApiRequest(query=_string_query(query or {}))
    resp = await _get_client().do_request_async(
        _make_params(action, pathname, method),
        request,
        runtime,
    )
    return _unwrap(resp)


def call_aliyun_action(
    *,
    action: str,
    pathname: str,
    method: str = "GET",
    query: dict[str, Any] | None = None,
    timeout_s: float | None = None,
) -> Any:
    from alibabacloud_tea_openapi import models as open_api_models

    runtime = _build_runtime(timeout_s)
    request = open_api_models.OpenApiRequest(query=_string_query(query or {}))
    resp = _get_client().do_request(
        _make_params(action, pathname, method),
        request,
        runtime,
    )
    return _unwrap(resp)


def _string_query(body: dict[str, Any]) -> dict[str, str]:
    return {k: str(v) for k, v in body.items() if v is not None}


class AliyunProvider:
    key = "aliyun"
    label = "Aliyun"
    supports_browse = True

    def available(self) -> tuple[bool, str | None]:
        missing = [k for k in _CRED_ENV_KEYS if not os.environ.get(k)]
        if missing:
            return False, (
                f"missing env vars: {', '.join(missing)} "
                "(set Aliyun AK/SK so the SDK can sign requests)"
            )
        for mod in (
            "alibabacloud_tea_openapi",
            "alibabacloud_credentials",
            "alibabacloud_tea_util",
        ):
            try:
                __import__(mod)
            except ImportError:
                return False, (
                    f"{mod.replace('_', '-')} not installed; run "
                    "`uv add alibabacloud-tea-openapi "
                    "alibabacloud-credentials alibabacloud-tea-util`"
                )
        return True, None

    async def search(
        self,
        query: str,
        limit: int,
        page: int,
    ) -> tuple[list[MarketResult], bool, int | None]:
        if int(page) > _MAX_PAGE_WALK:
            return [], False, None
        max_results = max(1, min(limit, _UPSTREAM_PAGE_SIZE))
        target_page = max(1, int(page))
        next_token: str | None = None
        target_results: list[MarketResult] = []
        has_more = False
        total: int | None = None

        for current_page in range(1, target_page + 1):
            params: dict[str, Any] = {"maxResults": max_results}
            if query:
                params["keyword"] = query
            if next_token:
                params["nextToken"] = next_token
            try:
                resp_body = await call_aliyun_action_async(
                    action="SearchSkills",
                    pathname="/openapi/skills",
                    method="GET",
                    query=params,
                    timeout_s=MARKET_SEARCH_TIMEOUT_S,
                )
            except ImportError as exc:
                raise RuntimeError(str(exc)) from exc
            except Exception as exc:  # noqa: BLE001
                msg = getattr(exc, "message", None) or str(exc) or repr(exc)
                raise RuntimeError(
                    f"Aliyun SearchSkills failed: {msg}",
                ) from exc

            items = _extract_skill_items(resp_body)
            next_token = _opt_str((resp_body or {}).get("nextToken"))

            if current_page == target_page:
                for item in items:
                    converted = _to_market_result(item)
                    if converted is not None:
                        target_results.append(converted)
                total = _opt_int((resp_body or {}).get("totalCount"))
                has_more = bool(next_token)
                break
            if not next_token:
                # Upstream exhausted before reaching target_page — caller
                # asked for a page past the end.
                break

        return target_results, has_more, total


def _extract_skill_items(body: Any) -> list[dict[str, Any]]:
    if isinstance(body, dict) and isinstance(body.get("data"), list):
        return [v for v in body["data"] if isinstance(v, dict)]
    return []


def _to_market_result(item: dict[str, Any]) -> MarketResult | None:
    skill_name = _str(item.get("skillName"))
    display = _str(item.get("displayName"))
    if not skill_name and not display:
        return None
    slug = skill_name or display
    detail_url = f"{_DETAIL_HOMEPAGE}/{quote(slug, safe='')}"
    stats: dict[str, str | int] = {}
    installs = _opt_int(item.get("installCount"))
    if installs is not None:
        stats["installs"] = installs
    likes = _opt_int(item.get("likeCount"))
    if likes is not None:
        stats["likes"] = likes
    category = _category_label(item)
    if category:
        stats["category"] = category
    updated_at = _opt_str(item.get("updatedAt"))
    if updated_at:
        stats["updated_at"] = updated_at
    # Aliyun SearchSkills response only carries the fields below; the
    # upstream schema has no version/author/iconUrl, so we leave those
    # MarketResult slots null instead of pretending to read them.
    return MarketResult(
        source="aliyun",
        slug=slug,
        name=display or skill_name,
        description=_opt_str(item.get("description")),
        source_url=detail_url,
        version=None,
        author=None,
        icon_url=None,
        stats=stats or None,
    )


def _category_label(item: dict[str, Any]) -> str:
    parent = _str(item.get("categoryName"))
    child = _str(item.get("subCategoryName"))
    if parent and child:
        return f"{parent} / {child}"
    return parent or child


def _str(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _opt_str(value: Any) -> str | None:
    s = _str(value)
    return s or None


def _opt_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


provider = AliyunProvider()
