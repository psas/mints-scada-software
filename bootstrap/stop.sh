#!/bin/bash
# bootstrap/stop.sh -- Stop the application.
#
# Terminates all application processes (GUI, backend, gateway)
# using pid files, with SIGTERM then SIGKILL fallback.
# This is the implementation behind `make stop`.

set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

stopped_any=0

# Stop processes listed in the application pid file.
if [[ -f "$APPLICATION_PID_FILE" ]]; then
    info "Stopping application processes from $APPLICATION_PID_FILE..."

    # First pass: SIGTERM.
    while IFS= read -r pid_line; do
        pid=$(echo "$pid_line" | awk '{print $1}')
        label=$(echo "$pid_line" | cut -d' ' -f2-)
        if pid_is_alive "$pid"; then
            info "Terminating $label (pid=$pid)"
            kill "$pid" 2>/dev/null || true
            stopped_any=1
        fi
    done < "$APPLICATION_PID_FILE"

    sleep 1

    # Second pass: SIGKILL survivors.
    while IFS= read -r pid_line; do
        pid=$(echo "$pid_line" | awk '{print $1}')
        label=$(echo "$pid_line" | cut -d' ' -f2-)
        if pid_is_alive "$pid"; then
            warn "Force killing $label (pid=$pid)"
            kill -9 "$pid" 2>/dev/null || true
            stopped_any=1
        fi
    done < "$APPLICATION_PID_FILE"

    rm -f "$APPLICATION_PID_FILE"
fi

# Stop backend and gateway via pid files.
stop_pid_file "$BACKEND_PID_FILE" "backend" && stopped_any=1 || true
stop_pid_file "$GATEWAY_PID_FILE" "gateway" && stopped_any=1 || true

# Clean up stale runtime files.
clean_runtime_files

if [[ "$stopped_any" -eq 1 ]]; then
    ok "Application stopped"
else
    info "No running application processes found"
fi
