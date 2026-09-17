# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=too-many-branches
# Vendored from Qwen-MM-Plugins (Apache-2.0), release commit 077aea6.
# Upstream path:
#   src/capabilities/core/qwen_media_toolkit_core/renderers/notebook.py
# Modified for QwenPaw Creator. See backend/vendor/NOTICE.md.
"""Render Jupyter notebooks (.ipynb) as interleaved text + image blocks.

Creator modifications: cell output images are decoded to PIL images instead
of base64 passthrough; the leading block is a meta block.
"""

from __future__ import annotations

import base64
import io
import os
from typing import Any


def render(path: str, **opts: Any) -> list[dict[str, Any]]:
    try:
        import nbformat
    except ImportError as error:
        raise RuntimeError(
            "Missing dependency nbformat — install with: pip install nbformat",
        ) from error

    from vendor.media_toolkit.renderers import DEFAULT_MAX_PAGES, meta_block

    nb = nbformat.read(path, as_version=4)

    max_images = opts.get("max_pages", DEFAULT_MAX_PAGES)

    code_cells = sum(1 for c in nb.cells if c.cell_type == "code")
    md_cells = sum(1 for c in nb.cells if c.cell_type == "markdown")
    kernel = (
        nb.metadata.get("kernelspec", {}).get("display_name")
        or nb.metadata.get("kernelspec", {}).get("name")
        or ""
    )

    parts = [
        f"Notebook: {os.path.basename(path)}",
        f"{code_cells} code cells, {md_cells} markdown cells",
    ]
    if kernel:
        parts.append(kernel)
    summary = " | ".join(parts)

    result: list[dict[str, Any]] = [{"type": "text", "text": summary}]
    images_emitted = 0
    images_truncated = False
    for cell in nb.cells:
        if cell.cell_type == "markdown":
            text = cell.source.strip()
            if text:
                result.append({"type": "text", "text": text})

        elif cell.cell_type == "code":
            source = cell.source.strip()
            if source:
                exec_count = cell.get("execution_count", " ")
                header = f"In [{exec_count or ' '}]"
                result.append(
                    {
                        "type": "text",
                        "text": f"{header}:\n```python\n{source}\n```",
                    },
                )

            for block in _output_blocks(cell):
                if block["type"] == "image":
                    if images_emitted >= max_images:
                        images_truncated = True
                        continue
                    images_emitted += 1
                    block["page"] = images_emitted
                result.append(block)

    if images_truncated:
        result.append(
            {
                "type": "text",
                "text": (
                    f"... (image outputs capped at {max_images}; "
                    "raise max_pages for more)"
                ),
            },
        )

    if len(result) == 1 and not result[0]["text"]:
        raise ValueError("No renderable cells found in notebook")

    pages = list(range(1, images_emitted + 1))
    return [meta_block("ipynb", images_emitted or 1, pages), *result]


def _output_blocks(cell) -> list[dict[str, Any]]:
    """Extract a code cell's outputs as content blocks."""
    from PIL import Image

    items: list[dict[str, Any]] = []
    for output in cell.get("outputs", []):
        out_type = output.get("output_type", "")

        if out_type == "stream":
            text = output.get("text", "")
            if isinstance(text, list):
                text = "".join(text)
            text = text.strip()
            if text:
                if len(text) > 2000:
                    text = text[:2000] + "\n... (truncated)"
                name = output.get("name", "stdout")
                items.append({"type": "text", "text": f"[{name}]\n{text}"})
            continue

        if out_type == "error":
            ename = output.get("ename", "Error")
            evalue = output.get("evalue", "")
            items.append(
                {"type": "text", "text": f"[error] {ename}: {evalue}"},
            )
            continue

        data = output.get("data", {})

        for mime in ("image/png", "image/jpeg", "image/gif"):
            if mime in data:
                img_b64 = data[mime]
                if isinstance(img_b64, list):
                    img_b64 = "".join(img_b64)
                try:
                    img_bytes = base64.b64decode(img_b64)
                    img = Image.open(io.BytesIO(img_bytes))
                    items.append(
                        {
                            "type": "image",
                            "image": img,
                            "label": "[Notebook Output]",
                        },
                    )
                except Exception:  # pylint: disable=broad-except
                    pass
                break
        else:
            if "text/plain" in data:
                text = data["text/plain"]
                if isinstance(text, list):
                    text = "".join(text)
                text = text.strip()
                if text:
                    if len(text) > 2000:
                        text = text[:2000] + "\n... (truncated)"
                    items.append({"type": "text", "text": f"Out: {text}"})

    return items
