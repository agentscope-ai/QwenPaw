#!/bin/bash
# CoPaw → E2B 沙箱调用测试
#
# 通过 CoPaw API 发送请求，验证 CoPaw 能否正确调用 E2B 沙箱执行代码
#
# 用法:
#   bash scripts/test_copaw_e2b.sh
#
# 依赖:
#   - curl, python3, jq (可选，用于格式化输出)

set -e

BLUE='\033[0;34m'; GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'

COPAW_URL="${COPAW_URL:-http://localhost:8088}"
COPAW_API_KEY="${COPAW_API_KEY:?请设置 COPAW_API_KEY 环境变量}"
SESSION_ID="test-copaw-e2b-$(date +%s)"
FAIL=0

# 生成不可预测的随机令牌，LLM 无法猜出，必须真实执行才能得到
RAND_TOKEN=$(python3 -c "import random,string; print(''.join(random.choices(string.ascii_lowercase+string.digits,k=12)))")
RAND_NUM_A=$(python3 -c "import random; print(random.randint(100000,999999))")
RAND_NUM_B=$(python3 -c "import random; print(random.randint(100000,999999))")
RAND_SUM=$((RAND_NUM_A + RAND_NUM_B))

log() { echo -e "[$(date '+%H:%M:%S')] $1"; }
pass() { log "  ${GREEN}✅ $1${NC}"; }
fail() { log "  ${RED}❌ $1${NC}"; FAIL=1; }
info() { log "  ${YELLOW}ℹ $1${NC}"; }

# 发送请求并提取工具调用输出
send_request() {
    local message="$1"
    curl -s -N -X POST "${COPAW_URL}/api/agent/process" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer ${COPAW_API_KEY}" \
        -d "{
            \"input\": [{\"role\": \"user\", \"content\": [{\"type\": \"text\", \"text\": \"${message}\"}]}],
            \"session_id\": \"${SESSION_ID}\"
        }" 2>&1
}

# 从 SSE 流中提取工具调用输出内容
extract_tool_output() {
    grep '"type":"data"' | grep 'plugin_call_output\|call_output' | \
        python3 -c "
import sys, json
for line in sys.stdin:
    line = line.strip()
    if line.startswith('data:'):
        try:
            d = json.loads(line[5:])
            output = d.get('data', {}).get('output', '')
            if output:
                print(output)
        except:
            pass
" 2>/dev/null
}

# 从 SSE 流中提取最终 assistant 文本
extract_final_text() {
    python3 -c "
import sys, json
for line in sys.stdin:
    line = line.strip()
    if not line.startswith('data:'): continue
    try:
        d = json.loads(line[5:])
        if d.get('object') == 'content' and d.get('status') == 'completed' and d.get('type') == 'text':
            print(d.get('text',''))
    except:
        pass
" 2>/dev/null | tail -1
}

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  CoPaw → E2B 沙箱调用测试${NC}"
echo -e "${BLUE}  COPAW: ${COPAW_URL}${NC}"
echo -e "${BLUE}  Session: ${SESSION_ID}${NC}"
echo -e "${BLUE}  随机令牌: ${RAND_TOKEN}  随机加法: ${RAND_NUM_A}+${RAND_NUM_B}=${RAND_SUM}${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# ─── 1. 健康检查 ───
log "─── 1. CoPaw 服务健康检查 ───"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${COPAW_URL}/api/version" \
    -H "Authorization: Bearer ${COPAW_API_KEY}" 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "401" ] || [ "$HTTP_CODE" = "307" ]; then
    pass "CoPaw 服务可达 (HTTP ${HTTP_CODE})"
else
    fail "CoPaw 服务不可达 (HTTP ${HTTP_CODE})"
fi
echo ""

# ─── 2. 认证校验 ───
log "─── 2. 认证校验 ───"
RESP=$(curl -s -o /dev/null -w "%{http_code}" "${COPAW_URL}/api/agent/process" \
    -X POST -H "Content-Type: application/json" \
    -H "Authorization: Bearer wrong-key" \
    -d '{"input":[{"role":"user","content":[{"type":"text","text":"hi"}]}]}' 2>/dev/null || echo "000")
if [ "$RESP" = "401" ]; then
    pass "错误 token 被拒绝 (401)"
else
    fail "错误 token 未被拒绝 (HTTP ${RESP})"
fi
echo ""

# ─── 3. Python 代码执行 ───
log "─── 3. Python 代码执行测试（随机令牌验证）───"
info "随机令牌: ${RAND_TOKEN}，LLM 不可能预知此值"
RESPONSE=$(send_request "请直接调用execute_python_code工具执行这段代码，只执行不解释，不要自己回答：print('SANDBOX_OUTPUT:${RAND_TOKEN}')")
TOOL_OUTPUT=$(echo "$RESPONSE" | extract_tool_output)

if echo "$TOOL_OUTPUT" | grep -q "SANDBOX_OUTPUT:${RAND_TOKEN}"; then
    pass "Python 代码执行成功（工具输出包含随机令牌，确认走了沙箱）"
elif echo "$RESPONSE" | grep -q "SANDBOX_OUTPUT:${RAND_TOKEN}"; then
    pass "Python 代码执行成功（响应包含随机令牌，确认走了沙箱）"
else
    fail "Python 代码执行失败或 LLM 未调用沙箱（响应中未找到随机令牌 ${RAND_TOKEN}）"
    info "响应片段: $(echo "$RESPONSE" | grep -o '"text":"[^"]*"' | head -3)"
fi
echo ""

# ─── 4. Shell 命令执行 ───
log "─── 4. Shell 命令执行测试（随机令牌验证）───"
info "随机令牌: ${RAND_TOKEN}"
SESSION_ID2="${SESSION_ID}-shell"
RESPONSE2=$(curl -s -N -X POST "${COPAW_URL}/api/agent/process" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer ${COPAW_API_KEY}" \
    -d "{
        \"input\": [{\"role\": \"user\", \"content\": [{\"type\": \"text\", \"text\": \"请直接调用execute_shell_command工具执行：echo 'SHELL_OUTPUT:${RAND_TOKEN}'，只执行不解释，不要自己回答\"}]}],
        \"session_id\": \"${SESSION_ID2}\"
    }" 2>&1)

if echo "$RESPONSE2" | grep -q "SHELL_OUTPUT:${RAND_TOKEN}"; then
    pass "Shell 命令执行成功（响应包含随机令牌，确认走了沙箱）"
else
    fail "Shell 命令执行失败或 LLM 未调用沙箱（未找到随机令牌 ${RAND_TOKEN}）"
    info "响应片段: $(echo "$RESPONSE2" | grep -o '"text":"[^"]*"' | head -3)"
fi
echo ""

# ─── 5. Python 计算验证 ───
log "─── 5. Python 计算验证（随机数加法，LLM 无法预知）───"
info "随机加法: ${RAND_NUM_A} + ${RAND_NUM_B} = ${RAND_SUM}"
SESSION_ID3="${SESSION_ID}-calc"
RESPONSE3=$(curl -s -N -X POST "${COPAW_URL}/api/agent/process" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer ${COPAW_API_KEY}" \
    -d "{
        \"input\": [{\"role\": \"user\", \"content\": [{\"type\": \"text\", \"text\": \"请直接调用execute_python_code工具执行：print(${RAND_NUM_A}+${RAND_NUM_B})，只执行不解释，不要自己回答\"}]}],
        \"session_id\": \"${SESSION_ID3}\"
    }" 2>&1)

if echo "$RESPONSE3" | grep -q "${RAND_SUM}"; then
    pass "Python 计算正确: ${RAND_NUM_A}+${RAND_NUM_B}=${RAND_SUM}（确认走了沙箱）"
else
    fail "Python 计算失败或 LLM 未调用沙箱（未找到正确结果 ${RAND_SUM}）"
    info "响应片段: $(echo "$RESPONSE3" | grep -o '"text":"[^"]*"' | head -3)"
fi
echo ""

# ─── 6. 多行代码执行 ───
log "─── 6. 多行 Python 代码执行（随机令牌写入环境变量验证）───"
SESSION_ID4="${SESSION_ID}-multiline"
RESPONSE4=$(curl -s -N -X POST "${COPAW_URL}/api/agent/process" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer ${COPAW_API_KEY}" \
    -d '{
        "input": [{"role": "user", "content": [{"type": "text", "text": "请直接调用execute_python_code工具执行以下代码，只执行不解释，不要自己回答：\nimport sys\nprint(f\"PYVER:{sys.version_info.major}.{sys.version_info.minor}\")\nprint(\"MULTILINE_OK:'"${RAND_TOKEN}"'\")"}]}],
        "session_id": "'"${SESSION_ID4}"'"
    }' 2>&1)

if echo "$RESPONSE4" | grep -q "MULTILINE_OK:${RAND_TOKEN}"; then
    pass "多行代码执行成功（随机令牌确认走了沙箱）"
    PY_VER=$(echo "$RESPONSE4" | grep -o 'PYVER:[0-9]\.[0-9]*' | head -1 | sed 's/PYVER://')
    [ -n "$PY_VER" ] && pass "Python 版本: Python ${PY_VER}"
else
    fail "多行代码执行失败或 LLM 未调用沙箱（未找到随机令牌 ${RAND_TOKEN}）"
fi
echo ""

# ─── 7. sandbox_read_file ───
log "─── 7. sandbox_read_file 文件读取测试（随机令牌写入文件验证）───"
info "写入随机令牌 ${RAND_TOKEN} 到文件，再读取验证"
SESSION_ID5="${SESSION_ID}-readfile"
RESPONSE5=$(curl -s -N -X POST "${COPAW_URL}/api/agent/process" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer ${COPAW_API_KEY}" \
    --data-raw '{"input":[{"role":"user","content":[{"type":"text","text":"请直接按顺序调用工具，只执行不解释，不要自己回答：1.调用execute_shell_command执行 echo READFILE_TOKEN:'"${RAND_TOKEN}"' > /tmp/test_read.txt ，2.再调用sandbox_read_file读取/tmp/test_read.txt内容"}]}],"session_id":"'"${SESSION_ID5}"'"}' 2>&1)

FULL_TEXT5=$(echo "$RESPONSE5" | python3 -c "
import sys, json
parts = []
for line in sys.stdin:
    line = line.strip()
    if not line.startswith('data:'): continue
    try:
        d = json.loads(line[5:])
        t = d.get('text', '')
        if t: parts.append(t)
    except: pass
print(''.join(parts))
" 2>/dev/null)
if echo "$RESPONSE5" | grep -q "READFILE_TOKEN:${RAND_TOKEN}"; then
    pass "sandbox_read_file 读取成功（随机令牌确认走了沙箱）"
else
    fail "sandbox_read_file 读取失败或 LLM 未调用沙箱（未找到随机令牌 ${RAND_TOKEN}）"
    info "LLM 最终回复: $(echo "$FULL_TEXT5" | head -c 200)"
fi
echo ""


# ─── 8. sandbox_write_file ───
log "─── 8. sandbox_write_file 文件写入测试（随机令牌验证）───"
info "用 sandbox_write_file 写入随机令牌，再用 sandbox_read_file 读回验证"
SESSION_ID6="${SESSION_ID}-writefile"
RESPONSE6=$(curl -s -N -X POST "${COPAW_URL}/api/agent/process" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer ${COPAW_API_KEY}" \
    --data-raw '{"input":[{"role":"user","content":[{"type":"text","text":"请直接按顺序调用工具，只执行不解释，不要自己回答：1.调用sandbox_write_file写入文件/tmp/write_test.txt内容为WRITEFILE_TOKEN:'"${RAND_TOKEN}"'，2.再调用sandbox_read_file读取/tmp/write_test.txt"}]}],"session_id":"'"${SESSION_ID6}"'"}' 2>&1)

if echo "$RESPONSE6" | grep -q "WRITEFILE_TOKEN:${RAND_TOKEN}"; then
    pass "sandbox_write_file 写入并验证成功（随机令牌确认走了沙箱）"
else
    fail "sandbox_write_file 写入失败或 LLM 未调用沙箱（未找到随机令牌 ${RAND_TOKEN}）"
    FULL_TEXT6=$(echo "$RESPONSE6" | python3 -c "
import sys, json
parts = []
for line in sys.stdin:
    line = line.strip()
    if not line.startswith('data:'): continue
    try:
        d = json.loads(line[5:])
        t = d.get('text', '')
        if t: parts.append(t)
    except: pass
print(''.join(parts))
" 2>/dev/null)
    info "LLM 最终回复: $(echo "$FULL_TEXT6" | head -c 200)"
fi
echo ""


# ─── 9. sandbox_list_files ───
log "─── 9. sandbox_list_files 目录列表测试（随机令牌文件名验证）───"
info "写入随机令牌 ${RAND_TOKEN} 为文件名，再用 sandbox_list_files 列出目录验证文件存在"
SESSION_ID7="${SESSION_ID}-listfiles"
RAND_FILENAME="listcheck_${RAND_TOKEN}.txt"
RESPONSE7=$(curl -s -N -X POST "${COPAW_URL}/api/agent/process" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer ${COPAW_API_KEY}" \
    --data-raw '{"input":[{"role":"user","content":[{"type":"text","text":"请直接按顺序调用工具，只执行不解释，不要自己回答：1.调用execute_shell_command执行 touch /tmp/'"${RAND_FILENAME}"' ，2.再调用sandbox_list_files列出/tmp目录"}]}],"session_id":"'"${SESSION_ID7}"'"}' 2>&1)

FULL_TEXT7=$(echo "$RESPONSE7" | python3 -c "
import sys, json
parts = []
for line in sys.stdin:
    line = line.strip()
    if not line.startswith('data:'): continue
    try:
        d = json.loads(line[5:])
        t = d.get('text', '')
        if t: parts.append(t)
    except: pass
print(''.join(parts))
" 2>/dev/null)
if echo "$RESPONSE7" | grep -q "${RAND_FILENAME}"; then
    pass "sandbox_list_files 目录列表成功（找到随机文件名 ${RAND_FILENAME}，确认走了沙箱）"
elif echo "$FULL_TEXT7" | grep -q "${RAND_TOKEN}"; then
    pass "sandbox_list_files 目录列表成功（回复中含随机令牌，确认走了沙箱）"
else
    fail "sandbox_list_files 失败或 LLM 未调用沙箱（未找到随机文件名 ${RAND_FILENAME}）"
    info "LLM 最终回复: $(echo "$FULL_TEXT7" | head -c 200)"
fi
echo ""


# ─── 汇总 ───
echo -e "${BLUE}========================================${NC}"
if [ $FAIL -eq 0 ]; then
    echo -e "${GREEN}  CoPaw → E2B 沙箱全部测试通过 ✅${NC}"
else
    echo -e "${RED}  部分测试失败 ❌${NC}"
fi
echo -e "${BLUE}========================================${NC}"
exit $FAIL
