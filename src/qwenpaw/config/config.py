# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional, Union, Dict, List, Literal, Any, Set

from pydantic import (
    BaseModel,
    Field,
    ConfigDict,
    field_validator,
    model_validator,
)
import shortuuid
from agentscope_runtime.engine.schemas.exception import (
    ConfigurationException,
)

from .timezone import detect_system_timezone
from ..constant import (
    HEARTBEAT_DEFAULT_EVERY,
    HEARTBEAT_DEFAULT_TARGET,
    LLM_ACQUIRE_TIMEOUT,
    LLM_BACKOFF_BASE,
    LLM_BACKOFF_CAP,
    LLM_MAX_CONCURRENT,
    LLM_MAX_RETRIES,
    LLM_MAX_QPM,
    LLM_RATE_LIMIT_JITTER,
    LLM_RATE_LIMIT_PAUSE,
    WORKING_DIR,
)


# ============================================================================
# Core config models (moved here to avoid circular imports)
# ============================================================================


class ModelSlotConfig(BaseModel):
    """Model slot configuration for LLM routing."""

    provider_id: str = Field(default="")
    model: str = Field(default="")


class ActiveModelsInfo(BaseModel):
    """Active models information for provider manager."""

    active_llm: ModelSlotConfig | None


class ACPAgentConfig(BaseModel):
    """Configuration for one ACP agent."""

    enabled: bool = False
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    trusted: bool = True
    tool_parse_mode: str = "call_title"
    stdio_buffer_limit_bytes: int = Field(
        default=50 * 1024 * 1024,
        gt=0,
    )


def _get_default_acp_agents() -> Dict[str, ACPAgentConfig]:
    """Get default ACP agents configuration."""
    return {
        "opencode": ACPAgentConfig(
            enabled=True,
            command="opencode",
            args=["acp"],
            trusted=True,
            tool_parse_mode="update_detail",
        ),
        "qwen_code": ACPAgentConfig(
            enabled=True,
            command="qwen",
            args=["--acp"],
            trusted=True,
            tool_parse_mode="call_detail",
        ),
        "claude_code": ACPAgentConfig(
            enabled=True,
            command="npx",
            args=["-y", "@zed-industries/claude-agent-acp"],
            trusted=True,
            tool_parse_mode="update_detail",
        ),
        "codex": ACPAgentConfig(
            enabled=True,
            command="npx",
            args=["-y", "@zed-industries/codex-acp"],
            trusted=True,
            tool_parse_mode="call_detail",
        ),
    }


class ACPConfig(BaseModel):
    """ACP (Agent Communication Protocol) configuration."""

    agents: Dict[str, ACPAgentConfig] = Field(
        default_factory=_get_default_acp_agents,
    )

    @model_validator(mode="after")
    def _merge_default_agents(self):
        """Merge default agents with user-configured agents."""
        for name, agent_cfg in _get_default_acp_agents().items():
            if name not in self.agents:
                self.agents[name] = agent_cfg
        return self


# Agent ID validation: alphanumeric, hyphens, underscores.
_AGENT_ID_PATTERN = re.compile(
    r"^[a-zA-Z0-9][a-zA-Z0-9_-]*[a-zA-Z0-9]$",
)
_AGENT_ID_MIN_LENGTH = 2
_AGENT_ID_MAX_LENGTH = 64
_RESERVED_AGENT_IDS = frozenset({"default"})


def generate_short_agent_id() -> str:
    """Generate a 6-character short UUID for agent identification.

    Returns:
        6-character short UUID string
    """
    return shortuuid.ShortUUID().random(length=6)


def sanitize_agent_id(raw: str) -> str:
    """Normalize raw agent ID input: strip whitespace.

    Args:
        raw: Raw user input for agent ID.

    Returns:
        Sanitized agent ID string.
    """
    return raw.strip()


def validate_agent_id(
    agent_id: str,
    existing_ids: Set[str],
) -> None:
    """Validate a custom agent ID.

    Checks length, character set, reserved words, and uniqueness.

    Args:
        agent_id: The sanitized agent ID to validate.
        existing_ids: Set of already-registered agent IDs.

    Raises:
        ValueError: If the ID is invalid.
    """
    if len(agent_id) < _AGENT_ID_MIN_LENGTH:
        raise ValueError(
            f"Agent ID must be at least {_AGENT_ID_MIN_LENGTH} characters, "
            f"got {len(agent_id)}.",
        )
    if len(agent_id) > _AGENT_ID_MAX_LENGTH:
        raise ValueError(
            f"Agent ID must be at most {_AGENT_ID_MAX_LENGTH} characters, "
            f"got {len(agent_id)}.",
        )
    if not _AGENT_ID_PATTERN.match(agent_id):
        raise ValueError(
            f"Agent ID '{agent_id}' contains invalid characters. "
            "Only letters, digits, hyphens, and underscores "
            "are allowed. Cannot start or end with '-' or '_'.",
        )
    if agent_id in _RESERVED_AGENT_IDS:
        raise ValueError(
            f"Agent ID '{agent_id}' is reserved and cannot be used.",
        )
    if agent_id in existing_ids:
        raise ValueError(
            f"Agent ID '{agent_id}' already exists.",
        )


class BaseChannelConfig(BaseModel):
    """Base for channel config (read from config.json, no env)."""

    enabled: bool = False
    bot_prefix: str = ""
    filter_tool_messages: bool = False
    filter_thinking: bool = False
    dm_policy: Literal["open", "allowlist"] = "open"
    group_policy: Literal["open", "allowlist"] = "open"
    allow_from: List[str] = Field(default_factory=list)
    deny_message: str = ""
    require_mention: bool = False


class IMessageChannelConfig(BaseChannelConfig):
    db_path: str = "~/Library/Messages/chat.db"
    poll_sec: float = 1.0
    media_dir: Optional[str] = None
    max_decoded_size: int = (
        10 * 1024 * 1024
    )  # 10MB default limit for Base64 data


class DiscordConfig(BaseChannelConfig):
    bot_token: str = ""
    http_proxy: str = ""
    http_proxy_auth: str = ""
    accept_bot_messages: bool = False


class DingTalkConfig(BaseChannelConfig):
    client_id: str = ""
    client_secret: str = ""
    message_type: str = "markdown"
    card_template_id: str = ""
    card_template_key: str = "content"
    robot_code: str = ""
    media_dir: Optional[str] = None
    card_auto_layout: bool = False
    at_sender_on_reply: bool = False


class FeishuConfig(BaseChannelConfig):
    """Feishu/Lark channel: app_id, app_secret; optional encrypt_key,
    verification_token for event handler. media_dir for received media.
    domain: 'feishu' for China, 'lark' for international.
    """

    app_id: str = ""
    app_secret: str = ""
    encrypt_key: str = ""
    verification_token: str = ""
    media_dir: Optional[str] = None
    domain: Literal["feishu", "lark"] = "feishu"


class QQConfig(BaseChannelConfig):
    app_id: str = ""
    client_secret: str = ""
    markdown_enabled: bool = True
    max_reconnect_attempts: int = 100
    ack_message: str = ""


class OneBotConfig(BaseChannelConfig):
    """OneBot v11 channel: reverse WebSocket for NapCat/go-cqhttp/Lagrange."""

    ws_host: str = "0.0.0.0"
    ws_port: int = 6199
    access_token: str = ""
    share_session_in_group: bool = False


class TelegramConfig(BaseChannelConfig):
    bot_token: str = ""
    http_proxy: str = ""
    http_proxy_auth: str = ""
    show_typing: Optional[bool] = None


class MQTTConfig(BaseChannelConfig):
    host: str = ""
    port: Optional[int] = None
    transport: str = ""
    clean_session: bool = True
    qos: int = 2
    username: Optional[str] = None
    password: Optional[str] = None
    subscribe_topic: str = ""
    publish_topic: str = ""
    tls_enabled: bool = False
    tls_ca_certs: Optional[str] = None
    tls_certfile: Optional[str] = None
    tls_keyfile: Optional[str] = None


class MattermostConfig(BaseChannelConfig):
    """Mattermost channel: WebSocket polling and REST API."""

    url: str = ""
    bot_token: str = ""
    media_dir: Optional[str] = None
    show_typing: Optional[bool] = None
    thread_follow_without_mention: bool = False


class ConsoleConfig(BaseChannelConfig):
    """Console channel: prints agent responses to stdout."""

    enabled: bool = True
    media_dir: Optional[str] = None


class WecomConfig(BaseChannelConfig):
    """WeCom (Enterprise WeChat) AI Bot channel config."""

    bot_id: str = ""
    secret: str = ""
    media_dir: Optional[str] = None
    welcome_text: str = ""
    max_reconnect_attempts: int = -1


class MatrixConfig(BaseChannelConfig):
    """Matrix channel configuration."""

    homeserver: str = ""

    @field_validator("homeserver")
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    user_id: str = ""
    access_token: str = ""

    # Extended Matrix channel fields
    group_allow_from: List[str] = Field(default_factory=list)
    groups: Dict[str, Any] = Field(default_factory=dict)
    encryption: bool = False
    # When False, images are surfaced as text placeholders (no vision URL).
    vision_enabled: bool = True
    history_limit: int = 50
    username: str = ""
    password: str = ""
    device_name: str = "qwenpaw-worker"
    # matrix-nio sync long-poll timeout (ms); typical 30s
    sync_timeout_ms: int = Field(default=30000, ge=5000, le=300000)
    # When True, prepend HTML pill to formatted_body for outbound mentions.
    # Default False: m.mentions is always set for push, but pill is omitted.
    mention_pill_in_body: bool = False
    # When True, apply m.mentions + optional pill on outbound messages.
    outbound_structured_mentions: bool = True


class VoiceChannelConfig(BaseChannelConfig):
    """Voice channel: Twilio ConversationRelay + Cloudflare Tunnel."""

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    phone_number: str = ""
    phone_number_sid: str = ""
    tts_provider: str = "google"
    tts_voice: str = "en-US-Journey-D"
    stt_provider: str = "deepgram"
    language: str = "en-US"
    welcome_greeting: str = "Hi! This is QwenPaw. How can I help you?"


class SIPChannelConfig(BaseChannelConfig):
    """SIP voice channel: dual-track (pyVoIP dev / LiveKit production)."""

    sip_mode: str = "dev"
    sip_host: str = "0.0.0.0"
    sip_port: int = 5061
    sip_username: str = ""
    sip_password: str = ""
    sip_server: str = ""
    sip_transport: str = "UDP"
    rtp_port_low: int = 10000
    rtp_port_high: int = 20000
    dashscope_api_key: str = ""
    tts_provider: str = "aliyun"
    tts_voice: str = ""
    stt_provider: str = "aliyun"
    language: str = "zh-CN"
    welcome_greeting: str = "你好，我是QwenPaw"
    call_timeout: float = 120.0
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    livekit_sip_trunk_id: str = ""
    livekit_room_name: str = "sip-inbound"
    livekit_output_sample_rate: int = 24000
    max_concurrent_calls: int = 5


class XiaoYiConfig(BaseChannelConfig):
    """XiaoYi channel: Huawei A2A protocol via WebSocket."""

    ak: str = ""  # Access Key
    sk: str = ""  # Secret Key
    agent_id: str = ""  # Agent ID from XiaoYi platform
    ws_url: str = "wss://hag.cloud.huawei.com/openclaw/v1/ws/link"
    task_timeout_ms: int = 3600000  # 1 hour task timeout


class WeixinConfig(BaseChannelConfig):
    """WeChat (iLink Bot) personal account channel config.

    bot_token:      Bearer token obtained after QR code login.
    bot_token_file: Path to persist/load the bot_token
                    (default ~/.qwenpaw/weixin_bot_token).
    base_url:       iLink API base URL (leave empty to use default).
    media_dir:      Local directory for downloaded media files.
    """

    bot_token: str = ""
    bot_token_file: str = ""
    base_url: str = ""
    media_dir: Optional[str] = None


class ChannelConfig(BaseModel):
    """Built-in channel configs; extra keys allowed for plugin channels."""

    model_config = ConfigDict(extra="allow")

    imessage: IMessageChannelConfig = IMessageChannelConfig()
    discord: DiscordConfig = DiscordConfig()
    dingtalk: DingTalkConfig = DingTalkConfig()
    feishu: FeishuConfig = FeishuConfig()
    qq: QQConfig = QQConfig()
    telegram: TelegramConfig = TelegramConfig()
    mattermost: MattermostConfig = MattermostConfig()
    mqtt: MQTTConfig = MQTTConfig()
    console: ConsoleConfig = ConsoleConfig()
    matrix: MatrixConfig = MatrixConfig()
    voice: VoiceChannelConfig = VoiceChannelConfig()
    sip: SIPChannelConfig = SIPChannelConfig()
    wecom: WecomConfig = WecomConfig()
    xiaoyi: XiaoYiConfig = XiaoYiConfig()
    weixin: WeixinConfig = WeixinConfig()
    onebot: OneBotConfig = OneBotConfig()


class LastApiConfig(BaseModel):
    host: Optional[str] = None
    port: Optional[int] = None


class ActiveHoursConfig(BaseModel):
    """Optional active window for heartbeat (e.g. 08:00–22:00)."""

    start: str = "08:00"
    end: str = "22:00"


class HeartbeatConfig(BaseModel):
    """Heartbeat: run agent with HEARTBEAT.md as query at interval."""

    model_config = {"populate_by_name": True}

    enabled: bool = Field(default=False, description="Whether heartbeat is on")
    every: str = Field(default=HEARTBEAT_DEFAULT_EVERY)
    target: str = Field(default=HEARTBEAT_DEFAULT_TARGET)
    active_hours: Optional[ActiveHoursConfig] = Field(
        default=None,
        alias="activeHours",
    )


class AgentsDefaultsConfig(BaseModel):
    heartbeat: Optional[HeartbeatConfig] = None


class AutoMemorySearchConfig(BaseModel):
    """Auto memory search configuration."""

    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(
        default=False,
        description="Whether to auto search memory on every turn",
    )

    max_results: int = Field(
        default=2,
        ge=1,
        description=(
            "Maximum number of results to return when auto memory"
            " search is enabled"
        ),
    )

    min_score: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum relevance score for results when auto memory"
            " search is enabled"
        ),
    )


class EmbeddingModelConfig(BaseModel):
    """Embedding model configuration."""

    model_config = ConfigDict(extra="ignore")

    backend: str = Field(
        default="openai",
        description="Embedding backend (openai, etc.)",
    )
    api_key: str = Field(
        default="",
        description="API key for embedding provider",
    )
    base_url: str = Field(default="", description="Base URL for embedding API")
    model_name: str = Field(default="", description="Embedding model name")
    dimensions: int = Field(default=1024, description="Embedding dimensions")
    enable_cache: bool = Field(
        default=True,
        description="Whether to enable embedding cache",
    )
    use_dimensions: bool = Field(
        default=False,
        description="Whether to use custom dimensions",
    )
    max_cache_size: int = Field(default=3000, description="Maximum cache size")
    max_input_length: int = Field(
        default=8192,
        description="Maximum input length for embedding",
    )
    max_batch_size: int = Field(
        default=10,
        description="Maximum batch size for embedding",
    )


class ReMeLightMemoryConfig(BaseModel):
    """ReMeLight memory manager configuration."""

    model_config = ConfigDict(extra="ignore")

    summarize_when_compact: bool = Field(
        default=True,
        description="Whether to enable memory summarization during compaction",
    )

    auto_memory_interval: int | None = Field(
        default=None,
        description="Auto memory every N user queries. None disables "
        "periodic auto memory, 1 means auto memory after every user "
        "query, 2 means every 2 queries, etc. WARNING: Setting too "
        "small (e.g., 1-3) may cause high token usage and heavy "
        "background task burden. Recommended: 5 or 10.",
    )

    dream_cron: str = Field(
        default="0 23 * * *",
        description="Cron expression for dream-based memory optimization job "
        "(empty to disable)",
    )

    auto_memory_search_config: AutoMemorySearchConfig = Field(
        default_factory=AutoMemorySearchConfig,
    )

    embedding_model_config: EmbeddingModelConfig = Field(
        default_factory=EmbeddingModelConfig,
    )

    rebuild_memory_index_on_start: bool = Field(
        default=False,
        description=(
            "Whether to clear and rebuild the memory search index when the"
            " agent starts. Set to False to skip re-indexing and only monitor"
            " new file changes."
        ),
    )

    recursive_file_watcher: bool = Field(
        default=False,
        description=(
            "Whether to watch memory directory recursively. "
            "Set to True to include subdirectories like memory/subdirectory/* "
            "in vector search indexing."
        ),
    )


class ContextCompactConfig(BaseModel):
    """Context compaction configuration."""

    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(
        default=True,
        description="Whether to enable automatic context compaction",
    )

    compact_threshold_ratio: float = Field(
        default=0.8,
        ge=0.1,
        le=0.9,
        description=(
            "Compaction trigger threshold ratio: compaction is triggered when "
            "the context length reaches this fraction of max_input_length"
        ),
    )

    reserve_threshold_ratio: float = Field(
        default=0.1,
        ge=0,
        le=0.3,
        description=(
            "Context reserve threshold ratio: the most recent fraction of the "
            "context is preserved after compaction to maintain continuity"
        ),
    )

    compact_with_thinking_block: bool = Field(
        default=True,
        description="Whether to include thinking blocks when compacting",
    )


class ToolResultPruningConfig(BaseModel):
    """Tool result pruning configuration."""

    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(
        default=True,
        description="Whether to enable tool result pruning",
    )

    pruning_recent_n: int = Field(
        default=2,
        ge=1,
        le=10,
        description="Number of recent messages to use recent_max_bytes for",
    )

    pruning_old_msg_max_bytes: int = Field(
        default=3000,
        ge=100,
        description=("Byte threshold for old messages in tool result pruning"),
    )

    pruning_recent_msg_max_bytes: int = Field(
        default=50000,
        ge=1000,
        description=(
            "Byte threshold for recent messages in tool result pruning"
        ),
    )

    offload_retention_days: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Number of days to retain tool result files",
    )

    tool_results_cache: str = Field(
        default="tool_results",
        description="Directory name for tool result cache files "
        "relative to working_dir",
    )

    exempt_file_extensions: List[str] = Field(
        default_factory=lambda: [".md"],
        description=(
            "File extensions exempt from tool result pruning. "
            "Tool results for read_file operations on these file types "
            "will use recent_max_bytes instead of old_max_bytes."
        ),
    )

    exempt_tool_names: List[str] = Field(
        default_factory=lambda: ["chat_with_agent"],
        description=(
            "Tool names exempt from tool result pruning. "
            "Tool results from these tools will use recent_max_bytes "
            "instead of old_max_bytes."
        ),
    )


class LightContextConfig(BaseModel):
    """Light context manager configuration."""

    model_config = ConfigDict(extra="ignore")

    dialog_path: str = Field(
        default="dialog",
        description="Path for dialog persistence to jsonl files "
        "relative to working_dir.",
    )

    token_count_estimate_divisor: float = Field(
        default=4,
        ge=2,
        le=5,
        description=(
            "Divisor for byte-based token estimation (byte_len / divisor)"
        ),
    )

    context_compact_config: ContextCompactConfig = Field(
        default_factory=ContextCompactConfig,
    )
    tool_result_pruning_config: ToolResultPruningConfig = Field(
        default_factory=ToolResultPruningConfig,
    )


class AgentsRunningConfig(BaseModel):
    """Agent runtime behavior configuration."""

    model_config = ConfigDict(extra="ignore")

    max_iters: int = Field(
        default=100,
        ge=1,
        description=(
            "Maximum number of reasoning-acting iterations for ReAct agent"
        ),
    )

    auto_continue_on_text_only: bool = Field(
        default=False,
        description=(
            "When the model returns a text-only assistant message (no tool "
            "calls), inject one follow-up hint and run one extra reasoning "
            "pass with the same tool_choice as the current step (typically "
            "'auto'), so the model can either emit tool calls or finish with "
            "text. Does not use tool_choice='required' (that would force "
            "tools and prevent a natural summary when the task is done)."
        ),
    )

    llm_retry_enabled: bool = Field(
        default=LLM_MAX_RETRIES > 0,
        description="Whether to auto-retry transient LLM API errors",
    )

    llm_max_retries: int = Field(
        default=max(LLM_MAX_RETRIES, 1),
        ge=1,
        description="Maximum retry attempts for transient LLM API errors",
    )

    llm_backoff_base: float = Field(
        default=LLM_BACKOFF_BASE,
        ge=0.1,
        description="Base delay in seconds for exponential LLM retry backoff",
    )

    llm_backoff_cap: float = Field(
        default=LLM_BACKOFF_CAP,
        ge=0.5,
        description=(
            "Maximum delay cap in seconds for LLM retry backoff; "
            "must be greater than or equal to the base delay"
        ),
    )

    llm_max_concurrent: int = Field(
        default=LLM_MAX_CONCURRENT,
        ge=1,
        description=(
            "Maximum number of concurrent in-flight LLM calls. "
            "Shared across all agents; only the first initialization wins."
        ),
    )

    llm_max_qpm: int = Field(
        default=LLM_MAX_QPM,
        ge=0,
        description=(
            "Maximum queries per minute (60-second sliding window). "
            "New requests that would exceed this limit wait before being "
            "dispatched — proactively preventing 429s. 0 = disabled."
        ),
    )

    llm_rate_limit_pause: float = Field(
        default=LLM_RATE_LIMIT_PAUSE,
        ge=1.0,
        description=(
            "Default pause duration (seconds) applied globally when a 429 "
            "rate-limit response is received."
        ),
    )

    llm_rate_limit_jitter: float = Field(
        default=LLM_RATE_LIMIT_JITTER,
        ge=0.0,
        description=(
            "Random jitter range (seconds) added on top of the pause so "
            "concurrent waiters stagger their wake-up."
        ),
    )

    llm_acquire_timeout: float = Field(
        default=LLM_ACQUIRE_TIMEOUT,
        ge=10.0,
        description=(
            "Maximum time (seconds) a caller waits to acquire a rate-limiter "
            "slot before giving up with an error."
        ),
    )

    shell_command_timeout: float = Field(
        default=60.0,
        ge=1.0,
        description=(
            "Default timeout in seconds for execute_shell_command. "
            "The LLM may still override this per-call via the timeout "
            "parameter."
        ),
    )

    @model_validator(mode="after")
    def validate_llm_retry_backoff(self) -> "AgentsRunningConfig":
        """Validate LLM retry backoff relationships."""
        if self.llm_backoff_cap < self.llm_backoff_base:
            raise ConfigurationException(
                config_key="llm_backoff",
                message=(
                    "llm_backoff_cap must be greater than or equal to "
                    "llm_backoff_base"
                ),
            )
        return self

    max_input_length: int = Field(
        default=128 * 1024,  # 128K = 131072 tokens
        ge=1000,
        description=(
            "Maximum input length (tokens) for the model context window"
        ),
    )

    history_max_length: int = Field(
        default=10000,
        ge=1000,
        description="Maximum length for /history command output",
    )

    context_manager_backend: str = Field(default="light")

    light_context_config: LightContextConfig = Field(
        default_factory=LightContextConfig,
    )

    memory_manager_backend: str = Field(default="remelight")

    reme_light_memory_config: ReMeLightMemoryConfig = Field(
        default_factory=ReMeLightMemoryConfig,
    )

    daily_memory_dir: str = Field(
        default="memory",
        description="Dir name to daily summary file",
    )


class AgentsLLMRoutingConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(default=False)
    mode: Literal["local_first", "cloud_first"] = Field(
        default="local_first",
        description=(
            "local_first routes to the local slot by default; cloud_first "
            "routes to the cloud slot by default. Smarter switching can be "
            "added later without changing the dual-slot config shape."
        ),
    )
    local: ModelSlotConfig = Field(
        default_factory=ModelSlotConfig,
        description="Local model slot (required when routing is enabled).",
    )
    cloud: Optional[ModelSlotConfig] = Field(
        default=None,
        description=(
            "Optional explicit cloud model slot; when null, uses "
            "providers.json active_llm."
        ),
    )


class AgentProfileRef(BaseModel):
    """Agent Profile reference (stored in root config.json).

    Only contains ID and workspace directory reference.
    Full agent configuration is stored in workspace/agent.json.
    """

    model_config = ConfigDict(extra="ignore")

    id: str = Field(..., description="Unique agent ID")
    workspace_dir: str = Field(
        ...,
        description="Path to agent's workspace directory",
    )
    enabled: bool = Field(
        default=True,
        description="Whether agent is enabled (controls instance loading)",
    )


class PlanConfig(BaseModel):
    """Plan mode configuration (stored in agent.json)."""

    enabled: bool = Field(
        default=False,
        description="Whether plan mode is enabled for this agent",
    )


class AgentProfileConfig(BaseModel):
    """Complete Agent Profile configuration (stored in workspace/agent.json).

    Each agent has its own configuration file with all settings.
    """

    id: str = Field(..., description="Unique agent ID")
    name: str = Field(..., description="Human-readable agent name")
    description: str = Field(default="", description="Agent description")
    workspace_dir: str = Field(
        default="",
        description="Path to agent's workspace (optional, for reference)",
    )
    template_id: Optional[str] = Field(
        default=None,
        description="Builtin template used when this agent was created",
    )

    # Agent-specific configurations
    channels: Optional["ChannelConfig"] = Field(
        default=None,
        description="Channel configurations for this agent",
    )
    mcp: Optional["MCPConfig"] = Field(
        default=None,
        description="MCP clients for this agent",
    )
    heartbeat: Optional[HeartbeatConfig] = Field(
        default=None,
        description="Heartbeat configuration for this agent",
    )
    last_dispatch: Optional["LastDispatchConfig"] = Field(
        default=None,
        description="Last dispatch target for this agent",
    )
    running: AgentsRunningConfig = Field(
        default_factory=AgentsRunningConfig,
        description="Runtime configuration",
    )
    llm_routing: AgentsLLMRoutingConfig = Field(
        default_factory=AgentsLLMRoutingConfig,
        description="LLM routing settings",
    )
    active_model: Optional["ModelSlotConfig"] = Field(
        default=None,
        description="Active model for this agent (provider_id + model)",
    )
    language: str = Field(
        default="zh",
        description="Language setting for this agent",
    )
    approval_level: str = Field(
        default="AUTO",
        description=(
            "Tool execution security level: "
            "STRICT (all tools need approval), "
            "SMART (low-risk auto-allowed), "
            "AUTO (only guarded tools), "
            "OFF (guard disabled)"
        ),
    )
    system_prompt_files: List[str] = Field(
        default_factory=lambda: ["AGENTS.md", "SOUL.md", "PROFILE.md"],
        description="System prompt markdown files",
    )
    tools: Optional["ToolsConfig"] = Field(
        default=None,
        description="Tools configuration for this agent",
    )
    security: Optional["SecurityConfig"] = Field(
        default=None,
        description="Security configuration for this agent",
    )
    acp: Optional[ACPConfig] = Field(
        default=None,
        description="ACP configuration for this agent",
    )
    plan: PlanConfig = Field(
        default_factory=PlanConfig,
        description="Plan mode configuration for this agent",
    )


class AgentsConfig(BaseModel):
    """Agents configuration (root config.json only contains references)."""

    active_agent: str = Field(
        default="default",
        description="Currently active agent ID",
    )
    agent_order: List[str] = Field(
        default_factory=lambda: ["default"],
        description="Persisted UI order for configured agents",
    )
    profiles: Dict[str, AgentProfileRef] = Field(
        default_factory=lambda: {
            "default": AgentProfileRef(
                id="default",
                workspace_dir=f"{WORKING_DIR}/workspaces/default",
            ),
        },
        description="Agent profile references (ID and workspace path only)",
    )

    # Legacy fields for backward compatibility (deprecated)
    # These fields MUST have default values (not None) to support downgrade
    defaults: Optional[AgentsDefaultsConfig] = None
    running: AgentsRunningConfig = Field(
        default_factory=AgentsRunningConfig,
    )
    llm_routing: AgentsLLMRoutingConfig = Field(
        default_factory=AgentsLLMRoutingConfig,
    )
    language: str = Field(default="zh")
    installed_md_files_language: Optional[str] = None
    system_prompt_files: List[str] = Field(
        default_factory=lambda: ["AGENTS.md", "SOUL.md", "PROFILE.md"],
    )
    audio_mode: Literal["auto", "native"] = Field(
        default="auto",
        description=(
            "How to handle incoming audio/voice messages. "
            '"auto": transcribe if a provider is available, otherwise show '
            "file-uploaded placeholder; "
            '"native": send audio blocks directly to the model '
            "(may need ffmpeg)."
        ),
    )

    transcription_provider_type: Literal[
        "disabled",
        "whisper_api",
        "local_whisper",
    ] = Field(
        default="disabled",
        description=(
            "Transcription backend. "
            '"disabled": no transcription; '
            '"whisper_api": remote OpenAI-compatible endpoint; '
            '"local_whisper": locally installed openai-whisper.'
        ),
    )
    transcription_provider_id: str = Field(
        default="",
        description=(
            "Provider ID for Whisper API transcription. "
            "Empty = no provider selected. "
            'Only used when transcription_provider_type is "whisper_api".'
        ),
    )
    transcription_model: str = Field(
        default="whisper-1",
        description=(
            "Model name for Whisper API transcription. "
            'e.g. "whisper-1", "whisper-large-v3".'
        ),
    )


class LastDispatchConfig(BaseModel):
    """Last channel/user/session that received a user-originated reply."""

    channel: str = ""
    user_id: str = ""
    session_id: str = ""


class MCPClientConfig(BaseModel):
    """Configuration for a single MCP client."""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    description: str = ""
    enabled: bool = True
    transport: Literal["stdio", "streamable_http", "sse"] = "stdio"
    url: str = ""
    headers: Dict[str, str] = Field(default_factory=dict)
    command: str = ""
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    cwd: str = ""

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_fields(cls, data):
        """Normalize common MCP field aliases from third-party examples."""
        if not isinstance(data, dict):
            return data

        payload = dict(data)

        if "isActive" in payload and "enabled" not in payload:
            payload["enabled"] = payload["isActive"]

        if "baseUrl" in payload and "url" not in payload:
            payload["url"] = payload["baseUrl"]

        if "type" in payload and "transport" not in payload:
            payload["transport"] = payload["type"]

        if (
            "transport" not in payload
            and (payload.get("url") or payload.get("baseUrl"))
            and not payload.get("command")
        ):
            payload["transport"] = "streamable_http"

        raw_transport = payload.get("transport")
        if isinstance(raw_transport, str):
            normalized = raw_transport.strip().lower()
            transport_alias_map = {
                "streamablehttp": "streamable_http",
                "http": "streamable_http",
                "stdio": "stdio",
                "sse": "sse",
            }
            payload["transport"] = transport_alias_map.get(
                normalized,
                normalized,
            )

        return payload

    @model_validator(mode="after")
    def _validate_transport_config(self):
        """Validate required fields for each MCP transport type."""
        if self.transport == "stdio":
            if not self.command.strip():
                raise ConfigurationException(
                    config_key="mcp.command",
                    message="stdio MCP client requires non-empty command",
                )
            return self

        if not self.url.strip():
            raise ConfigurationException(
                config_key="mcp.url",
                message=f"{self.transport} MCP client requires non-empty url",
            )
        return self


class MCPConfig(BaseModel):
    """MCP clients configuration.

    Uses a dict to allow dynamic client definitions.
    Default tavily_search client is created and auto-enabled if API key exists.
    """

    clients: Dict[str, MCPClientConfig] = Field(
        default_factory=lambda: {
            "tavily_search": MCPClientConfig(
                name="tavily_mcp",
                enabled=False,
                command="npx",
                args=["-y", "tavily-mcp@latest"],
                env={"TAVILY_API_KEY": ""},
            ),
        },
    )


class BuiltinToolConfig(BaseModel):
    """Configuration for a single built-in tool."""

    name: str = Field(..., description="Tool function name")
    enabled: bool = Field(
        default=True,
        description="Whether the tool is enabled",
    )
    description: str = Field(default="", description="Tool description")
    display_to_user: bool = Field(
        default=True,
        description="Whether tool output is rendered to user channels",
    )
    async_execution: bool = Field(
        default=False,
        description="Whether to execute the tool asynchronously in background",
    )
    icon: str | None = Field(
        default=None,
        description="Emoji icon for the tool",
    )


def _default_builtin_tools() -> Dict[str, BuiltinToolConfig]:
    """Return a fresh copy of the canonical built-in tool definitions."""
    return {
        "execute_shell_command": BuiltinToolConfig(
            name="execute_shell_command",
            enabled=True,
            description="Execute shell commands",
            icon="💻",
        ),
        "read_file": BuiltinToolConfig(
            name="read_file",
            enabled=True,
            description="Read file contents",
            icon="📄",
        ),
        "write_file": BuiltinToolConfig(
            name="write_file",
            enabled=True,
            description="Write content to file",
            icon="✍️",
        ),
        "edit_file": BuiltinToolConfig(
            name="edit_file",
            enabled=True,
            description="Edit file using find-and-replace",
            icon="🖊️",
        ),
        "grep_search": BuiltinToolConfig(
            name="grep_search",
            enabled=True,
            description="Search file contents by pattern",
            icon="🔍",
        ),
        "glob_search": BuiltinToolConfig(
            name="glob_search",
            enabled=True,
            description="Find files matching a glob pattern",
            icon="📁",
        ),
        "browser_use": BuiltinToolConfig(
            name="browser_use",
            enabled=True,
            description="Browser automation and web interaction",
            icon="🌐",
        ),
        "desktop_screenshot": BuiltinToolConfig(
            name="desktop_screenshot",
            enabled=True,
            description="Capture desktop screenshots",
            icon="📸",
        ),
        "view_image": BuiltinToolConfig(
            name="view_image",
            enabled=True,
            description="Load an image into LLM context for visual analysis",
            display_to_user=False,
            icon="🖼️",
        ),
        "view_video": BuiltinToolConfig(
            name="view_video",
            enabled=True,
            description="Load a video into LLM context for visual analysis",
            display_to_user=False,
            icon="🎥",
        ),
        "send_file_to_user": BuiltinToolConfig(
            name="send_file_to_user",
            enabled=True,
            description="Send files to user",
            icon="📤",
        ),
        "get_current_time": BuiltinToolConfig(
            name="get_current_time",
            enabled=True,
            description="Get current date and time",
            icon="🕐",
        ),
        "set_user_timezone": BuiltinToolConfig(
            name="set_user_timezone",
            enabled=True,
            description="Set user timezone",
            icon="🌍",
        ),
        "get_token_usage": BuiltinToolConfig(
            name="get_token_usage",
            enabled=True,
            description="Get llm token usage",
            icon="📊",
        ),
        "delegate_external_agent": BuiltinToolConfig(
            name="delegate_external_agent",
            enabled=False,
            description="Delegate work to an external ACP agent runner",
            icon="📡",
        ),
        "list_agents": BuiltinToolConfig(
            name="list_agents",
            enabled=True,
            description="List configured agents from the local API",
            icon="🤖",
        ),
        "chat_with_agent": BuiltinToolConfig(
            name="chat_with_agent",
            enabled=True,
            description=(
                "Send a message to another configured agent and wait for "
                "the response"
            ),
            icon="💬",
        ),
        "submit_to_agent": BuiltinToolConfig(
            name="submit_to_agent",
            enabled=True,
            description="Submit a background task to another configured agent",
            icon="📨",
        ),
        "check_agent_task": BuiltinToolConfig(
            name="check_agent_task",
            enabled=True,
            description="Check the status of a background agent task",
            icon="⏳",
        ),
    }


class ToolsConfig(BaseModel):
    """Built-in tools management configuration."""

    builtin_tools: Dict[str, BuiltinToolConfig] = Field(
        default_factory=_default_builtin_tools,
    )

    @model_validator(mode="after")
    def _merge_default_tools(self):
        """Ensure new code-defined tools are present in saved configs."""
        for name, tc in _default_builtin_tools().items():
            if name not in self.builtin_tools:
                self.builtin_tools[name] = tc
            elif self.builtin_tools[name].icon is None:
                self.builtin_tools[name].icon = tc.icon
        return self


def build_qa_agent_tools_config() -> ToolsConfig:
    """Tools preset for builtin ``default_qa_agent`` (first workspace init).

    Only these are enabled: execute_shell_command, read_file, edit_file,
    write_file, view_image. All other built-ins are disabled.
    """
    allow = frozenset(
        {
            "execute_shell_command",
            "read_file",
            "write_file",
            "edit_file",
            "view_image",
        },
    )
    builtin_tools = {
        name: tc.model_copy(update={"enabled": name in allow})
        for name, tc in _default_builtin_tools().items()
    }
    return ToolsConfig(builtin_tools=builtin_tools)


def build_local_agent_tools_config() -> ToolsConfig:
    """Tools preset for local collaborative agents.

    Inter-agent coordination tools are enabled by default, along with
    execute_shell_command and file read/write/edit tools, so a local small
    model can escalate planning work while still handling basic workspace
    actions. All other built-ins are disabled.
    """
    allow = frozenset(
        {
            "list_agents",
            "chat_with_agent",
            "submit_to_agent",
            "check_agent_task",
            "execute_shell_command",
            "read_file",
            "write_file",
            "edit_file",
        },
    )
    builtin_tools = {
        name: tc.model_copy(update={"enabled": name in allow})
        for name, tc in _default_builtin_tools().items()
    }
    return ToolsConfig(builtin_tools=builtin_tools)


class ToolGuardRuleConfig(BaseModel):
    """A single user-defined guard rule (stored in config.json)."""

    id: str
    tools: List[str] = Field(default_factory=list)
    params: List[str] = Field(default_factory=list)
    category: str = "command_injection"
    severity: str = "HIGH"
    patterns: List[str] = Field(default_factory=list)
    exclude_patterns: List[str] = Field(default_factory=list)
    description: str = ""
    remediation: str = ""


def _default_shell_evasion_checks() -> Dict[str, bool]:
    """Return default shell-evasion checks (all disabled at startup)."""
    return {
        "command_substitution": False,
        "obfuscated_flags": False,
        "backslash_escaped_whitespace": False,
        "backslash_escaped_operators": False,
        "newlines": False,
        "comment_quote_desync": False,
        "quoted_newline": False,
    }


class ToolGuardConfig(BaseModel):
    """Tool guard settings under ``security.tool_guard``.

    ``guarded_tools``: ``None`` → use built-in default set; empty list → guard
    nothing; non-empty list → guard only those tools.
    """

    enabled: bool = True
    guarded_tools: Optional[List[str]] = None
    denied_tools: List[str] = Field(default_factory=list)
    custom_rules: List[ToolGuardRuleConfig] = Field(default_factory=list)
    disabled_rules: List[str] = Field(default_factory=list)
    shell_evasion_checks: Dict[str, bool] = Field(
        default_factory=_default_shell_evasion_checks,
    )


class FileGuardConfig(BaseModel):
    """File guard settings under ``security.file_guard``."""

    enabled: bool = True
    sensitive_files: List[str] = Field(default_factory=list)


class SkillScannerWhitelistEntry(BaseModel):
    """A whitelisted skill (identified by name + content hash)."""

    skill_name: str
    content_hash: str = Field(
        default="",
        description="SHA-256 of concatenated file contents at whitelist time. "
        "Empty string means any content is allowed.",
    )
    added_at: str = Field(
        default="",
        description="ISO 8601 timestamp when the entry was added.",
    )


class SkillScannerConfig(BaseModel):
    """Skill scanner settings under ``security.skill_scanner``.

    ``mode`` controls the scanner behavior:
    * ``"block"`` – scan and block unsafe skills.
    * ``"warn"``  – scan but only log warnings, do not block (default).
    * ``"off"``   – disable scanning entirely.
    """

    mode: Literal["block", "warn", "off"] = Field(
        default="warn",
        description="Scanner mode: block, warn, or off.",
    )
    timeout: int = Field(
        default=30,
        ge=5,
        le=300,
        description="Max seconds to wait for a scan to complete.",
    )
    whitelist: List[SkillScannerWhitelistEntry] = Field(
        default_factory=list,
        description="Skills that bypass security scanning.",
    )


class SecurityConfig(BaseModel):
    """Top-level ``security`` section in config.json."""

    tool_guard: ToolGuardConfig = Field(default_factory=ToolGuardConfig)
    file_guard: FileGuardConfig = Field(default_factory=FileGuardConfig)
    skill_scanner: SkillScannerConfig = Field(
        default_factory=SkillScannerConfig,
    )
    allow_no_auth_hosts: List[str] = Field(
        default_factory=lambda: ["127.0.0.1", "::1"],
        description=(
            "List of client IP addresses that can access API endpoints "
            "without authentication. By default, localhost addresses "
            "(127.0.0.1 for IPv4, ::1 for IPv6) are allowed. "
            "WARNING: Only add trusted IP addresses to this list."
        ),
    )


class Config(BaseModel):
    """Root config (config.json)."""

    channels: ChannelConfig = ChannelConfig()
    mcp: MCPConfig = MCPConfig()
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    last_api: LastApiConfig = LastApiConfig()
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    last_dispatch: Optional[LastDispatchConfig] = None
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    acp: ACPConfig = Field(default_factory=ACPConfig)
    show_tool_details: bool = True
    user_timezone: str = Field(
        default_factory=detect_system_timezone,
        description="User IANA timezone (e.g. Asia/Shanghai). "
        "Defaults to the system timezone.",
    )
    plugins: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict,
        description="Plugin configurations. Key is plugin_id, "
        "value is plugin-specific config dict.",
    )


ChannelConfigUnion = Union[
    IMessageChannelConfig,
    DiscordConfig,
    DingTalkConfig,
    FeishuConfig,
    QQConfig,
    TelegramConfig,
    MattermostConfig,
    MQTTConfig,
    ConsoleConfig,
    MatrixConfig,
    VoiceChannelConfig,
    SIPChannelConfig,
    WecomConfig,
    XiaoYiConfig,
    WeixinConfig,
]


# Agent configuration utility functions


def build_fallback_agent_profile_config(
    agent_id: str,
    config: "Config",
) -> AgentProfileConfig:
    """Build the same profile as when ``agent.json``
    is missing (no disk read/write).

    Used by :func:`load_agent_config` and ``qwenpaw doctor fix``
    so defaults stay in sync.
    """
    if agent_id not in config.agents.profiles:
        raise ValueError(f"Agent '{agent_id}' not found in config")

    agent_ref = config.agents.profiles[agent_id]
    workspace_dir = Path(agent_ref.workspace_dir).expanduser()
    return AgentProfileConfig(
        id=agent_id,
        name=agent_id.title(),
        description=f"{agent_id} agent",
        workspace_dir=str(workspace_dir),
        channels=(
            config.channels
            if hasattr(config, "channels") and config.channels
            else None
        ),
        mcp=config.mcp if hasattr(config, "mcp") and config.mcp else None,
        tools=(
            config.tools if hasattr(config, "tools") and config.tools else None
        ),
        security=(
            config.security
            if hasattr(config, "security") and config.security
            else None
        ),
        running=(
            config.agents.running
            if hasattr(config.agents, "running") and config.agents.running
            else AgentsRunningConfig()
        ),
        llm_routing=(
            config.agents.llm_routing
            if hasattr(config.agents, "llm_routing")
            and config.agents.llm_routing
            else AgentsLLMRoutingConfig()
        ),
        system_prompt_files=(
            config.agents.system_prompt_files
            if hasattr(config.agents, "system_prompt_files")
            and config.agents.system_prompt_files
            else ["AGENTS.md", "SOUL.md", "PROFILE.md"]
        ),
    )


def load_agent_config(agent_id: str) -> AgentProfileConfig:
    """Load agent's complete configuration from workspace/agent.json.

    Args:
        agent_id: Agent ID to load

    Returns:
        AgentProfileConfig: Complete agent configuration

    Raises:
        ValueError: If agent ID not found in root config
    """
    from .utils import load_config

    config = load_config()

    if agent_id not in config.agents.profiles:
        raise ConfigurationException(
            config_key="agent",
            message=f"Agent '{agent_id}' not found in config",
        )

    agent_ref = config.agents.profiles[agent_id]
    workspace_dir = Path(agent_ref.workspace_dir).expanduser()
    agent_config_path = workspace_dir / "agent.json"

    if not agent_config_path.exists():
        fallback_config = build_fallback_agent_profile_config(agent_id, config)
        # Save for future use
        save_agent_config(agent_id, fallback_config)
        return fallback_config

    with open(agent_config_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Normalize legacy ~/.copaw-bound paths to current WORKING_DIR.
    # This keeps QWENPAW_WORKING_DIR effective even if existing agent.json
    # contains older hard-coded paths like "~/.copaw/media".
    try:
        from .utils import _normalize_working_dir_bound_paths

        data = _normalize_working_dir_bound_paths(data)
    except Exception:
        pass

    return AgentProfileConfig(**data)


def save_agent_config(
    agent_id: str,
    agent_config: AgentProfileConfig,
) -> None:
    """Save agent configuration to workspace/agent.json.

    Args:
        agent_id: Agent ID
        agent_config: Complete agent configuration to save

    Raises:
        ValueError: If agent ID not found in root config
    """
    from .utils import load_config

    config = load_config()

    if agent_id not in config.agents.profiles:
        raise ConfigurationException(
            config_key="agent",
            message=f"Agent '{agent_id}' not found in config",
        )

    agent_ref = config.agents.profiles[agent_id]
    workspace_dir = Path(agent_ref.workspace_dir).expanduser()
    workspace_dir.mkdir(parents=True, exist_ok=True)

    agent_config_path = workspace_dir / "agent.json"

    with open(agent_config_path, "w", encoding="utf-8") as f:
        json.dump(
            agent_config.model_dump(exclude_none=True),
            f,
            ensure_ascii=False,
            indent=2,
        )


def migrate_legacy_config_to_multi_agent() -> bool:
    """Migrate legacy single-agent config to new multi-agent structure.

    Returns:
        bool: True if migration was performed, False if already migrated
    """
    from .utils import load_config, save_config

    config = load_config()

    # Check if already migrated (new structure has only AgentProfileRef)
    if "default" in config.agents.profiles:
        agent_ref = config.agents.profiles["default"]
        # If it's already a AgentProfileRef, migration done
        if isinstance(agent_ref, AgentProfileRef):
            # Check if default agent config exists
            workspace_dir = Path(agent_ref.workspace_dir).expanduser()
            agent_config_path = workspace_dir / "agent.json"
            if agent_config_path.exists():
                return False  # Already migrated

    # Perform migration
    print("Migrating legacy config to multi-agent structure...")

    # Extract legacy agent configuration
    legacy_agents = config.agents

    # Create default agent workspace
    default_workspace = Path(f"{WORKING_DIR}/workspaces/default").expanduser()
    default_workspace.mkdir(parents=True, exist_ok=True)

    # Create default agent configuration from legacy settings
    default_agent_config = AgentProfileConfig(
        id="default",
        name="Default Agent",
        description="Default QwenPaw agent",
        workspace_dir=str(default_workspace),
        channels=config.channels if config.channels else None,
        mcp=config.mcp if config.mcp else None,
        heartbeat=(
            legacy_agents.defaults.heartbeat
            if legacy_agents.defaults
            else None
        ),
        running=(
            legacy_agents.running
            if legacy_agents.running
            else AgentsRunningConfig()
        ),
        llm_routing=(
            legacy_agents.llm_routing
            if legacy_agents.llm_routing
            else AgentsLLMRoutingConfig()
        ),
        system_prompt_files=(
            legacy_agents.system_prompt_files
            if legacy_agents.system_prompt_files
            else ["AGENTS.md", "SOUL.md", "PROFILE.md"]
        ),
        tools=config.tools if config.tools else None,
        security=config.security if config.security else None,
    )

    # Save default agent configuration to workspace
    agent_config_path = default_workspace / "agent.json"
    with open(agent_config_path, "w", encoding="utf-8") as f:
        json.dump(
            default_agent_config.model_dump(exclude_none=True),
            f,
            ensure_ascii=False,
            indent=2,
        )

    # Migrate existing workspace files from legacy default working dir.
    # When QWENPAW_WORKING_DIR is customized, historical data may still exist
    # under "~/.copaw".
    old_workspace = Path("~/.copaw").expanduser().resolve()

    # Move sessions, memory, and other workspace files
    for item_name in ["sessions", "memory", "jobs.json"]:
        old_path = old_workspace / item_name
        if old_path.exists():
            new_path = default_workspace / item_name
            if not new_path.exists():
                import shutil

                if old_path.is_dir():
                    shutil.copytree(old_path, new_path)
                else:
                    shutil.copy2(old_path, new_path)
                print(f"  Migrated {item_name} to default workspace")

    # Copy markdown files (AGENTS.md, SOUL.md, PROFILE.md)
    for md_file in ["AGENTS.md", "SOUL.md", "PROFILE.md"]:
        old_md = old_workspace / md_file
        if old_md.exists():
            new_md = default_workspace / md_file
            if not new_md.exists():
                import shutil

                shutil.copy2(old_md, new_md)
                print(f"  Migrated {md_file} to default workspace")

    # Update root config.json to new structure
    # CRITICAL: Preserve legacy agent fields for downgrade compatibility
    config.agents = AgentsConfig(
        active_agent="default",
        profiles={
            "default": AgentProfileRef(
                id="default",
                workspace_dir=str(default_workspace),
            ),
        },
        # Preserve legacy fields with values from migrated agent config
        running=default_agent_config.running,
        llm_routing=default_agent_config.llm_routing,
        language=(
            default_agent_config.language
            if hasattr(default_agent_config, "language")
            else "zh"
        ),
        system_prompt_files=default_agent_config.system_prompt_files,
    )

    # IMPORTANT: Keep channels, mcp, tools, security in root config for
    # backward compatibility. Do NOT clear these fields.
    # Old versions expect these fields to exist with valid values.

    save_config(config)

    print("Migration completed successfully!")
    print(f"  Default agent workspace: {default_workspace}")
    print(f"  Default agent config: {agent_config_path}")

    return True
