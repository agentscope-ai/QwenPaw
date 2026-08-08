# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Manual real-provider acceptance for Serper grounding.

This opt-in entry point exercises the real Serper ``/search``, ``/images``,
``/lens`` and ``/scrape`` endpoints plus the no-OSS Uguu path. These calls
consume real quota. Every test skips unless
``SERPER_API_KEY`` is exported, so the module stays collectable-but-inert in CI
and in the default local suite.

Run manually::

    SERPER_API_KEY=... pytest tests/manual/test_real_serper_grounding.py -q

``SERPER_LENS_IMAGE_URL`` may override the public reference image used for
the reverse image search case.
"""

from __future__ import annotations

import asyncio
import io
import os

import httpx
import pytest
from PIL import Image

from services.web_grounding.providers import adapters
from services.web_grounding.providers import search as provider_search

pytestmark = pytest.mark.manual_real

requires_serper_key = pytest.mark.skipif(
    not os.environ.get("SERPER_API_KEY"),
    reason="SERPER_API_KEY not configured; manual real-provider run only",
)

DEFAULT_LENS_IMAGE_URL = (
    "https://upload.wikimedia.org/wikipedia/commons/a/a8/"
    "Tour_Eiffel_Wikimedia_Commons.jpg"
)


def _run(coroutine_factory):
    async def runner():
        async with httpx.AsyncClient(timeout=60.0) as client:
            return await coroutine_factory(client)

    return asyncio.run(runner())


@requires_serper_key
def test_real_serper_text_search_returns_relevant_sources():
    results = _run(
        lambda client: adapters._search_serper(
            client,
            "Eiffel Tower construction year",
            3,
        ),
    )

    assert results, "real /search returned no organic results"
    for source in results:
        assert source["provider"] == "serper"
        assert source["url"].startswith(("http://", "https://"))
        assert source["title"]


@requires_serper_key
def test_real_serper_image_search_returns_image_urls():
    results = _run(
        lambda client: adapters._search_serper_visuals(
            client,
            "Eiffel Tower at dusk",
            3,
        ),
    )

    assert results, "real /images returned no image results"
    for source in results:
        assert source["provider"] == "serper"
        assert source["url"].startswith(("http://", "https://"))


@requires_serper_key
def test_real_serper_lens_reverse_image_search():
    image_url = os.environ.get(
        "SERPER_LENS_IMAGE_URL",
        DEFAULT_LENS_IMAGE_URL,
    )
    results = _run(
        lambda client: adapters._search_serper_lens(
            client,
            image_url,
            5,
            query="manual lens acceptance",
        ),
    )

    # Lens recall depends on the reference image; require a well-formed
    # response rather than a minimum match count.
    assert isinstance(results, list)
    for source in results:
        assert source["provider"] == "serper_lens"
        assert source["url"].startswith(("http://", "https://"))


@requires_serper_key
def test_real_serper_scrape_extracts_page_content():
    results = _run(
        lambda client: adapters._extract_serper_pages(
            client,
            ["https://en.wikipedia.org/wiki/Eiffel_Tower"],
            goal="construction year",
        ),
    )

    assert results, "real /scrape returned no content"
    assert results[0]["provider"] == "serper_scrape"
    assert results[0]["content"]
    assert len(results[0]["content"]) <= 8000


@requires_serper_key
def test_real_local_lens_uses_uguu_when_oss_absent(
    monkeypatch,
    tmp_path,
):
    data_root = tmp_path / "creator-data"
    data_root.mkdir()
    reference = data_root / "reference.png"
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), color="red").save(buffer, format="PNG")
    reference.write_bytes(buffer.getvalue())
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(data_root))
    monkeypatch.setenv(
        "CREATOR_MODEL_CONFIG_PATH",
        str(tmp_path / "missing-model-config.json"),
    )
    for name in (
        "OSS_ACCESS_KEY_ID",
        "ALIYUN_ACCESS_KEY_ID",
        "ALIBABA_CLOUD_ACCESS_KEY_ID",
        "OSS_ACCESS_KEY_SECRET",
        "ALIYUN_ACCESS_KEY_SECRET",
        "ALIBABA_CLOUD_ACCESS_KEY_SECRET",
        "OSS_ENDPOINT",
        "ALIYUN_OSS_ENDPOINT",
        "OSS_BUCKET",
        "ALIYUN_OSS_BUCKET",
        "OSS_PUBLIC_BASE_URL",
        "ALIYUN_OSS_PUBLIC_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)

    result = asyncio.run(
        provider_search.search_visual_refs_by_image(
            str(reference),
            query="manual no-OSS Uguu Lens acceptance",
            bbox=[0, 0, 1000, 1000],
            max_sources=3,
        ),
    )

    assert result["image_transport"] == "uguu"
    assert result["providers_attempted"] == ["serper_lens"]
    assert not any("uguu_upload_failed" in issue for issue in result["issues"])
    lens_errors = [
        issue
        for issue in result["issues"]
        if issue.startswith("serper_lens:")
        and issue != "serper_lens:no_visual_sources"
    ]
    assert (
        not lens_errors
    ), f"real Lens call failed after Uguu upload: {lens_errors}"
