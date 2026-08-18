# -*- coding: utf-8 -*-
"""Minimal mock WeCom AI Bot gateway (TLS WebSocket) for tests.

The aibot SDK always passes an SSL context built from certifi, so the
mock must serve **wss** with a certificate the subprocess trusts. This
module generates a throwaway CA + server cert at runtime, and the test
module injects trust into the app subprocess via::

    PYTHONPATH=<pysite dir>  (sitecustomize patches certifi.where)
    INTEG_CA_BUNDLE=<bundle.pem>

Protocol (JSON frames, aibot SDK):
  * client -> aibot_subscribe (auth) -> respond errcode=0
  * client -> ping heartbeats        -> respond errcode=0
  * server -> aibot_msg_callback push (body.msgtype=text ...)
  * client -> aibot_respond_msg / stream replies -> recorded
"""
from __future__ import annotations

# pylint: disable=protected-access  # nested handler touches own instance

import json
import ssl
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Optional

from websockets.sync.server import serve as ws_serve

_SUBSCRIBE = "aibot_subscribe"
_PING = "ping"


def _generate_tls_material(base: Path) -> dict:
    """Create CA + 127.0.0.1 server cert + certifi bundle + pysite."""
    base.mkdir(parents=True, exist_ok=True)
    ca_cnf = base / "ca.cnf"
    ca_cnf.write_text(
        "[req]\n"
        "distinguished_name = dn\n"
        "x509_extensions = v3_ca\n"
        "prompt = no\n"
        "[dn]\n"
        "CN = Integ WeCom Mock CA\n"
        "[v3_ca]\n"
        "basicConstraints = critical,CA:TRUE\n"
        "keyUsage = critical,keyCertSign,cRLSign\n"
        "subjectKeyIdentifier = hash\n",
    )
    ext = base / "ext.cnf"
    ext.write_text("subjectAltName=IP:127.0.0.1\n")
    run = lambda *args: subprocess.run(  # noqa: E731
        args,
        check=True,
        capture_output=True,
    )
    run(
        "openssl",
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        str(base / "ca.key"),
        "-out",
        str(base / "ca.pem"),
        "-days",
        "7",
        "-config",
        str(ca_cnf),
    )
    run(
        "openssl",
        "req",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        str(base / "server.key"),
        "-out",
        str(base / "server.csr"),
        "-subj",
        "/CN=127.0.0.1",
    )
    run(
        "openssl",
        "x509",
        "-req",
        "-in",
        str(base / "server.csr"),
        "-CA",
        str(base / "ca.pem"),
        "-CAkey",
        str(base / "ca.key"),
        "-CAcreateserial",
        "-out",
        str(base / "server.pem"),
        "-days",
        "7",
        "-extfile",
        str(ext),
    )
    import certifi

    bundle = base / "bundle.pem"
    bundle.write_bytes(
        Path(certifi.where()).read_bytes() + (base / "ca.pem").read_bytes(),
    )
    pysite = base / "pysite"
    pysite.mkdir(exist_ok=True)
    (pysite / "sitecustomize.py").write_text(
        '"""Test-only: trust the integ mock CA in certifi consumers."""\n'
        "import os\n\n"
        '_BUNDLE = os.environ.get("INTEG_CA_BUNDLE")\n'
        "if _BUNDLE:\n"
        "    try:\n"
        "        import certifi\n\n"
        "        certifi.where = lambda: _BUNDLE\n"
        "        certifi.core.where = certifi.where\n"
        "    except Exception:\n"
        "        pass\n",
    )
    return {
        "server_pem": base / "server.pem",
        "server_key": base / "server.key",
        "bundle": bundle,
        "pysite": pysite,
    }


class MockWeComGateway:
    """Mock WeCom AI Bot wss gateway on localhost."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started = False
        self.ws_port: int = 0
        self.tls: dict = {}
        self._ws_conn: Optional[Any] = None
        self._subscribed = threading.Event()
        self._counter = 0
        # Frames the channel sends after auth (replies, acks...).
        self.frames: list[dict[str, Any]] = []
        self._ws_server: Optional[Any] = None

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
        self.tls = _generate_tls_material(
            Path(tempfile.mkdtemp(prefix="wecom-mock-tls-")),
        )
        self._start_ws()

    @property
    def ws_url(self) -> str:
        """Value for the WeCom channel ``ws_url`` config field."""
        return f"wss://127.0.0.1:{self.ws_port}"

    @property
    def pysite_dir(self) -> str:
        return str(self.tls["pysite"])

    @property
    def ca_bundle(self) -> str:
        return str(self.tls["bundle"])

    def _start_ws(self) -> None:
        mock = self
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(
            str(self.tls["server_pem"]),
            str(self.tls["server_key"]),
        )

        def handler(conn: Any) -> None:
            with mock._lock:
                mock._ws_conn = conn
            try:
                for raw in conn:
                    try:
                        frame = json.loads(raw)
                    except (ValueError, TypeError):
                        continue
                    cmd = frame.get("cmd", "")
                    req_id = (frame.get("headers") or {}).get("req_id", "")
                    if cmd == _SUBSCRIBE:
                        conn.send(
                            json.dumps(
                                {
                                    "errcode": 0,
                                    "errmsg": "ok",
                                    "headers": {"req_id": req_id},
                                },
                            ),
                        )
                        mock._subscribed.set()
                        continue
                    if cmd == _PING:
                        conn.send(
                            json.dumps(
                                {
                                    "errcode": 0,
                                    "headers": {"req_id": req_id},
                                },
                            ),
                        )
                        continue
                    with mock._lock:
                        mock.frames.append(frame)
                    # Ack response-type frames so SDK futures resolve.
                    if req_id:
                        conn.send(
                            json.dumps(
                                {
                                    "errcode": 0,
                                    "headers": {"req_id": req_id},
                                },
                            ),
                        )
            except Exception:  # noqa: BLE001 - client dropped
                pass
            finally:
                with mock._lock:
                    if mock._ws_conn is conn:
                        mock._ws_conn = None

        server = ws_serve(handler, "127.0.0.1", 0, ssl=ctx)
        self.ws_port = server.socket.getsockname()[1]
        self._ws_server = server
        threading.Thread(
            target=server.serve_forever,
            name="mock-wecom-ws",
            daemon=True,
        ).start()

    # -------------------------------------------------------------- #
    # test-facing helpers
    # -------------------------------------------------------------- #

    def wait_subscribed(self, timeout: float = 60.0) -> bool:
        return self._subscribed.wait(timeout)

    def reset_subscribed(self) -> None:
        self._subscribed.clear()

    @property
    def has_connection(self) -> bool:
        with self._lock:
            return self._ws_conn is not None

    def push_text_message(
        self,
        *,
        text: str,
        userid: str = "integ-wecom-user",
        chatid: str = "integ-wecom-chat",
        chat_type: str = "single",
        msgid: str = "",
    ) -> str:
        """Push an aibot_msg_callback text frame to the channel."""
        with self._lock:
            self._counter += 1
            n = self._counter
        mid = msgid or f"integ-wecom-msg-{n}"
        frame = {
            "cmd": "aibot_msg_callback",
            "headers": {"req_id": f"cb-{mid}"},
            "body": {
                "msgtype": "text",
                "msgid": mid,
                "chatid": chatid,
                "chattype": chat_type,
                "send_time": int(time.time()),
                "from": {"userid": userid},
                "text": {"content": text},
            },
        }
        with self._lock:
            conn = self._ws_conn
        assert conn is not None, "no wecom client connected"
        conn.send(json.dumps(frame))
        return mid

    def push_image_message(
        self,
        *,
        url: str = "https://example.invalid/wecom-image.jpg",
        aes_key: str = "integ-wecom-aes",
        userid: str = "integ-wecom-user",
        chatid: str = "integ-wecom-chat",
        msgid: str = "",
    ) -> str:
        """Push an aibot_msg_callback image frame."""
        with self._lock:
            self._counter += 1
            n = self._counter
        mid = msgid or f"integ-wecom-img-{n}"
        frame = {
            "cmd": "aibot_msg_callback",
            "headers": {"req_id": f"cb-{mid}"},
            "body": {
                "msgtype": "image",
                "msgid": mid,
                "chatid": chatid,
                "chattype": "single",
                "send_time": int(time.time()),
                "from": {"userid": userid},
                "image": {"url": url, "aeskey": aes_key},
            },
        }
        with self._lock:
            conn = self._ws_conn
        assert conn is not None, "no wecom client connected"
        conn.send(json.dumps(frame))
        return mid

    def push_enter_chat(
        self,
        *,
        userid: str = "integ-wecom-entrant",
        chatid: str = "integ-wecom-enterchat",
    ) -> str:
        """Push an aibot_event_callback enter_chat frame."""
        with self._lock:
            self._counter += 1
            n = self._counter
        rid = f"integ-wecom-enter-{n}"
        frame = {
            "cmd": "aibot_event_callback",
            "headers": {"req_id": rid},
            "body": {
                "msgtype": "event",
                "event": {"eventtype": "enter_chat"},
                "chatid": chatid,
                "chattype": "single",
                "send_time": int(time.time()),
                "from": {"userid": userid},
            },
        }
        with self._lock:
            conn = self._ws_conn
        assert conn is not None, "no wecom client connected"
        conn.send(json.dumps(frame))
        return rid

    def reply_texts(self) -> list[str]:
        out: list[str] = []
        with self._lock:
            frames = list(self.frames)
        for frame in frames:
            out.append(json.dumps(frame, ensure_ascii=False))
        return out

    def wait_for_reply(
        self,
        predicate,
        *,
        timeout: float = 90.0,
    ) -> Optional[str]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            for text in self.reply_texts():
                if predicate(text):
                    return text
            time.sleep(0.2)
        return None
