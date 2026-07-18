from __future__ import annotations

import unittest
from unittest.mock import Mock

from gui import MonitorVolumeApp
from windows_platform import (
    GlobalVolumeKeyListener,
    VK_VOLUME_DOWN,
    VK_VOLUME_UP,
    WM_KEYDOWN,
    WM_KEYUP,
    WM_SYSKEYDOWN,
    WM_SYSKEYUP,
)


class ListenerState:
    def __init__(self, is_active: bool) -> None:
        self.is_active = is_active


class MonitorVolumeAppHotkeyTests(unittest.TestCase):
    def make_ready_app(self, listener: ListenerState | None) -> MonitorVolumeApp:
        app = MonitorVolumeApp.__new__(MonitorVolumeApp)
        app._closing = False
        app._hotkeys_ready = True
        app._hotkeys_enabled = False
        app._listener = listener
        app.selected_key = ("Test monitor", 1)
        app.current_volume = 50
        return app

    def test_hotkey_state_requires_every_safety_condition(self) -> None:
        listener = ListenerState(is_active=True)
        app = self.make_ready_app(listener)

        app._update_hotkey_state()
        self.assertTrue(app._hotkeys_enabled)

        safety_conditions = (
            ("hook start failure", "_listener", None),
            ("hook runtime failure", "listener_active", False),
            ("refresh in progress", "_hotkeys_ready", False),
            ("monitor unavailable", "current_volume", None),
            ("selection cleared", "selected_key", None),
            ("shutdown", "_closing", True),
        )
        for name, attribute, value in safety_conditions:
            with self.subTest(name=name):
                listener.is_active = True
                app._listener = listener
                app._hotkeys_ready = True
                app.current_volume = 50
                app.selected_key = ("Test monitor", 1)
                app._closing = False
                if attribute == "listener_active":
                    listener.is_active = value
                else:
                    setattr(app, attribute, value)

                app._update_hotkey_state()
                self.assertFalse(app._hotkeys_enabled)

    def test_should_consume_rechecks_live_listener_state(self) -> None:
        listener = ListenerState(is_active=True)
        app = self.make_ready_app(listener)
        app._update_hotkey_state()
        self.assertTrue(app._should_consume_volume_keys())

        listener.is_active = False
        self.assertFalse(app._should_consume_volume_keys())

    def test_write_failure_marks_volume_unknown_and_releases_hotkeys(self) -> None:
        app = self.make_ready_app(ListenerState(is_active=True))
        app._hotkeys_enabled = True
        app._hotkeys_ready = True
        app._volume_write_inflight = True
        app._pending_target_volume = 75
        app._busy = True
        app.target_volume = 75
        app._overlay = Mock()
        app._set_displayed_volume = Mock()
        app._set_status = Mock()
        app._apply_control_state = Mock()

        app._finish_volume_write_error(RuntimeError("DDC connection lost"))

        self.assertFalse(app._volume_write_inflight)
        self.assertIsNone(app._pending_target_volume)
        self.assertFalse(app._busy)
        self.assertIsNone(app.current_volume)
        self.assertIsNone(app.target_volume)
        self.assertFalse(app._hotkeys_ready)
        self.assertFalse(app._hotkeys_enabled)
        app._set_displayed_volume.assert_called_once_with(None)
        app._overlay.hide.assert_called_once_with()
        app._set_status.assert_called_once_with(
            "DDC connection lost. Monitor volume may have changed. "
            "Refresh to resume volume-key control."
        )
        app._apply_control_state.assert_called_once_with()


class GlobalVolumeKeyListenerTests(unittest.TestCase):
    def make_listener(self, enabled: dict[str, bool]) -> GlobalVolumeKeyListener:
        return GlobalVolumeKeyListener(
            on_delta=lambda _delta: None,
            should_consume=lambda: enabled["value"],
            on_error=lambda _error: None,
            step=2,
        )

    def test_listener_active_state_is_explicit(self) -> None:
        listener = self.make_listener({"value": True})
        self.assertFalse(listener.is_active)

        listener._hook_active.set()
        self.assertTrue(listener.is_active)

        listener.stop()
        self.assertFalse(listener.is_active)

    def test_pass_through_decision_is_stable_until_key_up(self) -> None:
        enabled = {"value": False}
        listener = self.make_listener(enabled)

        self.assertEqual(listener._resolve_volume_key_event(VK_VOLUME_UP, WM_KEYDOWN), (False, None))
        enabled["value"] = True
        self.assertEqual(listener._resolve_volume_key_event(VK_VOLUME_UP, WM_KEYDOWN), (False, None))
        self.assertEqual(listener._resolve_volume_key_event(VK_VOLUME_UP, WM_KEYUP), (False, None))

        self.assertEqual(listener._resolve_volume_key_event(VK_VOLUME_UP, WM_SYSKEYDOWN), (True, 2))
        self.assertEqual(listener._resolve_volume_key_event(VK_VOLUME_UP, WM_SYSKEYUP), (True, None))

    def test_consumed_press_stays_consumed_but_stops_emitting_deltas_when_disabled(self) -> None:
        enabled = {"value": True}
        listener = self.make_listener(enabled)

        self.assertEqual(listener._resolve_volume_key_event(VK_VOLUME_DOWN, WM_KEYDOWN), (True, -2))
        enabled["value"] = False
        self.assertEqual(listener._resolve_volume_key_event(VK_VOLUME_DOWN, WM_KEYDOWN), (True, None))
        self.assertEqual(listener._resolve_volume_key_event(VK_VOLUME_DOWN, WM_KEYUP), (True, None))
        self.assertEqual(listener._resolve_volume_key_event(VK_VOLUME_DOWN, WM_KEYDOWN), (False, None))


if __name__ == "__main__":
    unittest.main()
