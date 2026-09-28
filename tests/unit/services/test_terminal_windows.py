# -*- coding: utf-8 -*-
"""Exercise Windows adapter contracts on any host, without a native PTY."""
# pylint: disable=protected-access

import importlib
import multiprocessing
import subprocess
import sys
import threading
from unittest.mock import MagicMock

import psutil
import pytest

from qwenpaw.services import terminal_windows as windows


def test_worker_protocol_and_eof(monkeypatch):
    native = MagicMock()
    process = native.PtyProcess.spawn.return_value
    process.pid = 123
    process.fileobj.recv.return_value = b""
    process.isalive.return_value = False
    process.exitstatus = 7
    monkeypatch.setattr(windows.importlib, "import_module", lambda _: native)
    control, child_control = multiprocessing.Pipe()
    output, child_output = multiprocessing.Pipe(duplex=False)
    worker = threading.Thread(
        target=windows.pty_worker,
        args=(child_control, child_output, [], ".", {}, (24, 80)),
        daemon=True,
    )
    worker.start()
    try:
        assert control.poll(3)
        assert control.recv() == (True, 123)
        for request_id, (operation, args, expected) in enumerate(
            [
                ("write", ("hello",), None),
                ("resize", (30, 100), None),
                ("status", (), (False, 7)),
            ],
            start=1,
        ):
            control.send((request_id, operation, args))
            assert control.poll(3)
            assert control.recv() == (request_id, True, expected)
        process.write.assert_called_once_with("hello")
        process.setwinsize.assert_called_once_with(30, 100)
        assert output.poll(3)
        with pytest.raises(EOFError):
            output.recv()
    finally:
        control.close()
        output.close()
        worker.join(timeout=3)
    assert not worker.is_alive()


def test_output_decoder_handles_split_utf8_and_incomplete_eof():
    process = MagicMock()
    process.fileobj.recv.side_effect = [
        b"before\xe4",
        b"\xbd\xa0after",
        b"\xe5",
        b"",
    ]
    output = MagicMock()

    windows.forward_output(process, output)

    assert [call.args[0] for call in output.send.call_args_list] == [
        "before",
        "你after",
        "�",
    ]
    output.close.assert_called_once_with()


def fake_worker(control, output, _command, _cwd, _env, _dimensions):
    """Model a shell and a PTY host as separate worker-owned processes."""
    command = [sys.executable, "-c", "import time; time.sleep(60)"]
    with subprocess.Popen(command) as shell, subprocess.Popen(command) as host:
        control.send((True, shell.pid))
        output.send(str(host.pid))
        while True:
            request_id, operation, _args = control.recv()
            if operation == "status":
                control.send((request_id, True, (True, None)))
            else:
                control.send((request_id, True, None))


def test_receive_call_discards_late_reply():
    adapter = windows.WindowsPty.__new__(windows.WindowsPty)
    adapter.control = MagicMock()
    adapter.control.poll.return_value = True
    adapter.control.recv.side_effect = [
        (1, True, None),
        (2, True, "current"),
    ]

    assert adapter._receive_call(2) == "current"


def test_write_timeout_does_not_close_worker():
    adapter = windows.WindowsPty.__new__(windows.WindowsPty)
    adapter.control = MagicMock()
    adapter.lock = threading.Lock()
    adapter.closed = False
    adapter.request_id = 0
    adapter._receive_call = MagicMock(
        side_effect=TimeoutError("Terminal worker did not respond"),
    )
    adapter.close = MagicMock()

    with pytest.raises(TimeoutError, match="did not respond"):
        adapter.write("hello")

    adapter.control.send.assert_called_once_with((1, "write", ("hello",)))
    adapter.close.assert_not_called()


def test_missing_or_broken_native_dependency(monkeypatch):
    original = importlib.import_module

    def missing(name):
        if name == "winpty":
            raise ModuleNotFoundError("winpty")
        return original(name)

    monkeypatch.setattr(importlib, "import_module", missing)
    assert windows.WindowsPty.unavailable_reason() == "dependency_missing"
    with pytest.raises(OSError, match="pywinpty"):
        windows.WindowsPty.spawn([], ".", {}, (24, 80))


def test_close_reclaims_only_owned_worker_tree(monkeypatch):
    monkeypatch.setattr(windows, "pty_worker", fake_worker)
    monkeypatch.setattr(windows.WindowsPty, "unavailable_reason", lambda: None)
    command = [sys.executable, "-c", "import time; time.sleep(60)"]
    with subprocess.Popen(command) as unrelated:
        adapter = windows.WindowsPty.spawn([], ".", {}, (24, 80))
        owned = [psutil.Process(adapter.pid), adapter.owner]
        try:
            assert adapter.output.poll(5)
            owned.append(psutil.Process(int(adapter.read(4096))))
            assert adapter.isalive()
            adapter.write("hello")
            adapter.setwinsize(30, 100)
            adapter.close()
            adapter.close()
            assert not adapter.isalive()
            assert all(
                not process.is_running()
                or process.status() == psutil.STATUS_ZOMBIE
                for process in owned
            )
            assert unrelated.poll() is None
        finally:
            adapter.close()
            unrelated.terminate()
