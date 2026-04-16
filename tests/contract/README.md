# Contract Test Framework

Prevents "fix one subclass, break others" when modifying base classes.

## Problem

Developer fixes DingTalk file upload by modifying `BaseChannel.send_media()`:
- DingTalk tests pass (tested locally)
- Feishu, Discord, Telegram break in production!

## Solution: Contract Tests

Automatically verify **all subclasses** comply with base class interface contracts.

## Core Mechanism

```
BaseContractTest (abstract base)
    ↓
ChannelContractTest (defines channel contracts)
    ↓
TestDingTalkChannel   TestFeishuChannel   TestDiscordChannel...
    (each implements create_instance())
```

### Contracts Verified

| Category | Verification | Example Issue Caught |
|---------|-------------|---------------------|
| **Abstract Methods** | start(), stop(), send() implemented | New abstract method not implemented |
| **Attributes** | channel, uses_manager_queue exist | Constructor missing attribute |
| **Signatures** | Parameter type compatibility | send() signature changed |
| **Behavior** | resolve_session_id returns str | Return type changed |

## Directory Structure

```
tests/contract/
├── README.md
├── __init__.py                    # Framework core
│
├── channels/                      # Channel contract tests
│   ├── __init__.py
│   ├── test_base_contract.py      # ChannelContractTest definition
│   ├── test_console_contract.py   # ConsoleChannel example
│   └── test_dingtalk_contract.py  # DingTalkChannel
│
└── providers/                     # Future: Provider contracts
    └── __init__.py
```

## Usage

### Adding a New Channel

```python
# tests/contract/channels/test_slack_contract.py
from tests.contract.channels import ChannelContractTest

class TestSlackChannelContract(ChannelContractTest):
    def create_instance(self):
        from src.copaw.app.channels.slack.channel import SlackChannel
        return SlackChannel(process=mock_process, ...)

    # Optional: Slack-specific contracts
    def test_has_webhook_url(self, instance):
        assert hasattr(instance, '_webhook_url')
```

### After Modifying Base Class

```bash
# Run all contract tests
pytest tests/contract/ -v

# If tests fail → subclasses don't meet new contracts → fix before merge
```

### CI Integration

```yaml
# .github/workflows/ci.yml
- name: Contract Tests
  run: pytest tests/contract/ -v
  # Base class changes must pass all subclass contract validations
```

## Comparison

| Aspect | Contract Tests | Integration Tests |
|--------|---------------|-------------------|
| **Purpose** | Verify interface compliance | Verify component collaboration |
| **Scope** | Single class (multiple subclasses) | Multiple components |
| **Speed** | Fast (isolated, no external deps) | Slow (may need real services) |
| **Error Location** | Precise: Subclass X missing method Y | Vague: DingTalk send failed |
| **Base Class Changes** | ✅ Auto-detect breakage | ⚠️ Probabilistic detection |

## Current Status

| Component | Status |
|-----------|--------|
| Framework Core (`BaseContractTest`) | ✅ Done |
| Channel Contracts (`ChannelContractTest`) | ✅ Done |
| ConsoleChannel Example | ✅ Done |
| DingTalkChannel Contract | ✅ Done |
| Other Channels (Feishu/Discord/QQ...) | ⏳ TODO |

## TODO: Add Channel Contracts

Copy `test_dingtalk_contract.py` template for:

- [ ] FeishuChannel
- [ ] DiscordChannel
- [ ] TelegramChannel
- [ ] QQChannel
- [ ] MQTTChannel
- [ ] MattermostChannel
- [ ] MatrixChannel
- [ ] iMessageChannel

## Design Decisions

### 1. Inheritance over Parametrization

```python
# Option A: Inheritance (chosen)
class TestDingTalkContract(ChannelContractTest): ...

# Option B: Parametrization (rejected)
@pytest.mark.parametrize("cls", [DingTalk, Feishu])
def test_contract(cls): ...
```

**Why inheritance:**
- Subclasses can add specific contracts (DingTalk has webhook, Feishu doesn't)
- Clear test discovery (`pytest -v` shows each subclass)
- Follows pytest best practices

### 2. Mock Dependencies

```python
def create_instance(self):
    process = AsyncMock()  # Mock, not real
    return DingTalkChannel(process=process, client_id="test", ...)
```

Contract tests verify **interface**, not **behavior**. Mocks are sufficient.

### 3. Abstract Base Classes

```python
class ChannelContractTest(BaseContractTest):
    @abstractmethod
    def create_instance(self) -> BaseChannel:
        pass  # Forces subclass implementation
```

ABC + pytest ensures unimplemented methods raise errors.
