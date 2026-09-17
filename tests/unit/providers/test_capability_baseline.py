# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from qwenpaw.providers import capability_baseline
from qwenpaw.providers.capability_baseline import (
    ExpectedCapability,
    ExpectedCapabilityRegistry,
    compare_probe_result,
)

# ---------------------------------------------------------------------------
# ExpectedCapabilityRegistry
# ---------------------------------------------------------------------------


@pytest.fixture()
def registry() -> ExpectedCapabilityRegistry:
    return ExpectedCapabilityRegistry()


def test_registry_loads_baseline() -> None:
    """Baseline file should load and contain at least one entry."""
    reg = ExpectedCapabilityRegistry()
    assert reg._data, "baseline file appears empty or failed to parse"


def test_registry_get_expected_found() -> None:
    reg = ExpectedCapabilityRegistry()
    cap = ExpectedCapability(
        provider_id="synth_provider",
        model_id="synth_model",
        expected_image=True,
        expected_video=False,
    )
    reg._data[(cap.provider_id, cap.model_id)] = cap
    result = reg.get_expected("synth_provider", "synth_model")
    assert result is not None
    assert result.provider_id == "synth_provider"
    assert result.model_id == "synth_model"


def test_registry_get_expected_not_found(
    registry: ExpectedCapabilityRegistry,
) -> None:
    assert registry.get_expected("nonexistent", "model") is None


def test_registry_get_all_for_provider_empty(
    registry: ExpectedCapabilityRegistry,
) -> None:
    assert not registry.get_all_for_provider("no_such_provider")


def test_registry_get_all_for_provider_filters() -> None:
    reg = ExpectedCapabilityRegistry()
    cap1 = ExpectedCapability(
        provider_id="synth_prov",
        model_id="m1",
        expected_image=True,
        expected_video=False,
    )
    cap2 = ExpectedCapability(
        provider_id="synth_prov",
        model_id="m2",
        expected_image=False,
        expected_video=True,
    )
    cap_other = ExpectedCapability(
        provider_id="other_prov",
        model_id="m3",
        expected_image=True,
        expected_video=True,
    )
    reg._data[(cap1.provider_id, cap1.model_id)] = cap1
    reg._data[(cap2.provider_id, cap2.model_id)] = cap2
    reg._data[(cap_other.provider_id, cap_other.model_id)] = cap_other
    caps = reg.get_all_for_provider("synth_prov")
    assert len(caps) >= 2
    assert all(c.provider_id == "synth_prov" for c in caps)


# ---------------------------------------------------------------------------
# compare_probe_result
# ---------------------------------------------------------------------------


def test_compare_no_discrepancy() -> None:
    cap = ExpectedCapability(
        "p",
        "m",
        expected_image=True,
        expected_video=False,
    )
    logs = compare_probe_result(cap, actual_image=True, actual_video=False)
    assert not logs


def test_compare_false_negative() -> None:
    cap = ExpectedCapability(
        "p",
        "m",
        expected_image=True,
        expected_video=None,
    )
    logs = compare_probe_result(cap, actual_image=False, actual_video=False)
    assert len(logs) == 1
    assert logs[0].field == "image"
    assert logs[0].discrepancy_type == "false_negative"
    assert logs[0].expected is True
    assert logs[0].actual is False


def test_compare_false_positive() -> None:
    cap = ExpectedCapability(
        "p",
        "m",
        expected_image=False,
        expected_video=None,
    )
    logs = compare_probe_result(cap, actual_image=True, actual_video=True)
    assert len(logs) == 1
    assert logs[0].field == "image"
    assert logs[0].discrepancy_type == "false_positive"


def test_compare_none_expected_skips() -> None:
    cap = ExpectedCapability(
        "p",
        "m",
        expected_image=None,
        expected_video=None,
    )
    logs = compare_probe_result(cap, actual_image=True, actual_video=True)
    assert not logs


def test_compare_both_fields_discrepant() -> None:
    cap = ExpectedCapability(
        "p",
        "m",
        expected_image=True,
        expected_video=True,
    )
    logs = compare_probe_result(cap, actual_image=False, actual_video=False)
    assert len(logs) == 2
    fields = {log.field for log in logs}
    assert fields == {"image", "video"}


def _write_capability_catalog(
    path: Path,
    capabilities: list[dict[str, object]],
) -> bytes:
    payload = {
        "schema_version": 1,
        "catalog_version": "test",
        "capabilities": capabilities,
    }
    content = json.dumps(payload).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return content


def test_capability_overlays_merge_by_provider_and_model(
    tmp_path: Path,
) -> None:
    packaged = tmp_path / "packaged.json"
    ota = tmp_path / "ota.json"
    local = tmp_path / "local.json"
    _write_capability_catalog(
        packaged,
        [
            {
                "provider_id": "provider",
                "model_id": "model",
                "expected_image": False,
                "expected_video": False,
                "note": "packaged",
            },
        ],
    )
    _write_capability_catalog(
        ota,
        [
            {
                "provider_id": "provider",
                "model_id": "model",
                "expected_image": True,
                "expected_video": False,
                "note": "ota",
            },
        ],
    )
    _write_capability_catalog(
        local,
        [
            {
                "provider_id": "provider",
                "model_id": "model",
                "expected_image": True,
                "expected_video": True,
                "note": "local",
            },
        ],
    )

    registry = ExpectedCapabilityRegistry(packaged, ota, local)
    capability = registry.get_expected("provider", "model")

    assert capability is not None
    assert capability.expected_image is True
    assert capability.expected_video is True
    assert capability.note == "local"


def test_capability_update_validates_hash_and_installs_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.json"
    destination = tmp_path / "cache" / "capabilities.json"
    payload = _write_capability_catalog(source, [])
    monkeypatch.setattr(
        capability_baseline,
        "_download_capability_bytes",
        lambda _url, _timeout: payload,
    )

    document = capability_baseline.update_capability_catalog(
        url="https://example.invalid/capabilities.json",
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        destination=destination,
    )

    assert document.catalog_version == "test"
    assert destination.read_bytes() == payload
    assert not list(destination.parent.glob("*.tmp"))


def test_capability_hash_mismatch_preserves_previous_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "capabilities.json"
    destination.write_bytes(b"previous")
    payload = _write_capability_catalog(tmp_path / "source.json", [])
    monkeypatch.setattr(
        capability_baseline,
        "_download_capability_bytes",
        lambda _url, _timeout: payload,
    )

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        capability_baseline.update_capability_catalog(
            url="https://example.invalid/capabilities.json",
            expected_sha256="0" * 64,
            destination=destination,
        )

    assert destination.read_bytes() == b"previous"


def test_capability_invalid_entry_preserves_previous_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "capabilities.json"
    previous = _write_capability_catalog(destination, [])
    payload = _write_capability_catalog(
        tmp_path / "source.json",
        [
            {
                "provider_id": "provider",
                "model_id": "model",
                "expected_image": "yes",
                "expected_video": False,
            },
        ],
    )
    monkeypatch.setattr(
        capability_baseline,
        "_download_capability_bytes",
        lambda _url, _timeout: payload,
    )

    with pytest.raises(ValueError):
        capability_baseline.update_capability_catalog(
            url="https://example.invalid/capabilities.json",
            destination=destination,
        )

    assert destination.read_bytes() == previous


def test_registry_reload_replaces_snapshot_atomically(tmp_path: Path) -> None:
    packaged = tmp_path / "packaged.json"
    ota = tmp_path / "ota.json"
    local = tmp_path / "local.json"
    _write_capability_catalog(
        packaged,
        [
            {
                "provider_id": "provider",
                "model_id": "model",
                "expected_image": False,
                "expected_video": False,
            },
        ],
    )
    registry = ExpectedCapabilityRegistry(packaged, ota, local)

    _write_capability_catalog(
        ota,
        [
            {
                "provider_id": "provider",
                "model_id": "model",
                "expected_image": True,
                "expected_video": False,
            },
        ],
    )
    registry.reload()

    capability = registry.get_expected("provider", "model")
    assert capability is not None
    assert capability.expected_image is True

    ota.write_text("{invalid", encoding="utf-8")
    with pytest.raises(ValueError):
        registry.reload()

    capability = registry.get_expected("provider", "model")
    assert capability is not None
    assert capability.expected_image is True
