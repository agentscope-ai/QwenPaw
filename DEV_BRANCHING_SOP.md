# CoPaw Dual-Mainline Branching SOP (Local Collaboration)

This SOP standardizes local dual-mainline workflows and prevents accidental merges into the wrong mainline.

## 1. Branch Roles

- upstream/main: upstream source-of-truth mainline for sync and upstream PR baselines.
- mirror/upstream-main: strict local mirror of upstream/main. Never develop here.
- fork/main: local fork mainline for fork-only features and validations.
- main (local integration line): the default collaboration mainline.
  - Must stay **behind=0** against upstream/main (merge upstream/main regularly).
  - Can stay ahead with local/fork commits.

Important: main is not a frozen mirror, but it must not accumulate upstream lag.

## 2. Standard Development Flow

1. Refresh base lines
- git fetch --all --prune
- git checkout mirror/upstream-main
- git reset --hard upstream/main

2. Sync local main with upstream (required)
- git checkout main
- git merge --no-ff upstream/main
- Resolve conflicts immediately if any, then push main.

3. Create feature branch
- upstream contribution branch: git checkout -b feat/upstream/<topic> mirror/upstream-main
- fork feature branch: git checkout -b feat/fork/<topic> fork/main

4. Develop and commit
- Follow Conventional Commits.
- Pass local gates before push/PR (pre-commit, pytest).

5. First merge stage (required)
- Merge fork features into fork/main first.
- Commands:
  - git checkout fork/main
  - git merge --no-ff feat/fork/<topic>

6. Second merge stage (policy-based)
- Merge validated fork/main changes into main as needed.
- Keep main synchronized with upstream/main continuously.

## 3. PR Target Mapping

- For upstream contribution:
- source: feat/upstream/<topic>
  - target: upstream/main
- For local fork integration:
- source: feat/fork/<topic>
  - target: fork/main
- For local integration into main:
  - source: fork/main (or selected feature branch)
  - target: main

## 4. Pre-Merge Checklist

- Working tree is clean (git status has no pending changes).
- Target branch is correct (fork/main or main).
- main is not behind upstream/main (behind=0).
- Diff/log range is explainable (git log / git diff).
- Required tests have passed (at least local gates).

## 5. Command Templates

### 5.1 Merge into development mainline first (fork/main)

- git checkout fork/main
- git merge --no-ff feat/upstream/knowledge-layer-mvp-sop-cognee

### 5.2 Merge into local mainline (only when main = integration line)

- git checkout main
- git merge --no-ff upstream/main
- git merge --no-ff fork/main

## 6. Common Pitfalls

- Pitfall 1: Let main lag behind upstream/main for days.
  - Risk: sync debt compounds and every later merge becomes harder.
- Pitfall 2: Let fork/main drift too far from upstream/main.
  - Risk: conflict debt accumulates and PR review cost rises.
- Pitfall 3: Merge to mainline before local gates pass.
  - Risk: unstable mainline and expensive rollback.

## 7. Relation to CONTRIBUTING

- This SOP complements, not replaces, CONTRIBUTING rules.
- Keep enforcing Conventional Commits, PR title format, pre-commit and test gates.
