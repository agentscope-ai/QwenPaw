# -*- coding: utf-8 -*-
"""Integrated tests for CoPaw version."""
from __future__ import annotations

import subprocess
import sys

import pytest
from packaging.version import Version


def test_version_import() -> None:
    """Test that version can be imported without errors."""
    from qwenpaw.__version__ import __version__

    assert __version__ is not None
    assert isinstance(__version__, str)
    assert len(__version__) > 0


def test_version_pep440_compliant() -> None:
    """Test that version follows PEP 440 format."""
    from qwenpaw.__version__ import __version__

    try:
        parsed_version = Version(__version__)
        assert str(parsed_version) == __version__
    except Exception as e:
        pytest.fail(f"Version '{__version__}' is not PEP 440 compliant: {e}")


def test_version_via_subprocess() -> None:
    """Test that version can be accessed via subprocess."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from qwenpaw.__version__ import __version__; print(__version__)",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, f"Failed to get version: {result.stderr}"
    version = result.stdout.strip()
    assert version
    assert "." in version
