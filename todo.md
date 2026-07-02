# Issue Todo

## PR Health Check

- [x] #5731: no failed checks or review comments; PR body updated to match template.
- [x] #5739: no failed checks or review comments; PR body updated to match template.
- [x] #5740: no failed checks or review comments; PR body updated to match template.

## Ranked Actionable Issues

1. #5705 Secret safety: high merge probability, maintainer welcomed contribution, can be split into small security PRs.
2. #5737 CLI non-GUI operation improvements: useful but broad; needs careful scoping before implementation.
3. #5718 Auto switch model: useful but overlaps existing fallback PRs, higher conflict risk.
4. #5657 Loop detection: valuable but design-sensitive and likely needs maintainer alignment.
5. #5667 Workspace file browser entry: user-facing frontend work, useful but larger QA surface.

## Selected Work

- [x] #5705 dialog/debug artifact redaction
  - Add reusable pattern-based secret redaction.
  - Redact `dialog/*.jsonl` offloads.
  - Redact `/dump_history` debug JSONL exports.
  - Redact offloaded tool-result text files.
