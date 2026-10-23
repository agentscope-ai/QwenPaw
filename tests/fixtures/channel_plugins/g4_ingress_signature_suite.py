"""Real reverse-proxy HTTP hop and child Twilio signature verification."""

import base64
import hashlib
import hmac
import json

from aiohttp import web
import pytest
from yarl import URL

from g4_ingress_support import listener, start

pytest_plugins = ["extension_process_suite", "g4_ingress_support"]


def configure_trusted_proxies(values):
    from qwenpaw.config.config import Config
    from qwenpaw.config.utils import get_config_path

    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    config = Config()
    assert config.security.trusted_proxies == []
    config.security.trusted_proxies = values
    path.write_text(config.model_dump_json())


async def reverse_proxy(ingress, path, signature, body):
    async def forward(request):
        async with ingress.client.post(
            URL(ingress.base + request.raw_path, encoded=True),
            data=await request.read(),
            headers={
                "Host": "public-tunnel.test:9443",
                "X-Forwarded-Host": "public-tunnel.test:9443",
                "X-Forwarded-Proto": "https",
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Twilio-Signature": request.headers["X-Twilio-Signature"],
            },
        ) as response:
            return web.Response(
                status=response.status, body=await response.read()
            )

    proxy = web.Application()
    proxy.router.add_post("/sample/signature", forward)
    runner = web.AppRunner(proxy)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        async with ingress.client.post(
            URL(f"http://127.0.0.1:{port}" + path, encoded=True),
            data=body,
            headers={"X-Twilio-Signature": signature},
        ) as response:
            return response.status, await response.read()
    finally:
        await runner.cleanup()


def signature_for(url):
    # Independent Twilio HMAC oracle; child uses the installed real validator.
    payload = url + "CallSidCA-localFrom+15551234567"
    return base64.b64encode(
        hmac.new(
            b"local-test-auth-token",
            payload.encode(),
            hashlib.sha1,
        ).digest()
    ).decode()


@pytest.mark.asyncio
async def test_default_https_tunnel_signature_remains_valid(ingress):
    configure_trusted_proxies([])
    rt, info = await start(ingress)
    # A real managed Voice tunnel publishes its origin through endpoint.update
    # after binding, before accepting public callbacks. Use that actual RPC.
    updated = await listener(
        rt,
        "canonical",
        public_base_url="https://public-tunnel.test:9443",
    )
    assert updated["forwarding"] == info["forwarding"]
    path = (
        "/sample/signature?_qp_endpoint="
        + info["forwarding"]["route_selector"]
    )
    external_url = "https://public-tunnel.test:9443" + path
    status, body = await reverse_proxy(
        ingress,
        path,
        signature_for(external_url),
        b"CallSid=CA-local&From=%2B15551234567",
    )
    row = (await listener(rt))["rows"][-1]
    original = dict((key.lower(), value) for key, value in row["headers"])[
        "x-qwenpaw-ingress-original-url"
    ]
    assert status == 200, json.dumps(
        {
            "status": status,
            "validator_url": original,
            "signed_url": external_url,
        }
    )
    assert body == b"signed"
    assert original == external_url


@pytest.mark.asyncio
async def test_no_canonical_origin_does_not_trust_unspecified_proxy(ingress):
    configure_trusted_proxies([])
    rt, info = await start(ingress)
    assert (
        rt.channel.endpoint_service.resolve().endpoint.public_base_url is None
    )
    path = (
        "/sample/signature?_qp_endpoint="
        + info["forwarding"]["route_selector"]
    )
    external_url = "https://public-tunnel.test:9443" + path
    status, _body = await reverse_proxy(
        ingress,
        path,
        signature_for(external_url),
        b"CallSid=CA-local&From=%2B15551234567",
    )
    assert status == 403
    row = (await listener(rt))["rows"][-1]
    headers = {key.lower(): value for key, value in row["headers"]}
    assert headers["x-qwenpaw-ingress-original-url"] == (
        "http://public-tunnel.test:9443" + path
    )


@pytest.mark.asyncio
async def test_explicit_trusted_proxy_signature_valid_and_forgery_rejected(
    ingress,
):
    configure_trusted_proxies(["127.0.0.1/32"])
    rt, info = await start(ingress)
    path = (
        "/sample/signature?_qp_endpoint="
        + info["forwarding"]["route_selector"]
    )
    external_url = "https://public-tunnel.test:9443" + path
    body = b"CallSid=CA-local&From=%2B15551234567"
    assert (
        await reverse_proxy(ingress, path, signature_for(external_url), body)
    )[0] == 200
    assert (await reverse_proxy(ingress, path, "invalid-signature", body))[
        0
    ] == 403
    rows = (await listener(rt))["rows"]
    assert len(rows) == 2 and all(row["authenticated"] for row in rows)
