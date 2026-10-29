"""证据资产库：不可变 blob，与工具沙箱分离。"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class RetentionClass(str, Enum):
    """保留级别。"""

    STANDARD = "standard"
    EVIDENCE = "evidence"
    TRANSIENT = "transient"


class AssetNotFound(Exception):
    """资产不存在或跨租户。"""


class InvalidAssetName(Exception):
    """路径穿越或非法名。"""


_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True)
class AssetMeta:
    """资产元数据。"""

    asset_id: str
    checksum: str
    org_id: str
    uploader: str
    retention: RetentionClass
    size: int
    deleted: bool = False


class AssetStore:
    """本地目录资产存储。"""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        self._meta: dict[str, AssetMeta] = {}
        self._blobs: dict[str, bytes] = {}

    def upload(
        self,
        *,
        org_id: str,
        uploader: str,
        name: str,
        payload: bytes,
        retention: RetentionClass = RetentionClass.EVIDENCE,
    ) -> AssetMeta:
        """上传证据，返回 id 与校验和。"""
        if ".." in name or "/" in name or "\\" in name or not _SAFE_NAME.match(name):
            raise InvalidAssetName(name)
        checksum = hashlib.sha256(payload).hexdigest()
        asset_id = checksum[:16]
        meta = AssetMeta(
            asset_id=asset_id,
            checksum=checksum,
            org_id=org_id,
            uploader=uploader,
            retention=retention,
            size=len(payload),
        )
        self._meta[asset_id] = meta
        self._blobs[asset_id] = payload
        (self._root / asset_id).write_bytes(payload)
        return meta

    def get(self, org_id: str, asset_id: str) -> bytes:
        """按组织读取字节。"""
        meta = self._meta.get(asset_id)
        if meta is None or meta.org_id != org_id or meta.deleted:
            raise AssetNotFound(asset_id)
        return self._blobs[asset_id]

    def meta(self, org_id: str, asset_id: str) -> AssetMeta:
        """读取元数据。"""
        meta = self._meta.get(asset_id)
        if meta is None or meta.org_id != org_id:
            raise AssetNotFound(asset_id)
        return meta

    def soft_delete(self, org_id: str, asset_id: str) -> AssetMeta:
        """软删除；blob 保留至 GC。"""
        meta = self.meta(org_id, asset_id)
        updated = AssetMeta(
            asset_id=meta.asset_id,
            checksum=meta.checksum,
            org_id=meta.org_id,
            uploader=meta.uploader,
            retention=meta.retention,
            size=meta.size,
            deleted=True,
        )
        self._meta[asset_id] = updated
        return updated

    def gc_candidates(self, *, dry_run: bool = True) -> list[AssetMeta]:
        """列出已软删候选。dry_run 不真正清除。"""
        candidates = [m for m in self._meta.values() if m.deleted]
        if not dry_run:
            for m in candidates:
                self._blobs.pop(m.asset_id, None)
                path = self._root / m.asset_id
                if path.exists():
                    path.unlink()
                self._meta.pop(m.asset_id, None)
        return candidates


__all__ = [
    "AssetMeta",
    "AssetNotFound",
    "AssetStore",
    "InvalidAssetName",
    "RetentionClass",
]
