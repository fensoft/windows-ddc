from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from ddc import MonitorIdentity, SavedMonitorSelection
from gui import MonitorVolumeApp
from overlay import VolumeOverlay, calculate_overlay_geometry
from windows_platform import (
    DisplayArea,
    GWL_EXSTYLE,
    SWP_FRAMECHANGED,
    SWP_NOACTIVATE,
    SWP_NOMOVE,
    SWP_NOSIZE,
    SWP_NOZORDER,
    SWP_SHOWWINDOW,
    ScreenRect,
    WS_EX_NOACTIVATE,
    WS_EX_TOOLWINDOW,
    configure_no_activate_window,
    enumerate_display_areas,
    get_overlay_display_area,
    select_display_area,
    show_window_no_activate,
)


def make_display_area(
    name: str,
    bounds: tuple[int, int, int, int],
    work_area: tuple[int, int, int, int] | None = None,
    *,
    scale_percent: int = 100,
    primary: bool = False,
) -> DisplayArea:
    if work_area is None:
        work_area = bounds
    return DisplayArea(
        display_device_name=name,
        bounds=ScreenRect(*bounds),
        work_area=ScreenRect(*work_area),
        scale_percent=scale_percent,
        primary=primary,
    )


class OverlayPlacementTests(unittest.TestCase):
    def test_native_display_inventory_captures_bounds_work_area_and_scale(self) -> None:
        def enumerate_monitors(_hdc: object, _clip: object, callback: object, _data: int) -> bool:
            return bool(callback(123, None, None, 0))

        def populate_monitor_info(_hmonitor: object, info_pointer: object) -> bool:
            info = info_pointer._obj  # type: ignore[attr-defined]
            info.rcMonitor.left = -1920
            info.rcMonitor.top = 0
            info.rcMonitor.right = 0
            info.rcMonitor.bottom = 1080
            info.rcWork.left = -1920
            info.rcWork.top = 0
            info.rcWork.right = 0
            info.rcWork.bottom = 1040
            info.dwFlags = 1
            info.szDevice = r"\\.\DISPLAY2"
            return True

        def populate_scale(_hmonitor: object, scale_pointer: object) -> int:
            scale_pointer._obj.value = 150  # type: ignore[attr-defined]
            return 0

        with patch(
            "windows_platform.user32.EnumDisplayMonitors",
            side_effect=enumerate_monitors,
        ), patch(
            "windows_platform.user32.GetMonitorInfoW",
            side_effect=populate_monitor_info,
        ), patch(
            "windows_platform.shcore.GetScaleFactorForMonitor",
            side_effect=populate_scale,
        ):
            display_areas = enumerate_display_areas()

        self.assertEqual(
            display_areas,
            [
                make_display_area(
                    r"\\.\DISPLAY2",
                    (-1920, 0, 0, 1080),
                    (-1920, 0, 0, 1040),
                    scale_percent=150,
                    primary=True,
                )
            ],
        )

    def test_bottom_centers_on_a_negative_coordinate_scaled_work_area(self) -> None:
        display_area = make_display_area(
            r"\\.\DISPLAY2",
            (-2560, 0, 0, 1440),
            (-2560, 0, 0, 1400),
            scale_percent=150,
        )

        placement = calculate_overlay_geometry(210, 122, display_area)

        self.assertEqual((placement.x, placement.y), (-1385, 1146))
        self.assertEqual((placement.width, placement.height), (210, 122))

    def test_oversized_overlay_is_clamped_inside_the_scaled_work_area(self) -> None:
        display_area = make_display_area(
            r"\\.\DISPLAY1",
            (100, 50, 300, 220),
            (100, 50, 300, 200),
        )

        placement = calculate_overlay_geometry(500, 500, display_area)

        self.assertEqual(
            (placement.x, placement.y, placement.width, placement.height),
            (124, 82, 152, 30),
        )

    def test_cursor_display_wins_over_the_selected_display(self) -> None:
        primary = make_display_area(r"\\.\DISPLAY1", (0, 0, 1920, 1080), primary=True)
        selected = make_display_area(r"\\.\DISPLAY2", (1920, 0, 3840, 1080))

        result = select_display_area(
            [primary, selected],
            r"\\.\display2",
            (100, 100),
        )

        self.assertIs(result, primary)

    def test_cursor_display_is_used_when_the_selection_is_missing(self) -> None:
        primary = make_display_area(r"\\.\DISPLAY1", (0, 0, 1920, 1080), primary=True)
        cursor_display = make_display_area(r"\\.\DISPLAY2", (-1920, 0, 0, 1080))

        result = select_display_area(
            [primary, cursor_display],
            r"\\.\DISPLAY9",
            (-500, 400),
        )

        self.assertIs(result, cursor_display)

    def test_selected_display_is_the_fallback_without_a_cursor(self) -> None:
        secondary = make_display_area(r"\\.\DISPLAY2", (-1920, 0, 0, 1080))
        primary = make_display_area(r"\\.\DISPLAY1", (0, 0, 1920, 1080), primary=True)

        self.assertIs(
            select_display_area([secondary, primary], r"\\.\DISPLAY2", None),
            secondary,
        )

    def test_native_resolver_always_reads_the_cursor_before_using_selection(self) -> None:
        primary = make_display_area(r"\\.\DISPLAY1", (0, 0, 1920, 1080), primary=True)
        secondary = make_display_area(r"\\.\DISPLAY2", (1920, 0, 3840, 1080))

        def set_cursor(point_pointer: object) -> bool:
            point_pointer._obj.x = 2500  # type: ignore[attr-defined]
            point_pointer._obj.y = 300  # type: ignore[attr-defined]
            return True

        with patch(
            "windows_platform.enumerate_display_areas",
            return_value=[primary, secondary],
        ), patch("windows_platform.user32.GetCursorPos", side_effect=set_cursor) as get_cursor:
            self.assertIs(get_overlay_display_area(r"\\.\DISPLAY2"), secondary)
            get_cursor.assert_called_once()

            self.assertIs(get_overlay_display_area(r"\\.\DISPLAY9"), secondary)
            self.assertEqual(get_cursor.call_count, 2)


class NoActivateWindowTests(unittest.TestCase):
    def test_no_activate_style_is_preserved_and_applied_without_activation(self) -> None:
        existing_style = 0x20
        with patch(
            "windows_platform.user32.GetWindowLongW",
            return_value=existing_style,
        ), patch(
            "windows_platform.user32.SetWindowLongW",
            return_value=existing_style,
        ) as set_style, patch(
            "windows_platform.user32.SetWindowPos",
            return_value=True,
        ) as set_position:
            self.assertTrue(configure_no_activate_window(42))

        set_style.assert_called_once_with(
            set_style.call_args.args[0],
            GWL_EXSTYLE,
            existing_style | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
        )
        flags = set_position.call_args.args[-1]
        self.assertEqual(
            flags,
            SWP_NOMOVE
            | SWP_NOSIZE
            | SWP_NOZORDER
            | SWP_NOACTIVATE
            | SWP_FRAMECHANGED,
        )

    def test_native_show_is_topmost_but_explicitly_no_activate(self) -> None:
        with patch("windows_platform.user32.SetWindowPos", return_value=True) as set_position:
            self.assertTrue(show_window_no_activate(42, -100, 50, 210, 122))

        args = set_position.call_args.args
        self.assertEqual(args[2:6], (-100, 50, 210, 122))
        self.assertEqual(args[-1] & SWP_NOACTIVATE, SWP_NOACTIVATE)
        self.assertEqual(args[-1] & SWP_SHOWWINDOW, SWP_SHOWWINDOW)

    def test_overlay_never_deiconifies_if_no_activate_style_fails(self) -> None:
        volume_overlay = VolumeOverlay.__new__(VolumeOverlay)
        volume_overlay.window = Mock()
        volume_overlay.window.winfo_reqwidth.return_value = 210
        volume_overlay.window.winfo_reqheight.return_value = 122
        volume_overlay.window.winfo_id.return_value = 7
        volume_overlay._hide_after_id = None
        display_area = make_display_area(r"\\.\DISPLAY1", (0, 0, 1920, 1040))

        with patch("overlay.get_overlay_display_area", return_value=display_area), patch(
            "overlay.get_toplevel_window_handle",
            return_value=42,
        ), patch("overlay.configure_no_activate_window", return_value=False), patch(
            "overlay.show_window_no_activate"
        ) as show_native:
            volume_overlay._show_window(1400, r"\\.\DISPLAY1")

        volume_overlay.window.deiconify.assert_not_called()
        volume_overlay.window.withdraw.assert_called_once_with()
        show_native.assert_not_called()

    def test_overlay_show_path_has_no_focus_or_lift_call(self) -> None:
        volume_overlay = VolumeOverlay.__new__(VolumeOverlay)
        volume_overlay.window = Mock()
        volume_overlay.window.winfo_reqwidth.return_value = 210
        volume_overlay.window.winfo_reqheight.return_value = 122
        volume_overlay.window.winfo_id.return_value = 7
        volume_overlay.window.after.return_value = "hide-timer"
        volume_overlay._hide_after_id = None
        display_area = make_display_area(r"\\.\DISPLAY2", (-1920, 0, 0, 1040))

        with patch("overlay.get_overlay_display_area", return_value=display_area), patch(
            "overlay.get_toplevel_window_handle",
            return_value=42,
        ), patch("overlay.configure_no_activate_window", return_value=True), patch(
            "overlay.show_window_no_activate",
            return_value=True,
        ) as show_native:
            volume_overlay._show_window(1400, r"\\.\DISPLAY2")

        volume_overlay.window.geometry.assert_called_once_with("210x122-1065+830")
        volume_overlay.window.deiconify.assert_called_once_with()
        volume_overlay.window.lift.assert_not_called()
        volume_overlay.window.focus_force.assert_not_called()
        show_native.assert_called_once_with(42, -1065, 830, 210, 122)
        self.assertEqual(volume_overlay._hide_after_id, "hide-timer")


class OverlayGUITests(unittest.TestCase):
    def test_gui_passes_the_selected_windows_display_to_the_overlay(self) -> None:
        app = MonitorVolumeApp.__new__(MonitorVolumeApp)
        app._closing = False
        app._overlay = Mock()
        app.current_volume = 47
        app.selected_key = SavedMonitorSelection(
            "Monitor",
            MonitorIdentity("device-path", "DEL", 1, "SERIAL"),
        )
        monitor = Mock()
        monitor.selection_key = app.selected_key
        monitor.display_device_name = r"\\.\DISPLAY2"
        app.monitors = [monitor]

        app._show_volume_overlay()

        app._overlay.show.assert_called_once_with(
            47,
            preferred_display_device_name=r"\\.\DISPLAY2",
        )

    def test_gui_falls_back_to_cursor_placement_without_a_current_match(self) -> None:
        app = MonitorVolumeApp.__new__(MonitorVolumeApp)
        app._closing = False
        app._overlay = Mock()
        app._control_unavailable_reason = "Monitor disconnected."
        app.selected_key = SavedMonitorSelection(
            "Monitor",
            MonitorIdentity("missing-path"),
        )
        app.monitors = []
        app._set_status = Mock()

        app._show_unavailable_error()

        app._overlay.show_error.assert_called_once_with(
            "Monitor disconnected.",
            preferred_display_device_name=None,
        )


if __name__ == "__main__":
    unittest.main()
