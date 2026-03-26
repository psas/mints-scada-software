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
  - backend health monitor
  - IPC server

GUI Client Side
  - GUI launcher
  - GUI supervisor
  - abort relay
  - left window process
  - right window process
  - visualization
  - operator interaction
  - playback UI
  - IPC clients
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
* `wire_command_out` - wire-level outbound packet facts (gateway-owned)
* `operator_action`
* `system_event`

Note: structured history uses `command_out` for semantic command dispatch events
(command name, device, interlocks).  These are intentionally separate streams.

### 6. Raw and rawbak must be failure-isolated

Raw and rawbak must not share one blocking write path.

### 7. Structured is asynchronous and must not block live

Structured persistence is important, but it must not stall live state updates.

### 8. One file, one writer owner

Each append-only file must have a single writer owner.

### 9. GUI windows must not share one failure domain

The left and right GUI windows must be able to fail independently.

A crash or freeze in one window process must not force the other window process down.

### 10. Abort must remain backend-authoritative

Abort may be triggered from either GUI window, but abort dispatch must still flow through backend command authority.

An abort relay process may forward abort requests, but it must not directly own hardware control.

### 11. GUI recovery should preserve workspace when possible

GUI layout, window placement, and widget arrangement should be restorable after crash or restart through GUI workspace metadata.

If that metadata is invalid or unavailable, the GUI must fall back to a safe default layout.

### 12. Playback must support archive validation

Playback should not only load `ignitionhistory`, but also support validation of archive consistency across raw, rawbak, and structured history.

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
* monitoring writer, queue, bus, and script health
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
* maintaining window-local presentation state
* restoring workspace layout from GUI workspace metadata

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
    wire_command_out.raw.jsonl
    operator_action.jsonl
    system_event.jsonl
    writer_stats.json
    complete.json

.ignitionrawbak/
  2026-03-12_ignition_test_01/
    metadata.json
    telemetry_in.raw.jsonl
    wire_command_out.raw.jsonl
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

### Archive Validation and Rebuild

Playback-oriented history should also support validation and optional rebuild support.

Validation should compare the available data in:

* `.ignitionraw`
* `.ignitionrawbak`
* `ignitionhistory`

The goal is to determine whether:

* all sources match
* one or more sources are missing
* sources conflict and require manual inspection

If rebuild support is used, rebuilt artifacts must remain separate from the native archive and must not silently overwrite native files.

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

### 2. wire_command_out (raw) / command_out (structured)

Outbound commands.  Raw/rawbak records wire-level packet facts as
`wire_command_out`.  Structured history records semantic command dispatch
events as `command_out`.

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
* GUI window restarted
* script held
* script continued

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
  -> Backend dispatches command through gateway bus proxy
  -> Gateway records wire_command_out to raw/rawbak
  -> Backend records semantic command_out to structured history
  -> Reducer/state update follows when telemetry confirms change
```

### Abort Flow

```text
Operator presses abort in left or right GUI window
  -> GUI window sends local abort request to AbortRelay
  -> AbortRelay forwards operator_action to backend
  -> AbortRelay forwards abort command_request to backend
  -> Backend validates and dispatches abort
  -> History/state updates follow in backend
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

Must be written through its own dedicated asynchronous writer path and must not block live processing.

### Requirement

Raw and rawbak must not be implemented as one synchronous sequential write call in the GUI path.

Preferred model:

```text
backend
  -> raw_queue        -> raw_writer_process        -> .ignitionraw/<run_id>/
  -> rawbak_queue     -> rawbak_writer_process     -> .ignitionrawbak/<run_id>/
  -> structured_queue -> structured_writer_process -> ignitionhistory/<run_id>/
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
* each GUI window should identify itself independently

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
* `hold_script`
* `continue_script`

#### backend -> GUI

* `hello_ack`
* `run_status`
* `state_snapshot`
* `state_patch`
* `structured_event`
* `system_event`
* `script_status`
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
* GUI client presence
* GUI window health state

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

Abort relay may forward an abort request, but it does not replace backend command authority.

---

## Script Model

Scripts must move under backend control.

Goals:

* GUI does not directly own script execution
* script lifecycle survives GUI restart where appropriate
* backend can capture script-related system events
* safer termination model than in-process GUI execution
* future ability to sandbox or subprocess-isolate scripts
* support a backend-native plan mode
* support hold/continue semantics for plan-mode execution

Plan-mode execution should allow a script to pause between steps without moving command authority into the GUI.

---

## Playback Model

Playback should use `ignitionhistory/<run_id>/...` as the replay-oriented archive.

Expected playback sources:

* `metadata.json`
* per-stream structured jsonl files
* `merged.jsonl`
* `snapshots/`

Playback must not depend on live backend memory state.

Playback should also support:

* archive integrity checking
* mismatch reporting
* optional rebuild-based recovery when sources are missing but not conflicting
* clear distinction between native archive data and rebuilt archive data

---

## GUI Supervision and Workspace Recovery

The GUI side should support a supervisor process that monitors the left and right window processes.

Goals:

* detect frozen or closed GUI windows
* restart a failed GUI window during active recording
* avoid a single GUI failure taking down all visible operator windows
* restore window placement and layout after restart

GUI layout and placement should be stored in a machine-local GUI workspace metadata file.

That metadata should include, at minimum:

* window role
* display/monitor placement
* window position and size
* layout/profile selection
* widget arrangement

If GUI workspace metadata cannot be restored, the GUI should fall back to a safe default layout.

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
* GUI window restarted
* script runner started/stopped/crashed
* script held/continued

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

gui/
  backend_client.py
  checklist_window.py
  controller_window.py
  scada_window.py
  supervisor.py
  abort_relay.py
  window_host.py
```

---

## Definition of Success

This architecture is considered successful when:

1. the backend can continue running if one or both GUI windows exit or crash
2. the backend can continue receiving telemetry without GUI
3. raw/rawbak continue recording independently
4. reducer and state store continue updating without GUI
5. structured events continue being produced without GUI
6. one GUI window can fail without taking the other down
7. GUI can reconnect and recover current live state
8. playback uses replay-oriented history instead of ad hoc live state
9. playback can detect missing/mismatched archive sources
10. abort remains available from either GUI window without moving command authority out of backend

---

## Final Summary

The intended end state is:

* the backend is the runtime core
* the GUI is a restartable supervised client side
* live state belongs to backend
* hardware command dispatch belongs to backend
* history belongs to backend
* playback belongs to `ignitionhistory`
* GUI is an observer/operator surface, not the system body
* one GUI window failure should not collapse the entire operator display surface