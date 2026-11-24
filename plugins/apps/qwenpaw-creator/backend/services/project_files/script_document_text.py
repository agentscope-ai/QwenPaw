# -*- coding: utf-8 -*-
"""DOCX/PDF 剧本的正文抽取：让文档剧本也能直登，而不是逐页当图片理解。

体验官自带的剧本常常存在 Word 或 PDF 里。直登此前只接受 UTF-8 文本，这类
文档只能作为普通素材入库并被逐页 VLM 观察——几十页的剧本能耗到小时级。
文档渲染链路本来就能抽出文字层（office→LibreOffice→PDF→pypdfium2），这里
把它复用成一次「只抽正文、不渲染页图」的调用，抽出的正文再交给
:func:`~services.project_files.script_import.publish_script_import` 落版本。

抽取不到就显式失败，绝不静默登记半份剧本：没有文字层的扫描件、缺
LibreOffice、转换超时、页数被渲染器截断，都要求回到素材理解链路或换一种
文件格式。
"""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
import tempfile

from domain.errors import ValidationError

from .script_import import ScriptImportError

# 只放开确实带文字层、且渲染链路能直接抽出的文档格式。ppt/pptx 是幻灯片、
# xlsx/csv 走 data 渲染器，语义都不是剧本，放开只会得到奇怪的正文。
SCRIPT_IMPORT_DOCUMENT_SUFFIXES = (".pdf", ".doc", ".docx")

# 抽正文只需要把上传缓冲一次；上限远高于一份真实剧本文档，又不至于让一个
# 误传的大文件占住内存。
SCRIPT_IMPORT_DOCUMENT_MAX_BYTES = 32 * 1024 * 1024

# 少于这个字符数说明抽到的只是封面或扫描噪点，不是剧本正文。
SCRIPT_IMPORT_DOCUMENT_MIN_CHARS = 40

# pdf 渲染器给每页正文加的定位前缀，不应留在剧本正文里。
_PAGE_MARKER_PATTERN = re.compile(r"^\[Page \d+\]$")
_BLANK_RUN_PATTERN = re.compile(r"\n{3,}")


def is_script_document_name(name: str) -> bool:
    """True when this file name is a document we can extract a script from."""

    return Path(name or "").suffix.lower() in SCRIPT_IMPORT_DOCUMENT_SUFFIXES


def extract_script_document_text(data: bytes, *, name: str) -> str:
    """抽出 DOCX/PDF 的正文，返回可直接登记的剧本文本。

    同步阻塞（LibreOffice 是子进程、pdfium 是 CPU 活），调用方负责放到线程
    里执行。
    """

    suffix = Path(name or "script").suffix.lower()
    if suffix not in SCRIPT_IMPORT_DOCUMENT_SUFFIXES:
        raise ScriptImportError(
            f"{name or '该文件'} 不是可抽正文的剧本文档"
            f"（支持 {', '.join(SCRIPT_IMPORT_DOCUMENT_SUFFIXES)}）。",
            code="SCRIPT_IMPORT_DOCUMENT_UNSUPPORTED",
        )
    if not data:
        raise ScriptImportError(
            f"{name or '剧本文档'} 内容为空，无法抽取正文。",
            code="SCRIPT_IMPORT_DOCUMENT_NO_TEXT",
        )
    # 固定文件名：上传名只用于报错文案，绝不参与落盘路径。
    with tempfile.TemporaryDirectory(prefix="creator-script-doc-") as work:
        document = Path(work) / f"script-import{suffix}"
        document.write_bytes(data)
        try:
            from services.document_reader import read_document_text

            result = read_document_text(document)
        except ValidationError as error:
            raise ScriptImportError(
                f"{name} 无法抽取正文：{error}。请把它作为素材上传走文档"
                "理解，或另存为 UTF-8 的 .md/.txt 后直登。",
                code="SCRIPT_IMPORT_DOCUMENT_UNREADABLE",
            ) from error
        except subprocess.TimeoutExpired as error:
            # 渲染器给 LibreOffice 子进程设了 180s 上限，而 macOS 首次启动
            # 光 Gatekeeper 扫描就可能超过 80s。这是「太慢」而不是「缺
            # 依赖」，必须单独一档：套用缺依赖的文案会叫用户去装一个
            # 已经装好的东西，而它真正需要的只是重试。
            raise ScriptImportError(
                f"{name} 转换超时，未能在限定时间内抽出正文。可以重试"
                "一次（首次启动 LibreOffice 明显更慢），或把它作为素材"
                "上传走文档理解，或另存为 .md/.txt 后直登。",
                code="SCRIPT_IMPORT_DOCUMENT_TIMEOUT",
            ) from error
        except (ImportError, RuntimeError, OSError) as error:
            raise ScriptImportError(
                f"{name} 抽取正文失败：{error}。当前部署缺少文档解析依赖"
                "（PDF 需要 pypdfium2，Word 需要 LibreOffice）；请把它作为"
                "素材上传走文档理解，或另存为 .md/.txt 后直登。",
                code="SCRIPT_IMPORT_DOCUMENT_UNREADABLE",
            ) from error
    return _clean_document_script_text(
        result.indexed_text,
        complete=result.extraction_complete,
        notes=result.notes,
        unextractable_pages=result.unextractable_pages,
        name=name,
    )


def _clean_document_script_text(
    indexed_text: str,
    *,
    complete: bool,
    notes: tuple[str, ...],
    unextractable_pages: tuple[int, ...],
    name: str,
) -> str:
    """Drop renderer scaffolding and refuse anything that is not a script."""

    if not complete:
        detail = "; ".join(note for note in notes if note) or "超出页数上限"
        raise ScriptImportError(
            f"{name} 的正文抽取不完整（{detail}）：不能只登记半份剧本。"
            "请拆分文档后分别导入，或把它作为素材上传走文档理解。",
            code="SCRIPT_IMPORT_DOCUMENT_TRUNCATED",
        )
    if unextractable_pages:
        # 有可见内容却抽不出文字层的页（扫描页/图片页、文字被转曲成矢量
        # 轮廓，或该页文字提取失败）：直登只登记文字层，这些页的正文会被
        # 静默丢掉。全局字符数再多也证明不了它们有正文，所以逐页拒绝并指
        # 路。空白页不进这里，正常带空白页的文档不会被误拒。
        pages = "、".join(str(page) for page in unextractable_pages)
        raise ScriptImportError(
            f"{name} 的第 {pages} 页有可见内容却抽不出文字层（扫描页/图片页、"
            "文字被转曲成矢量轮廓，或该页文字提取失败）：直登只会登记文字层，"
            "这些页的正文会被静默丢掉。请把它作为素材上传走文档理解（含图片/"
            "OCR 理解）或人工确认，或把这些页另存为可复制文字的文档后再直登。",
            code="SCRIPT_IMPORT_DOCUMENT_IMAGE_PAGE",
        )
    lines = [
        line
        for line in indexed_text.replace("\r\n", "\n").split("\n")
        if not _PAGE_MARKER_PATTERN.match(line.strip())
    ]
    text = _BLANK_RUN_PATTERN.sub("\n\n", "\n".join(lines)).strip()
    if len(text) < SCRIPT_IMPORT_DOCUMENT_MIN_CHARS:
        raise ScriptImportError(
            f"{name} 抽不出可用正文（仅 {len(text)} 字符）：扫描件或图片型 "
            "PDF 没有文字层。请把它作为素材上传走文档理解，或另存为可复制"
            "文字的 .docx/.md 后直登。",
            code="SCRIPT_IMPORT_DOCUMENT_NO_TEXT",
        )
    return text


__all__ = [
    "SCRIPT_IMPORT_DOCUMENT_MAX_BYTES",
    "SCRIPT_IMPORT_DOCUMENT_MIN_CHARS",
    "SCRIPT_IMPORT_DOCUMENT_SUFFIXES",
    "extract_script_document_text",
    "is_script_document_name",
]
