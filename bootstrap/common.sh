#!/bin/bash
# bootstrap/common.sh -- Shared helpers for bootstrap scripts.
#
# Sourced by other bootstrap scripts. Do not run directly.

set -euo pipefail

#  Repo root 

# Resolve the repository root (parent of bootstrap/).
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

#  Environment detection 

is_wsl() {
    grep -qEi "(Microsoft|WSL)" /proc/version 2>/dev/null
}

is_linux() {
    [[ "$(uname -s)" == "Linux" ]]
}

#  Logging helpers 

info()  { echo "[INFO] $*"; }
ok()    { echo "[OK] $*"; }
warn()  { echo "[WARN] $*"; }
err()   { echo "[ERROR] $*"; }

# Print a fatal error and exit.
die() {
    err "$@"
    exit 1
}

#  Interactive helpers 

# Prompt the user with a yes/cancel question.
# Returns 0 if the user confirms, 1 otherwise.
# Usage: confirm "Do you want to continue?" || exit 0
confirm() {
    local prompt="${1:-Continue?}"
    echo ""
    echo "$prompt"
    echo ""
    while true; do
        read -r -p "  [yes/cancel] " answer
        case "$answer" in
            yes|YES|y|Y) return 0 ;;
            cancel|CANCEL|no|NO|n|N) return 1 ;;
            *) echo "  Please type 'yes' or 'cancel'." ;;
        esac
    done
}

#  Package helpers

# Check if a dependency spec is satisfied.
# A spec is a single package name or alternatives separated by "|".
# Example: "libglib2.0-0|libglib2.0-0t64"
# Returns 0 if any alternative is installed, 1 if none are.
is_pkg_installed() {
    local spec="$1"
    local IFS='|'
    for pkg in $spec; do
        if dpkg -s "$pkg" &>/dev/null; then
            return 0
        fi
    done
    return 1
}

# Get the first package name from a dependency spec for display/install.
# "libglib2.0-0|libglib2.0-0t64" -> "libglib2.0-0"
pkg_install_name() {
    echo "${1%%|*}"
}

#  Paths

VENV_DIR="$REPO_ROOT/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"
VENV_ACTIVATE="$VENV_DIR/bin/activate"
REQUIREMENTS="$REPO_ROOT/requirements.txt"

DEV_DIR="$REPO_ROOT/.dev"
HISTORY_DIRS=(".ignitionraw" ".ignitionrawbak" "ignitionhistory")

GATEWAY_PID_FILE="$DEV_DIR/gateway.pid"
BACKEND_PID_FILE="$DEV_DIR/backend.pid"
APPLICATION_PID_FILE="$REPO_ROOT/.applicationpid"

GATEWAY_SOCKET="$REPO_ROOT/.gateway_service.sock"
BACKEND_SOCKET="$REPO_ROOT/.backend_service.sock"
SHUTDOWN_SIGNAL="$REPO_ROOT/.shutdown_signal"

LOCAL_DEV_FILES=(".guiworkspace.json")
LOCAL_DEV_DIRS=(".guimetadata")

#  Venv helpers

venv_exists() {
    [[ -d "$VENV_DIR" && -f "$VENV_ACTIVATE" ]]
}

require_venv() {
    if ! venv_exists; then
        die "Virtual environment not found. Run 'make setup' first."
    fi
}

activate_venv() {
    require_venv
    # shellcheck disable=SC1090
    source "$VENV_ACTIVATE"
}

#  Directory helpers

ensure_dev_dir() {
    mkdir -p "$DEV_DIR"
}

ensure_history_dirs() {
    for d in "${HISTORY_DIRS[@]}"; do
        mkdir -p "$REPO_ROOT/$d"
        touch "$REPO_ROOT/$d/.gitkeep"
    done
}

#  Process helpers

pid_is_alive() {
    [[ -n "${1:-}" ]] && kill -0 "$1" 2>/dev/null
}

# Stop a process given its pid file. SIGTERM, wait, SIGKILL if needed.
# Returns 0 if a process was stopped, 1 if nothing was running.
stop_pid_file() {
    local pid_file="$1"
    local label="${2:-process}"
    [[ -f "$pid_file" ]] || return 1
    local pid
    pid=$(cat "$pid_file" 2>/dev/null || true)
    if pid_is_alive "$pid"; then
        info "Stopping $label pid=$pid"
        kill "$pid" 2>/dev/null || true
        sleep 1
        if pid_is_alive "$pid"; then
            warn "Force killing $label pid=$pid"
            kill -9 "$pid" 2>/dev/null || true
        fi
        return 0
    else
        info "$label pid file exists but process is not alive"
        return 1
    fi
}

# Remove all runtime artifacts (pid files, sockets, signals).
clean_runtime_files() {
    rm -f "$GATEWAY_PID_FILE" "$GATEWAY_SOCKET"
    rm -f "$BACKEND_PID_FILE" "$BACKEND_SOCKET"
    rm -f "$APPLICATION_PID_FILE" "$SHUTDOWN_SIGNAL"
}

#  Confirmation helpers

# Require confirmation for destructive operations.
# Skipped if MINTS_FORCE=1 is set in the environment.
# Usage: require_confirm "This will delete all history data."
require_confirm() {
    local message="$1"
    if [[ "${MINTS_FORCE:-}" == "1" ]]; then
        return 0
    fi
    confirm "$message" || { info "Cancelled."; exit 2; }
}
