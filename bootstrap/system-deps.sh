#!/bin/bash
# bootstrap/system-deps.sh -- Check and install OS-level dependencies.
#
# Called by bootstrap/setup.sh. Can also be run standalone.
# Prompts before installing anything.

set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

#  Dependency lists 
#
# Edit these arrays to add or remove system packages.
# The checking/install logic below uses these lists automatically.

# Required on all Linux systems for PyQt5 and the application to run.
SYSTEM_DEPS_REQUIRED=(
    python3-venv        # Python venv module (sometimes missing on Ubuntu/Debian)
    libxcb-xinerama0    # Qt5 platform plugin dependency
    libxcb-cursor0      # Qt5 xcb cursor support
    libgl1                      # OpenGL for Qt rendering
    "libglib2.0-0|libglib2.0-0t64"  # GLib (Qt dependency; t64 rename on newer Ubuntu)
    libegl1                     # EGL for Qt WebEngine
    libxkbcommon0       # Keyboard handling for Qt
)

# Recommended but not strictly required.
SYSTEM_DEPS_RECOMMENDED=(
    git                 # Version control
    make                # Build system
)

# WSL-only packages (installed by wsl-usb.sh, checked here for visibility).
WSL_SYSTEM_DEPS=(
    usbutils            # lsusb
    linux-tools-generic # usbip client
    hwdata              # USB device database
)

#  Dependency checking 

# Check which dependency specs from a list are not satisfied.
# Each spec can be "pkg" or "pkg1|pkg2" (any-of alternatives).
# Prints unsatisfied specs, one per line.
# Returns 0 if all satisfied, 1 if any missing.
check_missing_packages() {
    local missing=()
    for spec in "$@"; do
        if ! is_pkg_installed "$spec"; then
            missing+=("$spec")
        fi
    done
    if [[ ${#missing[@]} -eq 0 ]]; then
        return 0
    fi
    printf '%s\n' "${missing[@]}"
    return 1
}

#  Main 

main() {
    echo "=== System Dependency Check ==="
    echo ""

    if ! is_linux; then
        die "This script requires Linux (or WSL). Detected: $(uname -s)"
    fi

    # Check required packages.
    local missing_required=()
    while IFS= read -r pkg; do
        missing_required+=("$pkg")
    done < <(check_missing_packages "${SYSTEM_DEPS_REQUIRED[@]}" || true)

    # Check recommended packages.
    local missing_recommended=()
    while IFS= read -r pkg; do
        missing_recommended+=("$pkg")
    done < <(check_missing_packages "${SYSTEM_DEPS_RECOMMENDED[@]}" || true)

    # Report results.
    if [[ ${#missing_required[@]} -eq 0 && ${#missing_recommended[@]} -eq 0 ]]; then
        ok "All system dependencies are installed."
        echo ""
        return 0
    fi

    # Show what is missing.
    if [[ ${#missing_required[@]} -gt 0 ]]; then
        echo "Missing required packages:"
        for spec in "${missing_required[@]}"; do
            echo "  - $(pkg_install_name "$spec")"
        done
        echo ""
    fi

    if [[ ${#missing_recommended[@]} -gt 0 ]]; then
        echo "Missing recommended packages:"
        for spec in "${missing_recommended[@]}"; do
            echo "  - $(pkg_install_name "$spec")"
        done
        echo ""
    fi

    # Build the combined install list (resolve specs to installable names).
    local to_install=()
    for spec in "${missing_required[@]}" "${missing_recommended[@]}"; do
        to_install+=("$(pkg_install_name "$spec")")
    done

    echo "The following packages will be installed on this computer:"
    for pkg in "${to_install[@]}"; do
        echo "  - $pkg"
    done

    # Non-interactive mode: skip confirmation if --yes is passed.
    if [[ "${1:-}" == "--yes" ]]; then
        info "Non-interactive mode (--yes): proceeding with installation."
    else
        if ! confirm "Install these packages? (requires sudo)"; then
            info "Installation cancelled. You can install them manually later."
            echo ""
            echo "Required packages:"
            echo "  sudo apt-get install -y ${to_install[*]}"
            echo ""
            exit 0
        fi
    fi

    # Install.
    echo ""
    info "Updating package lists..."
    sudo apt-get update -qq

    info "Installing packages..."
    sudo apt-get install -y "${to_install[@]}"

    echo ""
    ok "System dependencies installed."
    echo ""
}

main "$@"
