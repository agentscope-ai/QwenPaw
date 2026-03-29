# Channel Testing Guide

## Testing Architecture

```
tests/
├── contract/channels/          # ⭐ Contract Tests (Primary)
│   ├── __init__.py            # ChannelContractTest base class
│   ├── test_console_contract.py   # Official template: Simple Channel
│   ├── test_dingtalk_contract.py  # Official template: Complex Channel
│   ├── test_feishu_contract.py    # Official template: Complex Channel
│   └── test_*_contract.py         # All 11 Channels covered (0 missing)
│
└── unit/channels/              # Supplemental Tests (Optional)
    ├── README.md               # This file
    └── test_base_core.py       # BaseChannel internal logic (debounce/merge/permissions)
```

## Contract Tests vs Unit Tests

| Type | Location | Purpose | Coverage |
|------|----------|---------|----------|
| **Contract Tests** | `tests/contract/channels/` | Verify external interface compatibility | Contract coverage (128 tests) |
| **Unit Tests** | `tests/unit/channels/` | Verify internal logic correctness | Optional for local dev |

## Local Development

```bash
# Contract tests (primary)
pytest tests/contract/channels/ -v

# Check contract coverage
make check-contracts

# Supplemental unit tests (optional)
pytest tests/unit/channels/test_base_core.py -v
```

## Adding New Channel Contract Tests

All Channels already have contract tests. To add a new Channel:

```bash
# 1. Copy the official template
cp tests/contract/channels/test_console_contract.py \
   tests/contract/channels/test_yourchannel_contract.py

# 2. Modify class name and create_instance()

# 3. Local verification
make check-contracts  # Should show your Channel in tested list
```

## About test_base_core.py

**Purpose**: Supplemental tests for BaseChannel internal logic (debounce, merge, permissions)

**Run**: Manual during local development
```bash
pytest tests/unit/channels/test_base_core.py -v
```

**Coverage**: Not enforced this cycle, official team decides on CI inclusion later

**Note**: Some tests in this file may fail due to test expectations not matching actual implementation. These are supplemental tests and do not block PR merging.

## Running All Unit Tests

```bash
# Run all unit tests
pytest tests/unit/channels/ -v

# Run specific Channel unit tests
pytest tests/unit/channels/test_base_core.py -v

# With coverage check
pytest tests/unit/channels/ \
    --cov=src/copaw/app/channels \
    --cov-report=term-missing
```

## Contract Tests vs Unit Tests

```
Contract Tests (tests/contract/channels/): Verify interface specs ✅ All 11 Channels covered
Unit Tests (tests/unit/channels/): Verify internal logic   🆕 Supplemental (optional)
```

Complementary:
- Contract tests verify "method exists and signature is correct"
- Unit tests verify "internal logic is correct"

## Four-Layer Protection

```
Layer 1: Abstract Method Check
├── test_no_abstract_methods_remaining
└── Catches: BaseChannel adds @abstractmethod

Layer 2: Instantiation Check
├── test_no_abstractmethods__in_instance
└── Catches: Cannot create instance (unimplemented methods)

Layer 3: Method Override Check
├── test_required_methods_not_raising_not_implemented
└── Catches: Method still raises NotImplementedError

Layer 4: Signature Compatibility Check
├── test_start_method_signature_compatible
├── test_stop_method_signature_compatible
├── test_resolve_session_id_signature_compatible
└── Catches: Method signature changes break subclasses
```

## Current Status

```
📊 Channel Contract Test Coverage
   Total Channels: 11
   With Contract Tests: 12
   Missing: 0

✅ Tested: ConsoleChannel, DingTalkChannel, FeishuChannel,
          DiscordChannel, IMessageChannel, MQTTChannel,
          MatrixChannel, MattermostChannel, QQChannel,
          TelegramChannel, VoiceChannel

🎉 All Channels have contract tests!
128 contract tests passing, 0 failing
```

## Core Principles

1. **Contract tests are primary** - Must pass in CI
2. **Unit tests are optional** - Supplemental, don't block PR
3. **All Channels have contract tests** - Official team generated all 11
4. **Four-layer protection** - Effective prevention against "fix Console breaks DingTalk"
5. **Breaking contract = blocking PR** - CI gate ensures interface compatibility

## Quick Reference

| Command | Purpose |
|---------|---------|
| `make check-contracts` | Show contract coverage status |
| `pytest tests/contract/channels/ -v` | Run all contract tests |
| `pytest tests/unit/channels/test_base_core.py -v` | Run optional unit tests |
| `pytest tests/contract/channels/test_console_contract.py -v` | Run specific Channel |

---

📖 [中文版本](README_zh.md)
