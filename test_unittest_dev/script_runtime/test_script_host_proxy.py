from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.script_runtime.script_proxy import ScriptHostProxy


class ScriptHostProxyTests(unittest.TestCase):
    def test_proxy_can_start_ping_and_shutdown_host(self) -> None:
        project_root = Path(__file__).resolve().parents[2]
        proxy = ScriptHostProxy(project_root=project_root)

        ready = proxy.start(script_path="scripts/script_sources/script.py", cwd=str(project_root))
        self.assertEqual(ready["type"], "host_ready")
        self.assertTrue(ready["payload"]["pid"] > 0)

        pong = proxy.ping()
        self.assertEqual(pong["type"], "pong")
        self.assertTrue(pong["payload"]["ok"])

        shutdown_ack = proxy.shutdown()
        self.assertEqual(shutdown_ack["type"], "shutdown_ack")
        self.assertTrue(shutdown_ack["payload"]["ok"])


if __name__ == "__main__":
    unittest.main()
