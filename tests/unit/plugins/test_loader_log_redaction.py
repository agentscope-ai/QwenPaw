# -*- coding: utf-8 -*-
# pylint: disable=protected-access
import logging
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from qwenpaw.plugins.loader import PluginLoader


def test_install_subprocess_redacts_credentials(caplog):
    secret_url = "https://user:secret@example.com/simple/"

    with caplog.at_level(logging.DEBUG, logger="qwenpaw.plugins.loader"):
        result = PluginLoader.run_subprocess_with_streaming_log(
            [sys.executable, "-c", f"print({secret_url!r})", secret_url],
            timeout=10,
            plugin_id="redaction-test",
            redact_values=[secret_url, "user:secret@"],
        )

    assert result.returncode == 0
    assert secret_url not in result.stdout
    assert "secret" not in result.stdout
    assert secret_url not in caplog.text
    assert "secret" not in caplog.text
    assert "<redacted>" in caplog.text


def test_install_subprocess_uses_utf8_with_replacement():
    environment = {"QWENPAW_ENCODING_TEST": "custom"}
    result = PluginLoader.run_subprocess_with_streaming_log(
        [
            sys.executable,
            "-c",
            "import os, sys; "
            "sys.stdout.buffer.write(b'bad-byte: \\x80\\n'); "
            "print(os.environ['PYTHONUTF8']); "
            "print(os.environ['PYTHONIOENCODING']); "
            "print(os.environ['QWENPAW_ENCODING_TEST'])",
        ],
        timeout=10,
        plugin_id="encoding-test",
        environment=environment,
    )

    assert result.returncode == 0
    assert "bad-byte: \ufffd" in result.stdout
    assert "1" in result.stdout.splitlines()
    assert "utf-8" in result.stdout.splitlines()
    assert "custom" in result.stdout.splitlines()
    assert environment == {"QWENPAW_ENCODING_TEST": "custom"}


def test_install_subprocess_can_be_stopped():
    checks = 0

    def cancel_checker():
        nonlocal checks
        checks += 1
        return checks >= 2

    with pytest.raises(subprocess.SubprocessError, match="stopped"):
        PluginLoader.run_subprocess_with_streaming_log(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            timeout=10,
            plugin_id="cancellation-test",
            cancel_checker=cancel_checker,
        )


def test_plugin_install_failure_includes_merged_output(tmp_path):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("broken-package\n", encoding="utf-8")
    loader = PluginLoader(plugin_dirs=[Path(tmp_path)])

    with patch.object(
        loader,
        "run_subprocess_with_streaming_log",
        return_value=subprocess.CompletedProcess(
            [],
            1,
            "No matching distribution found for broken-package",
            "",
        ),
    ):
        with pytest.raises(RuntimeError, match="No matching distribution"):
            loader._install_requirements(requirements, "broken-plugin")


def test_plugin_uv_failure_includes_merged_output(tmp_path):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("broken-package\n", encoding="utf-8")
    loader = PluginLoader(plugin_dirs=[Path(tmp_path)])

    with (
        patch.object(
            loader,
            "run_subprocess_with_streaming_log",
            side_effect=[
                subprocess.CompletedProcess(
                    [],
                    1,
                    "No module named pip",
                    "",
                ),
                subprocess.CompletedProcess(
                    [],
                    1,
                    "uv could not resolve broken-package",
                    "",
                ),
            ],
        ),
        patch.object(loader, "find_uv", return_value="uv"),
    ):
        with pytest.raises(RuntimeError, match="uv could not resolve"):
            loader._install_requirements(requirements, "broken-plugin")


def test_frozen_plugin_failure_includes_merged_output(tmp_path):
    loader = PluginLoader(plugin_dirs=[Path(tmp_path)])
    with (
        patch(
            "qwenpaw.plugins.loader._desktop_python",
            return_value="python",
        ),
        patch(
            "qwenpaw.plugins.loader._plugin_site_dir",
            return_value=tmp_path / "plugin-site",
        ),
        patch.object(
            loader,
            "run_subprocess_with_streaming_log",
            return_value=subprocess.CompletedProcess(
                [],
                1,
                "frozen install failed",
                "",
            ),
        ),
    ):
        with pytest.raises(RuntimeError, match="frozen install failed"):
            loader._install_requirements_frozen(
                str(tmp_path / "requirements.txt"),
                "broken-plugin",
                300,
            )
