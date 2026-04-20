"""gateway/main.py

Gateway process entrypoint.

This module preserves ``python -m gateway.main`` style launching by delegating
directly to ``gateway.app.main`` and exiting with the returned process status
code.
"""

from .app import main

if __name__ == "__main__":
    raise SystemExit(main())
