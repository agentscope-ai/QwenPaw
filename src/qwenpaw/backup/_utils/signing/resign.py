# -*- coding: utf-8 -*-
"""Streaming zip rewriter for inserting a local backup signature.

Used after the user explicitly trusts a foreign or legacy backup. Rewriting
meta.json with a local signature turns that one archive into a locally trusted
backup without weakening signature checks for future imports/restores.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

from ...models import BackupMeta
from ..constants import META_FILE
from .digest import compute_signature

_CHUNK_SIZE = 1024 * 1024


def _copy_entry(
    src: zipfile.ZipFile,
    out: zipfile.ZipFile,
    info: zipfile.ZipInfo,
) -> None:
    """Copy one zip entry while leaving meta.json to be regenerated."""
    if info.filename == META_FILE:
        return
    if info.is_dir():
        out.writestr(info, b"")
        return
    with src.open(info) as in_fh, out.open(info, "w") as out_fh:
        while chunk := in_fh.read(_CHUNK_SIZE):
            out_fh.write(chunk)


def replace_meta_with_local_signature(
    src_zip: Path,
    new_meta: BackupMeta,
    dest_zip: Path | None = None,
) -> BackupMeta:
    """Rewrite *src_zip* with a locally signed meta.json.

    When *dest_zip* is omitted the source zip is replaced in place.
    """
    dest = dest_zip or src_zip
    tmp = dest.with_name(dest.name + ".resign.tmp")
    tmp.unlink(missing_ok=True)

    meta = new_meta.model_copy(update={"signature": None})
    with zipfile.ZipFile(src_zip, "r") as zf:
        signature = compute_signature(zf, meta)
    meta = meta.model_copy(update={"signature": signature})

    try:
        with zipfile.ZipFile(src_zip, "r") as src, zipfile.ZipFile(
            tmp,
            "w",
            zipfile.ZIP_DEFLATED,
        ) as out:
            out.writestr(META_FILE, meta.model_dump_json(indent=2))
            for info in src.infolist():
                _copy_entry(src, out, info)
        tmp.replace(dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise

    return meta
