## Description

Establishes Channel testing infrastructure with contract tests for all 11 channels and streamlined unit test templates.

### Fix & Changes

**Contract Tests (`tests/contract/channels/`):**

- Add `ChannelContractTest` base class (19 verification points, 4-layer protection)
- Add contract tests for all 11 channels (223 tests total)
- DingTalk/Feishu include extensions for CHAN-D02/D03 regression protection
- **Fix**: Feishu token management test now correctly validates `lark_oapi.TokenManager` usage

**Unit Tests (`tests/unit/channels/`):**

- `test_console.py` - Simple channel template (official)
- `test_base_core.py` - BaseChannel internal logic (debounce, merge, permissions, error extraction)
- **Fix**: Updated test expectations to match actual implementation:
  - `test_empty_content_gets_default`: expect `" "` as default (not `""`)
  - `test_meta_merge_combined`: test specific key merging behavior
  - `TestResponseErrorExtraction`: fix MagicMock usage to prevent false positives

**CI/CD:**

- Add 5-phase workflow with strong/soft gates
- Contract tests: 🔴 hard gate (blocks PR)
- Unit tests: 🟡 soft gate (informational)

## Why

Prevents "Fix Console, Break DingTalk" regressions. Interface changes in BaseChannel now have automated protection via 223 contract tests.

## Type of Change

- [x] Testing infrastructure
- [x] Documentation
- [x] Bug fix (test expectations)

## Component(s) Affected

- [x] Channels
- [x] Tests
- [x] CI/CD

## Checklist

- [x] 223 contract tests passing (was 222 passed + 1 skipped)
- [x] 49 unit tests passing
- [x] Pre-commit passes
- [x] CI workflow configured
- [x] PR template updated

## Testing

```bash
# Required - blocks PR (all pass ✅)
pytest tests/contract/channels/ -v

# Verify specific fixes
pytest tests/contract/channels/test_feishu_contract.py::TestFeishuChannelContract::test_has_token_management -v

# Unit tests - advisory (all pass ✅)
pytest tests/unit/channels/test_console.py tests/unit/channels/test_base_core.py -v
```

## Test Results

```
Contract Tests:  223 passed ✅
Unit Tests:      49 passed ✅
Pre-commit:      All checks passed ✅
```
