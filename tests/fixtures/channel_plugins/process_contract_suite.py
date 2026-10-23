# -*- coding: utf-8 -*-
# pylint: disable=unused-argument,redefined-outer-name
"""B1 contracts collected in a clean interpreter before platform imports."""

import importlib
import importlib.abc
import importlib.machinery
import json
from pathlib import Path
import socket
import subprocess
import sys
import threading

import pytest
from packaging.markers import default_environment
from packaging.tags import sys_tags


class PlatformImportGuard(importlib.abc.MetaPathFinder):
    """Record attempts so caught import errors cannot conceal violations."""

    def __init__(self):
        self.attempts = []

    @staticmethod
    def blocks(name):
        """Include candidate namespaces and SDKs even when installed."""
        return name.startswith(
            (
                "qwenpaw.app.channels",
                "plugin_feishu",
                "plugin_dingtalk",
                "alibabacloud_",
            ),
        ) or name.split(".")[0] in {
            "driver",
            "lark_oapi",
            "dingtalk_stream",
            "Tea",
            "PIL",
        }

    def find_spec(self, fullname, path=None, target=None):
        if self.blocks(fullname):
            self.attempts.append(fullname)
            raise AssertionError(
                f"Metadata path imported platform: {fullname}",
            )


GUARD = PlatformImportGuard()
assert not any(GUARD.blocks(name) for name in sys.modules)
sys.meta_path.insert(0, GUARD)
ROOT = Path(__file__).resolve().parents[3]
PLUGIN_ROOT = ROOT / "plugins/channel"
SOURCE = "4" * 64


@pytest.fixture(autouse=True)
def metadata_boundary(monkeypatch):
    """Metadata operations must not connect, install, or start workers."""

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Metadata operation started external work")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(subprocess.Popen, "__init__", forbidden)
    monkeypatch.setattr(threading.Thread, "start", forbidden)
    monkeypatch.setattr(
        sys,
        "meta_path",
        [GUARD, *[finder for finder in sys.meta_path if finder is not GUARD]],
    )
    yield
    assert not GUARD.attempts
    assert not any(GUARD.blocks(name) for name in sys.modules)


@pytest.fixture
def shared():
    """Missing B1 module is an assertion failure, not a collection error."""
    assert importlib.util.find_spec(
        "qwenpaw.channel_protocol.shared",
    ), "B1 shared descriptor/dependency/hello API is missing"
    return importlib.import_module("qwenpaw.channel_protocol.shared")


def requirements(tmp_path, text):
    """Write a real requirements declaration for metadata audit."""
    path = tmp_path / "requirements.txt"
    path.write_text(text, encoding="utf-8")
    return path


def hello_mapping():
    """Hand-authored shared identity; never fabricate a private environment."""
    return {
        "protocol_version": 2,
        "dependency_mode": "shared",
        "qwenpaw_version": "2.2.2b4",
        "channel_key": "feishu",
        "instance_id": "workspace-one",
        "generation": 7,
        "source_revision": SOURCE,
        "python_abi": "cp311-cp311",
        "platform_tag": "macosx_11_0_arm64",
        "marker_environment": default_environment(),
        "dependencies": [
            {
                "requirement": "b1-probe>=2",
                "name": "b1-probe",
                "installed_version": "2.5",
                "status": "satisfied",
            },
        ],
        "capabilities": ["media", "streaming"],
    }


def validate_hello(shared, value, **overrides):
    """Supply independent parent expectations to the public validator."""
    return shared.validate_shared_hello(
        value,
        **{
            "channel_key": "feishu",
            "instance_id": "workspace-one",
            "generation": 7,
            "source_revision": SOURCE,
            "qwenpaw_version": "2.2.2b4",
            "python_abi": "cp311-cp311",
            "platform_tag": "macosx_11_0_arm64",
            **overrides,
        },
    )


@pytest.mark.parametrize(
    "channel,qualname",
    [
        ("feishu", "FeishuDriver"),
        ("dingtalk", "DingTalkDriver"),
    ],
)
def test_static_discovery_requires_no_driver_or_sdk(shared, channel, qualname):
    """Listing candidate metadata must work before driver files exist."""
    path = PLUGIN_ROOT / channel / "channel.json"
    descriptor = shared.SharedChannelDescriptor.load(path)
    data = descriptor.to_mapping()
    assert data["schema_version"] == 2
    assert data["channel_key"] == channel
    assert data["process_mode"] == "runner_process"
    assert data["dependency_mode"] == "shared"
    assert data["entrypoint"] == {
        "scope": "runner",
        "module": channel + ".driver",
        "qualname": qualname,
    }
    assert data["label"]["en"] and data["label"]["zh"]
    assert data["requirements_file"] == "requirements.txt"
    assert not (
        {"requirements", "core_requirements", "isolated_requirements"}
        & data.keys()
    )
    assert (
        shared.SharedChannelDescriptor.from_json(path.read_bytes())
        == descriptor
    )
    audit = shared.audit_shared_dependencies(
        path.with_name("requirements.txt"),
        versions={},
    )
    assert audit.dependencies and not audit.satisfied
    assert all(item["status"] == "missing" for item in audit.to_mapping())


@pytest.mark.parametrize(
    "channel,model_name",
    [
        ("feishu", "FeishuConfig"),
        ("dingtalk", "DingTalkConfig"),
    ],
)
def test_static_config_preserves_model_and_inherited_fields(
    shared,
    channel,
    model_name,
):
    """Omitted ACL/renderer fields or changed defaults break fidelity."""
    config = importlib.import_module("qwenpaw.config.config")
    model = getattr(config, model_name)
    descriptor = shared.SharedChannelDescriptor.load(
        PLUGIN_ROOT / channel / "channel.json",
    ).to_mapping()
    fields = descriptor["config_fields"]
    properties = descriptor["config_schema"]["properties"]
    original = model.model_json_schema()["properties"]
    assert len(fields) == len(set(fields))
    assert set(fields) == set(properties) == set(model.model_fields)
    for name, schema in original.items():
        for key, value in schema.items():
            if key != "title":
                assert properties[name][key] == value, (channel, name, key)
    for name, value in model().model_dump().items():
        if "default" in properties[name]:
            assert properties[name]["default"] == value, (channel, name)
    assert properties["dm_policy"]["enum"] == ["open", "allowlist"]
    assert properties["allow_from"]["items"] == {"type": "string"}


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": 1},
        {"dependency_mode": "isolated"},
        {"process_mode": "in_process"},
        {"requirements_file": "../requirements.txt"},
        {
            "entrypoint": {
                "scope": "core",
                "module": "driver",
                "qualname": "Driver",
            },
        },
        {"config_fields": ["enabled", "enabled"]},
        {"unknown": True},
    ],
)
def test_shared_descriptor_rejects_invalid_modes_and_field_drift(
    shared,
    change,
):
    """A candidate must not masquerade as a legacy/in-process descriptor."""
    from qwenpaw.channel_protocol.errors import DescriptorValidationError

    value = json.loads((PLUGIN_ROOT / "feishu/channel.json").read_text())
    with pytest.raises(DescriptorValidationError):
        shared.SharedChannelDescriptor.from_mapping({**value, **change})


def test_dependency_statuses_follow_constraints_and_markers(shared, tmp_path):
    """Distinguish missing, old, compatible, and inactive requirements."""
    path = requirements(
        tmp_path,
        """# direct declarations only
B1_GOOD>=2,<3
b1-old>=2
b1-missing
b1-skipped>=99; python_version < '0'
b1-active>=1; python_version >= '0'
""",
    )
    audit = shared.audit_shared_dependencies(
        path,
        versions={
            "b1-good": "2.5",
            "b1-old": "1.9",
            "b1-active": "1.0",
        },
    )
    rows = audit.to_mapping()
    assert [
        (row["name"], row["installed_version"], row["status"]) for row in rows
    ] == [
        ("b1-active", "1.0", "satisfied"),
        ("b1-good", "2.5", "satisfied"),
        ("b1-missing", None, "missing"),
        ("b1-old", "1.9", "incompatible"),
        ("b1-skipped", None, "skipped"),
    ]
    from qwenpaw.channel_protocol.errors import ProtocolValidationError

    assert not audit.satisfied
    with pytest.raises(ProtocolValidationError) as rejected:
        audit.require_satisfied()
    assert rejected.value.reason_code == "DEPENDENCY_UNSATISFIED"


def test_default_audit_reads_distribution_metadata_without_import(
    shared,
    tmp_path,
    monkeypatch,
):
    """Distribution metadata determines availability without SDK imports."""
    info = tmp_path / "b1_probe-2.5.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: b1-probe\nVersion: 2.5\n",
    )
    (tmp_path / "b1_probe.py").write_text(
        "raise AssertionError('SDK was imported')",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    audit = shared.audit_shared_dependencies(
        requirements(tmp_path, "b1-probe>=2"),
    )
    assert audit.satisfied
    assert audit.to_mapping() == [
        {
            "requirement": "b1-probe>=2",
            "name": "b1-probe",
            "installed_version": "2.5",
            "status": "satisfied",
        },
    ]
    assert "b1_probe" not in sys.modules


@pytest.mark.parametrize(
    "declaration",
    [
        "b1-probe @ https://example.invalid/probe.whl",
        "b1-probe[extra]>=2",
        "--index-url https://example.invalid",
        "-r other.txt",
    ],
)
def test_audit_refuses_unverified_sources_and_install_options(
    shared,
    tmp_path,
    declaration,
):
    """Matching package names cannot verify URL provenance or extras."""
    from qwenpaw.channel_protocol.errors import ProtocolValidationError

    with pytest.raises(ProtocolValidationError):
        shared.audit_shared_dependencies(
            requirements(tmp_path, declaration),
            versions={"b1-probe": "2.5"},
        )


def test_shared_hello_round_trips_through_existing_rpc_dispatch(shared):
    """Shared hello uses the existing DTO/RPC path with explicit version 2."""
    from qwenpaw.channel_protocol.models import validate_method_params

    value = hello_mapping()
    parsed = validate_method_params("runner.hello", value)
    assert isinstance(parsed, shared.SharedHelloParams)
    assert parsed.to_mapping() == value
    assert validate_hello(shared, parsed) == parsed
    assert not (
        {"environment_spec_id", "environment_id", "lock_sha256"}
        & parsed.to_mapping().keys()
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("protocol_version", 1),
        ("channel_key", "dingtalk"),
        ("instance_id", "workspace-two"),
        ("generation", 8),
        ("source_revision", "5" * 64),
        ("qwenpaw_version", "other"),
        ("python_abi", "cp312-cp312"),
        ("platform_tag", "win_amd64"),
    ],
)
def test_shared_hello_rejects_parent_identity_mismatches(shared, field, value):
    """Different source, instance, generation, or runtime fails the fence."""
    from qwenpaw.channel_protocol.errors import ProtocolValidationError

    with pytest.raises(ProtocolValidationError) as rejected:
        validate_hello(shared, {**hello_mapping(), field: value})
    if field == "protocol_version":
        assert rejected.value.reason_code == "PROTOCOL_MISMATCH"


@pytest.mark.parametrize(
    "field",
    [
        "generation",
        "source_revision",
        "marker_environment",
        "dependencies",
    ],
)
def test_shared_hello_requires_complete_snapshot(shared, field):
    """Shared identity cannot omit instance fencing or metadata evidence."""
    from qwenpaw.channel_protocol.errors import ProtocolValidationError

    value = hello_mapping()
    value.pop(field)
    with pytest.raises(ProtocolValidationError):
        shared.SharedHelloParams.from_mapping(value)


@pytest.mark.parametrize(
    "extra",
    [
        {"environment_spec_id": "ches1_" + "1" * 64},
        {"environment_id": "ches1_" + "1" * 64 + ".install1_" + "2" * 32},
        {"lock_sha256": "0" * 64},
        {"generation": 0},
    ],
)
def test_shared_hello_refuses_private_environment_fields(shared, extra):
    """Shared hello must never smuggle dedicated-environment identities."""
    from qwenpaw.channel_protocol.errors import ProtocolValidationError

    with pytest.raises(ProtocolValidationError):
        shared.SharedHelloParams.from_mapping({**hello_mapping(), **extra})


@pytest.mark.parametrize(
    "version,status",
    [("1.0", "satisfied"), (None, "skipped")],
)
def test_shared_hello_does_not_trust_dependency_status(
    shared,
    version,
    status,
):
    """Forged status flags cannot hide an unmet active constraint."""
    from qwenpaw.channel_protocol.errors import ProtocolValidationError

    value = hello_mapping()
    value["dependencies"][0].update(installed_version=version, status=status)
    with pytest.raises(ProtocolValidationError) as rejected:
        validate_hello(shared, value)
    assert rejected.value.reason_code == "DEPENDENCY_UNSATISFIED"


def test_shared_hello_uses_child_markers_and_authoritative_requirements(
    shared,
    tmp_path,
):
    """A configured child runtime determines markers; omission still fails."""
    from qwenpaw.channel_protocol.errors import ProtocolValidationError

    path = requirements(tmp_path, 'b1-probe>=2; python_version < "3.12"')
    value = hello_mapping()
    value["marker_environment"].update(
        python_version="3.12",
        python_full_version="3.12.1",
    )
    value["python_abi"] = "cp312-cp312"
    value["dependencies"][0].update(
        requirement='b1-probe>=2; python_version < "3.12"',
        installed_version=None,
        status="skipped",
    )
    assert (
        validate_hello(
            shared,
            value,
            python_abi="cp312-cp312",
            requirements_path=path,
        ).generation
        == 7
    )
    value["marker_environment"].update(
        python_version="3.11",
        python_full_version="3.11.9",
    )
    value["python_abi"] = "cp311-cp311"
    with pytest.raises(ProtocolValidationError):
        validate_hello(shared, value, requirements_path=path)
    value = hello_mapping()
    value["dependencies"] = []
    with pytest.raises(ProtocolValidationError):
        validate_hello(shared, value, requirements_path=path)


def test_trusted_host_reports_actual_runtime_and_metadata(
    shared,
    tmp_path,
    monkeypatch,
):
    """Host derives runtime metadata and uses immutable source identity."""
    from qwenpaw.channel_protocol.runner_host import RunnerProtocolHost

    info = tmp_path / "b1_probe-2.5.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: b1-probe\nVersion: 2.5\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    path = requirements(tmp_path, "b1-probe>=2")
    tag = next(sys_tags())
    hello = RunnerProtocolHost(SOURCE).create_shared_hello(
        channel_key="feishu",
        instance_id="workspace-one",
        generation=7,
        qwenpaw_version="2.2.2b4",
        requirements_path=path,
        capabilities=("media", "streaming"),
    )
    assert hello.source_revision == SOURCE
    assert hello.python_abi == f"{tag.interpreter}-{tag.abi}"
    assert hello.platform_tag == tag.platform
    assert hello.to_mapping()["marker_environment"] == default_environment()
    assert hello.to_mapping()["dependencies"][0]["installed_version"] == "2.5"
    path.write_text("b1-probe>=3")
    from qwenpaw.channel_protocol.errors import ProtocolValidationError

    with pytest.raises(ProtocolValidationError) as rejected:
        RunnerProtocolHost(SOURCE).create_shared_hello(
            channel_key="feishu",
            instance_id="workspace-one",
            generation=7,
            qwenpaw_version="2.2.2b4",
            requirements_path=path,
        )
    assert rejected.value.reason_code == "DEPENDENCY_UNSATISFIED"


def test_legacy_v1_hello_dispatch_is_preserved():
    """Adding shared mode preserves exact dedicated hello v1 wire data."""
    from qwenpaw.channel_protocol.models import (
        HelloParams,
        validate_method_params,
    )

    value = {
        "protocol_version": 1,
        "qwenpaw_version": "0.1",
        "channel_key": "feishu",
        "instance_id": "legacy",
        "source_revision": SOURCE,
        "environment_spec_id": "ches1_" + "1" * 64,
        "environment_id": "ches1_" + "1" * 64 + ".install1_" + "2" * 32,
        "lock_sha256": "0" * 64,
        "python_abi": "cp313-cp313",
        "platform_tag": "macosx_11_0_arm64",
        "capabilities": ["media"],
    }
    parsed = validate_method_params("runner.hello", value)
    assert isinstance(parsed, HelloParams)
    assert parsed.to_mapping() == value
