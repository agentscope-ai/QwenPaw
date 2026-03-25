#!/bin/bash
# sync-all.sh - 一键同步 fork 仓库到最新 upstream
# 用法: ./scripts/sync-all.sh

set -e

REPO_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_PATH"

echo "📦 开始同步..."

# Step 1: 获取最新
echo "🔄 获取最新提交..."
git fetch origin --prune 2>/dev/null || true
git fetch upstream --prune 2>/dev/null || true

# Step 2: 更新 mirror
echo "🔄 更新 mirror/upstream-main..."
git checkout mirror/upstream-main > /dev/null 2>&1
git reset --hard upstream/main > /dev/null 2>&1
MIRROR_COMMIT=$(git rev-parse --short HEAD)
echo "   ✅ mirror/upstream-main 已更新到 $MIRROR_COMMIT"

# Step 3: 更新 fork/main
echo "🔄 更新 fork/main..."
git checkout fork/main > /dev/null 2>&1

BEFORE=$(git rev-list --count fork/main..mirror/upstream-main 2>/dev/null || echo "0")
if [ "$BEFORE" -eq 0 ]; then
  echo "   ℹ️  fork/main 已与 mirror/upstream-main 对齐，无需更新"
else
  echo "   ℹ️  fork/main 落后 $BEFORE commits，尝试 rebase..."
  
  if git rebase mirror/upstream-main > /dev/null 2>&1; then
    AFTER=$(git rev-list --count fork/main..mirror/upstream-main 2>/dev/null || echo "0")
    echo "   ✅ fork/main rebase 成功（本地提交: $AFTER）"
  else
    CONFLICT_FILES=$(git diff --name-only --diff-filter=U | wc -l)
    echo "   ❌ rebase 冲突！冲突文件数: $CONFLICT_FILES"
    git diff --name-only --diff-filter=U | sed 's/^/      - /'
    echo ""
    echo "   💡 提示："
    echo "      1. 手动解决冲突"
    echo "      2. git add <files>"
    echo "      3. git rebase --continue"
    exit 1
  fi
fi

# Step 4: 推送（可选）
echo ""
read -p "推送到 origin/fork/main？(y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
  git push --force-with-lease origin fork/main > /dev/null 2>&1
  echo "✅ fork/main 已推送"
fi

echo ""
echo "🎉 同步完成"
