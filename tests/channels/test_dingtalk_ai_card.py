# -*- coding: utf-8 -*-

import json

import pytest

from copaw.app.channels.dingtalk.ai_card import (
    AICardPendingStore,
    ActiveAICard,
    INPUTING,
    thinking_or_tool_to_card_text,
)
from copaw.app.channels.dingtalk.channel import DingTalkChannel


class _FakeResponse:
    def __init__(self, status: int, body: str):
        self.status = status
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def text(self):
        return self._body


class _FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.posts = []

    def post(self, url, json=None, headers=None):
        self.posts.append({"url": url, "json": json, "headers": headers})
        return self._responses.pop(0)


async def _noop_process(_request):
    if False:
        yield None


def _build_channel() -> DingTalkChannel:
    return DingTalkChannel(
        process=_noop_process,
        enabled=True,
        client_id="client_id",
        client_secret="client_secret",
        bot_prefix="c哥",
        message_type="card",
        card_template_id="tpl_id",
        card_template_key="content",
        robot_code="robot_code",
    )


def test_thinking_or_tool_to_card_text_truncate_and_quote() -> None:
    text = "a" * 600
    out = thinking_or_tool_to_card_text(text, "🤔 **思考中**")
    assert out.startswith("🤔 **思考中**\n> ")
    assert out.endswith("…")


def test_pending_store_roundtrip(tmp_path) -> None:
    store = AICardPendingStore(tmp_path / "dingtalk-active-cards.json")
    card = ActiveAICard(
        card_instance_id="card_x",
        access_token="t",
        conversation_id="cid1",
        account_id="default",
        store_path=str(tmp_path),
        created_at=1,
        last_updated=2,
        state=INPUTING,
    )
    store.save({"cid1": card})
    loaded = store.load()
    assert len(loaded) == 1
    assert loaded[0]["card_instance_id"] == "card_x"
    data = json.loads((tmp_path / "dingtalk-active-cards.json").read_text())
    assert data["version"] == 1


@pytest.mark.asyncio
async def test_create_ai_card_uses_sender_staff_id_for_dm(monkeypatch) -> None:
    channel = _build_channel()
    channel._http = _FakeSession(
        [
            _FakeResponse(200, '{"success":true}'),
            _FakeResponse(200, '{"result":[{"spaceId":"staff123","spaceType":"IM_ROBOT","success":true}],"success":true}'),
        ]
    )

    async def _fake_get_access_token():
        return "token"

    monkeypatch.setattr(channel, "_get_access_token", _fake_get_access_token)

    card = await channel._create_ai_card(
        "cid_single_chat",
        meta={"is_group": False, "sender_staff_id": "staff123"},
        inbound=False,
    )

    assert card is not None
    assert len(channel._http.posts) == 2
    deliver_payload = channel._http.posts[1]["json"]
    assert deliver_payload["openSpaceId"] == "dtv1.card//IM_ROBOT.staff123"
    assert deliver_payload["imRobotOpenDeliverModel"] == {"spaceType": "IM_ROBOT"}


@pytest.mark.asyncio
async def test_create_ai_card_raises_when_deliver_result_fails(monkeypatch) -> None:
    channel = _build_channel()
    channel._http = _FakeSession(
        [
            _FakeResponse(200, '{"success":true}'),
            _FakeResponse(
                200,
                '{"result":[{"spaceId":"cid123","spaceType":"IM_GROUP","success":false,"errorMsg":"chatbot not exist"}],"success":true}',
            ),
        ]
    )

    async def _fake_get_access_token():
        return "token"

    monkeypatch.setattr(channel, "_get_access_token", _fake_get_access_token)

    with pytest.raises(RuntimeError, match="chatbot not exist"):
        await channel._create_ai_card(
            "cid123",
            meta={"is_group": True},
            inbound=False,
        )
