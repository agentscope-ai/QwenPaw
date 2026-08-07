# -*- coding: utf-8 -*-
"""Tests for the channel pre-commit check script."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_specific_channel_uses_qwenpaw_environment(tmp_path: Path) -> None:
    """A single-channel check should not require legacy package tooling."""
    project_root = Path(__file__).resolve().parents[3]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    _write_executable(
        bin_dir / "python3",
        """#!/bin/sh
if [ "$1" = "-c" ] && [ "$2" = "import qwenpaw" ]; then
    exit 0
fi
echo "unexpected python3 invocation: $*" >&2
exit 91
""",
    )
    _write_executable(bin_dir / "pytest", "#!/bin/sh\nexit 0\n")
    _write_executable(
        bin_dir / "pip",
        "#!/bin/sh\necho 'unexpected bare pip invocation' >&2\nexit 92\n",
    )

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    result = subprocess.run(
        ["bash", "scripts/check-channels.sh", "console"],
        cwd=project_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "unexpected" not in result.stdout + result.stderr
