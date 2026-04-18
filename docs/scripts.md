# Scripts

MINTS SCADA supports user-provided automation scripts for test sequences. Scripts are executed by the backend service, not by the GUI.

## Running a Script

1. Start a live session (`make run` -> live mode)
2. In the controller window, open the script panel
3. Load a script file
4. Click **Run Script**

Scripts can also be started via the backend IPC protocol (`start_script` message).

## Script Location

- **Script runtime helpers**: `scripts/script_runtime/` -- shared compatibility and runtime code used by GUI, backend, and script host
- **User script files**: `scripts/script_sources/` -- default, example, and legacy scripts

The default script directory is `scripts/script_sources/` (defined in `scripts/script_runtime/script_contract.py`).

Example scripts included in the repository:

| File | Description |
|------|-------------|
| `script_example_actually_runnable.py` | Example showing basic script API usage |
| `script_blink.py` | Simple device toggle script |
| `pre_chill.py` | Pre-chill test sequence |
| `static_fire.py` | Static fire test sequence |
| `dummy-mints.py` | Development CAN bus simulator |

## Script API

Inside a script, you have access to these built-in names:

| Name | Description |
|------|-------------|
| `print(message)` | Print to the console. Overrides the default Python `print` so messages appear in the GUI console. Only accepts a single argument -- use f-strings to combine values. |
| `wait(seconds)` | Wait for the given number of seconds. Use this instead of `time.sleep` because it is interruptible by abort. |
| `abort(message=None)` | Trigger an abort request. An optional message can be provided. |
| `mints` | A `MintsScriptAPI` object that provides access to the system. |
| `mints.devices` | Dictionary of `device_id` -> `BusRider` containing all devices from `settings.py`. |

### Stable Long-Term API

These are the stable API functions maintained across versions (defined in `script_contract.py` as `SUPPORTED_SCRIPT_GLOBALS` and `SUPPORTED_MINTS_MEMBERS`):

- `print(...)`
- `wait(seconds)`
- `abort(message=None)`
- `mints.devices["device-id"]`

### Legacy API (Do Not Use in New Scripts)

These attributes exist because older scripts ran inside the GUI process. They are deprecated and not part of the long-term subprocess-based script contract:

- `mints.graph` -- GUI graph view reference
- `mints.exporter` -- CSV export reference
- `mints.autopoller` -- autopoller reference

## Launch Modes

The script runner (`backend/script_runner.py`) supports three launch modes:

1. **Subprocess execution** -- runs the script as a child process with explicit command payloads
2. **Legacy inline execution** -- runs the script through `script_host.py` and `ScriptHostProxy` (compatibility path for older scripts)
3. **Plan-mode execution** -- runs normalized plan steps on a backend worker thread

## Plan Mode

Scripts can run in **plan mode**, where execution pauses between steps and waits for operator confirmation before continuing. Plan mode is managed by the backend's script runner.

Plan mode supports:
- **Hold**: Pause execution at the current step
- **Continue**: Resume execution after a hold
- Step types include `sleep`, `command`, `wait_state`, `note`

Plan mode allows an operator to review each step before it executes, which is useful for safety-critical test sequences.

## Exception Handling

You can use exception handling in your scripts. However, if you catch a `PleaseStopNowException`, you **must** stop execution and/or re-raise it. This exception is used by the abort system to terminate scripts.

`PleaseStopNowException` is **not** a subclass of `Exception`, so a bare `except Exception:` will not accidentally catch it.

```python
try:
    # your code here
    wait(5)
except Exception:
    # this will NOT catch PleaseStopNowException
    print("Something went wrong")
```

If you need to catch everything, re-raise `PleaseStopNowException`:

```python
try:
    # your code here
except PleaseStopNowException:
    raise  # always re-raise this
except Exception:
    print("Something went wrong")
```

## Safety Warnings

**Scripts are not sandboxed.** Scripts run with full access to the Python environment and the system. Only run scripts you trust.

**Scripts can control real hardware.** Any command sent through `mints.devices` or `abort()` will be dispatched to real hardware during a live session. Double-check your scripts before running them on a live teststand.

**Scripts execute in the backend, not the GUI.** This means scripts survive GUI restarts. If a script is running and the GUI crashes, the script keeps running in the backend.

**The physical E-stop is the primary emergency stop.** The `abort()` function in scripts triggers the same software abort path as the GUI abort button. This is currently a placeholder that logs the request. In a real emergency, use the physical E-stop.

## Writing a New Script

A minimal script:

```python
print("Starting test sequence")

# Access a device by its settings.py ID
valve = mints.devices["sv-001"]

# Open the valve
valve.runtime.open()
print("Valve opened")

# Wait 5 seconds
wait(5)

# Close the valve
valve.runtime.close()
print("Valve closed")

print("Test sequence complete")
```

Tips:
- Use `wait()` instead of `time.sleep()` so aborts can interrupt your script
- Use `print()` for console output (only one argument, use f-strings)
- Check `mints.devices` keys against the device IDs in `settings.py`
- Test scripts in a safe configuration before running on a live teststand
- Place new scripts in `scripts/script_sources/`

## See Also

- [Live Mode](live-mode.md) -- operating the system with real hardware
- [Developer Guide](developer-guide.md) -- codebase orientation
- [Architecture](architecture.md) -- system design context
