# CoPaw Dual-Mainline Branching SOP (Local Collaboration)

This SOP standardizes local dual-mainline workflows and prevents accidental merges into the wrong mainline.

## 1. Branch Roles

- upstream/main: upstream source-of-truth mainline for sync and upstream PR baselines.
- fork/main: local development mainline where features are merged and validated first.
- main (local): choose exactly one model and keep it consistent.
  - Model A (recommended): upstream mirror line.
  - Model B: local release integration line.

Important: The team must align on what local main means before daily work.

## 2. Standard Development Flow

1. Refresh base lines
- git fetch --all --prune
- git checkout fork/main
- git merge --ff-only upstream/main

2. Create feature branch
- git checkout -b feat/upstream/<topic> fork/main

3. Develop and commit
- Follow Conventional Commits.
- Pass local gates before push/PR (pre-commit, pytest).

4. First merge stage (required)
- Merge feature into fork/main first.
- Commands:
  - git checkout fork/main
  - git merge --no-ff feat/upstream/<topic>

5. Second merge stage (optional, policy-based)
- If main is a local release integration line: merge fork/main into main.
- If main is an upstream mirror line: do not merge fork/main directly into main; open PR to upstream/main instead.

## 3. PR Target Mapping

- For upstream contribution:
  - source: feat/upstream/<topic> (or cleaned equivalent)
  - target: upstream/main
- For local fork integration:
  - source: feat/upstream/<topic>
  - target: fork/main

## 4. Pre-Merge Checklist

- Working tree is clean (git status has no pending changes).
- Target branch is correct (fork/main or main).
- Local mainline role is explicit (mirror vs integration).
- Diff/log range is explainable (git log / git diff).
- Required tests have passed (at least local gates).

## 5. Command Templates

### 5.1 Merge into development mainline first (fork/main)

- git checkout fork/main
- git merge --no-ff feat/upstream/knowledge-layer-mvp-sop-cognee

### 5.2 Merge into local mainline (only when main = integration line)

- git checkout main
- git merge --no-ff fork/main

## 6. Common Pitfalls

- Pitfall 1: Merge feature directly into main after implementation.
  - Risk: pollutes mirror semantics if main is meant to track upstream.
- Pitfall 2: Let fork/main drift too far from upstream/main.
  - Risk: conflict debt accumulates and PR review cost rises.
- Pitfall 3: Merge to mainline before local gates pass.
  - Risk: unstable mainline and expensive rollback.

## 7. Relation to CONTRIBUTING

- This SOP complements, not replaces, CONTRIBUTING rules.
- Keep enforcing Conventional Commits, PR title format, pre-commit and test gates.
