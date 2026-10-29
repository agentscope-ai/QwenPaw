"""资产库与沙箱测试。"""

from __future__ import annotations

from time import perf_counter

import pytest

from airport_sms.execenv import (
    AssetNotFound,
    AssetStore,
    InvalidAssetName,
    RetentionClass,
    Sandbox,
    SandboxAction,
)


def test_no_unsandboxed_rerun() -> None:
    sb = Sandbox()
    d = sb.record_violation("run_code")
    assert d.action is SandboxAction.DENY
    assert d.allow_unsandboxed_rerun is False
    again = sb.check("run_code")
    assert again.action is SandboxAction.DENY
    assert again.allow_unsandboxed_rerun is False


def test_upload_checksum(tmp_path) -> None:
    store = AssetStore(tmp_path)
    meta = store.upload(
        org_id="o", uploader="u", name="a.png", payload=b"abc"
    )
    assert meta.checksum
    assert store.get("o", meta.asset_id) == b"abc"


def test_fetch_bytes(tmp_path) -> None:
    store = AssetStore(tmp_path)
    meta = store.upload(org_id="o", uploader="u", name="a.png", payload=b"xyz")
    assert store.get("o", meta.asset_id) == b"xyz"


def test_cross_org_fails(tmp_path) -> None:
    store = AssetStore(tmp_path)
    meta = store.upload(org_id="o1", uploader="u", name="a.png", payload=b"x")
    with pytest.raises(AssetNotFound):
        store.get("o2", meta.asset_id)


def test_retention_stored(tmp_path) -> None:
    store = AssetStore(tmp_path)
    meta = store.upload(
        org_id="o",
        uploader="u",
        name="a.png",
        payload=b"x",
        retention=RetentionClass.EVIDENCE,
    )
    assert store.meta("o", meta.asset_id).retention is RetentionClass.EVIDENCE


def test_readonly_noop_sandbox() -> None:
    sb = Sandbox()
    d = sb.check("search_manual", readonly=True)
    assert d.action is SandboxAction.ALLOW
    assert d.reason == "noop"


def test_missing_asset(tmp_path) -> None:
    store = AssetStore(tmp_path)
    with pytest.raises(AssetNotFound):
        store.get("o", "missing")


def test_soft_delete(tmp_path) -> None:
    store = AssetStore(tmp_path)
    meta = store.upload(org_id="o", uploader="u", name="a.png", payload=b"x")
    store.soft_delete("o", meta.asset_id)
    with pytest.raises(AssetNotFound):
        store.get("o", meta.asset_id)
    assert store.meta("o", meta.asset_id).deleted is True


def test_gc_dry_run(tmp_path) -> None:
    store = AssetStore(tmp_path)
    meta = store.upload(org_id="o", uploader="u", name="a.png", payload=b"x")
    store.soft_delete("o", meta.asset_id)
    listed = store.gc_candidates(dry_run=True)
    assert any(m.asset_id == meta.asset_id for m in listed)
    assert store.meta("o", meta.asset_id).deleted is True


def test_path_traversal_rejected(tmp_path) -> None:
    store = AssetStore(tmp_path)
    with pytest.raises(InvalidAssetName):
        store.upload(org_id="o", uploader="u", name="../x.png", payload=b"x")


def test_upload_1mb_under_500ms(tmp_path) -> None:
    store = AssetStore(tmp_path)
    payload = b"0" * (1024 * 1024)
    start = perf_counter()
    store.upload(org_id="o", uploader="u", name="big.bin", payload=payload)
    ms = (perf_counter() - start) * 1000
    assert ms < 500, f"{ms:.1f}ms"
