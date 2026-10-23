# -*- coding: utf-8 -*-
"""Extracted wheel with reused process suite and controlled platform I/O."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

from tests.unit.pack.test_c7_distribution import _build, _copy_release_inputs


ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT / "tests/fixtures/channel_plugins/c7_release_process_suite.py"


@pytest.fixture(name="c7_extracted_release", scope="module")
def _c7_extracted_release(tmp_path_factory):
    root = tmp_path_factory.mktemp("c7-installed-wheel")
    stage = root / "stage"
    _copy_release_inputs(ROOT, stage)
    wheel = _build(stage, root / "wheel", "build_wheel")
    release = root / "release"
    site = release / "src"
    site.mkdir(parents=True)
    with zipfile.ZipFile(wheel) as host:
        host.extractall(site)
        index = json.loads(host.read("qwenpaw/official_channels/index.json"))
        for item in index["plugins"]:
            data = host.read("qwenpaw/official_channels/" + item["filename"])
            target = release / "plugins/channel" / item["plugin_id"]
            target.mkdir(parents=True)
            with zipfile.ZipFile(io.BytesIO(data)) as plugin:
                plugin.extractall(target.parent)
    assert list(site.glob("qwenpaw-*.dist-info/METADATA"))
    return release


@pytest.mark.parametrize("channel", ["feishu", "dingtalk"])
@pytest.mark.parametrize(
    "case",
    [
        "test_c7_extracted_wheel_receive_send_restart_stop",
        "test_c7_extracted_wheel_resolver_and_offline_full_seed",
        "test_c7_extracted_wheel_light_keeps_bundles_dormant",
        "test_c7_initial_boot_loader_manager_child_uses_product_timeout",
    ],
)
def test_c7_extracted_wheel_host_child_chain(
    c7_extracted_release,
    channel,
    case,
    tmp_path,
) -> None:
    site = c7_extracted_release / "src"
    script = """
import pathlib, sys
site = pathlib.Path(sys.argv[1]).resolve()
suite = pathlib.Path(sys.argv[2]).resolve()
sys.path.insert(0, str(site))
import qwenpaw
assert pathlib.Path(qwenpaw.__file__).resolve().is_relative_to(site)
import pytest
raise SystemExit(pytest.main([
    '--confcutdir', str(suite.parent), str(suite) + '::' + sys.argv[3], '-q',
]))
"""
    metrics_path = tmp_path / "c7-metrics.json"
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, str(site), str(SUITE), case],
        cwd=tmp_path,
        env={
            **os.environ,
            "PIP_NO_INDEX": "1",
            "QWENPAW_WORKING_DIR": str(tmp_path / "working"),
            "QWENPAW_CHANNEL_PRESET": (
                "light" if "light" in case else "channels-full"
            ),
            "QWENPAW_CHANNEL_BLOCK_BUILTINS": "1",
            "QWENPAW_C7_CHANNEL": channel,
            "QWENPAW_C7_RELEASE_ROOT": str(c7_extracted_release),
            "QWENPAW_C7_METRICS_PATH": (
                str(metrics_path) if "initial_boot" in case else ""
            ),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    if "initial_boot" in case:
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        assert metrics["console_stream_ready_seconds"] > 0
        assert (
            metrics["console_stream_ready_seconds"] < metrics["ready_seconds"]
        )
        assert metrics["ready_seconds"] > 0
        assert metrics["parent_rss_bytes"] > 0
        assert metrics["child_rss_bytes"] > 0
        assert metrics["summed_current_rss_bytes"] == (
            metrics["parent_rss_bytes"] + metrics["child_rss_bytes"]
        )
        assert metrics["parent_sdk_modules"] == 0
        assert metrics["stop_seconds"] < 5
        assert metrics["child_alive_after_stop"] is False
        print(json.dumps(metrics, sort_keys=True))
