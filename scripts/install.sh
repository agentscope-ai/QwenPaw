#!/usr/bin/env bash
# BoostClaw Installer
# Usage: curl -fsSL <url>/install.sh | bash
#    or: bash install.sh [--version X.Y.Z] [--from-source]
#
# Installs BoostClaw into ~/.boostclaw with a uv-managed Python environment.
# Users do NOT need Python pre-installed — uv handles everything.
set -euo pipefail

# ── Colors ────────────────────────────────────────────────────────────────────
if [ -t 1 ]; then
    BOLD="\033[1m"
    GREEN="\033[0;32m"
    YELLOW="\033[0;33m"
    RED="\033[0;31m"
    RESET="\033[0m"
else
    BOLD="" GREEN="" YELLOW="" RED="" RESET=""
fi

info()  { printf "${GREEN}[boostclaw]${RESET} %s\n" "$*"; }
warn()  { printf "${YELLOW}[boostclaw]${RESET} %s\n" "$*"; }
error() { printf "${RED}[boostclaw]${RESET} %s\n" "$*" >&2; }
die()   { error "$@"; exit 1; }

# ── Defaults ──────────────────────────────────────────────────────────────────
BOOSTCLAW_HOME="${BOOSTCLAW_HOME:-${COPAW_HOME:-$HOME/.boostclaw}}"
BOOSTCLAW_VENV="$BOOSTCLAW_HOME/venv"
BOOSTCLAW_BIN="$BOOSTCLAW_HOME/bin"
PYTHON_VERSION="3.12"
BOOSTCLAW_REPO="https://github.com/aimentorai/boostclaw.git"

# New: Intelligent selection of PyPI source (automatically using Alibaba Cloud mirror for domestic users, and official source for overseas users)
choose_pypi_mirror() {
    # Test the connectivity of the official PyPI source (timeout 3 seconds, no output)
    if curl -s --connect-timeout 3 https://pypi.org/simple/ > /dev/null 2>&1; then
        echo "https://pypi.org/simple/"
        info "Using official PyPI source (network is good)" >&2
    else
        echo "https://mirrors.aliyun.com/pypi/simple/"
        info "Using Aliyun PyPI mirror (official source is unreachable)" >&2
    fi
}
PYPI_MIRROR=$(choose_pypi_mirror)

# New: Automatically clear old virtual environments and skip interactive prompts
export UV_VENV_CLEAR=1




VERSION=""
FROM_SOURCE=false
SOURCE_DIR=""
EXTRAS=""

# ── Parse args ────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --version)
            VERSION="$2"; shift 2 ;;
        --from-source)
            FROM_SOURCE=true
            # Accept optional path argument (next arg that doesn't start with --)
            if [[ $# -ge 2 && "$2" != --* ]]; then
                SOURCE_DIR="$(cd "$2" && pwd)" || die "Directory not found: $2"
                shift
            fi
            shift ;;
        --extras)
            EXTRAS="$2"; shift 2 ;;
        -h|--help)
            cat <<EOF
BoostClaw Installer

Usage: bash install.sh [OPTIONS]

Options:
  --version <VER>       Install a specific version (e.g. 0.0.2)
  --from-source [DIR]   Install from source. If DIR is given, use that local
                        directory; otherwise clone from GitHub.
  --extras <EXTRAS>     Comma-separated optional extras to install
                        (e.g. llamacpp, mlx, llamacpp,mlx)
  -h, --help            Show this help

Environment:
  BOOSTCLAW_HOME    Installation directory (default: ~/.boostclaw)
  COPAW_HOME        Legacy alias for BOOSTCLAW_HOME
EOF
            exit 0 ;;
        *)
            die "Unknown option: $1 (try --help)" ;;
    esac
done

# ── OS check ──────────────────────────────────────────────────────────────────
OS="$(uname -s)"
case "$OS" in
    Linux|Darwin) ;;
    *) die "Unsupported OS: $OS. This installer supports Linux and macOS only." ;;
esac

printf "${GREEN}[boostclaw]${RESET} Installing BoostClaw into ${BOLD}%s${RESET}\n" "$BOOSTCLAW_HOME"

# ── Step 1: Ensure uv is available ───────────────────────────────────────────
ensure_uv() {
    if command -v uv &>/dev/null; then
        info "uv found: $(command -v uv)"
        return
    fi

    # Check common install locations not yet on PATH
    for candidate in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
        if [ -x "$candidate" ]; then
            export PATH="$(dirname "$candidate"):$PATH"
            info "uv found: $candidate"
            return
        fi
    done

    info "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh

    # Source the env file uv's installer creates, or add common paths
    if [ -f "$HOME/.local/bin/env" ]; then
        # shellcheck disable=SC1091
        . "$HOME/.local/bin/env"
    fi
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

    command -v uv &>/dev/null || die "Failed to install uv. Please install it manually: https://docs.astral.sh/uv/"
    info "uv installed successfully"
}

ensure_uv

# ── Step 2: Create / update virtual environment ──────────────────────────────
if [ -d "$BOOSTCLAW_VENV" ]; then
    info "Existing environment found, upgrading..."
else
    info "Creating Python $PYTHON_VERSION environment..."
fi

uv venv "$BOOSTCLAW_VENV" --python "$PYTHON_VERSION" --quiet

# Verify the venv was created
[ -x "$BOOSTCLAW_VENV/bin/python" ] || die "Failed to create virtual environment"
info "Python environment ready ($("$BOOSTCLAW_VENV/bin/python" --version))"

# ── Step 3: Install BoostClaw ────────────────────────────────────────────────
# Build extras suffix: "" or "[llamacpp,mlx]"
EXTRAS_SUFFIX=""
if [ -n "$EXTRAS" ]; then
    EXTRAS_SUFFIX="[$EXTRAS]"
fi

## Ensure console frontend assets are in src/copaw/console/ for source installs.
## Sets _CONSOLE_COPIED=1 if we populated the directory (so we can clean up).
_CONSOLE_COPIED=0
_CONSOLE_AVAILABLE=0

console_bundle_needs_refresh() {
    local console_src="$1"
    local console_dest="$2"

    if [ ! -f "$console_dest/index.html" ]; then
        return 0
    fi

    if [ ! -f "$console_src/index.html" ]; then
        return 1
    fi

    if ! cmp -s "$console_src/index.html" "$console_dest/index.html"; then
        return 0
    fi

    return 1
}

prepare_console() {
    local repo_dir="$1"
    local console_src="$repo_dir/console/dist"
    local console_dest="$repo_dir/src/copaw/console"
    local dest_had_index=0

    if [ -f "$console_dest/index.html" ]; then
        dest_had_index=1
    fi

    # Copy pre-built assets if available (e.g. developer already ran npm build).
    # Refresh stale bundled assets instead of blindly trusting an existing copy.
    if [ -d "$console_src" ] && [ -f "$console_src/index.html" ]; then
        if console_bundle_needs_refresh "$console_src" "$console_dest"; then
            info "Refreshing console frontend assets from console/dist..."
            mkdir -p "$console_dest"
            rm -rf "$console_dest/"*
            cp -R "$console_src/"* "$console_dest/"
            if [ "$dest_had_index" = 0 ]; then
                _CONSOLE_COPIED=1
            fi
        fi
        _CONSOLE_AVAILABLE=1
        return
    fi

    # Already populated (no dist build available, so keep the bundled copy).
    if [ -f "$console_dest/index.html" ]; then
        _CONSOLE_AVAILABLE=1
        return
    fi

    # Try to build if npm is available
    if [ ! -f "$repo_dir/console/package.json" ]; then
        warn "Console source not found — the web UI won't be available."
        return
    fi

    if ! command -v npm &>/dev/null; then
        warn "npm not found — skipping console frontend build."
        warn "Install Node.js from https://nodejs.org/ then re-run this installer,"
        warn "or run 'cd console && npm ci && npm run build' manually."
        return
    fi

    info "Building console frontend (npm ci && npm run build)..."
    (cd "$repo_dir/console" && npm ci && npm run build)
    if [ -f "$console_src/index.html" ]; then
        mkdir -p "$console_dest"
        if [ "$dest_had_index" = 0 ]; then
            rm -rf "$console_dest/"*
            cp -R "$console_src/"* "$console_dest/"
            _CONSOLE_COPIED=1
        fi
        _CONSOLE_AVAILABLE=1
        info "Console frontend built successfully"
        return
    fi

    warn "Console build completed but index.html not found — the web UI won't be available."
}

## Remove console assets we copied into the source tree.
cleanup_console() {
    local repo_dir="$1"
    if [ "$_CONSOLE_COPIED" = 1 ]; then
        rm -rf "$repo_dir/src/copaw/console/"*
    fi
}

if [ "$FROM_SOURCE" = true ]; then
    if [ -n "$SOURCE_DIR" ]; then
        info "Installing boostclaw from local source: $SOURCE_DIR"
        prepare_console "$SOURCE_DIR"
        info "Installing package from source..."
        uv pip install "${SOURCE_DIR}${EXTRAS_SUFFIX}" --python "$BOOSTCLAW_VENV/bin/python" --prerelease=allow --index-url "$PYPI_MIRROR"
        cleanup_console "$SOURCE_DIR"
    else
        info "Installing boostclaw from source (GitHub)..."
        CLONE_DIR="$(mktemp -d)"
        trap 'rm -rf "$CLONE_DIR"' EXIT
        git clone --depth 1 "$BOOSTCLAW_REPO" "$CLONE_DIR"
        prepare_console "$CLONE_DIR"
        info "Installing package from source..."
        uv pip install "${CLONE_DIR}${EXTRAS_SUFFIX}" --python "$BOOSTCLAW_VENV/bin/python" --prerelease=allow --index-url "$PYPI_MIRROR"
        # CLONE_DIR is cleaned up by trap; no need for cleanup_console
    fi
else
    PACKAGE="boostclaw"
    if [ -n "$VERSION" ]; then
        PACKAGE="boostclaw==$VERSION"
    fi

    info "Installing ${PACKAGE}${EXTRAS_SUFFIX} from PyPI..."
    if ! uv pip install "${PACKAGE}${EXTRAS_SUFFIX}" --python "$BOOSTCLAW_VENV/bin/python" --prerelease=allow --index-url "$PYPI_MIRROR"; then
        warn "PyPI install failed for ${PACKAGE}${EXTRAS_SUFFIX}."
        warn "Falling back to source install from GitHub..."

        command -v git &>/dev/null || die "git is required for source fallback. Please install git, or run with --from-source <DIR>."

        CLONE_DIR="$(mktemp -d)"
        info "Cloning source: $BOOSTCLAW_REPO"
        git clone --depth 1 "$BOOSTCLAW_REPO" "$CLONE_DIR" || die "Failed to clone repository"

        prepare_console "$CLONE_DIR"
        info "Installing package from source (fallback)..."
        uv pip install "${CLONE_DIR}${EXTRAS_SUFFIX}" --python "$BOOSTCLAW_VENV/bin/python" --prerelease=allow --index-url "$PYPI_MIRROR" || die "Fallback source installation failed"

        rm -rf "$CLONE_DIR"
    fi
fi

# Verify the CLI entry point exists
[ -x "$BOOSTCLAW_VENV/bin/boostclaw" ] || die "Installation failed: boostclaw CLI not found in venv"
info "BoostClaw installed successfully"

# Check console availability (for PyPI installs, check the installed package)
if [ "$_CONSOLE_AVAILABLE" = 0 ]; then
    # Check if console assets were included in the installed package
    CONSOLE_CHECK="$("$BOOSTCLAW_VENV/bin/python" -c "import importlib.resources, copaw; p=importlib.resources.files('copaw')/'console'/'index.html'; print('yes' if p.is_file() else 'no')" 2>/dev/null || echo 'no')"
    if [ "$CONSOLE_CHECK" = "yes" ]; then
        _CONSOLE_AVAILABLE=1
    fi
fi

# ── Step 4: Create wrapper script ────────────────────────────────────────────
mkdir -p "$BOOSTCLAW_BIN"

cat > "$BOOSTCLAW_BIN/boostclaw" << 'WRAPPER'
#!/usr/bin/env bash
# BoostClaw CLI wrapper — delegates to the uv-managed environment.
set -euo pipefail

BOOSTCLAW_HOME="${BOOSTCLAW_HOME:-${COPAW_HOME:-$HOME/.boostclaw}}"
REAL_BIN="$BOOSTCLAW_HOME/venv/bin/boostclaw"

if [ ! -x "$REAL_BIN" ]; then
    echo "Error: BoostClaw environment not found at $BOOSTCLAW_HOME/venv" >&2
    echo "Please reinstall: curl -fsSL <install-url> | bash" >&2
    exit 1
fi

exec "$REAL_BIN" "$@"
WRAPPER

chmod +x "$BOOSTCLAW_BIN/boostclaw"
info "Wrapper created at $BOOSTCLAW_BIN/boostclaw"

# ── Step 5: Update PATH in shell profile ─────────────────────────────────────
PATH_ENTRY="export PATH=\"\$HOME/.boostclaw/bin:\$PATH\""

add_to_profile() {
    local profile="$1"
    if [ -f "$profile" ] && grep -qF '.boostclaw/bin' "$profile"; then
        return 0  # already present
    fi
    if [ -f "$profile" ] || [ "$2" = "create" ]; then
        printf '\n# boostclaw\n%s\n' "$PATH_ENTRY" >> "$profile"
        info "Updated $profile"
        return 0
    fi
    return 1
}

UPDATED_PROFILE=false

case "$OS" in
    Darwin)
        add_to_profile "$HOME/.zshrc" "create" && UPDATED_PROFILE=true
        # Also update bash profile if it exists
        add_to_profile "$HOME/.bash_profile" "no-create" || true
        ;;
    Linux)
        add_to_profile "$HOME/.bashrc" "create" && UPDATED_PROFILE=true
        # Also update zshrc if it exists
        add_to_profile "$HOME/.zshrc" "no-create" || true
        ;;
esac

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
printf "${GREEN}${BOLD}boostclaw installed successfully!${RESET}\n"
echo ""

# Install summary
printf "  Install location:  ${BOLD}%s${RESET}\n" "$BOOSTCLAW_HOME"
printf "  Python:            ${BOLD}%s${RESET}\n" "$("$BOOSTCLAW_VENV/bin/python" --version 2>&1)"
if [ "$_CONSOLE_AVAILABLE" = 1 ]; then
    printf "  Console (web UI):  ${GREEN}available${RESET}\n"
else
    printf "  Console (web UI):  ${YELLOW}not available${RESET}\n"
    echo "                     Install Node.js and re-run to enable the web UI."
fi
echo ""

if [ "$UPDATED_PROFILE" = true ]; then
    echo "To get started, open a new terminal or run:"
    echo ""
    printf "  ${BOLD}source ~/.zshrc${RESET}  # or ~/.bashrc\n"
    echo ""
fi

echo "Then run:"
echo ""
printf "  ${BOLD}boostclaw init${RESET}   # first-time setup\n"
printf "  ${BOLD}boostclaw app${RESET}    # start BoostClaw\n"
echo ""
printf "To upgrade later, re-run this installer.\n"
printf "To uninstall, run: ${BOLD}boostclaw uninstall${RESET}\n"
