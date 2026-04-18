# Future Ideas

Deferred improvements, enhancement opportunities, and architectural cleanups worth considering for future development. These are not current bugs -- see [Known Issues](known-issues.md) for tracked bugs.

## Abort System

### Implement real hardware-side abort behavior

The software abort path currently sets a gateway latch flag and logs the request but does not send hardware stop commands. The gateway code has explicit `TODO(psas-abort-fastpath)` markers for defining what the abort should actually do (e.g., sending an abort CAN packet, forcing safe valve states, running a dedicated abort routine).

This is the single most important safety feature to complete before live teststand operation.

### Abort visual polish

After abort is implemented, the GUI should provide clear visual feedback: a persistent abort banner, disable non-emergency controls, and show latch state. The abort relay architecture already supports this -- the relay is independent from GUI windows and can accept requests even if a window is frozen.

### Clear-abort-latch operator workflow

The clear-abort-latch path exists in code but the full operator workflow (confirmation dialog, state validation, visual feedback) could be refined.

## Recording and Playback

### Periodic snapshots during recording

Currently only two snapshots are taken per run (start and finish). Adding periodic snapshots (e.g., every 30 seconds) would dramatically improve playback seek performance for long recordings, since seeking currently replays all events from the beginning.

### Push/subscribe mechanism for state updates

The GUI polls the backend for state updates (100ms in live mode, 5s in playback mode). An event-driven push mechanism would reduce latency and unnecessary polling traffic. The IPC protocol already supports bidirectional messaging, so this is an architectural refinement rather than a fundamental change.

### Playback graph and SCADA synchronization

During rapid seeking in playback, graphs and SCADA state update independently, which can cause brief visual inconsistencies. A synchronized update mechanism would provide smoother playback scrubbing.

### Large recording memory optimization

Playback loads all events from `merged.jsonl` into memory. For very large recordings, a streaming or windowed approach would reduce RAM usage.

## Operator UX

### Device library population reliability

The live mode device library depends on backend inventory messages arriving over IPC after connection. If the timing is off, the library appears empty. A more robust handshake or retry mechanism would help. See [Known Issues](known-issues.md).

### Checklist hardware detection

The checklist window should detect actual connected hardware state rather than showing dev bypass options by default. This requires better integration between the gateway's hardware discovery and the checklist UI.

### Drag-and-drop workspace stability

The workspace drag-and-drop in the controller window causes crashes. This needs investigation -- likely a Qt object lifecycle or thread-safety issue in the widget hosting code.

## Architecture

### Fix `removeRider` in nexus/bus.py

`removeRider()` calls `rider._setBus(None)` but `_setBus` does not exist on `BusRider`. This is a latent bug that will crash if ever called. Either add `_setBus` to `BusRider` or remove the call.

### Fix DataPacket truncation in nexus/datapacket.py

`_prepare()` uses `self.data[0:5]` (5 elements) when it should use `self.data[0:6]` (6 elements) to match the 6-byte data length limit.

### Writer process resilience

History writer processes run as daemon children and are killed without flushing if the parent exits unexpectedly. Options: use non-daemon processes with explicit shutdown, add a flush-on-signal handler, or use a write-ahead log.

### SCADA SVG bridge robustness

The SCADA window's JavaScript-to-Python bridge for valve click handling is fragile. The bridge path (SVG click -> JS callback -> `scada_bridge.py` -> backend command) has multiple failure points. A more robust command dispatch path would improve reliability.

## Testing

### Expand GUI regression coverage

Several GUI components lack automated tests. Priority areas:
- Workspace drag-and-drop
- SCADA valve click-to-command path
- Device library population after backend connect
- Playback timeline seeking edge cases
- Script panel load/run/stop lifecycle

### Integration test for full session lifecycle

An end-to-end integration test that starts the application, enters live mode (with mock bus), records a run, stops, enters playback, and verifies the recording would catch many regression categories at once.

### Hardware-in-the-loop test harness

For pre-deployment validation, a test mode that uses a real CAN bus adapter with a loopback or simulator device would catch hardware communication regressions.

## Documentation

### Operator walkthrough with screenshots

A visual walkthrough showing the checklist, controller window, and SCADA window would help new operators get oriented.

### Script API reference

A dedicated reference page for the script API (`print`, `wait`, `abort`, `mints.devices`) with examples for common patterns (valve sequencing, timed tests, conditional logic).

## See Also

- [Known Issues](known-issues.md) -- current bugs and limitations
- [Architecture](architecture.md) -- system design context
- [Developer Guide](developer-guide.md) -- codebase orientation
