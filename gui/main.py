"""GUI-only entrypoint — delegates to the application launcher.

This module exists so that ``python -m gui.main`` and ``make run-gui``
continue to work.  The full launcher logic lives in the project-root
``main`` module.
"""
import sys


def main() -> int:
    from main import main as _app_main
    return _app_main()


if __name__ == "__main__":
    raise SystemExit(main())
