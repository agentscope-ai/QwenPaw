#!/bin/bash
# check-sync-status.sh - 检查 upstream 同步状态与冲突风险
# 用法: ./scripts/check-sync-status.sh

set -e

REPO_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_PATH"

echo "📦 检查同步状态..."

# 获取最新
git fetch origin --prune 2>/dev/null || true
git fetch upstream --prune 2>/dev/null || true

# 检查 mirror/upstream-main 是否对齐
MIRROR_BEHIND=$(git rev-list --count mirror/upstream-main..upstream/main 2>/dev/null || echo "0")
if [ "$MIRROR_BEHIND" -gt 0 ]; then
  echo "⚠️  mirror/upstream-main 落后 upstream/main $MIRROR_BEHIND commits"
  echo "   建议运行: git checkout mirror/upstream-main && git reset --hard upstream/main"
else
  echo "✅ mirror/upstream-main 与 upstream/main 对齐"
fi

# 检查 fork/main 是否落后过多
FORK_BEHIND=$(git rev-list --count fork/main..mirror/upstream-main 2>/dev/null || echo "0")
if [ "$FORK_BEHIND" -ge 50 ]; then
  echo "❌ fork/main 落后 mirror/upstream-main $FORK_BEHIND commits（严重落后！）"
elif [ "$FORK_BEHIND" -ge 20 ]; then
  echo "⚠️  fork/main 落后 mirror/upstream-main $FORK_BEHIND commits（建议同步）"
elif [ "$FORK_BEHIND" -gt 0 ]; then
  echo "ℹ️  fork/main 落后 mirror/upstream-main $FORK_BEHIND commits（正常）"
else
  echo "✅ fork/main 与 mirror/upstream-main 对齐"
fi

# 检查 main 是否落后 upstream/main
MAIN_BEHIND=$(git rev-list --count main..upstream/main 2>/dev/null || echo "0")
if [ "$MAIN_BEHIND" -gt 0 ]; then
  echo "⚠️  main 落后 upstream/main $MAIN_BEHIND commits"
  echo "   建议运行: git checkout main && git merge --no-ff upstream/main"
else
  echo "✅ main 与 upstream/main 对齐（behind=0）"
fi

# 检查当前分枝
CURRENT_BRANCH=$(git symbolic-ref --short HEAD)
echo -e "\n📍 当前分枝: $CURRENT_BRANCH"

# 如果当前在 feat/* 分枝，检查冲突风险
if [[ $CURRENT_BRANCH == "feat/"* ]]; then
  if [[ $CURRENT_BRANCH == "feat/upstream/"* ]]; then
    BASE="mirror/upstream-main"
  else
    BASE="fork/main"
  fi
  
  echo "🔍 检查与 $BASE 的冲突风险..."
  
  # 干运行 merge 检查冲突
  if git merge --no-commit --no-ff "$BASE" > /dev/null 2>&1; then
    echo "✅ 无冲突风险"
    git merge --abort > /dev/null 2>&1
  else
    echo "⚠️  可能存在冲突："
    git diff --name-only --diff-filter=U | sed 's/^/   - /'
    git merge --abort > /dev/null 2>&1
    exit 1
  fi
fi

echo -e "\n✅ 检查完成"
