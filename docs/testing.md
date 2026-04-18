# Testing

This page covers how to run and write tests for the MINTS SCADA codebase.

## Running Tests

### Run All Tests

From the repository root, with the virtual environment active:

```bash
python -m unittest discover -s test_unittest_dev -t . -p "test_*.py" -v
```

The Makefile targets handle venv activation internally, but `python -m unittest` must be run from an activated venv or via the venv's Python directly.

### Run a Single Test File

```bash
python -m unittest test_unittest_dev.backend.test_state_store_run_and_clocks -v
```

### Run a Single Test Method

```bash
python -m unittest test_unittest_dev.backend.test_state_store_run_and_clocks.TestClassName.test_method -v
```

### GUI Tests

GUI tests require `QT_QPA_PLATFORM=offscreen` to run without a visible desktop. This is set automatically by the test helpers, so you do not need to set it manually.

## Test Directory Structure

Tests live under `test_unittest_dev/`:

```
test_unittest_dev/
  conftest.py                           Shared pytest configuration and fixtures
  run_all_unittest_dev.sh               Shell script to run all tests
  helpers/                              Test utilities and fakes
  backend/                              Backend module tests
  bootstrap/                            Bootstrap/Makefile smoke tests
  gateway/                              Gateway tests
  gui/                                  GUI component tests
  gui_regression/                       GUI regression tests
  historymanager/                       History subsystem tests
  integration/                          Cross-module integration tests
  live_real_system/                     Tests requiring real hardware
  playback_regression/                  Playback regression tests
  process_lifecycle/                    Process lifecycle tests
  script_runtime/                       Script runtime tests
```

### Backend Tests (`test_unittest_dev/backend/`)

| Test File | Coverage |
|-----------|----------|
| `test_bus_manager_idempotent_init.py` | Bus manager idempotent initialization |
| `test_command_router_dispatch.py` | Command dispatch: dry run, valve, abort |
| `test_command_router_guards.py` | Guard rejections: authority, playback, mode |
| `test_command_router_xv_positive_path.py` | Valve command positive path |
| `test_gateway_bus_proxy.py` | Gateway bus proxy behavior |
| `test_gateway_bus_proxy_ack_behavior.py` | Gateway bus proxy acknowledgement |
| `test_gateway_hardware_status_sync.py` | Hardware status sync |
| `test_gateway_live_registration_inventory.py` | Live registration inventory |
| `test_gateway_proxy_calls_gateway_client.py` | Gateway proxy -> client calls |
| `test_gateway_proxy_runtime_bus_binding.py` | Gateway proxy runtime bus binding |
| `test_live_device_inventory_backend.py` | Live device inventory |
| `test_live_registration_actual_settings.py` | Registration against actual settings.py |
| `test_live_runtime_actual_devices.py` | Actual device runtime behavior |
| `test_periodic_snapshot_non_telemetry.py` | Non-telemetry snapshot behavior |
| `test_playback_seek_boundary.py` | Playback seek edge cases |
| `test_router_after_actual_registration.py` | Router after device registration |
| `test_run_controller_lifecycle.py` | Run start, finish, integrity |
| `test_run_controller_playback_hardening.py` | Playback mode run controller edge cases |
| `test_script_runner_hold_continue.py` | Script hold/continue round trips |
| `test_script_runner_plan_mode.py` | Plan mode steps: wait_state, stop |
| `test_service_abort_command.py` | Service-level abort command handling |
| `test_settings_solenoid_addresses.py` | Settings solenoid address validation |
| `test_state_store_abort.py` | State store abort state management |
| `test_state_store_gui_and_script.py` | GUI sessions, script lifecycle |
| `test_state_store_health_and_backend_status.py` | Bus state, health snapshots |
| `test_state_store_run_and_clocks.py` | Run lifecycle, clocks, snapshots |
| `test_telemetry_identity_helpers.py` | Telemetry identity helpers |
| `test_actual_solenoid_runtime_bus_send.py` | Solenoid runtime bus send |

### Gateway Tests (`test_unittest_dev/gateway/`)

| Test File | Coverage |
|-----------|----------|
| `test_gateway_abort_latch.py` | Abort latch behavior |
| `test_gateway_clear_abort_latch.py` | Clear abort latch |
| `test_gateway_initialize_live_hardware_emits_hardware_status.py` | Hardware status on init |
| `test_hardware_status_message_accepts_gateway_fields.py` | Hardware status message fields |

### GUI Tests (`test_unittest_dev/gui/`)

| Test File | Coverage |
|-----------|----------|
| `test_abort_relay_clear_latch.py` | Abort relay clear latch |
| `test_abort_relay_gateway_path.py` | Abort relay gateway path |
| `test_checklist_window_live_setup.py` | Live setup validation |
| `test_checklist_window_playback_selection.py` | Playback run selection |
| `test_controller_badges.py` | Controller window status badges |
| `test_controller_finish_run_button.py` | Finish run button behavior |
| `test_controller_recording_clock.py` | Recording clock display |
| `test_controller_window_live_poller.py` | Live telemetry poller integration |
| `test_graph_data.py` | Graph data model |
| `test_graph_provider.py` | Graph provider |
| `test_graph_view_live_provider.py` | Live graph view provider |
| `test_graph_view_playback_provider.py` | Playback graph view provider |
| `test_live_device_library_bridge.py` | Device library bridge |
| `test_live_device_library_panel.py` | Device library panel |
| `test_live_graph_provider.py` | Live graph provider |
| `test_live_telemetry_poller.py` | Live telemetry poller |
| `test_mintsscriptapi.py` | MintsScriptAPI |
| `test_playback_catalog.py` | Playback catalog |
| `test_playback_export.py` | Playback data export |
| `test_playback_graph_provider.py` | Playback graph provider |
| `test_playback_state_manager.py` | Playback state manager |
| `test_scada_abort_button_wiring.py` | SCADA abort button wiring |
| `test_scada_xv_live_registration.py` | SCADA valve live registration |
| `test_script_view_backend_runtime.py` | Script view backend runtime |

### History Manager Tests (`test_unittest_dev/historymanager/`)

| Test File | Coverage |
|-----------|----------|
| `test_integrity_report_write.py` | Integrity report writing |
| `test_integrity_scan.py` | Cross-archive integrity scan |
| `test_merged_sort_order.py` | Merged timeline sort order |
| `test_stream_split.py` | Stream splitting |

### Integration Tests (`test_unittest_dev/integration/`)

| Test File | Coverage |
|-----------|----------|
| `test_backend_first_contracts.py` | Backend-first architectural contracts |
| `test_run_controller_and_catalog_flow.py` | Run controller and catalog flow |

### Script Runtime Tests (`test_unittest_dev/script_runtime/`)

| Test File | Coverage |
|-----------|----------|
| `test_abort_command.py` | Abort command dispatch metadata |
| `test_abort_relay.py` | Abort relay unit tests |
| `test_script_compat.py` | Script compatibility |
| `test_script_contract.py` | Script contract validation |
| `test_script_exit_status.py` | Script exit status handling |
| `test_script_host_protocol.py` | Script host protocol |
| `test_script_host_proxy.py` | Script host proxy |
| `test_script_runner_legacy_host.py` | Legacy script host runner |

### GUI Regression Tests (`test_unittest_dev/gui_regression/`)

| Test File | Coverage |
|-----------|----------|
| `test_run_script_button.py` | Run script button regression |
| `test_workspace_drag_drop.py` | Workspace drag-and-drop regression |

### Playback Regression Tests (`test_unittest_dev/playback_regression/`)

| Test File | Coverage |
|-----------|----------|
| `test_playback_live_log_isolation.py` | Playback/live log isolation |
| `test_playback_seek_advance_equivalence.py` | Seek/advance equivalence |

### Process Lifecycle Tests (`test_unittest_dev/process_lifecycle/`)

| Test File | Coverage |
|-----------|----------|
| `test_controller_close_linkage.py` | Controller window close linkage |
| `test_recording_respawn_state.py` | Recording respawn state handling |

### Live/Real System Tests (`test_unittest_dev/live_real_system/`)

| Test File | Coverage |
|-----------|----------|
| `test_live_abort_command.py` | Live abort command |
| `test_live_checklist_real_system.py` | Checklist with real hardware |
| `test_live_device_inventory.py` | Live device inventory |
| `test_live_scada_wire_equivalence.py` | SCADA wire-level equivalence |

### Bootstrap Tests (`test_unittest_dev/bootstrap/`)

| Test File | Coverage |
|-----------|----------|
| `test_makefile_smoke.py` | Makefile smoke tests |

## Test Helpers

### Shared Configuration (`conftest.py`)

The `conftest.py` at the test root provides pytest fixtures and options for live/real-system testing:

- `lab_config` fixture: configurable test parameters (run command, timeouts, device IDs)
- `app_session` fixture: manages application lifecycle for integration tests
- `artifact_recorder` fixture: captures test artifacts

Pytest markers defined:
- `@pytest.mark.hardware` -- requires real hardware or bench setup
- `@pytest.mark.live` -- requires live mode
- `@pytest.mark.manual` -- operator-assisted validation
- `@pytest.mark.process` -- process lifecycle or multi-window regression
- `@pytest.mark.backend` -- backend unit tests
- `@pytest.mark.playback` -- playback-only regression
- `@pytest.mark.gui` -- GUI interaction regression

### Fakes (`test_unittest_dev/helpers/`)

The test suite provides helper utilities for isolating components during testing. These include fake implementations of backend components that can substitute for real subsystems in unit tests.

## Writing New Tests

### Test File Naming

Place tests in the appropriate subdirectory under `test_unittest_dev/` and name them `test_*.py`.

### Test Structure

Tests use the standard `unittest` module:

```python
import unittest

class TestMyFeature(unittest.TestCase):
    def setUp(self):
        # setup code
        pass

    def test_something(self):
        # test code
        self.assertEqual(expected, actual)
```

### Testing GUI Components

GUI tests need the offscreen platform:

```python
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
```

### Tips

- Use fakes and mocks instead of real CAN hardware or real GUI processes
- Avoid `time.sleep` in tests -- use polling helpers with timeouts instead
- Test architectural behaviors and contracts, not just getters/setters
- The `conftest.py` fixtures are designed for integration/regression tests and may not be needed for unit tests

## See Also

- [Developer Guide](developer-guide.md) -- codebase orientation
- [Architecture](architecture.md) -- system design context
