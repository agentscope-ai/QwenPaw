# -*- coding: utf-8 -*-
"""Minimal mock Yuanbao backend for integration tests.

Serves both Yuanbao surfaces:

* HTTP: ``POST /api/v5/robotLogic/sign-token`` -> fake token
  (the product's ``api_domain`` accepts an explicit http:// scheme).
* WS gateway (protobuf ConnMsg frames): answers AuthBind with a
  success response, ACKs pings, records send_c2c/send_group biz
  requests, and lets tests push inbound message JSON.

Frame encoding reuses the *product codec*
(``qwenpaw.app.channels.yuanbao.codec``), so the mock stays in sync
with the real protocol definitions.
"""
from __future__ import annotations

# pylint: disable=protected-access  # nested handlers touch own instance

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional

from websockets.sync.server import serve as ws_serve

from qwenpaw.app.channels.yuanbao import codec as ybcodec

MOCK_BOT_ID = "integ-mock-yb-bot"
MOCK_TOKEN = "integ-mock-yb-token"


class MockYuanbao:
    """Mock Yuanbao backend (sign-token HTTP + protobuf WS)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started = False
        self.http_port: int = 0
        self.ws_port: int = 0
        # Recorded biz sends: dicts decoded from send_c2c/send_group.
        self.sent_msgs: list[dict[str, Any]] = []
        self._ws_conn: Optional[Any] = None
        self._authed = threading.Event()
        self._msg_counter = 0
        self._http_server: Optional[ThreadingHTTPServer] = None
        self._ws_server: Optional[Any] = None

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
        self._start_ws()
        self._start_http()

    @property
    def api_domain(self) -> str:
        """Value for the channel ``api_domain`` field (explicit http)."""
        return f"http://127.0.0.1:{self.http_port}"

    @property
    def ws_url(self) -> str:
        """Value for the channel ``ws_url`` field."""
        return f"ws://127.0.0.1:{self.ws_port}/wss/connection"

    # -------------------------------------------------------------- #
    # HTTP: sign-token
    # -------------------------------------------------------------- #

    def _start_http(self) -> None:
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:
                pass

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                _ = self.rfile.read(length) if length else b""
                raw = json.dumps(
                    {
                        "code": 0,
                        "data": {
                            "bot_id": MOCK_BOT_ID,
                            "token": MOCK_TOKEN,
                            "source": "bot",
                            "duration": 7200,
                            "product": "yuanbao",
                        },
                    },
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.http_port = server.server_address[1]
        self._http_server = server
        threading.Thread(
            target=server.serve_forever,
            name="mock-yuanbao-http",
            daemon=True,
        ).start()

    # -------------------------------------------------------------- #
    # WS gateway (protobuf ConnMsg)
    # -------------------------------------------------------------- #

    def _start_ws(self) -> None:
        mock = self

        def handler(conn: Any) -> None:
            with mock._lock:
                mock._ws_conn = conn
            try:
                for raw in conn:
                    if not isinstance(raw, (bytes, bytearray)):
                        continue
                    frame = ybcodec.decode_conn_msg(bytes(raw))
                    if not frame:
                        continue
                    head = frame.get("head") or {}
                    data = frame.get("data") or b""
                    mock._handle_frame(conn, head, data)
            except Exception:  # noqa: BLE001 - client dropped
                pass
            finally:
                with mock._lock:
                    if mock._ws_conn is conn:
                        mock._ws_conn = None

        server = ws_serve(handler, "127.0.0.1", 0)
        self.ws_port = server.socket.getsockname()[1]
        self._ws_server = server
        threading.Thread(
            target=server.serve_forever,
            name="mock-yuanbao-ws",
            daemon=True,
        ).start()

    def _handle_frame(self, conn: Any, head: dict, data: bytes) -> None:
        cmd = head.get("cmd", "")
        cmd_type = head.get("cmdType", 0)
        if cmd == ybcodec.CMD_AUTH_BIND:
            rsp_head = {
                "cmdType": ybcodec.CMD_TYPE_RESPONSE,
                "cmd": cmd,
                "seqNo": head.get("seqNo", 0),
                "msgId": head.get("msgId", ""),
                "module": head.get("module", ""),
            }
            rsp_data = ybcodec.encode_pb(
                ybcodec.AUTH_BIND_RSP,
                {"code": 0, "message": "ok"},
            )
            out = ybcodec.encode_conn_msg(rsp_head, rsp_data)
            if out:
                conn.send(out)
            self._authed.set()
            return
        if cmd == ybcodec.CMD_PING:
            rsp_head = {
                "cmdType": ybcodec.CMD_TYPE_RESPONSE,
                "cmd": cmd,
                "seqNo": head.get("seqNo", 0),
                "msgId": head.get("msgId", ""),
                "module": head.get("module", ""),
            }
            out = ybcodec.encode_conn_msg(rsp_head, b"")
            if out:
                conn.send(out)
            return
        if cmd_type == ybcodec.CMD_TYPE_REQUEST and cmd in (
            ybcodec.BIZ_CMD_SEND_C2C,
            ybcodec.BIZ_CMD_SEND_GROUP,
        ):
            decoded = self._decode_send_req(cmd, data)
            with self._lock:
                self.sent_msgs.append(
                    {"cmd": cmd, "body": decoded},
                )
            rsp_head = {
                "cmdType": ybcodec.CMD_TYPE_RESPONSE,
                "cmd": cmd,
                "seqNo": head.get("seqNo", 0),
                "msgId": head.get("msgId", ""),
                "module": head.get("module", ""),
            }
            rsp_data = ybcodec.encode_pb(
                ybcodec.SEND_C2C_RSP,
                {"code": 0, "message": "ok"},
            )
            out = ybcodec.encode_conn_msg(rsp_head, rsp_data)
            if out:
                conn.send(out)

    @staticmethod
    def _decode_send_req(cmd: str, data: bytes) -> dict:
        """Decode a send request without the product's decode_pb.

        The product decode_pb passes a protobuf kwarg removed in newer
        protobuf releases; decode directly with MessageToDict instead.
        """
        from google.protobuf import json_format

        type_name = (
            ybcodec.SEND_C2C_REQ
            if cmd == ybcodec.BIZ_CMD_SEND_C2C
            else ybcodec.SEND_GROUP_REQ
        )
        try:
            # pylint: disable-next=protected-access
            cls = ybcodec._get_message_class(type_name)
            msg = cls()
            msg.ParseFromString(data)
            return json_format.MessageToDict(
                msg,
                preserving_proto_field_name=True,
            )
        except Exception:  # noqa: BLE001
            return {}

    # -------------------------------------------------------------- #
    # test-facing helpers
    # -------------------------------------------------------------- #

    def wait_authed(self, timeout: float = 60.0) -> bool:
        return self._authed.wait(timeout)

    def reset_authed(self) -> None:
        self._authed.clear()

    @property
    def has_connection(self) -> bool:
        with self._lock:
            return self._ws_conn is not None

    def push_c2c_text(
        self,
        *,
        text: str,
        from_account: str = "integ-yb-user",
        msg_id: str = "",
    ) -> str:
        """Push an inbound C2C text message (JSON in push frame)."""
        with self._lock:
            self._msg_counter += 1
            n = self._msg_counter
        mid = msg_id or f"integ-yb-msg-{n}"
        inbound = {
            "callback_command": "Bot.OnC2CMessage",
            "from_account": from_account,
            "to_account": MOCK_BOT_ID,
            "sender_nickname": "Integ YB User",
            "msg_seq": n,
            "msg_time": int(time.time()),
            "msg_key": f"key-{mid}",
            "msg_id": mid,
            "msg_body": [
                {
                    "msg_type": "TIMTextElem",
                    "msg_content": {"text": text},
                },
            ],
        }
        head = {
            "cmdType": ybcodec.CMD_TYPE_PUSH,
            "cmd": "push_message",
            "seqNo": n,
            "msgId": mid,
            "module": "conn-access",
        }
        frame = ybcodec.encode_conn_msg(
            head,
            json.dumps(inbound).encode(),
        )
        with self._lock:
            conn = self._ws_conn
        assert conn is not None, "no yuanbao client connected"
        assert frame is not None
        conn.send(frame)
        return mid

    def push_group_text(
        self,
        *,
        text: str,
        group_code: str,
        from_account: str = "integ-yb-grouper",
        msg_id: str = "",
    ) -> str:
        """Push an inbound group text message (JSON push frame)."""
        with self._lock:
            self._msg_counter += 1
            n = self._msg_counter
        mid = msg_id or f"integ-yb-gmsg-{n}"
        inbound = {
            "callback_command": "Group.OnGroupMessage",
            "from_account": from_account,
            "to_account": MOCK_BOT_ID,
            "sender_nickname": "Integ YB Grouper",
            "group_code": group_code,
            "group_name": "Integ Group",
            "msg_seq": n,
            "msg_time": int(time.time()),
            "msg_key": f"key-{mid}",
            "msg_id": mid,
            "msg_body": [
                {
                    "msg_type": "TIMTextElem",
                    "msg_content": {"text": text},
                },
            ],
        }
        head = {
            "cmdType": ybcodec.CMD_TYPE_PUSH,
            "cmd": "push_message",
            "seqNo": n,
            "msgId": mid,
            "module": "conn-access",
        }
        frame = ybcodec.encode_conn_msg(
            head,
            json.dumps(inbound).encode(),
        )
        with self._lock:
            conn = self._ws_conn
        assert conn is not None, "no yuanbao client connected"
        assert frame is not None
        conn.send(frame)
        return mid

    def push_kickout(self, *, reason: str = "integ kickout") -> None:
        """Push a kickout control frame."""
        with self._lock:
            self._msg_counter += 1
            n = self._msg_counter
        head = {
            "cmdType": ybcodec.CMD_TYPE_PUSH,
            "cmd": ybcodec.CMD_KICKOUT,
            "seqNo": n,
            "msgId": f"integ-yb-kick-{n}",
            "module": "conn-access",
        }
        frame = ybcodec.encode_conn_msg(
            head,
            json.dumps({"reason": reason}).encode(),
        )
        with self._lock:
            conn = self._ws_conn
        if conn is None or frame is None:
            return
        conn.send(frame)

    def sent_texts(self) -> list[str]:
        out: list[str] = []
        with self._lock:
            msgs = list(self.sent_msgs)
        for msg in msgs:
            body = msg.get("body") or {}
            raw = json.dumps(body, ensure_ascii=False)
            out.append(raw)
        return out

    def wait_for_sent_text(
        self,
        predicate,
        *,
        timeout: float = 90.0,
    ) -> Optional[str]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            for text in self.sent_texts():
                if predicate(text):
                    return text
            time.sleep(0.2)
        return None
