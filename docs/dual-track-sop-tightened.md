# CoPaw 双主线协作 SOP - 加强版（紧随策略）

本文档是 `dual-track-sop.md` 的补充，针对 upstream 快速迭代场景下的同步策略加强。

## 1. 核心变化：从被动同步→主动定期同步

### 1.1 原 SOP 的问题
> "每次准备开发前，先同步"

**问题**：
- 定义模糊（何时为"准备开发"）
- 执行不强制（容易被遗忘）
- 后置冲突处理（冲突积累后爆发）

### 1.2 改进策略：定期强制同步

**新规则**：

```
MUST DO：
1. 每次开始开发时强制执行日常同步流程（见下文）
2. 每次提 PR 前强制执行顺序同步检查
3. 定期检查 fork/main 与 upstream/main 的落后程度

GOAL：
- 保持 fork/main 落后 mirror/upstream-main < 20 commits
- 若落后 >= 50 commits 时自动告警
- rebase 冲突控制在 < 5 个文件
```

## 2. 优化的日常同步流程

### 2.1 快速检查（每日）

```bash
#!/bin/bash
# check-sync-status.sh

git fetch origin --prune
git fetch upstream --prune

# 检查 mirror/upstream-main 是否对齐
MIRROR_BEHIND=$(git rev-list --count mirror/upstream-main..upstream/main)
if [ "$MIRROR_BEHIND" -gt 0 ]; then
  echo "⚠️  mirror/upstream-main 落后 $MIRROR_BEHIND commits"
fi

# 检查 fork/main 是否落后过多
FORK_BEHIND=$(git rev-list --count fork/main..mirror/upstream-main)
if [ "$FORK_BEHIND" -ge 20 ]; then
  echo "⚠️  fork/main 落后 mirror/upstream-main $FORK_BEHIND commits（建议立即同步）"
fi

# 如果可能有冲突，干运行检查
if [ "$FORK_BEHIND" -ge 5 ]; then
  echo "ℹ️  干运行冲突检查..."
  git merge --no-commit --no-ff mirror/upstream-main > /dev/null 2>&1
  if [ $? -ne 0 ]; then
    echo "⚠️  可能存在冲突，rebase 前请准备好手动解决"
    git merge --abort
  fi
fi
```

### 2.2 完整同步流程（开发前或 PR 前必执行）

```bash
#!/bin/bash
# sync-all.sh

set -e  # 失败即停止

echo "📦 同步开始..."

# Step 1: 获取最新
git fetch origin --prune
git fetch upstream --prune

# Step 2: 更新 mirror
echo "🔄 更新 mirror/upstream-main..."
git checkout mirror/upstream-main
git reset --hard upstream/main

# Step 3: 更新 fork/main
echo "🔄 更新 fork/main..."
git checkout fork/main

BEFORE=$(git rev-list --count mirror/upstream-main..HEAD)
git rebase mirror/upstream-main

if [ $? -eq 0 ]; then
  AFTER=$(git rev-list --count mirror/upstream-main..HEAD)
  echo "✅ fork/main 同步成功（本地提交: $AFTER）"
else
  echo "❌ 冲突检测！需要手动处理"
  echo "冲突文件："
  git diff --name-only --diff-filter=U
  exit 1
fi

# Step 4: 推送（可选）
read -p "推送到 origin/fork/main？(y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
  git push --force-with-lease origin fork/main
  echo "✅ 推送成功"
fi

echo "🎉 同步完成"
```

## 3. 加强的分支生命周期管理

### 3.1 feat/upstream/* 分支规范

```
创建：git checkout -b feat/upstream/<topic> mirror/upstream-main
开发周期：最多 7 天
提交规则：
  - 不包含任何 fork 私有改动
  - 功能完整且独立
  - 测试通过、代码审查完成
PR 流程：
  1. 本地 rebase mirror/upstream-main
  2. 强制 push（如有变更）
  3. 创建 PR to upstream/main
  4. 等待 upstream review & merge
删除：PR 合并到 upstream/main 后 3 天自动清理本地分枝
```

### 3.2 feat/fork/* 分枝规范

```
创建：git checkout -b feat/fork/<topic> fork/main
开发周期：最多 14 天
提交规则：
  - 仅包含 fork 特有的功能或改动
  - 避免与 upstream 功能重叠
开发期间：
  - 每周强制 rebase 到最新 fork/main（含 upstream 同步）
  - 如冲突 > 3 个，优先解决冲突再继续开发
PR/合并流程：
  1. rebase 到最新 fork/main
  2. 创建 PR to fork/main
  3. 等待 review & merge
删除：合并到 fork/main 后 3 天自动清理本地分枝
```

## 4. 冲突预防与快速恢复

### 4.1 前置冲突检测（拉分支前）

```bash
#!/bin/bash
# check-before-branch.sh

# 在切分支前检查当前与 mirror/upstream-main 是否有冲突风险

CURRENT=$(git symbolic-ref --short HEAD)

if [[ $CURRENT == "feat/fork/"* ]]; then
  # feat/fork 可以基于 fork/main
  BASE="fork/main"
else
  # 其他分支应基于 mirror/upstream-main
  BASE="mirror/upstream-main"
fi

echo "检查与 $BASE 的冲突风险..."

git merge --no-commit --no-ff $BASE > /dev/null 2>&1
RESULT=$?

if [ $RESULT -eq 0 ]; then
  echo "✅ 无冲突"
  git merge --abort
else
  echo "⚠️  可能存在冲突："
  git diff --name-only --diff-filter=U
  git merge --abort
  exit 1
fi
```

### 4.2 快速冲突恢复（rebase 失败后）

**场景 1**：feat/fork 与 upstream 同步冲突过多

```bash
# 选项 A：采纳 upstream，放弃 fork 改动
git rebase --abort
git checkout fork/main
git reset --hard mirror/upstream-main

# 选项 B：手动提取 fork 重要改动
git rebase --abort
git checkout -b fork/main-backup fork/main
# 然后从 backup cherry-pick 需要的提交

# 选项 C：分阶段合并
git rebase --continue  # 逐个提交解决冲突
```

**场景 2**：feat/upstream 与新 upstream 改动冲突

```bash
git rebase --abort
git checkout feat/upstream/<topic>
git rebase mirror/upstream-main --interactive
# 选择性保留或删除冲突的提交
# 如果该功能与 upstream 新改动重叠，考虑放弃本分支
```

## 5. 自动化监控脚本（建议实现）

### 5.1 周期性检查（daily cron）

```bash
#!/bin/bash
# daily-sync-monitor.sh

REPO_PATH="/Users/futuremeng/github/futuremeng/CoPaw"
cd $REPO_PATH

git fetch origin --prune
git fetch upstream --prune

# 检查 mirror/upstream-main
MIRROR_BEHIND=$(git rev-list --count mirror/upstream-main..upstream/main)
if [ "$MIRROR_BEHIND" -gt 0 ]; then
  echo "[ALERT] mirror/upstream-main 落后 $MIRROR_BEHIND commits"
  # 可选：自动更新
  # git checkout mirror/upstream-main && git reset --hard upstream/main
fi

# 检查 fork/main
FORK_BEHIND=$(git rev-list --count fork/main..mirror/upstream-main)
if [ "$FORK_BEHIND" -ge 50 ]; then
  echo "[ALERT] fork/main 落后 $FORK_BEHIND commits，建议立即同步"
fi

# 检查过期分枝
echo "[INFO] 检查过期分枝..."
git branch -v | while read branch rest; do
  LAST_COMMIT_DATE=$(git log -1 --format=%ai $branch | cut -d' ' -f1)
  DAYS_AGO=$(( ($(date +%s) - $(date -d "$LAST_COMMIT_DATE" +%s)) / 86400 ))
  
  if [[ $branch == "feat/fork/"* ]] && [ $DAYS_AGO -gt 14 ]; then
    echo "[WARN] feat/fork 分枝 $branch 已 $DAYS_AGO 天未更新，建议清理"
  fi
  
  if [[ $branch == "feat/upstream/"* ]] && [ $DAYS_AGO -gt 7 ]; then
    echo "[WARN] feat/upstream 分枝 $branch 已 $DAYS_AGO 天未更新，建议清理"
  fi
done
```

### 5.2 分枝清理脚本

```bash
#!/bin/bash
# cleanup-branches.sh

git fetch --all --prune

# 清理合并过的特性分枝
echo "清理已合并的分枝..."
git branch --merged fork/main | grep -E 'feat/fork/' | xargs -r git branch -d
git branch --merged mirror/upstream-main | grep -E 'feat/upstream/' | xargs -r git branch -d

echo "✅ 清理完成"
```

## 6. 改进版操作清单

### 每日开发前（必执行）

```
□ git fetch origin --prune
□ git fetch upstream --prune
□ 运行 check-sync-status.sh 检查状态
□ 如果 fork/main 落后 >= 20，运行 sync-all.sh 同步
□ 选择基于 mirror/upstream-main 或 fork/main 切分支
```

### 提交 PR 前（必执行）

```
□ git fetch upstream --prune  # 确保最新
□ 当前分枝是否需要 rebase？
   - feat/upstream/*: 必须 rebase mirror/upstream-main
   - feat/fork/*: 必须 rebase fork/main（已包含 upstream 同步）
□ 运行测试并通过
□ 检查 PR 是否包含无关改动（尤其是 fork/upstream 不混）
□ 推送并创建 PR
```

### 每周一次（维护）

```
□ 运行 daily-sync-monitor.sh 检查工程状态
□ 手动检查是否有待同步的 upstream 关键更新
□ 清理过期分枝：cleanup-branches.sh
□ 更新本地文档（如有策略变更）
```

## 7. 决策树：何时采用什么策略

```
START: 要开发新功能？
│
├─ 目标是上游贡献？
│  ├─ YES → 从 mirror/upstream-main 切 feat/upstream/<topic>
│  │         └─ 每日 fetch upstream，如 upstream 更新则 rebase mirror/upstream-main
│  │         └─ PR 创建到 upstream/main
│  │
│  └─ NO → 是 fork 特有功能？
│     ├─ YES → 从 fork/main 切 feat/fork/<topic>
│     │         └─ 每周同步 fork/main（含 upstream 更新）
│     │         └─ PR 创建到 fork/main
│     │
│     └─ NO → 不明确，咨询团队
│
├─ 开发中遇到 upstream 更新？
│  └─ 运行 check-sync-status.sh
│     ├─ 无冲突 but 落后 >= 20 → rebase 继续
│     ├─ 有冲突 but < 5 文件 → 手动解决
│     └─ 有冲突 and >= 5 文件 → 评估是否该功能仍需要
│
└─ PR 准备提交？
   └─ 运行 sync-all.sh 强制同步
      ├─ OK → 推送、创建 PR
      └─ CONFLICT → 手动处理、解决后再提
```

## 8. FAQ

### Q: 为什么要强制定期同步？
A: upstream 快速迭代（10+ commits/天）。不定期同步会导致 fork/main 与 upstream 偏离 50+ commits，最后 rebase 冲突爆发。定期同步避免问题积累。

### Q: fork/main 落后 mirror/upstream-main 多少算"正常"？
A: 
- <= 5 commits：完全正常（可能是本地功能 cherry-pick 的差异）
- 5-20 commits：可接受（fork 特有功能正在开发）
- 20-50 commits：需要关注（考虑优先提交这些改动）
- \> 50 commits：需要立即处理（自动化告警）

### Q: 冲突超过 5 个文件怎么办？
A: 这通常说明 fork 的改动与 upstream 产生了较大偏离，建议：
1. 首先检查 fork/main 最后几个提交是否大型功能
2. 考虑将该功能分拆为更小的独立提交
3. 或者，评估该功能是否仍需保留、是否该提交 upstream
4. 最后手段：`git reset --hard mirror/upstream-main` 后重新开发

### Q: 如何判断一个改动是"fork 特有"还是"应该 upstream"？
A: 参考 dual-track-sop.md 第 7 部分的分类。一般来说：
- **应该 upstream**：bug fix、性能优化、feature (通用)、开发工具改进
- **fork 特有**：定制化 UI、特殊业务逻辑、内部工具、实验性功能

## 9. 与原 SOP 的关系

本文档是 `dual-track-sop.md` 的**补充与加强**，不是替代。

**使用指南**：
- 新手：从 `dual-track-sop.md` 开始学习基础
- 日常工作：参考本文档的"改进版操作清单"
- 故障排查：参考"冲突预防与快速恢复"
- 团队建议：采用本文档的"自动化脚本"

---

> 最后更新：2026-03-18
> 作者：@futuremeng
> 状态：草稿版（待团队反馈）
