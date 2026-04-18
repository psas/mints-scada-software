# Getting Started

This guide walks through setting up and running the MINTS SCADA software for the first time.

## Requirements

- **Python 3.12** (the version matters -- other versions may not work)
- **Linux** or **WSL** (Windows Subsystem for Linux)
- **venv** (Python virtual environment module, usually included with Python 3.12)
- **CAN bus hardware** (for live mode -- not required for playback)

Mac is not officially supported but may work with adjustments.

## First-Time Setup

### 1. Clone the repository

```bash
git clone <repository-url>
cd mints-scada-software
```

### 2. Run setup

```bash
make setup
```

This does two things:

1. **Checks system dependencies** -- verifies that OS-level libraries needed by PyQt5 and the application are installed. If any are missing, setup lists them and asks for confirmation before installing.
2. **Sets up the Python environment** -- creates a virtual environment in `.venv/` and installs all Python dependencies from `requirements.txt`. Runs a quick import check to verify key packages.

You do **not** need to activate the virtual environment manually. `make run` and all other Makefile targets handle virtual environment activation internally.

If the setup detects WSL, it will suggest running `make wsl-usb` for USB forwarding.

### 3. WSL USB forwarding (WSL users only)

If you are running in WSL and need to connect CAN bus hardware:

```bash
make wsl-usb
```

This runs `bootstrap/wsl-usb.sh`, which:
- Checks for and installs USB/serial tools (`usbutils`, `linux-tools-generic`, `hwdata`) -- with confirmation before installing
- Checks that `usbipd-win` is installed on the Windows host
- Walks you through attaching a USB device from Windows into WSL

`usbipd-win` must be installed on the Windows side first. The script will tell you how if it is missing.

## Normal Run

After setup is complete, start the application with:

```bash
make run
```

You do not need to run `make setup` again unless dependencies change.

## What Happens at Startup

`make run` does the following:

1. Checks that the virtual environment exists
2. Creates history archive directories if they do not exist
3. Lists available serial ports
4. Starts a shutdown watcher process (background cleanup watchdog)
5. Launches the GUI entry point (`gui/main.py` -> `main.py`)

The first window you see is the **startup checklist**. Here you choose:

- **Live mode** -- Connect to real hardware. The launcher starts the gateway and backend services, then opens the operator windows.
- **Playback mode** -- Select a previously recorded test run. The launcher starts only the backend service (no gateway, no hardware), then opens the operator windows.

After your selection, the system opens two operator windows:

- **Controller window** (left) -- Device controls, graphs, console, scripts, recording controls
- **SCADA window** (right) -- P&ID schematic with valve state visualization

## Stopping the Application

You can stop the application in several ways:

- **Close the SCADA window** (right window). This triggers a full shutdown.
- Run `make stop` from the terminal.
- Press **Ctrl+C** in the terminal where `make run` is running.

Closing the controller window (left window) does **not** shut down the application. If you are recording, the supervisor will respawn the controller window. If you are not recording, the supervisor shuts down both windows.

## Checking Status

```bash
make status
```

This shows the state of all tracked processes (gateway, backend, GUI windows), socket files, history directories, and PID files.

## What is Running

When the application is running, these OS-level processes cooperate:

| Process | Purpose |
|---------|---------|
| Gateway | Owns CAN bus hardware, writes raw data archives (live mode only) |
| Backend | Processes telemetry, manages state, dispatches commands, writes structured history |
| Shutdown watcher | Monitors for shutdown signal, cleans up processes on exit |
| Supervisor | Monitors GUI windows, restarts them if they crash during recording |
| Controller window | Left operator window |
| SCADA window | Right operator window (P&ID schematic) |
| Abort relay | Independent abort command forwarding (live mode only) |

The backend and gateway communicate over Unix domain sockets. The GUI windows also connect to the backend over a Unix socket. All processes register their PIDs in `.applicationpid` for coordinated shutdown.

## Files Created After First Run

After running the application, you will see some new files and directories:

| Path | Purpose |
|------|---------|
| `.venv/` | Python virtual environment (created by `make setup`) |
| `.dev/` | PID files for backend and gateway |
| `.backend_service.sock` | Backend IPC socket |
| `.gateway_service.sock` | Gateway IPC socket (live mode only) |
| `.applicationpid` | Process ID registry for cleanup |
| `.guiworkspace.json` | Saved window positions |
| `log/debug.log` | Application debug log |
| `.ignitionraw/` | Raw event archives (per run) |
| `.ignitionrawbak/` | Backup raw event archives (per run) |
| `ignitionhistory/` | Structured replay archives (per run) |

None of these are checked into version control.

## Next Steps

- [Live Mode](live-mode.md) -- How to operate the system with real hardware
- [Playback](playback.md) -- How to review recorded test runs
- [Scripts](scripts.md) -- How to write and run automation scripts
