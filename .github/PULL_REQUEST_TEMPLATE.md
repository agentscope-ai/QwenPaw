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

## Testing

[How to test these changes]

## Local Verification Evidence

```bash
pre-commit run --all-files
# paste summary result

pytest
# paste summary result
```

## Release-specific Checklist (if this is a release PR)

Release PR only. Non-release PR can skip this section.
仅发布类 PR 需要勾选，非发布 PR 可跳过本节。

- [ ] I followed `RELEASE.md` (and `RELEASE_zh.md` if needed)
- [ ] 我已按 `RELEASE.md`（如需要也参考 `RELEASE_zh.md`）执行发布流程
- [ ] `src/copaw/__version__.py` is updated with the target version
- [ ] 我已将目标版本更新到 `src/copaw/__version__.py`
- [ ] I validated version format (PEP 440)
- [ ] 我已校验版本格式（PEP 440）
- [ ] I completed a release checklist issue using `.github/ISSUE_TEMPLATE/6-release_checklist.md`
- [ ] 我已使用 `.github/ISSUE_TEMPLATE/6-release_checklist.md` 创建并完成发布检查清单 issue
- [ ] I verified the target release type (stable/prerelease/post) and tag naming
- [ ] 我已确认发布类型（stable/prerelease/post）与 tag 命名

## Additional Notes

[Optional: any other context]
