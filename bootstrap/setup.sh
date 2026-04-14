#!/bin/bash
# bootstrap/setup.sh -- Main setup entry point.
#
# Orchestrates system dependency checks and Python environment setup.
# This is the implementation behind `make setup`.

set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

BOOTSTRAP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

main() {
    echo "========================================="
    echo "  MINTS SCADA Software -- Setup"
    echo "========================================="
    echo ""

    if ! is_linux; then
        die "This project requires Linux (or WSL). Detected: $(uname -s)"
    fi

    # Step 1: System dependencies.
    info "Checking system dependencies..."
    echo ""
    bash "$BOOTSTRAP_DIR/system-deps.sh" "$@"

    # Step 2: Python environment.
    bash "$BOOTSTRAP_DIR/python-env.sh"

    # Step 3: WSL hint.
    if is_wsl; then
        echo "=== WSL USB Setup (Optional) ==="
        echo ""
        echo "Detected WSL environment."
        echo "Run 'make wsl-usb' if you need to forward a USB device from Windows to WSL."
    else
        echo "Detected native Linux -- USB devices should be available directly."
        echo "No USB forwarding needed."
        echo "Make sure you connected the COM switch to your computer."
    fi

    echo ""
    ok "Setup complete!"
    echo "To run: make run"
    echo ""
}

main "$@"
