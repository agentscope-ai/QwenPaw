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
    _requested_constraints,
    network_allow_is_absolute,
    report_unenforced_config,
)
from qwenpaw.sandbox.linux_sandbox import LinuxSandbox
from qwenpaw.sandbox.local_sandbox import LocalSandbox, NoneSandbox
from qwenpaw.sandbox.macos_sandbox import MacOSSandbox

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
            _config(env_mode="allowlist", platform_hints={"a": "b"}),
            "FakeSandbox",
            frozenset(),
        )
        levels = {level for level, _ in _reports(caplog)}
        assert levels == {logging.DEBUG}

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
    def test_configured_shell_actually_runs_the_command(self):
        sandbox = NoneSandbox(
            _config(shell_executable="/bin/sh", workspace_dir="/tmp"),
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
