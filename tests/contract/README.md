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
│   ├── __init__.py                # ChannelContractTest definition
│   └── test_*_contract.py         # One file per built-in channel
│
└── providers/                     # Provider contracts
    └── test_provider_contract.py
```

## Usage

### Adding a New Channel

```python
# tests/contract/channels/test_slack_contract.py
from tests.contract.channels import ChannelContractTest

class TestSlackChannelContract(ChannelContractTest):
    def create_instance(self):
        from qwenpaw.app.channels.slack.channel import SlackChannel
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
# .github/workflows/tests.yml
- name: Check channel contract coverage
  run: python scripts/check_channel_contracts.py

- name: Run contract tests
  run: pytest tests/contract -v
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
| Built-in Channel Coverage | ✅ 18/18 |
| Static Coverage Gate | ✅ Required CI check |

## Coverage Gate

`scripts/check_channel_contracts.py` reads the built-in registry and inspects
source and tests with Python's AST module. It does not import optional channel
dependencies. The check fails when a registered channel implementation is
missing, does not inherit `BaseChannel`, or has no unambiguous
`ChannelContractTest.create_instance()` factory.

Each built-in channel must have exactly one concrete contract factory. Its
`create_instance()` method must directly return the channel constructor (or
its `from_config()`/`from_env()` factory) using straight-line code with one
`return` statement. Shared contract helpers must mark their factory with
`@abstractmethod` so the static check can distinguish them from runnable
tests.

The factory must live at
`tests/contract/channels/test_<registry-key>_contract.py`, and its concrete
`Test*` class must remain collectable in every supported test environment.
Do not guard required contract coverage with module/class `skip`, `xfail`,
`pytest.importorskip()`, or a skip call in `create_instance()`; mock optional
services and side effects instead. Module/class `pytestmark`, class
decorators, custom metaclasses, and class-level `__test__` overrides are
rejected because their collection behavior is ambiguous to the static
checker. Method-level markers remain available for supplemental tests.

Run it whenever a built-in channel or its contract test changes:

```bash
python scripts/check_channel_contracts.py
```

Plugin-provided channels are outside the built-in registry and should define
their contract coverage within the plugin's own test scope.

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
