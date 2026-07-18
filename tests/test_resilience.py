from __future__ import annotations

import queue
import threading
import unittest
from unittest.mock import Mock

from gui import MonitorVolumeApp
from windows_platform import (
    DisplayChangeListener,
    GlobalVolumeKeyListener,
    PlatformError,
    TrayIconController,
)


class QueuePollingTests(unittest.TestCase):
    def test_callback_failure_is_reported_and_polling_continues(self) -> None:
        app = MonitorVolumeApp.__new__(MonitorVolumeApp)
        app.root = Mock()
        app.root.after.return_value = "next-poll"
        app._closing = False
        app._poll_after_id = "old-poll"
        app._result_queue = queue.Queue()
        app._hotkey_delta_queue = queue.Queue()
        app._hotkeys_enabled = False
        app._busy = False
        app._volume_write_inflight = False
        app._report_ui_callback_error = Mock()
        completed = Mock()

        failure = RuntimeError("broken queued callback")
        app._result_queue.put(Mock(side_effect=failure))
        app._result_queue.put(completed)

        app._poll_queues()

        app._report_ui_callback_error.assert_called_once_with(failure)
        completed.assert_called_once_with()
        app.root.after.assert_called_once_with(50, app._poll_queues)
        self.assertEqual(app._poll_after_id, "next-poll")

    def test_hotkey_adjustment_failure_does_not_stop_polling(self) -> None:
        app = MonitorVolumeApp.__new__(MonitorVolumeApp)
        app.root = Mock()
        app.root.after.return_value = "next-poll"
        app._closing = False
        app._poll_after_id = None
        app._result_queue = queue.Queue()
        app._hotkey_delta_queue = queue.Queue()
        app._hotkey_delta_queue.put(3)
        app._hotkeys_enabled = True
        app._busy = False
        app._volume_write_inflight = False
        failure = RuntimeError("adjustment failed")
        app.adjust_selected_volume = Mock(side_effect=failure)
        app._report_ui_callback_error = Mock()

        app._poll_queues()

        app.adjust_selected_volume.assert_called_once_with(3)
        app._report_ui_callback_error.assert_called_once_with(failure)
        app.root.after.assert_called_once_with(50, app._poll_queues)

    def test_callback_report_fails_monitor_control_closed(self) -> None:
        app = MonitorVolumeApp.__new__(MonitorVolumeApp)
        app.root = Mock()
        app._topology_valid = threading.Event()
        app._topology_valid.set()
        app._hotkeys_ready = True
        app._hotkeys_enabled = True
        app.current_volume = 40
        app.target_volume = 41
        app._active_ddc_operation_id = None
        app._busy = True
        app._volume_write_inflight = True
        app._pending_target_volume = 42
        app._update_hotkey_state = Mock(
            side_effect=lambda: setattr(app, "_hotkeys_enabled", False)
        )
        app._set_displayed_volume = Mock()
        app._set_status = Mock()
        app._apply_control_state = Mock()
        failure = RuntimeError("bad state update")

        app._report_ui_callback_error(failure)

        self.assertFalse(app._topology_valid.is_set())
        self.assertFalse(app._hotkeys_ready)
        self.assertFalse(app._hotkeys_enabled)
        self.assertFalse(app._busy)
        self.assertFalse(app._volume_write_inflight)
        self.assertIsNone(app.current_volume)
        self.assertIsNone(app.target_volume)
        self.assertIsNone(app._pending_target_volume)
        app._set_displayed_volume.assert_called_once_with(None)
        app.root.report_callback_exception.assert_called_once_with(
            RuntimeError,
            failure,
            failure.__traceback__,
        )


class DDCWatchdogTests(unittest.TestCase):
    def make_active_app(self) -> MonitorVolumeApp:
        app = MonitorVolumeApp.__new__(MonitorVolumeApp)
        app.root = Mock()
        app._closing = False
        app._topology_valid = threading.Event()
        app._topology_valid.set()
        app._topology_generation = 2
        app._topology_generation_lock = threading.Lock()
        app._hotkeys_ready = True
        app._hotkeys_enabled = True
        app.current_volume = 40
        app.target_volume = 41
        app._pending_target_volume = 42
        app._busy = True
        app._volume_write_inflight = True
        app._ddc_timeout_after_id = "watchdog"
        app._ddc_operation_sequence = 7
        app._active_ddc_operation_id = 7
        app._active_ddc_operation_kind = "Monitor volume write"
        app._ddc_operation_timed_out = False
        app._control_unavailable_reason = None
        app._refresh_requested = False
        app._refresh_requested_automatic = False
        app._refresh_retry_index = 2
        app._refresh_after_id = None
        app._update_hotkey_state = Mock(
            side_effect=lambda: setattr(app, "_hotkeys_enabled", False)
        )
        app._set_displayed_volume = Mock()
        app._show_unavailable_error = Mock()
        app._apply_control_state = Mock()
        app._schedule_refresh = Mock()
        app._run_deferred_refresh = Mock()
        return app

    def test_timeout_disables_control_without_releasing_the_worker_slot(self) -> None:
        app = self.make_active_app()

        app._handle_ddc_operation_timeout(7)

        self.assertEqual(app._active_ddc_operation_id, 7)
        self.assertTrue(app._ddc_operation_timed_out)
        self.assertTrue(app._busy)
        self.assertTrue(app._volume_write_inflight)
        self.assertFalse(app._topology_valid.is_set())
        self.assertFalse(app._hotkeys_ready)
        self.assertFalse(app._hotkeys_enabled)
        self.assertIsNone(app.current_volume)
        self.assertIsNone(app.target_volume)
        app._schedule_refresh.assert_not_called()
        app._show_unavailable_error.assert_called_once()

    def test_late_completion_is_ignored_then_schedules_a_read_only_refresh(self) -> None:
        app = self.make_active_app()
        app._update_monitor_list = Mock()
        app._handle_ddc_operation_timeout(7)

        app._finish_volume_write_success(Mock(), generation=2, operation_id=7)

        self.assertIsNone(app._active_ddc_operation_id)
        self.assertFalse(app._busy)
        self.assertFalse(app._volume_write_inflight)
        self.assertEqual(app._refresh_retry_index, 0)
        app._update_monitor_list.assert_not_called()
        app._schedule_refresh.assert_called_once_with(500, automatic=True)

    def test_stale_completion_cannot_release_the_active_operation(self) -> None:
        app = self.make_active_app()

        accepted = app._accept_ddc_completion(6)

        self.assertFalse(accepted)
        self.assertEqual(app._active_ddc_operation_id, 7)
        self.assertTrue(app._busy)
        app.root.after_cancel.assert_not_called()

    def test_on_time_completion_cancels_the_watchdog(self) -> None:
        app = self.make_active_app()

        accepted = app._accept_ddc_completion(7)

        self.assertTrue(accepted)
        self.assertIsNone(app._active_ddc_operation_id)
        self.assertIsNone(app._active_ddc_operation_kind)
        self.assertIsNone(app._ddc_timeout_after_id)
        app.root.after_cancel.assert_called_once_with("watchdog")
        app._schedule_refresh.assert_not_called()


class NativeThreadTimeoutTests(unittest.TestCase):
    def test_all_native_starts_are_bounded(self) -> None:
        controllers = [
            (DisplayChangeListener(lambda: None, lambda _error: None), "_ready", "_stop_requested"),
            (
                TrayIconController("test", lambda: None, lambda: None, lambda _error: None),
                "_ready",
                "_stop_requested",
            ),
            (
                GlobalVolumeKeyListener(
                    lambda _delta: None,
                    lambda: False,
                    lambda _error: None,
                    step=1,
                ),
                "_hook_ready",
                "_stop_event",
            ),
        ]

        for controller, ready_name, stop_name in controllers:
            with self.subTest(controller=controller.__class__.__name__):
                controller._thread = Mock()
                ready = Mock()
                ready.wait.return_value = False
                setattr(controller, ready_name, ready)

                with self.assertRaises(PlatformError):
                    controller.start(timeout=0.01)

                ready.wait.assert_called_once_with(0.01)
                self.assertTrue(getattr(controller, stop_name).is_set())

    def test_stop_reports_a_thread_that_does_not_exit(self) -> None:
        listener = GlobalVolumeKeyListener(
            lambda _delta: None,
            lambda: False,
            lambda _error: None,
            step=1,
        )
        listener._thread = Mock()
        listener._thread.is_alive.return_value = True

        stopped = listener.stop(timeout=0.01)

        self.assertFalse(stopped)
        listener._thread.join.assert_called_once_with(timeout=0.01)


class ShutdownDiagnosticsTests(unittest.TestCase):
    def test_stop_failures_and_timeouts_are_collected(self) -> None:
        failures: list[str] = []
        timed_out = Mock()
        timed_out.stop.return_value = False
        failed = Mock()
        failed.stop.side_effect = RuntimeError("native error")

        MonitorVolumeApp._stop_native_controller("Tray controller", timed_out, failures)
        MonitorVolumeApp._stop_native_controller("Hook", failed, failures)

        self.assertEqual(
            failures,
            [
                "Tray controller did not stop before the timeout",
                "Hook stop failed: native error",
            ],
        )


if __name__ == "__main__":
    unittest.main()
