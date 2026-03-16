# -*- coding: utf-8 -*-
import os
from typing import Optional, Union, Dict, List, Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator

from ..providers.models import ModelSlotConfig
from ..constant import (
    HEARTBEAT_DEFAULT_EVERY,
    HEARTBEAT_DEFAULT_TARGET,
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
    media_dir: str = "~/.copaw/media"
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
    media_dir: str = "~/.copaw/media"


class FeishuConfig(BaseChannelConfig):
    """Feishu/Lark channel: app_id, app_secret; optional encrypt_key,
    verification_token for event handler. media_dir for received media.
    """

    app_id: str = ""
    app_secret: str = ""
    encrypt_key: str = ""
    verification_token: str = ""
    media_dir: str = "~/.copaw/media"


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
    media_dir: str = "~/.copaw/media/mattermost"
    show_typing: Optional[bool] = None
    thread_follow_without_mention: bool = False


class ConsoleConfig(BaseChannelConfig):
    """Console channel: prints agent responses to stdout."""

    enabled: bool = True


class WecomConfig(BaseChannelConfig):
    """WeCom (Enterprise WeChat) AI Bot channel config."""

    bot_id: str = ""
    secret: str = ""
    media_dir: str = "~/.copaw/media"
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
        default=False,
        description="Whether to compact tool result messages in memory",
    )

    tool_result_compact_keep_n: int = Field(
        default=5,
        ge=1,
        le=10,
        description=(
            "Number of tool result messages to keep in memory when compacting"
        ),
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


class AgentsConfig(BaseModel):
    defaults: AgentsDefaultsConfig = Field(
        default_factory=AgentsDefaultsConfig,
    )
    running: AgentsRunningConfig = Field(
        default_factory=AgentsRunningConfig,
    )
    llm_routing: AgentsLLMRoutingConfig = Field(
        default_factory=AgentsLLMRoutingConfig,
        description="LLM routing settings (local/cloud).",
    )
    language: str = Field(
        default="zh",
        description="Language for agent MD files (zh/en/ru)",
    )
    installed_md_files_language: Optional[str] = Field(
        default=None,
        description="Language of currently installed md files",
    )
    system_prompt_files: List[str] = Field(
        default_factory=lambda: ["AGENTS.md", "SOUL.md", "PROFILE.md"],
        description="List of markdown files to load into system prompt",
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


class ToolsConfig(BaseModel):
    """Built-in tools management configuration."""

    builtin_tools: Dict[str, BuiltinToolConfig] = Field(
        default_factory=lambda: {
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
            "get_token_usage": BuiltinToolConfig(
                name="get_token_usage",
                enabled=True,
                description="Get llm token usage",
            ),
        },
    )


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


class SecurityConfig(BaseModel):
    """Top-level ``security`` section in config.json."""

    tool_guard: ToolGuardConfig = Field(default_factory=ToolGuardConfig)


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
