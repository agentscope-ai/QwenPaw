#!/bin/bash
# CoPaw Daemon Management Script
# 用于管理 CoPaw 守护进程

set -e

SERVICE_NAME="copaw"
# 使用环境变量或默认值（支持多用户）
COPAW_HOME="${COPAW_HOME:-$HOME/.copaw}"
SERVICE_FILE="${COPAW_HOME}/scripts/copaw.service"
LOG_FILE="${COPAW_HOME}/logs/copaw.log"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

usage() {
    echo "用法：$0 {install|start|stop|restart|status|logs|uninstall|update|update-check|setup-cron}"
    echo ""
    echo "命令说明:"
    echo "  install     - 安装 systemd 服务（需要 sudo）"
    echo "  start       - 启动服务（需要 sudo）"
    echo "  stop        - 停止服务（需要 sudo）"
    echo "  restart     - 重启服务（需要 sudo）"
    echo "  status      - 查看服务状态"
    echo "  logs        - 查看服务日志"
    echo "  uninstall   - 卸载服务（需要 sudo）"
    echo "  update      - 更新 CoPaw 到最新版本（需要 sudo）"
    echo "  update-check- 检查是否有新版本"
    echo "  setup-cron  - 配置定时自动更新（每周日凌晨 3 点）"
    exit 1
}

check_sudo() {
    if [ "$EUID" -ne 0 ]; then
        echo -e "${RED}错误：此命令需要 sudo 权限${NC}"
        echo "请使用：sudo $0 $1"
        exit 1
    fi
}

install_service() {
    check_sudo "install"
    echo -e "${YELLOW}正在安装 CoPaw 服务...${NC}"
    
    # 获取当前用户信息
    CURRENT_USER=$(whoami)
    CURRENT_HOME=$HOME
    
    # 复制并替换服务文件中的占位符
    sed -e "s/__USER__/${CURRENT_USER}/g" \
        -e "s/__GROUP__/${CURRENT_USER}/g" \
        -e "s|__HOME__|${CURRENT_HOME}|g" \
        -e "s|__COPAW_HOME__|${COPAW_HOME}|g" \
        "$SERVICE_FILE" > /etc/systemd/system/${SERVICE_NAME}.service
    
    # 重新加载 systemd 配置
    systemctl daemon-reload
    
    # 启用服务（开机自启）
    systemctl enable ${SERVICE_NAME}.service
    
    echo -e "${GREEN}✓ 服务安装成功${NC}"
    echo -e "${YELLOW}提示：使用 'sudo $0 start' 启动服务${NC}"
}

start_service() {
    check_sudo "start"
    echo -e "${YELLOW}正在启动 CoPaw 服务...${NC}"
    systemctl start ${SERVICE_NAME}.service
    echo -e "${GREEN}✓ 服务已启动${NC}"
}

stop_service() {
    check_sudo "stop"
    echo -e "${YELLOW}正在停止 CoPaw 服务...${NC}"
    systemctl stop ${SERVICE_NAME}.service
    echo -e "${GREEN}✓ 服务已停止${NC}"
}

restart_service() {
    check_sudo "restart"
    echo -e "${YELLOW}正在重启 CoPaw 服务...${NC}"
    systemctl restart ${SERVICE_NAME}.service
    echo -e "${GREEN}✓ 服务已重启${NC}"
}

check_status() {
    echo -e "${YELLOW}CoPaw 服务状态:${NC}"
    echo ""
    systemctl status ${SERVICE_NAME}.service --no-pager
}

view_logs() {
    echo -e "${YELLOW}最近 50 行日志:${NC}"
    echo ""
    
    # 优先使用 journalctl，如果不可用则查看日志文件
    if command -v journalctl &> /dev/null; then
        journalctl -u ${SERVICE_NAME}.service -n 50 --no-pager
    elif [ -f "$LOG_FILE" ]; then
        tail -n 50 "$LOG_FILE"
    else
        echo -e "${RED}日志文件不存在：$LOG_FILE${NC}"
    fi
}

uninstall_service() {
    check_sudo "uninstall"
    echo -e "${YELLOW}正在卸载 CoPaw 服务...${NC}"
    
    # 停止并禁用服务
    systemctl stop ${SERVICE_NAME}.service 2>/dev/null || true
    systemctl disable ${SERVICE_NAME}.service 2>/dev/null || true
    
    # 删除服务文件
    rm -f /etc/systemd/system/${SERVICE_NAME}.service
    
    # 重新加载 systemd 配置
    systemctl daemon-reload
    
    echo -e "${GREEN}✓ 服务已卸载${NC}"
}

# 添加更新相关命令的包装函数
do_update() {
    check_sudo "update"
    "${COPAW_HOME}/scripts/update-copaw.sh" update
}

do_update_check() {
    # update-check 不需要 sudo，但 update-copaw.sh 内部会检查
    "${COPAW_HOME}/scripts/update-copaw.sh" check
}

do_setup_cron() {
    "${COPAW_HOME}/scripts/setup-cron.sh"
}

# 主逻辑
case "${1:-}" in
    install)
        install_service
        ;;
    start)
        start_service
        ;;
    stop)
        stop_service
        ;;
    restart)
        restart_service
        ;;
    status)
        check_status
        ;;
    logs)
        view_logs
        ;;
    uninstall)
        uninstall_service
        ;;
    update)
        do_update
        ;;
    update-check)
        do_update_check
        ;;
    setup-cron)
        do_setup_cron
        ;;
    *)
        usage
        ;;
esac
