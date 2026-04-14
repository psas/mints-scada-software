#!/bin/bash
# bootstrap/status.sh -- Show application status.
#
# Reports on running processes, sockets, history dirs, and dev files.
# This is the implementation behind `make status`.

set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

echo "=== MINTS SCADA Status ==="

# Gateway process.
if [[ -f "$GATEWAY_PID_FILE" ]]; then
    pid=$(cat "$GATEWAY_PID_FILE" 2>/dev/null || true)
    if pid_is_alive "$pid"; then
        echo "Gateway PID: $pid [alive]"
    else
        echo "Gateway PID file exists but process is dead"
    fi
else
    echo "Gateway PID: [none]"
fi

# Sockets.
echo "Gateway socket: $GATEWAY_SOCKET"
if [[ -S "$GATEWAY_SOCKET" ]]; then echo "  [OK] socket exists"; else echo "  [--] socket missing"; fi
echo "Backend socket: $BACKEND_SOCKET"
if [[ -S "$BACKEND_SOCKET" ]]; then echo "  [OK] socket exists"; else echo "  [--] socket missing"; fi

# Backend process.
if [[ -f "$BACKEND_PID_FILE" ]]; then
    pid=$(cat "$BACKEND_PID_FILE" 2>/dev/null || true)
    if pid_is_alive "$pid"; then
        echo "Backend PID: $pid [alive]"
    else
        echo "Backend PID file exists but process is dead"
    fi
else
    echo "Backend PID: [none]"
fi

# Application processes.
if [[ -f "$APPLICATION_PID_FILE" ]]; then
    echo "Application PID file: $APPLICATION_PID_FILE [present]"
    while IFS= read -r pid_line; do
        pid=$(echo "$pid_line" | awk '{print $1}')
        label=$(echo "$pid_line" | cut -d' ' -f2-)
        if pid_is_alive "$pid"; then
            echo "  [OK] $label pid=$pid"
        else
            echo "  [--] $label pid=$pid not alive"
        fi
    done < "$APPLICATION_PID_FILE"
else
    echo "Application PID file: [none]"
fi

# History directories.
echo "History roots:"
for d in "${HISTORY_DIRS[@]}"; do
    if [[ -d "$REPO_ROOT/$d" ]]; then
        echo "  [OK] $d"
    else
        echo "  [--] $d missing"
    fi
done

# Local dev files.
echo "Local dev files:"
for f in "${LOCAL_DEV_FILES[@]}"; do
    if [[ -f "$REPO_ROOT/$f" ]]; then echo "  [OK] $f"; else echo "  [--] $f missing"; fi
done
echo "Local dev dirs:"
for d in "${LOCAL_DEV_DIRS[@]}"; do
    if [[ -d "$REPO_ROOT/$d" ]]; then echo "  [OK] $d"; else echo "  [--] $d missing"; fi
done
