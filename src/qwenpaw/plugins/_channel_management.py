# -*- coding: utf-8 -*-
"""Translate the public management result into the fixed, fenced host contract."""

import asyncio

from ..channel_protocol.errors import ProtocolValidationError
from ..channel_protocol.management import management_result
from ._events import freeze
from ._models import json_mapping
from .channel_management import (
    ChannelManagementRequest,
    ChannelManagementFailure,
    ChannelQRCode,
    ChannelAuthorization,
    ChannelVerification,
)
from .errors import ResourceError
from .resources import ResourceOwner, ResourceScope


async def manage(driver_class, native, *, workspace_id):
    scope = ResourceScope(
        ResourceOwner(
            native.plugin_id,
            native.generation,
            workspace_id,
            native.request_id,
        ),
        lambda: None,
    )
    values = native.parameters
    request = ChannelManagementRequest(
        native.request_id,
        native.plugin_id,
        workspace_id,
        native.channel_key,
        native.operation,
        freeze(json_mapping(values["config"])),
        scope,
        asyncio.get_running_loop().time() + native.timeout_ms / 1000,
        freeze(values.get("options", {})),
        values.get("continuation"),
        values.get("level"),
    )
    try:
        value = await driver_class.manage(request)
        if isinstance(value, ChannelManagementFailure):
            return management_result(
                native,
                reason=value.reason_code,
                unsupported=value.unsupported,
            )
        if (
            isinstance(value, ChannelQRCode)
            and native.operation == "qrcode.fetch"
        ):
            result = {
                "scan_url": value.scan_url,
                "continuation": value.continuation,
            }
            if value.expires_in_seconds is not None:
                result["expires_in_seconds"] = value.expires_in_seconds
        elif (
            isinstance(value, ChannelAuthorization)
            and native.operation == "qrcode.poll"
        ):
            result = {
                "status": value.status,
                "credentials": dict(value.credentials),
                "metadata": dict(value.metadata),
            }
        elif (
            isinstance(value, ChannelVerification)
            and native.operation == "connection.verify"
        ):
            result = {
                "level": value.level,
                "verdict": value.verdict,
                "reason_code": value.reason_code,
                "notes": list(value.notes),
            }
        else:
            raise ProtocolValidationError(
                "Management result does not match the requested operation",
                reason_code="MANAGEMENT_INVALID_RESULT",
            )
        return management_result(native, result)
    finally:
        try:
            await scope.close()
        except ResourceError as exc:
            raise ProtocolValidationError(
                "Management resources are still active",
                reason_code="MANAGEMENT_CLEANUP_FAILED",
            ) from exc
