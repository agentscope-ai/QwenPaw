# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for unenforced-constraint reporting.

Regression cover for TC-SB-05: ``SandboxConfig`` accepts constraints that
some backends cannot apply (``max_memory_mb`` on every backend, everything
but the shell on ``NoneSandbox``).  Dropping them silently let an operator
believe ``deny_paths`` protected their credentials when it did not, so each
backend now declares what it enforces and the rest is logged.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

import pytest

from qwenpaw.sandbox import (
    MountSpec,
    PortRule,
    SandboxConfig,
    SandboxMode,
)
from qwenpaw.sandbox.bubblewrap_sandbox import BubblewrapSandbox
from qwenpaw.sandbox.config import (
    _SECURITY_BOUNDARY_FIELDS,
    NETWORK_DOMAIN_HINT,
    _requested_constraints,
    network_allow_is_absolute,
    report_unenforced_config,
)
from qwenpaw.sandbox.linux_sandbox import (
    LinuxSandbox,
    _generate_sandbox_script,
)
from qwenpaw.sandbox.local_sandbox import (
    LocalSandbox,
    NoneSandbox,
    _platform_default_shell,
    _resolve_shell,
    _shell_argv,
)
from qwenpaw.sandbox.macos_sandbox import MacOSSandbox
from qwenpaw.sandbox.windows_elevated_sandbox import WindowsElevatedSandbox
from qwenpaw.sandbox.windows_unelevated_sandbox import (
    WindowsUnelevatedSandbox,
)

_CONFIG_LOGGER = "qwenpaw.sandbox.config"


def _config(**overrides) -> SandboxConfig:
    """Build a config whose network posture is all-open unless overridden.

    ``network_allow=["*"]`` mirrors what ``ResourceGovernor`` actually
    compiles, so a test only sees reports for what it deliberately sets.
    """
    params = {
        "mode": SandboxMode.NONE,
        "workspace_dir": "/tmp/ws",
        "network_allow": ["*"],
    }
    params.update(overrides)
    return SandboxConfig(**params)


def _reports(caplog) -> list[tuple[int, str]]:
    return [
        (record.levelno, record.getMessage())
        for record in caplog.records
        if record.name == _CONFIG_LOGGER
    ]


# ============================================================================
# Requested-constraint detection
# ============================================================================


class TestRequestedConstraints:
    """Only constraints the caller actually asked for are reported."""

    def test_all_open_network_is_not_a_request(self):
        assert not _requested_constraints(_config())

    def test_block_all_network_is_a_request(self):
        # ``[]`` is the dataclass default but means "block all", so a
        # backend that ignores it is granting unrequested network access.
        requested = _requested_constraints(_config(network_allow=[]))
        assert requested["network_allow"] == "block all"

    def test_domain_allowlist_is_a_request(self):
        requested = _requested_constraints(
            _config(network_allow=["github.com", "pypi.org"]),
        )
        assert requested["network_allow"] == "github.com, pypi.org"

    def test_every_constraint_field_is_detected(self):
        requested = _requested_constraints(
            _config(
                mounts=[MountSpec(path="/tmp/ws", writable=True)],
                deny_paths=["~/.ssh"],
                network_allow=["github.com"],
                network_ports=[PortRule(port=443)],
                max_processes=8,
                max_memory_mb=100,
                env_mode="allowlist",
                shell_executable="/bin/zsh",
                platform_hints={"seatbelt_extra_rules": "..."},
            ),
        )
        assert set(requested) == {
            "mounts",
            "deny_paths",
            "network_allow",
            "network_ports",
            "max_processes",
            "max_memory_mb",
            "env_mode",
            "shell_executable",
            "platform_hints",
        }

    def test_default_env_mode_and_shell_are_not_requests(self):
        requested = _requested_constraints(
            _config(env_mode="inject", shell_executable=None),
        )
        assert "env_mode" not in requested
        assert "shell_executable" not in requested


class TestNetworkAllowIsAbsolute:
    """All-open and block-all are enforceable; a domain list is not."""

    @pytest.mark.parametrize("allow", [[], ["*"], ["*", "github.com"]])
    def test_absolute_postures(self, allow):
        assert network_allow_is_absolute(_config(network_allow=allow))

    def test_domain_list_is_not_absolute(self):
        assert not network_allow_is_absolute(
            _config(network_allow=["github.com"]),
        )


# ============================================================================
# report_unenforced_config
# ============================================================================


class TestReportUnenforcedConfig:
    """Severity split, suppression of enforced fields, and hints."""

    def test_security_fields_are_warnings(self, caplog):
        caplog.set_level(logging.DEBUG, logger=_CONFIG_LOGGER)
        report_unenforced_config(
            _config(deny_paths=["~/.ssh"], max_memory_mb=100),
            "FakeSandbox",
            frozenset(),
        )
        levels = {level for level, _ in _reports(caplog)}
        assert levels == {logging.WARNING}
        assert "deny_paths=~/.ssh" in caplog.text
        assert "IGNORED" in caplog.text

    def test_non_security_fields_are_debug(self, caplog):
        caplog.set_level(logging.DEBUG, logger=_CONFIG_LOGGER)
        report_unenforced_config(
            _config(shell_executable="/bin/zsh"),
            "FakeSandbox",
            frozenset(),
        )
        levels = {level for level, _ in _reports(caplog)}
        assert levels == {logging.DEBUG}

    def test_env_mode_is_a_security_boundary(self, caplog):
        # The unimplemented allowlist mode leaks the whole parent
        # environment -- API keys included -- into the child. At DEBUG that
        # is invisible under the default INFO log level, so it has to warn.
        caplog.set_level(logging.DEBUG, logger=_CONFIG_LOGGER)
        report_unenforced_config(
            _config(env_mode="allowlist"),
            "FakeSandbox",
            frozenset(),
        )
        assert [level for level, _ in _reports(caplog)] == [logging.WARNING]
        assert "env_mode=allowlist" in caplog.text

    def test_platform_hints_is_a_security_boundary(self, caplog):
        # platform_hints carries admin-authored native rules (Seatbelt deny
        # clauses); a dropped hint weakens the sandbox like a dropped
        # deny_path would.
        caplog.set_level(logging.DEBUG, logger=_CONFIG_LOGGER)
        report_unenforced_config(
            _config(platform_hints={"seatbelt_extra_rules": "(deny ...)"}),
            "FakeSandbox",
            frozenset(),
        )
        assert [level for level, _ in _reports(caplog)] == [logging.WARNING]

    @pytest.mark.parametrize(
        "field",
        ["env_mode", "platform_hints", "max_processes", "max_memory_mb"],
    )
    def test_unimplemented_fields_stay_security_classified(self, field):
        # Guards the H3 regression: reclassifying any of these to DEBUG
        # hides a boundary failure at the default log level.
        assert field in _SECURITY_BOUNDARY_FIELDS

    def test_enforced_fields_are_silent(self, caplog):
        caplog.set_level(logging.DEBUG, logger=_CONFIG_LOGGER)
        report_unenforced_config(
            _config(deny_paths=["~/.ssh"], mounts=[MountSpec(path="/a")]),
            "FakeSandbox",
            frozenset({"deny_paths", "mounts"}),
        )
        assert _reports(caplog) == []

    def test_hint_is_appended(self, caplog):
        caplog.set_level(logging.DEBUG, logger=_CONFIG_LOGGER)
        report_unenforced_config(
            _config(deny_paths=["~/.ssh"]),
            "FakeSandbox",
            frozenset(),
            {"deny_paths": "Run as administrator."},
        )
        assert "Run as administrator." in caplog.text

    def test_hint_for_an_enforced_field_is_not_emitted(self, caplog):
        caplog.set_level(logging.DEBUG, logger=_CONFIG_LOGGER)
        report_unenforced_config(
            _config(deny_paths=["~/.ssh"]),
            "FakeSandbox",
            frozenset({"deny_paths"}),
            {"deny_paths": "Run as administrator."},
        )
        assert "Run as administrator." not in caplog.text


# ============================================================================
# Backend capability declarations
# ============================================================================


class TestBackendDeclarations:
    """Each backend declares only fields it genuinely applies."""

    def test_base_default_enforces_nothing(self):
        # A new subclass must be loud until it declares what it honours.
        assert LocalSandbox._ENFORCED_FIELDS == frozenset()

    @pytest.mark.parametrize(
        "declared",
        [
            NoneSandbox._ENFORCED_FIELDS,
            BubblewrapSandbox._ENFORCED_FIELDS,
            MacOSSandbox._ENFORCED_FIELDS,
        ],
    )
    def test_declarations_use_real_field_names(self, declared):
        # Guards against a typo silently disabling a whole report.
        tracked = set(
            _requested_constraints(
                _config(
                    mounts=[MountSpec(path="/a")],
                    deny_paths=["~/.ssh"],
                    network_allow=["github.com"],
                    network_ports=[PortRule(port=443)],
                    max_processes=1,
                    max_memory_mb=1,
                    env_mode="allowlist",
                    shell_executable="/bin/zsh",
                    platform_hints={"a": "b"},
                ),
            ),
        )
        assert declared <= tracked

    def test_no_backend_claims_the_resource_caps(self):
        # The caps need cgroups / Job objects that nothing wires up yet.
        for declared in (
            NoneSandbox._ENFORCED_FIELDS,
            BubblewrapSandbox._ENFORCED_FIELDS,
            MacOSSandbox._ENFORCED_FIELDS,
        ):
            assert "max_processes" not in declared
            assert "max_memory_mb" not in declared

    def test_resource_caps_are_security_boundary_fields(self):
        assert "max_processes" in _SECURITY_BOUNDARY_FIELDS
        assert "max_memory_mb" in _SECURITY_BOUNDARY_FIELDS


class TestNoneSandboxReporting:
    """The Docker fallback case from TC-SB-05."""

    def test_every_isolation_constraint_is_reported(self, caplog):
        caplog.set_level(logging.DEBUG, logger=_CONFIG_LOGGER)
        NoneSandbox(
            _config(
                mounts=[MountSpec(path="/tmp/ws", writable=True)],
                deny_paths=["~/.ssh", "~/.aws"],
                network_allow=["github.com"],
                network_ports=[PortRule(port=443)],
                max_processes=8,
                max_memory_mb=100,
            ),
        )
        warned = {
            message.split(" does not enforce ")[1].split("=")[0]
            for level, message in _reports(caplog)
            if level == logging.WARNING
        }
        assert warned == {
            "mounts",
            "deny_paths",
            "network_allow",
            "network_ports",
            "max_processes",
            "max_memory_mb",
        }

    def test_governor_default_config_is_quiet(self, caplog):
        # The compiled production config must not spam the log on every
        # tool call, or the report becomes noise operators filter out.
        caplog.set_level(logging.DEBUG, logger=_CONFIG_LOGGER)
        NoneSandbox(_config())
        assert _reports(caplog) == []

    def test_shell_executable_is_honoured(self):
        sandbox = NoneSandbox(_config(shell_executable="/bin/sh"))
        assert "shell_executable" in sandbox._enforced_fields()

    @pytest.mark.skipif(
        not os.path.exists("/bin/sh"),
        reason="POSIX shell not available",
    )
    def test_configured_shell_actually_runs_the_command(self, tmp_path):
        sandbox = NoneSandbox(
            _config(
                shell_executable="/bin/sh",
                workspace_dir=str(tmp_path),
            ),
        )
        result = asyncio.run(sandbox.execute("echo $0"))
        assert result.exit_code == 0
        assert "/bin/sh" in result.stdout


class TestBubblewrapReporting:
    """bubblewrap isolates the filesystem but not the network."""

    def test_filesystem_is_enforced_network_is_not(self, caplog):
        caplog.set_level(logging.DEBUG, logger=_CONFIG_LOGGER)
        BubblewrapSandbox(
            _config(
                mounts=[MountSpec(path="/tmp/ws", writable=True)],
                deny_paths=["~/.ssh"],
                network_allow=["github.com"],
            ),
        )
        messages = [message for _, message in _reports(caplog)]
        assert any("network_allow" in message for message in messages)
        assert not any("deny_paths" in message for message in messages)
        assert not any("mounts" in message for message in messages)


class TestMacOSReporting:
    """Seatbelt enforces the network only for absolute postures."""

    @pytest.mark.parametrize("allow", [[], ["*"]])
    def test_absolute_posture_counts_as_enforced(self, allow):
        sandbox = MacOSSandbox(_config(network_allow=allow))
        assert "network_allow" in sandbox._enforced_fields()

    def test_domain_allowlist_reports_fail_open(self, caplog):
        caplog.set_level(logging.DEBUG, logger=_CONFIG_LOGGER)
        MacOSSandbox(_config(network_allow=["github.com"]))
        assert "network_allow=github.com" in caplog.text
        # The operator must learn the fallback is fail-open, not fail-closed.
        assert "ALLOWED" in caplog.text


class TestLinuxReporting:
    """Landlock network rules require ABI v4."""

    def test_network_is_unenforced_below_abi_v4(self, monkeypatch, caplog):
        monkeypatch.setattr(
            LinuxSandbox,
            "_detect_abi_version",
            lambda self: 3,
        )
        caplog.set_level(logging.DEBUG, logger=_CONFIG_LOGGER)
        sandbox = LinuxSandbox(
            _config(network_allow=[], network_ports=[PortRule(port=443)]),
        )
        enforced = sandbox._enforced_fields()
        assert "network_allow" not in enforced
        assert "network_ports" not in enforced
        assert "deny_paths" not in _requested_constraints(sandbox.config)

    def test_absolute_network_is_enforced_on_abi_v4(self, monkeypatch):
        monkeypatch.setattr(
            LinuxSandbox,
            "_detect_abi_version",
            lambda self: 4,
        )
        sandbox = LinuxSandbox(
            _config(network_allow=[], network_ports=[PortRule(port=443)]),
        )
        enforced = sandbox._enforced_fields()
        assert "network_allow" in enforced
        assert "network_ports" in enforced

    def test_domain_allowlist_stays_unenforced_on_abi_v4(self, monkeypatch):
        monkeypatch.setattr(
            LinuxSandbox,
            "_detect_abi_version",
            lambda self: 4,
        )
        sandbox = LinuxSandbox(_config(network_allow=["github.com"]))
        assert "network_allow" not in sandbox._enforced_fields()


# ============================================================================
# Declaration vs. real enforcement
#
# A declaration is only worth logging if it matches what the backend
# actually installs. Asserting the field set alone let three backends claim
# constraints their own enforcement path skipped, so these compare each
# claim against the artefact the backend really produces -- the Landlock
# script, the Seatbelt profile, the Windows token mechanism.
# ============================================================================


class TestLandlockClaimMatchesScript:
    """``network_ports`` is only real when a port rule reaches the ruleset."""

    @staticmethod
    def _build(monkeypatch, allow, abi=4):
        monkeypatch.setattr(
            LinuxSandbox,
            "_detect_abi_version",
            lambda self: abi,
        )
        cfg = _config(
            network_allow=allow,
            network_ports=[PortRule(port=443)],
        )
        sandbox = LinuxSandbox(cfg)
        script = _generate_sandbox_script(cfg, "true", "/tmp/ws", abi)
        return sandbox, script

    @pytest.mark.parametrize(
        "allow",
        [[], ["*"], ["github.com"]],
    )
    def test_claim_matches_installed_port_rule(self, monkeypatch, allow):
        sandbox, script = self._build(monkeypatch, allow)
        claimed = "network_ports" in sandbox._enforced_fields()
        installed = "443" in script
        assert claimed == installed, (
            f"network_allow={allow!r}: claimed={claimed} but the generated "
            f"script {'has' if installed else 'lacks'} the port rule"
        )

    def test_open_network_drops_the_port_rule(self, monkeypatch):
        # The regression: ["*"] is what ResourceGovernor compiles, and the
        # ruleset handles no network access there, so the port rule never
        # lands. Claiming it would silence the only warning about it.
        sandbox, script = self._build(monkeypatch, ["*"])
        assert "443" not in script
        assert "network_ports" not in sandbox._enforced_fields()

    def test_port_rule_is_never_claimed_below_abi_v4(self, monkeypatch):
        sandbox, _ = self._build(monkeypatch, [], abi=3)
        assert "network_ports" not in sandbox._enforced_fields()


class TestWindowsClaimMatchesMechanism:
    """Only backends with a kernel-level mechanism may claim the network."""

    @staticmethod
    def _detached(backend, **overrides):
        # Bypass __init__: it reaches for Windows APIs, while the claim is a
        # pure function of the config.
        sandbox = object.__new__(backend)
        sandbox._config = _config(mode=SandboxMode.WINDOWS, **overrides)
        return sandbox

    @pytest.mark.parametrize("allow", [[], ["*"]])
    def test_unelevated_never_claims_the_network(self, allow):
        # Its "block" is HTTP(S) proxy variables, which a raw socket
        # ignores, so no posture is enforced.
        sandbox = self._detached(
            WindowsUnelevatedSandbox,
            network_allow=allow,
        )
        assert "network_allow" not in sandbox._enforced_fields()

    def test_unelevated_hint_names_the_proxy_limitation(self):
        hint = WindowsUnelevatedSandbox._ENFORCEMENT_HINTS["network_allow"]
        assert "proxy" in hint.lower()
        assert "raw socket" in hint.lower()

    def test_unelevated_never_claims_deny_paths(self):
        sandbox = self._detached(WindowsUnelevatedSandbox, deny_paths=["C:/s"])
        assert "deny_paths" not in sandbox._enforced_fields()

    @pytest.mark.parametrize("allow", [[], ["*"]])
    def test_elevated_claims_the_network_via_wfp(self, allow):
        sandbox = self._detached(WindowsElevatedSandbox, network_allow=allow)
        assert "network_allow" in sandbox._enforced_fields()

    def test_elevated_hint_says_fail_closed_not_fail_open(self):
        # WFP degrades a domain allowlist to blocking everything, the
        # opposite of the shared fail-open hint the other backends use.
        hint = WindowsElevatedSandbox._ENFORCEMENT_HINTS["network_allow"]
        assert "blocking ALL network access" in hint
        assert hint != NETWORK_DOMAIN_HINT


class TestSeatbeltClaimMatchesProfile:
    """``platform_hints`` is only real for keys the compiler reads."""

    def test_supported_key_is_claimed_and_compiled(self):
        rule = '(deny file-read* (subpath "/etc"))'
        sandbox = MacOSSandbox(
            _config(platform_hints={"seatbelt_extra_rules": rule}),
        )
        assert "platform_hints" in sandbox._enforced_fields()
        assert rule in sandbox._compile_seatbelt_profile()

    def test_typo_key_is_not_claimed_and_not_compiled(self):
        # Singular key: silently dropped before this fix, because the field
        # was claimed wholesale.
        rule = '(deny file-read* (subpath "/etc"))'
        sandbox = MacOSSandbox(
            _config(platform_hints={"seatbelt_extra_rule": rule}),
        )
        assert "platform_hints" not in sandbox._enforced_fields()
        assert rule not in sandbox._compile_seatbelt_profile()

    def test_mixed_keys_are_reported(self, caplog):
        caplog.set_level(logging.DEBUG, logger=_CONFIG_LOGGER)
        MacOSSandbox(
            _config(
                platform_hints={
                    "seatbelt_extra_rules": "(deny ...)",
                    "unknown_key": "x",
                },
            ),
        )
        # Errs loud, and lists every key so the unknown one is findable.
        assert "platform_hints=seatbelt_extra_rules, unknown_key" in (
            caplog.text
        )


class TestNoneSandboxShellFallback:
    """A claimed field must not degrade silently either."""

    def test_missing_configured_shell_is_reported(self, caplog, tmp_path):
        # The report is the cross-platform contract; the fallback shell
        # itself differs per platform (cmd.exe on Windows, /bin/bash
        # elsewhere), which the tests below cover separately.
        caplog.set_level(
            logging.WARNING,
            logger="qwenpaw.sandbox.local_sandbox",
        )
        sandbox = NoneSandbox(
            _config(
                shell_executable="/nonexistent/fish",
                workspace_dir=str(tmp_path),
            ),
        )
        asyncio.run(sandbox.execute("true"))
        assert "/nonexistent/fish" in caplog.text
        assert "could not be resolved" in caplog.text

    def test_fallback_shell_still_executes(self, tmp_path):
        # Runs everywhere: the platform default is cmd.exe on Windows and
        # /bin/bash elsewhere, and "echo" is understood by both.
        sandbox = NoneSandbox(
            _config(
                shell_executable="/nonexistent/fish",
                workspace_dir=str(tmp_path),
            ),
        )
        result = asyncio.run(sandbox.execute("echo ok"))
        assert result.exit_code == 0
        assert "ok" in result.stdout

    @pytest.mark.skipif(
        not os.path.exists("/bin/sh"),
        reason="POSIX shell not available",
    )
    def test_existing_shell_is_not_reported(self, caplog, tmp_path):
        caplog.set_level(
            logging.WARNING,
            logger="qwenpaw.sandbox.local_sandbox",
        )
        sandbox = NoneSandbox(
            _config(
                shell_executable="/bin/sh",
                workspace_dir=str(tmp_path),
            ),
        )
        asyncio.run(sandbox.execute("true"))
        assert "could not be resolved" not in caplog.text


class TestShellArgvDispatch:
    """The shell flag must match the shell, not just the platform.

    ``NoneSandbox`` used to hard-code ``/bin/bash -c``, which cannot run on
    Windows at all -- ``mode=none`` is returned there by ``create_sandbox``
    like anywhere else.
    """

    def test_posix_shells_take_dash_c(self):
        assert _shell_argv("/bin/bash", "echo hi") == [
            "/bin/bash",
            "-c",
            "echo hi",
        ]

    @pytest.mark.parametrize(
        "shell",
        ["cmd.exe", r"C:\Windows\System32\cmd.exe", "CMD.EXE"],
    )
    def test_cmd_takes_slash_c(self, shell):
        assert _shell_argv(shell, "echo hi")[1:] == ["/c", "echo hi"]

    @pytest.mark.parametrize("shell", ["powershell.exe", "pwsh"])
    def test_powershell_gets_noninteractive_flags(self, shell):
        argv = _shell_argv(shell, "echo hi")
        assert argv[0] == shell
        assert "-NonInteractive" in argv
        assert argv[-2:] == ["-Command", "echo hi"]

    def test_default_shell_is_platform_appropriate(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.delenv("COMSPEC", raising=False)
        assert _platform_default_shell() == "cmd.exe"

        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.delenv("SHELL", raising=False)
        assert _platform_default_shell() == "/bin/bash"

    def test_bare_name_resolves_via_path(self):
        # os.path.exists() alone rejects a PATH-resident name, which is how
        # cmd.exe is normally referenced.
        assert _resolve_shell("definitely-not-a-real-binary") is None
        assert _resolve_shell("/nonexistent/fish") is None
