# CoPaw Fork 双主线协作 SOP

## 1. 目标

本 SOP 用于在 fork 仓库中同时满足两类需求：

- 持续跟进上游 `upstream/main`
- 在 fork 上保留自定义改动，并选择性向上游提交 PR

采用双主线模型后，可以降低冲突成本，并让上游 PR 更干净。

## 2. 分支与远程约定

### 2.1 远程

- `origin`: 个人 fork（例如 `futuremeng/CoPaw`）
- `upstream`: 官方仓库（例如 `agentscope-ai/CoPaw`）

### 2.2 分支

- `mirror/upstream-main`
  - 只做上游镜像，不直接开发
  - 始终对齐 `upstream/main`
- `fork/main`
  - fork 的主发布线
  - 可以包含 fork 特有提交
- `feat/upstream/*`
  - 准备提交给 upstream 的功能分支
  - 必须从 `mirror/upstream-main` 切出
- `feat/fork/*`
  - 仅保留在 fork 的功能分支
  - 从 `fork/main` 切出

## 3. 一次性初始化

在仓库根目录执行：

```bash
git remote -v
git remote add upstream git@github.com:agentscope-ai/CoPaw.git  # 若已存在可跳过

git fetch origin --prune
git fetch upstream --prune

git branch -f mirror/upstream-main upstream/main
git branch -f fork/main main
```

可选：将本地默认开发分支切到 `fork/main`。

```bash
git checkout fork/main
```

## 4. 日常同步流程（固定执行）

每次准备开发前，先同步：

```bash
git fetch origin --prune
git fetch upstream --prune

# 更新上游镜像线
git checkout mirror/upstream-main
git reset --hard upstream/main

# 更新 fork 主线
git checkout fork/main
git rebase mirror/upstream-main
```

说明：

- `mirror/upstream-main` 上允许使用 `reset --hard`，因为它是纯镜像线。
- 其他开发分支不要使用破坏性 reset，改用 rebase/merge/cherry-pick。

## 5. 向 upstream 提交功能

### 5.1 创建分支

```bash
git checkout mirror/upstream-main
git checkout -b feat/upstream/<topic>
```

### 5.2 开发与提交

```bash
# coding...
git add <files>
git commit -m "<type>: <message>"
```

### 5.3 推送并创建 PR

```bash
git push -u origin feat/upstream/<topic>
```

然后在 GitHub 创建 PR：

- from: `futuremeng:feat/upstream/<topic>`
- to: `agentscope-ai:main`

## 6. 仅保留在 fork 的功能

```bash
git checkout fork/main
git checkout -b feat/fork/<topic>

# coding...
git add <files>
git commit -m "<type>: <message>"
git push -u origin feat/fork/<topic>
```

合并目标应为 `fork/main`，不进入 upstream PR。

## 7. 当前仓库建议的改动归类

### 7.1 适合 upstream

- `src/copaw/app/runner/runner.py`（503 降级处理）
- `src/copaw/providers/retry_chat_model.py`（重试与可观测性）
- `scripts/bootstrap_dev.sh`（开发启动脚本）
- `scripts/README.md`（脚本说明）
- `pyproject.toml`（依赖补齐）

### 7.2 分拆建议

将上游贡献拆成两个 PR：

1. 稳定性修复 PR（503 重试与友好降级）
2. 开发体验 PR（bootstrap 脚本与文档）

## 8. 提交拆分 SOP（避免混合 PR）

当一个提交混有多类改动时：

```bash
# 假设当前分支已有混合提交 <mixed_commit>

git checkout -b feat/upstream/<part-a> mirror/upstream-main
git cherry-pick -n <mixed_commit>
git reset
git add <part-a-files>
git commit -m "<part-a-message>"

git checkout -b feat/upstream/<part-b> mirror/upstream-main
git cherry-pick -n <mixed_commit>
git reset
git add <part-b-files>
git commit -m "<part-b-message>"
```

## 9. 冲突处理建议

- upstream 同步冲突优先在 `fork/main` 解决，不在 `mirror/upstream-main` 解决。
- 上游 PR 分支冲突时，优先 `rebase mirror/upstream-main` 后再推送。
- 如果分支历史已公开并被多人基于其开发，改用 merge 避免强推风险。

## 10. 维护与清理

定期清理已合并分支：

```bash
git fetch --all --prune
git branch --merged | grep -E 'feat/upstream|feat/fork' | xargs -n 1 git branch -d
```

清理临时 stash（确认无用后）：

```bash
git stash list
git stash drop stash@{0}
```

## 11. 最小操作清单（Checklist）

每次开始开发前：

1. `git fetch origin --prune && git fetch upstream --prune`
2. 更新 `mirror/upstream-main`
3. 更新 `fork/main`
4. 根据目标选择从 `mirror/upstream-main` 或 `fork/main` 切分支

每次提 upstream PR 前：

1. 确认分支基于 `mirror/upstream-main`
2. 确认不包含 fork 私有改动
3. 运行测试并通过
4. 推送并创建 PR
