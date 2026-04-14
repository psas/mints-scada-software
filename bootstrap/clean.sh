#!/bin/bash
# bootstrap/clean.sh -- Full cleanup.
#
# Stops the application, clears all history data, and removes
# local dev-only metadata and scratch directories.
# This is the implementation behind `make clean`.
#
# Set MINTS_FORCE=1 to skip confirmation.

set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

BOOTSTRAP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

require_confirm "This will stop the application, delete ALL history data, and remove dev metadata. Continue?"

# Stop running processes first.
bash "$BOOTSTRAP_DIR/stop.sh"

# Clear history (skip its own confirmation since we already confirmed).
MINTS_FORCE=1 bash "$BOOTSTRAP_DIR/clean-history.sh"

# Remove local dev-only metadata and scratch directories.
warn "Removing local dev-only metadata and scratch directories..."
for f in "${LOCAL_DEV_FILES[@]}"; do
    rm -f "$REPO_ROOT/$f"
done
for d in "${LOCAL_DEV_DIRS[@]}"; do
    rm -rf "$REPO_ROOT/$d"
done
rm -rf "$DEV_DIR"

ok "Full dev cleanup complete"
