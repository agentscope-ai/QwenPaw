#!/bin/bash
# CoPaw Supabase Auth Setup Script
# 这个脚本帮助用户快速配置 Supabase 认证

set -e

echo "========================================"
echo "  CoPaw Supabase 认证配置向导"
echo "========================================"
echo ""

# 检查 Node.js
if ! command -v node &> /dev/null; then
    echo "❌ 错误: Node.js 未安装"
    echo "   请先安装 Node.js: https://nodejs.org/"
    exit 1
fi

echo "✓ Node.js 已安装: $(node --version)"

# 检查 pnpm/npm
if command -v pnpm &> /dev/null; then
    PACKAGE_MANAGER="pnpm"
elif command -v npm &> /dev/null; then
    PACKAGE_MANAGER="npm"
else
    echo "❌ 错误: 未找到 pnpm 或 npm"
    echo "   请安装其中一个包管理器"
    exit 1
fi

echo "✓ 包管理器: $PACKAGE_MANAGER"

# 安装前端依赖
cd /data/CoPaw/website

echo ""
echo "📦 正在安装前端依赖..."
$PACKAGE_MANAGER install @supabase/supabase-js

echo ""
echo "========================================"
echo "  下一步操作"
echo "========================================"
echo ""
echo "1. 在 https://supabase.com 创建新项目"
echo ""
echo "2. 获取 API 密钥:"
echo "   - 进入 Project Settings → API"
echo "   - 复制 Project URL"
echo "   - 复制 anon/public key"
echo ""
echo "3. 编辑配置文件:"
echo "   vim /data/CoPaw/website/.env"
echo ""
echo "   填入以下内容:"
echo "   VITE_SUPABASE_URL=你的项目 URL"
echo "   VITE_SUPABASE_ANON_KEY=你的 anon key"
echo ""
echo "4. (可选) 后端 Supabase 集成:"
echo "   pip install supabase"
echo ""
echo "5. 启动开发服务器:"
echo "   $PACKAGE_MANAGER run dev"
echo ""
echo "详细的配置指南请查看:"
echo "  /data/CoPaw/docs/SUPABASE_AUTH_SETUP.md"
echo ""
echo "✨ 配置完成！"
