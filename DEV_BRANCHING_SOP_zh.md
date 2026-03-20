# CoPaw 双主线开发 SOP（本地协作版）

本文用于规范本地双主线协作，避免 feature 直接误合到错误主线。

## 1. 分支角色

- upstream/main：上游事实主线，仅用于同步上游状态、构建上游 PR 基线。
- mirror/upstream-main：upstream/main 的本地严格镜像线，禁止开发。
- fork/main：fork 特性开发主线，功能先合入这里并完成验证。
- main（本地整合主线）：默认协作主线。
  - 必须长期保持相对 upstream/main 的 behind=0（持续同步）。
  - 允许 ahead>0（承载本地/fork 的增量提交）。

注意：main 不是纯镜像线，但不能长期落后 upstream。

## 2. 标准开发路径

1. 更新基线
- git fetch --all --prune
- git checkout mirror/upstream-main
- git reset --hard upstream/main

2. 同步本地 main（必须）
- git checkout main
- git merge --no-ff upstream/main
- 如有冲突立即处理并推送 main。

3. 创建功能分支
- upstream 贡献：git checkout -b feat/upstream/<topic> mirror/upstream-main
- fork 特性：git checkout -b feat/fork/<topic> fork/main

4. 开发与提交
- 按 Conventional Commits 提交。
- push/提 PR 前通过本地门禁（pre-commit、pytest）。

5. 第一段合并（必须）
- 目标：fork 特性先合入 fork/main。
- 命令：
  - git checkout fork/main
  - git merge --no-ff feat/fork/<topic>

6. 第二段合并（按策略）
- 按需将已验证的 fork/main 合入 main。
- main 与 upstream/main 的同步要持续进行，不要堆积。

## 3. PR 与分支对应关系

- 面向 upstream：
  - 源分支：feat/upstream/<topic>
  - 目标分支：upstream/main
- 面向 fork 内部整合：
  - 源分支：feat/fork/<topic>
  - 目标分支：fork/main
- 面向本地 main 整合：
  - 源分支：fork/main（或已验证功能分支）
  - 目标分支：main

## 4. 合并前检查清单

- 当前工作区干净（git status 无未提交改动）。
- 当前目标分支正确（fork/main 或 main）。
- 确认 main 不落后 upstream/main（behind=0）。
- 确认 feature 与目标分支差异范围可解释（git log/ git diff）。
- 必要测试已通过（至少本地门禁）。

## 5. 推荐命令模板

### 5.1 先合开发主线（fork/main）

- git checkout fork/main
- git merge --no-ff feat/upstream/knowledge-layer-mvp-sop-cognee

### 5.2 再合本地 main（仅当 main=本地发布整合线）

- git checkout main
- git merge --no-ff upstream/main
- git merge --no-ff fork/main

## 6. 常见误区

- 误区 1：main 长期落后 upstream/main。
  - 风险：同步债务越积越大，后续冲突和回归成本陡增。
- 误区 2：fork/main 与 upstream/main 长期不对齐。
  - 风险：后续冲突集中爆发，PR 审核成本升高。
- 误区 3：未先做门禁验证就推进主线合并。
  - 风险：主线不稳定，后续回滚成本上升。

## 7. 与贡献规范的关系

- 本 SOP 不替代 CONTRIBUTING 中的提交与质量规范。
- 所有分支流程仍需遵守：Conventional Commits、PR 标题规范、pre-commit 与测试门禁。
