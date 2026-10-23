"""Actual parsed request and private manage/client; HTTP transport only fake."""
import asyncio
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
sys.path[:0] = [str(root / "src"), str(root / "plugins/channel/wechat")]
import httpx
from qwenpaw.channel_protocol.management import ManagementRequest
from qwenpaw_channel_wechat.management import manage

requests = []


def respond(request):
    requests.append(str(request.url))
    return httpx.Response(
        200,
        json={
            "qrcode": "qr-code",
            "qrcode_img_content": "https://fixture.invalid/qr",
        },
        request=request,
    )


original = httpx.AsyncClient


class Client(original):
    def __init__(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(respond)
        kwargs["trust_env"] = False
        super().__init__(*args, **kwargs)


httpx.AsyncClient = Client
packet = {
    "request_id": "d095974b-e2f1-4e78-81e2-47767df96632",
    "plugin_id": "wechat",
    "workspace_id": "A",
    "channel_key": "wechat",
    "instance_id": "actual-private-manage",
    "generation": 1,
    "source_revision": "a" * 64,
    "operation": "qrcode.fetch",
    "timeout_ms": 3000,
    "parameters": {
        "config": {"base_url": "https://saved.invalid"},
        "options": {"base_url": "https://temporary.invalid"},
    },
}
request = ManagementRequest.from_mapping(packet)
assert type(request.operation) is str
result = asyncio.run(manage(request))
assert result.outcome == "ok"
assert result.result == {
    "scan_url": "https://fixture.invalid/qr",
    "continuation": "qr-code",
}
assert len(requests) == 1 and requests[0].startswith(
    "https://temporary.invalid/ilink/bot/get_bot_qrcode?"
)
print(json.dumps({"passed": True, "http_requests": requests}))
