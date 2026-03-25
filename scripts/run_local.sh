#!/usr/bin/env bash
# 本地运行 CoPaw
# 用法: ./scripts/run_local.sh
# 要求: Python >= 3.10（macOS 自带 3.9 不够，需先 brew install python@3.12）

set -e
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

# ---------- 找到 Python >= 3.10 ----------
PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" &>/dev/null; then
        ver=$("$candidate" -c "import sys; print(sys.version_info[:2])")
        major=$("$candidate" -c "import sys; print(sys.version_info[0])")
        minor=$("$candidate" -c "import sys; print(sys.version_info[1])")
        if [[ "$major" -ge 3 && "$minor" -ge 10 ]]; then
            PYTHON="$(command -v "$candidate")"
            break
        fi
    fi
done
if [[ -z "$PYTHON" ]]; then
    echo "[run_local] 错误: 需要 Python >= 3.10，当前系统未找到。" >&2
    echo "[run_local] 请先安装:  brew install python@3.12" >&2
    exit 1
fi
echo "[run_local] 使用 Python: $PYTHON ($($PYTHON --version))"

# ---------- 创建/激活虚拟环境 ----------
if [[ ! -d "$ROOT/.venv" ]]; then
    echo "[run_local] 创建 .venv ..."
    "$PYTHON" -m venv "$ROOT/.venv"
fi
source "$ROOT/.venv/bin/activate"
VENV_PY="$ROOT/.venv/bin/python"
PIP_CMD=("$VENV_PY" -m pip)
# 某些环境创建 venv 时不会自动带 pip，先自愈一次
if ! "${PIP_CMD[@]}" --version >/dev/null 2>&1; then
    echo "[run_local] 当前虚拟环境缺少 pip，正在尝试通过 ensurepip 修复 ..."
    if ! "$VENV_PY" -m ensurepip --upgrade >/dev/null 2>&1; then
        echo "[run_local] 错误: 无法在虚拟环境中初始化 pip（ensurepip 失败）" >&2
        echo "[run_local] 建议重装 Python（brew install python@3.12）后重试" >&2
        exit 1
    fi
fi
"${PIP_CMD[@]}" install -q -U pip

# ---------- 安装 agentscope（从同级目录的本地源码） ----------
AGENTSCOPE_DIR="$ROOT/../agentscope"
if [[ ! -d "$AGENTSCOPE_DIR" ]]; then
    echo "[run_local] 错误: 未找到 $AGENTSCOPE_DIR" >&2
    echo "[run_local] 请将 agentscope 源码放到与本项目同级的目录下" >&2
    exit 1
fi
if ! python -c "import agentscope" 2>/dev/null; then
    echo "[run_local] 安装 agentscope（本地: $AGENTSCOPE_DIR）..."
    "${PIP_CMD[@]}" install -e "$AGENTSCOPE_DIR"
fi

# ---------- 安装 agentscope-runtime ----------
AGENTSCOPE_RT_DIR="$ROOT/../agentscope-runtime"
if [[ -d "$AGENTSCOPE_RT_DIR" ]]; then
    if ! python -c "import agentscope_runtime" 2>/dev/null; then
        echo "[run_local] 安装 agentscope-runtime（本地: $AGENTSCOPE_RT_DIR）..."
        "${PIP_CMD[@]}" install -e "$AGENTSCOPE_RT_DIR"
    fi
else
    if ! python -c "import agentscope_runtime" 2>/dev/null; then
        echo "[run_local] 安装 agentscope-runtime（从 GitHub）..."
        "${PIP_CMD[@]}" install "git+https://github.com/agentscope-ai/agentscope-runtime.git@main"
    fi
fi

# ---------- 以可编辑方式安装 copaw ----------
echo "[run_local] 安装 copaw (editable) ..."
"${PIP_CMD[@]}" install -e .

# ---------- 构建前端（若 dist 不存在） ----------
CONSOLE_DIR="$ROOT/console"
if [[ -f "$CONSOLE_DIR/package.json" && ! -d "$CONSOLE_DIR/dist" ]]; then
    echo "[run_local] 构建前端 console ..."
    (cd "$CONSOLE_DIR" && npm ci && npm run build)
fi

# ---------- 若无工作区则自动初始化（生成 ~/.copaw 与 config.json 等） ----------
if ! python -c "
from pathlib import Path
from copaw.constant import WORKING_DIR
cfg = Path(WORKING_DIR) / 'config.json'
exit(0 if cfg.is_file() else 1)
" 2>/dev/null; then
    echo "[run_local] 工作区未初始化，正在执行 copaw init --defaults --accept-security ..."
    copaw init --defaults --accept-security
fi

# ---------- 启动 ----------
# 避免重复启动多个 copaw app 导致 Wechat 轮询互抢消息
if command -v pgrep >/dev/null 2>&1; then
    EXISTING_PIDS="$(pgrep -f "$ROOT/.venv/bin/copaw app" || true)"
    if [[ -n "$EXISTING_PIDS" ]]; then
        echo "[run_local] 检测到已有 copaw app 进程，准备停止后重启: $EXISTING_PIDS"
        for pid in $EXISTING_PIDS; do
            if [[ -n "$pid" && "$pid" != "$$" ]]; then
                kill "$pid" 2>/dev/null || true
            fi
        done
        sleep 1
    fi
fi

echo "[run_local] 启动 CoPaw (Console: http://127.0.0.1:8088/) ..."
exec copaw app
