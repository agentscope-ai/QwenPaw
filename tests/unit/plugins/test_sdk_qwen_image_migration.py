# -*- coding: utf-8 -*-
"""The shipped Qwen-Image plugin uses public settings and owned media IO."""

import asyncio
from dataclasses import asdict
from pathlib import Path
import threading
from types import SimpleNamespace
from urllib.parse import urlparse
from urllib.request import url2pathname

import dashscope
import httpx
import pytest

from qwenpaw.plugins.compliance import check_plugin
from qwenpaw.plugins.testing import PluginTestHost


PLUGIN = Path(__file__).resolve().parents[3] / "plugins/tool/qwen-image"


@pytest.fixture(autouse=True)
def preserve_dashscope_endpoint(monkeypatch):
    monkeypatch.setattr(
        dashscope,
        "base_http_api_url",
        dashscope.base_http_api_url,
    )


def response(*urls):
    return SimpleNamespace(
        status_code=200,
        output=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=[{"image": url} for url in urls],
                    ),
                ),
            ],
        ),
    )


def test_shipped_tool_uses_only_public_sdk():
    report = check_plugin(PLUGIN)
    assert (report.compatibility, report.findings) == ("compatible", ())


async def test_generate_and_edit_keep_independent_tool_settings(
    tmp_path,
    monkeypatch,
):
    calls = []

    def model(**kwargs):
        calls.append(kwargs)
        return response("https://images.invalid/result.png")

    monkeypatch.setattr(dashscope.MultiModalConversation, "call", model)
    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=b"image-bytes"),
    )
    reference = tmp_path / "reference.png"
    reference.write_bytes(b"reference")
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(PLUGIN)
        for name, key, model_id in (
            ("generate_image_qwen", "generate-key", "qwen-image-2.0-pro"),
            ("edit_image_qwen", "edit-key", "qwen-image-edit-max"),
        ):
            await host.configure_tool(
                name,
                {
                    "api_key": key,
                    "model": model_id,
                    "timeout": 90,
                    "endpoint": "https://models.invalid/api/v1",
                },
            )
        monkeypatch.setattr(
            httpx,
            "AsyncClient",
            lambda **kwargs: original_client(transport=transport, **kwargs),
        )
        generated = await host.call_tool(
            "generate_image_qwen",
            {"prompt": "a tree"},
        )
        edited = await host.call_tool(
            "edit_image_qwen",
            {
                "prompt": "make it blue",
                "reference_images": [str(reference)],
            },
        )
        assert calls == [
            {
                "api_key": "generate-key",
                "model": "qwen-image-2.0-pro",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"text": "a tree"},
                        ],
                    },
                ],
                "result_format": "message",
                "stream": False,
                "watermark": False,
                "prompt_extend": True,
                "n": 1,
                "size": "2048*2048",
            },
            {
                "api_key": "edit-key",
                "model": "qwen-image-edit-max",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"image": "data:image/png;base64,cmVmZXJlbmNl"},
                            {"text": "make it blue"},
                        ],
                    },
                ],
                "result_format": "message",
                "stream": False,
                "watermark": False,
                "prompt_extend": True,
                "n": 1,
            },
        ]
        for result, label, model_id, prompt, details in (
            (
                generated,
                "Generated",
                "qwen-image-2.0-pro",
                "a tree",
                "Size: 2048*2048, Count: 1",
            ),
            (
                edited,
                "Edited",
                "qwen-image-edit-max",
                "make it blue",
                "Reference images: 1",
            ),
        ):
            attachment = result.content[0].attachment
            assert attachment is not None
            file = Path(url2pathname(urlparse(attachment.url).path))
            assert file.is_relative_to(host.root)
            assert file.read_bytes() == b"image-bytes"
            assert attachment.mime_type == "image/png"
            assert attachment.preview_url
            assert (result.is_error, result.metadata) == (False, {})
            assert [asdict(block) for block in result.content] == [
                {
                    "type": "image",
                    "text": "",
                    "attachment": asdict(attachment),
                    "id": "",
                    "name": "",
                    "arguments": "",
                    "output": (),
                    "state": "",
                    "metadata": {},
                    "attributes": {},
                },
                {
                    "type": "text",
                    "text": (
                        f"{label} 1 image(s) using Qwen-Image\n"
                        f"Model: {model_id}\nPrompt: {prompt}\n"
                        f"{details}\nSaved to: {attachment.url}"
                    ),
                    "attachment": None,
                    "id": "",
                    "name": "",
                    "arguments": "",
                    "output": (),
                    "state": "",
                    "metadata": {},
                    "attributes": {},
                },
            ]


async def test_download_failure_keeps_remote_image(tmp_path, monkeypatch):
    monkeypatch.setattr(
        dashscope.MultiModalConversation,
        "call",
        lambda **kwargs: response("https://images.invalid/result.png"),
    )
    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(503))
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(PLUGIN)
        await host.configure_tool("generate_image_qwen", {"api_key": "key"})
        monkeypatch.setattr(
            httpx,
            "AsyncClient",
            lambda **kwargs: original_client(transport=transport, **kwargs),
        )
        result = await host.call_tool("generate_image_qwen", {"prompt": "x"})
        assert (result.is_error, asdict(result.content[0].attachment)) == (
            False,
            {
                "url": "https://images.invalid/result.png",
                "mime_type": "image/png",
                "name": "",
                "preview_url": "",
            },
        )


async def test_cancelled_tool_does_not_release_live_model_thread(
    tmp_path,
    monkeypatch,
):
    entered, finished = asyncio.Event(), threading.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    def model(**kwargs):
        loop.call_soon_threadsafe(entered.set)
        try:
            if not release.wait(10):
                raise TimeoutError("Test did not release the model")
            return response()
        finally:
            finished.set()

    monkeypatch.setattr(dashscope.MultiModalConversation, "call", model)
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(PLUGIN)
        await host.configure_tool("generate_image_qwen", {"api_key": "key"})
        task = asyncio.create_task(
            host.call_tool(
                "generate_image_qwen",
                {"prompt": "x"},
            ),
        )
        try:
            await asyncio.wait_for(entered.wait(), 5)
            task.cancel()
            await asyncio.sleep(0)
            assert not finished.is_set()
        finally:
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert finished.is_set()
