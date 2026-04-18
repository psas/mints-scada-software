# Architecture

MINTS SCADA is a backend-first system. The backend service is the system of record. The GUI is a restartable client that connects over IPC. This page explains how the major subsystems fit together.

## Design Principles

1. **Backend is the source of truth.** The backend owns hardware access, runtime state, command dispatch, and history writing. The GUI never talks to hardware directly.
2. **GUI is restartable.** The GUI can crash and restart without losing state or stopping a recording. The backend keeps running.
3. **Failure isolation.** GUI windows run as separate processes so one can crash without taking the other down. Raw and backup archives use separate writer processes so a failure in one does not corrupt the other.
4. **Abort relay is independent.** Abort requests go through a separate relay process that is architecturally independent from the GUI windows. However, the current abort implementation is a placeholder -- see [Abort Flow](#abort-flow) below.

## Process Model

When the application is running via `make run`, these OS-level processes cooperate:

```
make run
  ├── Shutdown watcher         (polls for shutdown signal, kills processes)
  └── GUI launcher (main.py)   (checklist dialog, then spawns:)
        ├── Gateway service          (CAN bus owner, raw/rawbak recording) [live mode only]
        ├── Backend service          (state, commands, structured recording)
        ├── Supervisor               (monitors windows, respawns during recording)
        │     ├── Controller window host    (left window)
        │     └── SCADA window host         (right window)
        └── Abort relay              (abort forwarding) [live mode only]
```

The Makefile starts the shutdown watcher via nohup, then runs `python -m gui.main` in the foreground. `gui/main.py` delegates to the root `main.py`, which shows the checklist dialog and starts services based on the operator's mode selection.

In live mode, the launcher starts the gateway, then the backend, then the abort relay, then the supervisor. In playback mode, only the backend and supervisor are started.

The backend also spawns up to three child processes for history writing when a recording run is active:

- Raw writer
- Raw backup writer
- Structured writer

### Process Communication

| Link | Transport | Direction |
|------|-----------|-----------|
| Gateway <-> Backend | Unix socket (`.gateway_service.sock`) | Bidirectional |
| Backend <-> GUI windows | Unix socket (`.backend_service.sock`) | Bidirectional |
| GUI windows -> Abort relay | Unix socket (temp dir) | Request/response |
| Abort relay -> Gateway | Unix socket (`.gateway_service.sock`) | Request/response |
| Backend -> Writers | `multiprocessing.Queue` | One-way commands |
| Writers -> Backend | `multiprocessing.Queue` | One-way status |
| Shutdown watcher | File-based (`.shutdown_signal`, `.applicationpid`) | Signal |

All IPC sockets use JSON-lines protocol (newline-delimited JSON).

## Subsystem Responsibilities

### Gateway (`gateway/`)

The gateway owns the physical CAN bus connection. It:

- Opens and manages the CAN bus hardware via the nexus bus layer
- Receives all inbound telemetry packets from the bus
- Forwards telemetry to the backend over IPC
- Accepts outbound command packets from the backend and sends them on the bus
- Writes raw and raw-backup event archives during recording
- Handles abort relay requests (currently a placeholder -- sets a latch flag and logs)
- Reports bus connection status to the backend

The gateway is intentionally simple. It owns the bus, writes raw archives, and forwards data. The backend remains the system of record for authoritative state and structured history.

### Backend (`backend/`)

The backend is the main orchestrator. It:

- Maintains the authoritative runtime state (`StateStore`, RLock-protected)
- Runs the telemetry reducer (raw packets -> semantic state: pressure, temperature, valve position, etc.)
- Routes and validates operator commands with safety interlocks (`CommandRouter`)
- Manages the recording lifecycle: start run, stop run (`RunController`)
- Writes structured history archives with semantic event data
- Executes user scripts with plan-mode hold/continue support (`ScriptRunner`)
- Monitors system health and publishes health transitions (`BackendHealthMonitor`)
- Serves GUI clients over IPC (`IPCServer`)
- Maintains a persistent client to the gateway (`GatewayClient`)

Key backend modules:

| Module | Role |
|--------|------|
| `service.py` | Main orchestrator, composes all subsystems, IPC message dispatch |
| `state_store.py` | Thread-safe authoritative runtime state (RLock-protected) |
| `command_router.py` | Command validation, interlock pipeline, dispatch |
| `reducer.py` | Telemetry packet -> semantic state transformation |
| `script_runner.py` | Script execution: subprocess, legacy inline, plan-mode |
| `bus_manager.py` | CAN bus lifecycle, reconnect with exponential backoff |
| `device_registry.py` | Device loading from `settings.py`, runtime instance creation |
| `run_controller.py` | Recording run start/finish lifecycle |
| `structured_builder.py` | Structured history event construction |
| `health.py` | Periodic health sampling, state transition events |
| `ipc_server.py` | Unix socket server with per-client daemon threads |
| `gateway_client.py` | Persistent IPC client to gateway |
| `gateway_bus_proxy.py` | Bus proxy that routes commands through gateway instead of local bus |
| `abort_command.py` | Canonical abort dispatch metadata and event builders |
| `clear_abort_latch_command.py` | Abort latch clear dispatch and event builders |

### GUI (`gui/`)

The GUI is a PyQt5 client that renders state and collects operator actions. It:

- Displays live telemetry data, graphs, and device states
- Shows the P&ID schematic with valve state visualization
- Provides recording start/stop controls
- Provides script loading and execution controls
- Sends command requests to the backend (the backend decides whether to execute them)
- Receives state snapshots from the backend via periodic polling
- Loads and replays recorded test runs in playback mode

The GUI does **not** own hardware access, state, history writing, or command dispatch.

Key GUI modules:

| Module | Role |
|--------|------|
| `window_host.py` | Window process entry point, backend IPC bridge, playback driver |
| `controller_window.py` | Left window: devices, graphs, console, scripts, recording |
| `scada_window.py` | Right window: P&ID schematic with valve controls |
| `checklist_window.py` | Pre-launch dialog: live vs playback selection, run metadata |
| `supervisor.py` | Process monitor, window respawn during recording |
| `abort_relay.py` | Independent abort/clear-abort-latch forwarding to gateway |
| `backend_client.py` | IPC client with auto-reconnect and heartbeat |
| `shutdown_watcher.py` | Polls for shutdown signal file, force-kills tracked processes |
| `playback_state_manager.py` | Playback position, speed, and state reconstruction |

### History Manager (`historymanager/`)

The history subsystem handles recording, archive validation, and rebuild:

| Module | Role |
|--------|------|
| `manager.py` | Run lifecycle, writer process management, event materialization |
| `writers.py` | Worker process main loops for raw and structured archives |
| `integrity.py` | Cross-archive validation (event UID matching, hash comparison) |
| `rebuild.py` | Archive reconstruction from available sources |
| `models.py` | Data models: stream filenames, path containers, writer stats |
| `paths.py` | Path resolution for archive directories |
| `snapshots.py` | Snapshot serialization helpers |
| `stats.py` | Writer statistics helpers |

### Nexus (`nexus/`)

The CAN bus abstraction layer. Wraps `python-can` and provides base classes for devices:

| Module | Role |
|--------|------|
| `bus.py` | CAN bus wrapper with receiver thread |
| `busrider.py` | Base class for bus-connected devices |
| `datapacket.py` | CAN message wrapper with arbitration ID bit extraction |
| `genericsensor.py` | Sensor base class: value reading, history buffer |
| `genericactuator.py` | Actuator base class: set/write commands |

### Electrical Devices (`electricaldevices/`)

Concrete hardware device implementations built on the nexus base classes. Located under `actuators/` and `sensors/` subdirectories.

### Device Catalog (`settings.py`)

The static device catalog that defines all devices in the system. Each device has:

- `id` -- unique identifier in lowercase-hyphenated form (must match SVG element IDs)
- `name` -- human-readable display name
- `deviceType` -- software device type / backend class family
- `deviceGroup` -- engineering grouping (PT, XV, PSV, etc.)
- `deviceSystems` -- list of system memberships (IG, LOX, etc.)
- `address` -- CAN bus address
- `hasElectricalIO` -- whether the device has readable electrical signals
- `isControllable` -- whether commands can be sent to the device

## Data Flow

### Live Telemetry

```
CAN hardware
  -> Gateway receives bus packet
  -> Gateway writes raw event to .ignitionraw/ and .ignitionrawbak/
  -> Gateway forwards packet to backend over IPC
  -> Backend DeviceRegistry routes to device instance
  -> Backend Reducer transforms to semantic state
  -> Backend StateStore updates authoritative state
  -> Backend writes structured event to ignitionhistory/
  -> GUI polls backend for state snapshots
```

### Command Dispatch

```
Operator clicks control in GUI
  -> GUI sends command_request to backend over IPC
  -> Backend CommandRouter validates:
      authority level -> mode guard -> run status -> device existence
      -> controllability -> bus connection -> interlocks
  -> Accepted: backend sends command to gateway over IPC
  -> Gateway sends CAN packet on bus
  -> Telemetry feedback confirms state change
```

### Abort Flow

The abort path uses an independent relay process so it can function even if GUI windows are frozen or crashed:

```
Operator presses Abort in either GUI window
  -> GUI window sends abort request to Abort Relay (separate process)
  -> Abort Relay forwards to gateway
  -> Gateway sets abort latch flag and logs the request
  -> Gateway records the abort as an operator action and system event
```

**Current limitation:** The abort implementation is a placeholder. The gateway sets an internal latch flag and logs the abort request, but does **not** currently send hardware stop commands to devices. The code contains explicit TODO markers (`TODO(psas-abort-fastpath)`) noting that the real hardware-side abort behavior has not been defined yet.

The gateway's abort latch message reads: *"ABORT LATCHED !!! PRESS THE E-STOP BUTTON NOW !!!"* -- reinforcing that the physical E-stop is the intended real emergency stop mechanism.

The abort relay also supports a "clear abort latch" flow that resets the gateway's latch flag and reinitializes runtime state.

### Recording Lifecycle

```
Start recording:
  Backend creates run ID -> creates archive directories -> starts writer processes
  -> writes metadata -> records initial snapshot -> marks state as recording

During recording:
  Events flow to writer processes via multiprocessing queues
  Raw writer + rawbak writer: gateway-owned, write raw event streams
  Structured writer: backend-owned, writes structured events + merged timeline

Stop recording:
  Backend writes final snapshot -> drains writer queues -> writes complete.json
  -> runs integrity scan -> marks state as not recording
```

## IPC Protocol

GUI and backend communicate over Unix domain sockets using newline-delimited JSON messages.

**GUI -> Backend messages:**
`hello`, `ping`, `status_request`, `request_full_state`, `list_devices`, `initialize_live_hardware`, `shutdown_live_hardware`, `start_run`, `finish_run`, `ingest_mock_telemetry`, `operator_action`, `command_request`, `start_script`, `stop_script`, `hold_script`, `continue_script`, `shutdown_service`

**Backend -> GUI messages:**
`hello_ack`, `backend_status`, `run_status`, `state_snapshot`, `structured_event`, `operator_action_recorded`, `command_result`, `script_status`, `device_inventory`, `hardware_status`, `pong`, `error`

**Gateway supported messages:**
`hello`, `ping`, `status_request`, `start_run`, `finish_run`, `record_raw_event`, `initialize_live_hardware`, `shutdown_live_hardware`, `send_packet`, `abort_request`, `clear_abort_latch_request`

### State Polling

The GUI uses periodic polling rather than a push/subscribe mechanism:
- **Live mode**: state sync every 100ms, health poll every 1s
- **Playback mode**: state sync every 5s, health poll every 1s
- **Heartbeat**: 1s interval from each window to backend

## History Archives

Each recording run produces data in three archive directories:

| Archive | Path | Owner | Purpose |
|---------|------|-------|---------|
| Raw | `.ignitionraw/{run_id}/` | Gateway | First-order events as received |
| Raw backup | `.ignitionrawbak/{run_id}/` | Gateway | Redundant copy, failure-isolated |
| Structured | `ignitionhistory/{run_id}/` | Backend | Semantically decoded events, snapshots, merged stream |

See [History Format](history-format.md) for detailed archive structure.

## Thread Model

### Backend Threads

| Thread | Purpose |
|--------|---------|
| Main thread | IPC accept loop (`IPCServer.serve_forever()`) |
| IPC client handlers (N) | One daemon thread per connected client |
| Bus supervisor | Connection health monitoring |
| Bus receive | CAN packet polling |
| Health monitor | Periodic health state sampling |
| Script watcher | Subprocess exit detection |
| Plan runner | Plan-mode step execution (when active) |

### GUI Threads (per window process)

| Thread | Purpose |
|--------|---------|
| Main thread | Qt event loop |
| Backend reader | IPC socket read loop |
| QTimers | State polling, heartbeat, display refresh |

## See Also

- [Developer Guide](developer-guide.md) -- codebase orientation and conventions
- [History Format](history-format.md) -- recording archive structure
- [Known Issues](known-issues.md) -- tracked bugs and limitations
- [Future Ideas](future-ideas.md) -- deferred improvements
