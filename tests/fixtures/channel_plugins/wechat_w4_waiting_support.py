"""Native QR GET responses on the existing external iLink HTTP mock."""

import time
from urllib.parse import parse_qs, urlsplit

import pytest_asyncio

from wechat_w4_formal_support import native_ilink

__all__ = ["native_ilink", "qr_ilink"]


@pytest_asyncio.fixture
async def qr_ilink(native_ilink):
    state = native_ilink
    state.qr_confirmed = False
    state.qr_expired = False
    state.qr_polls = []
    state.qr_fetches = 0
    server = state.mock._http_server
    previous = server.RequestHandlerClass

    class NativeQRHTTP(previous):
        def do_GET(self):
            path = urlsplit(self.path).path
            if path.endswith("/get_bot_qrcode"):
                state.qr_fetches += 1
                return self._json(
                    {
                        "qrcode": "controlled-runtime-code",
                        "qrcode_img_content": state.mock.base_url + "/scan",
                    }
                )
            if path.endswith("/get_qrcode_status"):
                confirmed = state.qr_confirmed
                status = (
                    "expired"
                    if state.qr_expired
                    else "confirmed" if confirmed else "waiting"
                )
                state.qr_polls.append(
                    {
                        "time": time.monotonic(),
                        "status": status,
                        "qrcode": parse_qs(urlsplit(self.path).query).get(
                            "qrcode", []
                        ),
                    }
                )
                return self._json(
                    {
                        "status": "confirmed",
                        "bot_token": "temporary-file-token",
                        "baseurl": state.mock.base_url,
                    }
                    if status == "confirmed"
                    else {"status": status}
                )
            return super().do_GET()

    server.RequestHandlerClass = NativeQRHTTP
    yield state
    server.RequestHandlerClass = previous
