# -*- coding: utf-8 -*-
"""Unit tests for Feishu QR Code Auth Handler."""
# pylint: disable=redefined-outer-name,protected-access
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


@pytest.fixture
def mock_request():
    """Mock FastAPI Request object."""
    return MagicMock()


@pytest.fixture
def feishu_handler():
    """Create Feishu handler instance."""
    from qwenpaw.app.channels.qrcode_auth_handler import (
        FeishuQRCodeAuthHandler,
    )

    return FeishuQRCodeAuthHandler()


@pytest.fixture
def mock_httpx_client():
    """Create mock httpx.AsyncClient context manager."""

    def _create_mock(responses):
        """Create mock with given responses.

        Args:
            responses: Single response or list of responses for side_effect
        """
        mock_client = MagicMock()
        if isinstance(responses, list):
            mock_client.post = AsyncMock(side_effect=responses)
        else:
            mock_client.post = AsyncMock(return_value=responses)

        mock_async_client = MagicMock()
        mock_async_client.return_value.__aenter__ = AsyncMock(
            return_value=mock_client,
        )
        mock_async_client.return_value.__aexit__ = AsyncMock(return_value=None)
        return mock_async_client

    return _create_mock


def _mock_response(json_data):
    """Create mock HTTP response with JSON data."""
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = json_data
    return response


class TestFeishuQRCodeAuthHandler:
    """Tests for FeishuQRCodeAuthHandler."""

    @pytest.mark.asyncio
    async def test_get_domain_default_feishu(
        self,
        feishu_handler,
        mock_request,
    ):
        """Should default to feishu domain."""
        domain = await feishu_handler._get_domain(mock_request)
        assert domain == "feishu"

    def test_get_accounts_domain(self, feishu_handler):
        """Should return correct accounts domain."""
        assert (
            feishu_handler._get_accounts_domain("feishu")
            == "https://accounts.feishu.cn"
        )
        assert (
            feishu_handler._get_accounts_domain("lark")
            == "https://accounts.larksuite.com"
        )

    @pytest.mark.asyncio
    async def test_fetch_qrcode_success(
        self,
        feishu_handler,
        mock_request,
        mock_httpx_client,
    ):
        """Should successfully fetch QR code."""
        init_resp = _mock_response(
            {"supported_auth_methods": ["client_secret"]},
        )
        begin_resp = _mock_response(
            {
                "device_code": "device_123",
                "verification_uri_complete": "https://example.com/qr?code=abc",
            },
        )

        with patch(
            "httpx.AsyncClient",
            mock_httpx_client([init_resp, begin_resp]),
        ):
            result = await feishu_handler.fetch_qrcode(mock_request)

            assert result.poll_token == "device_123"
            assert "source=QwenPaw" in result.scan_url
            assert "code=abc" in result.scan_url

    @pytest.mark.asyncio
    async def test_fetch_qrcode_unsupported_auth_method(
        self,
        feishu_handler,
        mock_request,
        mock_httpx_client,
    ):
        """Should raise error for unsupported auth methods."""
        init_resp = _mock_response(
            {"supported_auth_methods": ["other_method"]},
        )

        with patch("httpx.AsyncClient", mock_httpx_client(init_resp)):
            with pytest.raises(HTTPException) as exc:
                await feishu_handler.fetch_qrcode(mock_request)

            assert exc.value.status_code == 502
            assert "unsupported auth methods" in str(exc.value.detail)

    @pytest.mark.asyncio
    async def test_fetch_qrcode_missing_device_code(
        self,
        feishu_handler,
        mock_request,
        mock_httpx_client,
    ):
        """Should raise error when device_code is missing."""
        init_resp = _mock_response(
            {"supported_auth_methods": ["client_secret"]},
        )
        begin_resp = _mock_response(
            {"verification_uri_complete": "https://example.com/qr"},
        )

        with patch(
            "httpx.AsyncClient",
            mock_httpx_client([init_resp, begin_resp]),
        ):
            with pytest.raises(HTTPException) as exc:
                await feishu_handler.fetch_qrcode(mock_request)

            assert exc.value.status_code == 502
            assert "missing device_code" in str(exc.value.detail)

    @pytest.mark.asyncio
    async def test_poll_status_success(
        self,
        feishu_handler,
        mock_request,
        mock_httpx_client,
    ):
        """Should return success when credentials are ready."""
        response = _mock_response(
            {
                "client_id": "cli_abc123",
                "client_secret": "secret_xyz789",
                "user_info": {
                    "open_id": "ou_user123",
                    "tenant_brand": "feishu",
                },
            },
        )

        with patch("httpx.AsyncClient", mock_httpx_client(response)):
            result = await feishu_handler.poll_status(
                "device_123",
                mock_request,
            )

            assert result.status == "success"
            assert result.credentials["app_id"] == "cli_abc123"
            assert result.credentials["app_secret"] == "secret_xyz789"
            assert result.credentials["open_id"] == "ou_user123"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "error,expected_status",
        [
            ("authorization_pending", "waiting"),
            ("slow_down", "waiting"),
            ("expired_token", "expired"),
            ("invalid_grant", "expired"),
            ("access_denied", "fail"),
        ],
    )
    async def test_poll_status_errors(
        self,
        feishu_handler,
        mock_request,
        mock_httpx_client,
        error,
        expected_status,
    ):
        """Should handle various error responses correctly."""
        response = _mock_response({"error": error})

        with patch("httpx.AsyncClient", mock_httpx_client(response)):
            result = await feishu_handler.poll_status(
                "device_123",
                mock_request,
            )
            assert result.status == expected_status

    @pytest.mark.asyncio
    async def test_poll_status_network_error(
        self,
        feishu_handler,
        mock_request,
    ):
        """Should raise HTTPException on network error."""
        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=Exception("Network error"))

        mock_async_client = MagicMock()
        mock_async_client.return_value.__aenter__ = AsyncMock(
            return_value=mock_client,
        )
        mock_async_client.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", mock_async_client):
            with pytest.raises(HTTPException) as exc:
                await feishu_handler.poll_status("device_123", mock_request)

            assert exc.value.status_code == 502
            assert "status check failed" in str(exc.value.detail)


class TestQRCodeAuthHandlerRegistry:
    """Tests for the global handler registry."""

    def test_registry_contains_all_channels(self):
        """Should contain handlers for all supported channels."""
        from qwenpaw.app.channels.qrcode_auth_handler import (
            QRCODE_AUTH_HANDLERS,
        )

        expected_channels = {"wechat", "wecom", "dingtalk", "feishu"}
        assert set(QRCODE_AUTH_HANDLERS.keys()) == expected_channels

    def test_registry_handlers_are_correct_type(self):
        """Should contain FeishuQRCodeAuthHandler for feishu."""
        from qwenpaw.app.channels.qrcode_auth_handler import (
            QRCODE_AUTH_HANDLERS,
            FeishuQRCodeAuthHandler,
            QRCodeAuthHandler,
        )

        # All handlers should be QRCodeAuthHandler instances
        for handler in QRCODE_AUTH_HANDLERS.values():
            assert isinstance(handler, QRCodeAuthHandler)

        # Feishu handler should be FeishuQRCodeAuthHandler
        assert isinstance(
            QRCODE_AUTH_HANDLERS["feishu"],
            FeishuQRCodeAuthHandler,
        )
