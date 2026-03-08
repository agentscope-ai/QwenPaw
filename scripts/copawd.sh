#!/bin/bash
# CoPaw Daemon Start Script
# 用于 systemd 服务启动 CoPaw

set -e

# 配置（使用环境变量或默认值）
COPAW_HOME="${COPAW_HOME:-$HOME/.copaw}"
LOG_DIR="${COPAW_HOME}/logs"

# 确保日志目录存在
mkdir -p "$LOG_DIR"

# 激活虚拟环境（如果有）或使用全局安装
if [ -f "$HOME/.local/bin/copaw" ]; then
    COPAW_CMD="$HOME/.local/bin/copaw"
elif command -v copaw &> /dev/null; then
    COPAW_CMD="copaw"
else
    echo "Error: copaw command not found"
    exit 1
fi

# 记录启动信息（输出到 stdout，由 systemd/journald 统一管理）
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting CoPaw daemon..."

# 启动 CoPaw app（FastAPI 服务）
# 使用 exec 替换 shell 进程，确保信号正确传递
# 日志由 systemd/journald 统一管理
exec "$COPAW_CMD" app