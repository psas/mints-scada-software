#!/bin/bash
# bootstrap/run.sh -- Application launch helper.
#
# Activates the virtual environment, creates required directories,
# prints serial port status, and launches the GUI entry point with
# a cleanup trap for process lifecycle management.
#
# This is the implementation behind `make run`.

set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

#  Configuration

GUI_MODULE="gui.main"

#  Preflight

require_venv
ensure_dev_dir
ensure_history_dirs

#  Serial port status 

echo "=== Serial Ports ==="
ports=$(ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null || true)
if [[ -n "$ports" ]]; then
    echo "$ports"
else
    echo "  (none detected)"
    if is_wsl; then
        echo "  WSL: run 'make wsl-usb' if USB forwarding is needed"
    fi
fi
echo ""

#  Cleanup trap 

cleanup() {
    gui_code=$?
    info "Launcher cleanup starting..."

    if [[ -f "$SHUTDOWN_SIGNAL" ]]; then
        info "Detected shutdown signal; waiting for shutdown_watcher..."
        for _ in $(seq 1 20); do
            if [[ ! -f "$SHUTDOWN_SIGNAL" && ! -f "$APPLICATION_PID_FILE" ]]; then
                ok "shutdown_watcher completed cleanup"
                exit "$gui_code"
            fi
            sleep 0.25
        done
        warn "shutdown_watcher did not finish in time; falling back to manual cleanup"
    fi

    if [[ -f "$APPLICATION_PID_FILE" ]]; then
        # First pass: SIGTERM (skip shutdown_watcher).
        while IFS= read -r pid_line; do
            pid=$(echo "$pid_line" | awk '{print $1}')
            label=$(echo "$pid_line" | cut -d' ' -f2-)
            [[ "$label" == "shutdown_watcher" ]] && continue
            if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
                info "Terminating $label (pid=$pid)"
                kill "$pid" 2>/dev/null || true
            fi
        done < "$APPLICATION_PID_FILE"

        sleep 1.5

        # Second pass: SIGKILL survivors.
        while IFS= read -r pid_line; do
            pid=$(echo "$pid_line" | awk '{print $1}')
            label=$(echo "$pid_line" | cut -d' ' -f2-)
            [[ "$label" == "shutdown_watcher" ]] && continue
            if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
                warn "Force killing $label (pid=$pid)"
                kill -9 "$pid" 2>/dev/null || true
            fi
        done < "$APPLICATION_PID_FILE"

        rm -f "$APPLICATION_PID_FILE"
    fi

    clean_runtime_files
    ok "Launcher session ended"
    exit "$gui_code"
}

trap cleanup EXIT INT TERM

#  Launch 

rm -f "$APPLICATION_PID_FILE" "$SHUTDOWN_SIGNAL"

info "Starting shutdown watcher..."
nohup "$VENV_PYTHON" "$REPO_ROOT/gui/shutdown_watcher.py" >/dev/null 2>&1 &
watcher_pid=$!
echo "$watcher_pid shutdown_watcher" >> "$APPLICATION_PID_FILE"

info "Starting GUI launcher..."
cd "$REPO_ROOT"
"$VENV_PYTHON" -m "$GUI_MODULE"
