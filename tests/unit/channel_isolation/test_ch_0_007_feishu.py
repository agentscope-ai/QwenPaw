# -*- coding: utf-8 -*-
"""Run CH-0-007 tests outside legacy global SDK substitutes."""

from pathlib import Path
import subprocess
import sys

SUITE = (
    Path(__file__).parents[2]
    / "fixtures"
    / "channel_isolation"
    / "feishu"
    / "ch_0_007_feishu_suite.py"
)


def test_ch_0_007_in_isolated_pytest_process() -> None:
    """Verify the production adapter with its real dependency imports."""
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            """
import pathlib, sys
source = pathlib.Path(sys.argv[1]).resolve()
suite = pathlib.Path(sys.argv[2]).resolve()
sys.path.insert(0, str(source))
import qwenpaw
assert pathlib.Path(qwenpaw.__file__).resolve().is_relative_to(source)
import pytest
raise SystemExit(pytest.main([
    '--confcutdir', str(suite.parent), str(suite), '-q',
]))
""",
            str(SUITE.parents[4] / "src"),
            str(SUITE),
        ],
        capture_output=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout.decode(
        errors="replace",
    ) + result.stderr.decode(errors="replace")
