from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import app
from windows_platform import (
    ERROR_ALREADY_EXISTS,
    HWND_BROADCAST,
    SINGLE_INSTANCE_MUTEX_NAME,
    InstanceAlreadyRunningError,
    PlatformError,
    SingleInstanceGuard,
    request_existing_instance_restore,
)


class SingleInstanceGuardTests(unittest.TestCase):
    def test_guard_holds_and_closes_the_created_mutex(self) -> None:
        with patch(
            "windows_platform.kernel32.CreateMutexW",
            return_value=123,
        ) as create_mock, patch(
            "windows_platform.kernel32.CloseHandle",
            return_value=True,
        ) as close_mock, patch(
            "windows_platform.ctypes.get_last_error",
            return_value=0,
        ):
            guard = SingleInstanceGuard()
            guard.close()
            guard.close()

        create_mock.assert_called_once_with(None, False, SINGLE_INSTANCE_MUTEX_NAME)
        close_mock.assert_called_once_with(123)

    def test_existing_mutex_rejects_the_duplicate_and_closes_its_handle(self) -> None:
        with patch(
            "windows_platform.kernel32.CreateMutexW",
            return_value=456,
        ), patch(
            "windows_platform.kernel32.CloseHandle",
            return_value=True,
        ) as close_mock, patch(
            "windows_platform.ctypes.get_last_error",
            return_value=ERROR_ALREADY_EXISTS,
        ):
            with self.assertRaisesRegex(InstanceAlreadyRunningError, "already running"):
                SingleInstanceGuard()

        close_mock.assert_called_once_with(456)

    def test_mutex_creation_failure_is_reported(self) -> None:
        native_error = OSError("mutex unavailable")
        with patch(
            "windows_platform.kernel32.CreateMutexW",
            return_value=None,
        ), patch(
            "windows_platform.win_error",
            return_value=native_error,
        ):
            with self.assertRaisesRegex(PlatformError, "single-instance guard"):
                SingleInstanceGuard()

    def test_restore_request_is_broadcast_with_a_registered_message(self) -> None:
        with patch(
            "windows_platform.user32.RegisterWindowMessageW",
            return_value=0xC321,
        ) as register_mock, patch(
            "windows_platform.user32.PostMessageW",
            return_value=True,
        ) as post_mock:
            request_existing_instance_restore()

        register_mock.assert_called_once()
        post_mock.assert_called_once_with(HWND_BROADCAST, 0xC321, 0, 0)


class CompositionRootTests(unittest.TestCase):
    def test_primary_instance_holds_guard_for_the_tk_lifetime(self) -> None:
        guard = Mock()
        root = Mock()
        with patch("app.SingleInstanceGuard", return_value=guard), patch(
            "app.tk.Tk",
            return_value=root,
        ) as tk_mock, patch("app.MonitorVolumeApp") as app_mock:
            result = app.main()

        self.assertEqual(result, 0)
        tk_mock.assert_called_once_with()
        app_mock.assert_called_once_with(root)
        root.mainloop.assert_called_once_with()
        guard.close.assert_called_once_with()

    def test_duplicate_exits_before_tk_and_requests_existing_window(self) -> None:
        with patch(
            "app.SingleInstanceGuard",
            side_effect=InstanceAlreadyRunningError("already running"),
        ), patch("app.request_existing_instance_restore") as restore_mock, patch(
            "app.tk.Tk"
        ) as tk_mock:
            result = app.main()

        self.assertEqual(result, 0)
        restore_mock.assert_called_once_with()
        tk_mock.assert_not_called()

    def test_guard_is_closed_when_app_construction_fails(self) -> None:
        guard = Mock()
        root = Mock()
        with patch("app.SingleInstanceGuard", return_value=guard), patch(
            "app.tk.Tk",
            return_value=root,
        ), patch("app.MonitorVolumeApp", side_effect=RuntimeError("startup failed")):
            with self.assertRaisesRegex(RuntimeError, "startup failed"):
                app.main()

        guard.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
