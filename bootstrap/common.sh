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

#  Venv helpers

VENV_DIR="$REPO_ROOT/.venv"
VENV_ACTIVATE="$VENV_DIR/bin/activate"
REQUIREMENTS="$REPO_ROOT/requirements.txt"

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
