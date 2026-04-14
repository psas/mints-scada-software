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

PYTHON="${PYTHON:-python3}"
GUI_MODULE="gui.main"

DEV_DIR="$REPO_ROOT/.dev"
HISTORY_DIRS=(".ignitionraw" ".ignitionrawbak" "ignitionhistory")

GATEWAY_PID_FILE="$DEV_DIR/gateway.pid"
BACKEND_PID_FILE="$DEV_DIR/backend.pid"
GATEWAY_SOCKET="$REPO_ROOT/.gateway_service.sock"
BACKEND_SOCKET="$REPO_ROOT/.backend_service.sock"
APPLICATION_PID_FILE="$REPO_ROOT/.applicationpid"
SHUTDOWN_SIGNAL="$REPO_ROOT/.shutdown_signal"
VENV_ACTIVATE_PATH="$REPO_ROOT/.venv/bin/activate"

#  Preflight 

require_venv

mkdir -p "$DEV_DIR"
for d in "${HISTORY_DIRS[@]}"; do
    mkdir -p "$REPO_ROOT/$d"
    touch "$REPO_ROOT/$d/.gitkeep"
done

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

    rm -f "$BACKEND_PID_FILE" "$BACKEND_SOCKET" "$GATEWAY_PID_FILE" "$GATEWAY_SOCKET"
    rm -f "$SHUTDOWN_SIGNAL"
    ok "Launcher session ended"
    exit "$gui_code"
}

trap cleanup EXIT INT TERM

#  Launch 

rm -f "$APPLICATION_PID_FILE" "$SHUTDOWN_SIGNAL"

info "Starting shutdown watcher..."
nohup bash -lc "source \"$VENV_ACTIVATE_PATH\" && exec $PYTHON gui/shutdown_watcher.py" >/dev/null 2>&1 &
watcher_pid=$!
echo "$watcher_pid shutdown_watcher" >> "$APPLICATION_PID_FILE"

info "Starting GUI launcher..."
activate_venv
cd "$REPO_ROOT"
$PYTHON -m "$GUI_MODULE"
