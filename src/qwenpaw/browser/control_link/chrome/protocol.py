# -*- coding: utf-8 -*-
"""Frozen wire-protocol source-of-truth for the core Chrome backend."""

from __future__ import annotations

from enum import StrEnum

PROTOCOL_VERSION = 2

# Chrome Native Messaging hard limits. These are protocol facts, not tunables:
# a message from the extension to the host may be up to 64 MiB, while a message
# from the host to the extension may not exceed 1 MiB - Chrome kills the host
# process when it does. Mirrored by the plugin-side nm_host snapshot.
NM_MAX_INBOUND_BYTES = 64 * 1024 * 1024
NM_MAX_OUTBOUND_BYTES = 1024 * 1024

# Native Messaging host install contract. Producer: the plugin installer
# (plugins/bundle/chrome/extension_setup.py, native_host_launcher_path).
# Consumer: the core probe (control_link/chrome/observe.py). Windows ships a
# batch launcher because the host is a Python script.
NM_HOST_BASENAME = "qwenpaw-nm-host"
NM_HOST_WIN_SUFFIX = ".bat"


class ReceiptState(StrEnum):
    """Closed receipt states persisted by the extension executor.

    RECEIVED  - accepted, the execution barrier has NOT been crossed yet.
    RUNNING   - the barrier has been crossed; side effects may exist. This
                state must be durably stored before the executor is invoked;
                it is the only evidence that can later distinguish "never
                started" from "outcome unknown". Never collapse it into
                RECEIVED.
    COMPLETED - finished, the result is carried by the receipt.
    """

    RECEIVED = "RECEIVED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"


# Facts the extension may broadcast about one target command. Only the
# conclusive subset may drive a decision; the rest differ for diagnostics only
# and must all be treated as uncertain by the host.
COMMAND_OBSERVED_STATES = frozenset(
    {
        "COMPLETED",
        "NOT_STARTED",
        "IN_FLIGHT",
        "ABANDONED",
        "LOST",
        "UNKNOWN",
    },
)
CONCLUSIVE_OBSERVED_STATES = frozenset({"COMPLETED", "NOT_STARTED"})

# Receipt contract: after a NOT_STARTED verdict, retry identity MUST reuse the
# same commandId and commandFingerprint; a new id bypasses deduplication.
# A command.execute receipt is not conclusive: only command.status
# observedState
# decides conclusiveness after its epoch is stripped. Public receipt fields are
# sessionId, commandId, commandFingerprint, state, result, createdAt and
# updatedAt. executorEpoch, TTLs and capacity limits are extension-internal.

# Oldest extension protocol version this core can still work with. Raise only
# on a breaking protocol change; additive changes bump PROTOCOL_VERSION alone.
MIN_COMPATIBLE_PROTOCOL_VERSION = 2


def contract_snapshot() -> dict[str, object]:
    """Return values a plugin build must mirror for health comparison."""
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "minCompatibleProtocolVersion": MIN_COMPATIBLE_PROTOCOL_VERSION,
        "nmMaxInboundBytes": NM_MAX_INBOUND_BYTES,
        "nmMaxOutboundBytes": NM_MAX_OUTBOUND_BYTES,
    }


# Earliest plugin build known to carry the frame-limit and disconnect fixes.
# Diagnostic only: an older build warns, never hard-fails a connection.
MIN_HEALTHY_PLUGIN_BUILD = "2026-07-27T23:24:00Z"

# WebSocket close codes the native messaging host uses to report why it went
# away. 4000-4999 is the range the WebSocket spec reserves for applications.
NM_CLOSE_STDIN_EOF = 4000
NM_CLOSE_FRAME_PROTOCOL = 4001
NM_CLOSE_INBOUND_TOO_LARGE = 4002
NM_CLOSE_INTERNAL_ERROR = 4003


def close_code_catalog() -> dict[int, str]:
    """Return close codes the plugin may report and their short meanings."""
    return {
        NM_CLOSE_STDIN_EOF: "stdin_eof",
        NM_CLOSE_FRAME_PROTOCOL: "frame_protocol_error",
        NM_CLOSE_INBOUND_TOO_LARGE: "inbound_frame_too_large",
        NM_CLOSE_INTERNAL_ERROR: "host_internal_error",
    }


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

EVENT_SCHEMA = {"load": ("url",), "dialog": ("kind", "message")}
EVENT_TYPES = frozenset(EVENT_SCHEMA)
