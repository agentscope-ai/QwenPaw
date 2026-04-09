# -*- coding: utf-8 -*-
"""
Mattermost Channel Unit Tests

Comprehensive unit tests for MattermostChannel covering:
- Initialization and configuration
- Factory methods (from_env, from_config)
- Session ID resolution and routing
- HTTP API interactions (mocked)
- Send methods (text and media)
- File upload and download
- History fetching (thread and channel)
- Typing indicators
- Message event handling
- Lifecycle (start/stop)
- Allowlist and ACL checks

Test Patterns:
- Uses MockHttpxClient for HTTP request mocking (httpx.AsyncClient)
- Async tests with @pytest.mark.asyncio (only on async methods)
- No global pytestmark

Run:
    pytest tests/unit/channels/test_mattermost.py -v
    pytest tests/unit/channels/test_mattermost.py::TestMattermostChannelInit -v
"""
# pylint: disable=redefined-outer-name,protected-access,unused-argument
# pylint: disable=broad-exception-raised,using-constant-test
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Generator, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# =============================================================================
# Mock HTTP Classes for httpx
# =============================================================================


class MockHttpxResponse:
    """Mock httpx Response for testing."""

    def __init__(
        self,
        status_code: int = 200,
        json_data: Optional[dict] = None,
        text_data: str = "",
        headers: Optional[dict] = None,
    ):
        self.status_code = status_code
        self._json_data = json_data or {}
        self._text_data = text_data
        self.headers = headers or {}

    def json(self) -> dict:
        """Return JSON data."""
        return self._json_data

    def text(self) -> str:
        """Return text data."""
        return self._text_data

    def read(self) -> bytes:
        """Return bytes data."""
        return self._text_data.encode()

    async def aiter_bytes(self, chunk_size: int = 65536):
        """Async iterator over response bytes."""
        yield self._text_data.encode()

    def raise_for_status(self):
        """Raise exception for error status codes."""
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


class MockHttpxClient:
    """Mock httpx.AsyncClient for testing Mattermost channel."""

    def __init__(self):
        self._expectations: list[dict] = []
        self._requests: list[dict] = []
        self.call_count = 0
        self.closed = False

    def expect_post(
        self,
        url: Optional[str] = None,
        response_status: int = 200,
        response_json: Optional[dict] = None,
        response_text: str = "",
    ) -> None:
        """Set up expected POST request."""
        self._expectations.append(
            {
                "method": "POST",
                "url": url,
                "response": MockHttpxResponse(
                    status_code=response_status,
                    json_data=response_json,
                    text_data=response_text,
                ),
            },
        )

    def expect_get(
        self,
        url: Optional[str] = None,
        response_status: int = 200,
        response_json: Optional[dict] = None,
        response_text: str = "",
    ) -> None:
        """Set up expected GET request."""
        self._expectations.append(
            {
                "method": "GET",
                "url": url,
                "response": MockHttpxResponse(
                    status_code=response_status,
                    json_data=response_json,
                    text_data=response_text,
                ),
            },
        )

    async def post(self, url: str, **kwargs) -> MockHttpxResponse:
        """Mock POST request."""
        self._requests.append({"method": "POST", "url": url, "kwargs": kwargs})
        self.call_count += 1

        for exp in self._expectations:
            if exp["method"] == "POST":
                if exp["url"] is None or exp["url"] in url:
                    return exp["response"]
        return MockHttpxResponse(status_code=404, text_data="Not Found")

    async def get(self, url: str, **kwargs) -> MockHttpxResponse:
        """Mock GET request."""
        self._requests.append({"method": "GET", "url": url, "kwargs": kwargs})
        self.call_count += 1

        for exp in self._expectations:
            if exp["method"] == "GET":
                if exp["url"] is None or exp["url"] in url:
                    return exp["response"]
        return MockHttpxResponse(status_code=404, text_data="Not Found")

    def stream(self, method: str, url: str, **kwargs):
        """Mock stream context manager."""
        self._requests.append({"method": method, "url": url, "kwargs": kwargs})
        self.call_count += 1

        class StreamContext:
            def __init__(self, response):
                self.response = response

            async def __aenter__(self):
                return self.response

            async def __aexit__(self, *args):
                pass

        for exp in self._expectations:
            if exp["method"] == method or exp["method"] == "GET":
                if exp["url"] is None or exp["url"] in url:
                    return StreamContext(exp["response"])
        return StreamContext(MockHttpxResponse(status_code=404))

    async def aclose(self) -> None:
        """Mock close."""
        self.closed = True


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_process_handler() -> AsyncMock:
    """Mock process handler that yields simple events."""

    async def mock_process(*_args, **_kwargs):
        mock_event = MagicMock()
        mock_event.object = "message"
        mock_event.status = "completed"
        mock_event.type = "text"
        yield mock_event

    return AsyncMock(side_effect=mock_process)


@pytest.fixture
def mock_http_client() -> MockHttpxClient:
    """Create a mock httpx client."""
    return MockHttpxClient()


@pytest.fixture
def mattermost_channel(
    mock_process_handler,
    tmp_path: Path,
) -> Generator:
    """Create a MattermostChannel instance for testing."""
    from copaw.app.channels.mattermost.channel import MattermostChannel

    channel = MattermostChannel(
        process=mock_process_handler,
        enabled=True,
        url="https://mattermost.example.com",
        bot_token="test_token_123",
        bot_prefix="[TestBot] ",
        media_dir=str(tmp_path / "media"),
        show_tool_details=False,
        filter_tool_messages=True,
        dm_policy="open",
        group_policy="open",
    )
    yield channel


# =============================================================================
# P0: Initialization and Configuration
# =============================================================================


class TestMattermostChannelInit:
    """Tests for MattermostChannel initialization and factory methods."""

    def test_init_stores_basic_config(
        self,
        mock_process_handler,
        tmp_path: Path,
    ):
        """Constructor should store all basic configuration parameters."""
        from copaw.app.channels.mattermost.channel import MattermostChannel

        channel = MattermostChannel(
            process=mock_process_handler,
            enabled=True,
            url="https://mm.example.com",
            bot_token="my_token_123",
            bot_prefix="[Bot] ",
            media_dir=str(tmp_path / "media"),
            dm_policy="open",
            group_policy="allowlist",
        )

        assert channel.enabled is True
        assert channel._url == "https://mm.example.com"
        assert channel._bot_token == "my_token_123"
        assert channel.bot_prefix == "[Bot] "
        assert channel.channel == "mattermost"
        assert channel.dm_policy == "open"
        assert channel.group_policy == "allowlist"

    def test_init_stores_advanced_config(
        self,
        mock_process_handler,
        tmp_path: Path,
    ):
        """Constructor should store advanced configuration parameters."""
        from copaw.app.channels.mattermost.channel import MattermostChannel

        channel = MattermostChannel(
            process=mock_process_handler,
            enabled=False,
            url="",
            bot_token="",
            bot_prefix="",
            media_dir=str(tmp_path / "custom_media"),
            show_typing=False,
            thread_follow_without_mention=True,
            show_tool_details=True,
            filter_tool_messages=True,
            filter_thinking=True,
            allow_from=["user1", "user2"],
            deny_message="Access denied",
        )

        assert channel.enabled is False
        assert channel._show_typing is False
        assert channel._thread_follow is True
        assert channel._show_tool_details is True
        assert channel._filter_tool_messages is True
        assert channel._filter_thinking is True
        assert channel.allow_from == {"user1", "user2"}
        assert channel.deny_message == "Access denied"

    def test_init_normalizes_url(self, mock_process_handler):
        """Constructor should normalize URL by stripping trailing slash."""
        from copaw.app.channels.mattermost.channel import MattermostChannel

        channel = MattermostChannel(
            process=mock_process_handler,
            enabled=True,
            url="https://mm.example.com/",
            bot_token="token123",
        )

        assert channel._url == "https://mm.example.com"

    def test_init_disables_when_empty_url(self, mock_process_handler):
        """Should disable channel when URL is empty but enabled=True."""
        from copaw.app.channels.mattermost.channel import MattermostChannel

        channel = MattermostChannel(
            process=mock_process_handler,
            enabled=True,
            url="",
            bot_token="token123",
        )

        assert channel.enabled is False

    def test_init_disables_when_empty_token(self, mock_process_handler):
        """Should disable channel when bot_token is empty but enabled=True."""
        from copaw.app.channels.mattermost.channel import MattermostChannel

        channel = MattermostChannel(
            process=mock_process_handler,
            enabled=True,
            url="https://mm.example.com",
            bot_token="",
        )

        assert channel.enabled is False

    def test_init_creates_required_data_structures(self, mock_process_handler):
        """Constructor should initialize required internal data structures."""
        from copaw.app.channels.mattermost.channel import MattermostChannel

        channel = MattermostChannel(
            process=mock_process_handler,
            enabled=True,
            url="https://mm.example.com",
            bot_token="token123",
        )

        assert hasattr(channel, "_typing_tasks")
        assert isinstance(channel._typing_tasks, dict)
        assert hasattr(channel, "_participated_threads")
        assert isinstance(channel._participated_threads, set)
        assert hasattr(channel, "_seen_sessions")
        assert isinstance(channel._seen_sessions, set)
        assert channel._bot_id == ""
        assert channel._bot_username == ""

    def test_init_creates_http_client(self, mock_process_handler):
        """Constructor should create httpx client with auth header."""
        from copaw.app.channels.mattermost.channel import MattermostChannel

        channel = MattermostChannel(
            process=mock_process_handler,
            enabled=True,
            url="https://mm.example.com",
            bot_token="test_token",
        )

        assert channel._http is not None
        assert hasattr(channel._http, "headers")


class TestMattermostChannelFromEnv:
    """Tests for from_env factory method."""

    def test_from_env_reads_basic_env_vars(
        self,
        mock_process_handler,
        monkeypatch,
    ):
        """from_env should read basic environment variables."""
        from copaw.app.channels.mattermost.channel import MattermostChannel

        monkeypatch.setenv("MATTERMOST_CHANNEL_ENABLED", "1")
        monkeypatch.setenv("MATTERMOST_URL", "https://env.mm.com")
        monkeypatch.setenv("MATTERMOST_BOT_TOKEN", "env_token_123")
        monkeypatch.setenv("MATTERMOST_BOT_PREFIX", "[EnvBot] ")

        channel = MattermostChannel.from_env(mock_process_handler)

        assert channel.enabled is True
        assert channel._url == "https://env.mm.com"
        assert channel._bot_token == "env_token_123"
        assert channel.bot_prefix == "[EnvBot] "

    def test_from_env_reads_advanced_env_vars(
        self,
        mock_process_handler,
        monkeypatch,
    ):
        """from_env should read advanced environment variables."""
        from copaw.app.channels.mattermost.channel import MattermostChannel

        monkeypatch.setenv("MATTERMOST_MEDIA_DIR", "/env/media")
        monkeypatch.setenv("MATTERMOST_SHOW_TYPING", "0")
        monkeypatch.setenv("MATTERMOST_THREAD_FOLLOW", "1")
        monkeypatch.setenv("MATTERMOST_DM_POLICY", "allowlist")
        monkeypatch.setenv("MATTERMOST_GROUP_POLICY", "allowlist")
        monkeypatch.setenv("MATTERMOST_DENY_MESSAGE", "Env access denied")

        channel = MattermostChannel.from_env(mock_process_handler)

        assert channel._media_dir == Path("/env/media").expanduser()
        assert channel._show_typing is False
        assert channel._thread_follow is True
        assert channel.dm_policy == "allowlist"
        assert channel.group_policy == "allowlist"
        assert channel.deny_message == "Env access denied"

    def test_from_env_allow_from_parsing(
        self,
        mock_process_handler,
        monkeypatch,
    ):
        """from_env should parse MATTERMOST_ALLOW_FROM correctly."""
        from copaw.app.channels.mattermost.channel import MattermostChannel

        monkeypatch.setenv("MATTERMOST_ALLOW_FROM", "user1,user2,user3")

        channel = MattermostChannel.from_env(mock_process_handler)

        assert "user1" in channel.allow_from
        assert "user2" in channel.allow_from
        assert "user3" in channel.allow_from

    def test_from_env_allow_from_empty(
        self,
        mock_process_handler,
        monkeypatch,
    ):
        """from_env should handle empty MATTERMOST_ALLOW_FROM."""
        from copaw.app.channels.mattermost.channel import MattermostChannel

        monkeypatch.setenv("MATTERMOST_ALLOW_FROM", "")

        channel = MattermostChannel.from_env(mock_process_handler)

        assert channel.allow_from == set()

    def test_from_env_defaults(self, mock_process_handler, monkeypatch):
        """from_env should use sensible defaults."""
        from copaw.app.channels.mattermost.channel import MattermostChannel

        monkeypatch.delenv("MATTERMOST_CHANNEL_ENABLED", raising=False)
        monkeypatch.delenv("MATTERMOST_BOT_PREFIX", raising=False)
        monkeypatch.delenv("MATTERMOST_DM_POLICY", raising=False)
        monkeypatch.delenv("MATTERMOST_GROUP_POLICY", raising=False)

        channel = MattermostChannel.from_env(mock_process_handler)

        assert channel.enabled is False  # Default disabled
        assert channel.bot_prefix == ""  # Default empty
        assert channel.dm_policy == "open"  # Default open
        assert channel.group_policy == "open"  # Default open
        assert channel._show_typing is True  # Default True


class TestMattermostChannelFromConfig:
    """Tests for from_config factory method."""

    def test_from_config_uses_config_values(self, mock_process_handler):
        """from_config should use values from config object."""
        from copaw.app.channels.mattermost.channel import MattermostChannel

        class MockConfig:
            enabled = True
            url = "https://config.mm.com"
            bot_token = "config_token_123"
            bot_prefix = "[ConfigBot] "
            media_dir = "/config/media"
            show_typing = False
            thread_follow_without_mention = True
            dm_policy = "allowlist"
            group_policy = "allowlist"
            allow_from = ["user1", "user2"]
            deny_message = "Config denied"

            def model_dump(self):
                return {
                    "enabled": self.enabled,
                    "url": self.url,
                    "bot_token": self.bot_token,
                    "bot_prefix": self.bot_prefix,
                    "media_dir": self.media_dir,
                    "show_typing": self.show_typing,
                    "thread_follow_without_mention": self.thread_follow_without_mention,
                    "dm_policy": self.dm_policy,
                    "group_policy": self.group_policy,
                    "allow_from": self.allow_from,
                    "deny_message": self.deny_message,
                }

        config = MockConfig()
        channel = MattermostChannel.from_config(
            process=mock_process_handler,
            config=config,
        )

        assert channel.enabled is True
        assert channel._url == "https://config.mm.com"
        assert channel._bot_token == "config_token_123"
        assert channel.bot_prefix == "[ConfigBot]"
        assert channel.dm_policy == "allowlist"
        assert channel.group_policy == "allowlist"

    def test_from_config_handles_dict_config(self, mock_process_handler):
        """from_config should handle dict config."""
        from copaw.app.channels.mattermost.channel import MattermostChannel

        config_dict = {
            "enabled": True,
            "url": "https://dict.mm.com",
            "bot_token": "dict_token",
            "bot_prefix": "[Dict] ",
            "dm_policy": "open",
            "group_policy": "open",
        }

        channel = MattermostChannel.from_config(
            process=mock_process_handler,
            config=config_dict,
        )

        assert channel.enabled is True
        assert channel._url == "https://dict.mm.com"
        assert channel._bot_token == "dict_token"

    def test_from_config_handles_none_values(self, mock_process_handler):
        """from_config should handle None values gracefully."""
        from copaw.app.channels.mattermost.channel import MattermostChannel

        config_dict = {
            "enabled": None,
            "url": None,
            "bot_token": None,
            "bot_prefix": None,
            "dm_policy": None,
            "group_policy": None,
        }

        channel = MattermostChannel.from_config(
            process=mock_process_handler,
            config=config_dict,
        )

        assert channel.enabled is False
        assert channel._url == ""
        assert channel._bot_token == ""
        assert channel.bot_prefix == ""
        assert channel.dm_policy == "open"
        assert channel.group_policy == "open"


# =============================================================================
# P1: Session ID Resolution and Routing
# =============================================================================


class TestMattermostResolveSession:
    """Tests for session resolution and routing helpers."""

    def test_resolve_session_id_dm(self, mattermost_channel):
        """resolve_session_id should format DM session ID."""
        result = mattermost_channel.resolve_session_id(
            sender_id="user123",
            channel_meta={
                "channel_type": "D",
                "mm_channel_id": "dm_channel_456",
            },
        )

        assert result == "mattermost_dm:dm_channel_456"

    def test_resolve_session_id_thread(self, mattermost_channel):
        """resolve_session_id should format thread session ID."""
        result = mattermost_channel.resolve_session_id(
            sender_id="user123",
            channel_meta={
                "channel_type": "O",
                "mm_channel_id": "channel_789",
                "root_id": "root_post_abc",
                "post_id": "post_def",
            },
        )

        assert result == "mattermost_thread:root_post_abc"

    def test_resolve_session_id_no_root_uses_post_id(self, mattermost_channel):
        """resolve_session_id should use post_id when root_id is empty."""
        result = mattermost_channel.resolve_session_id(
            sender_id="user123",
            channel_meta={
                "channel_type": "O",
                "mm_channel_id": "channel_789",
                "root_id": "",
                "post_id": "post_123",
            },
        )

        assert result == "mattermost_thread:post_123"

    def test_get_to_handle_from_request_with_meta(self, mattermost_channel):
        """get_to_handle_from_request should extract handle from meta."""
        mock_request = MagicMock()
        mock_request.channel_meta = {"mm_channel_id": "channel_abc"}
        mock_request.session_id = ""

        result = mattermost_channel.get_to_handle_from_request(mock_request)

        assert result == "channel_abc"

    def test_get_to_handle_from_request_fallback_session(
        self,
        mattermost_channel,
    ):
        """get_to_handle_from_request should fallback to session_id."""
        mock_request = MagicMock()
        mock_request.channel_meta = {}
        mock_request.session_id = "mattermost_dm:dm_channel_123"

        result = mattermost_channel.get_to_handle_from_request(mock_request)

        assert result == "dm_channel_123"

    def test_get_to_handle_from_request_fallback_user(
        self,
        mattermost_channel,
    ):
        """get_to_handle_from_request should fallback to user_id."""
        mock_request = MagicMock()
        mock_request.channel_meta = {}
        mock_request.session_id = ""
        mock_request.user_id = "user123"

        result = mattermost_channel.get_to_handle_from_request(mock_request)

        assert result == "user123"

    def test_to_handle_from_target_dm_session(self, mattermost_channel):
        """to_handle_from_target should extract from DM session_id."""
        result = mattermost_channel.to_handle_from_target(
            user_id="user123",
            session_id="mattermost_dm:dm_channel_456",
        )

        assert result == "dm_channel_456"

    def test_to_handle_from_target_fallback_user(self, mattermost_channel):
        """to_handle_from_target should fallback to user_id."""
        result = mattermost_channel.to_handle_from_target(
            user_id="user123",
            session_id="mattermost_thread:root_abc",
        )

        assert result == "user123"


# =============================================================================
# P1: Build Agent Request
# =============================================================================


class TestMattermostBuildAgentRequest:
    """Tests for build_agent_request_from_native method."""

    def test_build_agent_request_from_native(self, mattermost_channel):
        """Should create AgentRequest from native payload."""
        from copaw.app.channels.base import TextContent, ContentType

        payload = {
            "channel_id": "mattermost",
            "sender_id": "user123",
            "content_parts": [
                TextContent(type=ContentType.TEXT, text="Hello"),
            ],
            "meta": {
                "mm_channel_id": "channel_abc",
                "root_id": "root_123",
                "channel_type": "O",
                "post_id": "post_456",
            },
        }

        request = mattermost_channel.build_agent_request_from_native(payload)

        assert request.user_id == "user123"
        assert request.channel == "mattermost"
        assert request.session_id == "mattermost_thread:root_123"
        assert hasattr(request, "channel_meta")

    def test_build_agent_request_auto_session(self, mattermost_channel):
        """Should auto-generate session_id when not provided."""
        from copaw.app.channels.base import TextContent, ContentType

        payload = {
            "channel_id": "mattermost",
            "sender_id": "user123",
            "content_parts": [
                TextContent(type=ContentType.TEXT, text="Hello"),
            ],
            "meta": {
                "mm_channel_id": "channel_abc",
                "channel_type": "D",
            },
        }

        request = mattermost_channel.build_agent_request_from_native(payload)

        assert request.session_id == "mattermost_dm:channel_abc"


# =============================================================================
# P1: HTTP API Interactions
# =============================================================================


class TestMattermostHTTPBase:
    """Base class for HTTP-based tests."""

    @pytest.fixture
    def channel_with_mock_http(
        self,
        mattermost_channel,
        mock_http_client,
    ):
        """Create channel with mocked HTTP client."""
        mattermost_channel._http = mock_http_client
        mattermost_channel._bot_id = "bot_123"
        return mattermost_channel


class TestMattermostInitBotInfo:
    """Tests for _init_bot_info method."""

    @pytest.mark.asyncio
    async def test_init_bot_info_success(
        self,
        mattermost_channel,
        mock_http_client,
    ):
        """Should fetch and cache bot info on success."""
        mock_http_client.expect_get(
            url="/api/v4/users/me",
            response_status=200,
            response_json={
                "id": "bot_user_123",
                "username": "testbot",
            },
        )
        mattermost_channel._http = mock_http_client

        result = await mattermost_channel._init_bot_info()

        assert result is True
        assert mattermost_channel._bot_id == "bot_user_123"
        assert mattermost_channel._bot_username == "testbot"

    @pytest.mark.asyncio
    async def test_init_bot_info_failure(
        self,
        mattermost_channel,
        mock_http_client,
    ):
        """Should return False on API error."""
        mock_http_client.expect_get(
            url="/api/v4/users/me",
            response_status=401,
            response_text="Unauthorized",
        )
        mattermost_channel._http = mock_http_client

        result = await mattermost_channel._init_bot_info()

        assert result is False

    @pytest.mark.asyncio
    async def test_init_bot_info_exception(
        self,
        mattermost_channel,
        mock_http_client,
    ):
        """Should handle exception gracefully."""
        mock_http_client.get = AsyncMock(
            side_effect=Exception("Network error"),
        )
        mattermost_channel._http = mock_http_client

        result = await mattermost_channel._init_bot_info()

        assert result is False


class TestMattermostPostMessage:
    """Tests for _post_message method."""

    @pytest.mark.asyncio
    async def test_post_message_success(
        self,
        mattermost_channel,
        mock_http_client,
    ):
        """Should return True on successful post."""
        mock_http_client.expect_post(
            url="/api/v4/posts",
            response_status=201,
            response_json={"id": "post_123"},
        )
        mattermost_channel._http = mock_http_client

        result = await mattermost_channel._post_message(
            mm_channel_id="channel_123",
            text="Hello World",
            root_id="root_456",
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_post_message_failure(
        self,
        mattermost_channel,
        mock_http_client,
    ):
        """Should return False on API error."""
        mock_http_client.expect_post(
            url="/api/v4/posts",
            response_status=403,
            response_text="Forbidden",
        )
        mattermost_channel._http = mock_http_client

        result = await mattermost_channel._post_message(
            mm_channel_id="channel_123",
            text="Hello",
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_post_message_with_file_ids(
        self,
        mattermost_channel,
        mock_http_client,
    ):
        """Should include file_ids in payload when provided."""
        mock_http_client.expect_post(
            url="/api/v4/posts",
            response_status=201,
        )
        mattermost_channel._http = mock_http_client

        await mattermost_channel._post_message(
            mm_channel_id="channel_123",
            text="",
            root_id="",
            file_ids=["file_1", "file_2"],
        )

        call_args = mock_http_client._requests[-1]
        assert "file_ids" in call_args["kwargs"].get("json", {})


class TestMattermostFetchHistory:
    """Tests for history fetching methods."""

    @pytest.mark.asyncio
    async def test_fetch_thread_history_success(
        self,
        mattermost_channel,
        mock_http_client,
    ):
        """Should fetch and format thread history."""
        mock_http_client.expect_get(
            url="/api/v4/posts/root_123/thread",
            response_status=200,
            response_json={
                "order": ["post1", "post2", "post3"],
                "posts": {
                    "post1": {
                        "id": "post1",
                        "user_id": "user_abc",
                        "message": "First message",
                        "create_at": 1000,
                    },
                    "post2": {
                        "id": "post2",
                        "user_id": "user_def",
                        "message": "Second message",
                        "create_at": 2000,
                    },
                    "post3": {
                        "id": "post3",
                        "user_id": "user_abc",
                        "message": "Third message",
                        "create_at": 3000,
                    },
                },
            },
        )
        mattermost_channel._http = mock_http_client
        mattermost_channel._bot_id = "bot_123"

        result = await mattermost_channel._fetch_thread_history(
            root_id="root_123",
            triggering_post_id="post3",
        )

        assert "[Thread history]" in result
        assert "User: First message" in result
        assert "User: Second message" in result

    @pytest.mark.asyncio
    async def test_fetch_thread_history_api_error(
        self,
        mattermost_channel,
        mock_http_client,
    ):
        """Should return empty string on API error."""
        mock_http_client.expect_get(
            url="/api/v4/posts/root_123/thread",
            response_status=404,
        )
        mattermost_channel._http = mock_http_client

        result = await mattermost_channel._fetch_thread_history(
            root_id="root_123",
        )

        assert result == ""

    @pytest.mark.asyncio
    async def test_fetch_channel_history_success(
        self,
        mattermost_channel,
        mock_http_client,
    ):
        """Should fetch and format channel history."""
        mock_http_client.expect_get(
            url="/api/v4/channels/channel_123/posts",
            response_status=200,
            response_json={
                "order": ["post1", "post2"],
                "posts": {
                    "post1": {
                        "id": "post1",
                        "user_id": "user_abc",
                        "message": "Hello",
                    },
                    "post2": {
                        "id": "post2",
                        "user_id": "bot_123",
                        "message": "Hi there",
                    },
                },
            },
        )
        mattermost_channel._http = mock_http_client
        mattermost_channel._bot_id = "bot_123"

        result = await mattermost_channel._fetch_channel_history(
            mm_channel_id="channel_123",
            per_page=10,
        )

        assert "[Recent 10 DM context messages]" in result
        assert "User: Hello" in result
        assert "Bot: Hi there" in result

    @pytest.mark.asyncio
    async def test_fetch_channel_history_api_error(
        self,
        mattermost_channel,
        mock_http_client,
    ):
        """Should return empty string on API error."""
        mock_http_client.expect_get(
            url="/api/v4/channels/channel_123/posts",
            response_status=403,
        )
        mattermost_channel._http = mock_http_client

        result = await mattermost_channel._fetch_channel_history(
            mm_channel_id="channel_123",
        )

        assert result == ""


# =============================================================================
# P1: Send Methods
# =============================================================================


class TestMattermostSend:
    """Tests for send and send_media methods."""

    @pytest.mark.asyncio
    async def test_send_success(self, mattermost_channel, mock_http_client):
        """Should send text message successfully."""
        mock_http_client.expect_post(
            url="/api/v4/posts",
            response_status=201,
        )
        mattermost_channel._http = mock_http_client

        await mattermost_channel.send(
            to_handle="channel_123",
            text="Hello World",
            meta={"root_id": "root_456"},
        )

        call_args = mock_http_client._requests[-1]
        assert call_args["kwargs"]["json"]["message"] == "Hello World"

    @pytest.mark.asyncio
    async def test_send_disabled_channel(
        self,
        mattermost_channel,
        mock_http_client,
    ):
        """Should do nothing when channel is disabled."""
        mattermost_channel.enabled = False
        mattermost_channel._http = mock_http_client

        await mattermost_channel.send(
            to_handle="channel_123",
            text="Hello",
        )

        assert mock_http_client.call_count == 0

    @pytest.mark.asyncio
    async def test_send_no_channel_id(
        self,
        mattermost_channel,
        mock_http_client,
    ):
        """Should do nothing when no channel ID."""
        mattermost_channel._http = mock_http_client

        await mattermost_channel.send(
            to_handle="",
            text="Hello",
        )

        assert mock_http_client.call_count == 0

    @pytest.mark.asyncio
    async def test_send_chunks_long_text(
        self,
        mattermost_channel,
        mock_http_client,
    ):
        """Should split and send long text in chunks."""
        mock_http_client.expect_post(
            url="/api/v4/posts",
            response_status=201,
        )
        mock_http_client.expect_post(
            url="/api/v4/posts",
            response_status=201,
        )
        mattermost_channel._http = mock_http_client

        long_text = "A" * 5000  # Exceeds MATTERMOST_POST_CHUNK_SIZE
        await mattermost_channel.send(
            to_handle="channel_123",
            text=long_text,
        )

        assert mock_http_client.call_count >= 2

    @pytest.mark.asyncio
    async def test_send_media_image(
        self,
        mattermost_channel,
        mock_http_client,
        tmp_path: Path,
    ):
        """Should upload and send image."""
        # Create a test image file
        test_file = tmp_path / "test_image.png"
        test_file.write_bytes(b"fake_image_data")

        mock_http_client.expect_post(
            url="/api/v4/files",
            response_status=201,
            response_json={"file_infos": [{"id": "file_123"}]},
        )
        mock_http_client.expect_post(
            url="/api/v4/posts",
            response_status=201,
        )
        mattermost_channel._http = mock_http_client

        from copaw.app.channels.base import ImageContent, ContentType

        part = ImageContent(type=ContentType.IMAGE, image_url=str(test_file))

        await mattermost_channel.send_media(
            to_handle="channel_123",
            part=part,
            meta={},
        )

        # Should upload file and then post
        assert mock_http_client.call_count >= 2

    @pytest.mark.asyncio
    async def test_send_media_file_not_found(
        self,
        mattermost_channel,
        mock_http_client,
    ):
        """Should handle missing file gracefully."""
        mattermost_channel._http = mock_http_client

        from copaw.app.channels.base import FileContent, ContentType

        part = FileContent(
            type=ContentType.FILE,
            file_url="/nonexistent/file.txt",
        )

        await mattermost_channel.send_media(
            to_handle="channel_123",
            part=part,
            meta={},
        )

        # Should not crash, file upload should fail but not raise


# =============================================================================
# P1: File Operations
# =============================================================================


class TestMattermostFileOperations:
    """Tests for file download and upload."""

    @pytest.mark.asyncio
    async def test_upload_file_success(
        self,
        mattermost_channel,
        mock_http_client,
        tmp_path: Path,
    ):
        """Should upload file and return file_id."""
        test_file = tmp_path / "upload.txt"
        test_file.write_text("test content")

        mock_http_client.expect_post(
            url="/api/v4/files",
            response_status=201,
            response_json={"file_infos": [{"id": "file_abc"}]},
        )
        mattermost_channel._http = mock_http_client

        result = await mattermost_channel._upload_file(
            mm_channel_id="channel_123",
            local_path=str(test_file),
        )

        assert result == "file_abc"

    @pytest.mark.asyncio
    async def test_upload_file_not_found(
        self,
        mattermost_channel,
        mock_http_client,
    ):
        """Should return None when file not found."""
        mattermost_channel._http = mock_http_client

        result = await mattermost_channel._upload_file(
            mm_channel_id="channel_123",
            local_path="/nonexistent/file.txt",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_upload_file_api_error(
        self,
        mattermost_channel,
        mock_http_client,
        tmp_path: Path,
    ):
        """Should return None on API error."""
        test_file = tmp_path / "upload.txt"
        test_file.write_text("test")

        mock_http_client.expect_post(
            url="/api/v4/files",
            response_status=500,
            response_text="Server Error",
        )
        mattermost_channel._http = mock_http_client

        result = await mattermost_channel._upload_file(
            mm_channel_id="channel_123",
            local_path=str(test_file),
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_download_file_success(
        self,
        mattermost_channel,
        mock_http_client,
    ):
        """Should download file and return local path."""
        mock_http_client.expect_get(
            url="/api/v4/files/file_123",
            response_status=200,
            response_text="file content",
        )
        mattermost_channel._http = mock_http_client

        result = await mattermost_channel._download_file(
            file_id="file_123",
            filename_hint="document.pdf",
        )

        assert result is not None
        assert result.endswith(".pdf")

    @pytest.mark.asyncio
    async def test_download_file_api_error(
        self,
        mattermost_channel,
        mock_http_client,
    ):
        """Should return None on API error."""
        mock_http_client.expect_get(
            url="/api/v4/files/file_123",
            response_status=404,
        )
        mattermost_channel._http = mock_http_client

        result = await mattermost_channel._download_file(
            file_id="file_123",
        )

        assert result is None


# =============================================================================
# P1: Typing Indicators
# =============================================================================


class TestMattermostTyping:
    """Tests for typing indicator functionality."""

    @pytest.mark.asyncio
    async def test_start_typing_creates_task(self, mattermost_channel):
        """Should create typing task when started."""
        mattermost_channel._bot_id = "bot_123"
        mattermost_channel._typing_loop = AsyncMock()

        mattermost_channel._start_typing("channel_123", "root_456")

        assert "channel_123" in mattermost_channel._typing_tasks
        task = mattermost_channel._typing_tasks["channel_123"]
        assert task is not None

        # Cleanup
        mattermost_channel._stop_typing("channel_123")

    @pytest.mark.asyncio
    async def test_stop_typing_cancels_task(self, mattermost_channel):
        """Should cancel typing task when stopped."""
        mattermost_channel._bot_id = "bot_123"

        # Create a typing task
        async def mock_loop():
            await asyncio.sleep(60)

        task = asyncio.create_task(mock_loop())
        mattermost_channel._typing_tasks["channel_123"] = task

        mattermost_channel._stop_typing("channel_123")

        # Give event loop a chance to process the cancellation
        await asyncio.sleep(0)

        assert "channel_123" not in mattermost_channel._typing_tasks
        assert task.cancelled() or task.done()

    @pytest.mark.asyncio
    async def test_typing_loop_sends_request(
        self,
        mattermost_channel,
        mock_http_client,
    ):
        """Should send typing request."""
        mock_http_client.expect_post(
            url="/api/v4/users/bot_123/typing",
            response_status=200,
        )
        mattermost_channel._http = mock_http_client
        mattermost_channel._bot_id = "bot_123"

        # Run typing loop briefly
        task = asyncio.create_task(
            mattermost_channel._typing_loop("channel_123", "root_456"),
        )

        # Let it run once
        await asyncio.sleep(0.1)
        task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass

        # Should have made at least one typing request
        assert mock_http_client.call_count >= 1


# =============================================================================
# P1: Message Event Handling
# =============================================================================


class TestMattermostIsTriggered:
    """Tests for _is_triggered method."""

    def test_is_triggered_dm(self, mattermost_channel):
        """Should trigger on DM messages."""
        mattermost_channel._bot_id = "bot_123"
        mattermost_channel._bot_username = "testbot"

        post = {
            "user_id": "user_abc",
            "message": "Hello",
            "root_id": "",
        }

        result = mattermost_channel._is_triggered(post, channel_type="D")

        assert result is True

    def test_is_triggered_mention(self, mattermost_channel):
        """Should trigger on bot mention."""
        mattermost_channel._bot_id = "bot_123"
        mattermost_channel._bot_username = "testbot"

        post = {
            "user_id": "user_abc",
            "message": "Hey @testbot help me",
            "root_id": "",
        }

        result = mattermost_channel._is_triggered(post, channel_type="O")

        assert result is True

    def test_is_triggered_thread_follow(self, mattermost_channel):
        """Should trigger on thread participation."""
        mattermost_channel._bot_id = "bot_123"
        mattermost_channel._thread_follow = True
        mattermost_channel._participated_threads.add("thread_abc")

        post = {
            "user_id": "user_abc",
            "message": "Hello",
            "root_id": "thread_abc",
        }

        result = mattermost_channel._is_triggered(post, channel_type="O")

        assert result is True

    def test_is_triggered_skip_bot_message(self, mattermost_channel):
        """Should not trigger on bot's own messages."""
        mattermost_channel._bot_id = "bot_123"

        post = {
            "user_id": "bot_123",
            "message": "Hello",
        }

        result = mattermost_channel._is_triggered(post, channel_type="O")

        assert result is False

    def test_is_triggered_no_mention_not_dm(self, mattermost_channel):
        """Should not trigger without mention in non-DM."""
        mattermost_channel._bot_id = "bot_123"
        mattermost_channel._bot_username = "testbot"

        post = {
            "user_id": "user_abc",
            "message": "Hello everyone",
            "root_id": "",
        }

        result = mattermost_channel._is_triggered(post, channel_type="O")

        assert result is False


class TestMattermostGetContextPrefix:
    """Tests for _get_context_prefix method."""

    @pytest.mark.asyncio
    async def test_get_context_prefix_first_dm(
        self,
        mattermost_channel,
        mock_http_client,
    ):
        """Should fetch channel history on first DM."""
        mock_http_client.expect_get(
            url="/api/v4/channels/dm_123/posts",
            response_status=200,
            response_json={
                "order": ["post1"],
                "posts": {
                    "post1": {
                        "user_id": "user_abc",
                        "message": "Previous message",
                    },
                },
            },
        )
        mattermost_channel._http = mock_http_client
        mattermost_channel._bot_id = "bot_123"

        result = await mattermost_channel._get_context_prefix(
            session_id="mattermost_dm:dm_123",
            mm_channel_id="dm_123",
            original_root_id="",
            post_id="post_123",
            is_dm=True,
        )

        assert "Previous message" in result
        assert "mattermost_dm:dm_123" in mattermost_channel._seen_sessions

    @pytest.mark.asyncio
    async def test_get_context_prefix_thread(
        self,
        mattermost_channel,
        mock_http_client,
    ):
        """Should fetch thread history for threads."""
        mock_http_client.expect_get(
            url="/api/v4/posts/root_123/thread",
            response_status=200,
            response_json={
                "order": ["post1"],
                "posts": {
                    "post1": {
                        "user_id": "user_abc",
                        "message": "Thread message",
                        "create_at": 1000,
                    },
                },
            },
        )
        mattermost_channel._http = mock_http_client
        mattermost_channel._bot_id = "bot_123"

        result = await mattermost_channel._get_context_prefix(
            session_id="mattermost_thread:root_123",
            mm_channel_id="channel_abc",
            original_root_id="root_123",
            post_id="new_post",
            is_dm=False,
        )

        assert "Thread message" in result

    @pytest.mark.asyncio
    async def test_get_context_prefix_cached_session(self, mattermost_channel):
        """Should return empty string for cached session."""
        mattermost_channel._seen_sessions.add("mattermost_dm:dm_123")

        result = await mattermost_channel._get_context_prefix(
            session_id="mattermost_dm:dm_123",
            mm_channel_id="dm_123",
            original_root_id="",
            post_id="post_123",
            is_dm=True,
        )

        assert result == ""


class TestMattermostProcessAttachments:
    """Tests for _process_attachments method."""

    @pytest.mark.asyncio
    async def test_process_attachments_image(
        self,
        mattermost_channel,
        mock_http_client,
    ):
        """Should process image attachment."""
        mock_http_client.expect_get(
            url="/api/v4/files/file_123",
            response_status=200,
            response_text="fake_image",
        )
        mattermost_channel._http = mock_http_client

        post = {
            "file_ids": ["file_123"],
            "metadata": {
                "files": [{"id": "file_123", "name": "image.png"}],
            },
        }

        parts = await mattermost_channel._process_attachments(post)

        assert len(parts) == 1

    @pytest.mark.asyncio
    async def test_process_attachments_document(
        self,
        mattermost_channel,
        mock_http_client,
    ):
        """Should process document attachment."""
        mock_http_client.expect_get(
            url="/api/v4/files/file_456",
            response_status=200,
            response_text="document content",
        )
        mattermost_channel._http = mock_http_client

        post = {
            "file_ids": ["file_456"],
            "metadata": {
                "files": [{"id": "file_456", "name": "document.pdf"}],
            },
        }

        parts = await mattermost_channel._process_attachments(post)

        assert len(parts) == 1

    @pytest.mark.asyncio
    async def test_process_attachments_download_failure(
        self,
        mattermost_channel,
        mock_http_client,
    ):
        """Should handle download failure gracefully."""
        mock_http_client.expect_get(
            url="/api/v4/files/file_789",
            response_status=404,
        )
        mattermost_channel._http = mock_http_client

        post = {
            "file_ids": ["file_789"],
            "metadata": {
                "files": [{"id": "file_789", "name": "missing.pdf"}],
            },
        }

        parts = await mattermost_channel._process_attachments(post)

        assert len(parts) == 0

    @pytest.mark.asyncio
    async def test_process_attachments_empty(self, mattermost_channel):
        """Should handle post with no attachments."""
        post = {"file_ids": []}

        parts = await mattermost_channel._process_attachments(post)

        assert len(parts) == 0


class TestMattermostOnPostedEvent:
    """Tests for _on_posted_event method."""

    @pytest.mark.asyncio
    async def test_on_posted_event_dm(
        self,
        mattermost_channel,
        mock_http_client,
    ):
        """Should handle DM event."""
        mock_http_client.expect_get(
            url="/api/v4/channels/dm_123/posts",
            response_status=200,
            response_json={"order": [], "posts": {}},
        )
        mattermost_channel._http = mock_http_client
        mattermost_channel._bot_id = "bot_123"
        mattermost_channel._bot_username = "testbot"
        mattermost_channel._enqueue = MagicMock()

        event_data = {
            "event": "posted",
            "data": {
                "channel_type": "D",
                "post": json.dumps(
                    {
                        "id": "post_123",
                        "user_id": "user_abc",
                        "channel_id": "dm_123",
                        "message": "Hello bot",
                        "root_id": "",
                    },
                ),
            },
        }

        await mattermost_channel._on_posted_event(event_data)

        assert mattermost_channel._enqueue.called
        call_args = mattermost_channel._enqueue.call_args[0][0]
        assert call_args["sender_id"] == "user_abc"
        assert call_args["meta"]["mm_channel_id"] == "dm_123"

    @pytest.mark.asyncio
    async def test_on_posted_event_with_mention(
        self,
        mattermost_channel,
        mock_http_client,
    ):
        """Should handle event with bot mention."""
        mock_http_client.expect_get(
            url="/api/v4/channels/channel_123/posts",
            response_status=200,
            response_json={"order": [], "posts": {}},
        )
        mattermost_channel._http = mock_http_client
        mattermost_channel._bot_id = "bot_123"
        mattermost_channel._bot_username = "testbot"
        mattermost_channel._enqueue = MagicMock()

        event_data = {
            "event": "posted",
            "data": {
                "channel_type": "O",
                "post": json.dumps(
                    {
                        "id": "post_123",
                        "user_id": "user_abc",
                        "channel_id": "channel_123",
                        "message": "Hey @testbot help",
                        "root_id": "",
                    },
                ),
            },
        }

        await mattermost_channel._on_posted_event(event_data)

        assert mattermost_channel._enqueue.called
        # Should have cleaned the mention from text
        call_args = mattermost_channel._enqueue.call_args[0][0]
        content_text = str(call_args["content_parts"])
        assert "@testbot" not in content_text

    @pytest.mark.asyncio
    async def test_on_posted_event_not_triggered(self, mattermost_channel):
        """Should skip non-triggered events."""
        mattermost_channel._enqueue = MagicMock()
        mattermost_channel._bot_id = "bot_123"
        mattermost_channel._bot_username = "testbot"

        event_data = {
            "event": "posted",
            "data": {
                "channel_type": "O",
                "post": json.dumps(
                    {
                        "id": "post_123",
                        "user_id": "user_abc",
                        "channel_id": "channel_123",
                        "message": "Just a regular message",  # No mention
                        "root_id": "",
                    },
                ),
            },
        }

        await mattermost_channel._on_posted_event(event_data)

        assert not mattermost_channel._enqueue.called


# =============================================================================
# P1: Text Chunking
# =============================================================================


class TestMattermostChunkText:
    """Tests for _chunk_text method."""

    def test_chunk_text_short(self, mattermost_channel):
        """Should not chunk short text."""
        text = "Short message"

        chunks = mattermost_channel._chunk_text(text)

        assert len(chunks) == 1
        assert chunks[0] == text

    def test_chunk_text_empty(self, mattermost_channel):
        """Should return empty list for empty text."""
        chunks = mattermost_channel._chunk_text("")

        assert chunks == []

    def test_chunk_text_long(self, mattermost_channel):
        """Should chunk long text at boundaries."""
        # Create text longer than MATTERMOST_POST_CHUNK_SIZE
        from copaw.app.channels.mattermost.channel import (
            MATTERMOST_POST_CHUNK_SIZE,
        )

        text = "A" * (MATTERMOST_POST_CHUNK_SIZE + 1000)

        chunks = mattermost_channel._chunk_text(text)

        assert len(chunks) > 1
        # Each chunk should be within limit
        for chunk in chunks:
            assert len(chunk) <= MATTERMOST_POST_CHUNK_SIZE

    def test_chunk_text_breaks_at_newline(self, mattermost_channel):
        """Should prefer to break at newlines."""
        from copaw.app.channels.mattermost.channel import (
            MATTERMOST_POST_CHUNK_SIZE,
        )

        # Create text with newlines over the limit
        line = "A" * 100 + "\n"
        repeats = (MATTERMOST_POST_CHUNK_SIZE // 100) + 5
        text = line * repeats

        chunks = mattermost_channel._chunk_text(text)

        assert len(chunks) >= 1
        # Chunks should prefer newline boundaries when possible


# =============================================================================
# P2: Lifecycle (Start/Stop)
# =============================================================================


class TestMattermostLifecycle:
    """Tests for channel lifecycle management."""

    @pytest.mark.asyncio
    async def test_start_disabled_channel(self, mattermost_channel):
        """Starting disabled channel should succeed without action."""
        mattermost_channel.enabled = False

        await mattermost_channel.start()

        assert mattermost_channel._task is None

    @pytest.mark.asyncio
    async def test_start_creates_task(self, mattermost_channel):
        """Start should create websocket task."""
        with patch.object(
            mattermost_channel,
            "_init_bot_info",
            AsyncMock(return_value=True),
        ):
            with patch.object(
                mattermost_channel,
                "_websocket_loop",
                AsyncMock(),
            ):
                await mattermost_channel.start()

                assert mattermost_channel._task is not None

                # Cancel task to clean up
                mattermost_channel._task.cancel()
                try:
                    await mattermost_channel._task
                except asyncio.CancelledError:
                    pass

    @pytest.mark.asyncio
    async def test_stop_disabled_channel(self, mattermost_channel):
        """Stopping disabled channel should succeed."""
        mattermost_channel.enabled = False

        await mattermost_channel.stop()

        # Should not raise

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self, mattermost_channel):
        """Stop should cancel running task."""

        async def mock_task():
            await asyncio.sleep(60)

        mattermost_channel.enabled = True
        mattermost_channel._task = asyncio.create_task(mock_task())
        mattermost_channel._http = MockHttpxClient()

        await mattermost_channel.stop()

        assert mattermost_channel._task is None

    @pytest.mark.asyncio
    async def test_stop_closes_http(self, mattermost_channel):
        """Stop should close HTTP client."""
        mock_http = MockHttpxClient()
        mattermost_channel.enabled = True
        mattermost_channel._http = mock_http

        await mattermost_channel.stop()

        assert mock_http.closed is True

    @pytest.mark.asyncio
    async def test_stop_typing_tasks(self, mattermost_channel):
        """Stop should cancel typing tasks."""

        async def mock_typing():
            await asyncio.sleep(60)

        mattermost_channel.enabled = True
        mattermost_channel._typing_tasks["channel_123"] = asyncio.create_task(
            mock_typing(),
        )
        mattermost_channel._http = MockHttpxClient()

        await mattermost_channel.stop()

        assert "channel_123" not in mattermost_channel._typing_tasks


# =============================================================================
# P2: Allowlist Check
# =============================================================================


class TestMattermostAllowlist:
    """Tests for _check_allowlist method (inherited from BaseChannel)."""

    def test_check_allowlist_open_policy(self, mattermost_channel):
        """Open policy should allow all users."""
        mattermost_channel.dm_policy = "open"

        allowed, error = mattermost_channel._check_allowlist("any_user", False)

        assert allowed is True
        assert error is None

    def test_check_allowlist_dm_allowlist_authorized(self, mattermost_channel):
        """DM allowlist should allow authorized users."""
        mattermost_channel.dm_policy = "allowlist"
        mattermost_channel.allow_from = {"user123"}

        allowed, error = mattermost_channel._check_allowlist("user123", False)

        assert allowed is True
        assert error is None

    def test_check_allowlist_dm_allowlist_unauthorized(
        self,
        mattermost_channel,
    ):
        """DM allowlist should block unauthorized users."""
        mattermost_channel.dm_policy = "allowlist"
        mattermost_channel.allow_from = {"other_user"}
        mattermost_channel.deny_message = "Custom denial"

        allowed, error = mattermost_channel._check_allowlist("user123", False)

        assert allowed is False
        assert error == "Custom denial"

    def test_check_allowlist_dm_default_deny_message(self, mattermost_channel):
        """Should use default deny message when not configured."""
        mattermost_channel.dm_policy = "allowlist"
        mattermost_channel.allow_from = set()
        mattermost_channel.deny_message = ""

        allowed, error = mattermost_channel._check_allowlist("user123", False)

        assert allowed is False
        assert "not authorized" in error
        assert "user123" in error


# =============================================================================
# P2: Edge Cases
# =============================================================================


class TestMattermostEdgeCases:
    """Additional edge case tests."""

    def test_default_media_dir(self, mock_process_handler):
        """Should use default media dir when not specified."""
        from copaw.app.channels.mattermost.channel import (
            MattermostChannel,
            _DEFAULT_MEDIA_DIR,
        )

        channel = MattermostChannel(
            process=mock_process_handler,
            enabled=True,
            url="https://mm.example.com",
            bot_token="token123",
        )

        assert channel._media_dir == _DEFAULT_MEDIA_DIR

    @pytest.mark.asyncio
    async def test_init_bot_info_partial_response(
        self,
        mattermost_channel,
        mock_http_client,
    ):
        """Should handle partial response from users/me."""
        mock_http_client.expect_get(
            url="/api/v4/users/me",
            response_status=200,
            response_json={"id": "user_123"},  # Missing username
        )
        mattermost_channel._http = mock_http_client

        result = await mattermost_channel._init_bot_info()

        assert result is True
        assert mattermost_channel._bot_id == "user_123"
        assert mattermost_channel._bot_username == ""

    def test_get_thread_target_order_with_bot_replies(
        self,
        mattermost_channel,
    ):
        """Should correctly identify gap when bot has replied."""
        mattermost_channel._bot_id = "bot_123"

        order = ["post1", "post2", "post3", "post4"]
        posts = {
            "post1": {"user_id": "user_abc", "message": "Hello"},
            "post2": {"user_id": "bot_123", "message": "Bot reply"},
            "post3": {"user_id": "user_abc", "message": "Follow up"},
            "post4": {"user_id": "user_abc", "message": "Another message"},
        }

        target_order, label = mattermost_channel._get_thread_target_order(
            order,
            posts,
            last_bot_idx=1,
        )

        assert len(target_order) == 2
        assert target_order == ["post3", "post4"]
        assert "supplement" in label

    def test_get_thread_target_order_first_time(self, mattermost_channel):
        """Should return full history when bot hasn't replied."""
        order = ["post1", "post2"]
        posts = {
            "post1": {"user_id": "user_abc", "message": "Hello"},
            "post2": {"user_id": "user_def", "message": "Hi"},
        }

        target_order, label = mattermost_channel._get_thread_target_order(
            order,
            posts,
            last_bot_idx=-1,
        )

        assert target_order == order
        assert "history" in label
