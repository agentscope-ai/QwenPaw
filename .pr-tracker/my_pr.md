# My PRs Tracker

> 自动/手动更新 PR 状态、CI、审查反馈
> 最后更新: 2026-07-29

## Active PRs

### PR #6522: fix: retain dirty flag on token usage flush failure
- **仓库**: agentscope-ai/QwenPaw
- **分支**: fix/issue-6374-token-usage-retry
- **关联 Issue**: #6374
- **状态**: 🟢 open
- **创建时间**: 2026-07-28
- **CI 状态**: ⚠️ "Real behavior proof" 失败 (GitHub Integration 权限问题，非代码问题)
- **Review 状态**: ⏳ pending (REVIEW_REQUIRED)
- **合并状态**: ✅ mergeable
- **链接**: [github.com/agentscope-ai/QwenPaw/pull/6522](https://github.com/agentscope-ai/QwenPaw/pull/6522)

### PR #6523: fix: preserve quoted verify commands in mission arg parsing
- **仓库**: agentscope-ai/QwenPaw
- **分支**: fix/issue-6355-mission-quoted-args
- **关联 Issue**: #6355
- **状态**: 🟢 open
- **创建时间**: 2026-07-28
- **CI 状态**: ⚠️ "Real behavior proof" 失败 (GitHub Integration 权限问题，非代码问题)
- **Review 状态**: ⏳ pending (REVIEW_REQUIRED)
- **合并状态**: ✅ mergeable
- **链接**: [github.com/agentscope-ai/QwenPaw/pull/6523](https://github.com/agentscope-ai/QwenPaw/pull/6523)

### PR #6539: fix(unified_queue): prevent stale consumer from removing recreated queue state
- **仓库**: agentscope-ai/QwenPaw
- **分支**: fix/issue-6372-queue-race
- **关联 Issue**: #6372
- **状态**: 🟢 open
- **创建时间**: 2026-07-29
- **CI 状态**: 🔄 running
- **Review 状态**: ⏳ pending (REVIEW_REQUIRED)
- **合并状态**: -
- **核心修复**: 向 _run_consumer 传入 QueueState 引用，finally 块在 pop 前校验身份，避免老 consumer 误删新创建的队列状态
- **链接**: [github.com/agentscope-ai/QwenPaw/pull/6539](https://github.com/agentscope-ai/QwenPaw/pull/6539)

## CI 状态说明

| PR | Tests | CodeQL | Format | Real Behavior Proof |
|----|-------|--------|--------|---------------------|
| 6522 | ✅ pass | ✅ pass | ✅ pass | ❌ fail (integration permission) |
| 6523 | ✅ pass | ✅ pass | ✅ pass | ❌ fail (integration permission) |
| 6539 | 🔄 running | 🔄 running | 🔄 running | - |

> **Note**: "Real behavior proof" failure is due to `HttpError: Resource not accessible by integration` — a GitHub Actions integration configuration issue, not related to our code changes. The actual test/format/codeql checks all pass.

## Merged PRs

| # | Title | Merged At | Merged By | 🎉 |
|---|-------|-----------|-----------|-----|
| 6015 | fix(providers): use max_completion_tokens for reasoning models | 2026-07-13 | @yuanxs21 | ✅ |
| 5924 | docs(console): add Whisper installation notes | 2026-07-10 | @yuanxs21 | ✅ |
| 5751 | fix(chat): prioritize built-in slash commands | 2026-07-13 | @yuanxs21 | ✅ |
| 5731 | fix(runtime): honor per-request model override | 2026-07-15 | @yuanxs21 | ✅ |

## Open PRs (from previous sessions)

| # | Title | State | CI 状态 | URL |
|---|-------|-------|---------|-----|
| 5745 | fix(security): redact secrets in persisted dialog artifacts | OPEN | - | [link](https://github.com/agentscope-ai/QwenPaw/pull/5745) |
| 5740 | feat(config): expand env var references in json config | OPEN | - | [link](https://github.com/agentscope-ai/QwenPaw/pull/5740) |
| 5739 | feat(chat): support selecting and auto-copying message text | OPEN | - | [link](https://github.com/agentscope-ai/QwenPaw/pull/5739) |
