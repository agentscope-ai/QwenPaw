#!/bin/bash
# CoPaw Cron Setup Script
# 配置定时任务：自动更新检查和心跳任务

set -e

# 配置
COPAW_HOME="${COPAW_HOME:-$HOME/.copaw}"
UPDATE_SCRIPT="${COPAW_HOME}/scripts/update-copaw.sh"
LOG_DIR="${COPAW_HOME}/logs"

# 颜色输出
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}CoPaw 定时任务配置${NC}"
echo "================================"
echo ""

# 确保日志目录存在
mkdir -p "$LOG_DIR"

# 确保更新脚本可执行
chmod +x "$UPDATE_SCRIPT"

# 获取当前用户的 crontab
current_crontab=$(crontab -l 2>/dev/null || echo "")

# 定义 CoPaw 相关的 cron 任务
# 每天凌晨 3 点自动更新检查
auto_update_cron="0 3 * * * sudo ${UPDATE_SCRIPT} auto >> ${LOG_DIR}/cron-update.log 2>&1"

# 检查是否已存在
if echo "$current_crontab" | grep -q "update-copaw.sh"; then
    echo -e "${YELLOW}⚠️  已存在 CoPaw 自动更新任务${NC}"
    echo ""
    echo "当前配置:"
    echo "$current_crontab" | grep "update-copaw.sh" || true
    echo ""
    read -p "是否要更新配置？(y/N): " confirm
    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        echo "取消操作"
        exit 0
    fi
    
    # 删除旧的 CoPaw 相关任务
    current_crontab=$(echo "$current_crontab" | grep -v "update-copaw.sh" || true)
fi

echo ""
echo -e "${YELLOW}即将添加以下定时任务:${NC}"
echo ""
echo "📅 自动更新检查：每天凌晨 3 点"
echo "   $auto_update_cron"
echo ""

read -p "确认添加？(y/N): " confirm
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "取消操作"
    exit 0
fi

# 添加新任务
if [ -n "$current_crontab" ]; then
    new_crontab="${current_crontab}
${auto_update_cron}"
else
    new_crontab="${auto_update_cron}"
fi

# 安装 crontab
echo "$new_crontab" | crontab -

echo ""
echo -e "${GREEN}✓ 定时任务配置成功！${NC}"
echo ""
echo "查看当前所有定时任务:"
echo "  crontab -l"
echo ""
echo "查看更新日志:"
echo "  tail -f ${LOG_DIR}/cron-update.log"
echo ""
echo "手动测试更新:"
echo "  sudo ${UPDATE_SCRIPT} update"
echo ""
