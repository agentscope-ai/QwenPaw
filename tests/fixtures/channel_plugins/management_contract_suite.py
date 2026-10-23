# -*- coding: utf-8 -*-
"""Independent SDK-free G3 public DTO contracts, with no global SDK mocks."""

from copy import deepcopy
import importlib
import importlib.abc
import importlib.util
import json
from pathlib import Path
import sys

import pytest


class ManagementImportGuard(importlib.abc.MetaPathFinder):
    """A caught SDK import still leaves evidence for the final assertion."""

    def __init__(self):
        self.attempts = []

    @staticmethod
    def blocks(name):
        return name.startswith(
            (
                "qwenpaw.app.channels.",
                "qwenpaw.app.qrcode",
                "feishu.",
                "dingtalk.",
                "wechat.",
                "qq.",
                "wecom.",
                "mattermost.",
                "mqtt.",
            )
        ) or name.split(".")[0] in {
            "lark_oapi",
            "dingtalk_stream",
            "wecom_aibot_sdk",
            "wecom_aibot",
            "paho",
            "nio",
            "discord",
            "telegram",
            "slack_bolt",
            "Tea",
            "cryptography",
            "PIL",
            "aibot",
        }

    def find_spec(self, fullname, path=None, target=None):
        if self.blocks(fullname):
            self.attempts.append(fullname)
            raise AssertionError(
                "Management DTO imported platform: " + fullname
            )


GUARD = ManagementImportGuard()
assert not any(GUARD.blocks(name) for name in sys.modules), [
    name for name in sys.modules if GUARD.blocks(name)
]
sys.meta_path.insert(0, GUARD)
MODULE = "qwenpaw.channel_protocol.management"


@pytest.fixture(autouse=True)
def sdk_free_boundary():
    yield
    assert not GUARD.attempts
    assert not any(GUARD.blocks(name) for name in sys.modules)


@pytest.fixture
def dto():
    assert importlib.util.find_spec(
        MODULE
    ), "G3 management DTO module is missing; constraints have not executed"
    api = importlib.import_module(MODULE)
    assert hasattr(api, "ManagementRequest")
    assert hasattr(api, "ManagementResult")
    return api


def request_mapping(operation="qrcode.fetch"):
    parameters = {
        "qrcode.fetch": {"config": {"enabled": False}},
        "qrcode.poll": {
            "config": {"enabled": False},
            "continuation": "fixture-continuation",
        },
        "connection.verify": {"config": {}, "level": "reachability"},
    }[operation]
    return {
        "request_id": "d095974b-e2f1-4e78-81e2-47767df96632",
        "plugin_id": "wechat",
        "workspace_id": "workspace-A",
        "channel_key": "wechat",
        "instance_id": "b35b9c25-86d9-4e04-8f75-f44d426cb21c",
        "generation": 1,
        "source_revision": "a" * 64,
        "operation": operation,
        "timeout_ms": 65000,
        "parameters": parameters,
    }


def result_mapping(operation="qrcode.fetch"):
    value = request_mapping(operation)
    value.pop("parameters")
    value.pop("timeout_ms")
    value.update(
        outcome="ok",
        reason_code=None,
        result={
            "qrcode.fetch": {
                "scan_url": "https://fixture.invalid/scan",
                "continuation": "fixture-continuation",
            },
            "qrcode.poll": {
                "status": "confirmed",
                "credentials": {
                    "bot_token": "fixture-token",
                    "base_url": "https://fixture.invalid",
                },
            },
            "connection.verify": {
                "level": "reachability",
                "verdict": "passed",
                "reason_code": None,
                "notes": ["Local fixture reached"],
            },
        }[operation],
    )
    return value


def replace_path(value, path, replacement):
    copied = deepcopy(value)
    target = copied
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement
    return copied


@pytest.mark.parametrize(
    "operation",
    [
        "qrcode.fetch",
        "qrcode.poll",
        "connection.verify",
    ],
)
def test_request_and_result_round_trip_exact_public_shape(dto, operation):
    request = request_mapping(operation)
    result = result_mapping(operation)
    assert dto.ManagementRequest.from_mapping(request).to_mapping() == request
    assert dto.ManagementResult.from_mapping(result).to_mapping() == result


@pytest.mark.parametrize("kind", ["request", "result"])
@pytest.mark.parametrize(
    "path,value",
    [
        (("request_id",), ""),
        (("request_id",), "not-a-uuid"),
        (("plugin_id",), ""),
        (("workspace_id",), ""),
        (("channel_key",), ""),
        (("instance_id",), ""),
        (("generation",), True),
        (("generation",), False),
        (("generation",), 0),
        (("generation",), -1),
        (("generation",), 1.5),
        (("generation",), float("nan")),
        (("source_revision",), "b" * 63),
        (("source_revision",), "g" * 64),
        (("operation",), "state.get"),
        (("operation",), "logout"),
        (("operation",), "module.Driver.manage"),
        (("operation",), object()),
        (("function",), "manage"),
        (("module",), "wechat.driver"),
        (("qualname",), "Driver.manage"),
        (("unknown",), True),
    ],
)
def test_dto_rejects_invalid_identity_operation_and_extra_fields(
    dto,
    kind,
    path,
    value,
):
    from qwenpaw.channel_protocol.errors import ProtocolValidationError

    data = request_mapping() if kind == "request" else result_mapping()
    cls = dto.ManagementRequest if kind == "request" else dto.ManagementResult
    with pytest.raises(ProtocolValidationError):
        cls.from_mapping(replace_path(data, path, value))


@pytest.mark.parametrize("kind", ["request", "result"])
@pytest.mark.parametrize(
    "field",
    [
        "request_id",
        "plugin_id",
        "workspace_id",
        "channel_key",
        "instance_id",
        "generation",
        "source_revision",
        "operation",
    ],
)
def test_envelope_requires_every_identity_field(dto, kind, field):
    from qwenpaw.channel_protocol.errors import ProtocolValidationError

    data = request_mapping() if kind == "request" else result_mapping()
    data.pop(field)
    cls = dto.ManagementRequest if kind == "request" else dto.ManagementResult
    with pytest.raises(ProtocolValidationError):
        cls.from_mapping(data)


@pytest.mark.parametrize(
    "timeout", [True, False, 0, -1, 65001, 1.5, float("nan")]
)
def test_request_timeout_is_integer_and_within_one_to_65000_ms(dto, timeout):
    from qwenpaw.channel_protocol.errors import ProtocolValidationError

    with pytest.raises(ProtocolValidationError):
        dto.ManagementRequest.from_mapping(
            {**request_mapping(), "timeout_ms": timeout}
        )


@pytest.mark.parametrize("timeout", [1, 30000, 65000])
def test_request_timeout_inclusive_boundaries(dto, timeout):
    value = {**request_mapping(), "timeout_ms": timeout}
    assert dto.ManagementRequest.from_mapping(value).to_mapping() == value


@pytest.mark.parametrize(
    "operation,parameters",
    [
        ("qrcode.fetch", {}),
        ("qrcode.fetch", {"config": [], "continuation": "x"}),
        ("qrcode.fetch", {"config": {}, "level": "reachability"}),
        ("qrcode.poll", {"config": {}}),
        ("qrcode.poll", {"config": {}, "continuation": object()}),
        ("qrcode.poll", {"config": {}, "continuation": "x", "unknown": True}),
        ("connection.verify", {"config": {}, "level": "connected"}),
        (
            "connection.verify",
            {"config": {}, "level": "reachability", "module": "os"},
        ),
        ("connection.verify", {"config": {}, "level": True}),
    ],
)
def test_request_parameters_follow_operation_closed_shape(
    dto, operation, parameters
):
    from qwenpaw.channel_protocol.errors import ProtocolValidationError

    with pytest.raises(ProtocolValidationError):
        dto.ManagementRequest.from_mapping(
            {
                **request_mapping(operation),
                "parameters": parameters,
            }
        )


@pytest.mark.parametrize(
    "config",
    [
        {"value": object()},
        {"value": float("nan")},
        {"value": float("inf")},
        {"nested": {"value": float("-inf")}},
        {1: "integer-key"},
        {"nested": [object()]},
    ],
)
def test_request_projection_accepts_only_finite_json_data(dto, config):
    from qwenpaw.channel_protocol.errors import ProtocolValidationError

    with pytest.raises(ProtocolValidationError):
        dto.ManagementRequest.from_mapping(
            {
                **request_mapping(),
                "parameters": {"config": config},
            }
        )


@pytest.mark.parametrize(
    "operation,payload",
    [
        ("qrcode.fetch", None),
        ("qrcode.fetch", {"scan_url": "x"}),
        (
            "qrcode.fetch",
            {"scan_url": "x", "continuation": "x", "credentials": {}},
        ),
        ("qrcode.poll", {"status": "waiting", "credentials": None}),
        ("qrcode.poll", {"status": object(), "credentials": {}}),
        (
            "qrcode.poll",
            {"status": "confirmed", "credentials": {"bot_token": 123}},
        ),
        ("qrcode.poll", {"status": "confirmed", "credentials": {1: "x"}}),
        (
            "connection.verify",
            {
                "level": "connected",
                "verdict": "passed",
                "reason_code": None,
                "notes": [],
            },
        ),
        (
            "connection.verify",
            {
                "level": "reachability",
                "verdict": "connected",
                "reason_code": None,
                "notes": [],
            },
        ),
        (
            "connection.verify",
            {
                "level": "reachability",
                "verdict": "passed",
                "reason_code": None,
                "notes": [object()],
            },
        ),
    ],
)
def test_success_result_requires_operation_payload(dto, operation, payload):
    from qwenpaw.channel_protocol.errors import ProtocolValidationError

    with pytest.raises(ProtocolValidationError):
        dto.ManagementResult.from_mapping(
            {**result_mapping(operation), "result": payload}
        )


@pytest.mark.parametrize(
    "status", ["confirmed", "waiting", "scanned", "success", "fail"]
)
def test_poll_preserves_existing_platform_status(dto, status):
    value = result_mapping("qrcode.poll")
    value["result"]["status"] = status
    assert dto.ManagementResult.from_mapping(value).to_mapping() == value


@pytest.mark.parametrize("outcome", ["failed", "unsupported"])
def test_execution_error_cannot_carry_partial_credentials_or_missing_reason(
    dto, outcome
):
    from qwenpaw.channel_protocol.errors import ProtocolValidationError

    value = result_mapping("qrcode.poll")
    value["outcome"] = outcome
    with pytest.raises(ProtocolValidationError):
        dto.ManagementResult.from_mapping(value)
    value["result"] = None
    with pytest.raises(ProtocolValidationError):
        dto.ManagementResult.from_mapping(value)


@pytest.mark.parametrize(
    "operation,path,value",
    [
        ("qrcode.fetch", ("result", "scan_url"), "x" * (16 * 1024 + 1)),
        ("qrcode.fetch", ("result", "continuation"), "x" * (16 * 1024 + 1)),
        ("qrcode.fetch", ("result", "scan_url"), "界" * (16 * 1024 // 3 + 1)),
        (
            "qrcode.poll",
            ("result", "credentials", "bot_token"),
            "x" * (8 * 1024 + 1),
        ),
        ("connection.verify", ("result", "notes"), ["x"] * 17),
        ("connection.verify", ("result", "notes"), ["x" * 513]),
    ],
    ids=[
        "url-size",
        "continuation-size",
        "url-utf8-size",
        "credential-size",
        "notes-count",
        "note-size",
    ],
)
def test_result_bounds_fail_without_truncating_secret(
    dto, operation, path, value
):
    from qwenpaw.channel_protocol.errors import ProtocolValidationError

    data = replace_path(result_mapping(operation), path, value)
    original = deepcopy(data)
    with pytest.raises(ProtocolValidationError):
        dto.ManagementResult.from_mapping(data)
    assert data == original


def test_request_entire_package_is_bounded_independently_of_rpc_frame(dto):
    from qwenpaw.channel_protocol.errors import ProtocolValidationError

    value = request_mapping()
    value["parameters"]["config"] = {"value": "x" * (64 * 1024)}
    with pytest.raises(ProtocolValidationError):
        dto.ManagementRequest.from_mapping(value)


def test_result_entire_package_is_bounded_independently_of_individual_values(
    dto,
):
    from qwenpaw.channel_protocol.errors import ProtocolValidationError

    value = result_mapping("qrcode.poll")
    value["result"]["credentials"] = {
        "field_" + str(index): "x" * (8 * 1024) for index in range(9)
    }
    with pytest.raises(ProtocolValidationError):
        dto.ManagementResult.from_mapping(value)


@pytest.mark.parametrize(
    "extra",
    [
        {"function": "manage"},
        {"module": "os"},
        {"management_entrypoint": {"module": "os", "qualname": "system"}},
    ],
)
def test_descriptor_rejects_second_or_user_selected_management_entrypoint(
    extra,
):
    from qwenpaw.channel_protocol.errors import DescriptorValidationError
    from qwenpaw.channel_protocol.shared import SharedChannelDescriptor

    value = json.loads(
        Path(__file__)
        .with_name("sample_chat")
        .joinpath("channel.json")
        .read_text()
    )
    with pytest.raises(DescriptorValidationError):
        SharedChannelDescriptor.from_mapping({**value, **extra})


def test_descriptor_management_capabilities_preserve_one_fixed_driver_entrypoint():
    from qwenpaw.channel_protocol.shared import SharedChannelDescriptor

    value = json.loads(
        Path(__file__)
        .with_name("sample_chat")
        .joinpath("channel.json")
        .read_text()
    )
    value["capabilities"] = sorted(
        value["capabilities"]
        + ["channel.management.qrcode.v1", "channel.management.verify.v1"]
    )
    assert SharedChannelDescriptor.from_mapping(value).to_mapping() == value


@pytest.mark.parametrize(
    "field,value",
    [
        ("request_id", "34b8cfeb-a5e7-47ac-b858-6f736c6e6b3e"),
        ("plugin_id", "qq"),
        ("workspace_id", "workspace-B"),
        ("channel_key", "qq"),
        ("instance_id", "another-instance"),
        ("generation", 2),
        ("source_revision", "b" * 64),
    ],
)
def test_result_validate_for_rejects_valid_but_forged_identity(
    dto, field, value
):
    from qwenpaw.channel_protocol.errors import ProtocolValidationError

    request = dto.ManagementRequest.from_mapping(request_mapping())
    result = dto.ManagementResult.from_mapping(
        {**result_mapping(), field: value}
    )
    with pytest.raises(ProtocolValidationError):
        result.validate_for(request, credential_keys={"bot_token", "base_url"})


def test_result_validate_for_rejects_different_operation(dto):
    from qwenpaw.channel_protocol.errors import ProtocolValidationError

    request = dto.ManagementRequest.from_mapping(request_mapping())
    result = dto.ManagementResult.from_mapping(result_mapping("qrcode.poll"))
    with pytest.raises(ProtocolValidationError):
        result.validate_for(request, credential_keys={"bot_token", "base_url"})


def test_result_validate_for_rejects_unknown_credential_keys(dto):
    from qwenpaw.channel_protocol.errors import ProtocolValidationError

    request = dto.ManagementRequest.from_mapping(
        request_mapping("qrcode.poll")
    )
    value = result_mapping("qrcode.poll")
    value["result"]["credentials"]["untrusted_credential"] = "fixture-secret"
    result = dto.ManagementResult.from_mapping(value)
    with pytest.raises(ProtocolValidationError):
        result.validate_for(request, credential_keys={"bot_token", "base_url"})


def test_result_validate_for_uses_explicit_host_credential_authority(dto):
    request = dto.ManagementRequest.from_mapping(
        request_mapping("qrcode.poll")
    )
    result = dto.ManagementResult.from_mapping(result_mapping("qrcode.poll"))
    assert (
        result.validate_for(request, credential_keys={"bot_token", "base_url"})
        is None
    )


def test_result_validate_for_cannot_upgrade_reachability_to_credentials(dto):
    from qwenpaw.channel_protocol.errors import ProtocolValidationError

    request = dto.ManagementRequest.from_mapping(
        request_mapping("connection.verify")
    )
    value = result_mapping("connection.verify")
    value["result"]["level"] = "credentials"
    result = dto.ManagementResult.from_mapping(value)
    with pytest.raises(ProtocolValidationError):
        result.validate_for(request, credential_keys=())


@pytest.mark.parametrize("outcome", ["failed", "unsupported"])
def test_execution_failure_round_trip_uses_safe_reason_and_no_payload(
    dto, outcome
):
    value = result_mapping()
    value.update(outcome=outcome, reason_code="PLATFORM_REJECTED", result=None)
    assert dto.ManagementResult.from_mapping(value).to_mapping() == value


@pytest.mark.parametrize(
    "verdict,reason",
    [
        ("failed", "PLATFORM_REJECTED"),
        ("unsupported", "VERIFICATION_UNSUPPORTED"),
    ],
)
def test_normal_verification_failure_or_unsupported_is_operation_success(
    dto, verdict, reason
):
    value = result_mapping("connection.verify")
    value["result"].update(verdict=verdict, reason_code=reason)
    assert dto.ManagementResult.from_mapping(value).to_mapping() == value


@pytest.mark.parametrize(
    "verdict,reason",
    [
        ("passed", "PLATFORM_REJECTED"),
        ("failed", None),
        ("unsupported", None),
        ("failed", "SDK leaked fixture-secret"),
    ],
)
def test_verification_reason_is_safe_and_consistent(dto, verdict, reason):
    from qwenpaw.channel_protocol.errors import ProtocolValidationError

    value = result_mapping("connection.verify")
    value["result"].update(verdict=verdict, reason_code=reason)
    with pytest.raises(ProtocolValidationError):
        dto.ManagementResult.from_mapping(value)


@pytest.mark.parametrize("status", ["", "x" * 513])
def test_poll_status_has_frozen_nonempty_512_character_bound(dto, status):
    from qwenpaw.channel_protocol.errors import ProtocolValidationError

    value = result_mapping("qrcode.poll")
    value["result"]["status"] = status
    with pytest.raises(ProtocolValidationError):
        dto.ManagementResult.from_mapping(value)


@pytest.mark.parametrize("field", ["scan_url", "continuation"])
def test_fetch_result_tokens_must_be_nonempty(dto, field):
    from qwenpaw.channel_protocol.errors import ProtocolValidationError

    value = result_mapping()
    value["result"][field] = ""
    with pytest.raises(ProtocolValidationError):
        dto.ManagementResult.from_mapping(value)


def test_request_poll_continuation_has_utf8_byte_bound(dto):
    from qwenpaw.channel_protocol.errors import ProtocolValidationError

    value = request_mapping("qrcode.poll")
    value["parameters"]["continuation"] = "界" * (16384 // 3 + 1)
    with pytest.raises(ProtocolValidationError):
        dto.ManagementRequest.from_mapping(value)


@pytest.mark.parametrize(
    "kind,field",
    [
        ("request", "timeout_ms"),
        ("request", "parameters"),
        ("result", "outcome"),
        ("result", "reason_code"),
        ("result", "result"),
    ],
)
def test_nullable_and_payload_fields_are_still_required(dto, kind, field):
    from qwenpaw.channel_protocol.errors import ProtocolValidationError

    value = request_mapping() if kind == "request" else result_mapping()
    value.pop(field)
    cls = dto.ManagementRequest if kind == "request" else dto.ManagementResult
    with pytest.raises(ProtocolValidationError):
        cls.from_mapping(value)
