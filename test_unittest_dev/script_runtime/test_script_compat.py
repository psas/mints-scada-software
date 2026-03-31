from __future__ import annotations

import unittest

from scripts.script_runtime.script_compat import (
    LegacyScriptRuntimeFacade,
    ScriptHostCallbacks,
    UnsupportedLegacyScriptMember,
)


class ScriptCompatTests(unittest.TestCase):
    def test_deprecated_display_members_fail_clearly(self) -> None:
        runtime = LegacyScriptRuntimeFacade(
            device_ids=["eng_purge"],
            callbacks=ScriptHostCallbacks(
                print_callback=lambda *args, **kwargs: None,
                wait_callback=lambda seconds: None,
                abort_callback=lambda *args, **kwargs: None,
                command_callback=lambda **kwargs: None,
            ),
        )

        with self.assertRaises(UnsupportedLegacyScriptMember):
            _ = runtime.mints.graph

        with self.assertRaises(UnsupportedLegacyScriptMember):
            _ = runtime.mints.exporter

        with self.assertRaises(UnsupportedLegacyScriptMember):
            _ = runtime.mints.autopoller


if __name__ == "__main__":
    unittest.main()
