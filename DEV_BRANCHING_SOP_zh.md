# CoPaw 双主线开发 SOP（本地协作版）

本文用于规范本地双主线协作，避免 feature 直接误合到错误主线。

## 1. 分支角色

- upstream/main：上游事实主线，仅用于同步上游状态、构建上游 PR 基线。
- fork/main：本地开发主线，功能先合入这里并完成验证。
- main（本地）：建议固定为以下两种之一。
  - 方案 A（推荐）：上游镜像线。尽量保持与 upstream/main 对齐。
  - 方案 B：本地发布整合线。承接 fork/main，服务本地发布。

注意：项目内必须先统一 main 的定位，避免不同成员按不同语义操作。

## 2. 标准开发路径

1. 更新基线
- git fetch --all --prune
- git checkout fork/main
- git merge --ff-only upstream/main

2. 创建功能分支
- git checkout -b feat/upstream/<topic> fork/main

3. 开发与提交
- 按 Conventional Commits 提交。
- push/提 PR 前通过本地门禁（pre-commit、pytest）。

4. 第一段合并（必须）
- 目标：先合入 fork/main。
- 命令：
  - git checkout fork/main
  - git merge --no-ff feat/upstream/<topic>

5. 第二段合并（按需）
- 如果 main 是“本地发布整合线”：再将 fork/main 合入 main。
- 如果 main 是“上游镜像线”：不要把 fork/main 直接合入 main；改为对 upstream/main 提 PR。

## 3. PR 与分支对应关系

- 面向 upstream：
  - 源分支：feat/upstream/<topic>（或清理后的等价分支）
  - 目标分支：upstream/main
- 面向 fork 内部整合：
  - 源分支：feat/upstream/<topic>
  - 目标分支：fork/main

## 4. 合并前检查清单

- 当前工作区干净（git status 无未提交改动）。
- 当前目标分支正确（fork/main 或 main）。
- 明确 main 当前语义（上游镜像线 / 本地发布整合线）。
- 确认 feature 与目标分支差异范围可解释（git log/ git diff）。
- 必要测试已通过（至少本地门禁）。

## 5. 推荐命令模板

### 5.1 先合开发主线（fork/main）

- git checkout fork/main
- git merge --no-ff feat/upstream/knowledge-layer-mvp-sop-cognee

### 5.2 再合本地 main（仅当 main=本地发布整合线）

- git checkout main
- git merge --no-ff fork/main

## 6. 常见误区

- 误区 1：feature 完成后直接合 main。
  - 风险：若 main 是上游镜像线，会污染镜像语义。
- 误区 2：fork/main 与 upstream/main 长期不对齐。
  - 风险：后续冲突集中爆发，PR 审核成本升高。
- 误区 3：未先做门禁验证就推进主线合并。
  - 风险：主线不稳定，后续回滚成本上升。

## 7. 与贡献规范的关系

- 本 SOP 不替代 CONTRIBUTING 中的提交与质量规范。
- 所有分支流程仍需遵守：Conventional Commits、PR 标题规范、pre-commit 与测试门禁。
