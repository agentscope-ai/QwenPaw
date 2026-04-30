# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from ...constant import SECRET_DIR, WORKING_DIR


def knowledge_base_root() -> Path:
    return WORKING_DIR / "knowledge_base"


def knowledge_meta_path() -> Path:
    return knowledge_base_root() / "meta.json"


def knowledge_conf_path() -> Path:
    return knowledge_base_root() / "conf.json"


def knowledge_secret_path() -> Path:
    return SECRET_DIR / ".knowledge_api_key"


def knowledge_entry_dir(knowledge_id: str) -> Path:
    return knowledge_base_root() / knowledge_id


def knowledge_entry_meta_path(knowledge_id: str) -> Path:
    return knowledge_entry_dir(knowledge_id) / "meta.json"


def knowledge_documents_dir(knowledge_id: str) -> Path:
    return knowledge_entry_dir(knowledge_id) / "documents"


def knowledge_document_dir(knowledge_id: str, document_id: str) -> Path:
    return knowledge_documents_dir(knowledge_id) / document_id


def knowledge_document_meta_path(knowledge_id: str, document_id: str) -> Path:
    return knowledge_document_dir(knowledge_id, document_id) / "meta.json"


def knowledge_document_content_path(knowledge_id: str, document_id: str) -> Path:
    return knowledge_document_dir(knowledge_id, document_id) / "content.txt"


def knowledge_document_chunks_path(knowledge_id: str, document_id: str) -> Path:
    return knowledge_document_dir(knowledge_id, document_id) / "chunks.json"


def knowledge_assets_root() -> Path:
    return WORKING_DIR / "knowledge_assets"


def knowledge_assets_dir(knowledge_id: str) -> Path:
    return knowledge_assets_root() / knowledge_id


def knowledge_document_assets_dir(knowledge_id: str, document_id: str) -> Path:
    return knowledge_assets_dir(knowledge_id) / document_id


def knowledge_assets_date_dir(knowledge_id: str, asset_date: str) -> Path:
    return knowledge_assets_dir(knowledge_id) / asset_date


def legacy_workspace_store_path(workspace_dir: Path) -> Path:
    return workspace_dir / ".knowledge" / "store.json"