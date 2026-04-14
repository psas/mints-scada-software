#!/bin/bash
# bootstrap/clean-dev.sh -- Remove only runtime artifacts.
#
# Cleans PID files, socket files, shutdown signal, and the .dev/
# directory. Does NOT touch history data.
#
# Useful after a crash leaves stale runtime files.
# This is a dev-only helper (hidden from `make help`).

set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

info "Cleaning runtime artifacts..."
clean_runtime_files
rmdir "$DEV_DIR" 2>/dev/null || true
ok "Runtime artifacts cleaned"
