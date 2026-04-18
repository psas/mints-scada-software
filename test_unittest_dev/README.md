# test_unittest_dev

Development and regression test suite for the MINTS SCADA codebase.

## How to run everything

From the repository root:

```bash
python -m unittest discover -s test_unittest_dev -t . -p "test_*.py" -v
```

Run a single test file:

```bash
python -m unittest test_unittest_dev.backend.test_state_store_run_and_clocks -v
```

Run a single test method:

```bash
python -m unittest test_unittest_dev.backend.test_state_store_run_and_clocks.TestClassName.test_method -v
```

## Structure

```
backend/              Backend module tests (state store, command router, run controller, etc.)
bootstrap/            Bootstrap/Makefile smoke tests
gateway/              Gateway service tests
gui/                  GUI component unit tests
gui_regression/       GUI regression tests (drag-drop, script button)
historymanager/       History recording and integrity tests
integration/          Cross-module integration tests
live_real_system/     Tests requiring real CAN bus hardware
playback_regression/  Playback regression tests
process_lifecycle/    Process lifecycle tests (window close, respawn)
script_runtime/       Script runtime and abort tests
helpers/              Shared test utilities and fakes
```

## Notes

- GUI tests use `QT_QPA_PLATFORM=offscreen` so they can run without a visible desktop session (set automatically by test helpers).
- Several tests use fakes and mocks instead of real CAN hardware or real GUI supervision processes.
- Tests in `live_real_system/` use `pytestmark` with `pytest.mark.hardware` and `pytest.mark.live`. These require real CAN bus hardware and are only run via pytest with `-m hardware` or `-m live` -- they are not discovered by `python -m unittest discover`.
- See [docs/testing.md](../docs/testing.md) for full documentation.
