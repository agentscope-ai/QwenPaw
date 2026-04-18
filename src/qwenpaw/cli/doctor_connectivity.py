# -*- coding: utf-8 -*-
"""Optional ``--deep`` network reachability checks for enabled channels.

Failures are reported as non-fatal notes (firewalls and offline use are
common). Built-in probes live here; custom channels can override
:class:`~qwenpaw.app.channels.base.BaseChannel`.doctor_connectivity_notes.
"""
from __future__ import annotations

import socket
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

from ..app.channels.registry import get_channel_registry
from ..config.config import (
    ChannelConfig,
    Config,
    DingTalkConfig,
    FeishuConfig,
    MatrixConfig,
    MattermostConfig,
    MQTTConfig,
    OneBotConfig,
    QQConfig,
    TelegramConfig,
    VoiceChannelConfig,
    WecomConfig,
    XiaoYiConfig,
    WeixinConfig,
)
from .doctor_checks import _effective_channels_mcp, _read_workspace_agent_json

ChannelProbe = Callable[[str, Any, float], list[str]]


def _tcp_check(host: str, port: int, timeout: float) -> str | None:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except OSError as exc:
        return str(exc)
    return None


def _http_get_ok(url: str, timeout: float) -> str | None:
    try:
        resp = httpx.get(url, timeout=timeout, follow_redirects=True)
        if resp.status_code >= 400:
            return f"HTTP {resp.status_code}"
    except httpx.RequestError as exc:
        return str(exc)
    return None


def _probe_mqtt(agent_id: str, cfg: MQTTConfig, timeout: float) -> list[str]:
    host = (cfg.host or "").strip()
    if not host:
        return []
    port = int(cfg.port or 1883)
    err = _tcp_check(host, port, timeout)
    if err:
        return [f"{agent_id}: mqtt: TCP {host}:{port} — {err}"]
    return []


def _probe_mattermost(
    agent_id: str,
    cfg: MattermostConfig,
    timeout: float,
) -> list[str]:
    url = (cfg.url or "").strip().rstrip("/")
    if not url:
        return []
    ping = f"{url}/api/v4/system/ping"
    err = _http_get_ok(ping, timeout)
    if err:
        return [f"{agent_id}: mattermost: GET {ping!r} — {err}"]
    return []


def _probe_matrix(
    agent_id: str,
    cfg: MatrixConfig,
    timeout: float,
) -> list[str]:
    hs = (cfg.homeserver or "").strip().rstrip("/")
    if not hs:
        return []
    ver = f"{hs}/_matrix/client/versions"
    err = _http_get_ok(ver, timeout)
    if err:
        return [f"{agent_id}: matrix: GET {ver!r} — {err}"]
    return []


def _probe_telegram(
    agent_id: str,
    _cfg: TelegramConfig,
    timeout: float,
) -> list[str]:
    err = _http_get_ok("https://api.telegram.org", timeout)
    if err:
        return [f"{agent_id}: telegram: reach api.telegram.org — {err}"]
    return []


def _probe_discord(agent_id: str, _cfg: Any, timeout: float) -> list[str]:
    err = _http_get_ok("https://discord.com/api/v10/gateway", timeout)
    if err:
        return [f"{agent_id}: discord: reach discord API — {err}"]
    return []


def _probe_onebot(
    agent_id: str,
    cfg: OneBotConfig,
    timeout: float,
) -> list[str]:
    host = (cfg.ws_host or "127.0.0.1").strip()
    port = int(cfg.ws_port or 6199)
    if host in ("0.0.0.0", ""):
        host = "127.0.0.1"
    err = _tcp_check(host, port, timeout)
    if err:
        return [
            f"{agent_id}: onebot: TCP {host}:{port} — {err} "
            "(is the reverse WebSocket server running?)",
        ]
    return []


def _probe_feishu(
    agent_id: str,
    cfg: FeishuConfig,
    timeout: float,
) -> list[str]:
    base = (
        "https://open.feishu.cn"
        if getattr(cfg, "domain", "feishu") == "feishu"
        else "https://open.larksuite.com"
    )
    err = _http_get_ok(base + "/", timeout)
    if err:
        return [f"{agent_id}: feishu: reach {base} — {err}"]
    return []


def _probe_dingtalk(
    agent_id: str,
    _cfg: DingTalkConfig,
    timeout: float,
) -> list[str]:
    err = _http_get_ok("https://oapi.dingtalk.com/", timeout)
    if err:
        return [f"{agent_id}: dingtalk: reach oapi.dingtalk.com — {err}"]
    return []


def _probe_qq(agent_id: str, _cfg: QQConfig, timeout: float) -> list[str]:
    err = _tcp_check("qq.com", 443, timeout)
    if err:
        return [f"{agent_id}: qq: TCP qq.com:443 — {err}"]
    return []


def _probe_wecom(
    agent_id: str,
    _cfg: WecomConfig,
    timeout: float,
) -> list[str]:
    err = _tcp_check("qyapi.weixin.qq.com", 443, timeout)
    if err:
        return [f"{agent_id}: wecom: TCP qyapi.weixin.qq.com:443 — {err}"]
    return []


def _probe_voice(
    agent_id: str,
    _cfg: VoiceChannelConfig,
    timeout: float,
) -> list[str]:
    err = _http_get_ok("https://api.twilio.com/", timeout)
    if err:
        return [f"{agent_id}: voice (Twilio): reach api.twilio.com — {err}"]
    return []


def _probe_xiaoyi(
    agent_id: str,
    cfg: XiaoYiConfig,
    timeout: float,
) -> list[str]:
    raw = (cfg.ws_url or "").strip()
    if not raw:
        return []
    parsed = urlparse(raw)
    host = parsed.hostname
    if not host:
        return [f"{agent_id}: xiaoyi: could not parse host from ws_url"]
    port = parsed.port or (443 if parsed.scheme in ("wss", "https") else 80)
    err = _tcp_check(host, port, timeout)
    if err:
        return [f"{agent_id}: xiaoyi: TCP {host}:{port} — {err}"]
    return []


def _probe_weixin(
    agent_id: str,
    cfg: WeixinConfig,
    timeout: float,
) -> list[str]:
    base = (cfg.base_url or "").strip().rstrip("/")
    if base:
        err = _http_get_ok(base + "/", timeout)
        if err:
            return [f"{agent_id}: weixin: GET {base!r} — {err}"]
        return []
    err = _http_get_ok("https://api.weixin.qq.com/", timeout)
    if err:
        return [f"{agent_id}: weixin: reach api.weixin.qq.com — {err}"]
    return []


_BUILTIN_PROBES: dict[str, ChannelProbe] = {
    "mqtt": _probe_mqtt,
    "mattermost": _probe_mattermost,
    "matrix": _probe_matrix,
    "telegram": _probe_telegram,
    "discord": _probe_discord,
    "onebot": _probe_onebot,
    "feishu": _probe_feishu,
    "dingtalk": _probe_dingtalk,
    "qq": _probe_qq,
    "wecom": _probe_wecom,
    "voice": _probe_voice,
    "xiaoyi": _probe_xiaoyi,
    "weixin": _probe_weixin,
}


def _channel_enabled(sub: Any) -> bool:
    return bool(getattr(sub, "enabled", False))


# pylint: disable-next=too-many-branches
def collect_deep_channel_connectivity_notes(
    cfg: Config,
    timeout: float,
) -> list[str]:
    """Run reachability probes for each enabled channel (per agent profile)."""
    notes: list[str] = []
    reg = get_channel_registry()

    for agent_id, ref in cfg.agents.profiles.items():
        raw = _read_workspace_agent_json(ref)
        ch, _ = _effective_channels_mcp(cfg, raw)

        for name in ChannelConfig.model_fields:
            sub = getattr(ch, name, None)
            if sub is None or not _channel_enabled(sub):
                continue
            if name == "console":
                continue
            if name == "imessage":
                continue

            cls = reg.get(name)
            custom_lines: list[str] = []
            if cls is not None:
                try:
                    custom_lines = cls.doctor_connectivity_notes(
                        agent_id,
                        sub,
                        timeout=timeout,
                    )
                except (
                    Exception
                ) as exc:  # pylint: disable=broad-exception-caught
                    custom_lines = [
                        f"{agent_id}: {name}: "
                        f"doctor_connectivity_notes error: {exc}",
                    ]
            if custom_lines:
                notes.extend(custom_lines)
                continue

            probe = _BUILTIN_PROBES.get(name)
            if probe is None:
                continue
            try:
                notes.extend(probe(agent_id, sub, timeout))
            except Exception as exc:  # pylint: disable=broad-exception-caught
                notes.append(
                    f"{agent_id}: {name}: connectivity probe error: {exc}",
                )

        extra = getattr(ch, "__pydantic_extra__", None) or {}
        for key, val in extra.items():
            en = False
            if isinstance(val, dict):
                en = bool(val.get("enabled"))
            elif hasattr(val, "enabled"):
                en = bool(getattr(val, "enabled"))
            if not en:
                continue
            cls = reg.get(key)
            if cls is None:
                notes.append(
                    f"{agent_id}: plugin channel {key!r} enabled — "
                    "not in registry; add a BaseChannel subclass "
                    "or skip --deep",
                )
                continue
            try:
                notes.extend(
                    cls.doctor_connectivity_notes(
                        agent_id,
                        val,
                        timeout=timeout,
                    ),
                )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                notes.append(
                    f"{agent_id}: {key}: doctor_connectivity_notes error: "
                    f"{exc}",
                )

    return notes
