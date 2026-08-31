# -*- coding: utf-8 -*-
"""Tests for doctor connectivity probe helpers.

Covers _tcp_check, _http_get_ok, and the per-channel probe functions
(mqtt, feishu, dingtalk, qq, telegram, discord, matrix, mattermost,
wechat), which previously had no coverage. Network access is stubbed at
the _tcp_check / _http_get_ok boundary.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from qwenpaw.cli import doctor_connectivity as dc


# ---------------------------------------------------------------------------
# _tcp_check
# ---------------------------------------------------------------------------


class TestTcpCheck:
    def test_success_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            dc.socket,
            "create_connection",
            lambda addr, timeout: MagicMock(
                __enter__=lambda self: self,
                __exit__=lambda *a: False,
            ),
        )
        assert dc._tcp_check("host", 443, 1.0) is None

    def test_failure_returns_error_string(self, monkeypatch):
        def refused(addr, timeout):
            raise OSError("Connection refused")

        monkeypatch.setattr(dc.socket, "create_connection", refused)
        result = dc._tcp_check("host", 443, 1.0)
        assert result == "Connection refused"


# ---------------------------------------------------------------------------
# _http_get_ok
# ---------------------------------------------------------------------------


class TestHttpGetOk:
    def test_ok_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            dc.httpx,
            "get",
            lambda url, **kw: SimpleNamespace(status_code=200),
        )
        assert dc._http_get_ok("https://x", 1.0) is None

    def test_redirect_ok(self, monkeypatch):
        monkeypatch.setattr(
            dc.httpx,
            "get",
            lambda url, **kw: SimpleNamespace(status_code=302),
        )
        assert dc._http_get_ok("https://x", 1.0) is None

    def test_client_error_reported(self, monkeypatch):
        monkeypatch.setattr(
            dc.httpx,
            "get",
            lambda url, **kw: SimpleNamespace(status_code=404),
        )
        assert dc._http_get_ok("https://x", 1.0) == "HTTP 404"

    def test_request_error_reported(self, monkeypatch):
        import httpx

        def boom(url, **kw):
            raise httpx.ConnectError("down")

        monkeypatch.setattr(dc.httpx, "get", boom)
        result = dc._http_get_ok("https://x", 1.0)
        assert "down" in result


# ---------------------------------------------------------------------------
# per-channel probes
# ---------------------------------------------------------------------------


class TestProbeMqtt:
    def test_empty_host_skipped(self):
        cfg = SimpleNamespace(host="  ", port=1883)
        assert dc._probe_mqtt("a1", cfg, 1.0) == []

    def test_tcp_failure_reported(self, monkeypatch):
        monkeypatch.setattr(
            dc,
            "_tcp_check",
            lambda host, port, timeout: "refused",
        )
        cfg = SimpleNamespace(host="broker", port=1883)
        result = dc._probe_mqtt("a1", cfg, 1.0)
        assert len(result) == 1
        assert "mqtt" in result[0]
        assert "refused" in result[0]

    def test_default_port_when_missing(self, monkeypatch):
        seen = {}

        def capture(host, port, timeout):
            seen["port"] = port
            return None

        monkeypatch.setattr(dc, "_tcp_check", capture)
        cfg = SimpleNamespace(host="broker", port=None)
        assert dc._probe_mqtt("a1", cfg, 1.0) == []
        assert seen["port"] == 1883

    def test_success_no_notes(self, monkeypatch):
        monkeypatch.setattr(dc, "_tcp_check", lambda h, p, t: None)
        cfg = SimpleNamespace(host="broker", port=1883)
        assert dc._probe_mqtt("a1", cfg, 1.0) == []


class TestProbeFeishu:
    def test_feishu_domain_default(self, monkeypatch):
        urls = []
        monkeypatch.setattr(
            dc,
            "_http_get_ok",
            lambda url, t: urls.append(url) or None,
        )
        cfg = SimpleNamespace(domain="feishu")
        assert dc._probe_feishu("a1", cfg, 1.0) == []
        assert urls[0].startswith("https://open.feishu.cn")

    def test_lark_domain(self, monkeypatch):
        urls = []
        monkeypatch.setattr(
            dc,
            "_http_get_ok",
            lambda url, t: urls.append(url) or None,
        )
        cfg = SimpleNamespace(domain="lark")
        assert dc._probe_feishu("a1", cfg, 1.0) == []
        assert urls[0].startswith("https://open.larksuite.com")

    def test_unreachable_reported(self, monkeypatch):
        monkeypatch.setattr(dc, "_http_get_ok", lambda url, t: "HTTP 500")
        cfg = SimpleNamespace(domain="feishu")
        result = dc._probe_feishu("a1", cfg, 1.0)
        assert len(result) == 1
        assert "feishu" in result[0]


class TestProbeMatrix:
    def test_empty_homeserver_skipped(self):
        cfg = SimpleNamespace(homeserver="")
        assert dc._probe_matrix("a1", cfg, 1.0) == []

    def test_unreachable_reported(self, monkeypatch):
        monkeypatch.setattr(dc, "_http_get_ok", lambda url, t: "HTTP 503")
        cfg = SimpleNamespace(homeserver="https://hs.example.com")
        result = dc._probe_matrix("a1", cfg, 1.0)
        assert len(result) == 1
        assert "_matrix/client/versions" in result[0]

    def test_reachable_no_notes(self, monkeypatch):
        monkeypatch.setattr(dc, "_http_get_ok", lambda url, t: None)
        cfg = SimpleNamespace(homeserver="https://hs.example.com")
        assert dc._probe_matrix("a1", cfg, 1.0) == []


class TestProbeMattermost:
    def test_empty_url_skipped(self):
        cfg = SimpleNamespace(url="  ")
        assert dc._probe_mattermost("a1", cfg, 1.0) == []

    def test_ping_failure_reported(self, monkeypatch):
        urls = []

        def fail(url, t):
            urls.append(url)
            return "HTTP 404"

        monkeypatch.setattr(dc, "_http_get_ok", fail)
        cfg = SimpleNamespace(url="https://mm.example.com/")
        result = dc._probe_mattermost("a1", cfg, 1.0)
        assert len(result) == 1
        assert urls[0] == "https://mm.example.com/api/v4/system/ping"

    def test_ping_ok_no_notes(self, monkeypatch):
        monkeypatch.setattr(dc, "_http_get_ok", lambda url, t: None)
        cfg = SimpleNamespace(url="https://mm.example.com")
        assert dc._probe_mattermost("a1", cfg, 1.0) == []


class TestProbeWechat:
    def test_custom_base_url_used(self, monkeypatch):
        urls = []
        monkeypatch.setattr(
            dc,
            "_http_get_ok",
            lambda url, t: urls.append(url) or None,
        )
        cfg = SimpleNamespace(base_url="https://wx.internal/")
        assert dc._probe_wechat("a1", cfg, 1.0) == []
        assert urls[0] == "https://wx.internal/"

    def test_default_weixin_api(self, monkeypatch):
        urls = []
        monkeypatch.setattr(
            dc,
            "_http_get_ok",
            lambda url, t: urls.append(url) or None,
        )
        cfg = SimpleNamespace(base_url="")
        assert dc._probe_wechat("a1", cfg, 1.0) == []
        assert urls[0].startswith("https://api.weixin.qq.com")

    def test_failure_reported(self, monkeypatch):
        monkeypatch.setattr(dc, "_http_get_ok", lambda url, t: "HTTP 500")
        cfg = SimpleNamespace(base_url="")
        result = dc._probe_wechat("a1", cfg, 1.0)
        assert len(result) == 1
        assert "wechat" in result[0]


class TestProbeTelegram:
    def test_default_api_url(self, monkeypatch):
        urls = []
        monkeypatch.setattr(
            dc,
            "_http_get_ok",
            lambda url, t: urls.append(url) or None,
        )
        cfg = SimpleNamespace(base_url="")
        assert dc._probe_telegram("a1", cfg, 1.0) == []
        assert urls[0] == "https://api.telegram.org"

    def test_custom_base_url(self, monkeypatch):
        urls = []
        monkeypatch.setattr(
            dc,
            "_http_get_ok",
            lambda url, t: urls.append(url) or None,
        )
        cfg = SimpleNamespace(base_url="https://tg.internal/")
        dc._probe_telegram("a1", cfg, 1.0)
        assert urls[0] == "https://tg.internal"


class TestProbeDingtalk:
    def test_reachable_no_notes(self, monkeypatch):
        monkeypatch.setattr(dc, "_http_get_ok", lambda url, t: None)
        assert dc._probe_dingtalk("a1", SimpleNamespace(), 1.0) == []

    def test_unreachable_reported(self, monkeypatch):
        monkeypatch.setattr(dc, "_http_get_ok", lambda url, t: "HTTP 500")
        result = dc._probe_dingtalk("a1", SimpleNamespace(), 1.0)
        assert len(result) == 1
        assert "dingtalk" in result[0]


class TestProbeDiscord:
    def test_reachable_no_notes(self, monkeypatch):
        monkeypatch.setattr(dc, "_http_get_ok", lambda url, t: None)
        assert dc._probe_discord("a1", None, 1.0) == []

    def test_unreachable_reported(self, monkeypatch):
        monkeypatch.setattr(dc, "_http_get_ok", lambda url, t: "HTTP 500")
        result = dc._probe_discord("a1", None, 1.0)
        assert len(result) == 1
        assert "discord" in result[0]


class TestProbeQq:
    def test_reachable_no_notes(self, monkeypatch):
        monkeypatch.setattr(dc, "_tcp_check", lambda h, p, t: None)
        assert dc._probe_qq("a1", SimpleNamespace(), 1.0) == []

    def test_unreachable_reported(self, monkeypatch):
        monkeypatch.setattr(dc, "_tcp_check", lambda h, p, t: "timeout")
        result = dc._probe_qq("a1", SimpleNamespace(), 1.0)
        assert len(result) == 1
        assert "qq" in result[0]
