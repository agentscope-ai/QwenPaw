# -*- coding: utf-8 -*-
"""CLI channel: list and interactively configure channels in config.json."""
from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path
from typing import Optional

import click
from agentscope_runtime.engine.schemas.exception import (
    AppBaseException,
)

from ..config import (
    get_config_path,
    load_config,
    save_config,
)
from ..config.config import (
    Config,
    ConsoleConfig,
    DiscordConfig,
    TelegramConfig,
    DingTalkConfig,
    FeishuConfig,
    IMessageChannelConfig,
    QQConfig,
    VoiceChannelConfig,
    WeixinConfig,
    load_agent_config,
    save_agent_config,
)
from .utils import prompt_confirm, prompt_path, prompt_select
from .http import client, print_json, resolve_base_url
from ..config import get_available_channels
from ..constant import CUSTOM_CHANNELS_DIR
from ..app.channels.registry import (
    BUILTIN_CHANNEL_KEYS,
    get_channel_registry,
)


# Fields that contain secrets — display masked in ``list``
_SECRET_FIELDS = {
    "bot_token",
    "client_secret",
    "app_secret",
    "http_proxy_auth",
    "twilio_auth_token",
}

_ALL_CHANNEL_NAMES = {
    "imessage": "iMessage",
    "discord": "Discord",
    "telegram": "Telegram",
    "dingtalk": "DingTalk",
    "feishu": "Feishu",
    "qq": "QQ",
    "console": "Console",
    "voice": "Twilio",
}
# Public alias for tests and external use.
CHANNEL_NAMES = _ALL_CHANNEL_NAMES

# Template for `qwenpaw channels install <key>` stub (channel key substituted).
CHANNEL_TEMPLATE = '''# -*- coding: utf-8 -*-
"""Custom channel: {key}. Edit and implement required methods."""
from __future__ import annotations

import os
from typing import Any

from agentscope_runtime.engine.schemas.agent_schemas import (
    TextContent,
    ContentType,
)

from qwenpaw.app.channels.base import BaseChannel
from qwenpaw.app.channels.schema import ChannelType


class CustomChannel(BaseChannel):
    channel: ChannelType = "{key}"

    def __init__(
        self,
        process,
        enabled=True,
        bot_prefix="",
        on_reply_sent=None,
        show_tool_details=True,
        filter_tool_messages=False,
        filter_thinking=False,
        **kwargs,
    ):
        super().__init__(
            process,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
        )
        self.enabled = enabled
        self.bot_prefix = bot_prefix or ""

    @classmethod
    def from_config(
        cls,
        process,
        config,
        on_reply_sent=None,
        show_tool_details=True,
        **kwargs,
    ):
        return cls(
            process=process,
            enabled=getattr(config, "enabled", True),
            bot_prefix=getattr(config, "bot_prefix", ""),
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=kwargs.get(
                "filter_tool_messages",
                getattr(config, "filter_tool_messages", False),
            ),
            filter_thinking=kwargs.get(
                "filter_thinking",
                getattr(config, "filter_thinking", False),
            ),
        )

    @classmethod
    def from_env(cls, process, on_reply_sent=None):
        return cls(process=process, on_reply_sent=on_reply_sent)

    def build_agent_request_from_native(self, native_payload: Any):
        payload = native_payload if isinstance(native_payload, dict) else {{}}
        channel_id = payload.get("channel_id") or self.channel
        sender_id = payload.get("sender_id") or ""
        meta = payload.get("meta") or {{}}
        session_id = self.resolve_session_id(sender_id, meta)
        text = payload.get("text", "")
        content_parts = [TextContent(type=ContentType.TEXT, text=text)]
        request = self.build_agent_request_from_user_content(
            channel_id=channel_id,
            sender_id=sender_id,
            session_id=session_id,
            content_parts=content_parts,
            channel_meta=meta,
        )
        request.channel_meta = meta
        return request

    async def start(self):
        pass

    async def stop(self):
        pass

    async def send(self, to_handle: str, text: str, meta=None):
        # Implement: send text to the channel (e.g. HTTP API).
        pass
'''


def _get_channel_names() -> dict[str, str]:
    """Return channel key -> display name (built-in + plugins)."""
    available = get_available_channels()
    registry = get_channel_registry()
    out = {k: v for k, v in _ALL_CHANNEL_NAMES.items() if k in available}
    for key in available:
        if key not in out and key in registry:
            cls = registry[key]
            out[key] = (
                getattr(cls, "display_name", None)
                or key.replace(
                    "_",
                    " ",
                ).title()
            )
    return out


def _mask(value: str) -> str:
    """Mask a secret value, keeping first 4 chars visible."""
    if not value:
        return "(empty)"
    if len(value) <= 4:
        return "****"
    return value[:4] + "****"


# ── per-channel interactive configurators ──────────────────────────


def configure_imessage(
    current_config: IMessageChannelConfig,
) -> IMessageChannelConfig:
    """Configure iMessage channel interactively."""
    click.echo("\n=== Configure iMessage Channel ===")

    enabled = prompt_confirm(
        "Enable iMessage channel?",
        default=current_config.enabled,
    )

    if not enabled:
        current_config.enabled = False
        return current_config

    current_config.enabled = True

    bot_prefix = click.prompt(
        "Bot prefix (e.g., @bot)",
        default=current_config.bot_prefix or "",
        type=str,
    )
    current_config.bot_prefix = bot_prefix

    db_path = prompt_path(
        "iMessage database path",
        default=current_config.db_path or "~/Library/Messages/chat.db",
    )
    current_config.db_path = db_path

    poll_sec = click.prompt(
        "Poll interval (seconds)",
        default=current_config.poll_sec,
        type=float,
    )
    current_config.poll_sec = poll_sec

    return current_config


def configure_discord(current_config: DiscordConfig) -> DiscordConfig:
    """Configure Discord channel interactively."""
    click.echo("\n=== Configure Discord Channel ===")

    enabled = prompt_confirm(
        "Enable Discord channel?",
        default=current_config.enabled,
    )

    if not enabled:
        current_config.enabled = False
        return current_config

    current_config.enabled = True

    bot_prefix = click.prompt(
        "Bot prefix (e.g., @bot)",
        default=current_config.bot_prefix or "",
        type=str,
    )
    current_config.bot_prefix = bot_prefix

    bot_token = click.prompt(
        "Discord Bot Token",
        default=current_config.bot_token or "",
        hide_input=True,
        type=str,
    )
    current_config.bot_token = bot_token

    use_proxy = prompt_confirm(
        "Use HTTP proxy?",
        default=bool(current_config.http_proxy),
    )

    if use_proxy:
        http_proxy = click.prompt(
            "HTTP proxy address (e.g., http://127.0.0.1:7890)",
            default=current_config.http_proxy or "",
            type=str,
        )
        current_config.http_proxy = http_proxy

        use_proxy_auth = prompt_confirm(
            "Does proxy require authentication?",
            default=bool(current_config.http_proxy_auth),
        )

        if use_proxy_auth:
            http_proxy_auth = click.prompt(
                "Proxy authentication (format: username:password)",
                default=current_config.http_proxy_auth or "",
                hide_input=True,
                type=str,
            )
            current_config.http_proxy_auth = http_proxy_auth
        else:
            current_config.http_proxy_auth = ""
    else:
        current_config.http_proxy = ""
        current_config.http_proxy_auth = ""

    return current_config


def configure_dingtalk(current_config: DingTalkConfig) -> DingTalkConfig:
    """Configure DingTalk channel interactively."""
    click.echo("\n=== Configure DingTalk Channel ===")

    enabled = prompt_confirm(
        "Enable DingTalk channel?",
        default=current_config.enabled,
    )

    if not enabled:
        current_config.enabled = False
        return current_config

    current_config.enabled = True

    bot_prefix = click.prompt(
        "Bot prefix (e.g., @bot)",
        default=current_config.bot_prefix or "",
        type=str,
    )
    current_config.bot_prefix = bot_prefix

    client_id = click.prompt(
        "DingTalk Client ID",
        default=current_config.client_id or "",
        type=str,
    )
    current_config.client_id = client_id

    client_secret = click.prompt(
        "DingTalk Client Secret",
        default=current_config.client_secret or "",
        hide_input=True,
        type=str,
    )
    current_config.client_secret = client_secret

    return current_config


def configure_feishu(current_config: FeishuConfig) -> FeishuConfig:
    """Configure Feishu channel interactively."""
    click.echo("\n=== Configure Feishu Channel ===")

    enabled = prompt_confirm(
        "Enable Feishu channel?",
        default=current_config.enabled,
    )

    if not enabled:
        current_config.enabled = False
        return current_config

    current_config.enabled = True

    # Domain selection: feishu (China) or lark (International)
    domain_choices = ["feishu", "lark"]
    current_domain = current_config.domain or "feishu"
    domain = click.prompt(
        "Region (feishu for China, lark for International)",
        default=current_domain,
        type=click.Choice(domain_choices),
    )
    current_config.domain = domain

    bot_prefix = click.prompt(
        "Bot prefix (e.g., @bot)",
        default=current_config.bot_prefix or "",
        type=str,
    )
    current_config.bot_prefix = bot_prefix

    app_id = click.prompt(
        "Feishu App ID",
        default=current_config.app_id or "",
        type=str,
    )
    current_config.app_id = app_id

    app_secret = click.prompt(
        "Feishu App Secret",
        default=current_config.app_secret or "",
        hide_input=True,
        type=str,
    )
    current_config.app_secret = app_secret

    return current_config


def configure_weixin(current_config: WeixinConfig) -> WeixinConfig:
    """Configure WeChat (iLink Bot) personal account channel interactively.

    ``bot_token`` is intentionally not prompted: it is a short-lived bearer
    token obtained via QR-code login at runtime and persisted to
    ``bot_token_file``. The wizard only collects the surrounding config.
    """
    click.echo("\n=== Configure WeChat (iLink Bot) Channel ===")

    enabled = prompt_confirm(
        "Enable WeChat channel?",
        default=current_config.enabled,
    )

    if not enabled:
        current_config.enabled = False
        return current_config

    current_config.enabled = True

    click.echo(
        "Note: bot_token is obtained via QR-code login at runtime and "
        "persisted to bot_token_file; it is not prompted here.",
    )

    bot_token_file = click.prompt(
        "bot_token file path",
        default=(
            current_config.bot_token_file or "~/.qwenpaw/weixin_bot_token"
        ),
        type=str,
    )
    current_config.bot_token_file = bot_token_file

    base_url = click.prompt(
        "iLink API base URL (leave empty for default)",
        default=current_config.base_url or "",
        type=str,
    )
    current_config.base_url = base_url

    media_dir = click.prompt(
        "Local media download directory (leave empty to disable)",
        default=current_config.media_dir or "",
        type=str,
    )
    current_config.media_dir = media_dir or None

    return current_config


def configure_qq(current_config: QQConfig) -> QQConfig:
    """Configure QQ channel interactively."""
    click.echo("\n=== Configure QQ Channel ===")

    enabled = prompt_confirm(
        "Enable QQ channel?",
        default=current_config.enabled,
    )

    if not enabled:
        current_config.enabled = False
        return current_config

    current_config.enabled = True

    bot_prefix = click.prompt(
        "Bot prefix (e.g., @bot)",
        default=current_config.bot_prefix or "",
        type=str,
    )
    current_config.bot_prefix = bot_prefix

    app_id = click.prompt(
        "QQ App ID",
        default=current_config.app_id or "",
        type=str,
    )
    current_config.app_id = app_id

    client_secret = click.prompt(
        "QQ Client Secret",
        default=current_config.client_secret or "",
        hide_input=True,
        type=str,
    )
    current_config.client_secret = client_secret

    markdown_enabled = prompt_confirm(
        "Enable QQ markdown replies?",
        default=current_config.markdown_enabled,
    )
    current_config.markdown_enabled = markdown_enabled

    return current_config


def configure_telegram(current_config: TelegramConfig) -> TelegramConfig:
    """Configure Telegram channel interactively."""
    click.echo("\n=== Configure Telegram Channel ===")

    enabled = prompt_confirm(
        "Enable Telegram channel?",
        default=current_config.enabled,
    )

    if not enabled:
        current_config.enabled = False
        return current_config

    current_config.enabled = True

    bot_prefix = click.prompt(
        "Bot prefix (e.g., @bot)",
        default=current_config.bot_prefix or "",
        type=str,
    )
    current_config.bot_prefix = bot_prefix

    bot_token = click.prompt(
        "Telegram Bot Token",
        default=current_config.bot_token or "",
        hide_input=True,
        type=str,
    )
    token = bot_token.strip()
    current_config.bot_token = token
    if not token:
        click.echo("Warning: Empty bot token provided.")
        click.echo("Disabling Telegram channel.")
        current_config.enabled = False
        return current_config

    show_typing = prompt_confirm(
        "Show typing indicator?",
        default=current_config.show_typing is not False,
    )
    current_config.show_typing = show_typing

    use_proxy = prompt_confirm(
        "Use HTTP proxy?",
        default=bool(current_config.http_proxy),
    )

    if use_proxy:
        http_proxy = click.prompt(
            "HTTP proxy address (e.g., http://127.0.0.1:7890)",
            default=current_config.http_proxy or "",
            type=str,
        )
        current_config.http_proxy = http_proxy

        use_proxy_auth = prompt_confirm(
            "Does proxy require authentication?",
            default=bool(current_config.http_proxy_auth),
        )

        if use_proxy_auth:
            http_proxy_auth = click.prompt(
                "Proxy authentication (format: username:password)",
                default=current_config.http_proxy_auth or "",
                hide_input=True,
                type=str,
            )
            current_config.http_proxy_auth = http_proxy_auth
        else:
            current_config.http_proxy_auth = ""
    else:
        current_config.http_proxy = ""
        current_config.http_proxy_auth = ""

    return current_config


def configure_voice(
    current_config: VoiceChannelConfig,
) -> VoiceChannelConfig:
    """Configure Twilio voice channel interactively."""
    click.echo("\n=== Configure Twilio Channel ===")

    enabled = prompt_confirm(
        "Enable Twilio channel?",
        default=current_config.enabled,
    )

    if not enabled:
        current_config.enabled = False
        return current_config

    current_config.enabled = True

    # — Twilio credentials —

    twilio_account_sid = click.prompt(
        "Twilio Account SID",
        default=current_config.twilio_account_sid or "",
        type=str,
    )
    current_config.twilio_account_sid = twilio_account_sid

    twilio_auth_token = click.prompt(
        "Twilio Auth Token",
        default=current_config.twilio_auth_token or "",
        hide_input=True,
        type=str,
    )
    current_config.twilio_auth_token = twilio_auth_token

    # — Phone number (may be blank if provisioning later via API) —

    phone_number = click.prompt(
        "Phone number (e.g., +15551234567, blank to provision later)",
        default=current_config.phone_number or "",
        type=str,
    )
    current_config.phone_number = phone_number

    phone_number_sid = click.prompt(
        "Phone Number SID (e.g., PN..., blank to provision later)",
        default=current_config.phone_number_sid or "",
        type=str,
    )
    current_config.phone_number_sid = phone_number_sid

    # — TTS / STT settings —

    configure_tts = prompt_confirm(
        "Configure TTS/STT settings? (default: Google TTS + Deepgram STT)",
        default=False,
    )

    if configure_tts:
        tts_provider = click.prompt(
            "TTS provider",
            default=current_config.tts_provider or "google",
            type=str,
        )
        current_config.tts_provider = tts_provider

        tts_voice = click.prompt(
            "TTS voice",
            default=current_config.tts_voice or "en-US-Journey-D",
            type=str,
        )
        current_config.tts_voice = tts_voice

        stt_provider = click.prompt(
            "STT provider",
            default=current_config.stt_provider or "deepgram",
            type=str,
        )
        current_config.stt_provider = stt_provider

        language = click.prompt(
            "Language",
            default=current_config.language or "en-US",
            type=str,
        )
        current_config.language = language

    # — Welcome greeting —

    welcome_greeting = click.prompt(
        "Welcome greeting",
        default=current_config.welcome_greeting
        or "Hi! This is QwenPaw. How can I help you?",
        type=str,
    )
    current_config.welcome_greeting = welcome_greeting

    return current_config


def configure_console(current_config: ConsoleConfig) -> ConsoleConfig:
    """Configure Console channel interactively."""
    click.echo("\n=== Configure Console Channel ===")

    enabled = prompt_confirm(
        "Enable Console channel?",
        default=current_config.enabled,
    )

    if not enabled:
        current_config.enabled = False
        return current_config

    current_config.enabled = True

    bot_prefix = click.prompt(
        "Bot prefix (e.g., [BOT])",
        default=current_config.bot_prefix or "",
        type=str,
    )
    current_config.bot_prefix = bot_prefix

    return current_config


# ── reusable channel configuration flow (used by init_cmd too) ─────

# Full registry — filtered at runtime by get_channel_configurators().
_ALL_CHANNEL_CONFIGURATORS = {
    "imessage": ("iMessage", configure_imessage),
    "discord": ("Discord", configure_discord),
    "telegram": ("Telegram", configure_telegram),
    "dingtalk": ("DingTalk", configure_dingtalk),
    "feishu": ("Feishu", configure_feishu),
    "weixin": ("WeChat (iLink Bot)", configure_weixin),
    "qq": ("QQ", configure_qq),
    "console": ("Console", configure_console),
    "voice": ("Twilio", configure_voice),
}


def _plugin_configure(
    _key: str,
    configurator,
    current,
):
    """Run plugin configurator; accept/return dict or object."""
    if isinstance(current, dict):
        cur_ns = SimpleNamespace(**current)
    else:
        cur_ns = current
    out = configurator(cur_ns)
    if out is None:
        return current
    if hasattr(out, "__dict__"):
        return vars(out)
    if isinstance(out, dict):
        return out
    return current


def get_channel_configurators() -> dict:
    """Return channel configurators (built-in + plugin get_configurator)."""
    available = get_available_channels()
    registry = get_channel_registry()
    out = {
        k: v for k, v in _ALL_CHANNEL_CONFIGURATORS.items() if k in available
    }

    def _default_plugin_configure(current):
        """Minimal configurator: enabled + bot_prefix."""

        def _get(obj, k, default=None):
            return (
                obj.get(k, default)
                if isinstance(obj, dict)
                else getattr(
                    obj,
                    k,
                    default,
                )
            )

        def _set(obj, k, v):
            if isinstance(obj, dict):
                obj[k] = v
            else:
                setattr(obj, k, v)

        enabled = _get(current, "enabled", False)
        _set(
            current,
            "enabled",
            prompt_confirm("Enable this channel?", default=enabled),
        )
        prefix = _get(current, "bot_prefix", "") or ""
        _set(
            current,
            "bot_prefix",
            click.prompt("Bot prefix (e.g. [BOT])", default=prefix, type=str),
        )
        return current

    for key in available:
        if key in out:
            continue
        ch_cls = registry.get(key)
        if ch_cls is None:
            continue
        display = (
            getattr(ch_cls, "display_name", None)
            or key.replace(
                "_",
                " ",
            ).title()
        )
        configurator = getattr(ch_cls, "get_configurator", None)
        if callable(configurator):
            configurator = configurator()
        if not callable(configurator):
            configurator = _default_plugin_configure

        def _wrap(cf, k=key):
            def _run(current):
                return _plugin_configure(k, cf, current)

            return _run

        out[key] = (display, _wrap(configurator))
    return out


def _get_channel_config(config: Config, key: str):
    """Get channel config for key (from attr or extra)."""
    ch = getattr(config.channels, key, None)
    if ch is not None:
        return ch
    extra = getattr(config.channels, "__pydantic_extra__", None) or {}
    return extra.get(key)


def configure_channels_interactive(config: Config) -> None:
    """Run the interactive channel selection / configuration loop.

    Mutates *config.channels* in-place.
    """
    configurators = get_channel_configurators()
    registry = get_channel_registry()
    click.echo("\n=== Channel Configuration ===")

    while True:
        channel_choices: list[tuple[str, str]] = []
        for channel_key, (channel_name, _) in configurators.items():
            channel_config = _get_channel_config(config, channel_key)
            status = "✓" if _channel_enabled(channel_config) else "✗"
            channel_choices.append(
                (f"{channel_name} [{status}]", channel_key),
            )
        channel_choices.append(("Save and exit", "exit"))

        click.echo()
        choice = prompt_select(
            "Select a channel to configure:",
            options=channel_choices,
        )

        if choice is None:
            click.echo("\n\nOperation cancelled.")
            return

        if choice == "exit":
            break

        channel_name, configure_func = configurators[choice]
        current_config = _get_channel_config(config, choice)
        if current_config is None:
            ch_cls = registry.get(choice)
            default = (
                getattr(ch_cls, "get_default_config", lambda: None)()
                if ch_cls
                else None
            )
            current_config = default or {"enabled": False, "bot_prefix": ""}
        updated_config = configure_func(current_config)
        setattr(config.channels, choice, updated_config)

    # Show enabled channels summary
    enabled_channels = [
        name
        for key, (name, _) in configurators.items()
        if _channel_enabled(_get_channel_config(config, key))
    ]

    if enabled_channels:
        click.echo(
            f"\n✓ Enabled channels: {', '.join(enabled_channels)}",
        )
    else:
        click.echo("\n⚠ Warning: No channels enabled!")


# ── CLI commands ───────────────────────────────────────────────────


@click.group("channels")
def channels_group() -> None:
    """Manage channel configuration
    (iMessage/Discord/DingTalk/Feishu/QQ/Console)."""


def _channel_config_fields(ch):
    """Yield (field_name, value) for a channel config (model or dict)."""
    if hasattr(ch, "model_fields"):
        for fn in ch.model_fields:
            if fn == "enabled":
                continue
            yield (fn, getattr(ch, fn))
    elif isinstance(ch, dict):
        for k, v in ch.items():
            if k == "enabled":
                continue
            yield (k, v)
    elif hasattr(ch, "__dict__"):
        for k, v in vars(ch).items():
            if k == "enabled":
                continue
            yield (k, v)


def _channel_enabled(ch) -> bool:
    """Whether channel config has enabled=True."""
    if ch is None:
        return False
    if hasattr(ch, "enabled"):
        return bool(ch.enabled)
    if isinstance(ch, dict):
        return bool(ch.get("enabled", False))
    return False


@channels_group.command("list")
@click.option(
    "--agent-id",
    default="default",
    help="Agent ID (defaults to 'default')",
)
def list_cmd(agent_id: str) -> None:
    """Show current channel configuration."""
    try:
        agent_config = load_agent_config(agent_id)
        click.echo(f"Channels for agent: {agent_id}\n")

        if not agent_config.channels:
            click.echo("No channels configured for this agent.")
            return

        extra = (
            getattr(agent_config.channels, "__pydantic_extra__", None) or {}
        )
        for key, name in _get_channel_names().items():
            ch = getattr(agent_config.channels, key, None)
            if ch is None:
                ch = extra.get(key)
            if ch is None:
                continue
            status = (
                click.style("enabled", fg="green")
                if _channel_enabled(ch)
                else click.style("disabled", fg="red")
            )
            click.echo(f"\n{'─' * 40}")
            click.echo(f"  {name}  [{status}]")
            click.echo(f"{'─' * 40}")

            for field_name, value in _channel_config_fields(ch):
                display = (
                    _mask(str(value))
                    if field_name in _SECRET_FIELDS
                    else value
                )
                click.echo(f"  {field_name:20s}: {display}")

        click.echo()
    except (ValueError, AppBaseException) as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from e


def _install_channel_to_dir(
    key: str,
    from_path: str | None = None,
    from_url: str | None = None,
) -> None:
    """Write channel module to CUSTOM_CHANNELS_DIR (template or copy)."""
    CUSTOM_CHANNELS_DIR.mkdir(parents=True, exist_ok=True)
    if not key.isidentifier():
        click.echo(
            f"Key must be a valid Python identifier (e.g. my_channel), "
            f"got: {key}",
            err=True,
        )
        raise SystemExit(1)

    dest_file = CUSTOM_CHANNELS_DIR / f"{key}.py"
    dest_dir = CUSTOM_CHANNELS_DIR / key

    if from_path:
        src = Path(from_path).resolve()
        if not src.exists():
            click.echo(f"Path not found: {src}", err=True)
            raise SystemExit(1)
        if src.is_file():
            import shutil

            shutil.copy2(src, dest_file)
            click.echo(f"✓ Installed {key}.py from {src}")
        else:
            import shutil

            if dest_dir.exists():
                shutil.rmtree(dest_dir)
            shutil.copytree(src, dest_dir)
            click.echo(f"✓ Installed {key}/ from {src}")
        return

    if from_url:
        import urllib.request

        try:
            with urllib.request.urlopen(from_url) as resp:
                body = resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            click.echo(f"Failed to fetch URL: {e}", err=True)
            raise SystemExit(1) from e
        dest_file.write_text(body, encoding="utf-8")
        click.echo(f"✓ Installed {key}.py from URL")
        return

    if dest_file.exists() or dest_dir.exists():
        click.echo(
            f"Channel '{key}' already exists in {CUSTOM_CHANNELS_DIR}. "
            "Edit the file or use --path/--url to overwrite.",
            err=True,
        )
        raise SystemExit(1)

    dest_file.write_text(
        CHANNEL_TEMPLATE.format(key=key),
        encoding="utf-8",
    )
    click.echo(
        f"✓ Created {dest_file}. Edit and add config with "
        "`qwenpaw channels config`.",
    )


@channels_group.command("install")
@click.argument("key", required=True)
@click.option(
    "--path",
    "from_path",
    type=click.Path(exists=True),
    help="Copy channel from local path (file or dir).",
)
@click.option(
    "--url",
    "from_url",
    type=str,
    help="Download channel module from URL (.py file).",
)
def install_cmd(key: str, from_path: str | None, from_url: str | None) -> None:
    """Install a channel into the working dir (custom_channels/). Creates a
    stub module you can edit, or use --path/--url to copy from elsewhere.
    Manager loads channels from this directory at runtime.
    """
    _install_channel_to_dir(key, from_path=from_path, from_url=from_url)


@channels_group.command("add")
@click.argument("key", required=True)
@click.option(
    "--path",
    "from_path",
    type=click.Path(exists=True),
    help="Copy channel from local path (file or dir).",
)
@click.option(
    "--url",
    "from_url",
    type=str,
    help="Download channel module from URL (.py file).",
)
@click.option(
    "--configure/--no-configure",
    default=True,
    help="Run interactive configurator after adding to config.",
)
def add_cmd(
    key: str,
    from_path: str | None,
    from_url: str | None,
    configure: bool,
) -> None:
    """Install channel to custom_channels/ and add to config. For built-in
    channels only adds to config; for custom, installs (stub or --path/--url)
    then adds to config.
    """
    dest_file = CUSTOM_CHANNELS_DIR / f"{key}.py"
    dest_dir = CUSTOM_CHANNELS_DIR / key
    already_in_dir = dest_file.exists() or dest_dir.exists()
    is_builtin = key in BUILTIN_CHANNEL_KEYS

    if not is_builtin and (from_path or from_url or not already_in_dir):
        _install_channel_to_dir(key, from_path=from_path, from_url=from_url)

    config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    existing = load_config(config_path) if config_path.is_file() else Config()
    current = _get_channel_config(existing, key)

    if current is None:
        default = {"enabled": False, "bot_prefix": ""}
        setattr(existing.channels, key, default)
        if configure:
            configurators = get_channel_configurators()
            if key in configurators:
                _, configure_func = configurators[key]
                updated = configure_func(default)
                setattr(existing.channels, key, updated)
        save_config(existing, config_path)
        click.echo(f"✓ Added '{key}' to config at {config_path}")


@channels_group.command("remove")
@click.argument("key", required=True)
@click.option(
    "--keep-config/--no-keep-config",
    "keep_config",
    default=False,
    help="Keep the channel entry in config.json (only remove the module).",
)
def remove_cmd(key: str, keep_config: bool) -> None:
    """Remove a custom channel from custom_channels/. Built-in channels
    cannot be removed.
    """
    if key in BUILTIN_CHANNEL_KEYS:
        click.echo(
            f"'{key}' is a built-in channel and cannot be removed. "
            "Disable it in config instead.",
            err=True,
        )
        raise SystemExit(1)

    dest_file = CUSTOM_CHANNELS_DIR / f"{key}.py"
    dest_dir = CUSTOM_CHANNELS_DIR / key
    if not dest_file.exists() and not dest_dir.exists():
        click.echo(
            f"Channel '{key}' not found in {CUSTOM_CHANNELS_DIR}.",
            err=True,
        )
        raise SystemExit(1)

    import shutil

    if dest_file.exists():
        dest_file.unlink()
    else:
        shutil.rmtree(dest_dir)
    click.echo(f"✓ Removed channel '{key}' from {CUSTOM_CHANNELS_DIR}.")

    if not keep_config:
        config_path = get_config_path()
        if config_path.is_file():
            cfg = load_config(config_path)
            data = cfg.model_dump()
            ch_data = data.get("channels") or {}
            if key in ch_data:
                del ch_data[key]
                new_cfg = Config.model_validate(data)
                save_config(new_cfg, config_path)
                click.echo(f"✓ Removed '{key}' from config.")


@channels_group.command("config")
@click.option(
    "--agent-id",
    default="default",
    help="Agent ID (defaults to 'default')",
)
def configure_cmd(agent_id: str) -> None:
    """Interactively configure channels."""
    try:
        agent_config = load_agent_config(agent_id)
        click.echo(f"Configuring channels for agent: {agent_id}\n")

        # Create a temporary Config object for the interactive configurator
        temp_config = Config()
        temp_config.channels = (
            agent_config.channels
            if agent_config.channels
            else temp_config.channels
        )

        configure_channels_interactive(temp_config)

        # Save back to agent config
        agent_config.channels = temp_config.channels
        save_agent_config(agent_id, agent_config)
        click.echo(f"\n✓ Configuration saved for agent {agent_id}")
    except (ValueError, AppBaseException) as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from e


@channels_group.command("send")
@click.option(
    "--agent-id",
    required=True,
    help="Agent ID sending the message",
)
@click.option(
    "--channel",
    required=True,
    help=(
        "Target channel (e.g., console, dingtalk, feishu, discord, "
        "imessage, qq)"
    ),
)
@click.option(
    "--target-user",
    required=True,
    help=("Target user ID (REQUIRED, get from 'qwenpaw chats list' query)"),
)
@click.option(
    "--target-session",
    required=True,
    help=("Target session ID (REQUIRED, get from 'qwenpaw chats list' query)"),
)
@click.option(
    "--text",
    required=True,
    help="Text message to send",
)
@click.option(
    "--base-url",
    default=None,
    help="Override the API base URL. Defaults to global --host/--port.",
)
@click.pass_context
def send_cmd(
    ctx: click.Context,
    agent_id: str,
    channel: str,
    target_user: str,
    target_session: str,
    text: str,
    base_url: Optional[str],
) -> None:
    """Send a text message to a channel.

    This command allows an agent to proactively send messages to users
    via configured channels (console, dingtalk, feishu, etc.).

    IMPORTANT: All 5 parameters are REQUIRED. You MUST query first to get
    valid target-user and target-session values.

    \b
    Complete Usage Flow:
      Step 1 - Query available sessions (REQUIRED):
        qwenpaw chats list --agent-id my_bot --channel console

      Step 2 - Extract parameters from query output:
        user_id: "alice"
        session_id: "alice_session_001"

      Step 3 - Send message using queried parameters:
        qwenpaw channels send --agent-id my_bot --channel console \\
          --target-user alice --target-session alice_session_001 \\
          --text "Hello!"

    \b
    Examples with jq automation:
      # Query and auto-extract parameters
      SESSIONS=$(qwenpaw chats list --agent-id bot --channel console)
      USER=$(echo "$SESSIONS" | jq -r '.[0].user_id')
      SESSION=$(echo "$SESSIONS" | jq -r '.[0].session_id')

      # Send message
      qwenpaw channels send --agent-id bot --channel console \\
        --target-user "$USER" --target-session "$SESSION" \\
        --text "Automated notification"

    \b
    Prerequisites:
      1. MUST use 'qwenpaw chats list' to get valid target-user and
         target-session
      2. Ensure the channel is properly configured
      3. All 5 parameters are required (no defaults)

    \b
    Returns:
      JSON response with success status and message details.
    """
    base_url = resolve_base_url(ctx, base_url)

    payload = {
        "channel": channel,
        "target_user": target_user,
        "target_session": target_session,
        "text": text,
    }

    with client(base_url) as c:
        headers = {"X-Agent-Id": agent_id}
        r = c.post("/messages/send", json=payload, headers=headers)
        r.raise_for_status()
        print_json(r.json())
