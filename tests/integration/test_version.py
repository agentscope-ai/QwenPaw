# -*- coding: utf-8 -*-
"""Integrated tests for QwenPaw version."""
from __future__ import annotations

import subprocess
import sys

import pytest
from packaging.version import Version


@pytest.mark.integration
@pytest.mark.p2
def test_version_import() -> None:
    """Test purpose:
    - Verify the version module can be imported directly, preventing missing
      version metadata in release artifacts.

    Test flow:
    1. Import ``__version__`` from ``qwenpaw.__version__``.
    2. Assert it is a non-empty string.

    API endpoints:
    - None (Python module import only)
    """
    from qwenpaw.__version__ import __version__

    assert __version__ is not None
    assert isinstance(__version__, str)
    assert len(__version__) > 0


@pytest.mark.integration
@pytest.mark.p2
def test_version_pep440_compliant() -> None:
    """Test purpose:
    - Verify the project version string is PEP 440 compliant.

    Test flow:
    1. Import ``__version__``.
    2. Parse it with ``packaging.version.Version``.
    3. Assert parsed string equals the original.

    API endpoints:
    - None (Python version-format validation only)
    """
    from qwenpaw.__version__ import __version__

    try:
        parsed_version = Version(__version__)
        assert str(parsed_version) == __version__
    except Exception as e:
        pytest.fail(f"Version '{__version__}' is not PEP 440 compliant: {e}")


@pytest.mark.integration
@pytest.mark.p2
def test_version_via_subprocess() -> None:
    """Test purpose:
    - Verify version retrieval also works in an isolated Python subprocess.

    Test flow:
    1. Run a subprocess that imports and prints ``__version__``.
    2. Assert return code is 0.
    3. Assert output is non-empty and includes a version separator.

    API endpoints:
    - None (Python subprocess execution only)
    """
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
