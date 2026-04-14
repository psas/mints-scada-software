#!/bin/bash
# bootstrap/python-env.sh -- Create or update the Python virtual environment.
#
# Called by bootstrap/setup.sh. Can also be run standalone.

set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

PYTHON="${PYTHON:-python3}"

main() {
    echo "=== Python Environment Setup ==="
    echo ""

    # Verify Python is available and meets minimum version.
    if ! command -v "$PYTHON" &>/dev/null; then
        die "'$PYTHON' not found. Install Python 3.12 and try again."
    fi

    local py_version
    py_version=$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    info "Found $PYTHON $py_version"

    if [[ "$py_version" != "3.12" ]]; then
        warn "This project targets Python 3.12. You have $py_version."
        warn "Things may not work correctly."
    fi

    # Create or reuse virtual environment.
    if venv_exists; then
        info "Virtual environment already exists at $VENV_DIR"
    else
        info "Creating virtual environment at $VENV_DIR ..."
        "$PYTHON" -m venv "$VENV_DIR"
        ok "Virtual environment created."
    fi

    # Activate and install dependencies.
    # shellcheck disable=SC1090
    source "$VENV_ACTIVATE"

    info "Installing Python dependencies from $REQUIREMENTS ..."
    pip install -r "$REQUIREMENTS"

    echo ""

    # Quick import smoke test.
    info "Running import check..."
    local failed=0
    for mod in serial can numpy PyQt5 matplotlib qdarkstyle; do
        if python -c "import $mod" 2>/dev/null; then
            echo "  [OK] $mod"
        else
            echo "  [FAIL] $mod"
            failed=1
        fi
    done

    echo ""
    if [[ $failed -eq 1 ]]; then
        warn "Some imports failed. The application may not run correctly."
        warn "Check the pip install output above for errors."
    else
        ok "All Python dependencies verified."
    fi

    echo ""
    ok "Python environment setup complete."
    echo ""
}

main "$@"
