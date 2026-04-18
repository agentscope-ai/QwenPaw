## Description

[Describe what this PR does and why]

**Related Issue:** Fixes #(issue_number) or Relates to #(issue_number)

**Security Considerations:** [If applicable, e.g. channel auth, env/config handling]

## Type of Change

- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation
- [ ] Refactoring

## Component(s) Affected

- [ ] Core / Backend (app, agents, config, providers, utils, local_models)
- [ ] Console (frontend web UI)
- [ ] Channels (DingTalk, Feishu, QQ, Discord, iMessage, etc.)
- [ ] Skills
- [ ] CLI
- [ ] Documentation (website)
- [ ] Tests
- [ ] CI/CD
- [ ] Scripts / Deploy

## Checklist

- [ ] I ran `pre-commit run --all-files` locally and it passes
- [ ] If pre-commit auto-fixed files, I committed those changes and reran checks
- [ ] I ran tests locally (`pytest` or as relevant) and they pass
- [ ] Documentation updated (if needed)
- [ ] Ready for review

### For Channel Changes (DingTalk, Feishu, QQ, Console, etc.)

- [ ] I ran `./scripts/check-channels.sh` (or `./scripts/check-channels.sh --changed`) and it passes
- [ ] **Contract test** exists in `tests/contract/channels/test_<channel>_contract.py` (REQUIRED)
- [ ] Contract test implements `create_instance()` with proper channel initialization
- [ ] All 19 contract verification points pass (see `tests/contract/channels/__init__.py`)
- [ ] **Optional**: Unit tests in `tests/unit/channels/test_<channel>.py` for complex internal logic

## Testing

[How to test these changes]

## Local Verification Evidence

```bash
pre-commit run --all-files
# paste summary result

pytest
# paste summary result
```

## Additional Notes

[Optional: any other context]
