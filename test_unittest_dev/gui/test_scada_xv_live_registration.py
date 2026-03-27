from __future__ import annotations

import types
import unittest
from types import SimpleNamespace

from test_unittest_dev.helpers.repo_test_tools import import_module_or_skip

scada_module = import_module_or_skip("gui.scada_window")
ScadaWindow = scada_module.ScadaWindow


class _FakeCatalog:
    def __init__(self, proxies: dict[str, object] | None = None):
        self._proxies = dict(proxies or {})

    def get_proxy(self, device_id: str):
        return self._proxies.get(device_id)


def _bind_method(fake_obj, name: str) -> None:
    method = getattr(ScadaWindow, name)
    setattr(fake_obj, name, types.MethodType(method, fake_obj))


def _make_scada_like_self():
    calls: list[tuple[tuple, dict]] = []

    fake = SimpleNamespace(
        playback_mode=False,
        xv_states={
            "ig-xv-24": "closed",
            "ig-xv-27": "closed",
        },
        pending_xv_commands={},
        backend_device_catalog=None,
        backend_device_presentation=None,
        request_backend_command=lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    for name in (
        "_normalize_state",
        "_state_to_command_name",
        "_command_name_to_state",
        "_resolve_backend_device_id",
        "_resolve_svg_valve_id",
        "_device_is_live_registered",
        "_request_xv_command",
    ):
        _bind_method(fake, name)

    return fake, calls


class TestScadaXVLiveRegistration(unittest.TestCase):
    """
    These tests isolate the SCADA click layer from the real GUI process.

    The most important test here is the presentation-fallback one.
    If that fails while the catalog-proxy case passes, you likely found the
    exact bug causing SCADA clicks to become mock_only=True.
    """

    def test_registered_catalog_proxy_sends_real_backend_command(self):
        fake, calls = _make_scada_like_self()
        fake.backend_device_catalog = _FakeCatalog(
            {"ig-xv-24": SimpleNamespace(live_registered=True)}
        )

        fake._request_xv_command("ig-xv-24", "open", source="unittest")

        self.assertEqual(len(calls), 1)
        args, kwargs = calls[0]

        self.assertEqual(args[0], "open")
        self.assertEqual(kwargs["device_id"], "ig-xv-24")
        self.assertFalse(kwargs["mock_only"])
        self.assertEqual(fake.pending_xv_commands["ig-xv-24"], "open")

    def test_unregistered_catalog_proxy_downgrades_to_mock_only(self):
        fake, calls = _make_scada_like_self()
        fake.backend_device_catalog = _FakeCatalog(
            {"ig-xv-24": SimpleNamespace(live_registered=False)}
        )

        fake._request_xv_command("ig-xv-24", "open", source="unittest")

        self.assertEqual(len(calls), 1)
        _, kwargs = calls[0]
        self.assertTrue(kwargs["mock_only"])

    def test_presentation_fallback_should_accept_backend_inventory_rows_keyed_by_id(self):
        fake, _ = _make_scada_like_self()

        # This shape matches backend inventory rows built from device meta.
        fake.backend_device_presentation = {
            "devices": [
                {
                    "id": "ig-xv-24",
                    "live_registered": True,
                }
            ]
        }

        self.assertTrue(fake._device_is_live_registered("ig-xv-24"))

    def test_presentation_fallback_current_code_path_accepts_device_id_key(self):
        fake, _ = _make_scada_like_self()

        fake.backend_device_presentation = {
            "devices": [
                {
                    "device_id": "ig-xv-24",
                    "live_registered": True,
                }
            ]
        }

        self.assertTrue(fake._device_is_live_registered("ig-xv-24"))

    def test_request_xv_command_uses_real_dispatch_for_presentation_rows_keyed_by_id(self):
        fake, calls = _make_scada_like_self()

        fake.backend_device_presentation = {
            "devices": [
                {
                    "id": "ig-xv-24",
                    "live_registered": True,
                }
            ]
        }

        fake._request_xv_command("ig-xv-24", "open", source="unittest")

        self.assertEqual(len(calls), 1)
        _, kwargs = calls[0]
        self.assertFalse(kwargs["mock_only"])