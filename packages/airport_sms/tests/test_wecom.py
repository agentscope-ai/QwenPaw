"""企业微信通道测试。"""

from __future__ import annotations

from time import perf_counter

import pytest

from airport_sms.channels import (
    AclDenied,
    ChannelSupervisor,
    InboundMessage,
    WeComChannel,
)
from airport_sms.runtime import Runtime


def _channel() -> WeComChannel:
    return WeComChannel(
        Runtime.in_memory(),
        allowed_groups={"g1"},
        site_map={"g1": "site-1"},
    )


def test_runtime_entry_only() -> None:
    ch = _channel()
    events = ch.handle(
        InboundMessage("u", "draft fod", "g1", "site-1")
    )
    assert any(e.get("type") in {"case", "done", "delta"} for e in events)


def test_inbound_creates_draft() -> None:
    ch = _channel()
    events = ch.handle(
        InboundMessage("u", "draft fod", "g1", "site-1")
    )
    assert any(e.get("state") == "draft" for e in events if e.get("type") == "case")


def test_acl_blocks_stranger() -> None:
    ch = _channel()
    with pytest.raises(AclDenied):
        ch.handle(InboundMessage("u", "draft", "stranger", "site-1"))


def test_outbound_on_submit() -> None:
    ch = _channel()
    # 直接模拟 submitted 出站
    from airport_sms.channels.base import OutboundCard

    ch.send(OutboundCard("c1", "submitted", "submitted"))
    assert len(ch.sent) == 1


def test_child_restart() -> None:
    sup = ChannelSupervisor()
    sup.start("wecom")
    sup.kill("wecom")
    child = sup.ensure("wecom")
    assert child.alive is True
    assert child.launches >= 2


def test_host_survives_kill() -> None:
    sup = ChannelSupervisor()
    sup.start("wecom")
    sup.kill("wecom")
    assert sup.host_healthy is True


def test_mention_policy() -> None:
    ch = _channel()
    events = ch.handle(
        InboundMessage("u", "draft", "g1", "site-1", mentioned=False)
    )
    assert events[0]["type"] == "ignored"


def test_image_ocr_path() -> None:
    ch = _channel()
    events = ch.handle(
        InboundMessage(
            "u",
            "photo",
            "g1",
            "site-1",
            media_kind="image",
            media_bytes=b"img",
        )
    )
    assert events


def test_voice_asr_path() -> None:
    ch = _channel()
    events = ch.handle(
        InboundMessage(
            "u",
            "voice",
            "g1",
            "site-1",
            media_kind="voice",
            media_bytes=b"wav",
        )
    )
    assert events


def test_site_isolation() -> None:
    ch = _channel()
    with pytest.raises(AclDenied):
        ch.handle(InboundMessage("u", "draft", "g1", "wrong-site"))


def test_env_filter() -> None:
    sup = ChannelSupervisor()
    env = sup.child_env(
        {"PATH": "/", "OPENAI_API_KEY": "secret", "LANG": "zh"}
    )
    assert "OPENAI_API_KEY" not in env
    assert env["LANG"] == "zh"


def test_50_events_under_2s() -> None:
    ch = _channel()
    start = perf_counter()
    for i in range(50):
        ch.handle(
            InboundMessage(f"u{i}", "draft x", "g1", "site-1")
        )
    assert (perf_counter() - start) < 2
