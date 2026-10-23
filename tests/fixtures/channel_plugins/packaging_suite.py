# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""Private candidate archives must run their own channel implementations."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[3]
SUITE_DIR = Path(__file__).resolve().parent


@pytest.fixture(params=["feishu", "dingtalk"])
def archived_plugin(request, tmp_path):
    """Use the release zipper without opting a preview into publication."""
    channel = request.param
    source = ROOT / "plugins/channel" / channel
    manifest_bytes = (source / "plugin.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    assert manifest["publish"] is False
    candidate_dir = os.environ.get("QWENPAW_CHANNEL_CANDIDATE_ARCHIVES")
    archive_name = f"{channel}-{manifest['version']}.zip"
    if candidate_dir:
        archive = Path(candidate_dir) / archive_name
    else:
        spec = importlib.util.spec_from_file_location(
            "channel_preview_packer",
            ROOT / "scripts/pack/generate_plugin_metadata.py",
        )
        packer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(packer)
        archive = tmp_path / archive_name
        packer._zip_plugin(source, archive, manifest)
    extracted_root = tmp_path / "extracted"
    with zipfile.ZipFile(archive) as zipped:
        assert zipped.testzip() is None
        zipped.extractall(extracted_root)
    extracted = extracted_root / channel
    for rel in (
        "plugin.json",
        "channel.json",
        f"{channel}/__init__.py",
        f"{channel}/platform.py",
        f"{channel}/driver.py",
        "requirements.txt",
        "README.md",
    ):
        assert (extracted / rel).is_file(), f"Archive missing {channel}/{rel}"
    assert not (extracted / channel / "channel.py").exists()
    assert not (extracted / channel / "plugin.py").exists()
    assert (extracted / "plugin.json").read_bytes() == manifest_bytes
    assert (source / "plugin.json").read_bytes() == manifest_bytes
    return channel, extracted_root


def run_archived_suite(archived_plugin, tmp_path, cases):
    """Registration and SDK behavior always run in separate fresh processes."""
    channel, extracted_root = archived_plugin
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "pytest",
            "--confcutdir",
            str(SUITE_DIR),
            *[str(SUITE_DIR / case) for case in cases],
            "-q",
        ],
        env={
            **os.environ,
            "QWENPAW_WORKING_DIR": str(tmp_path / f"{channel}-workspace"),
            "QWENPAW_CHANNEL_PLUGIN_ROOT": str(extracted_root),
            "QWENPAW_CHANNEL_BLOCK_BUILTINS": "1",
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_archive_registers_without_platform_sdk(archived_plugin, tmp_path):
    """Both normal and probe namespaces use the extracted entry/channel."""
    channel, _ = archived_plugin
    suite = (
        "registration_suite.py"
        if channel == "feishu"
        else "dingtalk_registration_suite.py"
    )
    run_archived_suite(archived_plugin, tmp_path, [suite])


def test_archive_runs_without_builtin_platform_implementation(
    archived_plugin,
    tmp_path,
):
    """Real receive/send paths run with fake external network boundaries."""
    channel, _ = archived_plugin
    cases = {
        "feishu": [
            (
                "feishu_process_suite.py::"
                "test_network_reconnect_fences_late_old_connection_callbacks"
            ),
            (
                "feishu_process_suite.py::"
                "test_proactive_send_reads_both_old_receive_store_orders"
            ),
        ],
        "dingtalk": [
            (
                "dingtalk_process_suite.py::"
                "test_native_message_runs_host_agent_and_sends_from_real_child"
            ),
            (
                "dingtalk_process_suite.py::"
                "test_direct_and_legacy_webhook_routes_bypass_openapi"
            ),
            (
                "dingtalk_process_suite.py::"
                "test_proactive_openapi_preserves_group_and_staff_identity"
            ),
        ],
    }
    run_archived_suite(archived_plugin, tmp_path, cases[channel])
