# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,unused-argument
# pylint: disable=use-implicit-booleaness-not-comparison
# ^ C1803 kept on purpose: ``calls == []`` asserts the exact empty list.
#   ``not calls`` would also accept ``None`` and thereby weaken the
#   assertion.  Upstream keeps the same convention in its test files.
"""Unit tests for the interactive channel configurators in the CLI.

Coverage-driven backfill.  The three existing files already cover:

* ``test_channels_cmd.py``      -- plugin configurator lookup, and that
  ``configure_channels_interactive`` loads plugins before building the
  menu;
* ``test_channels_cmd_commands.py`` -- ``list_cmd`` rendering/masking and
  ``configure_cmd`` save-back plus error handling;
* ``test_channels_cmd_helpers.py``  -- ``_mask``, ``_channel_enabled``,
  ``_channel_config_fields``, ``_get_channel_names``,
  ``get_channel_configurators`` filtering.

What they all leave out is the body of the nine ``configure_*`` wizards
(189 uncovered statements) plus ``_plugin_configure``, the plugin-loading
guard and the interactive loop itself.  Those are the code paths a user
actually walks through during ``qwenpaw configure``.

The assertions below are about observable behaviour, not implementation:
which fields end up with which value, which prompts were asked, whether
secrets were asked with ``hide_input``, what was echoed, and whether the
returned object is the same instance the caller passed in (the callers
mutate in place and rely on that).

🔴 Every scripted answer list is asserted to be *fully consumed*.  A test
that stops early (because a prompt sequence changed, or because a branch
was taken that was not intended) would otherwise still pass while
covering nothing.
"""
from __future__ import annotations

from types import SimpleNamespace

import click
import pytest

import qwenpaw.cli.channels_cmd as cc
from qwenpaw.config.config import (
    Config,
    ConsoleConfig,
    DingTalkConfig,
    DiscordConfig,
    FeishuConfig,
    IMessageChannelConfig,
    QQConfig,
    TelegramConfig,
    VoiceChannelConfig,
    WeChatConfig,
)

# Prompt texts whose answers are credentials.  Asking for one of these
# without ``hide_input`` would leave the secret in the terminal scrollback.
_SECRET_HINTS = ("Token", "Secret")


class _Recorder:
    """Collect what the configurators asked for, and hand back answers."""

    def __init__(self, confirms, texts, paths, selects):
        self.confirm_answers = list(confirms)
        self.text_answers = list(texts)
        self.path_answers = list(paths)
        self.select_answers = list(selects)
        self.confirms = []
        self.prompts = []
        self.paths = []
        self.selects = []
        self.echoes = []

    # -- scripted prompt implementations -------------------------------
    def confirm(self, question, *, default=False):
        self.confirms.append((question, default))
        if not self.confirm_answers:
            raise AssertionError(f"unscripted confirm: {question!r}")
        return self.confirm_answers.pop(0)

    def prompt(self, text, **kwargs):
        self.prompts.append((text, kwargs))
        if not self.text_answers:
            raise AssertionError(f"unscripted prompt: {text!r}")
        return self.text_answers.pop(0)

    def path(self, label, *, default=""):
        self.paths.append((label, default))
        if not self.path_answers:
            raise AssertionError(f"unscripted path prompt: {label!r}")
        return self.path_answers.pop(0)

    def select(self, question, options=None, **kwargs):
        self.selects.append((question, options))
        if not self.select_answers:
            raise AssertionError(f"unscripted select: {question!r}")
        return self.select_answers.pop(0)

    def echo(self, *args, **kwargs):
        self.echoes.append(args[0] if args else "")

    # -- assertions ----------------------------------------------------
    def assert_fully_consumed(self):
        """No scripted answer may be left over."""
        leftover = (
            self.confirm_answers
            + self.text_answers
            + self.path_answers
            + self.select_answers
        )
        assert leftover == [], f"unused scripted answers: {leftover!r}"

    def prompt_texts(self):
        return [text for text, _ in self.prompts]

    def assert_secrets_hidden(self):
        """Every credential prompt must be asked with ``hide_input``."""
        checked = 0
        for text, kwargs in self.prompts:
            if any(hint in text for hint in _SECRET_HINTS):
                assert kwargs.get("hide_input") is True, text
                checked += 1
        assert checked > 0, "no secret prompt was asked at all"

    def joined_echoes(self):
        return "\n".join(str(e) for e in self.echoes)


@pytest.fixture()
def io(monkeypatch):
    """Install a fully scripted stand-in for the interactive primitives.

    ``cc.click`` is replaced wholesale (rather than patching the real
    ``click`` module attribute) so nothing leaks into other tests in the
    same worker.  ``Choice`` is delegated to the real click so the tests
    can still inspect the offered options.
    """
    rec = _Recorder([], [], [], [])
    fake_click = SimpleNamespace(
        prompt=rec.prompt,
        echo=rec.echo,
        Choice=click.Choice,
    )
    monkeypatch.setattr(cc, "click", fake_click)
    monkeypatch.setattr(cc, "prompt_confirm", rec.confirm)
    monkeypatch.setattr(cc, "prompt_path", rec.path)
    monkeypatch.setattr(cc, "prompt_select", rec.select)

    def script(confirms=(), texts=(), paths=(), selects=()):
        rec.confirm_answers = list(confirms)
        rec.text_answers = list(texts)
        rec.path_answers = list(paths)
        rec.select_answers = list(selects)
        return rec

    return script


# ---------------------------------------------------------------------------
# iMessage
# ---------------------------------------------------------------------------


class TestConfigureIMessage:
    def test_declining_disables_and_asks_nothing_more(self, io):
        rec = io(confirms=[False])
        cfg = IMessageChannelConfig(enabled=True, bot_prefix="@old")

        out = cc.configure_imessage(cfg)

        assert out is cfg
        assert out.enabled is False
        assert out.bot_prefix == "@old"  # untouched on the decline path
        rec.assert_fully_consumed()

    def test_full_wizard_writes_every_field(self, io, tmp_path):
        db = tmp_path / "chat.db"
        db.write_text("stub", encoding="utf-8")
        rec = io(confirms=[True], texts=["@bot", 2.5], paths=[str(db)])
        cfg = IMessageChannelConfig()

        out = cc.configure_imessage(cfg)

        assert out.enabled is True
        assert out.bot_prefix == "@bot"
        assert out.db_path == str(db)
        assert out.poll_sec == 2.5
        rec.assert_fully_consumed()
        # prompt_path (not click.prompt) owns the filesystem question
        assert rec.paths and "iMessage database path" in rec.paths[0][0]
        assert "iMessage" in rec.joined_echoes()

    def test_existing_db_path_is_offered_as_default(self, io):
        rec = io(confirms=[True], texts=["@b", 9.0], paths=["/kept"])

        cc.configure_imessage(
            IMessageChannelConfig(db_path="/elsewhere/chat.db"),
        )

        assert rec.paths[0][1] == "/elsewhere/chat.db"
        rec.assert_fully_consumed()


# ---------------------------------------------------------------------------
# Discord
# ---------------------------------------------------------------------------


class TestConfigureDiscord:
    def test_declining_disables(self, io):
        rec = io(confirms=[False])
        cfg = DiscordConfig(enabled=True, bot_token="secret")

        out = cc.configure_discord(cfg)

        assert out.enabled is False
        assert out.bot_token == "secret"  # not wiped by declining
        rec.assert_fully_consumed()

    def test_no_proxy_clears_both_proxy_fields(self, io):
        rec = io(
            confirms=[True, False, False],
            texts=["@bot", "tok-123"],
        )
        cfg = DiscordConfig(
            http_proxy="http://old:7890",
            http_proxy_auth="user:pass",
        )

        out = cc.configure_discord(cfg)

        assert out.http_proxy == ""
        assert out.http_proxy_auth == ""
        rec.assert_fully_consumed()

    def test_proxy_without_auth_clears_only_the_auth(self, io):
        rec = io(
            confirms=[True, True, False, False],
            texts=["@bot", "tok", "http://proxy:1080"],
        )
        cfg = DiscordConfig(http_proxy_auth="stale:creds")

        out = cc.configure_discord(cfg)

        assert out.http_proxy == "http://proxy:1080"
        assert out.http_proxy_auth == ""
        rec.assert_fully_consumed()
        rec.assert_secrets_hidden()

    def test_proxy_with_auth_keeps_both(self, io):
        rec = io(
            confirms=[True, True, True, True],
            texts=["@bot", "tok", "http://proxy:1080", "u:p"],
        )

        out = cc.configure_discord(DiscordConfig())

        assert out.enabled is True
        assert out.bot_prefix == "@bot"
        assert out.bot_token == "tok"
        assert out.http_proxy == "http://proxy:1080"
        assert out.http_proxy_auth == "u:p"
        assert out.streaming_enabled is True
        rec.assert_fully_consumed()
        rec.assert_secrets_hidden()


# ---------------------------------------------------------------------------
# DingTalk / Feishu / QQ / Console
# ---------------------------------------------------------------------------


class TestConfigureDingTalk:
    def test_declining_disables(self, io):
        rec = io(confirms=[False])

        out = cc.configure_dingtalk(DingTalkConfig(enabled=True))

        assert out.enabled is False
        rec.assert_fully_consumed()

    def test_credentials_and_streaming_are_written(self, io):
        rec = io(
            confirms=[True, True],
            texts=["@bot", "client-id", "client-secret"],
        )

        out = cc.configure_dingtalk(DingTalkConfig())

        assert out.client_id == "client-id"
        assert out.client_secret == "client-secret"
        assert out.streaming_enabled is True
        rec.assert_fully_consumed()
        rec.assert_secrets_hidden()


class TestConfigureFeishu:
    def test_declining_disables(self, io):
        rec = io(confirms=[False])

        out = cc.configure_feishu(FeishuConfig(enabled=True))

        assert out.enabled is False
        rec.assert_fully_consumed()

    def test_blank_domain_offers_feishu_as_default_choice(self, io):
        rec = io(
            confirms=[True, False],
            texts=["feishu", "@bot", "app-id", "app-secret"],
        )

        out = cc.configure_feishu(FeishuConfig())

        assert out.domain == "feishu"
        assert out.app_id == "app-id"
        assert out.app_secret == "app-secret"
        assert out.streaming_enabled is False
        rec.assert_fully_consumed()
        # The region question is a two-option choice, not free text.
        region_kwargs = rec.prompts[0][1]
        assert isinstance(region_kwargs.get("type"), click.Choice)
        assert list(region_kwargs["type"].choices) == ["feishu", "lark"]
        rec.assert_secrets_hidden()

    def test_existing_lark_domain_is_preserved_as_default(self, io):
        rec = io(
            confirms=[True, True],
            texts=["lark", "@bot", "id", "sec"],
        )

        out = cc.configure_feishu(FeishuConfig(domain="lark"))

        assert out.domain == "lark"
        rec.assert_fully_consumed()


class TestConfigureQQ:
    def test_declining_disables(self, io):
        rec = io(confirms=[False])

        out = cc.configure_qq(QQConfig(enabled=True))

        assert out.enabled is False
        rec.assert_fully_consumed()

    def test_markdown_toggle_is_written(self, io):
        rec = io(
            confirms=[True, True],
            texts=["@bot", "app-id", "qq-secret"],
        )

        out = cc.configure_qq(QQConfig(markdown_enabled=False))

        assert out.app_id == "app-id"
        assert out.client_secret == "qq-secret"
        assert out.markdown_enabled is True
        rec.assert_fully_consumed()
        rec.assert_secrets_hidden()


class TestConfigureConsole:
    def test_declining_disables(self, io):
        rec = io(confirms=[False])

        out = cc.configure_console(ConsoleConfig(enabled=True))

        assert out.enabled is False
        rec.assert_fully_consumed()

    def test_prefix_is_written(self, io):
        rec = io(confirms=[True], texts=["[BOT]"])

        out = cc.configure_console(ConsoleConfig())

        assert out.enabled is True
        assert out.bot_prefix == "[BOT]"
        rec.assert_fully_consumed()


# ---------------------------------------------------------------------------
# WeChat (iLink Bot)
# ---------------------------------------------------------------------------


class TestConfigureWeChat:
    def test_declining_disables(self, io):
        rec = io(confirms=[False])

        out = cc.configure_wechat(WeChatConfig(enabled=True))

        assert out.enabled is False
        rec.assert_fully_consumed()

    def test_bot_token_is_never_prompted(self, io):
        """The token comes from QR login, so asking for it would be wrong."""
        rec = io(confirms=[True], texts=["~/tok", "", ""])

        out = cc.configure_wechat(WeChatConfig())

        asked = rec.prompt_texts()
        assert not any("Token" in text for text in asked)
        assert out.bot_token_file == "~/tok"
        assert out.base_url == ""
        # An empty media directory means "disabled", stored as None.
        assert out.media_dir is None
        assert "QR-code login" in rec.joined_echoes()
        rec.assert_fully_consumed()

    def test_media_dir_is_kept_when_given(self, io):
        rec = io(confirms=[True], texts=["~/tok", "https://ilink", "/media"])

        out = cc.configure_wechat(WeChatConfig())

        assert out.base_url == "https://ilink"
        assert out.media_dir == "/media"
        rec.assert_fully_consumed()

    def test_existing_token_file_is_offered_as_default(self, io):
        rec = io(confirms=[True], texts=["/kept", "", ""])

        cc.configure_wechat(WeChatConfig(bot_token_file="/kept"))

        assert rec.prompts[0][1].get("default") == "/kept"
        rec.assert_fully_consumed()


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------


class TestConfigureTelegram:
    def test_declining_disables(self, io):
        rec = io(confirms=[False])

        out = cc.configure_telegram(TelegramConfig(enabled=True))

        assert out.enabled is False
        rec.assert_fully_consumed()

    def test_blank_token_disables_the_channel_again(self, io):
        """A whitespace-only token must not produce a half-enabled channel."""
        rec = io(confirms=[True], texts=["@bot", "   "])

        out = cc.configure_telegram(TelegramConfig(enabled=True))

        assert out.bot_token == ""
        assert out.enabled is False
        echoed = rec.joined_echoes()
        assert "Empty bot token" in echoed
        assert "Disabling Telegram channel" in echoed
        rec.assert_fully_consumed()
        # base_url / typing / proxy / streaming are never reached
        assert len(rec.confirms) == 1
        rec.assert_secrets_hidden()

    def test_base_url_trailing_slash_is_stripped(self, io):
        rec = io(
            confirms=[True, True, False, False],
            texts=["@bot", "tok", "https://api.example.org/bot//"],
        )

        out = cc.configure_telegram(TelegramConfig())

        assert out.base_url == "https://api.example.org/bot"
        assert out.show_typing is True
        assert out.http_proxy == ""
        assert out.http_proxy_auth == ""
        rec.assert_fully_consumed()

    def test_typing_indicator_defaults_to_on_when_unset(self, io):
        rec = io(
            confirms=[True, False, False, False],
            texts=["@bot", "tok", ""],
        )

        cc.configure_telegram(TelegramConfig(show_typing=None))

        # the confirm default is "show typing unless explicitly False"
        typing_default = rec.confirms[1][1]
        assert typing_default is True
        rec.assert_fully_consumed()

    def test_proxy_with_auth(self, io):
        rec = io(
            confirms=[True, True, True, True, False],
            texts=["@bot", "tok", "", "http://p:1", "u:p"],
        )

        out = cc.configure_telegram(TelegramConfig())

        assert out.http_proxy == "http://p:1"
        assert out.http_proxy_auth == "u:p"
        assert out.streaming_enabled is False
        rec.assert_fully_consumed()
        rec.assert_secrets_hidden()

    def test_proxy_without_auth_clears_only_the_auth(self, io):
        """use-proxy = yes, proxy-auth = no."""
        rec = io(
            confirms=[True, True, True, False, False],
            texts=["@bot", "tok", "", "http://p:3"],
        )

        out = cc.configure_telegram(TelegramConfig())

        assert out.http_proxy == "http://p:3"
        assert out.http_proxy_auth == ""
        assert out.streaming_enabled is False
        rec.assert_fully_consumed()

    def test_existing_proxy_values_are_the_defaults(self, io):
        rec = io(
            confirms=[True, True, True, True, True],
            texts=["@bot", "tok", "", "http://p:2", "u2:p2"],
        )

        cc.configure_telegram(
            TelegramConfig(http_proxy="http://p:2", http_proxy_auth="u2:p2"),
        )

        proxy_prompt = rec.prompts[3]
        auth_prompt = rec.prompts[4]
        assert proxy_prompt[1].get("default") == "http://p:2"
        assert auth_prompt[1].get("default") == "u2:p2"
        rec.assert_fully_consumed()


# ---------------------------------------------------------------------------
# Twilio voice
# ---------------------------------------------------------------------------


class TestConfigureVoice:
    def test_declining_disables(self, io):
        rec = io(confirms=[False])

        out = cc.configure_voice(VoiceChannelConfig(enabled=True))

        assert out.enabled is False
        rec.assert_fully_consumed()

    def test_tts_section_can_be_skipped(self, io):
        """Skipping must leave the provider defaults untouched."""
        rec = io(
            confirms=[True, False],
            texts=["sid", "auth-token", "+15551234567", "PN123", "Hello"],
        )
        cfg = VoiceChannelConfig()
        before = (cfg.tts_provider, cfg.tts_voice, cfg.stt_provider)

        out = cc.configure_voice(cfg)

        assert (out.tts_provider, out.tts_voice, out.stt_provider) == before
        assert out.twilio_account_sid == "sid"
        assert out.twilio_auth_token == "auth-token"
        assert out.phone_number == "+15551234567"
        assert out.phone_number_sid == "PN123"
        assert out.welcome_greeting == "Hello"
        rec.assert_fully_consumed()
        rec.assert_secrets_hidden()

    def test_tts_section_overrides_every_setting(self, io):
        rec = io(
            confirms=[True, True],
            texts=[
                "sid",
                "auth",
                "",
                "",
                "azure",
                "zh-CN-Xiaoxiao",
                "whisper",
                "zh-CN",
                "Hi there",
            ],
        )

        out = cc.configure_voice(VoiceChannelConfig())

        assert out.tts_provider == "azure"
        assert out.tts_voice == "zh-CN-Xiaoxiao"
        assert out.stt_provider == "whisper"
        assert out.language == "zh-CN"
        assert out.welcome_greeting == "Hi there"
        # blank phone fields stay blank: provisioning happens later via API
        assert out.phone_number == ""
        assert out.phone_number_sid == ""
        rec.assert_fully_consumed()

    def test_existing_voice_values_are_the_defaults(self, io):
        rec = io(
            confirms=[True, True],
            texts=["sid", "auth", "+1", "PN", "p", "v", "s", "en", "g"],
        )

        cc.configure_voice(
            VoiceChannelConfig(
                twilio_account_sid="sid",
                tts_voice="v",
                language="en",
                welcome_greeting="g",
            ),
        )

        by_text = dict(rec.prompts)
        assert by_text["TTS voice"].get("default") == "v"
        assert by_text["Language"].get("default") == "en"
        assert by_text["Welcome greeting"].get("default") == "g"
        rec.assert_fully_consumed()


# ---------------------------------------------------------------------------
# _plugin_configure
# ---------------------------------------------------------------------------


class TestPluginConfigure:
    def test_dict_input_is_presented_as_a_namespace(self):
        seen = []

        def configurator(namespace):
            seen.append(namespace)

        out = cc._plugin_configure("k", configurator, {"enabled": False})

        assert isinstance(seen[0], SimpleNamespace)
        assert seen[0].enabled is False
        # returning None means "I did not build a new object"
        assert out == {"enabled": False}

    def test_object_input_is_passed_through_untouched(self):
        current = SimpleNamespace(enabled=True, bot_prefix="@x")
        seen = []

        def configurator(namespace):
            seen.append(namespace)

        out = cc._plugin_configure("k", configurator, current)

        assert seen[0] is current
        assert out is current

    def test_object_output_is_flattened_to_a_dict(self):
        def configurator(namespace):
            namespace.bot_prefix = "@new"
            return namespace

        out = cc._plugin_configure("k", configurator, {"bot_prefix": "@old"})

        assert out == {"bot_prefix": "@new"}

    def test_dict_output_is_returned_as_is(self):
        def configurator(namespace):
            return {"enabled": True, "extra": 1}

        out = cc._plugin_configure("k", configurator, SimpleNamespace())

        assert out == {"enabled": True, "extra": 1}

    def test_plain_value_output_falls_back_to_the_original(self):
        """A misbehaving plugin returning ``42`` must not corrupt config."""
        current = {"enabled": False}

        out = cc._plugin_configure("k", lambda ns: 42, current)

        assert out is current


# ---------------------------------------------------------------------------
# _load_channel_plugins_for_cli
# ---------------------------------------------------------------------------


class TestLoadChannelPluginsForCli:
    def test_second_call_is_a_noop(self, monkeypatch):
        """The guard means the plugin loader runs at most once per process."""
        monkeypatch.setattr(cc, "_CLI_CHANNEL_PLUGINS_LOADED", True)
        calls = []
        monkeypatch.setattr(cc, "load_config", lambda: calls.append("config"))
        monkeypatch.setattr(
            cc,
            "PluginLoader",
            lambda *a, **k: calls.append("loader"),
        )

        cc._load_channel_plugins_for_cli()

        assert calls == []

    def test_first_call_loads_and_sets_the_guard(self, monkeypatch):
        calls = []
        monkeypatch.setattr(cc, "_CLI_CHANNEL_PLUGINS_LOADED", False)
        monkeypatch.setattr(
            cc,
            "load_config",
            lambda: SimpleNamespace(plugins={"sentinel": {}}),
        )
        monkeypatch.setattr(cc, "get_plugins_dir", lambda: "/plugins")

        loader = SimpleNamespace(
            registry=SimpleNamespace(
                set_plugin_http_app=lambda app: calls.append(("app", app)),
            ),
            load_all_plugins=lambda **kwargs: calls.append(
                ("load", kwargs),
            ),
        )
        monkeypatch.setattr(cc, "PluginLoader", lambda dirs: loader)
        monkeypatch.setattr(
            cc,
            "FastAPI",
            lambda: calls.append(("fastapi",)) or "APP",
        )
        monkeypatch.setattr(cc.asyncio, "run", lambda coro: coro)

        cc._load_channel_plugins_for_cli()

        assert cc._CLI_CHANNEL_PLUGINS_LOADED is True
        kinds = [entry[0] for entry in calls]
        assert kinds == ["fastapi", "app", "load"]
        load_kwargs = calls[-1][1]
        assert load_kwargs["types"] == ["channel"]
        # the persisted plugin config is what gets loaded, not a fresh one
        assert load_kwargs["configs"] == {"sentinel": {}}


# ---------------------------------------------------------------------------
# get_channel_configurators: the default plugin configurator
# ---------------------------------------------------------------------------


class TestDefaultPluginConfigure:
    @staticmethod
    def _install(monkeypatch, channel_class):
        monkeypatch.setattr(cc, "get_available_channels", lambda: ["plug"])
        monkeypatch.setattr(
            cc,
            "get_channel_registry",
            lambda: {"plug": channel_class},
        )
        return cc.get_channel_configurators()["plug"]

    def test_object_config_is_mutated_then_flattened(self, monkeypatch, io):
        """The fallback asks enabled + bot_prefix, and the answer comes back
        as a plain dict.

        Note the layering: ``_default_plugin_configure`` mutates the object
        it was handed, but ``_plugin_configure`` flattens *any* return value
        that has ``__dict__`` via ``vars()``.  So callers of the wrapped
        configurator always see a dict for this path -- asserted here
        because ``configure_channels_interactive`` then does
        ``setattr(config.channels, key, result)``, and a dict is what ends
        up in the pydantic extra.
        """

        class Channel:
            display_name = "Plug Display"

            @staticmethod
            def get_configurator():
                return None  # forces the minimal fallback configurator

        rec = io(confirms=[True], texts=["[PLUG]"])
        display, configure = self._install(monkeypatch, Channel)
        current = SimpleNamespace(enabled=False, bot_prefix="")

        out = configure(current)

        assert display == "Plug Display"
        assert out == {"enabled": True, "bot_prefix": "[PLUG]"}
        # the object handed in was mutated too (same values)
        assert current.enabled is True
        assert current.bot_prefix == "[PLUG]"
        rec.assert_fully_consumed()

    def test_dict_config_is_mutated_in_place(self, monkeypatch, io):
        class Channel:
            pass  # no display_name, no get_configurator

        rec = io(confirms=[True], texts=["[D]"])
        display, configure = self._install(monkeypatch, Channel)
        current = {"enabled": False, "bot_prefix": ""}

        out = configure(current)

        assert display == "Plug"  # key derived title
        assert out == {"enabled": True, "bot_prefix": "[D]"}
        rec.assert_fully_consumed()

    def test_declining_still_asks_for_the_prefix(self, monkeypatch, io):
        """Measured truth: the minimal fallback has no decline short-circuit.

        Unlike the nine built-in ``configure_*`` wizards, which return as
        soon as the user answers "No", ``_default_plugin_configure`` always
        asks the bot prefix afterwards.  A non-callable ``get_configurator``
        return value still selects this fallback.
        """

        class Channel:
            @staticmethod
            def get_configurator():
                return "not-callable"

        rec = io(confirms=[False], texts=["@keep"])
        _, configure = self._install(monkeypatch, Channel)

        out = configure({"enabled": True, "bot_prefix": "@old"})

        assert out == {"enabled": False, "bot_prefix": "@keep"}
        assert rec.prompt_texts() == ["Bot prefix (e.g. [BOT])"]
        # the previous prefix was offered as the default
        assert rec.prompts[0][1].get("default") == "@old"
        rec.assert_fully_consumed()


# ---------------------------------------------------------------------------
# configure_channels_interactive
# ---------------------------------------------------------------------------


class TestConfigureChannelsInteractive:
    @staticmethod
    def _install(monkeypatch, configurators, registry=None):
        monkeypatch.setattr(cc, "_load_channel_plugins_for_cli", lambda: None)
        monkeypatch.setattr(
            cc,
            "get_channel_configurators",
            lambda: dict(configurators),
        )
        monkeypatch.setattr(
            cc,
            "get_channel_registry",
            lambda: dict(registry or {}),
        )

    def test_cancelling_the_menu_returns_without_saving(
        self,
        monkeypatch,
        io,
    ):
        rec = io(selects=[None])
        self._install(
            monkeypatch,
            {"console": ("Console", lambda cur: cur)},
        )
        cfg = Config()

        cc.configure_channels_interactive(cfg)

        assert "Operation cancelled" in rec.joined_echoes()
        assert rec.selects, "the menu was never shown"
        rec.assert_fully_consumed()

    def test_exiting_with_nothing_enabled_warns(self, monkeypatch, io):
        rec = io(selects=["exit"])
        self._install(
            monkeypatch,
            {"ghost": ("Ghost", lambda cur: cur)},
        )
        cfg = Config()
        cfg.channels.console.enabled = False

        cc.configure_channels_interactive(cfg)

        echoed = rec.joined_echoes()
        assert "No channels enabled" in echoed
        rec.assert_fully_consumed()

    def test_menu_shows_a_tick_for_an_enabled_channel(self, monkeypatch, io):
        rec = io(selects=["exit"])
        self._install(
            monkeypatch,
            {"console": ("Console", lambda cur: cur)},
        )
        cfg = Config()
        cfg.channels.console.enabled = True

        cc.configure_channels_interactive(cfg)

        question, options = rec.selects[0]
        assert question == "Select a channel to configure:"
        labels = dict((value, label) for label, value in options)
        assert labels["console"].endswith("[✓]")
        assert labels["exit"] == "Save and exit"
        assert "Enabled channels: Console" in rec.joined_echoes()
        rec.assert_fully_consumed()

    def test_unknown_channel_falls_back_to_a_dict_config(
        self,
        monkeypatch,
        io,
    ):
        seen = []

        def configure(current):
            seen.append(current)
            return {"enabled": True, "bot_prefix": "@made"}

        rec = io(selects=["ghost", "exit"])
        self._install(monkeypatch, {"ghost": ("Ghost", configure)})
        cfg = Config()

        cc.configure_channels_interactive(cfg)

        assert seen == [{"enabled": False, "bot_prefix": ""}]
        extra = getattr(cfg.channels, "__pydantic_extra__", None) or {}
        assert extra["ghost"] == {"enabled": True, "bot_prefix": "@made"}
        assert "Enabled channels: Ghost" in rec.joined_echoes()
        rec.assert_fully_consumed()

    def test_registry_default_config_is_used_when_available(
        self,
        monkeypatch,
        io,
    ):
        seen = []

        def configure(current):
            seen.append(current)
            return current

        class Channel:
            @staticmethod
            def get_default_config():
                return {"enabled": True, "bot_prefix": "@from-registry"}

        rec = io(selects=["plug", "exit"])
        self._install(
            monkeypatch,
            {"plug": ("Plug", configure)},
            registry={"plug": Channel},
        )
        cfg = Config()

        cc.configure_channels_interactive(cfg)

        assert seen == [{"enabled": True, "bot_prefix": "@from-registry"}]
        rec.assert_fully_consumed()

    def test_existing_channel_config_is_passed_to_its_configurator(
        self,
        monkeypatch,
        io,
    ):
        seen = []

        def configure(current):
            seen.append(current)
            return current

        rec = io(selects=["console", "exit"])
        self._install(monkeypatch, {"console": ("Console", configure)})
        cfg = Config()
        cfg.channels.console.bot_prefix = "[EXISTING]"

        cc.configure_channels_interactive(cfg)

        assert seen == [cfg.channels.console]
        assert seen[0].bot_prefix == "[EXISTING]"
        rec.assert_fully_consumed()
