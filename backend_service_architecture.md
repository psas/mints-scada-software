# Backend-First Architecture and Migration Plan

## Status

Draft for `feature/backend-service-core`

## Goal

Refactor the teststand software into a **backend-first system** where the backend service is the system of record and the PyQt5 GUI is only a client.

The backend must remain alive and continue recording, reducing, and maintaining state even if the GUI crashes or restarts.

The GUI must be treated as:

- a display surface
- an operator interaction surface
- a requester of actions
- a subscriber to backend state and events

The GUI must **not** be the authoritative owner of:

- COM / bus access
- live state
- reducer logic
- structured event generation
- history writing
- command dispatch

---

## Target Architecture

```text
Backend Service
  - COM / bus ownership
  - device registry
  - reducer
  - authoritative state store
  - structured event builder
  - history manager
    - raw writer
    - rawbak writer
    - structured writer
  - command dispatch
  - script runner
  - IPC server

GUI Client
  - window creation
  - visualization
  - operator interaction
  - playback UI
  - IPC client
  - subscribes to backend state/events
  - sends action/command requests to backend
````

---

## Core Design Principles

### 1. Backend is the source of truth

The backend owns the authoritative runtime state.

### 2. GUI is restartable

The GUI may disconnect, crash, or restart without ending the run.

### 3. Live UI does not read history from disk

Live UI reads backend state, not `.ignitionraw`, `.ignitionrawbak`, or `ignitionhistory`.

### 4. History is archive, not live source

History is for persistence, playback, replay, debugging, and analysis.

### 5. Raw means first-order event archive

Raw does **not** mean only wire-level serial packets.

Raw includes all first-order events that should be preserved as directly as possible:

* `telemetry_in`
* `command_out`
* `operator_action`
* `system_event`

### 6. Raw and rawbak must be failure-isolated

Raw and rawbak must not share one blocking write path.

### 7. Structured is asynchronous and must not block live

Structured persistence is important, but it must not stall live state updates.

### 8. One file, one writer owner

Each append-only file must have a single writer owner.

---

## Runtime Responsibilities

## Backend Service Responsibilities

The backend service is responsible for:

* owning COM / bus connections
* owning bus receive/send lifecycle
* owning runtime device registry
* receiving telemetry
* recording raw first-order events
* running reducer logic
* maintaining authoritative live state
* building structured events
* writing history
* routing commands
* enforcing command validation / interlocks
* publishing state and events to GUI clients
* handling GUI reconnects
* optionally running scripts in a controlled backend-owned environment

## GUI Responsibilities

The GUI is responsible for:

* rendering current live state
* rendering graphs and panels
* rendering alarms, status, and sequence information
* collecting operator actions
* sending action requests to backend
* requesting commands from backend
* receiving state snapshots and patches
* receiving structured events for display
* displaying playback data

The GUI is **not** responsible for:

* owning bus access
* reducer logic
* direct file writes to history
* direct command dispatch to hardware
* owning authoritative live state

---

## History Model

The backend owns the history subsystem.

### Fixed Root Directories

These directories must exist at repo root:

* `.ignitionraw`
* `.ignitionrawbak`
* `ignitionhistory`

### Meanings

* `.ignitionraw`

  * append-only first-order event archive

* `.ignitionrawbak`

  * mirrored first-order event archive
  * independent backup writer path

* `ignitionhistory`

  * interpreted replay-oriented archive
  * structured events, merged timeline, snapshots

### Per-run Structure

For run id example `2026-03-12_ignition_test_01`:

```text
.ignitionraw/
  2026-03-12_ignition_test_01/
    metadata.json
    telemetry_in.raw.jsonl
    command_out.raw.jsonl
    operator_action.jsonl
    system_event.jsonl
    writer_stats.json
    complete.json

.ignitionrawbak/
  2026-03-12_ignition_test_01/
    metadata.json
    telemetry_in.raw.jsonl
    command_out.raw.jsonl
    operator_action.jsonl
    system_event.jsonl
    writer_stats.json
    complete.json

ignitionhistory/
  2026-03-12_ignition_test_01/
    metadata.json
    telemetry_in.jsonl
    command_out.jsonl
    operator_action.jsonl
    system_event.jsonl
    merged.jsonl
    snapshots/
      000000.json
      000005.json
      000010.json
    writer_stats.json
    complete.json
```

---

## Event Streams

The system recognizes four top-level event streams.

### 1. telemetry_in

State and feedback from the teststand.

Examples:

* pressure
* temperature
* valve feedback
* health/status
* heartbeat
* fault code
* sequence state

### 2. command_out

Actual control commands sent outward.

Examples:

* open valve
* close valve
* arm
* disarm
* abort
* start sequence
* setpoint change

### 3. operator_action

Operator/UI actions, separate from command dispatch.

Examples:

* clicked abort
* switched page
* selected test profile
* changed a field but did not apply yet
* confirmed a dialog
* added marker/note
* switched tab/view

### 4. system_event

Local/backend/system runtime events.

Examples:

* logger started/stopped
* reconnecting bus
* lost connection
* replay started/paused
* dropped packet
* queue overflow warning
* file flush success/failure
* GUI exception
* writer exception
* thread restarted
* process restarted

---

## Data Flow

### Live Telemetry Flow

```text
Bus packet received
  -> Backend BusManager
  -> HistoryManager.record_raw_event("telemetry_in", ...)
  -> Reducer
  -> StateStore.apply(...)
  -> StructuredEventBuilder
  -> HistoryManager.record_structured_event("telemetry_in", ...)
  -> IPC publish state/event updates to GUI
```

### Operator Action / Command Flow

```text
Operator clicks button in GUI
  -> GUI sends operator_action to backend
  -> Backend records raw operator_action
  -> Backend validates command request
  -> Backend records raw command_out
  -> Backend dispatches command to bus
  -> Reducer/state update follows when telemetry confirms change
```

### Snapshot Flow

```text
Backend state store
  -> HistoryManager.write_snapshot(...)
  -> ignitionhistory/<run_id>/snapshots/
```

---

## Writer Isolation Model

### Raw

Must be written by a dedicated writer path.

### RawBak

Must be written by a separate dedicated writer path.

### Structured

May be more relaxed than raw/rawbak, but must remain asynchronous and must not block live processing.

### Requirement

Raw and rawbak must not be implemented as one synchronous sequential write call in the GUI path.

Preferred model:

```text
backend
  -> raw_queue     -> raw_writer_process     -> .ignitionraw/<run_id>/
  -> rawbak_queue  -> rawbak_writer_process  -> .ignitionrawbak/<run_id>/
  -> structured_queue -> structured_writer   -> ignitionhistory/<run_id>/
```

---

## IPC Model

The backend and GUI communicate through an explicit IPC protocol.

### Requirements

* GUI may disconnect and reconnect
* backend must continue running without GUI
* GUI must be able to request a full state snapshot after reconnect
* protocol should be stable and explicit
* messages should be typed
* no GUI direct object references into backend internals

### Initial Message Types

#### GUI -> backend

* `hello`
* `subscribe_state`
* `request_full_state`
* `start_run`
* `finish_run`
* `command_request`
* `operator_action`
* `start_script`
* `stop_script`

#### backend -> GUI

* `hello_ack`
* `run_status`
* `state_snapshot`
* `state_patch`
* `structured_event`
* `system_event`
* `error`

---

## Run Lifecycle

## start_run()

The backend-side run lifecycle must:

1. reject start if a run is already active
2. create a run id
3. create run directories
4. write metadata
5. initialize writer stats
6. initialize stream files
7. mark backend state as running
8. activate history writers for the run

## finish_run()

The backend-side run lifecycle must:

1. reject finish if no run is active
2. flush/drain writers
3. update metadata to completed
4. write complete.json
5. mark backend state as not running
6. preserve the run for playback/history browsing

---

## State Model

The backend owns the authoritative state store.

The state store should eventually contain at least:

* backend status
* current mode
* active run id
* bus connection state
* reconnecting state
* device states
* telemetry-derived state
* sequence state
* alarms/faults
* last telemetry times
* current profile/test info
* script runner state
* writer health state

The GUI may cache a copy for rendering, but the backend copy is authoritative.

---

## Command Model

All hardware-affecting commands must flow through backend command dispatch.

The backend command path must eventually support:

* validation
* interlock enforcement
* permission checks
* run-mode checks
* state-aware rejection
* history recording
* bus dispatch
* error reporting

The GUI must request commands, not perform them directly.

---

## Script Model

Scripts must eventually move under backend control.

Goals:

* GUI does not directly own script execution
* script lifecycle survives GUI restart where appropriate
* backend can capture script-related system events
* safer termination model than in-process GUI execution
* future ability to sandbox or subprocess-isolate scripts

---

## Playback Model

Playback should ultimately use `ignitionhistory/<run_id>/...` as the replay-oriented archive.

Expected playback sources:

* `metadata.json`
* per-stream structured jsonl files
* `merged.jsonl`
* `snapshots/`

Playback must not depend on live backend memory state.

---

## Health and Watchdog Events

The backend should emit system events for runtime health transitions such as:

* bus connected
* bus disconnected
* reconnecting
* raw writer alive/dead
* rawbak writer alive/dead
* structured writer lagging/failing
* queue overflow warning
* GUI client connected/disconnected
* script runner started/stopped/crashed

These should be visible both in history and in GUI runtime views.

---

## Proposed Directory Additions

```text
backend/
  __init__.py
  app.py
  service.py
  bus_manager.py
  device_registry.py
  reducer.py
  state_store.py
  structured_builder.py
  command_router.py
  ipc_server.py
  ipc_models.py
  run_controller.py
  script_runner.py
  health.py

historymanager/
  __init__.py
  manager.py
  models.py
  writers.py
  paths.py
  stats.py
  snapshots.py

docs/
  backend_service_architecture.md
```

---

## Migration Plan

### Phase 1: Architecture and history foundation

* add backend architecture doc
* add historymanager base paths and run lifecycle
* add raw/rawbak writer process skeleton

### Phase 2: Backend service skeleton

* add backend entrypoint
* add IPC server
* add IPC models
* add state store
* add run controller

### Phase 3: Move bus ownership to backend

* backend creates and owns bus
* backend owns device registry
* GUI no longer directly owns bus

### Phase 4: Move reducer and structured builder to backend

* telemetry enters backend
* backend records raw
* reducer updates state
* structured events are built and persisted

### Phase 5: Convert GUI into client

* add backend client layer
* GUI subscribes to backend state/events
* GUI no longer owns live system state

### Phase 6: Move command path to backend

* GUI sends command requests
* backend validates and dispatches
* operator_action and command_out are recorded separately

### Phase 7: Move scripts to backend-owned runner

* backend owns script lifecycle
* GUI becomes a requester only

### Phase 8: Switch playback to ignitionhistory

* playback reads structured history archive
* live and playback archive models are unified

---

## Non-Goals for Early Commits

The first commits do **not** need to complete all backend functionality.

Early commits only need to establish:

* system boundaries
* directory layout
* history run lifecycle
* writer isolation strategy
* backend service skeleton
* GUI/client split direction

---

## Definition of Success

This architecture is considered successful when:

1. the backend can continue running if the GUI exits or crashes
2. the backend can continue receiving telemetry without GUI
3. raw/rawbak continue recording independently
4. reducer and state store continue updating without GUI
5. structured events continue being produced without GUI
6. GUI can reconnect and recover current live state
7. playback uses replay-oriented history instead of ad hoc live state

---

## Final Summary

The intended end state is:

* the backend is the runtime core
* the GUI is a restartable client
* live state belongs to backend
* hardware command dispatch belongs to backend
* history belongs to backend
* GUI is an observer/operator surface, not the system body

