# -*- coding: utf-8 -*-
"""Local runtimes never invoke dependency package managers."""

# pylint: disable=protected-access
import subprocess
from unittest.mock import Mock

import pytest

from qwenpaw.plugins.loader import PluginLoader


@pytest.mark.parametrize("provisioner", ["local", "docker", ""])
def test_dependency_installation_policy(tmp_path, monkeypatch, provisioner):
    monkeypatch.setenv("QWENPAW_RUNTIME_PROVISIONER", provisioner)
    loader = PluginLoader([tmp_path])
    installer = Mock(
        return_value=subprocess.CompletedProcess([], 0, "", ""),
    )
    monkeypatch.setattr(
        loader,
        "_run_subprocess_with_streaming_log",
        installer,
    )
    if provisioner == "local":
        with pytest.raises(RuntimeError, match="administrator"):
            loader._install_requirements(tmp_path / "requirements.txt", "app")
        installer.assert_not_called()
    else:
        loader._install_requirements(tmp_path / "requirements.txt", "app")
        installer.assert_called_once()
