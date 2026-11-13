# -*- coding: utf-8 -*-
"""Tests for shared safety check primitives."""
from __future__ import annotations

from pathlib import PureWindowsPath

import pytest

from qwenpaw.security.tool_guard.safety_checks import (
    _is_posix_abs_token_catastrophic,
    _is_resolved_path_catastrophic,
    classify_destructive_command,
    is_command_catastrophic,
    is_command_destructive,
    is_path_outside_boundary,
)


class TestIsCommandDestructive:  # pylint: disable=too-many-public-methods
    """Verify destructive command pattern matching."""

    @pytest.mark.parametrize(
        "command",
        [
            "rm -rf /",
            "rm -rf /*",
            "rm -rf -- /*",
            "rm -rf --/*",
            "rm -rf --/",
            "rm -f -r /",
            "rm --force --recursive /",
            "rm -rf /./",
            "rm -rf //",
            "rm -rf /tmp/..",
            "rm -rf /tmp/../",
            "rm -rf /tmp/../etc",
            "rm -rf /home",
            "rm -rf /home/alice",
            "rm -rf /Users/alice",
            "rm -rf /Users/alice/*",
            "rm -rf /home/alice/*",
            "rm -rf /Users/alice/./*",
            "rm -rf /home/alice/./*",
            "rm -rf /Users/*",
            "rm -rf ~/*",
            "rm -rf ~/./*",
            "rm -rf $HOME/*",
            "rm -rf $HOME/./*",
            "rm -rf ~alice",
            "rm -rf ~root",
            "rm -rf ~alice/*",
            "rm -rf ~alice/./*",
            "rm -rf ~root/*",
            "rm -rf /root",
            "rm -rf /boot",
            "rm -rf /dev",
            "rm -rf /Applications",
            "rm -rf /var/lib",
            "rm -rf /private/etc",
            "rm -rf /etc/passwd",
            "rm -rf '/home/alice'",
            'rm -rf "/Users/alice"',
            "rm -rf '/'",
            "rm --recursive ~",
            "rm -rf '~'",
            "rm -rf $HOME",
            "rm -rf ${HOME}",
            'rm -rf "$HOME"',
            "rm -rf %USERPROFILE%",
            "rm -rf *",
            "mkfs.ext4 /dev/sda1",
            "mke2fs /dev/sdb",
            "dd if=/dev/zero of=/dev/sda",
            "shutdown now",
            "reboot",
            "halt",
            "poweroff",
            "sudo reboot",
            "echo hi; reboot",
            ": () { : | : & } ; :",
            # Windows catastrophic patterns
            "Remove-Item -Recurse -Force C:\\",
            "Remove-Item -Recurse -Force C:\\*",
            'Remove-Item -Recurse -Force "C:\\"',
            "Remove-Item -Recurse -Force C:\\Users",
            "Remove-Item -Recurse -Force C:\\Users\\*",
            "Remove-Item -Recurse -Force C:\\Users\\me",
            "Remove-Item -Recurse -Force C:\\Users\\me\\*",
            "Remove-Item -Recurse -Force C:\\Windows",
            "Remove-Item -Recurse -Force C:\\Windows\\*",
            "Remove-Item -Recurse -Force C:\\Windows\\System32",
            "rm -Recurse -Force C:\\",
            'rm -Recurse -Force "C:\\"',
            "del /s /q C:\\",
            "del /s /q C:\\*",
            "del /s /q C:\\Users",
            'del /s /q "C:\\"',
            "rd /s /q C:\\",
            "rd /s /q C:\\Windows",
            'rd /s /q "C:\\"',
            "rmdir /s /q C:\\",
            "format C:",
            # Mount/runtime roots (not full subtree).
            "rm -rf /mnt",
            "rm -rf /mnt/*",
            "rm -rf /media",
            "rm -rf /run",
            "rm -rf /srv",
        ],
    )
    def test_blocks_known_dangerous_commands(self, command: str) -> None:
        assert is_command_destructive(command) is True

    @pytest.mark.parametrize(
        "command",
        [
            "ls -la",
            "echo hello",
            "cat README.md",
            "git status",
            "python3 script.py",
            "rm file.txt",
            "rm -f single_file.log",
            "mkdir new_dir",
            # Must NOT treat ordinary temp / workspace trees as root wipes.
            "rm -rf /tmp",
            "rm -rf /tmp/cache",
            "rm -rf '/tmp/cache'",
            "rm -rf /private/tmp/foo",
            "rm -rf /var/tmp/foo",
            "rm -rf /private/var/tmp/foo",
            "rm -rf /var/folders/xx/workspace/build",
            "rm -rf /private/var/folders/xx/workspace/build",
            "rm -rf /homeless",
            # Home *workspace* absolute paths must not be shared-catastrophic
            # (default auto-deny would hard-reject normal cleanups).
            "rm -rf /Users/alice/AgentScope/QwenPaw/build",
            "rm -rf /home/alice/project/dist",
            "rm -rf /Users/alice/.qwenpaw/build",
            "rm -rf ~/project",
            "rm -rf ~/project/build",
            "rm -rf ~/project/./*",
            "rm -rf ~alice/project",
            "rm -rf ~alice/project/build",
            "rm -rf ~alice/project/./*",
            "rm -rf $HOME/project",
            "rm -rf $HOME/project/dist",
            # WSL / mount / runtime workspace paths (root-only policy).
            "rm -rf /mnt/c/Users/me/project/build",
            "rm -rf /mnt/data/workspace/.cache",
            "rm -rf /media/user/USB/project/dist",
            "rm -rf /run/user/1000/project/tmp",
            "rm -rf /srv/www/app/cache",
            # macOS external volume project paths (volume-root-only policy).
            "rm -rf /Volumes/External/project/build",
            "rm -rf /Volumes/MyDisk/workspace/.cache",
            # Substring / script-name false positives must not hard-match.
            "echo reboot later",
            "npm run reboot",
            "git checkout --orphan reboot",
            "python -c 'print(\"shutdown\")'",
            "echo mkfs later",
            # Windows non-catastrophic / non-recursive.
            "Remove-Item -Recurse -Force C:\\Users\\me\\project\\build",
            "del /s /q D:\\work\\out\\*",
            "rd /s /q C:\\Users\\me\\project",
            "del C:\\",
            "rd C:\\",
        ],
    )
    def test_allows_safe_commands(self, command: str) -> None:
        assert is_command_destructive(command) is False

    def test_case_insensitive_matching(self) -> None:
        assert is_command_destructive("SHUTDOWN now") is True
        assert is_command_destructive("ReBoot") is True
        assert is_command_destructive("RM -RF /") is True
        assert (
            is_command_destructive("remove-item -recurse -force c:\\") is True
        )

    def test_workspace_absolute_path_not_catastrophic(self, tmp_path) -> None:
        """Workspace abs paths under temp trees must not be catastrophic."""
        target = tmp_path / "build"
        target.mkdir()
        assert is_command_destructive(f"rm -rf {target}") is False

    def test_classify_separates_catastrophic_from_system_power(self) -> None:
        assert classify_destructive_command("rm -rf /") == "catastrophic"
        assert classify_destructive_command("reboot") == "system_power"
        assert classify_destructive_command("npm run reboot") is None
        assert is_command_catastrophic("rm -rf /") is True
        assert is_command_catastrophic("reboot") is False

    def test_glued_endopts_root_wipe_is_catastrophic(self) -> None:
        """``--/*`` must not be skipped as a long option flag."""
        assert is_command_catastrophic("rm -rf --/*") is True
        assert is_command_catastrophic("rm -rf --/") is True

    def test_home_root_still_catastrophic_but_workspace_subpath_not(
        self,
    ) -> None:
        """Wipe the home directory itself; not a project under the home."""
        assert is_command_catastrophic("rm -rf /Users/alice") is True
        assert is_command_catastrophic("rm -rf /home/alice") is True
        assert is_command_catastrophic("rm -rf /Users") is True
        assert is_command_catastrophic("rm -rf ~") is True
        assert is_command_catastrophic("rm -rf $HOME") is True
        # Home-content globs are equivalent to wiping the home.
        assert is_command_catastrophic("rm -rf /Users/alice/*") is True
        assert is_command_catastrophic("rm -rf /home/alice/*") is True
        assert is_command_catastrophic("rm -rf /Users/alice/./*") is True
        assert is_command_catastrophic("rm -rf /home/alice/./*") is True
        assert is_command_catastrophic("rm -rf ~/*") is True
        assert is_command_catastrophic("rm -rf ~/./*") is True
        assert is_command_catastrophic("rm -rf $HOME/*") is True
        assert is_command_catastrophic("rm -rf $HOME/./*") is True
        # Named-user home wipe (~user / ~user/* / ~user/./*).
        assert is_command_catastrophic("rm -rf ~alice") is True
        assert is_command_catastrophic("rm -rf ~root") is True
        assert is_command_catastrophic("rm -rf ~alice/*") is True
        assert is_command_catastrophic("rm -rf ~alice/./*") is True
        assert is_command_catastrophic("rm -rf ~root/*") is True
        assert (
            is_command_catastrophic("rm -rf /Users/alice/proj/build") is False
        )
        assert is_command_catastrophic("rm -rf ~/proj") is False
        assert is_command_catastrophic("rm -rf ~/proj/build") is False
        assert is_command_catastrophic("rm -rf ~/proj/./*") is False
        assert is_command_catastrophic("rm -rf ~alice/proj") is False
        assert is_command_catastrophic("rm -rf ~alice/proj/build") is False
        assert is_command_catastrophic("rm -rf ~alice/proj/./*") is False

    def test_relative_wipe_uses_provided_cwd(self, tmp_path) -> None:
        """Relative ``../`` resolves against *cwd*, not process cwd."""
        import os

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        # From a temp workspace, ``../`` stays inside the temp tree.
        assert (
            classify_destructive_command(
                "rm -rf ../",
                cwd=workspace,
            )
            is None
        )
        if os.name == "nt":
            return
        # On POSIX, parent of /etc/ssl is /etc → catastrophic.
        assert (
            classify_destructive_command(
                "rm -rf ../",
                cwd="/etc/ssl",
            )
            == "catastrophic"
        )

    def test_b1_normalize_before_home_glob_match(self) -> None:
        """B1: collapse /./ // .. before home-root / home-content checks."""
        import os

        # Equivalent spellings of home-content wipes (must HIT).
        assert is_command_catastrophic("rm -rf ~/././*") is True
        assert is_command_catastrophic("rm -rf $HOME/././*") is True
        assert is_command_catastrophic("rm -rf /Users/alice/././*") is True
        assert is_command_catastrophic("rm -rf ~alice/././*") is True
        assert is_command_catastrophic("rm -rf /Users/alice//*") is True
        assert is_command_catastrophic("rm -rf /Users//alice/*") is True
        assert is_command_catastrophic("rm -rf //Users/alice/*") is True
        assert is_command_catastrophic("rm -rf /./Users/alice/*") is True
        assert is_command_catastrophic("rm -rf /./home/alice/*") is True
        assert is_command_catastrophic("rm -rf /Users/alice/foo/../*") is True
        assert is_command_catastrophic("rm -rf ~/foo/../*") is True
        assert is_command_catastrophic("rm -rf $HOME/foo/../*") is True
        assert is_command_catastrophic("rm -rf ~alice/bar/baz/../../*") is True
        # Must NOT false-positive on workspace globs / concrete subpaths.
        assert is_command_catastrophic("rm -rf ~/project/./*") is False
        assert (
            is_command_catastrophic("rm -rf /Users/alice/project/build")
            is False
        )

        if os.name == "nt":
            return
        home = os.path.expanduser("~")
        project = os.path.join(home, "project")
        assert is_command_catastrophic("rm -rf ../*", cwd=project) is True
        assert is_command_catastrophic("rm -rf .././*", cwd=project) is True
        assert is_command_catastrophic("rm -rf ./../*", cwd=project) is True
        # Sibling wipe under a temp workspace must stay non-catastrophic.
        assert (
            is_command_catastrophic(
                "rm -rf ../*",
                cwd=os.path.join("/tmp", "qwenpaw-b1-ws"),
            )
            is False
        )

    def test_macos_temp_trees_not_catastrophic(self) -> None:
        """Regex + resolve must both allow /private/tmp and /var/tmp."""
        assert is_command_catastrophic("rm -rf /private/tmp/foo") is False
        assert is_command_catastrophic("rm -rf /var/tmp/foo") is False
        assert is_command_catastrophic("rm -rf /private/var/tmp/foo") is False
        # Non-temp /private and /var stay blocked.
        assert is_command_catastrophic("rm -rf /private/etc") is True
        assert is_command_catastrophic("rm -rf /var/lib") is True

    def test_macos_firmlink_data_volume_not_false_system_wipe(self) -> None:
        """``/System/Volumes/Data/...`` must use logical-path policy.

        Regex must not hard-match the firmlink prefix as a ``/System``
        wipe; resolve + ``_logical_posix_parts`` then applies the same
        home / temp rules as the short ``/Users`` / ``/tmp`` forms.
        """
        # Workspace / temp under the firmlink stay allowed.
        assert (
            is_command_catastrophic(
                "rm -rf /System/Volumes/Data/Users/alice/proj/build",
            )
            is False
        )
        assert (
            is_command_catastrophic(
                "rm -rf /System/Volumes/Data/home/alice/project/dist",
            )
            is False
        )
        assert (
            is_command_catastrophic("rm -rf /System/Volumes/Data/tmp/foo")
            is False
        )
        assert (
            is_command_catastrophic(
                "rm -rf /System/Volumes/Data/private/tmp/foo",
            )
            is False
        )
        # Real /System wipes and firmlink home roots stay catastrophic.
        assert is_command_catastrophic("rm -rf /System") is True
        assert is_command_catastrophic("rm -rf /System/Library") is True
        assert (
            is_command_catastrophic("rm -rf /System/Volumes/Data/Users")
            is True
        )
        assert (
            is_command_catastrophic(
                "rm -rf /System/Volumes/Data/Users/alice",
            )
            is True
        )
        assert (
            is_command_catastrophic(
                "rm -rf /System/Volumes/Data/Users/alice/*",
            )
            is True
        )

    def test_posix_abs_classification_host_independent_on_windows_parts(
        self,
    ) -> None:
        """Windows Path roots use ``\\\\`` — must still classify POSIX policy.

        CI failure mode: ``Path('/etc').parts == ('\\\\', 'etc')`` and
        ``Path.resolve('/etc')`` → ``C:\\\\etc``, which is not a Windows
        drive wipe.  Absolute ``/…`` tokens must use PurePosix policy.
        """
        assert _is_posix_abs_token_catastrophic("/etc") is True
        assert _is_posix_abs_token_catastrophic("/tmp/foo") is False
        assert (
            _is_posix_abs_token_catastrophic("/System/Volumes/Data/Users")
            is True
        )
        assert (
            _is_posix_abs_token_catastrophic(
                "/System/Volumes/Data/Users/alice/proj/build",
            )
            is False
        )
        assert _is_posix_abs_token_catastrophic("/mnt/c/Windows") is True
        assert (
            _is_posix_abs_token_catastrophic("/mnt/c/Users/me/project/build")
            is False
        )
        # Simulate host Path parts as seen on windows-latest runners.
        assert _is_resolved_path_catastrophic(PureWindowsPath("/etc")) is True
        assert (
            _is_resolved_path_catastrophic(
                PureWindowsPath("/System/Volumes/Data/Users"),
            )
            is True
        )
        assert (
            _is_resolved_path_catastrophic(
                PureWindowsPath("/mnt/c/Windows"),
            )
            is True
        )

    def test_posix_abs_fallback_when_host_resolve_rewrites_drive(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Host resolve remapping ``/etc`` to ``C:/etc`` must still deny."""
        import qwenpaw.security.tool_guard.safety_checks as sc

        monkeypatch.setattr(
            sc,
            "_resolve_path_token",
            lambda token, base: PureWindowsPath("C:/etc"),
        )
        assert is_command_catastrophic("rm -rf /tmp/../etc") is True
        assert is_command_catastrophic("rm -rf /etc") is True
        # Workspace under firmlink still allowed via PurePosix policy.
        monkeypatch.setattr(
            sc,
            "_resolve_path_token",
            lambda token, base: PureWindowsPath(
                "C:/System/Volumes/Data/Users/alice/proj/build",
            ),
        )
        assert (
            is_command_catastrophic(
                "rm -rf /System/Volumes/Data/Users/alice/proj/build",
            )
            is False
        )
        assert (
            is_command_catastrophic("rm -rf /System/Volumes/Data/Users")
            is True
        )

    def test_mount_runtime_roots_not_full_subtree(self) -> None:
        """WSL/USB/runtime workspace paths must not be default auto-deny."""
        assert is_command_catastrophic("rm -rf /mnt") is True
        assert is_command_catastrophic("rm -rf /mnt/*") is True
        assert (
            is_command_catastrophic("rm -rf /mnt/c/Users/me/project/build")
            is False
        )
        assert (
            is_command_catastrophic("rm -rf /media/user/USB/project/dist")
            is False
        )
        assert (
            is_command_catastrophic("rm -rf /run/user/1000/project/tmp")
            is False
        )
        assert is_command_catastrophic("rm -rf /srv/www/app") is False

    def test_macos_volumes_depth_capped_like_home(self) -> None:
        """External-disk project cleanups must not be default auto-deny."""
        # Volume list / volume-root wipes stay catastrophic.
        assert is_command_catastrophic("rm -rf /Volumes") is True
        assert is_command_catastrophic("rm -rf /Volumes/*") is True
        assert is_command_catastrophic("rm -rf /Volumes/External") is True
        assert is_command_catastrophic("rm -rf /Volumes/External/*") is True
        assert is_command_catastrophic("rm -rf /Volumes/External/./*") is True
        # Spaced volume names (common on macOS) still wipe at volume root.
        assert is_command_catastrophic('rm -rf "/Volumes/My Disk"') is True
        assert is_command_catastrophic('rm -rf "/Volumes/My Disk/*"') is True
        # Deeper project paths on an external volume stay allowed.
        assert (
            is_command_catastrophic("rm -rf /Volumes/External/project/build")
            is False
        )
        assert (
            is_command_catastrophic(
                'rm -rf "/Volumes/My Disk/AgentScope/QwenPaw/dist"',
            )
            is False
        )

    def test_windows_users_and_windows_tree_parity(self) -> None:
        """Windows Users/Windows roots match Unix /Users + /windows."""
        assert (
            is_command_catastrophic("Remove-Item -Recurse -Force C:\\Users")
            is True
        )
        assert (
            is_command_catastrophic("Remove-Item -Recurse -Force C:\\Users\\*")
            is True
        )
        assert (
            is_command_catastrophic(
                "Remove-Item -Recurse -Force C:\\Users\\me",
            )
            is True
        )
        assert (
            is_command_catastrophic(
                "Remove-Item -Recurse -Force C:\\Windows",
            )
            is True
        )
        assert (
            is_command_catastrophic(
                "Remove-Item -Recurse -Force C:\\Windows\\System32",
            )
            is True
        )
        assert (
            is_command_catastrophic(
                "Remove-Item -Recurse -Force C:\\Users\\me\\project\\build",
            )
            is False
        )

    def test_wsl_windows_drive_users_windows_not_bypassed(self) -> None:
        """WSL /mnt/<drive>/... mirrors Windows drive/Users/Windows policy."""
        assert is_command_catastrophic("rm -rf /mnt/c") is True
        assert is_command_catastrophic("rm -rf /mnt/c/*") is True
        assert is_command_catastrophic("rm -rf /mnt/c/Users") is True
        assert is_command_catastrophic("rm -rf /mnt/c/Users/alice") is True
        assert is_command_catastrophic("rm -rf /mnt/c/Users/alice/*") is True
        assert is_command_catastrophic("rm -rf /mnt/c/Windows") is True
        assert (
            is_command_catastrophic("rm -rf /mnt/c/Windows/System32") is True
        )
        assert is_command_catastrophic("rm -rf /mnt/c/../c/Windows") is True
        # Project workspace under WSL Users still allowed.
        assert (
            is_command_catastrophic(
                "rm -rf /mnt/c/Users/me/project/build",
            )
            is False
        )

    def test_windows_normalize_resolve_parity(self) -> None:
        """Windows targets use normalize (/ and ..), not only literals."""
        assert (
            is_command_catastrophic("Remove-Item -Recurse -Force C:/Users")
            is True
        )
        assert (
            is_command_catastrophic("Remove-Item -Recurse -Force C:/Windows")
            is True
        )
        assert (
            is_command_catastrophic(
                r"Remove-Item -Recurse -Force C:\Users\alice\..",
            )
            is True
        )
        assert (
            is_command_catastrophic(
                r"Remove-Item -Recurse -Force C:\Users\alice\project\..\..",
            )
            is True
        )
        assert is_command_catastrophic(r"rm -rf C:\Users") is True
        assert is_command_catastrophic("rm -rf C:/Windows") is True
        assert (
            is_command_catastrophic("rm -rf C:/Users/me/project/build")
            is False
        )
        assert (
            is_command_catastrophic(
                "Remove-Item -Recurse -Force C:/Users/me/project/build",
            )
            is False
        )

    def test_win_path_token_not_substring_false_positive(self) -> None:
        """Drive tokens must not be carved from $env:/version:/foo:bar text."""
        assert (
            is_command_catastrophic(
                r"Remove-Item -Recurse -Force $env:TEMP\myproject\build",
            )
            is False
        )
        assert (
            is_command_catastrophic(
                r"Remove-Item -Recurse -Force $env:USERPROFILE\project\build",
            )
            is False
        )
        assert is_command_catastrophic("rm -rf version:1/build") is False
        assert is_command_catastrophic("rm -rf ./namespace:pkg/dist") is False
        assert is_command_catastrophic("rm -rf /tmp/foo:bar/baz") is False
        assert (
            is_command_catastrophic(
                r"Remove-Item -Recurse -Force .\namespace:pkg\dist",
            )
            is False
        )

    def test_git_bash_and_cygwin_windows_path_parity(self) -> None:
        """Git Bash /c/... and Cygwin /cygdrive/<d>/... match WSL policy."""
        assert is_command_catastrophic("rm -rf /c") is True
        assert is_command_catastrophic("rm -rf /c/*") is True
        assert is_command_catastrophic("rm -rf /c/Users") is True
        assert is_command_catastrophic("rm -rf /c/Users/alice") is True
        assert is_command_catastrophic("rm -rf /c/Users/alice/*") is True
        assert is_command_catastrophic("rm -rf /c/Windows") is True
        assert is_command_catastrophic("rm -rf /c/Windows/System32") is True
        assert is_command_catastrophic("rm -rf /cygdrive/c") is True
        assert is_command_catastrophic("rm -rf /cygdrive/c/Users") is True
        assert is_command_catastrophic("rm -rf /cygdrive/c/Windows") is True
        assert (
            is_command_catastrophic("rm -rf /c/Users/alice/project/build")
            is False
        )
        assert (
            is_command_catastrophic(
                "rm -rf /cygdrive/c/Users/alice/project/build",
            )
            is False
        )

    def test_cmd_env_and_powershell_home_targets(self) -> None:
        """rd/del %USERPROFILE%/%SystemRoot% and Remove-Item ~/ $HOME."""
        assert is_command_catastrophic("rd /s /q %USERPROFILE%") is True
        assert is_command_catastrophic("del /s /q %USERPROFILE%") is True
        assert is_command_catastrophic(r"del /s /q %USERPROFILE%\*") is True
        assert is_command_catastrophic("rd /s /q %SystemRoot%") is True
        assert is_command_catastrophic("rd /s /q %WINDIR%") is True
        assert is_command_catastrophic("del /s /q %SystemRoot%") is True
        assert is_command_catastrophic("Remove-Item -Recurse -Force ~") is True
        assert (
            is_command_catastrophic("Remove-Item -Recurse -Force $HOME")
            is True
        )
        assert (
            is_command_catastrophic(
                r"Remove-Item -Recurse -Force $env:USERPROFILE",
            )
            is True
        )
        # Workspace under profile must stay allowed.
        assert (
            is_command_catastrophic(
                r"Remove-Item -Recurse -Force $env:USERPROFILE\project\build",
            )
            is False
        )
        assert (
            is_command_catastrophic(
                r"rd /s /q %USERPROFILE%\project\build",
            )
            is False
        )

    def test_windows_env_parent_climb_and_equivalents(self) -> None:
        """SystemRoot/WINDIR .. climb, PUBLIC/HOMEDRIVE, SystemDrive parity."""
        assert is_command_catastrophic(r"rd /s /q %SystemRoot%\..") is True
        assert is_command_catastrophic(r"rd /s /q %WINDIR%/..") is True
        assert (
            is_command_catastrophic(r'cmd /c "rd /s /q %SystemRoot%\.."')
            is True
        )
        assert (
            is_command_catastrophic(
                r"Remove-Item -Recurse -Force $env:SystemRoot",
            )
            is True
        )
        assert (
            is_command_catastrophic(
                r"Remove-Item -Recurse -Force $env:WinDir\..",
            )
            is True
        )
        assert (
            is_command_catastrophic(r"rd /s /q %HOMEDRIVE%%HOMEPATH%") is True
        )
        assert (
            is_command_catastrophic(r"rd /s /q %HOMEDRIVE%\%HOMEPATH%") is True
        )
        assert is_command_catastrophic("rd /s /q %PUBLIC%") is True
        assert (
            is_command_catastrophic(
                r"Remove-Item -Recurse -Force $env:PUBLIC",
            )
            is True
        )
        assert (
            is_command_catastrophic(
                r"Remove-Item -Recurse -Force $env:HOMEDRIVE$env:HOMEPATH",
            )
            is True
        )
        assert is_command_catastrophic(r"rd /s /q %SystemDrive%\Users") is True
        assert (
            is_command_catastrophic(r"rd /s /q %SystemDrive%\Windows") is True
        )
        assert is_command_catastrophic(r"rd /s /q %SystemDrive%\*") is True
        assert (
            is_command_catastrophic(
                r"Remove-Item -Recurse -Force $env:SystemDrive\Users",
            )
            is True
        )
        assert (
            is_command_catastrophic(
                r"rd /s /q %SystemDrive%\Users\me\project",
            )
            is False
        )

    def test_emulated_windows_inside_shell_c_wrapper(self) -> None:
        """WSL/Git Bash targets must hit as raw substrings inside bash -c."""
        assert (
            is_command_catastrophic('bash -lc "rm -rf /mnt/c/Users"') is True
        )
        assert is_command_catastrophic('bash -c "rm -rf /c/Windows"') is True
        assert is_command_catastrophic('sh -c "rm -rf /mnt/c"') is True
        assert (
            is_command_catastrophic(
                'bash -lc "bash -lc \\"rm -rf /mnt/c/Users\\""',
            )
            is True
        )

    def test_indirect_rm_command_substitution(self) -> None:
        """$(which rm) / backticks / ${RM:-rm} unwrap to bare rm checks."""
        assert is_command_catastrophic("$(which rm) -rf /") is True
        assert is_command_catastrophic("`which rm` -rf /") is True
        assert is_command_catastrophic("$(command -v rm) -rf /") is True
        assert is_command_catastrophic("`(command -v rm)` -rf /") is True
        assert is_command_catastrophic("${RM:-rm} -rf /") is True
        # Must not blank real ${HOME} targets (regression vs #5090 class).
        assert is_command_catastrophic("rm -rf ${HOME}") is True
        assert is_command_catastrophic("rm -rf ${HOME}/project") is False
        # Full wipe inside $(...) / backticks must still hit on the original
        # string (unwrap alone would collapse them to bare ``rm``).
        assert is_command_catastrophic("$(rm -rf /)") is True
        assert is_command_catastrophic("`rm -rf /`") is True
        assert is_command_catastrophic("$(sudo rm -rf /)") is True
        assert is_command_catastrophic("x=$(rm -rf /)") is True
        # Non-catastrophic substitution forms stay allowed.
        assert is_command_catastrophic("$(which rm) -rf /tmp/foo") is False
        assert is_command_catastrophic("echo $(which rm)") is False

    def test_expand_before_normpath_home_parent_climb(self) -> None:
        """Expand ~ / $HOME before normpath so ~/.. is not '.' ."""
        import os

        assert is_command_catastrophic("rm -rf ~/..") is True
        assert is_command_catastrophic("rm -rf $HOME/..") is True
        assert is_command_catastrophic("rm -rf ~/project/../..") is True
        assert is_command_catastrophic("rm -rf $HOME/project/../..") is True
        # Unknown ~user / Windows env form: must not normpath ``..`` away.
        assert is_command_catastrophic("rm -rf ~alice/..") is True
        assert is_command_catastrophic("rm -rf ~nosuchuser999/..") is True
        # POSIX shlex eats unquoted ``\``; use ``/`` or a quoted Windows form.
        assert is_command_catastrophic("rm -rf %USERPROFILE%/..") is True
        assert is_command_catastrophic(r"rm -rf '%USERPROFILE%\..'") is True
        if os.name != "nt":
            user = os.environ.get("USER") or os.environ.get("LOGNAME")
            if user:
                assert is_command_catastrophic(f"rm -rf ~{user}/..") is True
        # Workspace subpaths must still be allowed.
        assert is_command_catastrophic("rm -rf ~/project/./*") is False
        assert is_command_catastrophic("rm -rf ~/project/../project") is False


class TestIsPathOutsideBoundary:
    """Verify path boundary checking."""

    def test_path_inside_cwd(self, tmp_path) -> None:
        cwd = str(tmp_path)
        assert is_path_outside_boundary("subdir/file.txt", cwd) is False
        assert (
            is_path_outside_boundary(str(tmp_path / "file.txt"), cwd) is False
        )

    def test_path_outside_cwd(self, tmp_path) -> None:
        cwd = str(tmp_path)
        assert is_path_outside_boundary("/etc/passwd", cwd) is True
        assert is_path_outside_boundary("/tmp/outside", cwd) is True

    def test_relative_path_resolved_inside(self, tmp_path) -> None:
        cwd = str(tmp_path)
        subdir = tmp_path / "sub"
        subdir.mkdir()
        assert is_path_outside_boundary("sub/../file.txt", cwd) is False

    def test_relative_path_traversal_outside(self, tmp_path) -> None:
        inner = tmp_path / "inner"
        inner.mkdir()
        assert is_path_outside_boundary("../outside.txt", str(inner)) is True

    def test_tilde_expansion(self, tmp_path) -> None:
        # ~ expands to home dir which is almost certainly outside tmp_path
        cwd = str(tmp_path)
        assert is_path_outside_boundary("~/some_file", cwd) is True

    def test_sibling_directory_bypass_blocked(self, tmp_path) -> None:
        """A sibling whose name shares a prefix must NOT pass the check.

        String-prefix matching (``startswith``) would incorrectly allow
        ``/tmp/project_evil/file`` when cwd is ``/tmp/project`` because
        the string starts with the cwd prefix.  ``is_relative_to``
        handles this correctly.
        """
        project = tmp_path / "project"
        project.mkdir()
        evil = tmp_path / "project_evil"
        evil.mkdir()
        target = evil / "secret.txt"
        target.touch()
        assert is_path_outside_boundary(str(target), str(project)) is True

    def test_exact_cwd_path_is_inside(self, tmp_path) -> None:
        cwd = str(tmp_path)
        assert is_path_outside_boundary(cwd, cwd) is False

    def test_nonexistent_path_inside_cwd(self, tmp_path) -> None:
        assert is_path_outside_boundary("nonexistent", str(tmp_path)) is False
