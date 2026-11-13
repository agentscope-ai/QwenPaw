# -*- coding: utf-8 -*-
"""Plugin-local mirror of the core Chrome wire protocol; never import core."""

PROTOCOL_VERSION = 2
MIN_COMPATIBLE_PROTOCOL_VERSION = 2
# Chrome Native Messaging hard limits. Protocol facts, not tunables.
NM_MAX_INBOUND_BYTES = 64 * 1024 * 1024
NM_MAX_OUTBOUND_BYTES = 1024 * 1024
# Application-reserved WebSocket close codes for the Native Messaging bridge.
NM_CLOSE_STDIN_EOF = 4000
NM_CLOSE_FRAME_PROTOCOL = 4001
NM_CLOSE_INBOUND_TOO_LARGE = 4002
NM_CLOSE_INTERNAL_ERROR = 4003
EXTENSION_COMMANDS = frozenset(
    {
        "cdp.send",
        "command.execute",
        "command.status",
        "tabs.list",
        "tab.attach",
        "tab.detach",
        "tab.ensure",
        "tab.activate",
        "tab.close",
        "tab.create",
        "tab.metadata.commit",
        "banner.show",
        "banner.hide",
        "file.upload",
        "download.read",
        "dialog.set",
        "extension.open_extensions_manager",
        "status.get",
        "bridge.connect",
        "extension.reload",
    },
)
EVENT_TYPES = frozenset({"load", "dialog"})


def contract_snapshot() -> dict[str, object]:
    """Values this plugin build claims to implement, for core comparison."""
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "minCompatibleProtocolVersion": MIN_COMPATIBLE_PROTOCOL_VERSION,
        "nmMaxInboundBytes": NM_MAX_INBOUND_BYTES,
        "nmMaxOutboundBytes": NM_MAX_OUTBOUND_BYTES,
    }


def close_code_catalog() -> dict[int, str]:
    """Close-code meanings shared with the core browser bridge."""
    return {
        NM_CLOSE_STDIN_EOF: "stdin_eof",
        NM_CLOSE_FRAME_PROTOCOL: "frame_protocol_error",
        NM_CLOSE_INBOUND_TOO_LARGE: "inbound_frame_too_large",
        NM_CLOSE_INTERNAL_ERROR: "host_internal_error",
    }
