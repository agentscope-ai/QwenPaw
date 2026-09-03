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
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations


from qwenpaw.app.channels.yuanbao import codec


# ---------------------------------------------------------------------------
# encode_pb
# ---------------------------------------------------------------------------


class TestEncodePb:
    def test_encodes_known_message(self):
        data = codec.encode_pb(
            codec.AUTH_BIND_REQ,
            {"bizId": "biz", "authInfo": {"uid": "u"}},
        )
        assert isinstance(data, bytes)
        assert len(data) > 0

    def test_empty_data_encodes_to_empty_message(self):
        data = codec.encode_pb(codec.PING_REQ, {})
        assert data == b""

    def test_unknown_message_type_returns_none(self):
        assert codec.encode_pb("no.such.Message", {}) is None


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


def _frame_of(raw: bytes) -> dict:
    return codec.decode_conn_msg(raw)


class TestBuildAuthBindMsg:
    def test_builds_request_frame(self):
        raw = codec.build_auth_bind_msg(
            biz_id="biz",
            uid="uid",
            source="src",
            token="tok",
        )
        assert isinstance(raw, bytes)
        frame = _frame_of(raw)
        assert frame["head"]["cmd"] == codec.CMD_AUTH_BIND
        assert frame["head"]["cmdType"] == codec.CMD_TYPE_REQUEST
        assert frame["head"]["module"] == codec.MODULE_CONN_ACCESS
        assert len(frame["head"]["msgId"]) == 32  # uuid4 hex
        assert frame["data"]

    def test_with_route_env_encodes_payload(self):
        raw = codec.build_auth_bind_msg(
            biz_id="biz",
            uid="uid",
            source="src",
            token="tok",
            route_env="prod",
        )
        frame = _frame_of(raw)
        assert frame["data"]


class TestBuildPingMsg:
    def test_builds_ping_frame(self):
        raw = codec.build_ping_msg()
        frame = _frame_of(raw)
        assert frame["head"]["cmd"] == codec.CMD_PING
        assert frame["head"]["cmdType"] == codec.CMD_TYPE_REQUEST
        assert frame["head"]["module"] == codec.MODULE_CONN_ACCESS


class TestBuildPushAck:
    def test_ack_preserves_original_head_fields(self):
        original = {"cmd": "inbound", "msgId": "orig-1", "module": "mod"}
        raw = codec.build_push_ack(original)
        frame = _frame_of(raw)
        assert frame["head"]["cmdType"] == codec.CMD_TYPE_PUSH_ACK
        assert frame["head"]["cmd"] == "inbound"
        assert frame["head"]["msgId"] == "orig-1"
        assert frame["head"]["module"] == "mod"
        assert frame["data"] == b""


class TestBuildBizMsg:
    def test_uses_biz_module(self):
        raw = codec.build_biz_msg("custom_cmd", b"bizdata")
        frame = _frame_of(raw)
        assert frame["head"]["cmd"] == "custom_cmd"
        assert frame["head"]["module"] == codec.MODULE_BIZ
        assert frame["data"] == b"bizdata"


class TestBuildSendC2CMsg:
    def test_returns_frame_and_msg_id(self):
        result = codec.build_send_c2c_msg(
            to_account="friend",
            msg_body=[
                {"msg_type": "TIMTextElem", "msg_content": {"text": "hi"}},
            ],
        )
        assert result is not None
        raw, msg_id = result
        frame = _frame_of(raw)
        assert frame["head"]["cmd"] == codec.BIZ_CMD_SEND_C2C
        assert frame["head"]["msgId"] == msg_id
        assert frame["head"]["module"] == codec.MODULE_BIZ
        assert len(msg_id) == 32

    def test_with_group_code(self):
        raw, _ = codec.build_send_c2c_msg(
            to_account="friend",
            msg_body=[
                {"msg_type": "TIMTextElem", "msg_content": {"text": "hi"}},
            ],
            group_code="g1",
        )
        assert _frame_of(raw)["data"]


class TestBuildSendGroupMsg:
    def test_returns_frame_and_msg_id(self):
        raw, msg_id = codec.build_send_group_msg(
            group_code="group-1",
            msg_body=[
                {"msg_type": "TIMTextElem", "msg_content": {"text": "hi"}},
            ],
        )
        frame = _frame_of(raw)
        assert frame["head"]["cmd"] == codec.BIZ_CMD_SEND_GROUP
        assert frame["head"]["msgId"] == msg_id


class TestBuildHeartbeatMsg:
    def test_private_heartbeat(self):
        raw, msg_id = codec.build_heartbeat_msg(
            from_account="bot",
            to_account="user",
            heartbeat=1,
        )
        frame = _frame_of(raw)
        assert frame["head"]["cmd"] == codec.BIZ_CMD_PRIVATE_HB
        assert frame["head"]["msgId"] == msg_id

    def test_group_heartbeat(self):
        raw, _ = codec.build_heartbeat_msg(
            from_account="bot",
            to_account="user",
            heartbeat=1,
            group_code="g1",
        )
        frame = _frame_of(raw)
        assert frame["head"]["cmd"] == codec.BIZ_CMD_GROUP_HB


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
