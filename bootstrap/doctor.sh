#!/bin/bash
# bootstrap/doctor.sh -- Environment diagnostics.
#
# Checks that everything needed to run the application is in place.
# Does not install or modify anything.

set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

PYTHON="${PYTHON:-python3}"
passed=0
warned=0
failed=0

check_pass() { echo "  [OK]   $*"; ((passed++)) || true; }
check_warn() { echo "  [WARN] $*"; ((warned++)) || true; }
check_fail() { echo "  [FAIL] $*"; ((failed++)) || true; }

#  System checks 

main() {
    echo "=== MINTS SCADA Doctor ==="
    echo ""
    echo "--- Platform ---"

    if is_linux; then
        check_pass "Linux detected"
    else
        check_fail "Not running on Linux (detected: $(uname -s))"
    fi

    if is_wsl; then
        check_pass "WSL detected"
    else
        echo "  [--]   Not WSL (native Linux assumed)"
    fi

    echo ""
    echo "--- Python ---"

    if command -v "$PYTHON" &>/dev/null; then
        local py_version
        py_version=$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        if [[ "$py_version" == "3.12" ]]; then
            check_pass "Python $py_version"
        else
            check_warn "Python $py_version (project targets 3.12)"
        fi
    else
        check_fail "python3 not found"
    fi

    echo ""
    echo "--- Virtual Environment ---"

    if venv_exists; then
        check_pass ".venv exists"

        # Check pip and key imports inside venv.
        local venv_python="$VENV_DIR/bin/python"
        if [[ -x "$venv_python" ]]; then
            for mod in serial can numpy PyQt5 PyQt5.QtWebEngineWidgets matplotlib qdarkstyle; do
                if "$venv_python" -c "import $mod" 2>/dev/null; then
                    check_pass "import $mod"
                else
                    check_fail "import $mod"
                fi
            done
        fi
    else
        check_fail ".venv not found (run 'make setup')"
    fi

    echo ""
    echo "--- System Libraries ---"

    local sys_deps=(
        libxcb-xinerama0
        libxcb-cursor0
        libgl1
        "libglib2.0-0|libglib2.0-0t64"
        libegl1
        libxkbcommon0
    )
    for spec in "${sys_deps[@]}"; do
        local label
        label="$(pkg_install_name "$spec")"
        if is_pkg_installed "$spec"; then
            check_pass "$label"
        else
            check_warn "$label not installed"
        fi
    done

    echo ""
    echo "--- Serial Ports ---"

    local ports
    ports=$(ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null || true)
    if [[ -n "$ports" ]]; then
        check_pass "Serial port(s) detected: $ports"
    else
        check_warn "No serial ports detected (not needed for playback mode)"
    fi

    if is_wsl; then
        echo ""
        echo "--- WSL USB Tools ---"
        local wsl_deps=(usbutils linux-tools-generic hwdata)
        for pkg in "${wsl_deps[@]}"; do
            if dpkg -s "$pkg" &>/dev/null; then
                check_pass "$pkg"
            else
                check_warn "$pkg not installed (run 'make wsl-usb' if USB forwarding is needed)"
            fi
        done
    fi

    # Summary.
    echo ""
    echo "--- Summary ---"
    echo "  Passed: $passed  Warnings: $warned  Failed: $failed"
    echo ""

    if [[ $failed -gt 0 ]]; then
        err "Some checks failed. Run 'make setup' to fix setup issues."
        exit 1
    elif [[ $warned -gt 0 ]]; then
        warn "Some warnings found. The application may still work."
        exit 0
    else
        ok "Everything looks good!"
        exit 0
    fi
}

main "$@"
