# Channel Testing Guide

## Overview

This guide explains how to test the Channel module in CoPaw. We use a **contract-first** testing approach where all Channels must satisfy the BaseChannel interface contract.

```
tests/
├── contract/channels/          # Contract tests (PRIMARY) ⭐
│   ├── __init__.py            # ChannelContractTest base class
│   ├── test_console_contract.py    # Official template: simple Channel
│   ├── test_dingtalk_contract.py   # Official template: complex Channel
│   ├── test_feishu_contract.py     # Official template: complex Channel
│   └── test_*_contract.py          # Remaining 8 Channels
│
└── unit/channels/              # Unit test supplements (optional)
    └── test_base_core.py        # BaseChannel internal logic (debounce/merge/permissions)
```

---

## Quick Start

### Run All Channel Tests

```bash
# Run all contract tests (128 tests, all should pass)
pytest tests/contract/channels/ -v

# Check contract coverage
make check-contracts

# Run optional unit tests
pytest tests/unit/channels/test_base_core.py -v
```

### Check Contract Coverage

```bash
$ make check-contracts

📊 Channel Contract Coverage
   Total channels: 11
   With tests:     12
   Missing:        0 ✅

✅ Tested: ConsoleChannel, DingTalkChannel, FeishuChannel,
          DiscordChannel, IMessageChannel, MQTTChannel,
          MatrixChannel, MattermostChannel, QQChannel,
          TelegramChannel, VoiceChannel

🎉 All channels have contract tests!
```

---

## Contract Test Base Class

The `ChannelContractTest` provides **four-layer protection** to catch breaking changes:

| Layer | Test | Catches |
|-------|------|---------|
| 1 | `test_no_abstract_methods_remaining` | New abstract methods in BaseChannel |
| 2 | `test_no_abstractmethods__in_instance` | Cannot instantiate (unimplemented methods) |
| 3 | `test_required_methods_not_raising_not_implemented` | Methods still raising NotImplementedError |
| 4 | `test_start/stop_method_signature_compatible` | Method signature changes breaking subclasses |

---

## Adding a New Channel

### Step 1: Create Contract Test (REQUIRED)

Copy the official template:

```python
# tests/contract/channels/test_yourchannel_contract.py

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from tests.contract.channels import ChannelContractTest

if TYPE_CHECKING:
    from src.copaw.app.channels.base import BaseChannel


class TestYourChannelContract(ChannelContractTest):
    """
    Contract tests for YourChannel.

    Validates that YourChannel properly implements all BaseChannel
    abstract methods and maintains interface compatibility.
    """

    def create_instance(self) -> "BaseChannel":
        """Provide a YourChannel instance for contract testing."""
        from src.copaw.app.channels.yourchannel.channel import YourChannel

        process = AsyncMock()

        return YourChannel(
            process=process,
            enabled=True,
            bot_prefix="[Test]",
            show_tool_details=False,
            filter_tool_messages=True,
            # Add other required parameters here
        )

    # Optional: Add channel-specific contract tests
    def test_your_channel_specific_feature(self, instance):
        """YourChannel-specific: verify custom behavior."""
        assert hasattr(instance, 'your_custom_attribute')
```

### Step 2: Verify Contract Passes

```bash
pytest tests/contract/channels/test_yourchannel_contract.py -v
```

### Step 3: Check Coverage

```bash
make check-contracts
# Should show your channel in the tested list
```

---

## Official Templates

### Template A: Simple Channel (Console)

```python
# tests/contract/channels/test_console_contract.py
"""Official template: Simple channel with minimal configuration."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from tests.contract.channels import ChannelContractTest

if TYPE_CHECKING:
    from src.copaw.app.channels.base import BaseChannel


def create_mock_process_handler():
    """Create a mock process handler for channel testing."""
    mock = AsyncMock()

    async def mock_process(*_args, **_kwargs):
        from unittest.mock import MagicMock

        mock_event = MagicMock()
        mock_event.object = "message"
        mock_event.status = "completed"
        yield mock_event

    mock.side_effect = mock_process
    return mock


class TestConsoleChannelContract(ChannelContractTest):
    """ConsoleChannel contract validation."""

    def create_instance(self) -> "BaseChannel":
        """Provide a ConsoleChannel instance for contract testing."""
        from src.copaw.app.channels.console.channel import ConsoleChannel

        process = create_mock_process_handler()
        return ConsoleChannel(
            process=process,
            enabled=True,
            bot_prefix="[TEST] ",
            show_tool_details=False,
            filter_tool_messages=True,
        )
```

### Template B: Complex Channel with HTTP (DingTalk)

```python
# tests/contract/channels/test_dingtalk_contract.py
"""Official template: Complex channel with token caching and HTTP."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from tests.contract.channels import ChannelContractTest

if TYPE_CHECKING:
    from src.copaw.app.channels.base import BaseChannel


class TestDingTalkChannelContract(ChannelContractTest):
    """DingTalkChannel contract validation."""

    @pytest.fixture(autouse=True)
    def _setup_dingtalk_env(self, tmp_path):
        """Setup isolated environment for DingTalk tests."""
        self._media_dir = tmp_path / ".copaw" / "media"
        self._media_dir.mkdir(parents=True, exist_ok=True)

    def create_instance(self) -> "BaseChannel":
        """Provide a DingTalkChannel instance for contract testing."""
        from src.copaw.app.channels.dingtalk.channel import DingTalkChannel

        process = AsyncMock()

        return DingTalkChannel(
            process=process,
            enabled=True,
            client_id="test_client_id",
            client_secret="test_client_secret",
            bot_prefix="[Test]",
            media_dir=str(self._media_dir),
            show_tool_details=False,
            filter_tool_messages=True,
        )

    # DingTalk-specific contracts
    def test_has_token_caching_attributes(self, instance):
        """DingTalk-specific: must have token caching mechanism."""
        assert hasattr(instance, "_token_value")
        assert hasattr(instance, "_token_expires_at")

    def test_has_session_webhook_store(self, instance):
        """DingTalk-specific: must have session webhook storage."""
        assert hasattr(instance, "_session_webhook_store")
        assert isinstance(instance._session_webhook_store, dict)
```

---

## Testing Scenarios

### Scenario 1: Modifying BaseChannel

When you modify `BaseChannel`, run contract tests for ALL channels:

```bash
# Verify no breaking changes
pytest tests/contract/channels/ -v

# If any test fails, you broke the contract!
```

**Four-layer protection catches**:
- BaseChannel adds new abstract methods
- Method signature changes break compatibility
- Missing required methods
- Methods still raise NotImplementedError

### Scenario 2: Adding a New Channel

```bash
# 1. Create contract test from template
# cp tests/contract/channels/test_console_contract.py \
#    tests/contract/channels/test_yourchannel_contract.py

# 2. Implement create_instance() with your Channel's required parameters

# 3. Run contract tests
pytest tests/contract/channels/test_yourchannel_contract.py -v

# 4. Verify coverage
make check-contracts
```

### Scenario 3: Fixing a Bug

```bash
# 1. Write regression test first
# Add to the Channel's contract test file

# 2. Run test to confirm it fails
pytest tests/contract/channels/test_dingtalk_contract.py -v

# 3. Fix the bug in Channel implementation

# 4. Run all contract tests to ensure no regression
pytest tests/contract/channels/ -v
```

---

## Makefile Commands

```makefile
# Check contract coverage (shows which Channels are missing tests)
make check-contracts

# Run all contract tests
pytest tests/contract/channels/ -v

# Run specific Channel contract tests
pytest tests/contract/channels/test_dingtalk_contract.py -v

# Run unit test supplement (optional)
pytest tests/unit/channels/test_base_core.py -v
```

---

## Contract Test Coverage (Current Status)

```
✅ ConsoleChannel      - Official template (simple)
✅ DingTalkChannel     - Official template (complex with HTTP)
✅ FeishuChannel       - Official template (complex)
✅ DiscordChannel      - Batch generated
✅ TelegramChannel     - Batch generated
✅ QQChannel           - Batch generated
✅ IMessageChannel     - Batch generated
✅ MQTTChannel         - Batch generated
✅ MatrixChannel       - Batch generated
✅ MattermostChannel   - Batch generated
✅ VoiceChannel        - Batch generated

Total: 11 Channels, 12 tested (includes BaseChannel)
Missing: 0
```

---

## Core Principles

### 1. Contract Tests are Primary

Contract tests verify all Channels satisfy the BaseChannel interface. Prevents regressions like "fix Console breaks DingTalk".

### 2. All Channels Have Contract Tests

The official team generated contract tests for all 11 Channels.

### 3. Four-Layer Protection

The `ChannelContractTest` base class has four mechanisms to catch breaking changes:

1. **Abstract method check** - Catches new methods
2. **Instantiation check** - Catches unimplemented methods
3. **Method override check** - Catches NotImplementedError
4. **Signature check** - Catches parameter changes

### 4. Contract Tests = CI Gate

Contract tests must pass in CI. Breaking contracts blocks PRs.

---

## Troubleshooting

### Q: Contract test fails with "unimplemented abstract methods"

**Cause**: BaseChannel added new abstract methods, or your Channel doesn't implement required methods.

**Fix**: Implement the missing methods in your Channel.

### Q: Contract test fails with "contains NotImplementedError"

**Cause**: Your Channel inherited a method from BaseChannel that raises NotImplementedError.

**Fix**: Override the method with a real implementation.

### Q: Contract test fails with signature mismatch

**Cause**: Your method signature doesn't match BaseChannel (e.g., added required parameters).

**Fix**: Ensure your method accepts the same parameters as BaseChannel.

### Q: Import errors when running tests

```bash
# Ensure you're in project root and package is installed
cd /Users/hex/work/CoPaw
pip install -e ".[dev]"
pytest tests/contract/channels/ -v
```

---

## Quick Reference

| Task | Command |
|------|---------|
| Check coverage | `make check-contracts` |
| Run all contract tests | `pytest tests/contract/channels/ -v` |
| Run specific Channel | `pytest tests/contract/channels/test_dingtalk_contract.py -v` |
| Add new Channel test | Copy `test_console_contract.py` template |
| Verify no regression | `pytest tests/contract/channels/ -v` |

---

## Summary

| Aspect | Current Status |
|--------|----------------|
| Channel Coverage | 11/11 (100%) |
| Contract Tests | 128 passing ✅ |
| Official Templates | Console, DingTalk, Feishu |
| Protection Layers | 4 layers |
| CI Gate | Yes - contract tests must pass |

---

📖 [中文版本](channel-testing-guide_zh.md)
