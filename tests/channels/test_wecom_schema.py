# -*- coding: utf-8 -*-

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for candidate in (ROOT, SRC):
    path_str = str(candidate)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from copaw.app.channels.wecom.schema import (
    WeComIncomingMessage,
    WeComMediaDescriptor,
    WeComRoute,
    WeComSendTarget,
)


def test_route_model_fields() -> None:
    route = WeComRoute(
        session_id="wecom:user:u1",
        target_type="user",
        target_id="u1",
        chat_type="single",
        last_seen_at=1,
    )

    assert route.target_id == "u1"


def test_schema_models_are_instantiable() -> None:
    incoming = WeComIncomingMessage(
        message_id="m1",
        sender_id="u1",
        chat_type="single",
    )
    target = WeComSendTarget(
        target_type="user",
        target_id="u1",
        raw_handle="wecom:user:u1",
    )
    media = WeComMediaDescriptor(media_type="image", sdk_file_id="f1")

    assert incoming.message_id == "m1"
    assert target.raw_handle == "wecom:user:u1"
    assert media.sdk_file_id == "f1"
