# -*- coding: utf-8 -*-
"""
Azure Bot Channel Unit Tests

Comprehensive unit tests for AzureBotChannel covering:
- Initialization and configuration
- Factory methods (from_env, from_config)
- Session ID resolution and routing
- Conversation reference storage (group vs DM)
- Reference lookup (_find_ref)
- Bot mention detection and stripping
- Group chat detection (Teams, Slack, standard)
- Outbound send (bot_channel_id resolution)
- File-too-large i18n messages
- build_agent_request_from_native (sender_id / "group")

Test Patterns:
- Async tests with @pytest.mark.asyncio on async methods only
- No global pytestmark
- Uses tmp_path for temporary files

Run:
    pytest tests/unit/channels/test_azure_bot.py -v
    pytest tests/unit/channels/test_azure_bot.py::TestAzureBotInit -v
"""
# pylint: disable=redefined-outer-name,protected-access,unused-argument
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_process_handler() -> AsyncMock:
    """Mock process handler."""

    async def mock_process(*_args, **_kwargs):
        mock_event = MagicMock()
        mock_event.object = "message"
        mock_event.status = "completed"
        mock_event.type = "text"
        yield mock_event

    return AsyncMock(side_effect=mock_process)


@pytest.fixture
def azure_bot_channel(mock_process_handler, tmp_path: Path):
    """Create an AzureBotChannel instance for testing."""
    from qwenpaw.app.channels.azure_bot.channel import AzureBotChannel

    channel = AzureBotChannel(
        process=mock_process_handler,
        enabled=True,
        app_id="test-app-id-000",
        app_password="test-secret",
        tenant_id="test-tenant-id",
        http_host="127.0.0.1",
        http_port=13978,
        bot_prefix="[Bot] ",
        media_dir=str(tmp_path / "media"),
        workspace_dir=tmp_path,
        share_session_in_group=False,
        require_mention=False,
    )
    channel._enqueue = MagicMock()
    return channel


@pytest.fixture
def azure_bot_channel_shared(mock_process_handler, tmp_path: Path):
    """AzureBotChannel with share_session_in_group=True."""
    from qwenpaw.app.channels.azure_bot.channel import AzureBotChannel

    channel = AzureBotChannel(
        process=mock_process_handler,
        enabled=True,
        app_id="test-app-id-000",
        app_password="test-secret",
        tenant_id="test-tenant-id",
        http_host="127.0.0.1",
        http_port=13978,
        media_dir=str(tmp_path / "media"),
        workspace_dir=tmp_path,
        share_session_in_group=True,
        require_mention=False,
    )
    channel._enqueue = MagicMock()
    return channel


@pytest.fixture
def sample_slack_dm_activity() -> dict:
    """Sample Slack DM activity."""
    return {
        "type": "message",
        "id": "act-001",
        "timestamp": "2026-07-01T00:00:00Z",
        "serviceUrl": "https://slack.botframework.com/",
        "channelId": "slack",
        "from": {
            "id": "U0BC8NH0PRA:T0BC6UR737T",
            "name": "hainokiseki",
        },
        "conversation": {
            "id": "B0BC3AREXSS:T0BC6UR737T:D0BC3ARK7SA",
        },
        "recipient": {
            "id": "B0BC3AREXSS:T0BC6UR737T",
            "name": "qwenpaw-bot",
        },
        "text": "hello bot",
        "channelData": {},
        "attachments": [],
    }


@pytest.fixture
def sample_slack_group_activity() -> dict:
    """Sample Slack group channel activity."""
    return {
        "type": "message",
        "id": "act-002",
        "serviceUrl": "https://slack.botframework.com/",
        "channelId": "slack",
        "from": {
            "id": "U0BC8NH0PRA:T0BC6UR737T",
            "name": "hainokiseki",
        },
        "conversation": {
            "id": "B0BC3AREXSS:T0BC6UR737T:C0BC8NHDBDJ",
        },
        "recipient": {
            "id": "B0BC3AREXSS:T0BC6UR737T",
            "name": "qwenpaw-bot",
        },
        "text": "hello group",
        "channelData": {
            "SlackMessage": {
                "event": {
                    "channel_type": "channel",
                },
            },
        },
        "attachments": [],
    }


@pytest.fixture
def sample_webchat_activity() -> dict:
    """Sample Web Chat activity (no sender name)."""
    return {
        "type": "message",
        "id": "act-003",
        "serviceUrl": "https://webchat.botframework.com/",
        "channelId": "webchat",
        "from": {
            "id": "b573a062-142a-4c2d-bbf4-a79ab4955074",
            "name": "",
        },
        "conversation": {
            "id": "6gC3O43h8K49TI1n7Fgv49-as",
        },
        "recipient": {
            "id": "bot-channel-id-webchat",
            "name": "qwenpaw-teams",
        },
        "text": "你好",
        "channelData": {},
        "attachments": [],
    }


@pytest.fixture
def sample_teams_group_activity() -> dict:
    """Sample Teams group activity (conversationType=groupChat)."""
    return {
        "type": "message",
        "id": "act-004",
        "serviceUrl": "https://smba.trafficmanager.net/apac/",
        "channelId": "msteams",
        "from": {
            "id": "user-aad-id-123",
            "aadObjectId": "aad-obj-id-abc",
            "name": "Alice",
        },
        "conversation": {
            "id": "19:meeting_abc123@thread.v2",
            "conversationType": "groupChat",
        },
        "recipient": {
            "id": "bot-teams-id",
            "name": "QwenPaw",
        },
        "text": "hi team",
        "entities": [
            {
                "type": "mention",
                "mentioned": {
                    "id": "bot-teams-id",
                    "name": "QwenPaw",
                },
                "text": "<at>QwenPaw</at>",
            },
        ],
        "channelData": {},
        "attachments": [],
    }


# =============================================================================
# P0: Initialization and Configuration
# =============================================================================


class TestAzureBotInit:
    """P0: AzureBotChannel initialization tests."""

    def test_init_stores_basic_config(self, azure_bot_channel):
        """Constructor should store basic configuration."""
        ch = azure_bot_channel
        assert ch.channel == "azure_bot"
        assert ch.enabled is True
        assert ch._app_id == "test-app-id-000"
        assert ch._app_password == "test-secret"
        assert ch._tenant_id == "test-tenant-id"
        assert ch._http_port == 13978
        assert ch._share_session_in_group is False
        assert ch.require_mention is False

    def test_init_media_dir_from_param(self, azure_bot_channel, tmp_path):
        """media_dir param should be used when provided."""
        assert azure_bot_channel._media_dir == tmp_path / "media"

    def test_init_media_dir_fallback_workspace(
        self, mock_process_handler, tmp_path
    ):
        """Without media_dir, should fallback to workspace_dir/media."""
        from qwenpaw.app.channels.azure_bot.channel import AzureBotChannel

        ch = AzureBotChannel(
            process=mock_process_handler,
            enabled=True,
            app_id="id",
            app_password="pw",
            tenant_id="t",
            media_dir="",
            workspace_dir=tmp_path,
        )
        assert ch._media_dir == tmp_path / "media"

    def test_uses_manager_queue(self, azure_bot_channel):
        """Channel should declare uses_manager_queue = True."""
        assert azure_bot_channel.uses_manager_queue is True


# =============================================================================
# P0: Session ID Resolution
# =============================================================================


class TestResolveSessionId:
    """P0: resolve_session_id tests."""

    def test_basic_resolution(self, azure_bot_channel):
        """Should produce azure_{channelId}#{conv_id_last10}."""
        result = azure_bot_channel.resolve_session_id(
            sender_id="user123",
            channel_meta={
                "azure_channel_id": "slack",
                "conversation_id": "B0BC3AREXSS:T0BC6UR737T:D0BC3ARK7SA",
            },
        )
        assert result == "azure_slack#0BC3ARK7SA"

    def test_short_conversation_id(self, azure_bot_channel):
        """Short conv_id (< 10) should be used as-is."""
        result = azure_bot_channel.resolve_session_id(
            sender_id="u",
            channel_meta={
                "azure_channel_id": "webchat",
                "conversation_id": "short",
            },
        )
        assert result == "azure_webchat#short"

    def test_no_meta_defaults(self, azure_bot_channel):
        """Without meta, defaults to azure_bot#(empty)."""
        result = azure_bot_channel.resolve_session_id("x")
        assert result == "azure_bot#"


# =============================================================================
# P0: to_handle_from_target (cron routing)
# =============================================================================


class TestToHandleFromTarget:
    """P0: to_handle_from_target tests."""

    def test_group_shared(self, azure_bot_channel):
        """user_id='group' → returns session_id only."""
        result = azure_bot_channel.to_handle_from_target(
            user_id="group",
            session_id="azure_slack#0BC3ARK7SA",
        )
        assert result == "azure_slack#0BC3ARK7SA"

    def test_dm_or_isolated(self, azure_bot_channel):
        """Normal user_id → returns session_id:user_id."""
        result = azure_bot_channel.to_handle_from_target(
            user_id="hainokiseki#UR737T",
            session_id="azure_slack#0BC3ARK7SA",
        )
        assert result == "azure_slack#0BC3ARK7SA:hainokiseki#UR737T"


# =============================================================================
# P0: _store_conversation_reference
# =============================================================================


class TestStoreConversationReference:
    """P0: Reference storage key logic."""

    def test_dm_stores_with_user_key(
        self, azure_bot_channel, sample_slack_dm_activity
    ):
        """DM activity should store with key=session_id:display_user."""
        azure_bot_channel._store_conversation_reference(
            sample_slack_dm_activity
        )
        refs = azure_bot_channel._conversation_refs
        # conv_id last 10: "0BC3ARK7SA"
        # sender last 6: "UR737T"
        expected_key = "azure_slack#0BC3ARK7SA:hainokiseki#UR737T"
        assert expected_key in refs
        ref = refs[expected_key]
        assert ref["service_url"] == "https://slack.botframework.com/"
        assert ref["bot_channel_id"] == "B0BC3AREXSS:T0BC6UR737T"
        assert ref["is_group"] is False

    def test_group_stores_with_session_only_key(
        self, azure_bot_channel, sample_slack_group_activity
    ):
        """Group activity should store with key=session_id only."""
        azure_bot_channel._store_conversation_reference(
            sample_slack_group_activity
        )
        refs = azure_bot_channel._conversation_refs
        expected_key = "azure_slack#0BC8NHDBDJ"
        assert expected_key in refs
        assert refs[expected_key]["is_group"] is True

    def test_webchat_no_name_uses_channel_id(
        self, azure_bot_channel, sample_webchat_activity
    ):
        """Web Chat with no name → key uses channelId#last6."""
        azure_bot_channel._store_conversation_reference(
            sample_webchat_activity
        )
        refs = azure_bot_channel._conversation_refs
        # DM (no group indicators), sender has no name
        expected_key = "azure_webchat#n7Fgv49-as:webchat#955074"
        assert expected_key in refs

    def test_teams_group_conversationType(
        self, azure_bot_channel, sample_teams_group_activity
    ):
        """Teams groupChat conversationType → group key."""
        azure_bot_channel._store_conversation_reference(
            sample_teams_group_activity
        )
        refs = azure_bot_channel._conversation_refs
        # conv_id last 10: "hread.v2" (len < 10 check)
        # Actually "19:meeting_abc123@thread.v2" last 10 = "@thread.v2"
        expected_key = "azure_msteams#@thread.v2"
        assert expected_key in refs
        assert refs[expected_key]["is_group"] is True

    def test_group_deduplicates(
        self, azure_bot_channel, sample_slack_group_activity
    ):
        """Multiple users in same group → single ref entry."""
        act1 = sample_slack_group_activity.copy()
        act2 = dict(sample_slack_group_activity)
        act2["from"] = {"id": "U_OTHER_USER:T0BC6UR737T", "name": "bob"}

        azure_bot_channel._store_conversation_reference(act1)
        azure_bot_channel._store_conversation_reference(act2)

        refs = azure_bot_channel._conversation_refs
        # Only one key for the group
        group_keys = [k for k in refs if "0BC8NHDBDJ" in k]
        assert len(group_keys) == 1


# =============================================================================
# P1: _find_ref
# =============================================================================


class TestFindRef:
    """P1: Reference lookup logic."""

    def test_exact_match_group(self, azure_bot_channel):
        """Direct key match for group ref."""
        azure_bot_channel._conversation_refs["azure_slack#ABC"] = {
            "service_url": "https://slack.botframework.com/",
            "conversation_id": "conv_ABC",
        }
        ref = azure_bot_channel._find_ref("azure_slack#ABC")
        assert ref is not None
        assert ref["conversation_id"] == "conv_ABC"

    def test_exact_match_dm(self, azure_bot_channel):
        """Direct key match for DM ref."""
        key = "azure_slack#ABC:user#xyz123"
        azure_bot_channel._conversation_refs[key] = {
            "service_url": "https://slack.botframework.com/",
            "conversation_id": "conv_DM",
        }
        ref = azure_bot_channel._find_ref(key)
        assert ref is not None
        assert ref["conversation_id"] == "conv_DM"

    def test_group_fallback_from_dm_handle(self, azure_bot_channel):
        """to_handle=session_id:user_id → falls back to session_id key."""
        azure_bot_channel._conversation_refs["azure_slack#GRP123"] = {
            "service_url": "https://slack.botframework.com/",
            "conversation_id": "conv_GRP",
        }
        # Look up with session_id:user_id but only group key exists
        ref = azure_bot_channel._find_ref("azure_slack#GRP123:bob#abc123")
        assert ref is not None
        assert ref["conversation_id"] == "conv_GRP"

    def test_meta_build_group_key(self, azure_bot_channel):
        """Build key from meta → try group key first."""
        azure_bot_channel._conversation_refs["azure_slack#0123456789"] = {
            "service_url": "https://slack.botframework.com/",
            "conversation_id": "FULL_CONV_ID_0123456789",
        }
        ref = azure_bot_channel._find_ref(
            "unknown_handle",
            meta={
                "conversation_id": "FULL_CONV_ID_0123456789",
                "azure_channel_id": "slack",
            },
        )
        assert ref is not None

    def test_no_match_returns_none(self, azure_bot_channel):
        """No match → returns None."""
        ref = azure_bot_channel._find_ref("nonexistent")
        assert ref is None


# =============================================================================
# P1: build_agent_request_from_native
# =============================================================================


class TestBuildAgentRequest:
    """P1: AgentRequest construction from native payload."""

    def test_normal_dm_sender_id(self, azure_bot_channel):
        """DM: sender_id = display_sender → user_id = display_sender."""
        native = {
            "channel_id": "azure_bot",
            "sender_id": "hainokiseki#UR737T",
            "acl_sender_id": "U0BC8NH0PRA:T0BC6UR737T",
            "content_parts": [MagicMock(type="text", text="hi")],
            "meta": {
                "azure_channel_id": "slack",
                "conversation_id": "conv_1234567890",
            },
        }
        request = azure_bot_channel.build_agent_request_from_native(native)
        assert request.user_id == "hainokiseki#UR737T"
        assert request.session_id == "azure_slack#1234567890"

    def test_group_shared_sender_id(self, azure_bot_channel_shared):
        """Group shared: sender_id = "group" → user_id = "group"."""
        native = {
            "channel_id": "azure_bot",
            "sender_id": "group",
            "acl_sender_id": "U_REAL_ID",
            "content_parts": [MagicMock(type="text", text="hi")],
            "meta": {
                "azure_channel_id": "slack",
                "conversation_id": "conv_1234567890",
            },
        }
        request = azure_bot_channel_shared.build_agent_request_from_native(
            native
        )
        assert request.user_id == "group"


# =============================================================================
# P1: _on_message (group detection + sender_id)
# =============================================================================


class TestOnMessage:
    """P1: Message handling logic."""

    @pytest.mark.asyncio
    async def test_slack_group_sets_sender_group(
        self, azure_bot_channel_shared, sample_slack_group_activity
    ):
        """Group + share_session → sender_id = 'group'."""
        await azure_bot_channel_shared._on_message(
            sample_slack_group_activity
        )
        call_args = azure_bot_channel_shared._enqueue.call_args
        native = call_args[0][0]
        assert native["sender_id"] == "group"

    @pytest.mark.asyncio
    async def test_slack_dm_sets_display_sender(
        self, azure_bot_channel, sample_slack_dm_activity
    ):
        """DM → sender_id = display_sender (name#last6)."""
        await azure_bot_channel._on_message(sample_slack_dm_activity)
        call_args = azure_bot_channel._enqueue.call_args
        native = call_args[0][0]
        assert native["sender_id"] == "hainokiseki#UR737T"

    @pytest.mark.asyncio
    async def test_webchat_no_name_uses_channel_suffix(
        self, azure_bot_channel, sample_webchat_activity
    ):
        """Web Chat with empty name → sender_id = channelId#last6."""
        await azure_bot_channel._on_message(sample_webchat_activity)
        call_args = azure_bot_channel._enqueue.call_args
        native = call_args[0][0]
        assert native["sender_id"] == "webchat#955074"

    @pytest.mark.asyncio
    async def test_require_mention_skips_unmentioned(
        self, mock_process_handler, tmp_path
    ):
        """Group + require_mention + not mentioned → skip."""
        from qwenpaw.app.channels.azure_bot.channel import AzureBotChannel

        ch = AzureBotChannel(
            process=mock_process_handler,
            enabled=True,
            app_id="test-app-id",
            app_password="pw",
            tenant_id="t",
            workspace_dir=tmp_path,
            require_mention=True,
        )
        ch._enqueue = MagicMock()

        activity = {
            "type": "message",
            "channelId": "slack",
            "from": {"id": "user1", "name": "Alice"},
            "conversation": {"id": "conv123"},
            "recipient": {"id": "bot-id"},
            "serviceUrl": "https://slack.botframework.com/",
            "text": "hello",
            "channelData": {
                "SlackMessage": {"event": {"channel_type": "channel"}},
            },
            "entities": [],
            "attachments": [],
        }
        await ch._on_message(activity)
        ch._enqueue.assert_not_called()


# =============================================================================
# P1: Bot mention detection and stripping
# =============================================================================


class TestBotMention:
    """P1: Mention detection and text stripping."""

    def test_is_bot_mentioned_by_app_id(self, azure_bot_channel):
        """Detect mention by app_id."""
        activity = {
            "entities": [
                {
                    "type": "mention",
                    "mentioned": {"id": "test-app-id-000"},
                },
            ],
        }
        assert azure_bot_channel._is_bot_mentioned(activity) is True

    def test_is_bot_mentioned_by_channel_id(self, azure_bot_channel):
        """Detect mention by bot_channel_id."""
        azure_bot_channel._bot_channel_id = "B0BC3AREXSS:T0BC6UR737T"
        activity = {
            "entities": [
                {
                    "type": "mention",
                    "mentioned": {"id": "B0BC3AREXSS:T0BC6UR737T"},
                },
            ],
        }
        assert azure_bot_channel._is_bot_mentioned(activity) is True

    def test_is_bot_mentioned_false(self, azure_bot_channel):
        """No bot mention → False."""
        activity = {
            "entities": [
                {
                    "type": "mention",
                    "mentioned": {"id": "some-other-user"},
                },
            ],
        }
        assert azure_bot_channel._is_bot_mentioned(activity) is False

    def test_strip_bot_mention(self, azure_bot_channel):
        """Should remove @mention text from message."""
        activity = {
            "entities": [
                {
                    "type": "mention",
                    "mentioned": {"id": "test-app-id-000"},
                    "text": "<at>QwenPaw</at>",
                },
            ],
        }
        result = azure_bot_channel._strip_bot_mention(
            "<at>QwenPaw</at> hello", activity
        )
        assert result == "hello"


# =============================================================================
# P1: Send (bot_channel_id resolution)
# =============================================================================


class TestSend:
    """P1: Outbound send logic."""

    @pytest.mark.asyncio
    async def test_send_uses_meta_bot_id(self, azure_bot_channel):
        """send() should prefer bot_channel_id from meta."""
        import aiohttp

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.post = MagicMock(return_value=mock_resp)
        azure_bot_channel._http_session = mock_session

        with patch.object(
            azure_bot_channel, "_get_bot_token", return_value="fake-token"
        ):
            await azure_bot_channel.send(
                to_handle="handle",
                text="hi",
                meta={
                    "service_url": "https://slack.botframework.com/",
                    "conversation_id": "conv123",
                    "bot_channel_id": "meta-bot-id",
                },
            )

        call_kwargs = mock_session.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["from"]["id"] == "meta-bot-id"

    @pytest.mark.asyncio
    async def test_send_uses_ref_bot_id(self, azure_bot_channel):
        """send() should use ref's bot_channel_id when meta lacks it."""
        azure_bot_channel._conversation_refs["handle"] = {
            "service_url": "https://slack.botframework.com/",
            "conversation_id": "conv_ref",
            "bot_channel_id": "ref-bot-id",
            "azure_channel_id": "slack",
        }

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.post = MagicMock(return_value=mock_resp)
        azure_bot_channel._http_session = mock_session

        with patch.object(
            azure_bot_channel, "_get_bot_token", return_value="fake-token"
        ):
            await azure_bot_channel.send(
                to_handle="handle",
                text="hi",
                meta={},
            )

        call_kwargs = mock_session.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["from"]["id"] == "ref-bot-id"

    @pytest.mark.asyncio
    async def test_send_fallback_to_app_id(self, azure_bot_channel):
        """send() falls back to app_id when no bot_channel_id anywhere."""
        azure_bot_channel._bot_channel_id = None
        azure_bot_channel._conversation_refs["handle"] = {
            "service_url": "https://test.com/",
            "conversation_id": "conv",
            "bot_channel_id": "",
            "azure_channel_id": "slack",
        }

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.post = MagicMock(return_value=mock_resp)
        azure_bot_channel._http_session = mock_session

        with patch.object(
            azure_bot_channel, "_get_bot_token", return_value="token"
        ):
            await azure_bot_channel.send("handle", "hi", meta={})

        call_kwargs = mock_session.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["from"]["id"] == "test-app-id-000"


# =============================================================================
# P2: File-too-large i18n
# =============================================================================


class TestFileTooLargeMsg:
    """P2: i18n file size warning messages."""

    def test_zh_message(self, azure_bot_channel):
        """Chinese message for zh locale."""
        azure_bot_channel._language = "zh-CN"
        msg = azure_bot_channel._file_too_large_msg("报告.pdf", 200_000)
        assert "报告.pdf" in msg
        assert "195KB" in msg
        assert "180KB" in msg

    def test_en_message(self, azure_bot_channel):
        """English message for en locale."""
        azure_bot_channel._language = "en"
        msg = azure_bot_channel._file_too_large_msg("report.pdf", 200_000)
        assert "report.pdf" in msg
        assert "exceeds" in msg

    def test_unknown_locale_fallback_en(self, azure_bot_channel):
        """Unknown locale falls back to English."""
        azure_bot_channel._language = "fr"
        msg = azure_bot_channel._file_too_large_msg("file.zip", 200_000)
        assert "exceeds" in msg


# =============================================================================
# P2: Refs persistence
# =============================================================================


class TestRefsPersistence:
    """P2: Disk persistence of conversation refs."""

    def test_save_and_load(self, azure_bot_channel, tmp_path):
        """Refs should survive save → load cycle."""
        azure_bot_channel._conversation_refs["key1"] = {
            "service_url": "https://test.com/",
            "conversation_id": "conv1",
            "azure_channel_id": "slack",
            "bot_channel_id": "bot1",
            "is_group": False,
        }
        azure_bot_channel._save_refs_to_disk()

        # Create new instance and load
        from qwenpaw.app.channels.azure_bot.channel import AzureBotChannel

        ch2 = AzureBotChannel(
            process=MagicMock(),
            enabled=True,
            app_id="x",
            app_password="x",
            tenant_id="t",
            workspace_dir=tmp_path,
        )
        ch2._load_refs_from_disk()
        assert "key1" in ch2._conversation_refs
        assert ch2._conversation_refs["key1"]["conversation_id"] == "conv1"
        assert ch2._bot_channel_id == "bot1"
