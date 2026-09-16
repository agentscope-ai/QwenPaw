# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,unused-argument
# pylint: disable=use-implicit-booleaness-not-comparison
# ^ C1803 kept on purpose: ``== []`` / ``== {}`` is an *equality* assertion
#   on the exact container, not a truthiness check.  Rewriting it as
#   ``not list(...)`` would also accept ``None`` and thereby weaken the
#   test.  Upstream keeps the same convention in 64 test files.
"""Unit tests for the runtime-path and OS-detection helpers in config/utils.

Coverage-driven backfill for backend unit coverage.  The existing
``test_config_utils.py`` already covers path normalisation, the
``Exec=`` tokeniser, ``_remove_bad_field``, ``_read_config_data``,
``load_config``/``save_config`` caching, ``strict_validate_config_file``,
``get_available_channels`` and ``get_agent_dirs``.  This file deliberately
only adds the parts those tests leave out:

* per-platform system browser discovery (darwin plist handlers, win32
  registry ProgId lookup, Linux ``xdg-mime`` desktop file resolution);
* the Playwright chromium executable resolution ladder;
* the validation-repair ladder inside ``_load_and_validate_config``
  (unremovable field, removal that does not help, migration persistence
  failure);
* ``load_config``/``save_config`` behaviour when ``stat`` fails;
* legacy heartbeat / last-dispatch / last-api fallbacks;
* ``is_qwenpaw_running`` socket probing;
* ``sanitize_mcp_clients`` in-place pruning.

🔴 Isolation note (measured, not assumed): ``qwenpaw.agents.tools`` calls
``load_config()`` at *import time* (``__init__.py``: ``_BROWSER_EXPERIMENTAL
= load_config().browser.experimental``), and ``Config`` construction can
trigger that import lazily.  Patching ``Config.model_validate`` therefore
makes an unrelated ``load_config()`` run against the real working directory
and leave ``config.<sha8>.bak`` files behind.  Every test below patches
only names owned by ``qwenpaw.config.utils`` itself, never pydantic class
methods.
"""

from __future__ import annotations

import builtins
import json
import os
import plistlib
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# Imported for its side effect only: it makes the import-time
# ``load_config()`` above happen before any test patches module state.
import qwenpaw.agents.tools  # noqa: F401  pylint: disable=unused-import
import qwenpaw.config.utils as cu
from qwenpaw.config.config import (
    Config,
    HeartbeatConfig,
    LastApiConfig,
    ThemeConfig,
)

PLIST_NAME = "com.apple.LaunchServices.com.apple.launchservices.secure.plist"


@pytest.fixture()
def working_dir(tmp_path, monkeypatch):
    """Point every WORKING_DIR-bound helper at a throwaway directory."""
    wd = tmp_path / "wd"
    wd.mkdir()
    monkeypatch.setattr(cu, "WORKING_DIR", wd)
    return wd


@pytest.fixture()
def fresh_config_cache(monkeypatch):
    """Never inherit the module-level config cache across tests."""
    monkeypatch.setattr(cu, "_config_cache", None)
    monkeypatch.setattr(cu, "_config_mtime", None)


@pytest.fixture()
def fake_home(tmp_path, monkeypatch):
    """A throwaway HOME so ``~``-expansion cannot touch the real profile."""
    home = tmp_path / "home"
    home.mkdir()
    # expanduser() prefers USERPROFILE on Windows (py<3.12), HOME elsewhere.
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


def _write_plist(home: Path, payload: dict) -> Path:
    """Write a LaunchServices plist under a fake HOME and return its path."""
    prefs = home / "Library" / "Preferences"
    prefs.mkdir(parents=True, exist_ok=True)
    plist = prefs / PLIST_NAME
    with open(plist, "wb") as handle:
        plistlib.dump(payload, handle)
    return plist


# ---------------------------------------------------------------------------
# _discover_system_chromium_path
# ---------------------------------------------------------------------------


class _StubPath:
    """Minimal ``pathlib.Path`` stand-in with a controllable ``is_file``.

    The candidate browser locations are hard-coded absolute paths inside
    ``_discover_system_chromium_path``, so the only injectable seam is the
    ``Path`` name the module looks up at call time.  ``pathlib.Path`` cannot
    be subclassed on py3.11 without ``_flavour``, hence this stub.
    """

    def __init__(self, *parts, existing=()):
        self.text = os.path.join(*[str(p) for p in parts])
        self.existing = set(existing)

    def __truediv__(self, other):
        clone = _StubPath(existing=self.existing)
        clone.text = self.text + "/" + str(other)
        return clone

    def is_file(self):
        return self.text in self.existing

    def resolve(self):
        return self

    def __str__(self):
        return self.text

    def __fspath__(self):
        return self.text


class TestDiscoverSystemChromiumPath:
    def test_win32_honours_program_files_env(self, monkeypatch, tmp_path):
        """``ProgramFiles`` wins over the hard-coded default."""
        base = str(tmp_path)
        monkeypatch.setattr(cu.sys, "platform", "win32")
        monkeypatch.setenv("ProgramFiles", base)
        monkeypatch.setenv("ProgramFiles(x86)", base)
        # Unlike ``_get_win32_default_browser`` (which joins one raw
        # ``Google\Chrome\...`` suffix), this ladder builds the candidate
        # with separate ``/`` components, so on POSIX it is a real
        # directory tree under ``ProgramFiles``.
        exe = tmp_path / "Google" / "Chrome" / "Application" / "chrome.exe"
        exe.parent.mkdir(parents=True)
        exe.write_text("stub", encoding="utf-8")

        assert cu._discover_system_chromium_path() == str(exe.resolve())

    def test_win32_no_candidate_present(self, monkeypatch, tmp_path):
        monkeypatch.setattr(cu.sys, "platform", "win32")
        monkeypatch.setenv("ProgramFiles", str(tmp_path))
        monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path))

        assert cu._discover_system_chromium_path() is None

    def test_darwin_picks_first_existing_bundle(self, monkeypatch):
        wanted = "/Applications/Google Chrome.app/Contents/MacOS/Google C"
        monkeypatch.setattr(cu.sys, "platform", "darwin")
        monkeypatch.setattr(
            cu,
            "Path",
            lambda *parts: _StubPath(*parts, existing={wanted + "hrome"}),
        )

        found = cu._discover_system_chromium_path()

        assert found == wanted + "hrome"

    def test_darwin_without_any_bundle(self, monkeypatch):
        monkeypatch.setattr(cu.sys, "platform", "darwin")
        monkeypatch.setattr(cu, "Path", _StubPath)

        assert cu._discover_system_chromium_path() is None

    def test_linux_prefers_the_first_listed_candidate(self, monkeypatch):
        """The ladder is ordered: an earlier hit wins over a later one."""
        monkeypatch.setattr(cu.sys, "platform", "linux")
        # Candidates are hard-coded absolute paths, so the only injectable
        # seam is ``Path`` itself; ``existing`` must name those literals.
        monkeypatch.setattr(
            cu,
            "Path",
            lambda *parts: _StubPath(
                *parts,
                existing={
                    "/usr/bin/chromium",
                    "/usr/lib/chromium/chromium",
                },
            ),
        )

        assert cu._discover_system_chromium_path() == "/usr/bin/chromium"

    def test_linux_without_any_candidate_returns_none(self, monkeypatch):
        monkeypatch.setattr(cu.sys, "platform", "linux")
        monkeypatch.setattr(cu, "Path", _StubPath)

        assert cu._discover_system_chromium_path() is None

    def test_unknown_platform_reuses_the_linux_candidate_set(
        self,
        monkeypatch,
    ):
        """``else`` means "Linux and other", not "no candidates at all"."""
        monkeypatch.setattr(cu.sys, "platform", "plan9")
        monkeypatch.setattr(
            cu,
            "Path",
            lambda *parts: _StubPath(
                *parts,
                existing={"/usr/bin/chromium-browser"},
            ),
        )

        assert (
            cu._discover_system_chromium_path() == "/usr/bin/chromium-browser"
        )


# ---------------------------------------------------------------------------
# get_playwright_chromium_executable_path
# ---------------------------------------------------------------------------


class TestPlaywrightChromiumExecutablePath:
    def test_env_pointing_at_a_real_file_wins(self, tmp_path, monkeypatch):
        exe = tmp_path / "chromium"
        exe.write_text("stub", encoding="utf-8")
        monkeypatch.setenv(
            cu.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH_ENV,
            str(exe),
        )

        assert cu.get_playwright_chromium_executable_path() == str(exe)

    def test_env_pointing_at_nothing_is_ignored(
        self,
        tmp_path,
        monkeypatch,
    ):
        """A stale env value must not be trusted as an executable."""
        monkeypatch.setenv(
            cu.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH_ENV,
            str(tmp_path / "ghost"),
        )
        monkeypatch.setattr(cu, "is_running_in_container", lambda: False)
        monkeypatch.setattr(cu, "_discover_system_chromium_path", lambda: None)

        assert cu.get_playwright_chromium_executable_path() is None

    def test_container_falls_back_to_known_locations(self, monkeypatch):
        """In a container only the packaged chromium locations are probed."""
        monkeypatch.delenv(
            cu.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH_ENV,
            raising=False,
        )
        monkeypatch.setattr(cu, "is_running_in_container", lambda: True)
        real_isfile = os.path.isfile
        wanted = "/usr/lib/chromium/chromium"

        def fake_isfile(path):
            if path == wanted:
                return True
            if path.startswith("/usr/bin/"):
                return False
            return real_isfile(path)

        monkeypatch.setattr(cu.os.path, "isfile", fake_isfile)

        assert cu.get_playwright_chromium_executable_path() == wanted

    def test_container_without_chromium_returns_none(self, monkeypatch):
        monkeypatch.delenv(
            cu.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH_ENV,
            raising=False,
        )
        monkeypatch.setattr(cu, "is_running_in_container", lambda: True)
        real_isfile = os.path.isfile

        def fake_isfile(path):
            if str(path).startswith("/usr/"):
                return False
            return real_isfile(path)

        monkeypatch.setattr(cu.os.path, "isfile", fake_isfile)

        assert cu.get_playwright_chromium_executable_path() is None

    def test_desktop_delegates_to_system_discovery(self, monkeypatch):
        monkeypatch.delenv(
            cu.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH_ENV,
            raising=False,
        )
        monkeypatch.setattr(cu, "is_running_in_container", lambda: False)
        monkeypatch.setattr(
            cu,
            "_discover_system_chromium_path",
            lambda: "/opt/chrome",
        )

        assert cu.get_playwright_chromium_executable_path() == "/opt/chrome"


# ---------------------------------------------------------------------------
# _get_darwin_default_browser
# ---------------------------------------------------------------------------


class TestDarwinDefaultBrowser:
    def test_missing_plist_is_not_an_error(self, fake_home):
        assert cu._get_darwin_default_browser() == (None, None)

    def test_unreadable_plist_is_swallowed(self, fake_home):
        prefs = fake_home / "Library" / "Preferences"
        prefs.mkdir(parents=True)
        (prefs / PLIST_NAME).write_bytes(b"\x00\x01 not a plist")

        assert cu._get_darwin_default_browser() == (None, None)

    def test_handlers_must_be_a_list(self, fake_home):
        _write_plist(fake_home, {"LSHandlers": "notalist"})

        assert cu._get_darwin_default_browser() == (None, None)

    def test_safari_maps_to_webkit_without_path(self, fake_home):
        _write_plist(
            fake_home,
            {
                "LSHandlers": [
                    "junk-entry-is-skipped",
                    {
                        "LSHandlerURLScheme": "https",
                        "LSHandlerRoleAll": "com.apple.safari",
                    },
                ],
            },
        )

        assert cu._get_darwin_default_browser() == ("webkit", None)

    def test_non_http_schemes_are_ignored(self, fake_home):
        _write_plist(
            fake_home,
            {
                "LSHandler": [
                    {
                        "LSHandlerURLScheme": "ftp",
                        "LSHandlerRoleAll": "com.google.chrome",
                    },
                ],
            },
        )

        assert cu._get_darwin_default_browser() == (None, None)

    def test_known_bundle_with_missing_binary_is_dropped(
        self,
        fake_home,
        monkeypatch,
    ):
        """Chrome registered but not installed must not be reported."""
        _write_plist(
            fake_home,
            {
                "LSHandlers": [
                    {
                        "LSHandlerURLScheme": "http",
                        "LSHandlerRoleViewer": "com.google.chrome",
                    },
                ],
            },
        )
        monkeypatch.setattr(cu, "_DARWIN_DEFAULT_BROWSER_BUNDLES", ())

        assert cu._get_darwin_default_browser() == (None, None)

    def test_known_bundle_with_installed_binary(
        self,
        fake_home,
        tmp_path,
        monkeypatch,
    ):
        exe = tmp_path / "Google Chrome"
        exe.write_text("stub", encoding="utf-8")
        _write_plist(
            fake_home,
            {
                "LSHandlers": [
                    {
                        "LSHandlerURLScheme": "http",
                        "LSHandlerRoleAll": "com.google.chrome",
                    },
                ],
            },
        )
        bundles = (
            ("com.google.chrome", "chromium", str(exe)),
            ("other", "firefox", None),
        )
        # monkeypatch (not a bare assignment) so the module table is
        # restored even if the assertion below fails.
        monkeypatch.setattr(cu, "_DARWIN_DEFAULT_BROWSER_BUNDLES", bundles)

        assert cu._get_darwin_default_browser() == ("chromium", str(exe))

    def test_unlisted_safari_bundle_uses_the_for_else_branch(
        self,
        fake_home,
        monkeypatch,
    ):
        """Safari is still webkit even when the table lost its entry."""
        _write_plist(
            fake_home,
            {
                "LSHandlers": [
                    {
                        "LSHandlerURLScheme": "http",
                        "LSHandlerRoleAll": "com.apple.safari",
                    },
                ],
            },
        )
        monkeypatch.setattr(
            cu,
            "_DARWIN_DEFAULT_BROWSER_BUNDLES",
            (("com.google.chrome", "chromium", None),),
        )

        assert cu._get_darwin_default_browser() == ("webkit", None)

    def test_unlisted_non_safari_bundle_is_unknown(
        self,
        fake_home,
        monkeypatch,
    ):
        _write_plist(
            fake_home,
            {
                "LSHandlers": [
                    {
                        "LSHandlerURLScheme": "http",
                        "LSHandlerRoleAll": "com.brave.browser",
                    },
                ],
            },
        )
        monkeypatch.setattr(
            cu,
            "_DARWIN_DEFAULT_BROWSER_BUNDLES",
            (("com.google.chrome", "chromium", None),),
        )

        assert cu._get_darwin_default_browser() == (None, None)

    def test_handler_without_role_yields_nothing(self, fake_home):
        _write_plist(
            fake_home,
            {"LSHandlers": [{"LSHandlerURLScheme": "http"}]},
        )

        assert cu._get_darwin_default_browser() == (None, None)


# ---------------------------------------------------------------------------
# _get_win32_default_browser
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_winreg(monkeypatch):
    """Install a stub ``winreg`` module so win32 code runs on any platform."""
    import types

    module = types.ModuleType("winreg")
    module.HKEY_CURRENT_USER = 1
    module.KEY_READ = 2
    state = {"prog_id": "ChromeHTML", "opened": [], "closed": 0}

    def open_key(root, subkey, reserved=0, access=0):
        state["opened"].append(subkey)
        return "HANDLE"

    def query_value_ex(key, name):
        return (state["prog_id"], 1)

    def close_key(key):
        state["closed"] += 1

    module.OpenKey = open_key
    module.QueryValueEx = query_value_ex
    module.CloseKey = close_key
    monkeypatch.setitem(sys.modules, "winreg", module)
    return state


class TestWin32DefaultBrowser:
    def test_no_winreg_module(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "winreg", None)

        assert cu._get_win32_default_browser() == (None, None)

    def test_chrome_prog_id_resolves_under_program_files(
        self,
        fake_winreg,
        tmp_path,
        monkeypatch,
    ):
        # POSIX treats a backslash as an ordinary filename character, so the
        # win32-style relative suffix can be materialised for real.
        relative = "Google\\Chrome\\Application\\chrome.exe"
        exe = tmp_path / relative
        exe.write_text("stub", encoding="utf-8")
        monkeypatch.setenv("ProgramFiles", str(tmp_path))
        monkeypatch.delenv("ProgramFiles(x86)", raising=False)

        kind, path = cu._get_win32_default_browser()

        assert (kind, path) == ("chromium", str(exe))
        assert fake_winreg["closed"] == 1
        assert "UrlAssociations" in fake_winreg["opened"][0]

    def test_edge_prog_id_prefix_match(
        self,
        fake_winreg,
        tmp_path,
        monkeypatch,
    ):
        fake_winreg["prog_id"] = "MSEdgeHTM.42"
        relative = "Microsoft\\Edge\\Application\\msedge.exe"
        exe = tmp_path / relative
        exe.write_text("stub", encoding="utf-8")
        monkeypatch.setenv("ProgramFiles", str(tmp_path))
        monkeypatch.delenv("ProgramFiles(x86)", raising=False)

        assert cu._get_win32_default_browser() == ("chromium", str(exe))

    def test_firefox_found_only_in_program_files_x86(
        self,
        fake_winreg,
        tmp_path,
        monkeypatch,
    ):
        fake_winreg["prog_id"] = "FirefoxURL-308046B0AF4A39CB"
        plain = tmp_path / "pf"
        x86 = tmp_path / "pf86"
        plain.mkdir()
        x86.mkdir()
        exe = x86 / "Mozilla Firefox\\firefox.exe"
        exe.write_text("stub", encoding="utf-8")
        monkeypatch.setenv("ProgramFiles", str(plain))
        monkeypatch.setenv("ProgramFiles(x86)", str(x86))

        assert cu._get_win32_default_browser() == ("firefox", str(exe))

    def test_unknown_prog_id(self, fake_winreg, tmp_path, monkeypatch):
        fake_winreg["prog_id"] = "SomeOtherBrowserHTML"
        monkeypatch.setenv("ProgramFiles", str(tmp_path))
        monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path))

        assert cu._get_win32_default_browser() == (None, None)

    def test_known_prog_id_without_binary(
        self,
        fake_winreg,
        tmp_path,
        monkeypatch,
    ):
        """A registered browser that is not installed reports nothing."""
        # monkeypatch (not a bare ``os.environ[...] =``) so the value cannot
        # leak into later tests -- under xdist a leak is order-dependent and
        # therefore unreproducible.
        monkeypatch.setenv("ProgramFiles", str(tmp_path))
        monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path))

        assert cu._get_win32_default_browser() == (None, None)

    def test_open_key_failure(self, fake_winreg, monkeypatch):
        module = sys.modules["winreg"]

        def boom(*args, **kwargs):
            raise OSError("no such key")

        monkeypatch.setattr(module, "OpenKey", boom)

        assert cu._get_win32_default_browser() == (None, None)

    def test_query_value_failure_closes_nothing(
        self,
        fake_winreg,
        monkeypatch,
    ):
        module = sys.modules["winreg"]

        def boom(*args, **kwargs):
            raise OSError("access denied")

        monkeypatch.setattr(module, "QueryValueEx", boom)

        assert cu._get_win32_default_browser() == (None, None)


# ---------------------------------------------------------------------------
# get_system_default_browser win32 leg + _get_linux_default_browser remainder
# ---------------------------------------------------------------------------


class TestSystemDefaultBrowserWin32Leg:
    def test_win32_dispatch(self, monkeypatch):
        monkeypatch.setattr(cu, "is_running_in_container", lambda: False)
        monkeypatch.setattr(cu.sys, "platform", "win32")
        monkeypatch.setattr(
            cu,
            "_get_win32_default_browser",
            lambda: ("firefox", "C:/ff/firefox.exe"),
        )

        assert cu.get_system_default_browser() == (
            "firefox",
            "C:/ff/firefox.exe",
        )


def _run_xdg(monkeypatch, desktop_name, returncode=0):
    """Make ``xdg-mime query`` answer with *desktop_name*."""

    def fake_run(*args, **kwargs):
        return SimpleNamespace(returncode=returncode, stdout=desktop_name)

    monkeypatch.setattr(cu.subprocess, "run", fake_run)


def _write_desktop(tmp_path, monkeypatch, name, body):
    """Materialise *name* where the product actually looks for it.

    ``_get_linux_default_browser`` reads
    ``$XDG_DATA_HOME/applications/<desktop>`` (then ``/usr/share``), *not*
    ``$XDG_DATA_HOME/<desktop>``.  Writing to the wrong level makes every
    test in this class pass vacuously through the "desktop file not found"
    leg, so the directory is created here and asserted to exist.
    """
    apps = tmp_path / "applications"
    apps.mkdir(parents=True, exist_ok=True)
    desktop = apps / name
    desktop.write_text(body, encoding="utf-8")
    _run_xdg(monkeypatch, name)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert desktop.is_file()
    return desktop


class TestLinuxDefaultBrowserRemaining:
    def test_nonzero_exit_code_is_treated_as_no_handler(self, monkeypatch):
        _run_xdg(monkeypatch, "chrome.desktop\n", returncode=1)

        assert cu._get_linux_default_browser() == (None, None)

    def test_timeout_is_swallowed(self, monkeypatch):
        def slow(*args, **kwargs):
            raise cu.subprocess.TimeoutExpired(cmd="xdg-mime", timeout=5)

        monkeypatch.setattr(cu.subprocess, "run", slow)

        assert cu._get_linux_default_browser() == (None, None)

    def test_absolute_exec_that_exists_is_returned(
        self,
        monkeypatch,
        tmp_path,
    ):
        """The resolved absolute executable must be reported verbatim."""
        _write_desktop(
            tmp_path,
            monkeypatch,
            "browser.desktop",
            f"[Desktop Entry]\nExec={sys.executable} %U\n",
        )

        kind, path = cu._get_linux_default_browser()

        assert path == sys.executable
        assert kind == "chromium"  # unknown name falls back to chromium

    def test_env_wrapper_with_ime_vars_is_unwrapped(
        self,
        monkeypatch,
        tmp_path,
    ):
        """``Exec=env VAR=val /bin/browser`` must report the browser."""
        _write_desktop(
            tmp_path,
            monkeypatch,
            "chrome.desktop",
            "[Desktop Entry]\n"
            "Exec=env GTK_IM_MODULE=ibus /usr/bin/google-chrome-stable %U\n",
        )
        real_is_file = cu.Path.is_file

        def fake_is_file(self):
            # Only the browser binary is pretended to exist; the desktop
            # file itself must keep its real ``is_file`` or the loop would
            # ``continue`` before ever reading it.
            if str(self) == "/usr/bin/google-chrome-stable":
                return True
            return real_is_file(self)

        monkeypatch.setattr(cu.Path, "is_file", fake_is_file)

        assert cu._get_linux_default_browser() == (
            "chromium",
            "/usr/bin/google-chrome-stable",
        )

    def test_empty_exec_token_breaks_out(self, monkeypatch, tmp_path):
        """``Exec=env`` alone carries no browser and must not crash."""
        _write_desktop(
            tmp_path,
            monkeypatch,
            "browser.desktop",
            "[Desktop Entry]\nExec=env\n",
        )

        assert cu._get_linux_default_browser() == (None, None)

    def test_relative_exec_missing_everywhere(self, monkeypatch, tmp_path):
        _write_desktop(
            tmp_path,
            monkeypatch,
            "browser.desktop",
            "[Desktop Entry]\nExec=qwenpaw-ghost-browser\n",
        )

        assert cu._get_linux_default_browser() == (None, None)

    def test_relative_exec_found_in_usr_bin(self, monkeypatch, tmp_path):
        """A bare executable name is resolved against the standard bindirs."""
        probe = Path("/usr/bin")
        if not probe.is_dir():
            pytest.skip("no /usr/bin on this platform")
        name = next(
            (
                p.name
                for p in sorted(probe.iterdir())
                if p.is_file() and os.access(p, os.X_OK)
            ),
            None,
        )
        if name is None:
            pytest.skip("no executable under /usr/bin")
        _write_desktop(
            tmp_path,
            monkeypatch,
            "browser.desktop",
            f"[Desktop Entry]\nExec={name}\n",
        )

        kind, path = cu._get_linux_default_browser()

        assert path == f"/usr/bin/{name}"
        assert kind in ("chromium", "firefox")

    def test_desktop_file_without_exec_line(self, monkeypatch, tmp_path):
        _write_desktop(
            tmp_path,
            monkeypatch,
            "browser.desktop",
            "[Desktop Entry]\nName=Browser\n",
        )

        assert cu._get_linux_default_browser() == (None, None)

    def test_first_desktop_hit_wins_over_the_usr_share_fallback(
        self,
        monkeypatch,
        tmp_path,
    ):
        """``$XDG_DATA_HOME`` is scanned before the system-wide directory."""
        _write_desktop(
            tmp_path,
            monkeypatch,
            "mine.desktop",
            f"[Desktop Entry]\nExec={sys.executable}\n",
        )
        real_is_file = cu.Path.is_file

        def only_absent(self):
            # Make the /usr/share copy invisible so a wrong scan order would
            # be observable instead of silently passing.
            if str(self).startswith("/usr/share/"):
                return False
            return real_is_file(self)

        monkeypatch.setattr(cu.Path, "is_file", only_absent)

        kind, path = cu._get_linux_default_browser()

        assert path == sys.executable
        assert kind == "chromium"

    def test_unreadable_desktop_file_is_skipped_not_fatal(
        self,
        monkeypatch,
        tmp_path,
    ):
        """An OSError on one desktop file must not abort the whole scan.

        The product wraps the read in ``except OSError: continue``, so a
        permission-denied first base falls through to the second one.  To
        make that fall-through observable (instead of passing vacuously
        through the "not a file" leg) the same desktop name is present in
        ``/usr/share/applications`` too, and only the unreadable copy
        raises.
        """
        _write_desktop(
            tmp_path,
            monkeypatch,
            "shared.desktop",
            "[Desktop Entry]\nExec=/nope\n",
        )
        real_is_file = cu.Path.is_file

        def visible(self):
            # Pretend the system-wide copy also exists, so the loop really
            # does enter the ``open()`` for the second base.
            if str(self).endswith("applications/shared.desktop"):
                return True
            return real_is_file(self)

        monkeypatch.setattr(cu.Path, "is_file", visible)
        real_open = builtins.open
        opened = []

        def deny(path, *args, **kwargs):
            opened.append(str(path))
            if str(path).endswith("shared.desktop"):
                raise PermissionError("denied")
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", deny)

        assert cu._get_linux_default_browser() == (None, None)
        # Both bases were attempted: the failure was contained, not fatal.
        assert len(opened) == 2
        assert opened[0].startswith(str(tmp_path))
        assert opened[1].startswith("/usr/share")

    def test_missing_desktop_file_is_skipped(self, monkeypatch, tmp_path):
        _run_xdg(monkeypatch, "absent.desktop")
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

        assert cu._get_linux_default_browser() == (None, None)


# ---------------------------------------------------------------------------
# is_running_in_container OSError leg
# ---------------------------------------------------------------------------


class TestIsRunningInContainerErrorLeg:
    def test_unreadable_cgroup_is_not_a_container(self, monkeypatch):
        import io as _io

        monkeypatch.setattr(cu, "RUNNING_IN_CONTAINER", False)
        monkeypatch.setattr(cu.os.path, "exists", lambda path: False)
        real_open = builtins.open

        def deny(path, *args, **kwargs):
            if path == "/proc/1/cgroup":
                raise PermissionError("denied")
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", deny)

        assert cu.is_running_in_container() is False
        assert _io is not None  # keeps the import honest for reviewers


# ---------------------------------------------------------------------------
# _remove_nested_key: an intermediate None must abort, not raise
# ---------------------------------------------------------------------------


class TestRemoveNestedKeyNoneIntermediate:
    def test_intermediate_none_returns_false(self):
        data = {"a": {"b": None}}

        assert cu._remove_nested_key(data, ["a", "b", "c"]) is False
        assert data == {"a": {"b": None}}

    def test_intermediate_scalar_returns_false(self):
        data = {"a": {"b": 7}}

        assert cu._remove_nested_key(data, ["a", "b", "c"]) is False

    def test_type_mismatch_segment_returns_false(self):
        """A string index into a list (or int into a dict) is not a match."""
        data = {"a": [1, 2]}

        assert cu._remove_nested_key(data, ["a", "b", "c"]) is False
        assert data == {"a": [1, 2]}

    def test_int_segment_into_dict_returns_false(self):
        data = {"a": {"b": 1}}

        assert cu._remove_nested_key(data, ["a", 0, "c"]) is False


# ---------------------------------------------------------------------------
# _read_config_data: repairable JSON whose root is not an object
# ---------------------------------------------------------------------------


class TestReadConfigDataRepairedNonDict:
    def test_truncated_list_is_backed_up(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text("[1,2", encoding="utf-8")

        assert cu._read_config_data(path) is None
        assert len(list(tmp_path.glob("config.*.bak"))) == 1
        # the original must survive untouched for the user to inspect
        assert path.read_text(encoding="utf-8") == "[1,2"

    def test_repaired_scalar_is_backed_up(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text("not json at all", encoding="utf-8")

        assert cu._read_config_data(path) is None
        assert len(list(tmp_path.glob("config.*.bak"))) == 1


# ---------------------------------------------------------------------------
# _load_and_validate_config repair ladder
# ---------------------------------------------------------------------------


def _validation_error(loc):
    """Build a real pydantic ValidationError with a chosen ``loc``."""
    from pydantic import ValidationError
    from pydantic_core import PydanticCustomError

    return ValidationError.from_exception_data(
        "Config",
        [
            {
                "type": "value_error",
                "loc": tuple(loc),
                "msg": "boom",
                "input": None,
                "ctx": {"error": PydanticCustomError("value_error", "boom")},
            },
        ],
    )


class TestLoadAndValidateRepairLadder:
    def test_unremovable_field_backs_up_and_defaults(
        self,
        tmp_path,
        monkeypatch,
    ):
        """When nothing can be removed the file is backed up, not mutated."""
        path = tmp_path / "config.json"
        path.write_text('{"channels": 5}', encoding="utf-8")
        monkeypatch.setattr(cu, "_remove_bad_field", lambda data, loc: False)

        config = cu._load_and_validate_config(path, {"channels": 5})

        assert isinstance(config, Config)
        assert config.channels.slack.enabled is False
        backups = list(tmp_path.glob("config.*.bak"))
        assert len(backups) == 1
        assert json.loads(backups[0].read_text(encoding="utf-8")) == {
            "channels": 5,
        }
        assert json.loads(path.read_text(encoding="utf-8")) == {"channels": 5}

    def test_removal_that_does_not_help_backs_up_again(
        self,
        tmp_path,
        monkeypatch,
    ):
        """Claiming a fix that changed nothing must still fall back safely."""
        path = tmp_path / "config.json"
        path.write_text('{"channels": 5}', encoding="utf-8")
        monkeypatch.setattr(cu, "_remove_bad_field", lambda data, loc: True)

        config = cu._load_and_validate_config(path, {"channels": 5})

        assert isinstance(config, Config)
        assert len(list(tmp_path.glob("config.*.bak"))) == 1

    def test_successful_removal_keeps_the_other_fields(
        self,
        tmp_path,
        monkeypatch,
    ):
        """A removable bad field is dropped, the rest of config stays."""
        path = tmp_path / "config.json"
        payload = {"channels": 5, "show_tool_details": False}
        path.write_text(json.dumps(payload), encoding="utf-8")

        def really_remove(data, loc):
            data.pop(loc[0], None)
            return True

        monkeypatch.setattr(cu, "_remove_bad_field", really_remove)

        config = cu._load_and_validate_config(path, dict(payload))

        assert config.show_tool_details is False
        assert list(tmp_path.glob("config.*.bak")) == []

    def test_real_bad_nested_field_is_repaired(self, tmp_path):
        """No patching: a genuinely invalid nested value is pruned."""
        path = tmp_path / "config.json"
        payload = {
            "channels": {"slack": {"enabled": "definitely-not-a-bool"}},
            "show_tool_details": False,
        }
        path.write_text(json.dumps(payload), encoding="utf-8")

        config = cu._load_and_validate_config(
            path,
            json.loads(json.dumps(payload)),
        )

        assert config.show_tool_details is False
        assert config.channels.slack.enabled is False

    def test_legacy_weixin_channel_is_migrated_and_persisted(self, tmp_path):
        path = tmp_path / "config.json"
        payload = {"channels": {"weixin": {"enabled": True}}}
        path.write_text(json.dumps(payload), encoding="utf-8")

        config = cu._load_and_validate_config(
            path,
            json.loads(json.dumps(payload)),
        )

        assert config.channels.wechat.enabled is True
        assert json.loads(path.read_text(encoding="utf-8")) == {
            "channels": {"wechat": {"enabled": True}},
        }
        assert len(list(tmp_path.glob("config.*.weixin-migrate.bak"))) == 1

    def test_existing_wechat_wins_over_legacy_weixin(self, tmp_path):
        """Migration must never overwrite an already-migrated channel."""
        path = tmp_path / "config.json"
        payload = {
            "channels": {
                "weixin": {"enabled": True},
                "wechat": {"enabled": False},
            },
        }
        path.write_text(json.dumps(payload), encoding="utf-8")

        config = cu._load_and_validate_config(
            path,
            json.loads(json.dumps(payload)),
        )

        assert config.channels.wechat.enabled is False

    def test_migration_persist_failure_keeps_the_loaded_config(
        self,
        tmp_path,
        monkeypatch,
    ):
        """Read-only dir must not lose the migrated in-memory config."""
        path = tmp_path / "config.json"
        payload = {"channels": {"weixin": {"enabled": True}}}
        path.write_text(json.dumps(payload), encoding="utf-8")

        def deny(*args, **kwargs):
            raise OSError("read-only filesystem")

        monkeypatch.setattr(cu.shutil, "copy2", deny)

        config = cu._load_and_validate_config(
            path,
            json.loads(json.dumps(payload)),
        )

        assert config.channels.wechat.enabled is True
        # nothing was persisted, so the legacy key is still on disk
        assert (
            "weixin"
            in json.loads(path.read_text(encoding="utf-8"))["channels"]
        )

    def test_legacy_last_api_top_level_fields(self, tmp_path):
        path = tmp_path / "config.json"
        payload = {"last_api_host": "10.0.0.1", "last_api_port": 9999}
        path.write_text(json.dumps(payload), encoding="utf-8")

        config = cu._load_and_validate_config(path, dict(payload))

        assert config.last_api == LastApiConfig(host="10.0.0.1", port=9999)

    def test_existing_last_api_object_wins(self, tmp_path):
        """The migration must not clobber an explicit last_api block."""
        path = tmp_path / "config.json"
        payload = {
            "last_api": {"host": "127.0.0.1", "port": 1},
            "last_api_host": "10.0.0.1",
            "last_api_port": 9999,
        }
        path.write_text(json.dumps(payload), encoding="utf-8")

        config = cu._load_and_validate_config(
            path,
            json.loads(json.dumps(payload)),
        )

        assert config.last_api.host == "127.0.0.1"
        assert config.last_api.port == 1

    def test_legacy_paths_are_rebound_to_the_working_dir(
        self,
        tmp_path,
        monkeypatch,
    ):
        """``~/.copaw``-era paths must follow QWENPAW_WORKING_DIR."""
        wd = tmp_path / "wd"
        wd.mkdir()
        monkeypatch.setattr(cu, "WORKING_DIR", wd)
        path = tmp_path / "config.json"
        payload = {
            "agents": {
                "profiles": {
                    "default": {
                        "id": "default",
                        "workspace_dir": "~/.copaw/workspaces/default",
                    },
                },
            },
        }
        path.write_text(json.dumps(payload), encoding="utf-8")

        config = cu._load_and_validate_config(
            path,
            json.loads(json.dumps(payload)),
        )

        assert config.agents.profiles["default"].workspace_dir == str(
            wd / "workspaces" / "default",
        )


# ---------------------------------------------------------------------------
# load_config / save_config stat() failure legs
# ---------------------------------------------------------------------------


class _StatFailPath:
    """A path-like whose ``stat`` raises, to exercise the OSError legs."""

    def __init__(self, real, mode):
        self._real = Path(real)
        self._mode = mode
        self.calls = 0

    def is_file(self):
        return self._real.is_file()

    def stat(self):
        self.calls += 1
        if self._mode == "always":
            raise OSError("stat denied")
        if self._mode == "second" and self.calls > 1:
            raise OSError("stat denied after read")
        return self._real.stat()

    def __fspath__(self):
        return str(self._real)

    def __str__(self):
        return str(self._real)

    def with_suffix(self, suffix):
        return self._real.with_suffix(suffix)


class TestConfigStatFailures:
    def test_load_defaults_when_first_stat_fails(
        self,
        tmp_path,
        fresh_config_cache,
    ):
        real = tmp_path / "config.json"
        real.write_text('{"show_tool_details": false}', encoding="utf-8")
        stub = _StatFailPath(real, "always")

        config = cu.load_config(stub)

        assert isinstance(config, Config)
        # the unreadable file must not silently become the cached config
        assert config.show_tool_details is True
        assert stub.calls == 1

    def test_load_keeps_mtime_when_second_stat_fails(
        self,
        tmp_path,
        fresh_config_cache,
        monkeypatch,
    ):
        """A stat race after the read must not poison the cache key."""
        real = tmp_path / "config.json"
        real.write_text('{"show_tool_details": false}', encoding="utf-8")
        stub = _StatFailPath(real, "second")

        config = cu.load_config(stub)

        assert config.show_tool_details is False
        assert cu._config_mtime == real.stat().st_mtime
        assert stub.calls == 2

    def test_save_clears_mtime_when_stat_fails(
        self,
        tmp_path,
        fresh_config_cache,
    ):
        """A failed stat after write leaves the cache mtime unknown (None)."""
        real = tmp_path / "config.json"
        stub = _StatFailPath(real, "always")
        config = Config()
        config.theme = ThemeConfig(accent="#00ff00")

        cu.save_config(config, stub)

        assert cu._config_mtime is None
        assert json.loads(real.read_text(encoding="utf-8"))["theme"] == {
            "accent": "#00ff00",
        }

    def test_save_drops_a_none_theme_key(
        self,
        tmp_path,
        fresh_config_cache,
    ):
        path = tmp_path / "config.json"

        cu.save_config(Config(), path)

        assert "theme" not in json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# get_heartbeat_config legacy leg
# ---------------------------------------------------------------------------


class TestHeartbeatConfigLegacy:
    def test_agent_id_path_prefers_agent_config(self, monkeypatch):
        hb = HeartbeatConfig(enabled=True, every="1h")
        monkeypatch.setattr(
            cu,
            "load_agent_config",
            lambda agent_id: SimpleNamespace(heartbeat=hb),
        )

        assert cu.get_heartbeat_config("agent-1") is hb

    def test_agent_id_without_heartbeat_uses_defaults(self, monkeypatch):
        monkeypatch.setattr(
            cu,
            "load_agent_config",
            lambda agent_id: SimpleNamespace(heartbeat=None),
        )

        assert cu.get_heartbeat_config("agent-1") == HeartbeatConfig()

    def test_agent_config_failure_uses_defaults(self, monkeypatch):
        def boom(agent_id):
            raise RuntimeError("no such agent")

        monkeypatch.setattr(cu, "load_agent_config", boom)

        assert cu.get_heartbeat_config("ghost") == HeartbeatConfig()

    def test_legacy_defaults_without_heartbeat(self, monkeypatch):
        monkeypatch.setattr(
            cu,
            "load_config",
            lambda: SimpleNamespace(
                agents=SimpleNamespace(
                    defaults=SimpleNamespace(heartbeat=None),
                ),
            ),
        )

        assert cu.get_heartbeat_config() == HeartbeatConfig()

    def test_legacy_defaults_with_heartbeat(self, monkeypatch):
        hb = HeartbeatConfig(enabled=True, every="30m")
        monkeypatch.setattr(
            cu,
            "load_config",
            lambda: SimpleNamespace(
                agents=SimpleNamespace(defaults=SimpleNamespace(heartbeat=hb)),
            ),
        )

        assert cu.get_heartbeat_config() is hb

    def test_legacy_defaults_absent(self, monkeypatch):
        monkeypatch.setattr(
            cu,
            "load_config",
            lambda: SimpleNamespace(agents=SimpleNamespace(defaults=None)),
        )

        assert cu.get_heartbeat_config() == HeartbeatConfig()


# ---------------------------------------------------------------------------
# update_last_dispatch / _migrate_last_dispatch_state / read_last_api
# ---------------------------------------------------------------------------


class TestLastDispatchLegacyPaths:
    def test_legacy_root_config_update(self, working_dir, fresh_config_cache):
        cu.update_last_dispatch("console", "user-9", "session-9")

        persisted = json.loads(
            (working_dir / "config.json").read_text(encoding="utf-8"),
        )
        assert persisted["last_dispatch"] == {
            "channel": "console",
            "user_id": "user-9",
            "session_id": "session-9",
        }

    def test_agent_id_failure_is_logged_not_raised(
        self,
        working_dir,
        fresh_config_cache,
        monkeypatch,
    ):
        """One broken agent must not abort the dispatch update path."""

        def boom():
            raise RuntimeError("config unavailable")

        monkeypatch.setattr(cu, "load_config", boom)

        cu.update_last_dispatch("qq", "u", "s", agent_id="agent-x")

        assert list(working_dir.glob("config.json")) == []

    def test_agent_id_writes_dedicated_state_file(
        self,
        tmp_path,
        working_dir,
        fresh_config_cache,
        monkeypatch,
    ):
        ws = tmp_path / "agent-ws"
        monkeypatch.setattr(
            cu,
            "load_config",
            lambda: SimpleNamespace(
                agents=SimpleNamespace(
                    profiles={"a1": SimpleNamespace(workspace_dir=str(ws))},
                ),
                last_dispatch=None,
            ),
        )

        cu.update_last_dispatch("feishu", "u1", "s1", agent_id="a1")

        state = ws / "state" / "last_dispatch.json"
        assert json.loads(state.read_text(encoding="utf-8")) == {
            "channel": "feishu",
            "user_id": "u1",
            "session_id": "s1",
        }
        # the legacy root config must stay untouched
        assert list(working_dir.glob("config.json")) == []

    def test_migrate_skips_none(self, tmp_path):
        cu._migrate_last_dispatch_state(tmp_path, None)

        assert (tmp_path / "state" / "last_dispatch.json").exists() is False

    def test_migrate_publishes_legacy_state(self, tmp_path):
        cu._migrate_last_dispatch_state(
            tmp_path,
            {"channel": "telegram", "user_id": "u", "session_id": "s"},
        )

        state = tmp_path / "state" / "last_dispatch.json"
        assert json.loads(state.read_text(encoding="utf-8"))["channel"] == (
            "telegram"
        )

    def test_migrate_keeps_valid_newer_state(self, tmp_path):
        state = tmp_path / "state" / "last_dispatch.json"
        state.parent.mkdir(parents=True)
        state.write_text(json.dumps({"channel": "feishu"}), encoding="utf-8")

        cu._migrate_last_dispatch_state(
            tmp_path,
            {"channel": "legacy", "user_id": "old", "session_id": "old"},
        )

        assert json.loads(state.read_text(encoding="utf-8")) == {
            "channel": "feishu",
        }

    def test_migrate_replaces_corrupt_state(self, tmp_path):
        state = tmp_path / "state" / "last_dispatch.json"
        state.parent.mkdir(parents=True)
        state.write_text("{not json", encoding="utf-8")

        cu._migrate_last_dispatch_state(
            tmp_path,
            {"channel": "qq", "user_id": "u2", "session_id": "s2"},
        )

        assert json.loads(state.read_text(encoding="utf-8"))["channel"] == "qq"

    def test_read_last_dispatch_unknown_agent_is_none(self, monkeypatch):
        monkeypatch.setattr(
            cu,
            "load_config",
            lambda: SimpleNamespace(
                agents=SimpleNamespace(profiles={}),
            ),
        )

        assert cu.read_last_dispatch("ghost") is None

    def test_read_last_dispatch_missing_state_file(
        self,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.setattr(
            cu,
            "load_config",
            lambda: SimpleNamespace(
                agents=SimpleNamespace(
                    profiles={
                        "a1": SimpleNamespace(workspace_dir=str(tmp_path)),
                    },
                ),
            ),
        )

        assert cu.read_last_dispatch("a1") is None

    def test_read_last_api_prefers_runtime_cache(self, monkeypatch):
        monkeypatch.setattr(cu, "_runtime_last_api", ("127.0.0.1", 4321))

        assert cu.read_last_api() == ("127.0.0.1", 4321)

    def test_read_last_api_falls_back_to_disk(self, monkeypatch):
        monkeypatch.setattr(cu, "_runtime_last_api", None)
        monkeypatch.setattr(
            cu,
            "load_config",
            lambda: SimpleNamespace(
                last_api=LastApiConfig(host="10.1.2.3", port=8080),
            ),
        )

        assert cu.read_last_api() == ("10.1.2.3", 8080)

    def test_read_last_api_without_any_value(self, monkeypatch):
        monkeypatch.setattr(cu, "_runtime_last_api", None)
        monkeypatch.setattr(
            cu,
            "load_config",
            lambda: SimpleNamespace(last_api=LastApiConfig()),
        )

        assert cu.read_last_api() is None

    def test_read_last_api_partial_disk_value(self, monkeypatch):
        """A host without a port is not a usable API address."""
        monkeypatch.setattr(cu, "_runtime_last_api", None)
        monkeypatch.setattr(
            cu,
            "load_config",
            lambda: SimpleNamespace(
                last_api=LastApiConfig(host="10.1.2.3", port=None),
            ),
        )

        assert cu.read_last_api() is None

    def test_write_last_api_updates_cache_and_disk(
        self,
        working_dir,
        fresh_config_cache,
        monkeypatch,
    ):
        monkeypatch.setattr(cu, "_runtime_last_api", None)

        cu.write_last_api("127.0.0.1", 5150)

        assert cu._runtime_last_api == ("127.0.0.1", 5150)
        persisted = json.loads(
            (working_dir / "config.json").read_text(encoding="utf-8"),
        )
        assert persisted["last_api"] == {"host": "127.0.0.1", "port": 5150}


# ---------------------------------------------------------------------------
# get_jobs_path / get_chats_path
# ---------------------------------------------------------------------------


class TestRuntimeFilePaths:
    def test_jobs_path(self, working_dir):
        assert cu.get_jobs_path() == working_dir / cu.JOBS_FILE

    def test_chats_path(self, working_dir):
        assert cu.get_chats_path() == working_dir / cu.CHATS_FILE

    def test_jobs_path_expands_tilde(self, working_dir, fake_home):
        """A ``~``-based working dir must be expanded, not left literal."""
        tilde = Path("~") / "qwenpaw-wd"
        assert str(cu.get_jobs_path()).startswith(str(tilde)) is False
        assert cu.get_jobs_path().parent == working_dir


# ---------------------------------------------------------------------------
# is_qwenpaw_running
# ---------------------------------------------------------------------------


class _FakeSocket:
    """A socket stand-in that records what was probed."""

    results: list = []
    raised: Exception | None = None
    created: list = []

    def __init__(self, *args, **kwargs):
        _FakeSocket.created.append(args)
        self.timeout = None
        self.closed = 0

    def settimeout(self, value):
        self.timeout = value

    def connect_ex(self, addr):
        _FakeSocket.probed = addr
        if _FakeSocket.raised is not None:
            raise _FakeSocket.raised
        return _FakeSocket.results.pop(0)

    def close(self):
        self.closed += 1


@pytest.fixture()
def fake_socket(monkeypatch):
    _FakeSocket.results = []
    _FakeSocket.raised = None
    _FakeSocket.created = []
    monkeypatch.setattr(cu.socket, "socket", _FakeSocket)
    return _FakeSocket


class TestIsQwenpawRunning:
    def test_no_api_address_means_not_running(self, monkeypatch, fake_socket):
        monkeypatch.setattr(cu, "read_last_api", lambda: None)

        assert cu.is_qwenpaw_running() is False
        assert fake_socket.created == []

    def test_successful_connect(self, monkeypatch, fake_socket):
        monkeypatch.setattr(cu, "read_last_api", lambda: ("127.0.0.1", 8000))
        fake_socket.results = [0]

        assert cu.is_qwenpaw_running() is True
        assert fake_socket.probed == ("127.0.0.1", 8000)

    def test_refused_connect(self, monkeypatch, fake_socket):
        monkeypatch.setattr(cu, "read_last_api", lambda: ("127.0.0.1", 8000))
        fake_socket.results = [getattr(socket, "ECONNREFUSED", 111)]

        assert cu.is_qwenpaw_running() is False

    def test_socket_exception_is_swallowed(self, monkeypatch, fake_socket):
        monkeypatch.setattr(cu, "read_last_api", lambda: ("127.0.0.1", 8000))
        fake_socket.raised = OSError("network unreachable")

        assert cu.is_qwenpaw_running() is False

    def test_read_failure_is_swallowed(self, monkeypatch, fake_socket):
        def boom():
            raise RuntimeError("config exploded")

        monkeypatch.setattr(cu, "read_last_api", boom)

        assert cu.is_qwenpaw_running() is False

    def test_socket_construction_failure_is_swallowed(
        self,
        monkeypatch,
        fake_socket,
    ):
        monkeypatch.setattr(cu, "read_last_api", lambda: ("127.0.0.1", 8000))

        def deny(*args, **kwargs):
            raise OSError("no sockets allowed")

        monkeypatch.setattr(cu.socket, "socket", deny)

        assert cu.is_qwenpaw_running() is False


# ---------------------------------------------------------------------------
# sanitize_mcp_clients
# ---------------------------------------------------------------------------


class TestSanitizeMcpClients:
    def test_no_mcp_section_is_a_noop(self):
        data = {"something": 1}

        cu.sanitize_mcp_clients(data, "agent-1")

        assert data == {"something": 1}

    def test_mcp_not_a_dict_is_a_noop(self):
        data = {"mcp": "oops"}

        cu.sanitize_mcp_clients(data, "agent-1")

        assert data == {"mcp": "oops"}

    def test_clients_not_a_dict_is_a_noop(self):
        data = {"mcp": {"clients": ["a", "b"]}}

        cu.sanitize_mcp_clients(data, "agent-1")

        assert data == {"mcp": {"clients": ["a", "b"]}}

    def test_non_dict_entry_is_dropped(self):
        data = {"mcp": {"clients": {"bad": "string-not-a-config"}}}

        cu.sanitize_mcp_clients(data, "agent-1")

        assert data["mcp"]["clients"] == {}

    def test_invalid_transport_is_dropped(self):
        """One broken client must not take the whole agent down."""
        data = {
            "mcp": {
                "clients": {
                    "broken": {"transport": "carrier-pigeon"},
                    "good": {"command": "npx", "args": ["-y", "server"]},
                },
            },
        }

        cu.sanitize_mcp_clients(data, "agent-1")

        assert list(data["mcp"]["clients"]) == ["good"]

    def test_invalid_boolean_is_dropped(self):
        data = {"mcp": {"clients": {"x": {"enabled": "maybe"}}}}

        cu.sanitize_mcp_clients(data, "agent-1")

        assert data["mcp"]["clients"] == {}

    def test_legacy_alias_is_normalised_not_dropped(self):
        """``isActive`` is a documented alias, so the entry must survive."""
        data = {
            "mcp": {
                "clients": {
                    "y": {
                        "isActive": False,
                        "baseUrl": "https://example.com/mcp",
                    },
                },
            },
        }

        cu.sanitize_mcp_clients(data, "agent-1")

        # ``isActive`` alone is NOT enough to keep the entry: the alias only
        # feeds ``enabled``, ``transport`` stays ``stdio`` and an empty
        # ``command`` fails validation.  ``baseUrl`` is what flips transport
        # to ``streamable_http`` (and feeds ``url``), so the entry survives.
        assert list(data["mcp"]["clients"]) == ["y"]

    def test_legacy_alias_alone_still_dropped_without_url(self):
        """Measured truth, not the docstring's promise."""
        data = {"mcp": {"clients": {"y": {"isActive": False}}}}

        cu.sanitize_mcp_clients(data, "agent-1")

        assert data["mcp"]["clients"] == {}

    def test_agent_id_with_newlines_is_sanitised_in_logs(self, caplog):
        data = {"mcp": {"clients": {"bad": {"transport": "nope"}}}}

        with caplog.at_level("WARNING"):
            cu.sanitize_mcp_clients(data, "agent\nname")

        joined = "\n".join(record.getMessage() for record in caplog.records)
        assert "agent\\nname" in joined
        assert "agent\nname" not in joined

    def test_empty_clients_dict_is_left_alone(self):
        data = {"mcp": {"clients": {}}}

        cu.sanitize_mcp_clients(data, "agent-1")

        assert data == {"mcp": {"clients": {}}}
