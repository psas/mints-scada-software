# gui/main.py

"""GUI compatibility entrypoint that delegates startup to the root launcher.

This module preserves ``python -m gui.main`` and ``make run-gui`` as stable
entrypoints while keeping the real session orchestration in the project-root
``main`` module.
"""

import sys


def main() -> int:
    """Run the project-root application launcher through the GUI entrypoint.

    Returns:
        The process exit code returned by the root ``main`` launcher.
    """
    from main import main as _app_main

    return _app_main()


if __name__ == "__main__":
    raise SystemExit(main())
