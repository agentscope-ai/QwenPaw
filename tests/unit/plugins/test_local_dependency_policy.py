# -*- coding: utf-8 -*-
"""Local runtimes never invoke dependency package managers."""

# pylint: disable=protected-access
from unittest.mock import Mock

import pytest

from qwenpaw.plugins.loader import PluginLoader


def test_local_runtime_rejects_dependency_installation(tmp_path, monkeypatch):
    monkeypatch.setenv("QWENPAW_RUNTIME_PROVISIONER", "local")
    loader = PluginLoader([tmp_path])
    installer = Mock()
    monkeypatch.setattr(
        loader,
        "_run_subprocess_with_streaming_log",
        installer,
    )
    with pytest.raises(RuntimeError, match="administrator"):
        loader._install_requirements(tmp_path / "requirements.txt", "app")
    installer.assert_not_called()
