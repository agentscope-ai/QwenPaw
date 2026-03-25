#!/usr/bin/env bash
# F1: CoPaw 健康检查脚本 — 含业务层指标
# 用法: ./scripts/health-check.sh [copaw_port]

set -uo pipefail

PORT="${1:-8088}"
COPAW_DIR="${COPAW_DIR:-/home/ixiadao/.copaw}"
WORKSPACES="$COPAW_DIR/workspaces"

RED=$'\033[0;31m'
YEL=$'\033[1;33m'
GRN=$'\033[0;32m'
BLU=$'\033[0;34m'
NC=$'\033[0m'

WARN_COUNT=0

ok()      { echo "  ${GRN}[OK]${NC}   $*"; }
warn()    { echo "  ${YEL}[WARN]${NC} $*"; WARN_COUNT=$((WARN_COUNT+1)); }
fail()    { echo "  ${RED}[FAIL]${NC} $*"; WARN_COUNT=$((WARN_COUNT+1)); }
info()    { echo "  ${BLU}[INFO]${NC} $*"; }
section() { echo ""; echo "${BLU}=== $* ===${NC}"; }

export WORKSPACES

# ─────────────────────────────────────────
# 1. 服务进程
# ─────────────────────────────────────────
section "服务进程"
if pgrep -f "copaw app" > /dev/null 2>&1; then
    PID=$(pgrep -f "copaw app" | head -1)
    ok "copaw 进程运行中 (pid=$PID)"
else
    fail "copaw 进程未运行"
fi

# ─────────────────────────────────────────
# 2. HTTP 接口
# ─────────────────────────────────────────
section "HTTP 接口"
VERSION=$(curl -s --max-time 3 "http://127.0.0.1:$PORT/api/version" 2>/dev/null || echo "")
if echo "$VERSION" | grep -q 'version'; then
    VER=$(echo "$VERSION" | python3 -c "import sys,json; print(json.load(sys.stdin).get('version','?'))" 2>/dev/null || echo "?")
    ok "API 响应正常 (version=$VER, port=$PORT)"
else
    fail "API 无响应 (port=$PORT)"
fi

# ─────────────────────────────────────────
# 3. 错误日志扫描
# ─────────────────────────────────────────
section "错误日志"
LOG_FILE=$(find "$COPAW_DIR" -name '*.log' 2>/dev/null | head -1)
if [ -n "${LOG_FILE:-}" ]; then
    ERR_COUNT=$(tail -200 "$LOG_FILE" 2>/dev/null | grep -c 'ERROR\|CRITICAL' || true)
    if [ "$ERR_COUNT" -gt 10 ]; then
        warn "最近 200 行日志中有 $ERR_COUNT 条 ERROR/CRITICAL"
    else
        ok "日志错误数正常 ($ERR_COUNT 条)"
    fi
else
    info "未找到日志文件，跳过"
fi

# ─────────────────────────────────────────
# 4. 业务层 — Mailbox 积压
# ─────────────────────────────────────────
section "业务层 — Mailbox 积压"
TOTAL_INBOX=0
AGENT_WARN=0
if [ -d "$WORKSPACES" ]; then
    for agent_dir in "$WORKSPACES"/*/; do
        [ -d "$agent_dir" ] || continue
        agent_name=$(basename "$agent_dir")
        inbox_dir="$agent_dir/mailbox/inbox"
        if [ -d "$inbox_dir" ]; then
            count=$(find "$inbox_dir" -name '*.json' 2>/dev/null | wc -l)
            TOTAL_INBOX=$((TOTAL_INBOX + count))
            if [ "$count" -gt 10 ]; then
                warn "[$agent_name] inbox 积压 $count 条（阈值 10）"
                AGENT_WARN=$((AGENT_WARN+1))
            else
                info "[$agent_name] inbox 积压 $count 条"
            fi
        fi
    done
fi
if [ "$AGENT_WARN" -eq 0 ]; then
    ok "所有 agent inbox 积压正常（总计 $TOTAL_INBOX 条）"
fi

# ─────────────────────────────────────────
# 5. 业务层 — Task Board
# ─────────────────────────────────────────
section "业务层 — Task Board"

if command -v python3 &>/dev/null; then
    TASK_REPORT=$(python3 << 'PYEOF'
import json, os, sys, time
from pathlib import Path

workspaces = os.environ.get('WORKSPACES', '')
now = time.time()
orphan_count = 0
blocked_overtime = 0
status_totals = {}
teams_found = 0

for tasks_file in Path(workspaces).glob('*/teams/*/tasks.json'):
    teams_found += 1
    try:
        tasks = json.loads(tasks_file.read_text(encoding='utf-8'))
    except Exception:
        continue
    for t in tasks:
        status = t.get('status', 'unknown')
        status_totals[status] = status_totals.get(status, 0) + 1
        # 孤儿任务: claimed 超过 30 分钟无 started_at
        if status == 'claimed':
            claimed_at = t.get('claimed_at')
            started_at = t.get('started_at')
            if claimed_at and not started_at:
                if (now - claimed_at) > 1800:
                    orphan_count += 1
        # blocked 超过 1 小时
        if status == 'blocked':
            ts = t.get('submitted_at') or t.get('claimed_at') or t.get('created_at')
            if ts and (now - ts) > 3600:
                blocked_overtime += 1

print(f'ORPHAN={orphan_count}')
print(f'BLOCKED_OVERTIME={blocked_overtime}')
print(f'TEAMS={teams_found}')
for k, v in sorted(status_totals.items()):
    print(f'STATUS_{k.upper()}={v}')
PYEOF
    )

    ORPHAN=0; BLOCKED_OVERTIME=0; TEAMS=0
    STATUS_PENDING=0; STATUS_CLAIMED=0; STATUS_IN_PROGRESS=0
    STATUS_SUBMITTED=0; STATUS_BLOCKED=0; STATUS_COMPLETED=0
    eval "$TASK_REPORT" 2>/dev/null || true

    info "扫描到 $TEAMS 个团队"
    STATUS_LINE=""
    [ "$STATUS_PENDING" -gt 0 ]     && STATUS_LINE="$STATUS_LINE pending=$STATUS_PENDING"
    [ "$STATUS_CLAIMED" -gt 0 ]     && STATUS_LINE="$STATUS_LINE claimed=$STATUS_CLAIMED"
    [ "$STATUS_IN_PROGRESS" -gt 0 ] && STATUS_LINE="$STATUS_LINE in_progress=$STATUS_IN_PROGRESS"
    [ "$STATUS_SUBMITTED" -gt 0 ]   && STATUS_LINE="$STATUS_LINE submitted=$STATUS_SUBMITTED"
    [ "$STATUS_BLOCKED" -gt 0 ]     && STATUS_LINE="$STATUS_LINE blocked=$STATUS_BLOCKED"
    [ "$STATUS_COMPLETED" -gt 0 ]   && STATUS_LINE="$STATUS_LINE completed=$STATUS_COMPLETED"
    [ -n "$STATUS_LINE" ] && info "任务分布:$STATUS_LINE"

    if [ "$ORPHAN" -gt 3 ]; then
        warn "孤儿任务 $ORPHAN 个（claimed >30分钟无响应，阈值 3）"
    else
        ok "孤儿任务 $ORPHAN 个（正常）"
    fi

    if [ "$BLOCKED_OVERTIME" -gt 0 ]; then
        warn "blocked 超 1 小时任务 $BLOCKED_OVERTIME 个"
    else
        ok "无超时 blocked 任务"
    fi
else
    warn "python3 不可用，跳过 task board 检查"
fi

# ─────────────────────────────────────────
# 6. 业务层 — Active Rooms
# ─────────────────────────────────────────
section "业务层 — Active Rooms"
ROOM_WARN=0
ACTIVE_ROOMS=0

if command -v python3 &>/dev/null && [ -d "$WORKSPACES" ]; then
    ROOM_REPORT=$(python3 << 'PYEOF'
import json, os, time
from pathlib import Path

workspaces = os.environ.get('WORKSPACES', '')
now = time.time()
active_rooms = 0
timeout_rooms = []

for meta_f in Path(workspaces).glob('*/mailbox/rooms/*/meta.json'):
    try:
        d = json.loads(meta_f.read_text(encoding='utf-8'))
    except Exception:
        continue
    if d.get('status') != 'active':
        continue
    active_rooms += 1
    round_timeout = d.get('round_timeout_sec', 300)
    last_msg_at = d.get('last_msg_at', 0)
    if last_msg_at and (now - last_msg_at) > round_timeout:
        age_min = int((now - last_msg_at) / 60)
        room_id = d.get('room_id', '?')
        timeout_rooms.append(f'{room_id} 超时 {age_min} 分钟 (限 {round_timeout}s)')

print(f'ACTIVE_ROOMS={active_rooms}')
for r in timeout_rooms:
    print(f'TIMEOUT_ROOM={r}')
PYEOF
    )

    while IFS= read -r line; do
        key="${line%%=*}"
        val="${line#*=}"
        case "$key" in
            ACTIVE_ROOMS) ACTIVE_ROOMS="$val" ;;
            TIMEOUT_ROOM) warn "Room 超时: $val"; ROOM_WARN=$((ROOM_WARN+1)) ;;
        esac
    done <<< "$ROOM_REPORT"
fi

if [ "$ACTIVE_ROOMS" -eq 0 ]; then
    ok "无 active room"
elif [ "$ROOM_WARN" -eq 0 ]; then
    ok "$ACTIVE_ROOMS 个 active room，无超时轮次"
else
    info "$ACTIVE_ROOMS 个 active room，$ROOM_WARN 个有超时（已 WARN）"
fi

# ─────────────────────────────────────────
# 7. AutoPoll 指标
# ─────────────────────────────────────────
section "AutoPoll 指标"
METRICS_FOUND=0
for metrics_f in "$WORKSPACES"/*/autopoll_metrics.json; do
    [ -f "$metrics_f" ] || continue
    METRICS_FOUND=$((METRICS_FOUND+1))
    agent_name=$(basename "$(dirname "$metrics_f")")
    metrics=$(python3 -c "
import json
d=json.load(open('$metrics_f'))
print(', '.join(f'{k}={v}' for k,v in d.items()))
" 2>/dev/null || echo "解析失败")
    info "[$agent_name] $metrics"
done
[ "$METRICS_FOUND" -eq 0 ] && info "暂无 autopoll_metrics.json（agent 未运行或尚未生成）"

# ─────────────────────────────────────────
# 汇总
# ─────────────────────────────────────────
section "汇总"
if [ "$WARN_COUNT" -eq 0 ]; then
    echo "${GRN}✓ 所有检查通过${NC}"
else
    echo "${YEL}⚠ 共 $WARN_COUNT 项需关注（见上方 [WARN]/[FAIL]）${NC}"
fi
echo "检查时间: $(date '+%Y-%m-%d %H:%M:%S')"
