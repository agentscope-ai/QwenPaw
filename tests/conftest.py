# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
# pylint: disable=reimported,unused-argument,unnecessary-pass
"""
Global pytest fixtures for CoPaw test suite.

This module provides shared fixtures for testing CoPaw components.
All fixtures are designed to be isolated, safe, and easy to use.
"""

import os
import shutil
import sys
import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# =============================================================================
# Third-Party Library Mocks
# =============================================================================
# Mock missing third-party libraries before any imports
_MISSING_MODULES = {
    "aibot",  # WeCom AI Bot SDK
    "lark_oapi",  # Feishu Lark SDK
}

for _module in _MISSING_MODULES:
    if _module not in sys.modules:
        sys.modules[_module] = MagicMock()


# =============================================================================
# Directory Fixtures
# =============================================================================


@pytest.fixture
def temp_workspace() -> Generator[Path, None, None]:
    """Provide a temporary workspace directory.

    Creates an isolated temporary directory that is cleaned up after the test.
    Use this for file operations that need a clean workspace.

    Yields:
        Path to the temporary directory.

    Example:
        def test_file_operation(temp_workspace):
            file_path = temp_workspace / "test.txt"
            file_path.write_text("content")
            assert file_path.read_text() == "content"
    """
    temp_dir = tempfile.mkdtemp(prefix="copaw_test_")
    try:
        yield Path(temp_dir)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def temp_copaw_home(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[Path, None, None]:
    """Provide an isolated CoPaw HOME environment.

    Creates a temporary directory and sets it as both HOME and COPAW_HOME
    environment variables. Also clears any sensitive environment variables
    that could interfere with tests.

    Yields:
        Path to the temporary CoPaw home directory.

    Example:
        def test_config_loading(temp_copaw_home):
            # This test runs in an isolated environment
            config_path = temp_copaw_home / ".copaw" / "config.yaml"
            # ... test config operations
    """
    temp_dir = tempfile.mkdtemp(prefix="copaw_home_")
    temp_path = Path(temp_dir)

    # Create standard subdirectories
    (temp_path / ".copaw").mkdir(exist_ok=True)
    (temp_path / ".copaw" / "skills").mkdir(exist_ok=True)
    (temp_path / ".copaw" / "logs").mkdir(exist_ok=True)

    # Store original values (for potential future use)
    _ = os.environ.get("HOME")  # noqa: F841
    _ = os.environ.get("COPAW_HOME")  # noqa: F841

    # Set isolated environment
    monkeypatch.setenv("HOME", temp_dir)
    monkeypatch.setenv("COPAW_HOME", str(temp_path / ".copaw"))

    # Clear sensitive tokens to prevent accidental API calls
    sensitive_vars = [
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "DASHSCOPE_API_KEY",
        "DINGTALK_APP_KEY",
        "DINGTALK_APP_SECRET",
        "FEISHU_APP_ID",
        "FEISHU_APP_SECRET",
        "DISCORD_TOKEN",
        "TELEGRAM_BOT_TOKEN",
    ]
    for var in sensitive_vars:
        monkeypatch.delenv(var, raising=False)

    try:
        yield temp_path
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# =============================================================================
# Mock Fixtures
# =============================================================================


@pytest.fixture
def mock_llm_provider() -> MagicMock:
    """Provide a mock LLM provider for testing.

    Use this when testing components that depend on LLM providers but you don't
    want to make real API calls (e.g., testing agent logic, skill execution).

    Pre-configured methods:
        - chat(): returns "Mock response"
        - chat_stream(): yields ["Hello", " ", "world"]
        - embed(): returns 1536-dim vector
        - complete(): returns "Completed text"

    Returns:
        MagicMock configured as an LLM provider.

    Example - Testing skill that uses LLM:
        def test_summarize_skill(mock_llm_provider):
            # Configure mock response for this test
            mock_llm_provider.chat.return_value = "This is a summary"

            # Create skill with mock provider
            skill = SummarizeSkill(provider=mock_llm_provider)
            result = skill.run(text="Long text...")

            # Verify skill used provider correctly
            assert result == "This is a summary"
            mock_llm_provider.chat.assert_called_once()

    Example - Testing agent behavior:
        def test_agent_handles_llm_error(mock_llm_provider):
            # Simulate LLM failure
            mock_llm_provider.chat.side_effect = RuntimeError("API Error")

            agent = MyAgent(provider=mock_llm_provider)
            with pytest.raises(AgentError):
                agent.process("Hello")
    """
    mock = MagicMock()

    # Configure common methods
    mock.chat.return_value = "Mock response"
    mock.chat_stream.return_value = iter(["Hello", " ", "world"])
    mock.embed.return_value = [0.1] * 1536  # Standard embedding size
    mock.complete.return_value = "Completed text"

    # Add metadata
    mock.model_name = "gpt-mock"
    mock.is_available.return_value = True

    return mock


@pytest.fixture
def mock_channel() -> MagicMock:
    """Provide a mock channel for testing.

    Use this when testing components that interact with channels but you don't
    want to connect to real messaging services (e.g., testing agent responses,
    message formatting, channel manager logic).

    Pre-configured methods:
        - send_message(): returns True
        - send_file(): returns True
        - receive_message(): returns None
        - is_connected(): returns True

    Returns:
        MagicMock configured as a Channel.

    Example - Testing agent output formatting:
        def test_agent_sends_formatted_message(mock_channel):
            # Configure mock
            mock_channel.send_message.return_value = True

            # Create agent with mock channel
            agent = Agent(channel=mock_channel)
            agent.process("Hello")

            # Verify channel received properly formatted message
            call_args = mock_channel.send_message.call_args
            assert "formatted" in call_args.kwargs

    Example - Testing message router:
        def test_router_selects_correct_channel(mock_channel):
            # Setup multiple channels
            mock_dingtalk = MagicMock()
            mock_dingtalk.channel_type = "dingtalk"

            router = MessageRouter(channels={"dingtalk": mock_dingtalk})
            router.route(to="dingtalk", message="Hi")

            # Verify correct channel was used
            mock_dingtalk.send_message.assert_called_once_with("Hi")

    Example - Testing channel failure handling:
        def test_agent_retries_on_channel_failure(mock_channel):
            # Simulate send failure then success
            mock_channel.send_message.side_effect = [False, False, True]

            agent = Agent(channel=mock_channel, retry_policy= Retry3Times())
            agent.process("Hello")

            # Verify 3 attempts were made
            assert mock_channel.send_message.call_count == 3
    """
    mock = MagicMock()

    mock.send_message.return_value = True
    mock.send_file.return_value = True
    mock.receive_message.return_value = None
    mock.is_connected.return_value = True
    mock.channel_type = "mock"

    return mock


# =============================================================================
# Configuration Fixtures
# =============================================================================


@pytest.fixture
def minimal_config() -> dict[str, Any]:
    """Provide a minimal valid CoPaw configuration.

    Returns a dictionary with the minimum required configuration
    for starting the application in test mode.

    Returns:
        Dictionary with minimal configuration.
    """
    return {
        "version": "1.0.0",
        "llm": {
            "provider": "mock",
            "model": "gpt-mock",
        },
        "channels": [],
        "skills": [],
        "memory": {
            "enabled": False,
        },
    }


# =============================================================================
# Helper Fixtures
# =============================================================================


@pytest.fixture(scope="session")
def test_data_dir() -> Path:
    """Provide the path to the test data directory.

    Returns:
        Path to tests/data directory, creating it if needed.
    """
    data_dir = Path(__file__).parent / "data"
    data_dir.mkdir(exist_ok=True)
    return data_dir


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure a clean environment for tests.

    Clears environment variables that could affect test behavior.
    Use this for tests sensitive to environment state.

    Example:
        def test_env_loading(clean_env, monkeypatch):
            monkeypatch.setenv("COPAW_CONFIG", "/tmp/config.yaml")
            # Test config loading from env
    """
    # Clear CoPaw-specific environment variables
    vars_to_clear = [
        "COPAW_HOME",
        "COPAW_CONFIG",
        "COPAW_LOG_LEVEL",
        "COPAW_DEBUG",
    ]
    for var in vars_to_clear:
        monkeypatch.delenv(var, raising=False)


# =============================================================================
# Contract Test Fixtures
# =============================================================================


@pytest.fixture
def mock_process_handler():
    """Provide a mock process handler for channel contract testing.

    Creates an async mock that simulates the process handler interface
    used by channels to process agent requests.

    Returns:
        AsyncMock configured as a ProcessHandler.

    Example:
        def test_channel_process(mock_process_handler):
            channel = MyChannel(process=mock_process_handler)
            # channel will use the mock process handler
    """
    from unittest.mock import AsyncMock, MagicMock

    mock = AsyncMock()

    async def mock_process(*args, **kwargs):
        mock_event = MagicMock()
        mock_event.object = "message"
        mock_event.status = "completed"
        yield mock_event

    mock.side_effect = mock_process
    return mock


@pytest.fixture
def mock_channel_config():
    """Provide a minimal channel configuration for testing.

    Returns:
        MagicMock with common channel config attributes.
    """
    from unittest.mock import MagicMock

    config = MagicMock()
    config.enabled = True
    config.filter_tool_messages = False
    config.filter_thinking = False
    config.dm_policy = "open"
    config.group_policy = "open"
    config.require_mention = False
    return config


@pytest.fixture
def mock_provider_factory():
    """Provide a factory for creating mock providers.

    Returns a factory function that creates mock providers with
    the required interface for testing.

    Example:
        def test_provider_manager(mock_provider_factory):
            mock_provider = mock_provider_factory(id="test", name="Test")
            manager.register(mock_provider)
    """
    from unittest.mock import MagicMock

    def factory(**kwargs):
        mock = MagicMock()
        mock.id = kwargs.get("id", "mock-provider")
        mock.name = kwargs.get("name", "Mock Provider")
        mock.base_url = kwargs.get("base_url", "https://mock.local")
        mock.api_key = kwargs.get("api_key", "mock-key")
        mock.chat_model = kwargs.get("chat_model", "MockChatModel")
        mock.models = kwargs.get("models", [])
        mock.extra_models = kwargs.get("extra_models", [])

        # Async methods
        mock.check_connection = MagicMock(return_value=(True, ""))
        mock.fetch_models = MagicMock(return_value=[])
        mock.check_model_connection = MagicMock(return_value=(True, ""))

        return mock

    return factory


# =============================================================================
# Pytest Hooks
# =============================================================================


def pytest_configure(config: pytest.Config) -> None:
    """Configure pytest with custom markers."""
    # Markers are already defined in pyproject.toml, but we can add
    # additional configuration here if needed
    pass


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Modify test collection to add markers based on test location."""
    for item in items:
        # Auto-mark tests based on directory
        path_str = str(item.path)
        if "/unit/" in path_str:
            item.add_marker(pytest.mark.unit)
        elif "/integration/" in path_str:
            item.add_marker(pytest.mark.integration)
        elif "/e2e/" in path_str:
            item.add_marker(pytest.mark.e2e)

        # TODO: Module-level markers (s_module, a_module, etc.)
        # These will be configured via a flexible mapping file rather than
        # hardcoded paths. Example format (TBD):
        #   - s_module: ["utils/tokenizer", "security/tool_guard"]
        #   - c_module: ["channels/dingtalk", "channels/feishu"]
        # This allows module classification to evolve without code changes.
