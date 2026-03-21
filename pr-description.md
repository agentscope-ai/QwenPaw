**Related Issue:** N/A (new enhancement)

**Security Considerations:** No new secrets or auth changes. Uses existing QQ access token for media upload. Local file reads are limited to paths explicitly provided in agent responses.

## Type of Change
- [ ] Bug fix
- [x] New feature
- [ ] Breaking change
- [ ] Documentation
- [ ] Refactoring

## Component(s) Affected
- [ ] Core / Backend (app, agents, config, providers, utils, local_models)
- [ ] Console (frontend web UI)
- [x] Channels (DingTalk, Feishu, QQ, Discord, iMessage, etc.)
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
- [x] Documentation updated (if needed)
- [x] Ready for review

## Testing

1. Configure a QQ bot channel
2. Have an agent reply with `[Image: /path/to/local/image.png]` — should upload via `file_data` (base64) and send successfully
3. Have an agent reply with `[Image: https://example.com/pic.jpg]` — should work as before via URL
4. Verify non-existent local paths are logged and skipped gracefully

## Local Verification Evidence
```bash
pre-commit run --all-files
# (pending)

pytest
# (pending)
```

## Additional Notes

QQ's official rich media API supports a `file_data` field (base64-encoded binary) alongside the existing `url` field. This change leverages `file_data` so local images can be sent without needing an external OSS or public URL. Fully backward compatible — public URLs still go through the original path.
