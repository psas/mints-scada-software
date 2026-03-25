# test_unittest_dev

This folder contains temporary `unittest`-based development tests for the
backend-first migration work in `feature/backend-service-core`.

Why this folder exists:

- keep all development tests in one place
- make it easy to run everything together
- make it easy to delete later with one command
- keep the comments readable enough for a public GitHub branch

## How to run everything

From the repository root:

```bash
python -m unittest discover -s test_unittest_dev -t . -p "test_*.py" -v
```

## Suggested cleanup later

When the codebase is stable and you no longer want this temporary package:

```bash
rm -rf test_unittest_dev
```

## Notes

- GUI tests try to use `QT_QPA_PLATFORM=offscreen` so they can run without a
  visible desktop session.
- Several tests use fakes and mocks instead of real CAN hardware or real GUI
  supervision processes.
- These tests are meant to validate architecture behavior and regression safety,
  not only tiny implementation details.
