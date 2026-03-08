#!/bin/bash
# CoPaw Auto-Update Script
# 自动检查并更新 CoPaw 到最新版本

set -e

# 配置
COPAW_HOME="${COPAW_HOME:-$HOME/.copaw}"
LOG_DIR="${COPAW_HOME}/logs"
LOG_FILE="${LOG_DIR}/copaw-update.log"
SERVICE_NAME="copaw"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# 确保日志目录存在
mkdir -p "$LOG_DIR"

log() {
    local level="$1"
    local message="$2"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] [$level] $message" >> "$LOG_FILE"
    
    case "$level" in
        INFO)  echo -e "${BLUE}[$level]${NC} $message" ;;
        SUCCESS) echo -e "${GREEN}[$level]${NC} $message" ;;
        WARN)  echo -e "${YELLOW}[$level]${NC} $message" ;;
        ERROR) echo -e "${RED}[$level]${NC} $message" ;;
    esac
}

# 检查是否需要 sudo
check_sudo() {
    if [ "$EUID" -ne 0 ]; then
        echo -e "${RED}错误：此命令需要 sudo 权限${NC}"
        echo "请使用：sudo $0 [选项]"
        exit 1
    fi
}

# 检查版本不需要 sudo
check_version_no_sudo() {
    # 设置 PYTHONPATH 以访问用户安装的包（动态检测 Python 版本）
    export PYTHONPATH="$HOME/.local/lib/$(python3 -c 'import sys; print(f"python{sys.version_info.major}.{sys.version_info.minor}")')/site-packages:${PYTHONPATH:-}"
    
    local current=$(python3 -c "from importlib.metadata import version; print(version('copaw'))" 2>/dev/null || echo "not_installed")
    local latest=$(pip index versions copaw 2>/dev/null | head -1 | awk '{print $2}' | tr -d '()' || \
                   curl -s https://pypi.org/pypi/copaw/json 2>/dev/null | grep -o '"version":"[^"]*"' | head -1 | cut -d'"' -f4 || \
                   echo "unknown")
    
    echo -e "${BLUE}[INFO]${NC} 检查 CoPaw 更新..."
    echo -e "${BLUE}[INFO]${NC} 当前版本：$current"
    echo -e "${BLUE}[INFO]${NC} 最新版本：$latest"
    
    if [ "$current" = "$latest" ]; then
        echo -e "${GREEN}[SUCCESS]${NC} 已是最新版本 ($current)"
        return 0
    else
        echo -e "${YELLOW}[WARN]${NC} 发现新版本：$current → $latest"
        return 1
    fi
}

# 获取当前版本
get_current_version() {
    # 设置 PYTHONPATH 以访问用户安装的包（动态检测 Python 版本）
    export PYTHONPATH="$HOME/.local/lib/$(python3 -c 'import sys; print(f"python{sys.version_info.major}.{sys.version_info.minor}")')/site-packages:${PYTHONPATH:-}"
    
    # 使用 Python 直接查询（更可靠）
    local version=$(python3 -c "from importlib.metadata import version; print(version('copaw'))" 2>/dev/null)
    if [ -n "$version" ]; then
        echo "$version"
    else
        # 备用方法：pip show
        version=$(pip3 show copaw 2>/dev/null | grep "^Version:" | awk '{print $2}')
        if [ -n "$version" ]; then
            echo "$version"
        else
            echo "not_installed"
        fi
    fi
}

# 获取最新版本
get_latest_version() {
    local version=$(pip index versions copaw 2>/dev/null | head -1 | awk '{print $2}' | tr -d '()')
    if [ -n "$version" ]; then
        echo "$version"
    else
        # 备用方法：从 PyAPI 获取
        version=$(curl -s https://pypi.org/pypi/copaw/json 2>/dev/null | grep -o '"version":"[^"]*"' | head -1 | cut -d'"' -f4)
        echo "${version:-unknown}"
    fi
}

# 检查更新
check_update() {
    log "INFO" "检查 CoPaw 更新..."
    
    local current=$(get_current_version)
    local latest=$(get_latest_version)
    
    log "INFO" "当前版本：$current"
    log "INFO" "最新版本：$latest"
    
    if [ "$current" = "$latest" ]; then
        log "SUCCESS" "已是最新版本 ($current)"
        return 0
    else
        log "WARN" "发现新版本：$current → $latest"
        return 1
    fi
}

# 执行更新
do_update() {
    log "INFO" "开始更新 CoPaw..."
    
    # 停止服务
    log "INFO" "停止 CoPaw 服务..."
    systemctl stop ${SERVICE_NAME}.service 2>/dev/null || true
    
    # 等待服务完全停止
    sleep 2
    
    # 备份当前配置（可选）
    local backup_dir="${COPAW_HOME}/backups/$(date '+%Y%m%d_%H%M%S')"
    log "INFO" "备份配置到：$backup_dir"
    mkdir -p "$backup_dir"
    cp -r "${COPAW_HOME}/config.json" "$backup_dir/" 2>/dev/null || true
    cp -r "${COPAW_HOME}/memory/" "$backup_dir/" 2>/dev/null || true
    
    # 执行更新（使用 --break-system-packages 绕过 Ubuntu 限制）
    log "INFO" "执行 pip 更新..."
    pip install --upgrade copaw --break-system-packages 2>&1 | tee -a "$LOG_FILE"
    
    if [ ${PIPESTATUS[0]} -eq 0 ]; then
        local new_version=$(get_current_version)
        log "SUCCESS" "更新成功！新版本：$new_version"
        
        # 重启服务
        log "INFO" "重启 CoPaw 服务..."
        systemctl start ${SERVICE_NAME}.service
        
        # 等待服务启动
        sleep 3
        
        # 检查服务状态
        if systemctl is-active --quiet ${SERVICE_NAME}.service; then
            log "SUCCESS" "服务已重启并运行正常"
        else
            log "ERROR" "服务重启失败，请检查日志"
            return 1
        fi
        
        # 清理旧备份（保留最近 5 个）
        ls -t "${COPAW_HOME}/backups/" 2>/dev/null | tail -n +6 | xargs -I {} rm -rf "${COPAW_HOME}/backups/{}" 2>/dev/null || true
        
        return 0
    else
        log "ERROR" "更新失败！"
        
        # 尝试恢复服务
        log "INFO" "尝试恢复服务..."
        systemctl start ${SERVICE_NAME}.service
        
        return 1
    fi
}

# 显示帮助
usage() {
    echo "用法：$0 [选项]"
    echo ""
    echo "选项:"
    echo "  check     - 检查更新（不安装）"
    echo "  update    - 检查并更新到最新版本"
    echo "  force     - 强制更新（即使已是最新版本）"
    echo "  auto      - 自动模式（用于 cron，仅在有新版本时更新）"
    echo "  help      - 显示此帮助信息"
    echo ""
    echo "示例:"
    echo "  sudo $0 check     # 检查更新"
    echo "  sudo $0 update    # 更新到最新版本"
    echo "  sudo $0 auto      # 自动模式（cron 使用）"
    echo ""
    echo "日志文件：$LOG_FILE"
}

# 主逻辑
case "${1:-check}" in
    check)
        # check 命令不需要 sudo
        check_version_no_sudo
        ;;
    update)
        check_sudo
        log "INFO" "========== 手动更新开始 =========="
        do_update
        log "INFO" "========== 更新完成 =========="
        ;;
    force)
        check_sudo
        log "INFO" "========== 强制更新开始 =========="
        log "WARN" "强制更新模式（即使已是最新版本）"
        do_update
        log "INFO" "========== 更新完成 =========="
        ;;
    auto)
        check_sudo
        log "INFO" "========== 自动更新检查 =========="
        if check_update; then
            log "INFO" "无需更新，退出"
        else
            do_update
        fi
        log "INFO" "========== 自动更新检查完成 =========="
        ;;
    help|--help|-h)
        usage
        ;;
    *)
        echo -e "${RED}未知选项：$1${NC}"
        usage
        exit 1
        ;;
esac
