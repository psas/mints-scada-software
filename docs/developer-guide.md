# Developer Guide

This guide is for people working on the MINTS SCADA codebase. It covers how the code is organized, how the pieces connect, and practical advice for making changes.

## Codebase Overview

The repository is organized into Python packages by responsibility:

```
backend/              Backend service (system of record)
bootstrap/            Setup and launch scripts
  common.sh           Shared helpers (env detection, logging, repo root)
  setup.sh            Main setup entry point (orchestrates system-deps + python-env)
  system-deps.sh      OS-level dependency check and install
  python-env.sh       Virtual environment creation and pip install
  wsl-usb.sh          WSL USB forwarding setup
  run.sh              Application launcher (venv activation, cleanup trap)
  doctor.sh           Environment diagnostics
gateway/              CAN bus gateway service
gui/                  PyQt5 GUI client
historymanager/       Recording, validation, rebuild
nexus/                CAN bus abstraction layer
electricaldevices/    Concrete device implementations (actuators/, sensors/)
scripts/              User scripts and script runtime
  script_runtime/     Shared compatibility/runtime helpers
  script_sources/     Default, example, and legacy user scripts
test_unittest_dev/    Development test suite
```

### Entry Points

| Entry | File | What It Does |
|-------|------|-------------|
| Full application | `make run` -> `bootstrap/run.sh` -> `gui/main.py` -> `main.py` | Checklist -> services -> supervisor -> windows |
| Backend only | `python -m backend.main` (from activated venv) | Daemonized backend service |
| Gateway only | `python -m gateway.main` (from activated venv) | Daemonized gateway service |

The `main.py` at the repository root is the primary entry point. `gui/main.py` is a compatibility shim that delegates to it. The `bootstrap/run.sh` script handles preflight checks, directory setup, and the cleanup trap; it then invokes the venv Python directly with `-m gui.main`, which calls `main.main()`.

The Makefile is a thin user-facing wrapper. All commands delegate to scripts under `bootstrap/`.

The launcher (`main.py`) orchestrates:
1. Qt application creation and logging setup
2. Checklist dialog (`ChecklistWindow.exec_()`)
3. Service startup (gateway, backend) based on mode selection
4. Abort relay startup (live mode only)
5. Supervisor launch and wait
6. Session cleanup (shutdown watcher signal, process termination, socket/PID removal)

## Key Design Decisions

### Backend-First Architecture

The backend owns all authority. The GUI is a display and interaction surface only:

- All state changes happen in the backend first
- The GUI receives state through IPC polling (not direct object references)
- Commands go through the backend's command router, never directly to hardware
- History is written by the backend (structured) and gateway (raw), not the GUI

### Process Isolation

GUI windows run as separate OS processes (`gui/window_host.py` is the entry point for each). The supervisor (`gui/supervisor.py`) monitors them and restarts them during recording. The abort relay runs as its own process.

### Thread-Safe State

The backend's `StateStore` (`backend/state_store.py`) uses an `RLock` to protect all state access. Any code that reads or modifies runtime state must go through the state store's typed methods.

### IPC Protocol

All inter-process communication uses Unix domain sockets with newline-delimited JSON. No shared memory, no signals for data (only SIGTERM for shutdown), no files for communication (except the shutdown signal file).

## Working with the Backend

### Adding a New IPC Message Type

1. Define the message type constant and factory function in `backend/ipc_models.py`
2. Add a handler case in `BackendService.handle_message()` in `backend/service.py`
3. Add the client-side send method in `gui/backend_client.py` (`GuiBackendActionAPI`)
4. Connect the GUI signal/slot in `gui/window_host.py`

### Adding a New Command

1. Define the command behavior in the appropriate device class under `electricaldevices/`
2. Add validation logic in `backend/command_router.py` if needed
3. Update interlocks in `CommandRouter` if the command has safety requirements
4. The command router supports mock, global-abort, valve, and generic runtime-method dispatch paths

### Adding a New Device Type

1. Create the device class in `electricaldevices/` extending from `nexus/genericsensor.py` or `nexus/genericactuator.py`
2. Add device entries to the `devices` tuple in `settings.py` with all required fields
3. Update the reducer (`backend/reducer.py`) if the device has telemetry that maps to semantic state
4. The `DeviceRegistry` (`backend/device_registry.py`) resolves device classes by looking in `electricaldevices` first, then `nexus`

### Modifying State

All runtime state changes must go through `backend/state_store.py`. The state store provides typed update methods (`mark_device_packet`, `mark_command_result`, `mark_run_started`, `set_connected_clients`, etc.) that handle locking.

## Working with the GUI

### Window Process Model

Each GUI window runs in its own process. `gui/window_host.py` is the entry point for each window process. It creates:
- A `BackendClient` for IPC communication
- A `GuiBackendBridge` that translates IPC messages into Qt signals
- The appropriate window class (`ControllerWindow` or `ScadaWindow`)

### State Polling

The GUI polls the backend for state updates:
- Live mode: `_state_sync_timer` at 100ms interval
- Playback mode: `_state_sync_timer` at 5000ms interval
- Health poll: `_health_poll_timer` at 1000ms interval
- Heartbeat to backend: 1000ms interval

### Adding a New Widget

1. Create the widget class in `gui/`
2. Add it to the appropriate window class (`controller_window.py` or `scada_window.py`)
3. Connect it to state updates through the `GuiBackendBridge` signal chain in `window_host.py`

### GUI Tests

GUI tests require `QT_QPA_PLATFORM=offscreen` to run without a display. The test helpers set this automatically.

## Working with History

### Writer Processes

History writers run as `multiprocessing.Process` instances (daemon mode). They receive commands via `multiprocessing.Queue`:

- `start_run` -- create directories and stream files
- `event` -- write an event to the appropriate stream file
- `snapshot` -- write a state snapshot (structured writer only)
- `flush` -- flush all open file handles
- `finish_run` -- write completion marker, finalize files
- `shutdown` -- clean exit

Writer runtimes are created by `create_raw_writer_runtime()` and `create_structured_writer_runtime()` in `historymanager/writers.py`.

### Adding a New Event Stream

1. Add the stream name and filename to `RAW_STREAM_FILENAMES` and/or `STRUCTURED_STREAM_FILENAMES` in `historymanager/models.py`
2. Add recording calls in the appropriate backend or gateway module
3. Update the integrity scanner in `historymanager/integrity.py` if the new stream should participate in cross-archive validation

## Working with the Gateway

The gateway is intentionally simple. It owns the CAN bus and writes raw data:

1. Add IPC message handlers in `gateway/service.py` (`GatewayService`)
2. Add message definitions in `gateway/ipc_models.py`
3. Add the client-side call in `backend/gateway_client.py`
4. The gateway's `supported_messages` list in `__init__` must include the new message type

## Device Catalog

`settings.py` is the single source of truth for device metadata. Each device descriptor requires:

- `id` -- unique identifier in lowercase-hyphenated form (must match `^[a-z0-9]+(-[a-z0-9]+)*$` and SVG element IDs)
- `name` -- human-readable display name
- `deviceType` -- software device type / backend class family (e.g., `GenericSensor`, `GenericActuator`, `Solenoid`)
- `deviceGroup` -- engineering grouping (PT, XV, PSV, etc.)
- `deviceSystems` -- list of system memberships (e.g., `["IG"]`, `["LOX"]`, `[]`)
- `address` -- CAN bus address (use `0x000` for unknown)
- `hasElectricalIO` -- whether the device has readable electrical signals
- `isControllable` -- whether commands can be sent to this device

## Configuration and Runtime Files

| File | Purpose | Checked In |
|------|---------|-----------|
| `settings.py` | Device catalog, hardware config | Yes |
| `requirements.txt` | Python dependencies | Yes |
| `Makefile` | Build and run commands | Yes |
| `.guiworkspace.json` | Window positions (per machine) | No |
| `.guimetadata/` | GUI workspace metadata | No |
| `.dev/` | PID files for backend and gateway | No |
| `.backend_service.sock` | Backend IPC socket | No |
| `.gateway_service.sock` | Gateway IPC socket | No |
| `.applicationpid` | Process registry for shutdown | No |
| `.shutdown_signal` | Shutdown trigger file | No |
| `log/debug.log` | Application debug log | No |

## Useful Patterns

### Inspecting IPC Traffic

The backend logs IPC message handling at DEBUG level. Check `log/debug.log` to see message flow between GUI and backend.

### Running Just the Backend

For development, start only the backend from an activated venv:

```bash
source .venv/bin/activate
python -m backend.main
```

Then interact with it via IPC from a test script or a separately started GUI.

### Running Just the Gateway

```bash
source .venv/bin/activate
python -m gateway.main
```

Useful for testing CAN bus hardware connectivity without the full application stack.

## Common Pitfalls

- **Do not store state outside StateStore.** Any state that should survive GUI restarts belongs in the backend's `StateStore`.
- **Do not call hardware directly from GUI code.** All hardware interaction goes through backend IPC.
- **Be careful with multiprocessing.** Writer processes are daemon processes. They die when the parent dies without flushing. The writer creation uses the multiprocessing context pattern.
- **Qt thread safety.** Only modify Qt widgets from the main thread. Use signals/slots or `QMetaObject.invokeMethod` for cross-thread updates.
- **Device registry packet routing.** The device registry sets a `_onPacket` callback on device instances. Changes to packet handling should go through the registry's callback mechanism.

## See Also

- [Architecture](architecture.md) -- system design, process model, data flow
- [Testing](testing.md) -- running and writing tests
- [Known Issues](known-issues.md) -- tracked bugs and limitations
- [Future Ideas](future-ideas.md) -- deferred improvements
