# -*- coding: utf-8 -*-
"""Proxy ProBoost auth endpoints through the local backend to avoid CORS."""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


DEFAULT_PROBOOST_BASE_URL = "https://proboost.microdata-inc.com"
DEFAULT_PROBOOST_PREFIX = "/pb_api/insight/v3"
DEFAULT_PROBOOST_LANGUAGE = "zh_CN"
DEFAULT_PROBOOST_WEBSITE_ID = "1"
DEFAULT_PROBOOST_DEFAULT_COUNTRY_CODE = "+86"
DEFAULT_PROBOOST_SUPPORTED_COUNTRY_CODES = ["+86", "+1", "+81", "+39"]
DEFAULT_PROBOOST_COUNTRY_CODE_LABEL_KEYS = {
    "+86": "auth.countryCodeOptions.cn",
    "+1": "auth.countryCodeOptions.us",
    "+81": "auth.countryCodeOptions.jp",
    "+39": "auth.countryCodeOptions.it",
}
DEFAULT_PROBOOST_REFERER = "https://proboost.microdata-inc.com/login"
PROBOOST_TIMEOUT = 20.0


def _trim_trailing_slash(value: str) -> str:
    return value.rstrip("/")


def _read_env(suffix: str, fallback: str) -> str:
    for prefix in ("BOOSTCLAW", "COPAW"):
        value = os.getenv(f"{prefix}_{suffix}", "").strip()
        if value:
            return value

    return fallback


def _read_env_list(suffix: str, fallback: list[str]) -> list[str]:
    value = _read_env(suffix, "")
    if not value:
        return fallback.copy()

    return value.split(",")


def _normalize_supported_country_codes(values: list[str]) -> list[str]:
    normalized: list[str] = []

    for value in values:
        next_value = value.strip()
        if next_value and next_value not in normalized:
            normalized.append(next_value)

    return normalized or DEFAULT_PROBOOST_SUPPORTED_COUNTRY_CODES.copy()


def _build_auth_meta(
    default_country_code: str,
    supported_country_codes: list[str],
) -> dict[str, Any]:
    normalized_supported_country_codes = _normalize_supported_country_codes(
        supported_country_codes
    )
    normalized_default_country_code = default_country_code.strip()

    if not normalized_default_country_code:
        normalized_default_country_code = normalized_supported_country_codes[0]

    if normalized_default_country_code not in normalized_supported_country_codes:
        normalized_supported_country_codes = [
            normalized_default_country_code,
            *normalized_supported_country_codes,
        ]

    country_code_options = []
    for country_code in normalized_supported_country_codes:
        option: dict[str, str] = {"value": country_code}
        label_key = DEFAULT_PROBOOST_COUNTRY_CODE_LABEL_KEYS.get(country_code)
        if label_key:
            option["labelKey"] = label_key
        country_code_options.append(option)

    return {
        "defaultCountryCode": normalized_default_country_code,
        "supportedCountryCodes": normalized_supported_country_codes,
        "countryCodeOptions": country_code_options,
    }


PROBOOST_BASE_URL = _trim_trailing_slash(
    _read_env("PROBOOST_AUTH_BASE_URL", DEFAULT_PROBOOST_BASE_URL)
)
PROBOOST_PREFIX = _read_env("PROBOOST_AUTH_PREFIX", DEFAULT_PROBOOST_PREFIX)
PROBOOST_LANGUAGE = _read_env("PROBOOST_LANGUAGE", DEFAULT_PROBOOST_LANGUAGE)
PROBOOST_WEBSITE_ID = _read_env("PROBOOST_WEBSITE_ID", DEFAULT_PROBOOST_WEBSITE_ID)
PROBOOST_ORIGIN = _read_env("PROBOOST_ORIGIN", PROBOOST_BASE_URL)
PROBOOST_REFERER = _read_env("PROBOOST_REFERER", DEFAULT_PROBOOST_REFERER)
PROBOOST_AUTH_META = _build_auth_meta(
    _read_env("PROBOOST_DEFAULT_COUNTRY_CODE", DEFAULT_PROBOOST_DEFAULT_COUNTRY_CODE),
    _read_env_list(
        "PROBOOST_SUPPORTED_COUNTRY_CODES",
        DEFAULT_PROBOOST_SUPPORTED_COUNTRY_CODES,
    ),
)

router = APIRouter(prefix="/proboost-auth", tags=["proboost-auth"])


class PasswordLoginPayload(BaseModel):
    countryCode: str = Field(..., min_length=1)
    phone: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class SendSmsCodePayload(BaseModel):
    countryCode: str = Field(..., min_length=1)
    phone: str = Field(..., min_length=1)
    channelCode: str | None = None
    deepSeekChannelCode: str | None = None


class VerifySmsCodePayload(BaseModel):
    countryCode: str = Field(..., min_length=1)
    phone: str = Field(..., min_length=1)
    smsCode: str = Field(..., min_length=1)
    channelCode: str | None = None
    deepSeekChannelCode: str | None = None


def _get_proboost_auth_url(path: str) -> str:
    normalized_path = path if path.startswith("/") else f"/{path}"
    return f"{PROBOOST_BASE_URL}{PROBOOST_PREFIX}{normalized_path}"


def _build_proboost_headers(request: Request) -> dict[str, str]:
    authorization = request.headers.get("authorization", "").strip()

    # Upstream transport defaults are backend-owned so browser config stays minimal.
    return {
        "Authorization": authorization or "Bearer undefined",
        "Content-Type": "application/json",
        "Origin": PROBOOST_ORIGIN,
        "Referer": PROBOOST_REFERER,
        "language": PROBOOST_LANGUAGE,
    }


def _build_proboost_payload(payload: BaseModel) -> dict[str, Any]:
    data = payload.model_dump(mode="json")
    # `webSiteId` is injected here instead of being supplied by the browser.
    data["webSiteId"] = PROBOOST_WEBSITE_ID
    return data


@router.get("/meta")
def get_meta() -> dict[str, Any]:
    return PROBOOST_AUTH_META


async def _proxy_auth_request(
    request: Request,
    path: str,
    payload: BaseModel,
) -> JSONResponse:
    try:
        async with httpx.AsyncClient(timeout=PROBOOST_TIMEOUT) as client:
            response = await client.post(
                _get_proboost_auth_url(path),
                json=_build_proboost_payload(payload),
                headers=_build_proboost_headers(request),
            )
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=504,
            detail="ProBoost auth request timed out",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to reach ProBoost auth service: {exc}",
        ) from exc

    try:
        data: Any = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail="ProBoost auth service returned invalid JSON",
        ) from exc

    return JSONResponse(status_code=response.status_code, content=data)


@router.post("/login")
async def login(
    payload: PasswordLoginPayload,
    request: Request,
) -> JSONResponse:
    return await _proxy_auth_request(request, "/user/auth/login", payload)


@router.post("/send-sms-code")
async def send_sms_code(
    payload: SendSmsCodePayload,
    request: Request,
) -> JSONResponse:
    return await _proxy_auth_request(request, "/user/auth/sendSmsCode", payload)


@router.post("/verify-sms-code")
async def verify_sms_code(
    payload: VerifySmsCodePayload,
    request: Request,
) -> JSONResponse:
    return await _proxy_auth_request(request, "/user/auth/verifySmsCode", payload)
