# -*- coding: utf-8 -*-
"""DOC parser bridge for knowledge import."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..exceptions import KnowledgeError
from ..models import ParsedDocument
from .docx_parser import DocxParser


class DocParser:
    """Parser for legacy DOC files via soffice conversion."""

    supported_suffixes = (".doc",)

    def parse(self, path: Path) -> ParsedDocument:
        soffice_cmd = _resolve_soffice_cmd()
        if not soffice_cmd:
            raise KnowledgeError(
                "LibreOffice soffice is required "
                "for DOC knowledge import support",
            )

        with tempfile.TemporaryDirectory(prefix="copaw-kb-doc-") as tmp_dir:
            out_dir = Path(tmp_dir)
            result = subprocess.run(
                [
                    soffice_cmd,
                    "--headless",
                    "--convert-to",
                    "docx",
                    "--outdir",
                    str(out_dir),
                    str(path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                detail = (
                    (result.stderr or "").strip()
                    or (result.stdout or "").strip()
                    or f"exit code {result.returncode}"
                )
                raise KnowledgeError(
                    f"Failed to convert DOC with soffice: {detail}",
                )

            converted_path = _resolve_converted_docx_path(out_dir, path)
            parsed = DocxParser().parse(converted_path)

        metadata = dict(parsed.metadata or {})
        metadata["converted_via"] = "soffice"
        metadata["converted_from"] = ".doc"
        return ParsedDocument(
            title=parsed.title,
            source_path=str(path),
            source_type="doc",
            raw_text=parsed.raw_text,
            metadata=metadata,
        )


def _resolve_soffice_cmd() -> str | None:
    cmd = shutil.which("soffice")
    if cmd:
        return cmd

    if platform.system() != "Windows":
        return None

    for candidate in ("soffice.com", "soffice.exe"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved

    for program_dir in (
        os.environ.get("PROGRAMFILES", r"C:\Program Files"),
        os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
    ):
        if not program_dir:
            continue
        install_dir = Path(program_dir) / "LibreOffice" / "program"
        for exe_name in ("soffice.com", "soffice.exe"):
            candidate = install_dir / exe_name
            if candidate.exists():
                return str(candidate)
    return None


def _resolve_converted_docx_path(out_dir: Path, source_path: Path) -> Path:
    preferred = out_dir / f"{source_path.stem}.docx"
    if preferred.exists() and preferred.is_file():
        return preferred

    candidates = sorted(
        path for path in out_dir.glob("*.docx") if path.is_file()
    )
    if len(candidates) == 1:
        return candidates[0]

    raise KnowledgeError(
        "Failed to convert DOC with soffice: converted DOCX not found",
    )
