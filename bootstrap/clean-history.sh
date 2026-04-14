#!/bin/bash
# bootstrap/clean-history.sh -- Remove all generated history data.
#
# Clears everything inside the history directories, keeping only
# .gitkeep files so the directories remain tracked by git.
# This is the implementation behind `make clean-history`.
#
# Set MINTS_FORCE=1 to skip confirmation.

set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

require_confirm "This will delete ALL recording history data (.ignitionraw, .ignitionrawbak, ignitionhistory). Continue?"

warn "Clearing all history data..."

for d in "${HISTORY_DIRS[@]}"; do
    dir="$REPO_ROOT/$d"
    if [[ -d "$dir" ]]; then
        for entry in "$dir"/* "$dir"/.*; do
            [[ ! -e "$entry" ]] && continue
            name=$(basename "$entry")
            [[ "$name" == "." || "$name" == ".." || "$name" == ".gitkeep" ]] && continue
            echo "  [RM] $entry"
            rm -rf "$entry"
        done
    fi
    mkdir -p "$dir"
    touch "$dir/.gitkeep"
done

ok "All history data cleared"
