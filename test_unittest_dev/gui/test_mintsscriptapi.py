from __future__ import annotations

import unittest

from gui.mintsscriptapi import MintsScriptAPI
from scripts.script_runtime.script_compat import UnsupportedLegacyScriptMember


class MintsScriptAPITests(unittest.TestCase):
    def test_deprecated_display_members_are_not_exposed(self) -> None:
        api = MintsScriptAPI()

        with self.assertRaises(UnsupportedLegacyScriptMember):
            _ = api.graph

        with self.assertRaises(UnsupportedLegacyScriptMember):
            _ = api.exporter

        with self.assertRaises(UnsupportedLegacyScriptMember):
            _ = api.autopoller


if __name__ == "__main__":
    unittest.main()
