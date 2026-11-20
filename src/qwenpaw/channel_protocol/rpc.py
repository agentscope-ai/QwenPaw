# -*- coding: utf-8 -*-
"""Channel schemas over the shared JSON-RPC dispatcher."""

# pylint: disable=unused-import
from ..plugins.execution.rpc import (
    JSONRPC_PARSE_ERROR,
    JSONRPC_INVALID_REQUEST,
    JSONRPC_METHOD_NOT_FOUND,
    JSONRPC_INVALID_PARAMS,
    JSONRPC_INTERNAL_ERROR,
    RPC_REQUEST_ID_IN_USE,
    RPC_BACKPRESSURE,
    RpcCallNotSent,
    RpcLimits,
    RpcResponsePublication,
    request_was_cancelled,
    RequestHandler,
    NotificationHandler,
)
from ..plugins.execution.rpc import RpcPeer as _RpcPeer
from .models import validate_method_params


class RpcPeer(_RpcPeer):
    """Preserve Channel DTO validation on the common dispatcher."""

    def __init__(self, transport, *, limits=None, params_validator=None):
        validator = params_validator or validate_method_params
        super().__init__(transport, limits=limits, params_validator=validator)
