# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

import pytest

import qwenpaw.utils.system_info as system_info_module
from qwenpaw.utils.system_info import (
    get_architecture,
    get_system_info,
    get_vram_size_gb,
)

_NVIDIA_SMI_HEADER = (
    "NVIDIA-SMI 560.94    Driver Version: 560.94    CUDA Version: 12.6\n"
)


def _fake_run_command(
    responses: dict[str, str | None],
    calls: list[list[str]],
):
    """Build a _run_command stand-in that records every probe."""

    def _runner(args: list[str], **_kwargs: object) -> str | None:
        calls.append(list(args))
        for key, value in responses.items():
            if key in args:
                return value
        return None

    return _runner


# ---------------------------------------------------------------------------
# get_system_info
# ---------------------------------------------------------------------------


def test_get_system_info_does_not_probe_nvidia_smi_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        system_info_module,
        "_run_command",
        _fake_run_command(
            {
                "--query-gpu=memory.total": "8188",
                "nvidia-smi": _NVIDIA_SMI_HEADER,
            },
            calls,
        ),
    )

    info = get_system_info()

    nvidia_calls = [call for call in calls if call[0] == "nvidia-smi"]
    # One probe for the CUDA version, one for VRAM. A third means
    # get_vram_size_gb re-ran the CUDA probe the caller already did.
    assert len(nvidia_calls) == 2
    assert info["cuda_version"] == "12.6"
    assert info["vram_gb"] == 8.0


def test_get_system_info_skips_vram_probe_without_cuda(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        system_info_module,
        "_run_command",
        _fake_run_command({}, calls),
    )

    info = get_system_info()

    assert info["cuda_version"] is None
    assert info["vram_gb"] == 0.0
    assert not any("--query-gpu=memory.total" in call for call in calls)


# ---------------------------------------------------------------------------
# get_vram_size_gb
# ---------------------------------------------------------------------------


def test_get_vram_size_gb_returns_zero_without_nvidia_smi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        system_info_module,
        "_run_command",
        _fake_run_command({}, calls),
    )

    assert get_vram_size_gb() == 0.0


def test_get_vram_size_gb_picks_largest_gpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        system_info_module,
        "_run_command",
        _fake_run_command(
            {"--query-gpu=memory.total": "8188\n24564\n"},
            calls,
        ),
    )

    assert get_vram_size_gb() == 23.99


def test_get_vram_size_gb_ignores_unparsable_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        system_info_module,
        "_run_command",
        _fake_run_command(
            {"--query-gpu=memory.total": "\n[N/A]\n8188\n"},
            calls,
        ),
    )

    assert get_vram_size_gb() == 8.0


def test_get_architecture_uses_windows_env_when_machine_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(system_info_module.platform, "machine", lambda: "")
    monkeypatch.setattr(
        system_info_module,
        "get_os_name",
        lambda: "windows",
    )
    monkeypatch.setenv("PROCESSOR_ARCHITECTURE", "AMD64")
    monkeypatch.delenv("PROCESSOR_ARCHITEW6432", raising=False)

    assert get_architecture() == "x64"


def test_get_architecture_prefers_wow64_native_architecture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(system_info_module.platform, "machine", lambda: "")
    monkeypatch.setattr(
        system_info_module,
        "get_os_name",
        lambda: "windows",
    )
    monkeypatch.setenv("PROCESSOR_ARCHITECTURE", "AMD64")
    monkeypatch.setenv("PROCESSOR_ARCHITEW6432", "ARM64")

    assert get_architecture() == "arm64"


def test_get_architecture_does_not_guess_outside_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(system_info_module.platform, "machine", lambda: "")
    monkeypatch.setattr(
        system_info_module,
        "get_os_name",
        lambda: "linux",
    )
    monkeypatch.setenv("PROCESSOR_ARCHITECTURE", "AMD64")

    assert get_architecture() == ""
