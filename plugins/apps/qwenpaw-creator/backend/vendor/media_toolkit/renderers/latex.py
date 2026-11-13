# -*- coding: utf-8 -*-
# flake8: noqa: E501
# Vendored from Qwen-MM-Plugins (Apache-2.0), github/main commit f9d5741.
# Upstream path: src/capabilities/core/qwen_media_toolkit_core/renderers/latex.py
#   (compile-to-PDF-then-render strategy with source fallback).
# Modified for QwenPaw Creator. See backend/vendor/NOTICE.md.
"""Render LaTeX (.tex) files by compiling to PDF then rendering pages.

Falls back to the syntax-highlighted source (the ``code`` renderer) when
no LaTeX toolchain is installed or compilation fails — never a hard error
for a missing optional binary.

Creator modifications: toolchain discovery is a simple ``shutil.which``
probe over tectonic/xelatex/pdflatex (the upstream ``which_tool``/bibtex
pass is dropped — single-pass compilation covers review reading); the
compiled PDF is rendered through this registry's ``pdf`` renderer so page
blocks carry the shared meta + PIL protocol.
"""

from __future__ import annotations

import shutil
import subprocess  # nosec B404 - fixed argv toolchain invocation, no shell
import tempfile
from pathlib import Path
from typing import Any

COMPILE_TIMEOUT_SECONDS = 120

# Probe order: tectonic is self-contained, xelatex handles CJK sources,
# pdflatex is the classic fallback.
_TOOLCHAIN_CANDIDATES = ("tectonic", "xelatex", "pdflatex")


def _find_toolchain() -> tuple[str, list[str]] | None:
    for name in _TOOLCHAIN_CANDIDATES:
        executable = shutil.which(name)
        if not executable:
            continue
        if name == "tectonic":
            return executable, ["--outdir"]
        return executable, ["-interaction=nonstopmode", "-output-directory"]
    return None


def _compile_pdf(tex_path: Path, out_dir: Path) -> Path | None:
    toolchain = _find_toolchain()
    if toolchain is None:
        return None
    executable, out_flag_parts = toolchain
    command = [executable, *out_flag_parts]
    # tectonic takes "--outdir DIR", latex engines take
    # "-output-directory=DIR"-style separate args; normalize both forms.
    if out_flag_parts == ["--outdir"]:
        command = [executable, "--outdir", str(out_dir), str(tex_path)]
    else:
        command = [
            executable,
            "-interaction=nonstopmode",
            f"-output-directory={out_dir}",
            str(tex_path),
        ]
    proc = subprocess.run(  # nosec B603
        command,
        capture_output=True,
        timeout=COMPILE_TIMEOUT_SECONDS,
        check=False,
        stdin=subprocess.DEVNULL,
        cwd=str(tex_path.parent),
    )
    produced = out_dir / (tex_path.stem + ".pdf")
    if proc.returncode != 0 and not produced.is_file():
        return None
    return produced if produced.is_file() else None


def render(path: str, **opts: Any) -> list[dict[str, Any]]:
    from vendor.media_toolkit.renderers import code as code_renderer
    from vendor.media_toolkit.renderers import pdf as pdf_renderer

    tex_path = Path(path)
    with tempfile.TemporaryDirectory(prefix="latex-render-") as tmp:
        try:
            pdf_path = _compile_pdf(tex_path, Path(tmp))
        except Exception:
            pdf_path = None
        if pdf_path is not None:
            blocks = pdf_renderer.render(str(pdf_path), **opts)
            for block in blocks:
                if block.get("type") == "meta":
                    block["format"] = "latex"
            return blocks
    # No toolchain or compilation failed: the highlighted source is still
    # a faithful read of the document (upstream fallback semantics).
    blocks = code_renderer.render(str(tex_path), **opts)
    blocks.append(
        {
            "type": "extraction_note",
            "text": (
                "LaTeX 未编译（缺少 tectonic/xelatex/pdflatex 工具链或编译"
                "失败），以上为源码视图而非排版页面。"
            ),
        },
    )
    return blocks
