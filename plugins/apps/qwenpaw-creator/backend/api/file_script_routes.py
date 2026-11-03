# -*- coding: utf-8 -*-
"""剧本直登 HTTP 通道：用户写好的剧本正文直接成为 timeline_script 版本。

剧本此前只能作为普通素材入库：文档要逐页 VLM 观察，正文还要主 Agent 把整
份剧本重新抄进 patch 参数，"导入自带剧本"这一步能耗到小时级。这里让前端
剧本页把 UTF-8 正文（.md/.txt 文件或粘贴文本）交给与 Agent 工具同一个服务
端落版本函数——不创建 ProjectSource，因此不触发素材理解，也不经过模型回合。
DOCX/PDF 剧本走同一条路：服务端先抽出文字层（不渲染页图），抽不到就显式
报错让前端回退到素材理解，绝不静默登记半份剧本。

通知语义：与素材入库一致，直登是一次前端编辑提交（``FRONTEND_EDIT`` +
``AUTO_FIX``），不唤醒 Agent；用户下一条消息里 Agent 会读到已选中的剧本，
按 Creator 规则沿用而不是重新起草。剧本变更仍会按既有 ``production_stage``
派生规则要求用户重新确认剧本。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, Request, status
from starlette.datastructures import UploadFile

from domain.errors import (
    ConflictError,
    NotFoundError,
    StorageIntegrityError,
    ValidationError,
)
from services.project_files.assets import AssetFileError
from services.project_files.facade import CreatorFileServices
from services.project_files.script_document_text import (
    SCRIPT_IMPORT_DOCUMENT_MAX_BYTES,
    SCRIPT_IMPORT_DOCUMENT_SUFFIXES,
    extract_script_document_text,
    is_script_document_name,
)
from services.project_files.script_import import (
    SCRIPT_IMPORT_MAX_BYTES,
    ScriptImportError,
    publish_script_import,
)
from services.project_files.store import ProjectSnapshot
from services.runtime_files.models import ChangeOrigin, ReviewPolicy

from .dependencies import CreatorErrorRoute, project_file_services

router = APIRouter(
    prefix="/projects/{project_id}/timelines/{timeline_id}",
    tags=["script-import"],
    route_class=CreatorErrorRoute,
)

# 可作为剧本正文直登的文本后缀。DOCX/PDF 不在这里：它们没有现成的纯文本
# 表示，走 ``script_document_text`` 先抽文字层，抽不出就报错回退素材理解，
# 不能被静默当成乱码剧本。
_SCRIPT_SUFFIXES = (
    ".md",
    ".markdown",
    ".txt",
    ".text",
    ".rst",
    ".srt",
    ".vtt",
)

# Bound the optional retry key like the sibling Project write routes.  It is
# hashed into a deterministic transaction id, never used as a path verbatim,
# and stays optional: without it each import is simply a fresh edit.
_IDEMPOTENCY_KEY_MAX_CHARS = 192


def _looks_like_script_text(*, name: str, media_type: str) -> bool:
    normalized = media_type.split(";", 1)[0].strip().casefold()
    if normalized.startswith("text/") or normalized in {
        "application/markdown",
        "text/markdown",
    }:
        return True
    return name.casefold().endswith(_SCRIPT_SUFFIXES)


def _decode_script_text(payload: bytes, *, name: str) -> str:
    if len(payload) > SCRIPT_IMPORT_MAX_BYTES:
        raise ScriptImportError(
            f"剧本正文 {len(payload)} 字节超过直登上限 "
            f"{SCRIPT_IMPORT_MAX_BYTES} 字节；请按集或场次拆分后分别导入。",
            code="SCRIPT_IMPORT_TOO_LARGE",
        )
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ScriptImportError(
            f"{name or '剧本文件'} 不是 UTF-8 文本，无法直登为剧本；"
            "请另存为 UTF-8 编码的 .md/.txt，或上传 DOCX/PDF 走文档理解。",
            code="SCRIPT_IMPORT_NOT_UTF8",
        ) from error


async def _read_script_payload(request: Request) -> tuple[str, str]:
    """Parse the request into ``(text, source_name)``.

    Every rejection is a ``ScriptImportError`` carrying a ``SCRIPT_IMPORT_*``
    code, never a bare ``ValidationError``: ``_translate`` maps both to 422,
    but only the former keeps its specific code in ``details`` for the client.
    The codes mirror the Agent-side ``import_script`` tool so one failure has
    one identity no matter which entry point hit it.
    """

    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        upload = next(
            (
                value
                for _, value in form.multi_items()
                if isinstance(value, UploadFile)
            ),
            None,
        )
        if upload is None:
            raise ScriptImportError(
                "script-import multipart 请求缺少 file",
                code="SCRIPT_IMPORT_INVALID",
            )
        name = Path(upload.filename or "script.md").name
        document = is_script_document_name(name)
        if not document and not _looks_like_script_text(
            name=name,
            media_type=upload.content_type or "",
        ):
            raise ScriptImportError(
                f"剧本直登只接受 UTF-8 文本（{', '.join(_SCRIPT_SUFFIXES)}）"
                "或可抽正文的文档（"
                f"{', '.join(SCRIPT_IMPORT_DOCUMENT_SUFFIXES)}）；收到 {name}"
                f"（{upload.content_type or '未知类型'}）。",
                code="SCRIPT_IMPORT_NOT_TEXT",
            )
        cap = (
            SCRIPT_IMPORT_DOCUMENT_MAX_BYTES
            if document
            else SCRIPT_IMPORT_MAX_BYTES
        )
        # Read one byte past the cap so an oversized upload is rejected
        # without ever buffering the whole file.
        payload = await upload.read(cap + 1)
        if document:
            if len(payload) > cap:
                raise ScriptImportError(
                    f"{name} 超过文档直登上限 {cap} 字节；请把它作为素材" "上传走文档理解。",
                    code="SCRIPT_IMPORT_TOO_LARGE",
                )
            # LibreOffice/pdfium are blocking work: keep the loop free.
            return (
                await asyncio.to_thread(
                    extract_script_document_text,
                    payload,
                    name=name,
                ),
                name,
            )
        return _decode_script_text(payload, name=name), name
    if content_type.startswith("application/json"):
        body = await request.json()
        if not isinstance(body, dict):
            raise ScriptImportError(
                "script-import JSON 请求必须是对象",
                code="SCRIPT_IMPORT_INVALID",
            )
        content = body.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ScriptImportError(
                "script-import JSON 请求缺少非空 content",
                code="SCRIPT_IMPORT_EMPTY",
            )
        if len(content.encode("utf-8")) > SCRIPT_IMPORT_MAX_BYTES:
            raise ScriptImportError(
                f"粘贴的剧本正文超过直登上限 {SCRIPT_IMPORT_MAX_BYTES} 字节；"
                "请按集或场次拆分后分别导入。",
                code="SCRIPT_IMPORT_TOO_LARGE",
            )
        name = str(body.get("name") or "").strip()[:160]
        return content, name
    raise ScriptImportError(
        "script-import 需要 multipart/form-data 的 file，"
        "或 application/json 的 content 字段。",
        code="SCRIPT_IMPORT_INVALID",
    )


def _translate(error: BaseException) -> None:
    """Map direct-landing failures onto the shared HTTP error vocabulary.

    ``CreatorError.code`` is a class attribute, so the specific script-import
    reason has to ride in ``details`` -- the same channel the sibling Project
    routes use for machine-readable specifics.  Without it every failure
    collapses into ``VALIDATION_ERROR`` and the client cannot tell "retry in a
    moment" apart from "this deployment has no LibreOffice".
    """

    if isinstance(error, ScriptImportError):
        details = {"code": error.code, **error.details}
        if error.code == "SCRIPT_IMPORT_TIMELINE_NOT_FOUND":
            raise NotFoundError(str(error), details=details) from error
        if error.code == "SCRIPT_IMPORT_IDEMPOTENCY_CONFLICT":
            # A reused Idempotency-Key with a different payload is a client
            # conflict, not a validation failure: 409 tells it to mint a new
            # key instead of correcting the body.
            raise ConflictError(str(error), details=details) from error
        raise ValidationError(str(error), details=details) from error
    if isinstance(error, AssetFileError):
        raise StorageIntegrityError(str(error)) from error
    raise error


@router.post("/script-import", status_code=status.HTTP_201_CREATED)
async def import_timeline_script(
    project_id: str,
    timeline_id: str,
    request: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    services: CreatorFileServices = Depends(project_file_services),
) -> dict[str, Any]:
    """把提交的剧本正文登记为这条 Timeline 的当前剧本版本。

    正文可以是 UTF-8 文本（multipart 的 .md/.txt 或 JSON 的 content），
    也可以是 DOCX/PDF：后者先在服务端抽出文字层，抽不出就报错。
    可选的 ``Idempotency-Key`` 只用于识别同一次请求的网络重试；重新
    选用旧稿是一次新编辑，不带该键也会得到全新的事务身份。
    """

    committed: list[ProjectSnapshot] = []
    try:
        key = (idempotency_key or "").strip() or None
        if key is not None and len(key) > _IDEMPOTENCY_KEY_MAX_CHARS:
            raise ValidationError(
                f"Idempotency-Key 最长为 {_IDEMPOTENCY_KEY_MAX_CHARS} 个字符",
            )
        raw_text, source_name = await _read_script_payload(request)
        outcome = await asyncio.to_thread(
            publish_script_import,
            store=services.projects,
            commits=services.commits,
            project_id=project_id,
            timeline_id=timeline_id,
            raw_text=raw_text,
            source_name=source_name,
            idempotency_key=key,
            commit_metadata={
                "origin": ChangeOrigin.FRONTEND_EDIT,
                "review_policy": ReviewPolicy.AUTO_FIX,
                "caused_by_request_id": (
                    f"script-import:{project_id}:{timeline_id}"
                ),
                "advance_accepted_baseline": True,
            },
            observe_snapshot=committed.append,
        )
    except Exception as error:  # noqa: BLE001 - translated below
        _translate(error)
        raise
    if committed:
        services.poller.note_commit(committed[0])
    return outcome.to_payload()


__all__ = ["router"]
