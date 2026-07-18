from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from gui import MonitorVolumeApp


class AutostartGUITests(unittest.TestCase):
    def make_app(self) -> MonitorVolumeApp:
        app = MonitorVolumeApp.__new__(MonitorVolumeApp)
        app.start_with_windows = False
        app.start_with_windows_var = Mock()
        app.status_var = Mock()
        return app

    def test_toggle_updates_registry_state_and_status(self) -> None:
        app = self.make_app()
        app.start_with_windows_var.get.return_value = True

        with patch("gui.set_start_with_windows") as set_mock:
            app.on_start_with_windows_toggled()

        set_mock.assert_called_once_with(True)
        self.assertTrue(app.start_with_windows)
        app.status_var.set.assert_called_once_with("Start with Windows enabled.")

    def test_toggle_failure_restores_the_previous_value(self) -> None:
        app = self.make_app()
        app.start_with_windows = True
        app.start_with_windows_var.get.return_value = False

        with patch("gui.set_start_with_windows", side_effect=OSError("access denied")):
            app.on_start_with_windows_toggled()

        app.start_with_windows_var.set.assert_called_once_with(True)
        self.assertTrue(app.start_with_windows)
        app.status_var.set.assert_called_once_with(
            "Could not disable Start with Windows: access denied"
        )


if __name__ == "__main__":
    unittest.main()
