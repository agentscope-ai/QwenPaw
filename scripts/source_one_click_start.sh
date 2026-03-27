#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
CONSOLE_DIR="$ROOT_DIR/console"
CONSOLE_DEST="$ROOT_DIR/src/copaw/console"
HOST="0.0.0.0"
PORT="8088"
EXTRAS="dev"
SKIP_PULL=0
AUTO_STOP=1
STOP_WAIT_SECONDS=20
INSTALL_SHORTCUT=1
VENV_PYTHON=""

usage() {
    cat <<'EOF'
One-click source startup for CoPaw.

What it does:
1) git pull (ff-only)
2) create/activate .venv
3) install Python deps (editable mode)
4) build console frontend and copy dist assets
5) start CoPaw on 0.0.0.0

Usage:
  bash scripts/source_one_click_start.sh [options]

Options:
  --host <HOST>       Bind host (default: 0.0.0.0)
  --port <PORT>       Bind port (default: 8088)
  --extras <LIST>     Editable install extras (default: dev)
  --skip-pull         Skip git pull step
    --no-stop           Do not stop existing process on target port
    --stop-wait <SEC>   Graceful stop wait seconds before SIGKILL (default: 20)
    --no-shortcut       Do not install/update shortcut commands
  -h, --help          Show this help message

Example:
  bash scripts/source_one_click_start.sh --port 3000
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --host)
            HOST="$2"
            shift 2
            ;;
        --port)
            PORT="$2"
            shift 2
            ;;
        --extras)
            EXTRAS="$2"
            shift 2
            ;;
        --skip-pull)
            SKIP_PULL=1
            shift
            ;;
        --no-stop)
            AUTO_STOP=0
            shift
            ;;
        --stop-wait)
            STOP_WAIT_SECONDS="$2"
            shift 2
            ;;
        --no-shortcut)
            INSTALL_SHORTCUT=0
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

log() {
    printf '[source-start] %s\n' "$1"
}

ensure_cmd() {
    local cmd="$1"
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "Missing required command: $cmd" >&2
        exit 1
    fi
}

ensure_python() {
    if command -v python3 >/dev/null 2>&1; then
        printf '%s\n' "$(command -v python3)"
        return 0
    fi
    if command -v python >/dev/null 2>&1; then
        printf '%s\n' "$(command -v python)"
        return 0
    fi
    echo "Python is not available in PATH (need python3 or python)." >&2
    exit 1
}

prepare_git() {
    if [[ $SKIP_PULL -eq 1 ]]; then
        log "Skipping git pull (--skip-pull)."
        return 0
    fi

    ensure_cmd git
    log "Fetching remote updates..."
    git -C "$ROOT_DIR" fetch --all --prune

    local branch
    branch="$(git -C "$ROOT_DIR" rev-parse --abbrev-ref HEAD)"
    log "Pulling latest changes for branch: $branch"
    git -C "$ROOT_DIR" pull --ff-only
}

collect_running_pids_on_port() {
    local pids=()
    local raw=""

    if command -v lsof >/dev/null 2>&1; then
        raw="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
        if [[ -n "$raw" ]]; then
            while IFS= read -r pid; do
                [[ -n "$pid" ]] && pids+=("$pid")
            done <<< "$raw"
        fi
    fi

    if command -v pgrep >/dev/null 2>&1; then
        raw="$(pgrep -f "copaw app.*(--port[ =]$PORT|:[[:space:]]*$PORT)" 2>/dev/null || true)"
        if [[ -n "$raw" ]]; then
            while IFS= read -r pid; do
                [[ -n "$pid" ]] && pids+=("$pid")
            done <<< "$raw"
        fi
    fi

    if [[ ${#pids[@]} -eq 0 ]]; then
        return 0
    fi

    # De-duplicate while filtering out current shell lineage.
    local uniq=()
    local seen=":"
    local pid=""
    for pid in "${pids[@]}"; do
        [[ "$pid" == "$$" || "$pid" == "$PPID" ]] && continue
        if [[ "$seen" != *":$pid:"* ]]; then
            uniq+=("$pid")
            seen+="$pid:"
        fi
    done

    printf '%s\n' "${uniq[@]}"
}

stop_running_processes() {
    if [[ "$AUTO_STOP" -ne 1 ]]; then
        log "Auto-stop disabled (--no-stop)."
        return 0
    fi

    if ! [[ "$STOP_WAIT_SECONDS" =~ ^[0-9]+$ ]]; then
        echo "Invalid --stop-wait value: $STOP_WAIT_SECONDS (expect integer seconds)" >&2
        exit 1
    fi

    local pids=()
    local pid=""
    while IFS= read -r pid; do
        [[ -n "$pid" ]] && pids+=("$pid")
    done < <(collect_running_pids_on_port)

    if [[ ${#pids[@]} -eq 0 ]]; then
        log "No running process detected on port $PORT."
        return 0
    fi

    log "Detected existing process(es) on port $PORT: ${pids[*]}"
    log "Sending SIGTERM for graceful shutdown..."
    kill -TERM "${pids[@]}" 2>/dev/null || true

    local deadline=$((SECONDS + STOP_WAIT_SECONDS))
    while [[ $SECONDS -lt $deadline ]]; do
        local alive=0
        for pid in "${pids[@]}"; do
            if kill -0 "$pid" 2>/dev/null; then
                alive=1
                break
            fi
        done
        if [[ $alive -eq 0 ]]; then
            log "Existing process(es) stopped gracefully."
            return 0
        fi
        sleep 1
    done

    log "Graceful stop timed out after ${STOP_WAIT_SECONDS}s, sending SIGKILL..."
    kill -KILL "${pids[@]}" 2>/dev/null || true
    sleep 1
}

append_once() {
    local file_path="$1"
    local line="$2"
    if [[ ! -f "$file_path" ]]; then
        printf '%s\n' "$line" > "$file_path"
        return 0
    fi
    if ! grep -Fqx "$line" "$file_path"; then
        printf '\n%s\n' "$line" >> "$file_path"
    fi
}

install_shortcut_commands() {
    if [[ "$INSTALL_SHORTCUT" -ne 1 ]]; then
        log "Shortcut injection disabled (--no-shortcut)."
        return 0
    fi

    local local_bin="$HOME/.local/bin"
    local shortcut_cmd="$local_bin/copaw-rebuild"
    local copaw_shell_dir="$HOME/.config/copaw/shell"
    local bridge_file="$copaw_shell_dir/rebuild.shortcut.sh"
    local current_shell="$(basename "${SHELL:-}")"
    local rc_file=""

    mkdir -p "$local_bin"
    mkdir -p "$copaw_shell_dir"

    cat > "$shortcut_cmd" <<EOF
#!/usr/bin/env bash
set -euo pipefail
exec bash "$ROOT_DIR/scripts/source_one_click_start.sh" "\$@"
EOF
    chmod +x "$shortcut_cmd"
    log "Installed shortcut command: $shortcut_cmd"

    cat > "$bridge_file" <<EOF
#!/usr/bin/env bash
# Auto-generated by source_one_click_start.sh. Do not edit manually.
copaw() {
  if [[ "\${1:-}" == "rebuild" ]]; then
    shift
    bash "$ROOT_DIR/scripts/source_one_click_start.sh" "\$@"
    return \$?
  fi
  command copaw "\$@"
}
EOF
    chmod 644 "$bridge_file"

    case "$current_shell" in
        zsh)
            rc_file="$HOME/.zshrc"
            ;;
        bash)
            rc_file="$HOME/.bashrc"
            ;;
        *)
            rc_file="$HOME/.zshrc"
            ;;
    esac

    append_once "$rc_file" "source \"$bridge_file\""

    if [[ ":$PATH:" != *":$local_bin:"* ]]; then
        append_once "$rc_file" "export PATH=\"$local_bin:\$PATH\""
        log "Appended $local_bin to PATH in $rc_file"
    fi

    log "Shortcut ready: copaw-rebuild"
    log "Shell bridge installed: use 'copaw rebuild' after reloading shell"
    log "Apply now in current terminal: source $rc_file"
}

prepare_venv() {
    local python_bin
    python_bin="$(ensure_python)"

    if [[ ! -x "$VENV_DIR/bin/python" ]]; then
        log "Creating virtual environment at $VENV_DIR"
        "$python_bin" -m venv "$VENV_DIR"
    else
        log "Using existing virtual environment: $VENV_DIR"
    fi

    VENV_PYTHON="$VENV_DIR/bin/python"
    if [[ ! -x "$VENV_PYTHON" ]]; then
        echo "Virtual environment python is missing: $VENV_PYTHON" >&2
        echo "Try removing .venv and rerun this script." >&2
        exit 1
    fi

    if [[ -f "$VENV_DIR/bin/activate" ]]; then
        # shellcheck source=/dev/null
        source "$VENV_DIR/bin/activate"
    else
        log "activate script not found, using $VENV_PYTHON directly."
    fi

    # Some broken/minimal venvs miss pip. Try to self-heal before install.
    if ! "$VENV_PYTHON" -m pip --version >/dev/null 2>&1; then
        log "pip is missing in venv, attempting bootstrap via ensurepip..."
        if ! "$VENV_PYTHON" -m ensurepip --upgrade >/dev/null 2>&1; then
            echo "Failed to bootstrap pip in $VENV_DIR." >&2
            echo "Please remove .venv and rerun this script." >&2
            echo "Command: rm -rf .venv" >&2
            exit 1
        fi
    fi

    if ! "$VENV_PYTHON" -m pip --version >/dev/null 2>&1; then
        echo "pip is still unavailable in $VENV_DIR after ensurepip." >&2
        echo "Please remove .venv and rerun this script." >&2
        echo "Command: rm -rf .venv" >&2
        exit 1
    fi

    log "Upgrading pip/setuptools/wheel"
    "$VENV_PYTHON" -m pip install -U pip setuptools wheel

    log "Installing CoPaw in editable mode with extras: [$EXTRAS]"
    "$VENV_PYTHON" -m pip install -e ".[${EXTRAS}]"
}

build_console() {
    ensure_cmd npm

    if [[ ! -f "$CONSOLE_DIR/package.json" ]]; then
        echo "console/package.json not found under $CONSOLE_DIR" >&2
        exit 1
    fi

    log "Installing frontend dependencies (npm ci)..."
    (cd "$CONSOLE_DIR" && npm ci)

    log "Building frontend (npm run build)..."
    (cd "$CONSOLE_DIR" && npm run build)

    if [[ ! -f "$CONSOLE_DIR/dist/index.html" ]]; then
        echo "Frontend build output missing: $CONSOLE_DIR/dist/index.html" >&2
        exit 1
    fi

    log "Copying console/dist assets to src/copaw/console"
    mkdir -p "$CONSOLE_DEST"
    rm -rf "$CONSOLE_DEST"/*
    cp -R "$CONSOLE_DIR/dist/"* "$CONSOLE_DEST/"
}

start_app() {
    log "Starting CoPaw on ${HOST}:${PORT}"
    if [[ -n "$VENV_PYTHON" && -x "$VENV_PYTHON" ]]; then
        exec "$VENV_PYTHON" -m copaw app --host "$HOST" --port "$PORT"
    fi
    exec copaw app --host "$HOST" --port "$PORT"
}

main() {
    log "Repository root: $ROOT_DIR"
    stop_running_processes
    prepare_git
    prepare_venv
    build_console
    install_shortcut_commands
    start_app
}

main
