from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from gui import MonitorVolumeApp
from windows_platform import PlatformError, TrayIconController, WM_TRAY_SHOW


class TrayIconControllerTests(unittest.TestCase):
    def make_controller(self, on_error=None, on_restore=None) -> TrayIconController:
        with patch(
            "windows_platform.user32.RegisterWindowMessageW",
            side_effect=[0xC123, 0xC124],
        ):
            return TrayIconController(
                tooltip="windows-ddc",
                on_restore=on_restore or (lambda: None),
                on_exit=lambda: None,
                on_error=on_error or (lambda _error: None),
            )

    def test_duplicate_launch_message_requests_restore(self) -> None:
        on_restore = Mock()
        controller = self.make_controller(on_restore=on_restore)

        result = controller._window_proc(
            123,
            controller._restore_existing_instance_message,
            0,
            0,
        )

        self.assertEqual(result, 0)
        on_restore.assert_called_once_with()

    def test_show_waits_for_successful_native_add(self) -> None:
        controller = self.make_controller()
        controller._hwnd = 123

        def complete_show(_hwnd, message, request_id, _l_param) -> bool:
            self.assertEqual(message, WM_TRAY_SHOW)
            controller._complete_show_request(request_id, None)
            return True

        with patch("windows_platform.user32.PostMessageW", side_effect=complete_show):
            controller.show(timeout=0.1)

    def test_show_surfaces_native_add_failure(self) -> None:
        controller = self.make_controller()
        controller._hwnd = 123
        native_error = OSError("notification area rejected the icon")

        def fail_show(_hwnd, _message, request_id, _l_param) -> bool:
            controller._complete_show_request(request_id, native_error)
            return True

        with patch("windows_platform.user32.PostMessageW", side_effect=fail_show):
            with self.assertRaisesRegex(PlatformError, "notification area rejected the icon"):
                controller.show(timeout=0.1)

    def test_show_timeout_does_not_leave_a_pending_request(self) -> None:
        controller = self.make_controller()
        controller._hwnd = 123

        with patch("windows_platform.user32.PostMessageW", return_value=True):
            with self.assertRaisesRegex(PlatformError, "Timed out"):
                controller.show(timeout=0.001)

        self.assertEqual(controller._show_requests, {})

    def test_show_post_failure_does_not_leave_a_pending_request(self) -> None:
        controller = self.make_controller()
        controller._hwnd = 123

        with patch("windows_platform.user32.PostMessageW", return_value=False), patch(
            "windows_platform.win_error",
            return_value=OSError("PostMessageW failed"),
        ):
            with self.assertRaisesRegex(PlatformError, "PostMessageW failed"):
                controller.show(timeout=0.1)

        self.assertEqual(controller._show_requests, {})

    def test_show_rejects_a_stopped_controller(self) -> None:
        controller = self.make_controller()

        with self.assertRaisesRegex(PlatformError, "not running"):
            controller.show(timeout=0.1)

    def test_taskbar_recreation_readds_a_visible_icon(self) -> None:
        controller = self.make_controller()
        controller._icon_visible = True

        def restore_icon(_hwnd):
            controller._icon_visible = True
            return None

        controller._show_icon = Mock(side_effect=restore_icon)

        result = controller._window_proc(123, controller._taskbar_created_message, 0, 0)

        self.assertEqual(result, 0)
        controller._show_icon.assert_called_once_with(123)
        self.assertTrue(controller._icon_visible)

    def test_taskbar_recreation_failure_is_reported(self) -> None:
        on_error = Mock()
        controller = self.make_controller(on_error=on_error)
        controller._icon_visible = True
        native_error = OSError("Explorer rejected the replacement icon")
        controller._show_icon = Mock(return_value=native_error)

        controller._window_proc(123, controller._taskbar_created_message, 0, 0)

        on_error.assert_called_once_with(native_error)
        self.assertFalse(controller._icon_visible)

    def test_taskbar_recreation_does_not_add_an_icon_for_a_visible_window(self) -> None:
        controller = self.make_controller()
        controller._icon_visible = False
        controller._show_icon = Mock()

        controller._window_proc(123, controller._taskbar_created_message, 0, 0)

        controller._show_icon.assert_not_called()


class MonitorVolumeAppTrayTests(unittest.TestCase):
    def make_app(self) -> MonitorVolumeApp:
        app = MonitorVolumeApp.__new__(MonitorVolumeApp)
        app._closing = False
        app._in_tray = False
        app._tray_icon = Mock()
        app.root = Mock()
        app.dark_mode = False
        app._set_status = Mock()
        return app

    def test_window_withdraws_only_after_tray_show_succeeds(self) -> None:
        app = self.make_app()

        app.minimize_to_tray()

        app._tray_icon.show.assert_called_once_with()
        self.assertTrue(app._in_tray)
        app.root.withdraw.assert_called_once_with()
        app.root.deiconify.assert_not_called()

    def test_tray_show_failure_restores_the_main_window(self) -> None:
        app = self.make_app()
        app._tray_icon.show.side_effect = PlatformError("tray add failed")

        with patch("gui.apply_window_chrome") as apply_chrome:
            app.minimize_to_tray()

        self.assertFalse(app._in_tray)
        app.root.withdraw.assert_not_called()
        app._tray_icon.hide.assert_called_once_with()
        app.root.deiconify.assert_called_once_with()
        app.root.state.assert_called_once_with("normal")
        apply_chrome.assert_called_once_with(app.root, False)
        app.root.lift.assert_called_once_with()
        app.root.focus_force.assert_called_once_with()
        app._set_status.assert_called_once_with(
            "Tray icon failed: tray add failed. The main window was restored."
        )

    def test_async_tray_failure_restores_a_withdrawn_window(self) -> None:
        app = self.make_app()
        app._in_tray = True

        with patch("gui.apply_window_chrome"):
            app._handle_tray_error(OSError("Explorer lost the icon"))

        self.assertFalse(app._in_tray)
        app._tray_icon.hide.assert_called_once_with()
        app.root.deiconify.assert_called_once_with()
        app._set_status.assert_called_once_with(
            "Tray icon failed: Explorer lost the icon. The main window was restored."
        )


if __name__ == "__main__":
    unittest.main()
