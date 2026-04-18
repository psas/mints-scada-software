# Troubleshooting

Common problems and how to fix them.

**Quick check:** Run `make doctor` to diagnose environment issues before troubleshooting manually.

## Startup Issues

### "Virtual environment not found"

```
[ERROR] Virtual environment not found. Run 'make setup' first.
```

Run `make setup` to create the virtual environment and install dependencies. You only need to do this once.

### No serial ports detected

During `make run`, the startup output shows:

```
=== Serial Ports ===
  (none detected)
```

**On WSL**: Run `make wsl-usb` to configure USB forwarding from the Windows host. After forwarding, the serial device should appear as `/dev/ttyUSB0` or `/dev/ttyACM0`.

**On native Linux**: Make sure the CAN bus adapter is physically connected. Check `ls /dev/ttyUSB* /dev/ttyACM*` to see available ports.

Serial ports are not required for playback mode.

### Gateway or backend fails to start

If `make run` hangs or reports a service not becoming ready:

1. Run `make stop` to clean up any leftover processes
2. Run `make status` to check what is still running
3. Try `make run` again

The launcher waits up to 10 seconds for each service socket to become connectable (defined as `_SERVICE_SOCKET_TIMEOUT_S` in `main.py`). If a service does not start in time, the launcher reports an error.

If the problem persists, check for stale socket files:
```bash
ls -la .backend_service.sock .gateway_service.sock 2>/dev/null
```

If these exist but no processes are running, `make stop` will clean them up.

### Checklist shows "dev bypass" instead of real hardware

The checklist window may show development/bypass options even when hardware is connected. This is a known issue -- the checklist may not detect live hardware state correctly at startup time. See [Known Issues](known-issues.md).

## Runtime Issues

### GUI window crashes and respawns

During a recording, if a GUI window crashes, the supervisor will automatically restart it. This is expected behavior. The recording continues in the backend.

If the window keeps crashing in a loop, check `log/debug.log` for error details.

### "Backend did not accept the abort request"

This popup appears when the abort command fails to reach or be accepted by the backend. Possible causes:

- The abort relay could not connect to the gateway socket
- The gateway process may have stopped
- IPC connection issue between abort relay and gateway

Check `make status` to verify services are alive.

### Commands rejected by backend

The command router can reject commands for several reasons:

| Rejection | Meaning |
|-----------|---------|
| Authority | Command requires higher authority than the request source |
| Playback mode | Commands are disabled in playback mode |
| Finishing run | Commands blocked while a run is being finalized |
| Unknown device | Device ID not found in the registry |
| Not controllable | Device is not marked as controllable in `settings.py` |
| Bus reconnecting | CAN bus is disconnecting/reconnecting |
| Stale telemetry | Device telemetry is too old (possible hardware issue) |

### No devices in live mode device library

The device library in the controller window may appear empty in live mode. This is a known issue related to how device inventory is communicated from the backend to the GUI after connection. See [Known Issues](known-issues.md).

### Valve clicks on SCADA page do not work

The SCADA P&ID valve click path may not be sending commands successfully. This is a known issue. See [Known Issues](known-issues.md).

## Shutdown Issues

### Controller window close behavior

Closing the controller window (left) during a recording will cause the supervisor to respawn it (this is by design -- the recording continues). When not recording, closing either window triggers a full shutdown of both windows.

If you close the controller window during recording, the supervisor will respawn it.

### Processes left running after crash

If the application crashes without a clean shutdown, processes may be left running. Run:

```bash
make stop
```

This reads `.applicationpid` and service PID files, sends SIGTERM to all tracked processes, waits, then sends SIGKILL to any survivors. It also removes PID files and socket files.

If `make stop` does not work, check for leftover processes manually:

```bash
ps aux | grep -E "(backend|gateway|supervisor|window_host|abort_relay|shutdown_watcher)" | grep -v grep
```

### Stale PID or socket files

After a crash, you may see stale `.applicationpid`, `.dev/backend.pid`, `.dev/gateway.pid`, or socket files. Running `make stop` cleans these up. For a minimal cleanup of just runtime artifacts (PID files, sockets) without touching history:

```bash
make _clean-dev
```

## History / Recording Issues

### Recording not working

If recording appears to start but no data appears in the history directories:

1. Check `make status` -- verify backend and gateway are alive
2. Check `log/debug.log` for writer errors
3. Verify the history directories exist: `ls .ignitionraw .ignitionrawbak ignitionhistory`

### Corrupt or incomplete run

If a run was interrupted (crash, power loss), the archive may be incomplete. Look for:
- Missing `complete.json` (indicates the run was not cleanly finished)
- Writer stats with error counts in `writer_stats.json`

The integrity scanner can identify issues, and the rebuild tool can attempt reconstruction from available archive sources.

### Clearing history data

To clear all recording history:

```bash
make clean-history
```

To do a full cleanup including all development metadata:

```bash
make clean
```

Both commands ask for confirmation before deleting. Set `MINTS_FORCE=1` to skip:

```bash
MINTS_FORCE=1 make clean-history
```

## Development Commands

These commands are not shown in `make help`:

| Command | Description |
|---------|-------------|
| `make _clean-dev` | Remove only runtime artifacts (PID/socket files) |

## See Also

- [Known Issues](known-issues.md) -- tracked bugs and limitations
- [Getting Started](getting-started.md) -- setup and first run
