
import sys
import types
from unittest.mock import MagicMock

# Create mock for pydantic and its components
pydantic = types.ModuleType("pydantic")
pydantic.BaseModel = MagicMock
pydantic.Field = MagicMock
pydantic.ConfigDict = MagicMock
pydantic.model_validator = MagicMock
sys.modules["pydantic"] = pydantic

# Create mock for agentscope and its submodules
agentscope = types.ModuleType("agentscope")
sys.modules["agentscope"] = agentscope

agentscope_model = types.ModuleType("agentscope.model")
agentscope_model.ChatModelBase = MagicMock
sys.modules["agentscope.model"] = agentscope_model

agentscope_model_base = types.ModuleType("agentscope.model._model_base")
agentscope_model_base.ChatModelBase = MagicMock
sys.modules["agentscope.model._model_base"] = agentscope_model_base

agentscope_model_response = types.ModuleType("agentscope.model._model_response")
agentscope_model_response.ChatResponse = MagicMock
sys.modules["agentscope.model._model_response"] = agentscope_model_response

agentscope_model_usage = types.ModuleType("agentscope.model._model_usage")
agentscope_model_usage.ChatUsage = MagicMock
sys.modules["agentscope.model._model_usage"] = agentscope_model_usage

agentscope_message = types.ModuleType("agentscope.message")
agentscope_message.TextBlock = MagicMock
agentscope_message.ToolUseBlock = MagicMock
agentscope_message.ThinkingBlock = MagicMock
sys.modules["agentscope.message"] = agentscope_message

import pytest

# Test the core logic of _parse_single_tool_call
def test_parse_single_tool_call_valid():
    from copaw.local_models.tag_parser import _parse_single_tool_call, ParsedToolCall
    raw_text = '{"name": "test_tool", "arguments": {"a": 1}}'
    result = _parse_single_tool_call(raw_text)

    assert result is not None
    assert result.name == "test_tool"
    assert result.arguments == {"a": 1}
    assert result.id.startswith("call_")

def test_parse_single_tool_call_invalid_json():
    from copaw.local_models.tag_parser import _parse_single_tool_call
    # Malformed JSON (missing closing brace)
    raw_text = '{"name": "test_tool", "arguments": {"a": 1}'
    result = _parse_single_tool_call(raw_text)
    assert result is None

def test_parse_single_tool_call_missing_name():
    from copaw.local_models.tag_parser import _parse_single_tool_call
    # Missing required 'name' field
    raw_text = '{"arguments": {"a": 1}}'
    result = _parse_single_tool_call(raw_text)
    assert result is None

def test_parse_single_tool_call_string_arguments():
    from copaw.local_models.tag_parser import _parse_single_tool_call
    # 'arguments' as a JSON-encoded string
    raw_text = '{"name": "test_tool", "arguments": "{\\"a\\": 1}"}'
    result = _parse_single_tool_call(raw_text)
    assert result.name == "test_tool"
    assert result.arguments == {"a": 1}

def test_parse_single_tool_call_invalid_string_arguments():
    from copaw.local_models.tag_parser import _parse_single_tool_call
    # 'arguments' as an invalid JSON-encoded string
    raw_text = '{"name": "test_tool", "arguments": "{\\"a\\": 1"}'
    result = _parse_single_tool_call(raw_text)
    assert result.name == "test_tool"
    assert result.arguments == {}

# Test helper tag checks
def test_text_contains_think_tag():
    from copaw.local_models.tag_parser import text_contains_think_tag
    assert text_contains_think_tag("Some <think> content") is True
    assert text_contains_think_tag("No tag here") is False

def test_text_contains_tool_call_tag():
    from copaw.local_models.tag_parser import text_contains_tool_call_tag
    assert text_contains_tool_call_tag("Some <tool_call> content") is True
    assert text_contains_tool_call_tag("No tag here") is False

# Test extract_thinking_from_text
def test_extract_thinking_from_text_complete():
    from copaw.local_models.tag_parser import extract_thinking_from_text
    text = "Before <think> reasoning </think> After"
    result = extract_thinking_from_text(text)
    assert result.thinking == "reasoning"
    assert result.remaining_text == "Before  After"
    assert result.has_open_tag is False

def test_extract_thinking_from_text_unclosed():
    from copaw.local_models.tag_parser import extract_thinking_from_text
    text = "Before <think> reasoning"
    result = extract_thinking_from_text(text)
    assert result.thinking == "reasoning"
    assert result.remaining_text == "Before"
    assert result.has_open_tag is True

def test_extract_thinking_from_text_none():
    from copaw.local_models.tag_parser import extract_thinking_from_text
    text = "Just some text"
    result = extract_thinking_from_text(text)
    assert result.thinking == ""
    assert result.remaining_text == "Just some text"
    assert result.has_open_tag is False

# Test parse_tool_calls_from_text
def test_parse_tool_calls_from_text_single():
    from copaw.local_models.tag_parser import parse_tool_calls_from_text
    text = 'Some text <tool_call> {"name": "t1", "arguments": {}} </tool_call> more text'
    result = parse_tool_calls_from_text(text)
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "t1"
    assert result.text_before == "Some text"
    assert result.text_after == "more text"
    assert result.has_open_tag is False

def test_parse_tool_calls_from_text_multiple():
    from copaw.local_models.tag_parser import parse_tool_calls_from_text
    text = (
        'Start <tool_call> {"name": "t1", "arguments": {}} </tool_call> '
        'Middle <tool_call> {"name": "t2", "arguments": {}} </tool_call> End'
    )
    result = parse_tool_calls_from_text(text)
    assert len(result.tool_calls) == 2
    assert result.tool_calls[0].name == "t1"
    assert result.tool_calls[1].name == "t2"
    assert result.text_before == "Start"
    assert result.text_after == "End"

def test_parse_tool_calls_from_text_unclosed():
    from copaw.local_models.tag_parser import parse_tool_calls_from_text
    text = 'Start <tool_call> {"name": "t1", "arguments": {}} </tool_call> and then <tool_call> {"name": "t2"'
    result = parse_tool_calls_from_text(text)
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "t1"
    assert result.has_open_tag is True
    assert result.partial_tool_text == ' {"name": "t2"'

def test_parse_tool_calls_from_text_invalid_json():
    from copaw.local_models.tag_parser import parse_tool_calls_from_text
    text = 'Start <tool_call> invalid json </tool_call> End'
    result = parse_tool_calls_from_text(text)
    assert len(result.tool_calls) == 0
    assert result.text_before == "Start"
    assert result.text_after == "End"
