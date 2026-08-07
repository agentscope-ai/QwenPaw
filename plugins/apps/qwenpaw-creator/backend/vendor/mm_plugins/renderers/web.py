# -*- coding: utf-8 -*-
# flake8: noqa: E501
# Vendored from Qwen-MM-Plugins (Apache-2.0), release commit 077aea6.
# Upstream path: src/capabilities/core/qwen_mm_plugins_core/renderers/web.py
# Modified for QwenPaw Creator. See backend/vendor/NOTICE.md.
"""Render local HTML/MHTML files via Playwright headless browser screenshot.

Long pages are split into viewport-sized pages; a short trailing strip is
merged into the last full page.

Creator modifications: only local files are rendered (no URL fetch), page
images are returned as PIL images, and enablement is config-gated by
``services/document_reader.py`` (Playwright is not a declared dependency).
"""

from __future__ import annotations

import io
import os
from typing import Any

# Trailing strip shorter than this fraction of viewport merges into
# previous page.
_MERGE_THRESHOLD = 0.4


def render(path: str, **opts: Any) -> list[dict[str, Any]]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise RuntimeError(
            "Missing dependency playwright — install with: "
            "pip install playwright && playwright install chromium",
        ) from error

    from PIL import Image

    from vendor.mm_plugins.renderers import DEFAULT_MAX_PAGES, meta_block

    budget = opts.get("budget", "large")
    max_pages = opts.get("max_pages", DEFAULT_MAX_PAGES)
    viewport = {
        "small": (800, 600),
        "normal": (1280, 960),
        "large": (1920, 1080),
    }
    vw, vh = viewport.get(budget, (1280, 960))

    url = f"file://{os.path.abspath(path)}"
    label = os.path.basename(path)

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True, channel="chrome")
        except Exception:  # pylint: disable=broad-except
            browser = p.chromium.launch(headless=True)

        page = browser.new_page(viewport={"width": vw, "height": vh})
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2000)

        # Scroll to trigger lazy-loaded content.
        page_height = page.evaluate("document.body.scrollHeight") or vh
        steps = min(int(page_height / vh) + 1, max_pages + 5)
        for i in range(1, steps):
            page.evaluate(f"window.scrollTo(0, {i * vh})")
            page.wait_for_timeout(800)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(1000)

        screenshot_bytes = page.screenshot(full_page=True, type="png")
        browser.close()

    img = Image.open(io.BytesIO(screenshot_bytes))

    # Split into viewport-height pages; merge a short tail into the last.
    cuts = list(range(0, img.height, vh))
    pages = []
    for y in cuts:
        bottom = min(y + vh, img.height)
        remaining = img.height - bottom
        # Extend to end if leftover is too short (avoid thin sliver).
        if 0 < remaining < vh * _MERGE_THRESHOLD:
            bottom = img.height
        pages.append(img.crop((0, y, img.width, bottom)))
        if bottom >= img.height:
            break

    pages = pages[:max_pages]

    # Page-range selection (same syntax as PDF: "1-3", "2", "1,3,5").
    total = len(pages)
    selected = list(range(total))
    pages_str = opts.get("pages")
    if pages_str:
        from vendor.mm_plugins.renderers import parse_pages

        selected = [i for i in parse_pages(pages_str, total) if i < total]
        pages = [pages[i] for i in selected]

    content: list[dict[str, Any]] = [
        meta_block("html", total, [i + 1 for i in selected]),
        {
            "type": "text",
            "text": f"Source: {label} | Total pages: {total}",
        },
    ]
    for i, page_img in zip(selected, pages):
        content.append(
            {
                "type": "image",
                "image": page_img,
                "page": i + 1,
                "label": f"[Page {i + 1} View]",
            },
        )

    return content
