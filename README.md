# MINTS SCADA Software

Control and monitoring software for the Portland State Aerospace Society (PSAS) rocket teststand. Built with Python 3.12, PyQt5, and CAN bus hardware communication.

MINTS SCADA runs a persistent backend service that owns all hardware communication, state, and data recording. The GUI connects as a restartable client -- if the GUI crashes, the backend keeps running and recording.

## First-Time Setup

### Linux

```bash
git clone https://github.com/psas/mints-scada-software.git
cd mints-scada-software
make setup
```

### WSL (Windows Subsystem for Linux)

```bash
git clone https://github.com/psas/mints-scada-software.git
cd mints-scada-software
make setup
make wsl-usb    # Configure USB device forwarding from Windows to WSL
```

`make setup` checks system dependencies, creates a Python virtual environment in `.venv/`, and installs all Python dependencies. If any OS-level packages are missing, the setup will list them and ask for confirmation before installing. You do not need to activate the virtual environment manually -- `make run` handles activation internally.

`make wsl-usb` installs USB/serial tools and walks you through forwarding a USB device from the Windows host into WSL. This requires `usbipd-win` on the Windows side. Only needed if you are connecting CAN bus hardware through WSL.

## Normal Run

### Linux

```bash
make run
```

### WSL

```bash
make wsl-usb
make run
```

If USB forwarding was set up previously, the CAN bus device should already be available. If the serial port is not detected at startup, re-run `make wsl-usb` to re-attach the device.

### What Happens

`make run` starts the GUI launcher, which shows a startup checklist. From the checklist, choose:

- **Live mode** -- connect to real hardware, send commands, record data
- **Playback mode** -- review a previously recorded test run (no hardware needed)

After selection, the system opens two operator windows:

- **Controller window** (left) -- device controls, graphs, console, scripts, recording
- **SCADA window** (right) -- P&ID schematic with interactive valve state visualization

### Stopping

- Close the **SCADA window** (right window) to trigger a full shutdown
- Or run `make stop` from the terminal
- Or press Ctrl+C in the terminal where `make run` is running

## Common Workflows

| Task | How |
|------|-----|
| Start the system | `make run` |
| Stop everything | `make stop` or close the SCADA window |
| Check what is running | `make status` |
| Run a live test | `make run` -> checklist -> live mode -> start recording -> run test -> stop recording |
| Review a past test | `make run` -> checklist -> playback mode -> select a run |
| Run a script | Load a script file in the controller window script panel |

## Repository Layout

```
backend/            Backend service (system of record)
bootstrap/          Setup and launch scripts (system deps, venv, WSL USB)
gateway/            CAN bus gateway service (raw data capture)
gui/                PyQt5 GUI client (operator interface)
historymanager/     Recording, archive validation, and rebuild
nexus/              CAN bus abstraction layer
electricaldevices/  Concrete sensor and actuator implementations
scripts/            User scripts and script runtime
settings.py         Device catalog and hardware configuration
src/                SVG assets for P&ID schematic
docs/               Detailed documentation
test_unittest_dev/  Development test suite
```

## Documentation

See the [documentation index](docs/index.md) for a full listing.

| Document | Description |
|----------|-------------|
| [Getting Started](docs/getting-started.md) | Detailed setup and first run walkthrough |
| [Architecture](docs/architecture.md) | System design, process model, data flow |
| [Live Mode](docs/live-mode.md) | Operating the system with real hardware |
| [Playback](docs/playback.md) | Reviewing recorded test runs |
| [Scripts](docs/scripts.md) | Writing and running automation scripts |
| [History Format](docs/history-format.md) | Recording archives and data format |
| [Troubleshooting](docs/troubleshooting.md) | Common problems and fixes |
| [Developer Guide](docs/developer-guide.md) | Codebase orientation for contributors |
| [Testing](docs/testing.md) | Running and writing tests |
| [Known Issues](docs/known-issues.md) | Tracked bugs and limitations |
| [Future Ideas](docs/future-ideas.md) | Deferred improvements and enhancement opportunities |

## Safety Notes

**Physical E-stop is the primary emergency stop.** In an actual emergency, use the physical E-stop button. Do not rely on software controls for emergency shutdown.

The GUI abort button is a software-level stop path. It is currently a placeholder that logs the abort request and records it as a system event. It does **not** send hardware stop commands to devices. The abort relay and backend accept and record the request, but the actual hardware-side abort behavior is not yet implemented.

Additional safety notes:

- All hardware commands flow through the backend's command router, which enforces validation and safety interlocks. The GUI never talks to hardware directly.
- Scripts execute in the backend, not in the GUI. They survive GUI restarts.
- **Scripts are not sandboxed.** Only run scripts you trust. See [Scripts](docs/scripts.md) for details.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `make run` says virtual environment not found | Run `make setup` first |
| No serial ports detected (WSL) | Run `make wsl-usb` to set up USB forwarding |
| GUI won't start | Check `make status` to see if processes are running. Try `make stop` then `make run` |
| Stale socket files after crash | Run `make stop` to clean up, then `make run` |
| Not sure what is missing | Run `make doctor` to diagnose setup issues |

See [Troubleshooting](docs/troubleshooting.md) for more.

## License

GNU General Public License v3. See [LICENSE](LICENSE).
