#!/bin/bash
# CoPaw 守护进程安装验证脚本

set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

COPAW_HOME="${COPAW_HOME:-$HOME/.copaw}"
SCRIPTS_DIR="${COPAW_HOME}/scripts"

echo -e "${BLUE}================================${NC}"
echo -e "${BLUE}CoPaw 守护进程安装验证${NC}"
echo -e "${BLUE}================================${NC}"
echo ""

# 测试计数器
TOTAL=0
PASSED=0
FAILED=0

# 测试函数
test_case() {
    local name="$1"
    local command="$2"
    TOTAL=$((TOTAL + 1))
    
    echo -n "测试 $TOTAL: $name ... "
    
    if eval "$command" > /dev/null 2>&1; then
        echo -e "${GREEN}✓ 通过${NC}"
        PASSED=$((PASSED + 1))
        return 0
    else
        echo -e "${RED}✗ 失败${NC}"
        FAILED=$((FAILED + 1))
        return 1
    fi
}

# 1. 文件存在性检查
echo -e "${YELLOW}1. 文件存在性检查${NC}"
test_case "copawd.sh 存在" "test -f ${SCRIPTS_DIR}/copawd.sh"
test_case "copaw.service 存在" "test -f ${SCRIPTS_DIR}/copaw.service"
test_case "manage-copawd.sh 存在" "test -f ${SCRIPTS_DIR}/manage-copawd.sh"
test_case "update-copaw.sh 存在" "test -f ${SCRIPTS_DIR}/update-copaw.sh"
test_case "setup-cron.sh 存在" "test -f ${SCRIPTS_DIR}/setup-cron.sh"
test_case "脚本可执行" "test -x ${SCRIPTS_DIR}/manage-copawd.sh"
echo ""

# 2. systemd 服务检查
echo -e "${YELLOW}2. systemd 服务检查${NC}"
test_case "服务文件已安装" "test -f /etc/systemd/system/copaw.service"
test_case "服务已启用" "systemctl is-enabled copaw.service"
test_case "服务正在运行" "systemctl is-active copaw.service"
echo ""

# 3. 进程检查
echo -e "${YELLOW}3. 进程检查${NC}"
test_case "copaw 进程存在" "pgrep -f 'copaw app'"
echo ""

# 4. 网络检查
echo -e "${YELLOW}4. 网络检查${NC}"
test_case "端口 8088 监听" "curl -s http://localhost:8088"
echo ""

# 5. 日志检查
echo -e "${YELLOW}5. 日志检查${NC}"
test_case "应用日志存在" "test -f ${COPAW_HOME}/logs/copaw.log"
test_case "日志目录可写" "test -w ${COPAW_HOME}/logs"
echo ""

# 6. 更新功能检查
echo -e "${YELLOW}6. 更新功能检查${NC}"
test_case "版本检测正常" "${SCRIPTS_DIR}/update-copaw.sh check"
echo ""

# 7. 权限检查
echo -e "${YELLOW}7. 权限检查${NC}"
CURRENT_USER=$(whoami)
test_case "脚本所有者正确" "test \$(stat -c '%U' ${SCRIPTS_DIR}/manage-copawd.sh) = '$CURRENT_USER'"
test_case "日志目录权限正确" "test -d ${COPAW_HOME}/logs"
echo ""

# 总结
echo -e "${BLUE}================================${NC}"
echo -e "${BLUE}测试总结${NC}"
echo -e "${BLUE}================================${NC}"
echo -e "总计：${TOTAL}"
echo -e "${GREEN}通过：${PASSED}${NC}"
echo -e "${RED}失败：${FAILED}${NC}"
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✓ 所有测试通过！CoPaw 守护进程配置正确。${NC}"
    exit 0
else
    echo -e "${RED}✗ 有 $FAILED 个测试失败，请检查配置。${NC}"
    exit 1
fi
