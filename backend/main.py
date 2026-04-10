# backend/main.py

"""Backend process entrypoint.

This module preserves the ``python -m backend.main`` entry path by delegating to
``backend.app.main`` and exiting with its returned process status code.
"""

from .app import main

if __name__ == "__main__":
    raise SystemExit(main())
