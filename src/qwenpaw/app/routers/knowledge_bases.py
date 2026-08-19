# -*- coding: utf-8 -*-
"""Shared knowledge-base management API."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

from ...agents.knowledge.dream import (
    AuditReportSummary,
    InboxActionError,
    InboxItemSummary,
    ack_audit_report,
    get_inbox_item,
    list_audit_reports,
    list_inbox_items,
    merge_inbox_item,
    promote_inbox_item,
    read_audit_report,
    reject_inbox_item,
)
from ...agents.knowledge.store import (
    KnowledgeBaseMeta,
    ensure_kb,
    kb_root,
    list_knowledge_bases,
    validate_kb_id,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])


class CreateKnowledgeBaseRequest(BaseModel):
    """Create a shared knowledge base entity."""

    id: str = Field(..., description="Stable knowledge-base id")
    name: str = Field(default="", description="Display name")
    domain: str = Field(default="business", description="Knowledge domain")
    description: str = Field(default="", description="Optional description")


class KnowledgeBaseListResponse(BaseModel):
    """List of knowledge bases."""

    knowledge_bases: list[KnowledgeBaseMeta]


@router.get("", response_model=KnowledgeBaseListResponse)
async def list_kbs() -> KnowledgeBaseListResponse:
    """List knowledge bases available for agent binding."""
    return KnowledgeBaseListResponse(knowledge_bases=list_knowledge_bases())


@router.post("", response_model=KnowledgeBaseMeta, status_code=201)
async def create_kb(
    request: CreateKnowledgeBaseRequest = Body(...),
) -> KnowledgeBaseMeta:
    """Create a knowledge-base skeleton under WORKING_DIR/knowledge_bases."""
    try:
        kb_id = validate_kb_id(request.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    existing = {item.id for item in list_knowledge_bases()}
    if kb_id in existing:
        raise HTTPException(
            status_code=409,
            detail=f"Knowledge base {kb_id!r} already exists",
        )

    meta = ensure_kb(
        kb_id,
        name=request.name or kb_id,
        domain=request.domain or "business",
        description=request.description,
    )
    logger.info("API created knowledge base %s", kb_id)
    return meta


@router.get("/{kb_id}", response_model=KnowledgeBaseMeta)
async def get_kb(kb_id: str) -> KnowledgeBaseMeta:
    """Return metadata for one knowledge base."""
    try:
        kb_id = validate_kb_id(kb_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    for item in list_knowledge_bases():
        if item.id == kb_id:
            return item
    raise HTTPException(status_code=404, detail=f"Knowledge base {kb_id!r} not found")


# --- audit reports ---------------------------------------------------------


class AuditReportListResponse(BaseModel):
    """List of merge audit reports for a KB."""

    reports: list[AuditReportSummary]


class AuditReportDetailResponse(BaseModel):
    """Full markdown body of one audit report."""

    report_id: str
    body: str


def _validate_kb(kb_id: str) -> str:
    try:
        return validate_kb_id(kb_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/{kb_id}/audit-reports",
    response_model=AuditReportListResponse,
)
async def list_reports(
    kb_id: str,
    needs_review: bool | None = None,
) -> AuditReportListResponse:
    """List merge audit reports for a KB, newest first.

    Pass ``?needs_review=true`` to get only reports still awaiting human
    audit; ``?needs_review=false`` for only reviewed/clean ones; omit for all.
    """
    kb = _validate_kb(kb_id)
    needs_review_only = needs_review is True
    reports = list_audit_reports(kb, needs_review_only=needs_review_only)
    if needs_review is False:
        reports = [r for r in reports if not r.needs_review or r.reviewed]
    return AuditReportListResponse(reports=reports)


@router.get(
    "/{kb_id}/audit-reports/{report_id}",
    response_model=AuditReportDetailResponse,
)
async def get_report(kb_id: str, report_id: str) -> AuditReportDetailResponse:
    """Return the full markdown body of one audit report."""
    kb = _validate_kb(kb_id)
    body = read_audit_report(kb, report_id)
    if body is None:
        raise HTTPException(
            status_code=404,
            detail=f"Audit report {report_id!r} not found in kb {kb!r}",
        )
    return AuditReportDetailResponse(report_id=report_id, body=body)


@router.post(
    "/{kb_id}/audit-reports/{report_id}/ack",
    response_model=AuditReportSummary,
)
async def ack_report(kb_id: str, report_id: str) -> AuditReportSummary:
    """Mark an audit report as reviewed (human acknowledged the merge)."""
    kb = _validate_kb(kb_id)
    summary = ack_audit_report(kb, report_id)
    if summary is None:
        raise HTTPException(
            status_code=404,
            detail=f"Audit report {report_id!r} not found in kb {kb!r}",
        )
    logger.info("API acked audit report %s in kb %s", report_id, kb)
    return summary


# --- inbox (scheme C: human promote / merge / reject) ----------------------


class InboxItemListResponse(BaseModel):
    """Inbox drafts awaiting review or auto-replay."""

    items: list[InboxItemSummary]


class InboxItemDetailResponse(BaseModel):
    """One inbox draft plus its full markdown body."""

    item: InboxItemSummary
    body: str


class InboxActionResponse(BaseModel):
    """Result of promote / merge / reject."""

    path: str
    stem: str


class MergeInboxRequest(BaseModel):
    """Optional override target and merge mode for a human merge."""

    target_path: str = Field(
        default="",
        description="Published node path relative to the KB root",
    )
    mode: str = Field(default="REFINE", description="REFINE or CORRECT")


def _inbox_http(exc: InboxActionError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get("/{kb_id}/inbox", response_model=InboxItemListResponse)
async def list_inbox(kb_id: str) -> InboxItemListResponse:
    """List ``_inbox`` drafts (excludes ``_rejected``), newest first."""
    kb = _validate_kb(kb_id)
    return InboxItemListResponse(items=list_inbox_items(kb))


@router.get("/{kb_id}/inbox/{stem}", response_model=InboxItemDetailResponse)
async def get_inbox(kb_id: str, stem: str) -> InboxItemDetailResponse:
    """Return one inbox draft and its markdown body."""
    kb = _validate_kb(kb_id)
    item = get_inbox_item(kb, stem)
    if item is None:
        raise HTTPException(
            status_code=404,
            detail=f"Inbox item {stem!r} not found in kb {kb!r}",
        )
    root = kb_root(kb)
    path = root / item.path
    try:
        body = path.read_text(encoding="utf-8") if path.is_file() else ""
    except OSError:
        body = ""
    return InboxItemDetailResponse(item=item, body=body)


@router.post(
    "/{kb_id}/inbox/{stem}/promote",
    response_model=InboxActionResponse,
)
async def promote_inbox(
    kb_id: str,
    stem: str,
    agent_id: str = "api",
) -> InboxActionResponse:
    """Publish an inbox draft into its intended bucket as a new node."""
    kb = _validate_kb(kb_id)
    try:
        dest = promote_inbox_item(kb, stem, agent_id=agent_id)
    except InboxActionError as exc:
        raise _inbox_http(exc) from exc
    logger.info("API promoted inbox %s in kb %s → %s", stem, kb, dest)
    return InboxActionResponse(path=str(dest), stem=dest.stem)


@router.post(
    "/{kb_id}/inbox/{stem}/merge",
    response_model=InboxActionResponse,
)
async def merge_inbox(
    kb_id: str,
    stem: str,
    request: MergeInboxRequest | None = Body(default=None),
    agent_id: str = "api",
) -> InboxActionResponse:
    """Merge an inbox draft into a published node (structural, no LLM)."""
    kb = _validate_kb(kb_id)
    payload = request or MergeInboxRequest()
    try:
        dest = merge_inbox_item(
            kb,
            stem,
            agent_id=agent_id,
            target_path=payload.target_path,
            mode=payload.mode,
        )
    except InboxActionError as exc:
        raise _inbox_http(exc) from exc
    logger.info("API merged inbox %s in kb %s → %s", stem, kb, dest)
    return InboxActionResponse(path=str(dest), stem=dest.stem)


@router.post(
    "/{kb_id}/inbox/{stem}/reject",
    response_model=InboxActionResponse,
)
async def reject_inbox(kb_id: str, stem: str) -> InboxActionResponse:
    """Move an inbox draft to ``_inbox/_rejected/`` (not indexed)."""
    kb = _validate_kb(kb_id)
    try:
        dest = reject_inbox_item(kb, stem)
    except InboxActionError as exc:
        raise _inbox_http(exc) from exc
    logger.info("API rejected inbox %s in kb %s → %s", stem, kb, dest)
    return InboxActionResponse(path=str(dest), stem=dest.stem)
