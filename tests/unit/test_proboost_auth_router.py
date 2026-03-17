# -*- coding: utf-8 -*-

from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from starlette.requests import Request


MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "src" / "copaw" / "app" / "routers" / "proboost_auth.py"
)


def load_module():
    module_name = f"test_proboost_auth_router_{uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module spec from {MODULE_PATH}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_request(headers: dict[str, str] | None = None) -> Request:
    raw_headers = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in (headers or {}).items()
    ]
    return Request({"type": "http", "headers": raw_headers})


class ProBoostAuthRouterTests(unittest.TestCase):
    def test_router_exposes_expected_paths(self) -> None:
        module = load_module()

        route_paths = {route.path for route in module.router.routes}

        self.assertEqual(
            route_paths,
            {
                "/proboost-auth/login",
                "/proboost-auth/meta",
                "/proboost-auth/send-sms-code",
                "/proboost-auth/verify-sms-code",
            },
        )

    def test_get_proboost_auth_url_normalizes_path(self) -> None:
        module = load_module()

        self.assertEqual(
            module._get_proboost_auth_url("user/auth/login"),
            "https://proboost.microdata-inc.com/pb_api/insight/v3/user/auth/login",
        )
        self.assertEqual(
            module._get_proboost_auth_url("/user/auth/sendSmsCode"),
            "https://proboost.microdata-inc.com/pb_api/insight/v3/user/auth/sendSmsCode",
        )

    def test_build_proboost_headers_uses_request_headers_when_present(self) -> None:
        module = load_module()
        request = make_request(
            {
                "Authorization": "Bearer test-token",
                "language": "ja_JP",
            }
        )

        headers = module._build_proboost_headers(request)

        self.assertEqual(headers["Authorization"], "Bearer test-token")
        self.assertEqual(headers["language"], "zh_CN")
        self.assertEqual(headers["Origin"], "https://proboost.microdata-inc.com")
        self.assertEqual(headers["Referer"], "https://proboost.microdata-inc.com/login")
        self.assertEqual(headers["Content-Type"], "application/json")

    def test_build_proboost_headers_falls_back_to_default_auth(self) -> None:
        module = load_module()
        request = make_request()

        headers = module._build_proboost_headers(request)

        self.assertEqual(headers["Authorization"], "Bearer undefined")
        self.assertEqual(headers["language"], "zh_CN")

    def test_build_proboost_payload_injects_backend_website_id(self) -> None:
        module = load_module()
        payload = module.PasswordLoginPayload(
            countryCode="+81",
            phone="12345678",
            password="secret",
        )

        data = module._build_proboost_payload(payload)

        self.assertEqual(
            data,
            {
                "countryCode": "+81",
                "phone": "12345678",
                "password": "secret",
                "webSiteId": "1",
            },
        )

    def test_build_auth_meta_keeps_default_in_supported_list(self) -> None:
        module = load_module()

        meta = module._build_auth_meta("+39", ["+86", "+1"])

        self.assertEqual(
            meta,
            {
                "defaultCountryCode": "+39",
                "supportedCountryCodes": ["+39", "+86", "+1"],
                "countryCodeOptions": [
                    {"value": "+39", "labelKey": "auth.countryCodeOptions.it"},
                    {"value": "+86", "labelKey": "auth.countryCodeOptions.cn"},
                    {"value": "+1", "labelKey": "auth.countryCodeOptions.us"},
                ],
            },
        )

    def test_get_meta_returns_backend_country_code_defaults(self) -> None:
        module = load_module()

        self.assertEqual(
            module.get_meta(),
            {
                "defaultCountryCode": "+86",
                "supportedCountryCodes": ["+86", "+1", "+81", "+39"],
                "countryCodeOptions": [
                    {"value": "+86", "labelKey": "auth.countryCodeOptions.cn"},
                    {"value": "+1", "labelKey": "auth.countryCodeOptions.us"},
                    {"value": "+81", "labelKey": "auth.countryCodeOptions.jp"},
                    {"value": "+39", "labelKey": "auth.countryCodeOptions.it"},
                ],
            },
        )

    def test_get_meta_normalizes_env_driven_country_codes(self) -> None:
        with patch.dict(
            os.environ,
            {
                "BOOSTCLAW_PROBOOST_DEFAULT_COUNTRY_CODE": "+44",
                "BOOSTCLAW_PROBOOST_SUPPORTED_COUNTRY_CODES": " +44, +86, +44, ",
            },
            clear=False,
        ):
            module = load_module()

        self.assertEqual(
            module.get_meta(),
            {
                "defaultCountryCode": "+44",
                "supportedCountryCodes": ["+44", "+86"],
                "countryCodeOptions": [
                    {"value": "+44"},
                    {"value": "+86", "labelKey": "auth.countryCodeOptions.cn"},
                ],
            },
        )


if __name__ == "__main__":
    unittest.main()

