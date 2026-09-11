# -*- coding: utf-8 -*-
# flake8: noqa: E501
# Vendored from Qwen-MM-Plugins (Apache-2.0), release commit 077aea6.
# Upstream path:
#   src/capabilities/core/qwen_media_toolkit_core/renderers/office.py
# Modified for QwenPaw Creator. See backend/vendor/NOTICE.md.
"""Render Office documents (DOC/DOCX, PPT/PPTX, VSDX) via LibreOffice -> PDF -> pypdfium2.

Creator modifications: the LibreOffice executable is passed in explicitly by
the caller (resolved through Creator's runtime-dependency layer) and the
intermediate PDF lives in a caller-owned temp dir instead of a shared cache.
"""

from __future__ import annotations

import os
import shutil
import subprocess  # nosec B404 - fixed argv, no shell
import tempfile
from typing import Any

LIBREOFFICE_INSTALL_HINT = (
    "LibreOffice is required for this file type. Install: "
    "apt install libreoffice   |   brew install --cask libreoffice"
)


def convert_to_pdf(path: str, soffice: str, dest_pdf: str) -> None:
    """Convert `path` to `dest_pdf` via a headless LibreOffice run."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Isolated LibreOffice user profile to avoid lock conflicts.
        profile = (
            "-env:UserInstallation="
            f"file://{os.path.join(tmpdir, 'lo_profile')}"
        )
        cmd = [
            soffice,
            "--headless",
            "--norestore",
            profile,
            "--convert-to",
            "pdf",
            "--outdir",
            tmpdir,
            path,
        ]
        proc = subprocess.run(  # nosec B603
            cmd,
            capture_output=True,
            text=True,
            # First-ever launch on macOS includes the Gatekeeper scan of the
            # whole app bundle, which alone can take >80s.
            timeout=180,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"LibreOffice conversion failed: {proc.stderr.strip()}",
            )

        pdfs = [f for f in os.listdir(tmpdir) if f.endswith(".pdf")]
        if not pdfs:
            raise RuntimeError("LibreOffice produced no PDF output")

        shutil.copy2(os.path.join(tmpdir, pdfs[0]), dest_pdf)


def render(path: str, **opts: Any) -> list[dict[str, Any]]:
    from vendor.media_toolkit.renderers.pdf import render as pdf_render

    opts.setdefault(
        "doc_type",
        os.path.splitext(path)[1].lstrip(".").upper() or "DOC",
    )

    soffice = opts.pop("soffice", None)
    if not soffice:
        if os.path.splitext(path)[1].lower() == ".xlsx":
            from vendor.media_toolkit.renderers.data import (
                render as data_render,
            )

            return data_render(path, **opts)
        raise RuntimeError(LIBREOFFICE_INSTALL_HINT)

    with tempfile.TemporaryDirectory() as workdir:
        out_pdf = os.path.join(workdir, "converted.pdf")
        convert_to_pdf(path, soffice, out_pdf)
        return pdf_render(out_pdf, **opts)
