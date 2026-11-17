# -*- coding: utf-8 -*-
"""Keep ACP shutdown from redirecting output owned by an embedding host."""

import subprocess
import sys

from qwenpaw.agents.acp.server import silence_stdout


def test_silence_stdout_preserves_redirected_stream(monkeypatch, tmp_path):
    """A host's temporary output file must remain readable and writable."""
    path = tmp_path / f"captured.txt"
    with path.open(f"w+", encoding=f"utf-8") as stream:
        with monkeypatch.context() as patch:
            patch.setattr(sys, f"stdout", stream)
            silence_stdout()

        stream.write(f"captured")
        stream.seek(0)
        assert stream.read() == f"captured"


def test_silence_stdout_mutes_process_pipe():
    """A standalone ACP process still silences its actual stdout pipe."""
    script = f"""
import os
from qwenpaw.agents.acp.server import silence_stdout

os.write(1, f"before".encode())
silence_stdout()
os.write(1, f"after".encode())
"""
    result = subprocess.run(
        [sys.executable, f"-c", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout == f"before"
