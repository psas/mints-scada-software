# MINTS SCADA Documentation

Documentation for the MINTS SCADA teststand control and monitoring software, built by the Portland State Aerospace Society (PSAS).

## For Operators

- [Getting Started](getting-started.md) -- Setup, installation, and first run
- [Live Mode](live-mode.md) -- Operating the system with real hardware
- [Playback](playback.md) -- Reviewing recorded test runs
- [Scripts](scripts.md) -- Writing and running automation scripts
- [Troubleshooting](troubleshooting.md) -- Common problems and fixes

## For Developers

- [Architecture](architecture.md) -- System design, process model, data flow
- [Developer Guide](developer-guide.md) -- Codebase orientation and conventions
- [History Format](history-format.md) -- Recording archive structure and data format
- [Testing](testing.md) -- Running and writing tests

## Project Status

- [Known Issues](known-issues.md) -- Tracked bugs and limitations
- [Future Ideas](future-ideas.md) -- Deferred improvements and enhancement opportunities

## Quick Reference

| Command | Description |
|---------|-------------|
| `make setup` | Create virtual environment, install dependencies |
| `make wsl-usb` | Configure USB forwarding (WSL only) |
| `make run` | Start the application |
| `make stop` | Stop all running processes |
| `make status` | Show application status |
| `make doctor` | Check environment health |

See the [top-level README](../README.md) for a quick overview.
