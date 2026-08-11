# -*- coding: utf-8 -*-
"""The OS folder chooser used when the console runs in a plain browser.

No test here may actually open a dialog — that would block the suite on a
window nobody is looking at — so the subprocess layer is always faked.
"""
# pylint: disable=protected-access
from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.app import native_dir_picker as ndp


def _result(stdout: str = "", returncode: int = 0, stderr: str = ""):
    return SimpleNamespace(
        stdout=stdout,
        stderr=stderr,
        returncode=returncode,
    )


@pytest.fixture(name="fake_run")
def _fake_run(monkeypatch):
    """Capture the command instead of running it."""
    calls: list[list[str]] = []
    box = {"result": _result()}

    async def _run(command, **_kwargs):
        calls.append(list(command))
        outcome = box["result"]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(ndp, "run_command_async", _run)
    return SimpleNamespace(calls=calls, box=box)


class TestAvailability:
    def test_macos_needs_osascript(self, monkeypatch):
        monkeypatch.setattr(ndp.sys, "platform", "darwin")
        monkeypatch.setattr(
            ndp.shutil,
            "which",
            lambda _n: "/usr/bin/osascript",
        )
        assert ndp.native_picker_available() is True

        monkeypatch.setattr(ndp.shutil, "which", lambda _n: None)
        assert ndp.native_picker_available() is False

    def test_windows_accepts_either_powershell(self, monkeypatch):
        monkeypatch.setattr(ndp.sys, "platform", "win32")
        monkeypatch.setattr(
            ndp.shutil,
            "which",
            lambda name: r"C:\pwsh.exe" if name == "pwsh" else None,
        )
        assert ndp.native_picker_available() is True

    def test_headless_linux_is_unavailable(self, monkeypatch):
        """Otherwise the request would hang on an invisible dialog."""
        monkeypatch.setattr(ndp.sys, "platform", "linux")
        monkeypatch.setattr(ndp.shutil, "which", lambda _n: "/usr/bin/zenity")
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        assert ndp.native_picker_available() is False

        monkeypatch.setenv("DISPLAY", ":0")
        assert ndp.native_picker_available() is True

    def test_linux_without_any_dialog_tool(self, monkeypatch):
        monkeypatch.setattr(ndp.sys, "platform", "linux")
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.setattr(ndp.shutil, "which", lambda _n: None)
        assert ndp.native_picker_available() is False


class TestPickDirectory:
    @pytest.mark.asyncio
    async def test_returns_the_chosen_path(self, monkeypatch, fake_run):
        monkeypatch.setattr(ndp.sys, "platform", "darwin")
        monkeypatch.setattr(
            ndp.shutil,
            "which",
            lambda _n: "/usr/bin/osascript",
        )
        fake_run.box["result"] = _result("/Users/me/repos/app/\n")

        assert await ndp.pick_directory() == "/Users/me/repos/app"

    @pytest.mark.asyncio
    async def test_cancel_returns_none_not_an_error(
        self,
        monkeypatch,
        fake_run,
    ):
        """AppleScript's -128 branch yields empty output with rc=0."""
        monkeypatch.setattr(ndp.sys, "platform", "darwin")
        monkeypatch.setattr(
            ndp.shutil,
            "which",
            lambda _n: "/usr/bin/osascript",
        )
        fake_run.box["result"] = _result("")

        assert await ndp.pick_directory() is None

    @pytest.mark.asyncio
    async def test_nonzero_exit_without_output_is_a_cancel(
        self,
        monkeypatch,
        fake_run,
    ):
        """zenity and kdialog both exit 1 when the user dismisses them."""
        monkeypatch.setattr(ndp.sys, "platform", "linux")
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.setattr(ndp.shutil, "which", lambda _n: "/usr/bin/zenity")
        fake_run.box["result"] = _result("", returncode=1)

        assert await ndp.pick_directory() is None

    @pytest.mark.asyncio
    async def test_nonzero_exit_with_output_raises(
        self,
        monkeypatch,
        fake_run,
    ):
        monkeypatch.setattr(ndp.sys, "platform", "darwin")
        monkeypatch.setattr(
            ndp.shutil,
            "which",
            lambda _n: "/usr/bin/osascript",
        )
        fake_run.box["result"] = _result("boom", returncode=2, stderr="bad")

        with pytest.raises(RuntimeError):
            await ndp.pick_directory()

    @pytest.mark.asyncio
    async def test_raises_when_no_dialog_is_possible(self, monkeypatch):
        """The caller needs a signal so it can fall back to the browser."""
        monkeypatch.setattr(ndp.sys, "platform", "linux")
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

        with pytest.raises(RuntimeError):
            await ndp.pick_directory()

    @pytest.mark.asyncio
    async def test_root_path_keeps_its_slash(self, monkeypatch, fake_run):
        monkeypatch.setattr(ndp.sys, "platform", "darwin")
        monkeypatch.setattr(
            ndp.shutil,
            "which",
            lambda _n: "/usr/bin/osascript",
        )
        fake_run.box["result"] = _result("/\n")

        assert await ndp.pick_directory() == "/"

    @pytest.mark.asyncio
    async def test_windows_uses_sta(self, monkeypatch, fake_run):
        """FolderBrowserDialog raises in PowerShell's default apartment."""
        monkeypatch.setattr(ndp.sys, "platform", "win32")
        monkeypatch.setattr(
            ndp.shutil,
            "which",
            lambda name: r"C:\powershell.exe"
            if name == "powershell"
            else None,
        )
        fake_run.box["result"] = _result(r"C:\repos\app")

        assert await ndp.pick_directory() == r"C:\repos\app"
        assert "-STA" in fake_run.calls[0]


class TestPromptEscaping:
    def test_applescript_quotes_are_escaped(self, monkeypatch):
        """An unescaped quote would truncate the script and change it."""
        monkeypatch.setattr(ndp.sys, "platform", "darwin")
        monkeypatch.setattr(
            ndp.shutil,
            "which",
            lambda _n: "/usr/bin/osascript",
        )

        command = ndp._build_command('say "hi" \\ bye')

        script = command[2]
        assert '\\"hi\\"' in script
        # The prompt must not be able to close the string and inject code.
        assert 'choose folder with prompt "say \\"hi\\"' in script

    def test_powershell_single_quotes_are_doubled(self, monkeypatch):
        monkeypatch.setattr(ndp.sys, "platform", "win32")
        monkeypatch.setattr(ndp.shutil, "which", lambda _n: r"C:\pwsh.exe")

        command = ndp._build_command("it's mine")

        assert "it''s mine" in command[-1]
