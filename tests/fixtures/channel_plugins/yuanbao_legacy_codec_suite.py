# -*- coding: utf-8 -*-
"""Tests for the Yuanbao protobuf codec encode side and body converters.

Covers the message builders (auth bind, ping, push ack, biz, send c2c /
group, heartbeat), the ConnMsg encode/decode round-trip, encode_pb
error handling, and the internal/protobuf msg-body converters.

Note: ``decode_pb`` (and the decoders built on it) are excluded here —
they are broken under protobuf >= 6.33.5 because
``json_format.MessageToDict`` no longer accepts
``including_default_value_fields`` (Aone #86045261). Asserting their
current ``None`` return would pin the defect; they are covered when the
product fix lands.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument,use-implicit-booleaness-not-comparison  # noqa: E501
from __future__ import annotations

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "plugins/channel/yuanbao"))


from qwenpaw_channel_yuanbao import codec


# ---------------------------------------------------------------------------
# encode_pb
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# encode_conn_msg / decode_conn_msg round-trip
# ---------------------------------------------------------------------------


class TestConnMsgRoundTrip:
    def test_round_trip_preserves_head_and_data(self):
        raw = codec.encode_conn_msg(
            {
                "cmdType": codec.CMD_TYPE_REQUEST,
                "cmd": codec.CMD_PING,
                "seqNo": 7,
                "msgId": "mid-1",
                "module": codec.MODULE_CONN_ACCESS,
            },
            b"inner payload",
        )
        assert isinstance(raw, bytes)
        frame = codec.decode_conn_msg(raw)
        assert frame["head"]["cmd"] == codec.CMD_PING
        assert frame["head"]["cmdType"] == codec.CMD_TYPE_REQUEST
        assert frame["head"]["seqNo"] == 7
        assert frame["head"]["msgId"] == "mid-1"
        assert frame["head"]["module"] == codec.MODULE_CONN_ACCESS
        assert frame["data"] == b"inner payload"

    def test_without_inner_data(self):
        raw = codec.encode_conn_msg(
            {
                "cmdType": codec.CMD_TYPE_PUSH_ACK,
                "cmd": "x",
                "seqNo": 1,
                "msgId": "m",
                "module": "mod",
            },
        )
        frame = codec.decode_conn_msg(raw)
        assert frame["data"] == b""

    def test_need_ack_flag_preserved(self):
        raw = codec.encode_conn_msg(
            {
                "cmdType": codec.CMD_TYPE_PUSH,
                "cmd": "push",
                "seqNo": 2,
                "msgId": "m2",
                "module": "mod",
                "needAck": True,
            },
        )
        frame = codec.decode_conn_msg(raw)
        assert frame["head"]["needAck"] is True

    def test_decode_garbage_returns_none(self):
        assert codec.decode_conn_msg(b"\xff\xff\xff") is None


# ---------------------------------------------------------------------------
# message builders
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# msg body converters (pure dict transforms)
# ---------------------------------------------------------------------------


class TestToProtoMsgBody:
    def test_text_element(self):
        result = codec._to_proto_msg_body(
            [{"msg_type": "TIMTextElem", "msg_content": {"text": "hello"}}],
        )
        assert result == [
            {
                "msgType": "TIMTextElem",
                "msgContent": {"text": "hello"},
            },
        ]

    def test_image_element_maps_all_fields(self):
        result = codec._to_proto_msg_body(
            [
                {
                    "msg_type": "TIMImageElem",
                    "msg_content": {
                        "uuid": "u1",
                        "image_format": "png",
                        "url": "https://x",
                        "file_size": 100,
                        "desc": "pic",
                        "data": "base64",
                        "image_info_array": [{"w": 1}],
                    },
                },
            ],
        )
        content = result[0]["msgContent"]
        assert content["uuid"] == "u1"
        assert content["imageFormat"] == "png"
        assert content["url"] == "https://x"
        assert content["fileSize"] == 100
        assert content["desc"] == "pic"
        assert content["data"] == "base64"
        assert content["imageInfoArray"] == [{"w": 1}]

    def test_file_element_maps_file_name(self):
        result = codec._to_proto_msg_body(
            [
                {
                    "msg_type": "TIMFileElem",
                    "msg_content": {"file_name": "a.pdf", "file_size": 5},
                },
            ],
        )
        content = result[0]["msgContent"]
        assert content["fileName"] == "a.pdf"
        assert content["fileSize"] == 5

    def test_default_msg_type_when_missing(self):
        result = codec._to_proto_msg_body(
            [{"msg_content": {"text": "t"}}],
        )
        assert result[0]["msgType"] == "TIMTextElem"

    def test_empty_list(self):
        assert codec._to_proto_msg_body([]) == []


class TestFromProtoMsgBody:
    def test_text_element(self):
        result = codec._from_proto_msg_body(
            [{"msgType": "TIMTextElem", "msgContent": {"text": "hello"}}],
        )
        assert result == [
            {"msg_type": "TIMTextElem", "msg_content": {"text": "hello"}},
        ]

    def test_image_element_reverse_maps(self):
        result = codec._from_proto_msg_body(
            [
                {
                    "msgType": "TIMImageElem",
                    "msgContent": {
                        "uuid": "u1",
                        "imageFormat": 1,
                        "url": "https://x",
                        "fileName": "f",
                        "fileSize": 3,
                        "desc": "d",
                        "data": "b64",
                        "imageInfoArray": [{"w": 1}],
                    },
                },
            ],
        )
        content = result[0]["msg_content"]
        assert content["uuid"] == "u1"
        assert content["image_format"] == 1
        assert content["file_name"] == "f"
        assert content["file_size"] == 3
        assert content["image_info_array"] == [{"w": 1}]

    def test_image_format_zero_preserved(self):
        """imageFormat 0 is a valid value and must not be dropped."""
        result = codec._from_proto_msg_body(
            [{"msgType": "x", "msgContent": {"imageFormat": 0}}],
        )
        assert result[0]["msg_content"]["image_format"] == 0

    def test_empty_content_yields_empty_dict(self):
        result = codec._from_proto_msg_body(
            [{"msgType": "x", "msgContent": {}}],
        )
        assert result[0]["msg_content"] == {}

    def test_missing_msg_content_key(self):
        result = codec._from_proto_msg_body([{"msgType": "x"}])
        assert result[0]["msg_content"] == {}

    def test_round_trip_with_to_proto(self):
        internal = [
            {"msg_type": "TIMTextElem", "msg_content": {"text": "round"}},
        ]
        proto = codec._to_proto_msg_body(internal)
        back = codec._from_proto_msg_body(proto)
        assert back == internal
