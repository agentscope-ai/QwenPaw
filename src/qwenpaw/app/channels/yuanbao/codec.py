# -*- coding: utf-8 -*-
"""Protobuf codec for Yuanbao WebSocket protocol.

Uses protobufjs-compatible JSON descriptors (conn.json / biz.json)
to encode/decode the binary wire protocol without .proto compilation.
"""

import json
import logging
import random
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from google.protobuf import descriptor_pb2, descriptor_pool, json_format
from google.protobuf.descriptor import Descriptor, FieldDescriptor
from google.protobuf.message_factory import GetMessageClass

logger = logging.getLogger(__name__)

_PROTO_DIR = Path(__file__).parent / "proto"

# ── Protobuf JSON descriptor → runtime message classes ──────────────

_MSG_CLASSES: Dict[str, Any] = {}


def _field_type_map() -> Dict[str, int]:
    """Map JSON descriptor type strings to protobuf field type numbers."""
    ft = FieldDescriptor
    return {
        "double": ft.TYPE_DOUBLE,
        "float": ft.TYPE_FLOAT,
        "int32": ft.TYPE_INT32,
        "int64": ft.TYPE_INT64,
        "uint32": ft.TYPE_UINT32,
        "uint64": ft.TYPE_UINT64,
        "sint32": ft.TYPE_SINT32,
        "sint64": ft.TYPE_SINT64,
        "fixed32": ft.TYPE_FIXED32,
        "fixed64": ft.TYPE_FIXED64,
        "sfixed32": ft.TYPE_SFIXED32,
        "sfixed64": ft.TYPE_SFIXED64,
        "bool": ft.TYPE_BOOL,
        "string": ft.TYPE_STRING,
        "bytes": ft.TYPE_BYTES,
    }


def _resolve_field_type(
    type_name: str,
    package: str,
    known_enums: set,
) -> Tuple[int, Optional[str]]:
    """Resolve a field type string to (type_num, type_name_or_none)."""
    scalar_map = _field_type_map()
    if type_name in scalar_map:
        return scalar_map[type_name], None

    fqn = (
        f".{package}.{type_name}"
        if not type_name.startswith(".")
        else type_name
    )
    if fqn in known_enums or type_name in known_enums:
        return FieldDescriptor.TYPE_ENUM, fqn
    return FieldDescriptor.TYPE_MESSAGE, fqn


def _collect_names(nested: dict, prefix: str, messages: set, enums: set):
    """Recursively collect all message and enum fully-qualified names."""
    for name, spec in nested.items():
        fqn = f"{prefix}.{name}"
        if "fields" in spec:
            messages.add(fqn)
            if "nested" in spec:
                _collect_names(spec["nested"], fqn, messages, enums)
        elif "values" in spec:
            enums.add(fqn)


def _build_file_descriptor(
    json_path: Path,
) -> descriptor_pb2.FileDescriptorProto:
    """Convert a protobufjs JSON descriptor into a FileDescriptorProto."""
    with open(json_path, encoding="utf-8") as fh:
        root = json.load(fh)

    syntax = root.get("options", {}).get("syntax", "proto3")
    file_name = json_path.stem + ".proto"

    fdp = descriptor_pb2.FileDescriptorProto()
    fdp.name = file_name
    fdp.syntax = syntax

    # Walk the nested tree to find the package and message definitions
    nested = root.get("nested", {})

    # Flatten the package path (e.g., trpc.yuanbao.conn_common)
    package_parts: list = []
    current = nested

    while len(current) == 1:
        key = next(iter(current))
        child = current[key]
        if (
            "nested" in child
            and "fields" not in child
            and "values" not in child
        ):
            package_parts.append(key)
            current = child["nested"]
        else:
            break

    package = ".".join(package_parts)
    fdp.package = package

    # Collect all known message and enum names for type resolution
    known_messages: set = set()
    known_enums: set = set()
    _collect_names(current, package, known_messages, known_enums)

    def add_enum(enum_spec: dict, name: str, container):
        edp = container.enum_type.add()
        edp.name = name
        for val_name, val_number in enum_spec.get("values", {}).items():
            evdp = edp.value.add()
            evdp.name = val_name
            evdp.number = val_number

    def add_message(msg_spec: dict, name: str, container):
        mdp = container.message_type.add()
        mdp.name = name

        for field_name, field_spec in msg_spec.get("fields", {}).items():
            fdesc = mdp.field.add()
            fdesc.name = field_name
            fdesc.number = field_spec["id"]
            fdesc.json_name = field_name

            type_num, type_name = _resolve_field_type(
                field_spec["type"],
                package,
                known_enums,
            )
            fdesc.type = type_num
            if type_name:
                fdesc.type_name = type_name

            if field_spec.get("rule") == "repeated":
                fdesc.label = FieldDescriptor.LABEL_REPEATED
            else:
                fdesc.label = FieldDescriptor.LABEL_OPTIONAL

        # Handle nested messages/enums within this message
        for sub_name, sub_spec in msg_spec.get("nested", {}).items():
            if "fields" in sub_spec:
                add_message(sub_spec, sub_name, mdp)
            elif "values" in sub_spec:
                add_enum(sub_spec, sub_name, mdp)

    for name, spec in current.items():
        if "fields" in spec:
            add_message(spec, name, fdp)
        elif "values" in spec:
            add_enum(spec, name, fdp)

    return fdp


def _init_pool():
    """Initialize the descriptor pool with conn and biz proto descriptors."""
    if _MSG_CLASSES:
        return

    pool = descriptor_pool.DescriptorPool()

    for json_file in ("conn.json", "biz.json"):
        path = _PROTO_DIR / json_file
        fdp = _build_file_descriptor(path)
        pool.Add(fdp)

    # Register all message types
    for proto_file in ("conn.proto", "biz.proto"):
        file_desc = pool.FindFileByName(proto_file)
        for msg_desc in file_desc.message_types_by_name.values():
            _register_message(msg_desc)


def _register_message(msg_desc: Descriptor):
    """Recursively register a message descriptor and its nested types."""
    fqn = msg_desc.full_name
    _MSG_CLASSES[fqn] = GetMessageClass(msg_desc)
    for nested in msg_desc.nested_types:
        _register_message(nested)


def _get_message_class(full_name: str):
    """Get a protobuf message class by fully-qualified name."""
    _init_pool()
    cls = _MSG_CLASSES.get(full_name)
    if cls is None:
        raise ValueError(f"Unknown protobuf message type: {full_name}")
    return cls


# ── Public types ─────────────────────────────────────────────────────

# Connection-layer message types
CONN_MSG = "trpc.yuanbao.conn_common.ConnMsg"
AUTH_BIND_REQ = "trpc.yuanbao.conn_common.AuthBindReq"
AUTH_BIND_RSP = "trpc.yuanbao.conn_common.AuthBindRsp"
PING_REQ = "trpc.yuanbao.conn_common.PingReq"
PING_RSP = "trpc.yuanbao.conn_common.PingRsp"
KICKOUT_MSG = "trpc.yuanbao.conn_common.KickoutMsg"
PUSH_MSG = "trpc.yuanbao.conn_common.PushMsg"
DIRECTED_PUSH = "trpc.yuanbao.conn_common.DirectedPush"

# Business-layer message types
BIZ_PKG = "trpc.yuanbao.yuanbao_conn.yuanbao_openclaw_proxy"
INBOUND_MSG_PUSH = f"{BIZ_PKG}.InboundMessagePush"
SEND_C2C_REQ = f"{BIZ_PKG}.SendC2CMessageReq"
SEND_C2C_RSP = f"{BIZ_PKG}.SendC2CMessageRsp"
SEND_GROUP_REQ = f"{BIZ_PKG}.SendGroupMessageReq"
SEND_GROUP_RSP = f"{BIZ_PKG}.SendGroupMessageRsp"
SEND_PRIVATE_HB_REQ = f"{BIZ_PKG}.SendPrivateHeartbeatReq"
SEND_PRIVATE_HB_RSP = f"{BIZ_PKG}.SendPrivateHeartbeatRsp"
SEND_GROUP_HB_REQ = f"{BIZ_PKG}.SendGroupHeartbeatReq"
SEND_GROUP_HB_RSP = f"{BIZ_PKG}.SendGroupHeartbeatRsp"

# Command types
CMD_TYPE_REQUEST = 0
CMD_TYPE_RESPONSE = 1
CMD_TYPE_PUSH = 2
CMD_TYPE_PUSH_ACK = 3

# Built-in commands
CMD_AUTH_BIND = "auth-bind"
CMD_PING = "ping"
CMD_KICKOUT = "kickout"

# Built-in modules
MODULE_CONN_ACCESS = "conn_access"
MODULE_BIZ = "yuanbao_openclaw_proxy"

# Business commands
BIZ_CMD_SEND_C2C = "send_c2c_message"
BIZ_CMD_SEND_GROUP = "send_group_message"
BIZ_CMD_PRIVATE_HB = "send_private_heartbeat"
BIZ_CMD_GROUP_HB = "send_group_heartbeat"

_seq_counter = 0


def _next_seq() -> int:
    global _seq_counter
    _seq_counter += 1
    if _seq_counter >= 2**31:
        _seq_counter = 0
    return _seq_counter


def _generate_msg_id() -> str:
    return uuid.uuid4().hex


# ── Encode / Decode helpers ──────────────────────────────────────────


def encode_pb(type_name: str, data: dict) -> Optional[bytes]:
    """Encode a dict into protobuf binary.

    Returns b'' for empty messages (valid).
    """
    try:
        cls = _get_message_class(type_name)
        msg = cls()
        if data:
            json_format.ParseDict(data, msg)
        return msg.SerializeToString()
    except Exception as exc:
        logger.error("protobuf encode failed for %s: %s", type_name, exc)
        return None


def decode_pb(type_name: str, data: bytes) -> Optional[dict]:
    """Decode protobuf binary into a dict."""
    try:
        cls = _get_message_class(type_name)
        msg = cls()
        msg.ParseFromString(data)
        return json_format.MessageToDict(
            msg,
            preserving_proto_field_name=True,
            including_default_value_fields=False,
        )
    except Exception:
        return None


def encode_conn_msg(
    head: dict,
    inner_data: Optional[bytes] = None,
) -> Optional[bytes]:
    """Encode a ConnMsg (head + data) into binary."""
    payload = {"head": head}
    if inner_data:
        payload["data"] = inner_data
    try:
        cls = _get_message_class(CONN_MSG)
        msg = cls()
        # Set head fields manually to avoid base64 encoding issues with bytes
        msg.head.cmdType = head.get("cmdType", 0)
        msg.head.cmd = head.get("cmd", "")
        msg.head.seqNo = head.get("seqNo", 0)
        msg.head.msgId = head.get("msgId", "")
        msg.head.module = head.get("module", "")
        if head.get("needAck"):
            msg.head.needAck = True
        if inner_data:
            msg.data = inner_data
        return msg.SerializeToString()
    except Exception as exc:
        logger.error("encode_conn_msg failed: %s", exc)
        return None


def decode_conn_msg(raw: bytes) -> Optional[dict]:
    """Decode a raw binary frame into ConnMsg dict with raw data bytes."""
    try:
        cls = _get_message_class(CONN_MSG)
        msg = cls()
        msg.ParseFromString(raw)
        return {
            "head": {
                "cmdType": msg.head.cmdType,
                "cmd": msg.head.cmd,
                "seqNo": msg.head.seqNo,
                "msgId": msg.head.msgId,
                "module": msg.head.module,
                "needAck": msg.head.needAck,
                "status": msg.head.status,
            },
            "data": bytes(msg.data) if msg.data else b"",
        }
    except Exception:
        return None


# ── High-level message builders ──────────────────────────────────────


def build_auth_bind_msg(
    biz_id: str,
    uid: str,
    source: str,
    token: str,
    route_env: Optional[str] = None,
) -> Optional[bytes]:
    """Build an AuthBind request ConnMsg."""
    auth_bind_payload: Dict[str, Any] = {
        "bizId": biz_id,
        "authInfo": {
            "uid": uid,
            "source": source,
            "token": token,
        },
        "deviceInfo": {
            "instanceId": "16",
        },
    }
    if route_env:
        auth_bind_payload["envName"] = route_env

    auth_data = encode_pb(AUTH_BIND_REQ, auth_bind_payload)
    if auth_data is None:
        return None

    msg_id = _generate_msg_id()
    head = {
        "cmdType": CMD_TYPE_REQUEST,
        "cmd": CMD_AUTH_BIND,
        "seqNo": _next_seq(),
        "msgId": msg_id,
        "module": MODULE_CONN_ACCESS,
    }
    return encode_conn_msg(head, auth_data)


def build_ping_msg() -> Optional[bytes]:
    """Build a Ping request ConnMsg."""
    ping_data = encode_pb(PING_REQ, {})
    if ping_data is None:
        return None

    msg_id = _generate_msg_id()
    head = {
        "cmdType": CMD_TYPE_REQUEST,
        "cmd": CMD_PING,
        "seqNo": _next_seq(),
        "msgId": msg_id,
        "module": MODULE_CONN_ACCESS,
    }
    return encode_conn_msg(head, ping_data)


def build_push_ack(original_head: dict) -> Optional[bytes]:
    """Build a push acknowledgment."""
    ack_head = {
        "cmdType": CMD_TYPE_PUSH_ACK,
        "cmd": original_head.get("cmd", ""),
        "seqNo": _next_seq(),
        "msgId": original_head.get("msgId", ""),
        "module": original_head.get("module", ""),
    }
    return encode_conn_msg(ack_head, None)


def build_biz_msg(cmd: str, biz_data: bytes) -> Optional[bytes]:
    """Build a business request ConnMsg."""
    msg_id = _generate_msg_id()
    head = {
        "cmdType": CMD_TYPE_REQUEST,
        "cmd": cmd,
        "seqNo": _next_seq(),
        "msgId": msg_id,
        "module": MODULE_BIZ,
    }
    return encode_conn_msg(head, biz_data)


def build_send_c2c_msg(
    to_account: str,
    msg_body: List[dict],
    from_account: str = "",
    group_code: str = "",
) -> Optional[Tuple[bytes, str]]:
    """Build a SendC2CMessage request. Returns (binary, msg_id)."""
    proto_body = _to_proto_msg_body(msg_body)
    payload = {
        "toAccount": to_account,
        "fromAccount": from_account,
        "msgRandom": _random_int(),
        "msgBody": proto_body,
    }
    if group_code:
        payload["groupCode"] = group_code

    biz_data = encode_pb(SEND_C2C_REQ, payload)
    if biz_data is None:
        return None

    msg_id = _generate_msg_id()
    head = {
        "cmdType": CMD_TYPE_REQUEST,
        "cmd": BIZ_CMD_SEND_C2C,
        "seqNo": _next_seq(),
        "msgId": msg_id,
        "module": MODULE_BIZ,
    }
    raw = encode_conn_msg(head, biz_data)
    if raw is None:
        return None
    return raw, msg_id


def build_send_group_msg(
    group_code: str,
    msg_body: List[dict],
    from_account: str = "",
) -> Optional[Tuple[bytes, str]]:
    """Build a SendGroupMessage request. Returns (binary, msg_id)."""
    proto_body = _to_proto_msg_body(msg_body)
    payload = {
        "groupCode": group_code,
        "fromAccount": from_account,
        "random": str(_random_int()),
        "msgBody": proto_body,
    }

    biz_data = encode_pb(SEND_GROUP_REQ, payload)
    if biz_data is None:
        return None

    msg_id = _generate_msg_id()
    head = {
        "cmdType": CMD_TYPE_REQUEST,
        "cmd": BIZ_CMD_SEND_GROUP,
        "seqNo": _next_seq(),
        "msgId": msg_id,
        "module": MODULE_BIZ,
    }
    raw = encode_conn_msg(head, biz_data)
    if raw is None:
        return None
    return raw, msg_id


def build_heartbeat_msg(
    from_account: str,
    to_account: str,
    heartbeat: int,
    group_code: Optional[str] = None,
    send_time: Optional[int] = None,
) -> Optional[Tuple[bytes, str]]:
    """Build a reply-status heartbeat message (typing indicator)."""
    if group_code:
        payload = {
            "fromAccount": from_account,
            "toAccount": to_account,
            "groupCode": group_code,
            "sendTime": send_time or 0,
            "heartbeat": heartbeat,
        }
        biz_data = encode_pb(SEND_GROUP_HB_REQ, payload)
        cmd = BIZ_CMD_GROUP_HB
    else:
        payload = {
            "fromAccount": from_account,
            "toAccount": to_account,
            "heartbeat": heartbeat,
        }
        biz_data = encode_pb(SEND_PRIVATE_HB_REQ, payload)
        cmd = BIZ_CMD_PRIVATE_HB

    if biz_data is None:
        return None

    msg_id = _generate_msg_id()
    head = {
        "cmdType": CMD_TYPE_REQUEST,
        "cmd": cmd,
        "seqNo": _next_seq(),
        "msgId": msg_id,
        "module": MODULE_BIZ,
    }
    raw = encode_conn_msg(head, biz_data)
    if raw is None:
        return None
    return raw, msg_id


def decode_auth_bind_rsp(data: bytes) -> Optional[dict]:
    """Decode AuthBindRsp from raw bytes."""
    return decode_pb(AUTH_BIND_RSP, data)


def decode_ping_rsp(data: bytes) -> Optional[dict]:
    """Decode PingRsp from raw bytes."""
    return decode_pb(PING_RSP, data)


def decode_kickout_msg(data: bytes) -> Optional[dict]:
    """Decode KickoutMsg from raw bytes."""
    return decode_pb(KICKOUT_MSG, data)


def decode_inbound_message(data: bytes) -> Optional[dict]:
    """Decode an InboundMessagePush from raw bytes."""
    decoded = decode_pb(INBOUND_MSG_PUSH, data)
    if not decoded:
        return None
    # Convert proto field names to snake_case for internal use
    return {
        "callback_command": decoded.get("callbackCommand", ""),
        "from_account": decoded.get("fromAccount", ""),
        "to_account": decoded.get("toAccount", ""),
        "sender_nickname": decoded.get("senderNickname", ""),
        "group_code": decoded.get("groupCode", ""),
        "group_name": decoded.get("groupName", ""),
        "msg_seq": decoded.get("msgSeq", 0),
        "msg_time": decoded.get("msgTime", 0),
        "msg_key": decoded.get("msgKey", ""),
        "msg_id": decoded.get("msgId", ""),
        "msg_body": _from_proto_msg_body(decoded.get("msgBody", [])),
        "bot_owner_id": decoded.get("botOwnerId", ""),
        "claw_msg_type": decoded.get("clawMsgType", 0),
    }


def decode_send_rsp(data: bytes) -> Optional[dict]:
    """Decode a SendC2CMessageRsp or SendGroupMessageRsp."""
    result = decode_pb(SEND_C2C_RSP, data)
    if result is None:
        result = decode_pb(SEND_GROUP_RSP, data)
    return result


def decode_push_msg(data: bytes) -> Optional[dict]:
    """Decode a PushMsg wrapper."""
    return decode_pb(PUSH_MSG, data)


# ── Internal helpers ─────────────────────────────────────────────────


def _random_int() -> int:
    return random.randint(0, 4294967295)


def _to_proto_msg_body(elements: List[dict]) -> List[dict]:
    """Convert internal msg_body format to protobuf format."""
    result = []
    for elem in elements:
        content = elem.get("msg_content", {})
        proto_content: Dict[str, Any] = {}
        if "text" in content:
            proto_content["text"] = content["text"]
        if "uuid" in content:
            proto_content["uuid"] = content["uuid"]
        if "image_format" in content:
            proto_content["imageFormat"] = content["image_format"]
        if "url" in content:
            proto_content["url"] = content["url"]
        if "file_name" in content:
            proto_content["fileName"] = content["file_name"]
        if "file_size" in content:
            proto_content["fileSize"] = content["file_size"]
        if "desc" in content:
            proto_content["desc"] = content["desc"]
        if "data" in content:
            proto_content["data"] = content["data"]
        if "image_info_array" in content:
            proto_content["imageInfoArray"] = content["image_info_array"]

        result.append(
            {
                "msgType": elem.get("msg_type", "TIMTextElem"),
                "msgContent": proto_content,
            },
        )
    return result


def _from_proto_msg_body(elements: list) -> List[dict]:
    """Convert protobuf msg_body format to internal format."""
    result = []
    for elem in elements:
        mc = elem.get("msgContent", {})
        content: Dict[str, Any] = {}
        if mc.get("text"):
            content["text"] = mc["text"]
        if mc.get("uuid"):
            content["uuid"] = mc["uuid"]
        if mc.get("imageFormat") is not None:
            content["image_format"] = mc["imageFormat"]
        if mc.get("url"):
            content["url"] = mc["url"]
        if mc.get("fileName"):
            content["file_name"] = mc["fileName"]
        if mc.get("fileSize"):
            content["file_size"] = mc["fileSize"]
        if mc.get("desc"):
            content["desc"] = mc["desc"]
        if mc.get("data"):
            content["data"] = mc["data"]
        if mc.get("imageInfoArray"):
            content["image_info_array"] = mc["imageInfoArray"]

        result.append(
            {
                "msg_type": elem.get("msgType", ""),
                "msg_content": content,
            },
        )
    return result
