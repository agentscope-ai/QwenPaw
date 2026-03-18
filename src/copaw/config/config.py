# -*- coding: utf-8 -*-
import os
import json
from pathlib import Path
from typing import Optional, Union, Dict, List, Literal

from pydantic import BaseModel, Field, ConfigDict, model_validator
import shortuuid

from .timezone import detect_system_timezone
from ..constant import (
    HEARTBEAT_DEFAULT_EVERY,
    HEARTBEAT_DEFAULT_TARGET,
    WORKING_DIR,
)
from ..providers.models import ModelSlotConfig


def generate_short_agent_id() -> str:
    """Generate a 6-character short UUID for agent identification.

    Returns:
        6-character short UUID string
    """
    return shortuuid.ShortUUID().random(length=6)


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


class DingTalkConfig(BaseChannelConfig):
    client_id: str = ""
    client_secret: str = ""
    message_type: str = "markdown"
    card_template_id: str = ""
    card_template_key: str = "content"
    robot_code: str = ""
    media_dir: Optional[str] = None


class FeishuConfig(BaseChannelConfig):
    """Feishu/Lark channel: app_id, app_secret; optional encrypt_key,
    verification_token for event handler. media_dir for received media.
    """

    app_id: str = ""
    app_secret: str = ""
    encrypt_key: str = ""
    verification_token: str = ""
    media_dir: Optional[str] = None


class QQConfig(BaseChannelConfig):
    app_id: str = ""
    client_secret: str = ""
    markdown_enabled: bool = True


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
    user_id: str = ""
    access_token: str = ""


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
    welcome_greeting: str = "Hi! This is CoPaw. How can I help you?"


class XiaoYiConfig(BaseChannelConfig):
    """XiaoYi channel: Huawei A2A protocol via WebSocket."""

    ak: str = ""  # Access Key
    sk: str = ""  # Secret Key
    agent_id: str = ""  # Agent ID from XiaoYi platform
    ws_url: str = "wss://hag.cloud.huawei.com/openclaw/v1/ws/link"
    task_timeout_ms: int = 3600000  # 1 hour task timeout


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
    wecom: WecomConfig = WecomConfig()
    xiaoyi: XiaoYiConfig = XiaoYiConfig()


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


class AgentsRunningConfig(BaseModel):
    """Agent runtime behavior configuration."""

    max_iters: int = Field(
        default=50,
        ge=1,
        description=(
            "Maximum number of reasoning-acting iterations for ReAct agent"
        ),
    )

    token_count_model: str = Field(
        default="default",
        description="Model to use for token counting",
    )

    token_count_estimate_divisor: float = Field(
        default=3.75,
        gt=1,
        description=(
            "Divisor for character-based token estimation " "(len / divisor)"
        ),
    )

    token_count_use_mirror: bool = Field(
        default=False,
        description="Whether to use mirror token counting",
    )

    max_input_length: int = Field(
        default=128 * 1024,  # 128K = 131072 tokens
        ge=1000,
        description=(
            "Maximum input length (tokens) for the model context window"
        ),
    )

    memory_compact_ratio: float = Field(
        default=0.75,
        ge=0.3,
        le=0.9,
        description="Ratio of memory to compact when memory is full",
    )

    memory_reserve_ratio: float = Field(
        default=0.1,
        ge=0.05,
        le=0.3,
        description="Ratio of memory to reserve when compact memory",
    )

    enable_tool_result_compact: bool = Field(
        default=True,
        description="Whether to compact tool result messages in memory",
    )

    tool_result_compact_keep_n: int = Field(
        default=3,
        ge=1,
        le=10,
        description=(
            "Number of tool result messages to keep in memory when compacting"
        ),
    )

    history_max_length: int = Field(
        default=10000,
        ge=1000,
        description="Maximum length for /history command output",
    )

    @property
    def memory_compact_reserve(self) -> int:
        """Memory compact reserve size (tokens)."""
        return int(self.max_input_length * self.memory_reserve_ratio)

    @property
    def memory_compact_threshold(self) -> int:
        """Memory compact threshold size (tokens)."""
        return int(self.max_input_length * self.memory_compact_ratio)


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

    id: str = Field(..., description="Unique agent ID")
    workspace_dir: str = Field(
        ...,
        description="Path to agent's workspace directory",
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


class AgentsConfig(BaseModel):
    """Agents configuration (root config.json only contains references)."""

    active_agent: str = Field(
        default="default",
        description="Currently active agent ID",
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
                raise ValueError("stdio MCP client requires non-empty command")
            return self

        if not self.url.strip():
            raise ValueError(
                f"{self.transport} MCP client requires non-empty url",
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
                # Auto-enable if TAVILY_API_KEY exists in environment
                enabled=bool(os.getenv("TAVILY_API_KEY")),
                command="npx",
                args=["-y", "tavily-mcp@latest"],
                env={"TAVILY_API_KEY": os.getenv("TAVILY_API_KEY", "")},
            ),
        },
    )


class BuiltinToolConfig(BaseModel):
    """Configuration for a single built-in tool."""

    name: str = Field(..., description="Tool function name")
    enabled: bool = Field(True, description="Whether the tool is enabled")
    description: str = Field(default="", description="Tool description")
    display_to_user: bool = Field(
        True,
        description="Whether tool output is rendered to user channels",
    )


def _default_builtin_tools() -> Dict[str, BuiltinToolConfig]:
    """Return a fresh copy of the canonical built-in tool definitions."""
    return {
        "execute_shell_command": BuiltinToolConfig(
            name="execute_shell_command",
            enabled=True,
            description="Execute shell commands",
        ),
        "read_file": BuiltinToolConfig(
            name="read_file",
            enabled=True,
            description="Read file contents",
        ),
        "write_file": BuiltinToolConfig(
            name="write_file",
            enabled=True,
            description="Write content to file",
        ),
        "edit_file": BuiltinToolConfig(
            name="edit_file",
            enabled=True,
            description="Edit file using find-and-replace",
        ),
        "browser_use": BuiltinToolConfig(
            name="browser_use",
            enabled=True,
            description="Browser automation and web interaction",
        ),
        "desktop_screenshot": BuiltinToolConfig(
            name="desktop_screenshot",
            enabled=True,
            description="Capture desktop screenshots",
        ),
        "view_image": BuiltinToolConfig(
            name="view_image",
            enabled=True,
            description="Load an image into LLM context "
            "for visual analysis",
            display_to_user=False,
        ),
        "send_file_to_user": BuiltinToolConfig(
            name="send_file_to_user",
            enabled=True,
            description="Send files to user",
        ),
        "get_current_time": BuiltinToolConfig(
            name="get_current_time",
            enabled=True,
            description="Get current date and time",
        ),
        "set_user_timezone": BuiltinToolConfig(
            name="set_user_timezone",
            enabled=True,
            description="Set user timezone",
        ),
        "get_token_usage": BuiltinToolConfig(
            name="get_token_usage",
            enabled=True,
            description="Get llm token usage",
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
        return self


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
    skill_scanner: SkillScannerConfig = Field(
        default_factory=SkillScannerConfig,
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
    show_tool_details: bool = True
    user_timezone: str = Field(
        default_factory=detect_system_timezone,
        description="User IANA timezone (e.g. Asia/Shanghai). "
        "Defaults to the system timezone.",
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
    WecomConfig,
    XiaoYiConfig,
]


# Agent configuration utility functions


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
        raise ValueError(f"Agent '{agent_id}' not found in config")

    agent_ref = config.agents.profiles[agent_id]
    workspace_dir = Path(agent_ref.workspace_dir).expanduser()
    agent_config_path = workspace_dir / "agent.json"

    if not agent_config_path.exists():
        # Fallback: Try to use root config fields for backward compatibility
        # This allows downgrade scenarios where agent.json doesn't exist yet
        fallback_config = AgentProfileConfig(
            id=agent_id,
            name=agent_id.title(),
            description=f"{agent_id} agent",
            workspace_dir=str(workspace_dir),
            # Inherit from root config if available (for backward compat)
            channels=(
                config.channels
                if hasattr(config, "channels") and config.channels
                else None
            ),
            mcp=config.mcp if hasattr(config, "mcp") and config.mcp else None,
            tools=(
                config.tools
                if hasattr(config, "tools") and config.tools
                else None
            ),
            security=(
                config.security
                if hasattr(config, "security") and config.security
                else None
            ),
            # Use agent-specific configs with proper defaults
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
        # Save for future use
        save_agent_config(agent_id, fallback_config)
        return fallback_config

    with open(agent_config_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Normalize legacy ~/.copaw-bound paths to current WORKING_DIR.
    # This keeps COPAW_WORKING_DIR effective even if existing agent.json
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
        raise ValueError(f"Agent '{agent_id}' not found in config")

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
        description="Default CoPaw agent",
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
    # When COPAW_WORKING_DIR is customized, historical data may still exist
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
