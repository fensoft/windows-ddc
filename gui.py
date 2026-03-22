from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Any, Callable, TypeAlias

from ddc import (
    MonitorRef,
    SelectionKey,
    clamp,
    enumerate_monitors,
    pick_selected_monitor_index,
    read_monitor_volume,
    set_monitor_volume,
)
from overlay import VolumeOverlay
from settings import load_selected_monitor_key, save_selected_monitor_key
from theme import (
    apply_app_icon,
    apply_color_scheme,
    apply_theme,
    apply_window_chrome,
    is_windows_dark_mode_enabled,
)
from windows_platform import GlobalVolumeKeyListener, TrayIconController


RefreshResult: TypeAlias = tuple[list[MonitorRef], int | None, int | None, Exception | None]


class MonitorVolumeApp:
    STEP_SIZE = 1
    TRAY_TOOLTIP = "windows-ddc"

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Monitor Volume")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.bind("<Unmap>", self.on_window_unmap)

        self.dark_mode = is_windows_dark_mode_enabled()
        self.style = ttk.Style(self.root)
        self.active_theme = apply_theme(self.style, self.dark_mode)

        self.monitors: list[MonitorRef] = []
        self.preferred_selected_key = load_selected_monitor_key()
        self.selected_key: SelectionKey | None = None
        self.current_volume: int | None = None
        self.target_volume: int | None = None
        self.app_icon_path: Path | None = None
        self._busy = False
        self._closing = False
        self._ignore_scale_events = False
        self._result_queue: queue.Queue[Callable[[], None]] = queue.Queue()
        self._hotkey_delta_queue: queue.Queue[int] = queue.Queue()
        self._hotkeys_ready = False
        self._hotkeys_enabled = False
        self._listener: GlobalVolumeKeyListener | None = None
        self._overlay: VolumeOverlay | None = None
        self._volume_write_inflight = False
        self._pending_target_volume: int | None = None
        self._tray_icon: TrayIconController | None = None
        self._in_tray = False
        self._poll_after_id: str | None = None
        self._refresh_after_id: str | None = None

        self.monitor_var = tk.StringVar()
        self.volume_var = tk.DoubleVar(value=0.0)
        self.volume_text_var = tk.StringVar(value="--")
        self.status_var = tk.StringVar(value="Searching for monitors...")

        self.app_icon_path = apply_app_icon(self.root)
        self._build_widgets()
        self._overlay = VolumeOverlay(self.root)
        apply_color_scheme(self.root, self.status_bar, self.dark_mode)
        self._lock_window_size()
        apply_window_chrome(self.root, self.dark_mode)
        self._apply_control_state()
        self._start_tray_icon()
        self._start_minimized()
        self._start_keyboard_listener()
        self._poll_after_id = self.root.after(50, self._poll_queues)
        self._refresh_after_id = self.root.after(50, self.refresh_monitors)

    def _build_widgets(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        content = ttk.Frame(self.root, padding=12)
        content.grid(row=0, column=0, sticky="nsew")
        content.columnconfigure(1, weight=1)
        content.columnconfigure(2, weight=1)

        ttk.Label(content, text="Monitor:").grid(row=0, column=0, sticky="w")

        self.monitor_combo = ttk.Combobox(
            content,
            textvariable=self.monitor_var,
            state="readonly",
            width=34,
        )
        self.monitor_combo.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        self.monitor_combo.bind("<<ComboboxSelected>>", self.on_monitor_selected)

        self.refresh_button = ttk.Button(content, text="Refresh", width=10, command=self.refresh_monitors)
        self.refresh_button.grid(row=1, column=3, sticky="e", padx=(8, 0), pady=(4, 0))

        ttk.Label(content, text="Volume:").grid(row=2, column=0, sticky="w", pady=(14, 0))

        self.volume_value_label = ttk.Label(
            content,
            textvariable=self.volume_text_var,
            width=5,
            anchor="e",
        )
        self.volume_value_label.grid(row=2, column=3, sticky="e", pady=(14, 0))

        self.decrease_button = ttk.Button(
            content,
            text="-",
            width=4,
            command=lambda: self.adjust_selected_volume(-self.STEP_SIZE),
        )
        self.decrease_button.grid(row=3, column=0, sticky="w", pady=(6, 0))

        self.volume_scale = ttk.Scale(
            content,
            from_=0,
            to=100,
            orient=tk.HORIZONTAL,
            variable=self.volume_var,
            command=self.on_scale_moved,
            length=260,
        )
        self.volume_scale.grid(row=3, column=1, columnspan=2, sticky="ew", padx=8, pady=(6, 0))
        self.volume_scale.bind("<ButtonRelease-1>", self.on_scale_released)
        self.volume_scale.bind("<KeyRelease>", self.on_scale_released)

        self.increase_button = ttk.Button(
            content,
            text="+",
            width=4,
            command=lambda: self.adjust_selected_volume(self.STEP_SIZE),
        )
        self.increase_button.grid(row=3, column=3, sticky="e", pady=(6, 0))

        self.status_bar = tk.Label(
            self.root,
            textvariable=self.status_var,
            anchor="w",
            relief=tk.SUNKEN,
            bd=1,
            padx=6,
        )
        self.status_bar.grid(row=1, column=0, sticky="ew")

    def _lock_window_size(self) -> None:
        self.root.update_idletasks()
        width = max(self.root.winfo_reqwidth(), 440)
        height = self.root.winfo_reqheight()
        self.root.geometry(f"{width}x{height}")
        self.root.resizable(False, False)

    def _start_tray_icon(self) -> None:
        self._tray_icon = TrayIconController(
            tooltip=self.TRAY_TOOLTIP,
            on_restore=lambda: self._post_to_ui(self.restore_from_tray),
            on_exit=lambda: self._post_to_ui(self.on_close),
            on_error=self._handle_tray_error_from_thread,
            icon_path=self.app_icon_path,
        )
        try:
            self._tray_icon.start()
        except Exception as exc:
            self._tray_icon = None
            self._set_status(self._format_error(exc))

    def _start_minimized(self) -> None:
        if self._tray_icon is None:
            return
        self.minimize_to_tray()

    def _start_keyboard_listener(self) -> None:
        self._listener = GlobalVolumeKeyListener(
            on_delta=self._queue_hotkey_delta,
            should_consume=self._should_consume_volume_keys,
            on_error=self._handle_listener_error_from_thread,
            step=self.STEP_SIZE,
        )
        try:
            self._listener.start()
        except Exception as exc:
            self._listener = None
            self._set_status(self._format_error(exc))

    def _handle_listener_error_from_thread(self, exc: Exception) -> None:
        self._post_to_ui(lambda error=exc: self._handle_listener_error(error))

    def _handle_listener_error(self, exc: Exception) -> None:
        self._hotkeys_ready = False
        self._update_hotkey_state()
        self._set_status(f"Volume-key listener failed: {self._format_error(exc)}")

    def _handle_tray_error_from_thread(self, exc: Exception) -> None:
        self._post_to_ui(lambda error=exc: self._handle_tray_error(error))

    def _handle_tray_error(self, exc: Exception) -> None:
        self._set_status(f"Tray icon failed: {self._format_error(exc)}")

    def _queue_hotkey_delta(self, delta: int) -> None:
        if not self._closing:
            self._hotkey_delta_queue.put(delta)

    def _should_consume_volume_keys(self) -> bool:
        return self._hotkeys_enabled and not self._closing

    def _post_to_ui(self, callback: Callable[[], None]) -> None:
        if not self._closing:
            self._result_queue.put(callback)

    def _poll_queues(self) -> None:
        self._poll_after_id = None
        if self._closing:
            return

        while True:
            try:
                callback = self._result_queue.get_nowait()
            except queue.Empty:
                break
            callback()

        if self._hotkeys_enabled and (not self._busy or self._volume_write_inflight):
            pending_delta = 0
            while True:
                try:
                    pending_delta += self._hotkey_delta_queue.get_nowait()
                except queue.Empty:
                    break
            if pending_delta:
                self.adjust_selected_volume(pending_delta)
        elif not self._hotkeys_enabled:
            while True:
                try:
                    self._hotkey_delta_queue.get_nowait()
                except queue.Empty:
                    break

        self._poll_after_id = self.root.after(50, self._poll_queues)

    def _format_error(self, exc: Exception) -> str:
        message = str(exc).strip()
        return message or exc.__class__.__name__

    def _set_status(self, message: str) -> None:
        self.status_var.set(message)

    def _set_widget_enabled(self, widget: ttk.Widget, enabled: bool) -> None:
        if enabled:
            widget.state(["!disabled"])
        else:
            widget.state(["disabled"])

    def _apply_control_state(self) -> None:
        if self._closing:
            return

        has_monitors = bool(self.monitors)
        has_volume = has_monitors and self.current_volume is not None

        self._set_widget_enabled(self.refresh_button, not self._busy)
        self._set_widget_enabled(self.monitor_combo, has_monitors and not self._busy)
        volume_controls_enabled = has_volume and (not self._busy or self._volume_write_inflight)
        self._set_widget_enabled(self.decrease_button, volume_controls_enabled)
        self._set_widget_enabled(self.increase_button, volume_controls_enabled)
        self._set_widget_enabled(self.volume_scale, volume_controls_enabled)

    def _set_busy(self, busy: bool, status_message: str | None = None) -> None:
        self._busy = busy
        if status_message is not None:
            self._set_status(status_message)
        self._apply_control_state()

    def _update_hotkey_state(self) -> None:
        self._hotkeys_enabled = (
            self._hotkeys_ready
            and not self._closing
            and self.selected_key is not None
            and self.current_volume is not None
        )

    def _remember_selected_monitor(self, selection_key: SelectionKey) -> None:
        self.selected_key = selection_key
        self.preferred_selected_key = selection_key
        self._update_hotkey_state()
        try:
            save_selected_monitor_key(selection_key)
        except OSError:
            pass

    def _set_displayed_volume(self, volume: int | None) -> None:
        self._ignore_scale_events = True
        try:
            self.volume_var.set(0.0 if volume is None else float(clamp(volume, 0, 100)))
        finally:
            self._ignore_scale_events = False

        if volume is None:
            self.volume_text_var.set("--")
        else:
            self.volume_text_var.set(f"{clamp(volume, 0, 100)}%")

    def _show_volume_overlay(self, volume: int | None = None) -> None:
        if self._closing or self._overlay is None:
            return
        if volume is None:
            volume = self.current_volume
        if volume is None:
            return
        self._overlay.show(clamp(volume, 0, 100))

    def _selected_monitor(self) -> MonitorRef | None:
        current_index = self.monitor_combo.current()
        if current_index < 0 or current_index >= len(self.monitors):
            return None
        return self.monitors[current_index]

    def _clear_selected_monitor(self) -> None:
        self.selected_key = None
        self.current_volume = None
        self.target_volume = None
        self._set_displayed_volume(None)
        self._hotkeys_ready = False
        self._volume_write_inflight = False
        self._pending_target_volume = None
        self._update_hotkey_state()

    def _current_target_volume(self) -> int | None:
        if self.target_volume is not None:
            return self.target_volume
        return self.current_volume

    def _run_background(
        self,
        busy_message: str,
        worker: Callable[[], Any],
        on_success: Callable[[Any], None],
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        if self._busy or self._closing:
            return

        self._set_busy(True, busy_message)

        def runner() -> None:
            try:
                result = worker()
            except Exception as exc:
                self._post_to_ui(lambda error=exc: self._background_failed(error, on_error))
            else:
                self._post_to_ui(lambda value=result: self._background_succeeded(value, on_success))

        threading.Thread(target=runner, name="ddc-gui-worker", daemon=True).start()

    def _background_succeeded(self, result: Any, on_success: Callable[[Any], None]) -> None:
        if self._closing:
            return

        self._busy = False
        on_success(result)
        self._apply_control_state()

    def _background_failed(
        self,
        exc: Exception,
        on_error: Callable[[Exception], None] | None,
    ) -> None:
        if self._closing:
            return

        self._busy = False
        if on_error is None:
            self._set_status(self._format_error(exc))
        else:
            on_error(exc)
        self._apply_control_state()

    def _request_volume_target(self, monitor_ref: MonitorRef, target_volume: int) -> None:
        target_volume = clamp(target_volume, 0, 100)
        self.target_volume = target_volume
        self._set_displayed_volume(target_volume)
        self._show_volume_overlay(target_volume)

        if self._volume_write_inflight:
            self._pending_target_volume = target_volume
            self._set_status(f"Queued volume {target_volume}%...")
            return

        self._start_volume_write(monitor_ref, target_volume)

    def _start_volume_write(self, monitor_ref: MonitorRef, target_volume: int) -> None:
        if self._closing:
            return

        self._volume_write_inflight = True
        self._pending_target_volume = None
        self._set_busy(True, f"Setting volume to {target_volume}%...")

        def runner() -> None:
            try:
                new_volume = set_monitor_volume(monitor_ref, target_volume)
            except Exception as exc:
                self._post_to_ui(lambda error=exc: self._finish_volume_write_error(error))
            else:
                self._post_to_ui(
                    lambda value=new_volume, key=monitor_ref.selection_key: self._finish_volume_write_success(key, value)
                )

        threading.Thread(target=runner, name="ddc-volume-write", daemon=True).start()

    def _finish_volume_write_success(self, selection_key: SelectionKey, new_volume: int) -> None:
        if self._closing:
            return

        self.current_volume = new_volume
        self._hotkeys_ready = True
        self._update_hotkey_state()

        next_target = self._pending_target_volume
        selected_monitor = self._selected_monitor()
        if (
            next_target is not None
            and selected_monitor is not None
            and selected_monitor.selection_key == selection_key
            and next_target != new_volume
        ):
            self._pending_target_volume = None
            self._start_volume_write(selected_monitor, next_target)
            return

        self._volume_write_inflight = False
        self._busy = False
        self.target_volume = new_volume
        self._set_displayed_volume(new_volume)
        self._show_volume_overlay(new_volume)

        monitor_name = selected_monitor.description if selected_monitor is not None else "Monitor"
        self._set_status(f"{monitor_name} volume: {new_volume}%")
        self._apply_control_state()

    def _finish_volume_write_error(self, exc: Exception) -> None:
        if self._closing:
            return

        self._volume_write_inflight = False
        self._pending_target_volume = None
        self._busy = False
        self.target_volume = self.current_volume
        self._set_displayed_volume(self.current_volume)
        self._set_status(self._format_error(exc))
        self._apply_control_state()

    def refresh_monitors(self) -> None:
        self._refresh_after_id = None
        selection_target = self.selected_key if self.selected_key is not None else self.preferred_selected_key
        self._hotkeys_ready = False
        self._update_hotkey_state()

        def worker() -> RefreshResult:
            monitors = enumerate_monitors()
            selected_index = pick_selected_monitor_index(monitors, selection_target)
            if selected_index is None:
                return monitors, None, None, None

            try:
                volume = read_monitor_volume(monitors[selected_index])
            except Exception as exc:
                return monitors, selected_index, None, exc
            return monitors, selected_index, volume, None

        def on_success(result: RefreshResult) -> None:
            monitors, selected_index, volume, volume_error = result
            self.monitors = monitors
            self.monitor_combo["values"] = [monitor_ref.display_name for monitor_ref in monitors]

            if not monitors or selected_index is None:
                self.monitor_var.set("")
                self._clear_selected_monitor()
                self._set_status("No DDC/CI monitors found.")
                return

            selected_monitor = monitors[selected_index]
            self.monitor_combo.current(selected_index)
            self._remember_selected_monitor(selected_monitor.selection_key)

            if volume_error is None:
                self.current_volume = volume
                self.target_volume = volume
                self._set_displayed_volume(volume)
                self._hotkeys_ready = True
                self._update_hotkey_state()
                self._set_status(
                    f"Ready. {len(monitors)} monitor(s) detected. Volume keys control {selected_monitor.description}."
                )
            else:
                self.current_volume = None
                self._set_displayed_volume(None)
                self._hotkeys_ready = False
                self._update_hotkey_state()
                self._set_status(self._format_error(volume_error))

        def on_error(exc: Exception) -> None:
            self.monitors = []
            self.monitor_combo["values"] = ()
            self.monitor_var.set("")
            self._clear_selected_monitor()
            self._set_status(self._format_error(exc))

        self._run_background("Searching for monitors...", worker, on_success, on_error)

    def on_monitor_selected(self, _event: Any = None) -> None:
        monitor_ref = self._selected_monitor()
        if monitor_ref is None or self._busy:
            return

        self._remember_selected_monitor(monitor_ref.selection_key)
        self.current_volume = None
        self.target_volume = None
        self._set_displayed_volume(None)
        self._hotkeys_ready = False
        self._update_hotkey_state()

        def worker() -> int:
            return read_monitor_volume(monitor_ref)

        def on_success(volume: int) -> None:
            self.current_volume = volume
            self.target_volume = volume
            self._set_displayed_volume(volume)
            self._hotkeys_ready = True
            self._update_hotkey_state()
            self._set_status(f"{monitor_ref.description} selected. Volume keys now control this monitor at {volume}%.")

        def on_error(exc: Exception) -> None:
            self.current_volume = None
            self.target_volume = None
            self._set_displayed_volume(None)
            self._hotkeys_ready = False
            self._update_hotkey_state()
            self._set_status(self._format_error(exc))

        self._run_background(f"Reading {monitor_ref.description} volume...", worker, on_success, on_error)

    def on_scale_moved(self, value: str) -> None:
        if self._ignore_scale_events:
            return
        self.volume_text_var.set(f"{clamp(round(float(value)), 0, 100)}%")

    def on_scale_released(self, _event: Any = None) -> None:
        monitor_ref = self._selected_monitor()
        if monitor_ref is None or self.current_volume is None or (self._busy and not self._volume_write_inflight):
            return

        target_volume = clamp(round(self.volume_var.get()), 0, 100)
        current_target = self._current_target_volume()
        if target_volume == current_target:
            self._show_volume_overlay(target_volume)
            return

        self._request_volume_target(monitor_ref, target_volume)

    def adjust_selected_volume(self, delta: int) -> None:
        monitor_ref = self._selected_monitor()
        if monitor_ref is None or self.current_volume is None or (self._busy and not self._volume_write_inflight):
            return

        base_volume = self._current_target_volume()
        if base_volume is None:
            return

        target_volume = clamp(base_volume + delta, 0, 100)
        if target_volume == base_volume:
            if delta < 0:
                self._set_status("Volume is already at 0%.")
            else:
                self._set_status("Volume is already at 100%.")
            self._show_volume_overlay(base_volume)
            return

        self._request_volume_target(monitor_ref, target_volume)

    def minimize_to_tray(self) -> None:
        if self._closing or self._in_tray or self._tray_icon is None:
            return
        self._tray_icon.show()
        self._in_tray = True
        self.root.withdraw()

    def restore_from_tray(self) -> None:
        if self._closing or not self._in_tray:
            return
        self._in_tray = False
        if self._tray_icon is not None:
            self._tray_icon.hide()
        self.root.deiconify()
        self.root.state("normal")
        apply_window_chrome(self.root, self.dark_mode)
        self.root.lift()
        self.root.focus_force()

    def on_window_unmap(self, _event: Any = None) -> None:
        if self._closing or self._in_tray or self._tray_icon is None:
            return
        self.root.after_idle(self._minimize_if_iconified)

    def _minimize_if_iconified(self) -> None:
        if self._closing or self._in_tray or self._tray_icon is None:
            return
        try:
            window_state = self.root.state()
        except tk.TclError:
            return
        if window_state == "iconic":
            self.minimize_to_tray()

    def on_close(self) -> None:
        self._closing = True
        self._hotkeys_ready = False
        self._update_hotkey_state()
        if self._tray_icon is not None:
            self._tray_icon.hide()
        if self._poll_after_id is not None:
            self.root.after_cancel(self._poll_after_id)
            self._poll_after_id = None
        if self._refresh_after_id is not None:
            self.root.after_cancel(self._refresh_after_id)
            self._refresh_after_id = None
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
        if self._tray_icon is not None:
            self._tray_icon.stop()
            self._tray_icon = None
        if self._overlay is not None:
            self._overlay.close()
            self._overlay = None
        self.root.destroy()
