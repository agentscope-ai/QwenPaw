"""Real private Azure attachment boundary security regressions."""
# flake8: noqa: F811

from pathlib import Path
import asyncio
import gzip

from aiohttp import web
import pytest

from azure_bot_native_support import (  # noqa: F401
    azure,
    connector,
    rsa_material,
)


def streamed_download(body, framing, *, declared_length=None, encoding=None):
    """Serve actual HTTP framing through the fixture's trusted TLS boundary."""

    async def handle(request):
        headers = {"Content-Type": "application/octet-stream"}
        if encoding is not None:
            headers["Content-Encoding"] = encoding
        response = web.StreamResponse(headers=headers)
        if framing == "length":
            response.content_length = (
                len(body) if declared_length is None else declared_length
            )
            if declared_length is not None:
                response.force_close()
        elif framing == "chunked":
            response.enable_chunked_encoding()
        else:
            assert framing == "eof"
            # HTTP/1.1 close-delimited bodies have neither length nor chunks.
            response._length_check = False
            response.force_close()
        await response.prepare(request)
        for offset in range(0, len(body), 7):
            await response.write(body[offset : offset + 7])
        await response.write_eof()
        return response

    return handle


@pytest.mark.asyncio
@pytest.mark.parametrize("framing", ["length", "chunked", "eof"])
@pytest.mark.parametrize("size", [31, 32, 33])
async def test_download_byte_limit_accepts_boundary_and_rejects_overflow(
    azure, connector, monkeypatch, framing, size
):
    from azure_bot_native_support import platform_module

    monkeypatch.setattr(
        platform_module, "DOWNLOAD_MAX_BYTES", 32, raising=False
    )
    body = b"x" * size
    connector.download_handler = streamed_download(body, framing)
    async with azure() as (driver, _):
        media = driver._platform.media_dir
        before = set(media.rglob("*"))
        part = await driver._platform._attachment(
            {
                "contentUrl": "https://media.test/download/size",
                "contentType": "image/png",
            },
            "secret",
        )
        if size <= 32:
            assert part is not None
            assert Path(part["image_url"]).read_bytes() == body
        else:
            assert part is None
            assert set(media.rglob("*")) == before
        assert (
            connector.download_headers[0].get("Accept-Encoding") == "identity"
        )


@pytest.mark.asyncio
async def test_truncated_declared_download_leaves_no_file(
    azure, connector, monkeypatch
):
    from azure_bot_native_support import platform_module

    monkeypatch.setattr(
        platform_module, "DOWNLOAD_MAX_BYTES", 32, raising=False
    )
    # A smaller declared length defines the body boundary in HTTP; a larger
    # false length is truncated and must never publish the partial body.
    connector.download_handler = streamed_download(
        b"short", "length", declared_length=16
    )
    async with azure() as (driver, _):
        media = driver._platform.media_dir
        before = set(media.rglob("*"))
        part = await driver._platform._attachment(
            {
                "contentUrl": "https://media.test/download/truncated",
                "contentType": "image/png",
            },
            "secret",
        )
        assert part is None
        assert set(media.rglob("*")) == before


@pytest.mark.asyncio
async def test_declared_overflow_rejected_without_waiting_for_body(
    azure, connector, monkeypatch
):
    from azure_bot_native_support import platform_module

    monkeypatch.setattr(
        platform_module, "DOWNLOAD_MAX_BYTES", 32, raising=False
    )
    release_body = asyncio.Event()

    async def headers_only(request):
        response = web.StreamResponse(headers={"Content-Length": "33"})
        await response.prepare(request)
        await release_body.wait()
        return response

    connector.download_handler = headers_only
    async with azure() as (driver, _):
        media = driver._platform.media_dir
        before = set(media.rglob("*"))
        try:
            part = await asyncio.wait_for(
                driver._platform._attachment(
                    {
                        "contentUrl": "https://media.test/download/headers-only",
                        "contentType": "image/png",
                    },
                    "secret",
                ),
                timeout=2,
            )
            assert part is None
            assert set(media.rglob("*")) == before
        finally:
            release_body.set()


@pytest.mark.asyncio
async def test_http_compression_rejected_before_eager_decompression(
    azure, connector, monkeypatch
):
    from aiohttp.compression_utils import ZLibDecompressor
    from azure_bot_native_support import platform_module

    # The encoded body fits the cap, so checking its wire size alone cannot
    # satisfy the refusal of compressed HTTP representations.
    monkeypatch.setattr(
        platform_module, "DOWNLOAD_MAX_BYTES", 64, raising=False
    )
    decompressed = []
    real_decompress = ZLibDecompressor.decompress_sync

    def observed_decompress(self, *args, **kwargs):
        decompressed.append(len(args[0]))
        return real_decompress(self, *args, **kwargs)

    monkeypatch.setattr(
        ZLibDecompressor, "decompress_sync", observed_decompress
    )
    body = gzip.compress(b"x" * 4096)
    assert len(body) < 64
    connector.download_handler = streamed_download(
        body, "length", encoding="gzip"
    )
    async with azure() as (driver, _):
        media = driver._platform.media_dir
        before = set(media.rglob("*"))
        part = await driver._platform._attachment(
            {
                "contentUrl": "https://media.test/download/compressed",
                "contentType": "image/png",
            },
            "secret",
        )
        assert (part, decompressed) == (None, [])
        assert set(media.rglob("*")) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("encoding", [None, "identity"])
async def test_gzip_file_bytes_are_allowed_without_http_compression(
    azure, connector, monkeypatch, encoding
):
    from azure_bot_native_support import platform_module

    body = gzip.compress(b"archive contents")
    monkeypatch.setattr(
        platform_module, "DOWNLOAD_MAX_BYTES", 128, raising=False
    )
    connector.download_handler = streamed_download(
        body, "length", encoding=encoding
    )
    async with azure() as (driver, _):
        part = await driver._platform._attachment(
            {
                "contentUrl": "https://media.test/download/archive",
                "contentType": "application/gzip",
                "name": "archive.gz",
            },
            "secret",
        )
        assert part["type"] == "file"
        assert part["filename"] == "archive.gz"
        assert Path(part["file_url"]).read_bytes() == body

@pytest.mark.asyncio
async def test_unsafe_attachment_never_falls_back_to_untrusted_url(azure):
    async with azure() as (driver, _):
        part = await driver._platform._attachment(
            {
                "contentUrl": "http://media.test/download/image",
                "contentType": "image/png",
            },
            "sensitive-bot-token",
        )
    assert part is None


@pytest.mark.asyncio
async def test_external_attachment_does_not_receive_bot_token(
    azure, connector
):
    async with azure() as (driver, _):
        part = await driver._platform._attachment(
            {
                "contentUrl": "https://media.test/download/image",
                "contentType": "image/png",
            },
            "sensitive-bot-token",
        )
        assert part and Path(part["image_url"]).read_bytes().startswith(
            b"\x89PNG"
        )
    assert connector.requests == [("download", "/download/image", None)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://media.test/download/image",
        "https://user:pass@media.test/download/image",
        "https://@media.test/download/image",
        "https://media.test:444/download/image",
        "https://127.0.0.1/download/image",
        "https://10.0.0.1/download/image",
        "https://169.254.169.254/latest/meta-data",
        "https://[::1]/download/image",
        "https://[fec0::1]/download/image",
        "https://[fecf:abcd::1]/download/image",
        "https://[::ffff:127.0.0.1]/download/image",
        "https://224.0.0.1/download/image",
        "https://[64:ff9b::7f00:1]/download/image",
        "https://[2002:7f00:1::]/download/image",
        "https://[2001:0:4136:e378:8000:63bf:3fff:fdd2]/download/image",
        "file:///etc/passwd",
    ],
)
async def test_unsafe_url_is_rejected_before_dns_or_socket(
    azure, connector, url
):
    async with azure() as (driver, _):
        result = await driver._platform._attachment(
            {"contentUrl": url, "contentType": "image/png"}, "secret"
        )
        assert result is None
        assert connector.dns_calls == connector.connections == []
        assert connector.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "addresses",
    [
        ["127.0.0.1"],
        ["10.3.2.1"],
        ["169.254.169.254"],
        ["::1"],
        ["fc00::1"],
        ["fec0::1"],
        ["fecf:abcd::1"],
        ["::ffff:127.0.0.1"],
        ["93.184.216.34", "127.0.0.1"],
        ["127.0.0.1", "93.184.216.34"],
        ["93.184.216.34", "fc00::1"],
        ["224.0.0.1"],
    ],
)
async def test_private_or_mixed_dns_cannot_download(
    azure, connector, addresses
):
    connector.dns_answers["media.test"] = addresses
    async with azure() as (driver, _):
        result = await driver._platform._attachment(
            {
                "contentUrl": "https://media.test/download/image",
                "contentType": "image/png",
            },
            "secret",
        )
        assert result is None
        assert connector.dns_calls == ["media.test"]
        assert connector.connections == connector.requests == []


@pytest.mark.asyncio
async def test_rebinding_cannot_replace_validated_socket_ip(azure, connector):
    answers = iter([["93.184.216.34"], ["127.0.0.1"]])
    connector.dns_answers["media.test"] = lambda: next(answers)
    async with azure() as (driver, _):
        result = await driver._platform._attachment(
            {
                "contentUrl": "https://media.test/download/image",
                "contentType": "image/png",
            },
            "secret",
        )
        assert result and Path(result["image_url"]).read_bytes() == (
            b"\x89PNG\r\n\x1a\nimage"
        )
        assert connector.dns_calls == ["media.test"]
        assert connector.connections == [("93.184.216.34", 443)]
        assert connector.requests == [("download", "/download/image", None)]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["redirect", "missing"])
async def test_redirect_and_failed_download_never_escape_as_raw_url(
    azure, connector, path
):
    async with azure() as (driver, _):
        result = await driver._platform._attachment(
            {
                "contentUrl": "https://media.test/download/" + path,
                "contentType": "image/png",
            },
            "secret",
        )
        assert result is None
    assert connector.requests == [("download", "/download/" + path, None)]


@pytest.mark.asyncio
async def test_signed_connector_origin_retains_authenticated_download(
    azure, connector
):
    from azure_bot_native_support import activity, post

    async with azure() as (driver, peer):
        status, _ = await post(
            driver,
            connector,
            activity(
                attachments=[
                    {
                        "contentUrl": "https://connector.test/download/image",
                        "contentType": "image/png",
                    }
                ]
            ),
        )
        assert status == 200
        image = peer.events[0].content_parts[1]
        assert (
            Path(image["image_url"]).read_bytes() == b"\x89PNG\r\n\x1a\nimage"
        )
    assert connector.requests == [
        ("download", "/download/image", "Bearer access-1")
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mime, expected_type, field",
    [
        ("image/png", "image", "image_url"),
        ("video/mp4", "video", "video_url"),
        ("audio/ogg", "audio", "data"),
        ("application/pdf", "file", "file_url"),
    ],
)
async def test_safe_public_media_still_becomes_local_content(
    azure, connector, mime, expected_type, field
):
    async with azure() as (driver, _):
        part = await driver._platform._attachment(
            {
                "contentUrl": "https://media.test/download/image",
                "contentType": mime,
                "name": "../original.bin",
            },
            "secret",
        )
        assert part["type"] == expected_type
        path = Path(part[field])
        assert path.is_relative_to(driver._platform.media_dir)
        assert path.read_bytes() == b"\x89PNG\r\n\x1a\nimage"
        if expected_type == "audio":
            assert part["format"] == "ogg"
        if expected_type == "file":
            assert part["filename"] == "../original.bin"
    assert connector.requests == [("download", "/download/image", None)]


@pytest.mark.asyncio
async def test_inline_data_attachment_stays_nonnetwork(azure, connector):
    value = "data:image/png;base64,aGVsbG8="
    async with azure() as (driver, _):
        result = await driver._platform._attachment(
            {"contentUrl": value, "contentType": "image/png"}, "secret"
        )
        assert result == {"type": "image", "image_url": value}
        assert connector.dns_calls == connector.connections == []
        assert connector.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "host",
    ["api.botframework.com", "smba.trafficmanager.net", "botapi.skype.com"],
)
async def test_known_bot_framework_attachment_host_receives_token(
    azure, connector, host
):
    async with azure() as (driver, _):
        part = await driver._platform._attachment(
            {
                "contentUrl": "https://" + host + "/download/image",
                "contentType": "image/png",
            },
            "secret",
        )
        assert part and Path(part["image_url"]).is_file()
    assert connector.requests == [
        ("download", "/download/image", "Bearer secret")
    ]


@pytest.mark.asyncio
async def test_public_activity_media_survives_bot_credential_failure(
    azure, connector, monkeypatch
):
    from azure_bot_native_support import activity, platform_module, post

    def unavailable_credentials(*args, **kwargs):
        raise RuntimeError("external credential issuer unavailable")

    monkeypatch.setattr(
        platform_module.msal,
        "ConfidentialClientApplication",
        unavailable_credentials,
    )
    async with azure() as (driver, peer):
        status, _ = await post(
            driver,
            connector,
            activity(
                attachments=[
                    {
                        "contentUrl": "https://media.test/download/image",
                        "contentType": "image/png",
                    }
                ]
            ),
        )
        assert status == 200
        assert len(peer.events) == 1
        path = Path(peer.events[0].content_parts[1]["image_url"])
        assert path.read_bytes() == b"\x89PNG\r\n\x1a\nimage"
    assert connector.requests == [("download", "/download/image", None)]
    assert connector.token_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "host",
    ["api.botframework.com.attacker.test", "tenant.blob.core.windows.net"],
)
async def test_public_lookalike_or_azure_tenant_host_gets_no_bot_token(
    azure, connector, host
):
    async with azure() as (driver, _):
        result = await driver._platform._attachment(
            {
                "contentUrl": "https://" + host + "/download/image",
                "contentType": "image/png",
            },
            "secret",
        )
        assert result and Path(result["image_url"]).is_file()
    assert connector.requests == [("download", "/download/image", None)]


@pytest.mark.asyncio
async def test_tls_hostname_mismatch_cannot_be_downloaded(azure, connector):
    async with azure() as (driver, _):
        result = await driver._platform._attachment(
            {
                "contentUrl": "https://mismatch.test/download/image",
                "contentType": "image/png",
            },
            "secret",
        )
        assert result is None
        assert connector.connections == [("93.184.216.34", 443)]
        assert connector.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_stop", [False, True])
async def test_attachment_network_resources_close_after_owned_stop(
    azure, connector, monkeypatch, failed_stop
):
    async with azure() as (driver, _):
        platform = driver._platform
        await platform._attachment(
            {
                "contentUrl": "https://media.test/download/image",
                "contentType": "image/png",
            },
            "secret",
        )
        session = platform._attachment_session
        tcp_connector = session.connector
        dns = platform._attachment_resolver.resolver
        if failed_stop:
            with monkeypatch.context() as patch:

                async def fails(*args):
                    raise RuntimeError("fixture stop failure")

                patch.setattr(type(platform.site), "stop", fails)
                with pytest.raises(RuntimeError, match="fixture stop failure"):
                    await driver.stop()
                assert not session.closed
                assert not dns.closed
        await driver.stop()
        assert session.closed and tcp_connector.closed
        assert dns.closed
        assert platform._attachment_session is None
        assert platform._attachment_resolver is None


@pytest.mark.parametrize(
    "host", ["127.000.000.001", "010.0.0.1", "127.000.0.1", "000.0.0.0"]
)
def test_ambiguous_numeric_host_is_rejected_before_aiohttp_version_checks(
    host,
):
    # aiohttp 3.8 classifies padded IPv4 literals without consulting a resolver.
    from qwenpaw_channel_azure_bot.attachments import attachment_url

    with pytest.raises(ValueError):
        attachment_url("https://" + host + "/download/image")
