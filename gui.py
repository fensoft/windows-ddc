from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Any, Callable, TypeAlias

from ddc import (
    MonitorRef,
    SavedMonitorSelection,
    SelectionMatch,
    SelectionMatchStatus,
    clamp,
    enumerate_monitors,
    match_selected_monitor,
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
from windows_platform import DisplayChangeListener, GlobalVolumeKeyListener, TrayIconController


RefreshResult: TypeAlias = tuple[list[MonitorRef], SelectionMatch, int | None, Exception | None]
WriteResult: TypeAlias = tuple[list[MonitorRef], int, int, SavedMonitorSelection]


class MonitorSelectionUnavailable(RuntimeError):
    def __init__(self, message: str, monitors: list[MonitorRef] | None = None) -> None:
        super().__init__(message)
        self.monitors = monitors


class DisplayTopologyChanged(RuntimeError):
    pass


class MonitorVolumeApp:
    STEP_SIZE = 1
    STEP_OPTIONS = (1, 2, 3)
    TRAY_TOOLTIP = "windows-ddc"
    DISPLAY_CHANGE_DEBOUNCE_MS = 500
    DDC_OPERATION_TIMEOUT_MS = 10_000
    REFRESH_RETRY_DELAYS_MS = (1000, 2000, 4000)

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
        self.selected_key: SavedMonitorSelection | None = None
        self.current_volume: int | None = None
        self.target_volume: int | None = None
        self.volume_step = self.STEP_SIZE
        self.app_icon_path: Path | None = None
        self._busy = False
        self._closing = False
        self._ignore_scale_events = False
        self._result_queue: queue.Queue[Callable[[], None]] = queue.Queue()
        self._hotkey_delta_queue: queue.Queue[int] = queue.Queue()
        self._hotkeys_ready = False
        self._hotkeys_enabled = False
        self._listener: GlobalVolumeKeyListener | None = None
        self._display_listener: DisplayChangeListener | None = None
        self._overlay: VolumeOverlay | None = None
        self._volume_write_inflight = False
        self._pending_target_volume: int | None = None
        self._tray_icon: TrayIconController | None = None
        self._in_tray = False
        self._poll_after_id: str | None = None
        self._refresh_after_id: str | None = None
        self._ddc_timeout_after_id: str | None = None
        self._ddc_operation_sequence = 0
        self._active_ddc_operation_id: int | None = None
        self._active_ddc_operation_kind: str | None = None
        self._ddc_operation_timed_out = False
        self._refresh_retry_index = 0
        self._refresh_requested = False
        self._refresh_requested_automatic = False
        self._topology_generation = 0
        self._topology_generation_lock = threading.Lock()
        self._topology_valid = threading.Event()
        self._control_unavailable_reason: str | None = "Monitor selection is not ready."

        self.monitor_var = tk.StringVar()
        self.volume_var = tk.DoubleVar(value=0.0)
        self.volume_text_var = tk.StringVar(value="--")
        self.volume_step_var = tk.StringVar(value=f"+{self.volume_step}")
        self.status_var = tk.StringVar(value="Searching for monitors...")

        self.app_icon_path = apply_app_icon(self.root)
        self._build_widgets()
        self._overlay = VolumeOverlay(self.root)
        apply_color_scheme(self.root, self.status_bar, self.dark_mode)
        self._lock_window_size()
        apply_window_chrome(self.root, self.dark_mode)
        self._apply_control_state()
        self._start_display_listener()
        self._start_tray_icon()
        self._start_minimized()
        self._start_keyboard_listener()
        self._poll_after_id = self.root.after(50, self._poll_queues)
        self._refresh_after_id = self.root.after(
            50,
            lambda: self._run_scheduled_refresh(automatic=False),
        )

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
            width=44,
        )
        self.monitor_combo.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        self.monitor_combo.bind("<<ComboboxSelected>>", self.on_monitor_selected)

        self.refresh_button = ttk.Button(content, text="Refresh", width=10, command=self.refresh_monitors)
        self.refresh_button.grid(row=1, column=3, sticky="e", padx=(8, 0), pady=(4, 0))

        ttk.Label(content, text="Volume:").grid(row=2, column=0, sticky="w", pady=(14, 0))

        ttk.Label(content, text="Step:").grid(row=2, column=1, sticky="e", pady=(14, 0))

        self.volume_step_combo = ttk.Combobox(
            content,
            textvariable=self.volume_step_var,
            values=tuple(f"+{step}" for step in self.STEP_OPTIONS),
            state="readonly",
            width=4,
        )
        self.volume_step_combo.grid(row=2, column=2, sticky="w", padx=(4, 8), pady=(14, 0))
        self.volume_step_combo.bind("<<ComboboxSelected>>", self.on_volume_step_selected)

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
            command=lambda: self.adjust_selected_volume(-self.volume_step),
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
            command=lambda: self.adjust_selected_volume(self.volume_step),
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
        width = max(self.root.winfo_reqwidth(), 520)
        height = self.root.winfo_reqheight()
        self.root.geometry(f"{width}x{height}")
        self.root.resizable(False, False)

    def _start_display_listener(self) -> None:
        self._display_listener = DisplayChangeListener(
            on_change=self._handle_display_change_from_thread,
            on_error=self._handle_display_listener_error_from_thread,
        )
        try:
            self._display_listener.start()
        except Exception as exc:
            self._display_listener = None
            self._topology_valid.clear()
            self._control_unavailable_reason = "Display-change protection is unavailable."
            self._set_status(f"Display-change listener failed: {self._format_error(exc)}")

    def _start_tray_icon(self) -> None:
        try:
            self._tray_icon = TrayIconController(
                tooltip=self.TRAY_TOOLTIP,
                on_restore=lambda: self._post_to_ui(self.restore_from_tray),
                on_exit=lambda: self._post_to_ui(self.on_close),
                on_error=self._handle_tray_error_from_thread,
                icon_path=self.app_icon_path,
            )
            self._tray_icon.start()
        except Exception as exc:
            self._tray_icon = None
            error_message = self._format_error(exc).rstrip(".")
            self._set_status(f"Tray icon failed: {error_message}. The main window will remain available.")

    def _start_minimized(self) -> None:
        if self._tray_icon is None:
            return
        self.minimize_to_tray()

    def _start_keyboard_listener(self) -> None:
        self._listener = GlobalVolumeKeyListener(
            on_delta=self._queue_hotkey_delta,
            should_consume=self._should_consume_volume_keys,
            on_error=self._handle_listener_error_from_thread,
            step=self.volume_step,
            on_unavailable=self._queue_unavailable_hotkey_notice,
            should_report_unavailable=self._should_report_unavailable_hotkey,
        )
        try:
            self._listener.start()
        except Exception as exc:
            self._listener = None
            self._set_status(self._format_error(exc))

    def on_volume_step_selected(self, _event: Any = None) -> None:
        try:
            selected_step = int(self.volume_step_var.get().removeprefix("+"))
        except ValueError:
            selected_step = self.STEP_SIZE

        if selected_step not in self.STEP_OPTIONS:
            selected_step = self.STEP_SIZE
        self.volume_step = selected_step
        self.volume_step_var.set(f"+{selected_step}")
        if self._listener is not None:
            self._listener.set_step(selected_step)

    def _handle_display_change_from_thread(self) -> None:
        self._invalidate_topology_generation()
        self._post_to_ui(self._handle_display_change)

    def _handle_display_listener_error_from_thread(self, exc: Exception) -> None:
        self._invalidate_topology_generation()
        self._post_to_ui(lambda error=exc: self._handle_display_listener_error(error))

    def _handle_display_listener_error(self, exc: Exception) -> None:
        self._hotkeys_ready = False
        self.current_volume = None
        self.target_volume = None
        self._pending_target_volume = None
        self._control_unavailable_reason = "Display-change protection is unavailable."
        self._update_hotkey_state()
        self._set_displayed_volume(None)
        self._set_status(f"Display-change listener failed: {self._format_error(exc)}")
        self._apply_control_state()

    def _handle_display_change(self) -> None:
        if self._closing:
            return
        self._hotkeys_ready = False
        self.current_volume = None
        self.target_volume = None
        self._pending_target_volume = None
        self._control_unavailable_reason = "Display configuration changed; checking the selected monitor."
        self._update_hotkey_state()
        self._set_displayed_volume(None)
        if self._listener is not None:
            self._listener.reset_unavailable_notice()
        self._set_status("Display configuration changed. Revalidating the selected monitor...")
        self._apply_control_state()
        self._refresh_retry_index = 0
        self._schedule_refresh(self.DISPLAY_CHANGE_DEBOUNCE_MS, automatic=True)

    def _handle_listener_error_from_thread(self, exc: Exception) -> None:
        self._post_to_ui(lambda error=exc: self._handle_listener_error(error))

    def _handle_listener_error(self, exc: Exception) -> None:
        self._hotkeys_ready = False
        self._update_hotkey_state()
        self._set_status(f"Volume-key listener failed: {self._format_error(exc)}")

    def _handle_tray_error_from_thread(self, exc: Exception) -> None:
        self._post_to_ui(lambda error=exc: self._handle_tray_error(error))

    def _handle_tray_error(self, exc: Exception) -> None:
        if self._closing:
            return
        self._in_tray = False
        if self._tray_icon is not None:
            self._tray_icon.hide()
        self._show_main_window()
        error_message = self._format_error(exc).rstrip(".")
        self._set_status(f"Tray icon failed: {error_message}. The main window was restored.")

    def _invalidate_topology_generation(self) -> None:
        self._topology_valid.clear()
        with self._topology_generation_lock:
            self._topology_generation += 1

    def _current_topology_generation(self) -> int:
        with self._topology_generation_lock:
            return self._topology_generation

    def _is_topology_generation_current(self, generation: int) -> bool:
        return generation == self._current_topology_generation()

    def _display_listener_available(self) -> bool:
        return self._display_listener is not None and self._display_listener.is_active

    def _control_ready(self) -> bool:
        return (
            not self._closing
            and self._display_listener_available()
            and self._topology_valid.is_set()
            and self.selected_key is not None
            and self.current_volume is not None
        )

    def _queue_hotkey_delta(self, delta: int) -> None:
        if not self._closing:
            self._hotkey_delta_queue.put(delta)

    def _queue_unavailable_hotkey_notice(self) -> None:
        self._post_to_ui(self._show_unavailable_error)

    def _should_report_unavailable_hotkey(self) -> bool:
        return (
            not self._closing
            and self._control_unavailable_reason is not None
            and (self.selected_key is not None or self.preferred_selected_key is not None)
        )

    def _should_consume_volume_keys(self) -> bool:
        return (
            self._hotkeys_enabled
            and self._topology_valid.is_set()
            and not self._closing
            and self._listener is not None
            and self._listener.is_active
        )

    def _post_to_ui(self, callback: Callable[[], None]) -> None:
        if not self._closing:
            self._result_queue.put(callback)

    def _poll_queues(self) -> None:
        self._poll_after_id = None
        if self._closing:
            return

        try:
            while True:
                try:
                    callback = self._result_queue.get_nowait()
                except queue.Empty:
                    break
                try:
                    callback()
                except Exception as exc:
                    self._report_ui_callback_error(exc)

            if self._hotkeys_enabled and (not self._busy or self._volume_write_inflight):
                pending_delta = 0
                while True:
                    try:
                        pending_delta += self._hotkey_delta_queue.get_nowait()
                    except queue.Empty:
                        break
                if pending_delta:
                    try:
                        self.adjust_selected_volume(pending_delta)
                    except Exception as exc:
                        self._report_ui_callback_error(exc)
            elif not self._hotkeys_enabled:
                while True:
                    try:
                        self._hotkey_delta_queue.get_nowait()
                    except queue.Empty:
                        break
        except Exception as exc:
            self._report_ui_callback_error(exc)
        finally:
            if not self._closing:
                try:
                    self._poll_after_id = self.root.after(50, self._poll_queues)
                except tk.TclError:
                    self._poll_after_id = None

    def _report_ui_callback_error(self, exc: Exception) -> None:
        message = f"Internal UI callback failed: {self._format_error(exc)}"
        try:
            self._topology_valid.clear()
            self._hotkeys_ready = False
            self.current_volume = None
            self.target_volume = None
            if self._active_ddc_operation_id is None:
                self._busy = False
                self._volume_write_inflight = False
                self._pending_target_volume = None
            self._control_unavailable_reason = (
                "An internal UI operation failed; monitor control is disabled until Refresh succeeds."
            )
            self._update_hotkey_state()
            self._set_displayed_volume(None)
            self._set_status(message)
            self._apply_control_state()
        except Exception:
            pass

        try:
            self.root.report_callback_exception(type(exc), exc, exc.__traceback__)
        except Exception:
            print(message, file=sys.stderr)

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
        self._set_widget_enabled(self.refresh_button, not self._busy)
        self._set_widget_enabled(self.monitor_combo, has_monitors and not self._busy)
        volume_controls_enabled = self._control_ready() and (
            not self._busy or self._volume_write_inflight
        )
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
            and self._control_ready()
            and self._listener is not None
            and self._listener.is_active
        )

    def _remember_selected_monitor(self, selection: SavedMonitorSelection) -> None:
        self.selected_key = selection
        should_save = self.preferred_selected_key != selection
        self.preferred_selected_key = selection
        self._update_hotkey_state()
        if not should_save:
            return
        try:
            save_selected_monitor_key(selection)
        except (OSError, ValueError):
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
        if volume is not None:
            self._overlay.show(clamp(volume, 0, 100))

    def _show_unavailable_error(self, message: str | None = None) -> None:
        reason = message or self._control_unavailable_reason or "Selected monitor is unavailable."
        self._set_status(reason)
        if not self._closing and self._overlay is not None:
            self._overlay.show_error(reason)

    def _selected_monitor(self) -> MonitorRef | None:
        current_index = self.monitor_combo.current()
        if current_index < 0 or current_index >= len(self.monitors):
            return None
        return self.monitors[current_index]

    def _clear_active_selection(self) -> None:
        self.selected_key = None
        self.current_volume = None
        self.target_volume = None
        self._set_displayed_volume(None)
        self._hotkeys_ready = False
        self._pending_target_volume = None
        self._topology_valid.clear()
        self._update_hotkey_state()

    def _current_target_volume(self) -> int | None:
        if self.target_volume is not None:
            return self.target_volume
        return self.current_volume

    def _update_monitor_list(self, monitors: list[MonitorRef], selected_index: int | None) -> None:
        self.monitors = monitors
        self.monitor_combo["values"] = [monitor_ref.display_name for monitor_ref in monitors]
        if selected_index is None:
            self.monitor_var.set("")
        else:
            self.monitor_combo.current(selected_index)

    @staticmethod
    def _selection_error_message(status: SelectionMatchStatus) -> str:
        if status == SelectionMatchStatus.AMBIGUOUS:
            return "Selected monitor identity is ambiguous. Select the monitor again."
        if status == SelectionMatchStatus.UNVERIFIABLE:
            return "The monitor identity could not be verified; volume control is disabled."
        if status == SelectionMatchStatus.NEEDS_SELECTION:
            return "Select a monitor before monitor-volume control can start."
        return "Selected monitor was not found. Reconnect it or select another monitor."

    def _schedule_refresh(self, delay_ms: int, automatic: bool) -> None:
        if self._closing:
            return
        if self._refresh_after_id is not None:
            self.root.after_cancel(self._refresh_after_id)
        self._refresh_after_id = self.root.after(
            delay_ms,
            lambda: self._run_scheduled_refresh(automatic=automatic),
        )

    def _run_scheduled_refresh(self, automatic: bool) -> None:
        self._refresh_after_id = None
        self.refresh_monitors(automatic=automatic)

    def _schedule_next_refresh_retry(self) -> None:
        if self._refresh_retry_index >= len(self.REFRESH_RETRY_DELAYS_MS):
            return
        delay = self.REFRESH_RETRY_DELAYS_MS[self._refresh_retry_index]
        self._refresh_retry_index += 1
        self._schedule_refresh(delay, automatic=True)

    def _run_deferred_refresh(self) -> None:
        if not self._refresh_requested or self._busy or self._closing:
            return
        automatic = self._refresh_requested_automatic
        self._refresh_requested = False
        self._refresh_requested_automatic = False
        if self._refresh_after_id is not None:
            self.root.after_cancel(self._refresh_after_id)
            self._refresh_after_id = None
        self.refresh_monitors(automatic=automatic)

    def _begin_ddc_operation(self, kind: str) -> int:
        if self._active_ddc_operation_id is not None:
            raise RuntimeError("A DDC operation is already active.")
        self._ddc_operation_sequence += 1
        operation_id = self._ddc_operation_sequence
        self._active_ddc_operation_id = operation_id
        self._active_ddc_operation_kind = kind
        self._ddc_operation_timed_out = False
        self._ddc_timeout_after_id = self.root.after(
            self.DDC_OPERATION_TIMEOUT_MS,
            lambda token=operation_id: self._handle_ddc_operation_timeout(token),
        )
        return operation_id

    def _accept_ddc_completion(self, operation_id: int | None) -> bool:
        # Optional IDs keep direct, hardware-free unit calls to the completion
        # helpers useful while every real worker supplies a token.
        if operation_id is None:
            return True
        if operation_id != self._active_ddc_operation_id:
            return False

        timed_out = self._ddc_operation_timed_out
        if self._ddc_timeout_after_id is not None:
            try:
                self.root.after_cancel(self._ddc_timeout_after_id)
            except tk.TclError:
                pass
        self._ddc_timeout_after_id = None
        self._active_ddc_operation_id = None
        self._active_ddc_operation_kind = None
        self._ddc_operation_timed_out = False

        if timed_out:
            self._finish_timed_out_ddc_operation()
            return False
        return True

    def _handle_ddc_operation_timeout(self, operation_id: int) -> None:
        if self._closing or operation_id != self._active_ddc_operation_id:
            return

        operation_kind = self._active_ddc_operation_kind or "DDC"
        self._ddc_timeout_after_id = None
        self._ddc_operation_timed_out = True
        self._invalidate_topology_generation()
        self._hotkeys_ready = False
        self.current_volume = None
        self.target_volume = None
        self._pending_target_volume = None
        self._update_hotkey_state()
        self._set_displayed_volume(None)
        reason = (
            f"{operation_kind} timed out. Monitor state is unknown; control remains disabled "
            "until the DDC call returns and Refresh succeeds. Restart the app if it does not return."
        )
        self._control_unavailable_reason = reason
        self._show_unavailable_error(reason)
        self._apply_control_state()

    def _finish_timed_out_ddc_operation(self) -> None:
        if self._closing:
            return
        self._volume_write_inflight = False
        self._pending_target_volume = None
        self._busy = False
        self._refresh_retry_index = 0
        self._apply_control_state()
        if self._refresh_requested:
            self._run_deferred_refresh()
        else:
            self._schedule_refresh(self.DISPLAY_CHANGE_DEBOUNCE_MS, automatic=True)

    def refresh_monitors(
        self,
        automatic: bool = False,
        selection_target: SavedMonitorSelection | None = None,
    ) -> None:
        if self._refresh_after_id is not None:
            self.root.after_cancel(self._refresh_after_id)
            self._refresh_after_id = None
        if self._busy or self._closing:
            self._refresh_requested = True
            self._refresh_requested_automatic = self._refresh_requested_automatic or automatic
            return

        if not automatic:
            self._refresh_retry_index = 0
        if selection_target is None:
            selection_target = self.selected_key or self.preferred_selected_key

        generation = self._current_topology_generation()
        self._topology_valid.clear()
        self._hotkeys_ready = False
        self.current_volume = None
        self.target_volume = None
        self._set_displayed_volume(None)
        if selection_target is not None:
            self._control_unavailable_reason = "Selected monitor is being revalidated."
            if self._listener is not None:
                self._listener.reset_unavailable_notice()
        self._update_hotkey_state()
        self._set_busy(True, "Searching for monitors...")
        operation_id = self._begin_ddc_operation("Monitor discovery")

        def runner() -> None:
            try:
                monitors = enumerate_monitors()
                match = match_selected_monitor(monitors, selection_target)
                if match.status != SelectionMatchStatus.FOUND or match.index is None:
                    result: RefreshResult = monitors, match, None, None
                else:
                    try:
                        volume = read_monitor_volume(monitors[match.index])
                    except Exception as exc:
                        result = monitors, match, None, exc
                    else:
                        result = monitors, match, volume, None
            except Exception as exc:
                self._post_to_ui(
                    lambda error=exc, token=generation, retry=automatic, operation=operation_id: self._finish_refresh_error(
                        error,
                        token,
                        retry,
                        operation,
                    )
                )
            else:
                self._post_to_ui(
                    lambda value=result, token=generation, retry=automatic, operation=operation_id: self._finish_refresh(
                        value,
                        token,
                        retry,
                        operation,
                    )
                )

        try:
            threading.Thread(target=runner, name="ddc-gui-worker", daemon=True).start()
        except Exception as exc:
            self._finish_refresh_error(exc, generation, automatic, operation_id)

    def _finish_refresh(
        self,
        result: RefreshResult,
        generation: int,
        automatic: bool,
        operation_id: int | None = None,
    ) -> None:
        if self._closing:
            return
        if not self._accept_ddc_completion(operation_id):
            return
        self._busy = False
        if not self._is_topology_generation_current(generation):
            self._apply_control_state()
            self._schedule_refresh(self.DISPLAY_CHANGE_DEBOUNCE_MS, automatic=True)
            return

        monitors, match, volume, volume_error = result
        selected_index = match.index if match.status == SelectionMatchStatus.FOUND else None
        self._update_monitor_list(monitors, selected_index)

        if match.status != SelectionMatchStatus.FOUND or selected_index is None:
            self._clear_active_selection()
            if not monitors:
                reason = "No DDC/CI monitors found."
            else:
                reason = self._selection_error_message(match.status)
            self._control_unavailable_reason = reason
            self._set_status(reason)
            self._apply_control_state()
            if automatic and match.status not in (
                SelectionMatchStatus.AMBIGUOUS,
                SelectionMatchStatus.NEEDS_SELECTION,
            ):
                self._schedule_next_refresh_retry()
            self._run_deferred_refresh()
            return

        selected_monitor = monitors[selected_index]
        selection = selected_monitor.selection_key
        if selection is None:
            self._clear_active_selection()
            self._control_unavailable_reason = self._selection_error_message(
                SelectionMatchStatus.UNVERIFIABLE
            )
            self._set_status(self._control_unavailable_reason)
            self._apply_control_state()
            return

        if volume_error is not None or volume is None:
            self.selected_key = selection
            self.current_volume = None
            self.target_volume = None
            self._hotkeys_ready = False
            self._topology_valid.clear()
            self._update_hotkey_state()
            self._set_displayed_volume(None)
            reason = self._format_error(volume_error or RuntimeError("Monitor volume is unavailable."))
            self._control_unavailable_reason = reason
            self._set_status(reason)
            self._apply_control_state()
            if automatic:
                self._schedule_next_refresh_retry()
            return

        self.current_volume = volume
        self.target_volume = volume
        self._set_displayed_volume(volume)
        self._remember_selected_monitor(selection)
        if self._display_listener_available():
            self._topology_valid.set()
            self._hotkeys_ready = True
            self._control_unavailable_reason = None
        else:
            self._topology_valid.clear()
            self._hotkeys_ready = False
            self._control_unavailable_reason = "Display-change protection is unavailable."
        self._update_hotkey_state()
        if self._listener is not None:
            self._listener.reset_unavailable_notice()
        if self._control_ready():
            self._set_status(
                f"Ready. {len(monitors)} monitor(s) detected. Volume keys control {selected_monitor.description}."
            )
        else:
            self._set_status(
                f"{selected_monitor.description} detected at {volume}%, but display-change protection is unavailable."
            )
        self._apply_control_state()
        self._run_deferred_refresh()

    def _finish_refresh_error(
        self,
        exc: Exception,
        generation: int,
        automatic: bool,
        operation_id: int | None = None,
    ) -> None:
        if self._closing:
            return
        if not self._accept_ddc_completion(operation_id):
            return
        self._busy = False
        if not self._is_topology_generation_current(generation):
            self._schedule_refresh(self.DISPLAY_CHANGE_DEBOUNCE_MS, automatic=True)
            return
        self.monitors = []
        self.monitor_combo["values"] = ()
        self.monitor_var.set("")
        self._clear_active_selection()
        reason = self._format_error(exc)
        self._control_unavailable_reason = reason
        self._set_status(reason)
        self._apply_control_state()
        if automatic:
            self._schedule_next_refresh_retry()
        self._run_deferred_refresh()

    def on_monitor_selected(self, _event: Any = None) -> None:
        monitor_ref = self._selected_monitor()
        if monitor_ref is None or self._busy:
            return
        selection = monitor_ref.selection_key
        if selection is None:
            self._clear_active_selection()
            reason = "The selected monitor has no verifiable Windows identity."
            self._control_unavailable_reason = reason
            self._show_unavailable_error(reason)
            self._apply_control_state()
            return
        self.refresh_monitors(selection_target=selection)

    def _request_volume_target(self, target_volume: int) -> None:
        if not self._control_ready() or self.selected_key is None:
            self._show_unavailable_error()
            return

        target_volume = clamp(target_volume, 0, 100)
        self.target_volume = target_volume
        self._set_displayed_volume(target_volume)
        self._show_volume_overlay(target_volume)

        if self._volume_write_inflight:
            self._pending_target_volume = target_volume
            self._set_status(f"Queued volume {target_volume}%...")
            return

        self._start_volume_write(self.selected_key, target_volume)

    def _start_volume_write(
        self,
        selection: SavedMonitorSelection,
        target_volume: int,
    ) -> None:
        if self._closing or not self._control_ready():
            self._show_unavailable_error()
            return

        generation = self._current_topology_generation()
        self._volume_write_inflight = True
        self._pending_target_volume = None
        self._set_busy(True, f"Validating monitor and setting volume to {target_volume}%...")
        operation_id = self._begin_ddc_operation("Monitor volume write")

        def runner() -> None:
            try:
                monitors = enumerate_monitors()
                match = match_selected_monitor(monitors, selection)
                if match.status != SelectionMatchStatus.FOUND or match.index is None:
                    raise MonitorSelectionUnavailable(
                        self._selection_error_message(match.status),
                        monitors,
                    )
                if not self._is_topology_generation_current(generation) or not self._topology_valid.is_set():
                    raise DisplayTopologyChanged(
                        "Display changed while validating the selected monitor."
                    )
                monitor_ref = monitors[match.index]
                fresh_selection = monitor_ref.selection_key
                if fresh_selection is None:
                    raise MonitorSelectionUnavailable(
                        "The selected monitor identity could not be verified.",
                        monitors,
                    )
                new_volume = set_monitor_volume(monitor_ref, target_volume)
                result: WriteResult = monitors, match.index, new_volume, fresh_selection
            except Exception as exc:
                self._post_to_ui(
                    lambda error=exc, token=generation, operation=operation_id: self._finish_volume_write_error(
                        error,
                        token,
                        operation,
                    )
                )
            else:
                self._post_to_ui(
                    lambda value=result, token=generation, operation=operation_id: self._finish_volume_write_success(
                        value,
                        token,
                        operation,
                    )
                )

        try:
            threading.Thread(target=runner, name="ddc-volume-write", daemon=True).start()
        except Exception as exc:
            self._finish_volume_write_error(exc, generation, operation_id)

    def _finish_volume_write_success(
        self,
        result: WriteResult,
        generation: int,
        operation_id: int | None = None,
    ) -> None:
        if self._closing:
            return
        if not self._accept_ddc_completion(operation_id):
            return
        monitors, selected_index, new_volume, selection = result
        if not self._is_topology_generation_current(generation) or not self._topology_valid.is_set():
            self._finish_volume_write_error(
                DisplayTopologyChanged(
                    "Display changed while setting volume; monitor volume may have changed."
                ),
                generation,
            )
            return

        self._update_monitor_list(monitors, selected_index)
        self.current_volume = new_volume
        self._remember_selected_monitor(selection)
        self._hotkeys_ready = True
        self._control_unavailable_reason = None
        self._update_hotkey_state()

        next_target = self._pending_target_volume
        if next_target is not None and next_target != new_volume:
            # Keep the newest requested value authoritative while its follow-up
            # write is validated. Resetting this to the older readback makes
            # rapid +/- events calculate from a value that is one write behind.
            self.target_volume = next_target
            self._pending_target_volume = None
            self._volume_write_inflight = False
            self._busy = False
            self._start_volume_write(selection, next_target)
            return

        self.target_volume = new_volume
        self._volume_write_inflight = False
        self._pending_target_volume = None
        self._busy = False
        self._set_displayed_volume(new_volume)
        self._show_volume_overlay(new_volume)
        self._set_status(f"{selection.description} volume: {new_volume}%")
        self._apply_control_state()
        self._run_deferred_refresh()

    def _finish_volume_write_error(
        self,
        exc: Exception,
        generation: int | None = None,
        operation_id: int | None = None,
    ) -> None:
        if self._closing:
            return
        if not self._accept_ddc_completion(operation_id):
            return

        if isinstance(exc, MonitorSelectionUnavailable) and exc.monitors is not None:
            self._update_monitor_list(exc.monitors, None)
        self._volume_write_inflight = False
        self._pending_target_volume = None
        self._busy = False
        self.current_volume = None
        self.target_volume = None
        self._hotkeys_ready = False
        self._topology_valid.clear()
        self._update_hotkey_state()
        self._set_displayed_volume(None)
        error_message = self._format_error(exc).rstrip(".")
        if isinstance(exc, MonitorSelectionUnavailable):
            reason = f"{error_message}."
        elif isinstance(exc, DisplayTopologyChanged):
            reason = f"{error_message}."
        else:
            reason = f"{error_message}. Monitor volume may have changed; control is disabled."
        self._control_unavailable_reason = reason
        self._show_unavailable_error(reason)
        self._apply_control_state()
        self._refresh_retry_index = 0
        if self._refresh_requested:
            self._run_deferred_refresh()
        else:
            self._schedule_refresh(self.DISPLAY_CHANGE_DEBOUNCE_MS, automatic=True)

    def on_scale_moved(self, value: str) -> None:
        if self._ignore_scale_events:
            return
        self.volume_text_var.set(f"{clamp(round(float(value)), 0, 100)}%")

    def on_scale_released(self, _event: Any = None) -> None:
        if not self._control_ready() or (self._busy and not self._volume_write_inflight):
            self._show_unavailable_error()
            return

        target_volume = clamp(round(self.volume_var.get()), 0, 100)
        current_target = self._current_target_volume()
        if target_volume == current_target:
            self._show_volume_overlay(target_volume)
            return

        self._request_volume_target(target_volume)

    def adjust_selected_volume(self, delta: int) -> None:
        if not self._control_ready() or (self._busy and not self._volume_write_inflight):
            self._show_unavailable_error()
            return

        base_volume = self._current_target_volume()
        if base_volume is None:
            self._show_unavailable_error()
            return

        target_volume = clamp(base_volume + delta, 0, 100)
        if target_volume == base_volume:
            if delta < 0:
                self._set_status("Volume is already at 0%.")
            else:
                self._set_status("Volume is already at 100%.")
            self._show_volume_overlay(base_volume)
            return

        self._request_volume_target(target_volume)

    def minimize_to_tray(self) -> None:
        if self._closing or self._in_tray or self._tray_icon is None:
            return
        try:
            self._tray_icon.show()
        except Exception as exc:
            self._handle_tray_error(exc)
            return
        self._in_tray = True
        self.root.withdraw()

    def _show_main_window(self) -> None:
        self.root.deiconify()
        self.root.state("normal")
        apply_window_chrome(self.root, self.dark_mode)
        self.root.lift()
        self.root.focus_force()

    def restore_from_tray(self) -> None:
        if self._closing or not self._in_tray:
            return
        self._in_tray = False
        if self._tray_icon is not None:
            self._tray_icon.hide()
        self._show_main_window()

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
        self._topology_valid.clear()
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
        if self._ddc_timeout_after_id is not None:
            self.root.after_cancel(self._ddc_timeout_after_id)
            self._ddc_timeout_after_id = None
        shutdown_failures: list[str] = []
        if self._listener is not None:
            self._stop_native_controller("Volume-key listener", self._listener, shutdown_failures)
            self._listener = None
        if self._display_listener is not None:
            self._stop_native_controller(
                "Display-change listener",
                self._display_listener,
                shutdown_failures,
            )
            self._display_listener = None
        if self._tray_icon is not None:
            self._stop_native_controller("Tray controller", self._tray_icon, shutdown_failures)
            self._tray_icon = None
        if shutdown_failures:
            message = "Shutdown warning: " + "; ".join(shutdown_failures)
            print(message, file=sys.stderr)
            try:
                self._set_status(message)
                self.root.update_idletasks()
            except Exception:
                pass
        if self._overlay is not None:
            self._overlay.close()
            self._overlay = None
        self.root.destroy()

    @staticmethod
    def _stop_native_controller(
        name: str,
        controller: Any,
        failures: list[str],
    ) -> None:
        try:
            stopped = controller.stop()
        except Exception as exc:
            message = str(exc).strip() or exc.__class__.__name__
            failures.append(f"{name} stop failed: {message}")
        else:
            if not stopped:
                failures.append(f"{name} did not stop before the timeout")
