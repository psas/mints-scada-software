# Live Mode

Live mode connects to real CAN bus hardware for teststand operation. This page covers what operators need to know.

## Important: Physical E-Stop

**The physical E-stop button is the primary emergency stop mechanism.** In an actual emergency, press the physical E-stop on the teststand. Do not rely on the software abort button for emergency shutdown.

The GUI abort button is a software-level stop path. It is currently a placeholder -- see [Abort](#abort) below.

## Starting a Live Session

1. Run `make run`
2. In the startup checklist, select **Live mode**
3. Fill in the required test metadata (test name, operator info)
4. Click **Continue**

The launcher will:
- Start the gateway (connects to CAN bus hardware)
- Start the backend (connects to gateway, begins processing telemetry)
- Start the abort relay (independent abort forwarding process)
- Open two operator windows via the supervisor

### Serial Port Detection

During startup, the system checks for available serial ports (`/dev/ttyUSB*`, `/dev/ttyACM*`). If no ports are found:
- On WSL: Run `make wsl-usb` to configure USB forwarding
- On native Linux: Make sure the CAN bus adapter is physically connected

## Operator Windows

### Controller Window (Left)

The controller window provides:
- **Device workspace** -- drag devices from the library to the workspace for monitoring
- **Graphs** -- live telemetry plotting
- **Console** -- log output and system events
- **Script panel** -- load and run automation scripts
- **Recording controls** -- start and stop recording

### SCADA Window (Right)

The SCADA window shows:
- **P&ID schematic** -- interactive SVG diagram of the teststand
- **Valve states** -- color-coded valve positions (open/closed)
- **Valve controls** -- click valves on the schematic to send commands

## Recording

### Start Recording

Press the **Start Recording** button in the controller window. The backend will:
- Create a new run with a timestamped ID
- Create archive directories under `.ignitionraw/`, `.ignitionrawbak/`, and `ignitionhistory/`
- Start raw, rawbak, and structured writer processes
- Record an initial state snapshot
- Begin capturing all events

### Stop Recording

Press the **Stop Recording** button. The backend will:
- Write a final state snapshot
- Drain all writer queues
- Write completion markers (`complete.json`)
- Run an integrity scan on the archives

### What Gets Recorded

During a recording run, four event streams are captured:

| Stream | Content |
|--------|---------|
| `telemetry_in` | All sensor readings from the CAN bus |
| `command_out` (structured) / `wire_command_out` (raw) | Commands sent to devices |
| `operator_action` | Button presses, mode changes, operator interactions |
| `system_event` | Backend lifecycle events, health transitions, bus status changes |

These are written to three archive locations for redundancy. See [History Format](history-format.md) for details.

## Sending Commands

Commands are sent by:
- Clicking a valve on the SCADA P&ID schematic
- Using controls in the controller window device workspace
- Running a script

All commands go through the backend's command router, which checks:
1. Authority level
2. Mode (must be live, not playback)
3. Run status (not blocked during run finalization)
4. Device existence and controllability
5. Safety interlocks (bus connected, not reconnecting, telemetry not stale)

If any check fails, the command is rejected and the GUI shows the rejection reason.

## Abort

The **Abort** button appears in both GUI windows during live mode.

Pressing Abort:
- Sends an abort request through the abort relay (a separate process independent from the GUI windows)
- The abort relay forwards the request to the gateway
- The gateway sets an internal abort latch flag and logs the request
- The backend records the abort as an operator action and system event

**Current limitation:** The abort implementation is a placeholder. It records the abort request and sets a latch flag, but does **not** currently send hardware stop commands to devices. The gateway code contains explicit TODO markers for defining real hardware-side abort behavior. The abort latch message displayed by the gateway reinforces using the physical E-stop.

The abort relay is architecturally independent from the GUI windows. It runs as its own process and communicates with the gateway over its own socket, so it can accept abort requests even if a GUI window is frozen or crashed.

### Clear Abort Latch

After an abort, the system enters a latched state. The abort relay also supports a "clear abort latch" operation that resets the latch flag and reinitializes gateway runtime state.

## Window Crash Recovery

If a GUI window crashes **during recording**:
- The supervisor detects the exit (polling at 250ms intervals)
- The crashed window is automatically respawned
- Recording continues uninterrupted in the backend
- The respawned window reconnects and receives current state

If a GUI window crashes **when not recording**:
- The supervisor shuts down the remaining window and the session ends

## Backend Independence

The backend service continues running independently of the GUI:
- Telemetry continues being received and processed
- Recording continues writing to all archives
- Scripts continue executing
- State is preserved

When the GUI reconnects (after crash or restart), it requests a full state snapshot from the backend and resumes display from the current state.

## See Also

- [Playback](playback.md) -- reviewing recorded test runs
- [Scripts](scripts.md) -- writing and running automation scripts
- [Troubleshooting](troubleshooting.md) -- common problems and fixes
- [Architecture](architecture.md) -- system design context
