# -*- coding: utf-8 -*-
# pylint: disable=protected-access
import logging
from importlib.metadata import PackageNotFoundError
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from packaging.requirements import Requirement

from qwenpaw.plugins.loader import PluginLoader


def _write_runtime_metadata(
    site_dir: Path,
    directory: str,
    version: str,
) -> None:
    metadata_dir = site_dir / directory
    metadata_dir.mkdir(parents=True)
    (metadata_dir / "METADATA").write_text(
        f"Name: discord-py\nVersion: {version}\n",
        encoding="utf-8",
    )


def _write_staged_distribution(site_dir: Path) -> None:
    metadata_dir = site_dir / "demo_package-1.0.dist-info"
    metadata_dir.mkdir(parents=True)
    (site_dir / "demo_package.py").write_text(
        "value = 1\n",
        encoding="utf-8",
    )
    (metadata_dir / "METADATA").write_text(
        "Name: demo-package\nVersion: 1.0\n",
        encoding="utf-8",
    )
    (metadata_dir / "RECORD").write_text(
        "demo_package.py,,\n"
        "demo_package-1.0.dist-info/METADATA,,\n"
        "demo_package-1.0.dist-info/RECORD,,\n",
        encoding="utf-8",
    )


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


@pytest.mark.parametrize(
    ("distribution", "import_name"),
    [
        ("audioop-lts", "audioop"),
        ("dashscope-realtime", "dashscope_realtime"),
        ("discord-py", "discord"),
        ("lark-oapi", "lark_oapi"),
        ("livekit-api", "livekit"),
        ("matrix-nio", "nio"),
        ("paho-mqtt", "paho"),
        ("pycryptodome", "Crypto"),
        ("python-socks", "python_socks"),
        ("pyVoIP", "pyVoIP"),
        ("slack-bolt", "slack_bolt"),
        ("slack-sdk", "slack_sdk"),
        ("websocket-client", "websocket"),
        ("wecom-aibot-python-sdk", "aibot"),
    ],
)
def test_requirement_import_name_overrides(distribution, import_name):
    with (
        patch(
            "qwenpaw.plugins.loader._dist_version",
            side_effect=PackageNotFoundError,
        ),
        patch(
            "qwenpaw.plugins.loader.importlib.util.find_spec",
            return_value=object(),
        ) as find_spec,
    ):
        assert PluginLoader.is_requirement_satisfied(
            Requirement(distribution),
        )

    find_spec.assert_called_once_with(import_name)


def test_unknown_distribution_has_no_import_name_override():
    assert (
        PluginLoader.import_name_override_for_distribution(
            "unknown-distribution",
        )
        is None
    )
    assert (
        PluginLoader.import_name_for_distribution(
            "unknown-distribution",
        )
        == "unknown_distribution"
    )


def test_frozen_plugin_detects_duplicate_runtime_metadata(tmp_path):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("discord-py==2.7.1\n", encoding="utf-8")
    site_dir = tmp_path / "site"
    _write_runtime_metadata(
        site_dir,
        "discord_py-2.3.2.dist-info",
        "2.3.2",
    )
    _write_runtime_metadata(
        site_dir,
        "discord_py-2.7.1.dist-info",
        "2.7.1",
    )

    with (
        patch("qwenpaw.plugins.loader._is_frozen", return_value=True),
        patch(
            "qwenpaw.plugins.loader._plugin_site_dir",
            return_value=site_dir,
        ),
    ):
        missing = PluginLoader._find_unsatisfied_dependencies(requirements)

    assert missing == ["discord-py==2.7.1"]


@pytest.mark.asyncio
async def test_plugin_dependency_inspection_is_offloaded(tmp_path):
    loader = PluginLoader(plugin_dirs=[tmp_path])
    requirements = tmp_path / "plugin" / "requirements.txt"
    inspect = patch.object(
        loader,
        "_inspect_dependencies",
        return_value=[],
    )
    offload = AsyncMock(return_value=[])

    with (
        inspect as inspect_dependencies,
        patch(
            "qwenpaw.plugins.loader.asyncio.to_thread",
            offload,
        ),
        patch("qwenpaw.plugins.loader._ensure_plugin_site_on_path"),
    ):
        await loader._ensure_dependencies_installed(
            requirements.parent,
            "demo-plugin",
        )

    offload.assert_awaited_once_with(
        inspect_dependencies,
        requirements,
    )


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


def test_frozen_plugin_installs_to_staging_before_runtime(tmp_path):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("demo-package==1.0\n", encoding="utf-8")
    site_dir = tmp_path / "bucket" / "site"
    loader = PluginLoader(plugin_dirs=[tmp_path])
    targets = []

    def run_install(command, **_kwargs):
        target = Path(command[command.index("--target") + 1])
        targets.append(target)
        assert "--upgrade" in command
        strategy = command.index("--upgrade-strategy")
        assert command[strategy + 1] == "only-if-needed"
        assert target != site_dir
        assert ".transactions" in target.parts
        _write_staged_distribution(target)
        return subprocess.CompletedProcess(command, 0, "", "")

    with (
        patch("qwenpaw.plugins.loader._desktop_python", return_value="python"),
        patch(
            "qwenpaw.plugins.loader._plugin_site_dir",
            return_value=site_dir,
        ),
        patch.object(
            loader,
            "run_subprocess_with_streaming_log",
            side_effect=run_install,
        ),
        patch.object(loader, "_runtime_constraints", return_value=[]),
        patch("qwenpaw.plugins.loader.verify_runtime_requirements"),
    ):
        loader._install_requirements_frozen(
            str(requirements),
            "demo-plugin",
            300,
        )

    assert len(targets) == 1
    assert (site_dir / "demo_package.py").is_file()
    assert (site_dir / "demo_package-1.0.dist-info").is_dir()
