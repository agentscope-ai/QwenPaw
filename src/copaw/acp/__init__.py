# -*- coding: utf-8 -*-
"""ACP (Agent Client Protocol) integration for CoPaw."""
from .config import ACPConfig, ACPHarnessConfig
from .errors import (
    ACPConfigurationError,
    ACPError,
    ACPPermissionError,
    ACPProtocolError,
    ACPTransportError,
)
from .projector import ACPEventProjector
from .runtime import ACPRuntime
from .service import ACPService
from .session_store import ACPSessionStore
from .transport import ACPTransport
from .types import (
    ACPConversationSession,
    ACPRunResult,
    AcpEvent,
    ExternalAgentConfig,
    merge_external_agent_configs,
    normalize_harness_name,
    parse_external_agent_config,
    parse_external_agent_text,
)

__all__ = [
    # Config
    "ACPConfig",
    "ACPHarnessConfig",
    "ACPError",
    "ACPTransportError",
    "ACPProtocolError",
    "ACPConfigurationError",
    "ACPPermissionError",
    "ACPTransport",
    "ACPRuntime",
    "ACPSessionStore",
    "ACPEventProjector",
    "ACPService",
    "AcpEvent",
    "ACPConversationSession",
    "ACPRunResult",
    "ExternalAgentConfig",
    "merge_external_agent_configs",
    "normalize_harness_name",
    "parse_external_agent_config",
    "parse_external_agent_text",
]
