from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk

from diagnostics import get_logger
from windows_platform import (
    DisplayArea,
    configure_no_activate_window,
    get_overlay_display_area,
    get_toplevel_window_handle,
    show_window_no_activate,
)


OVERLAY_BG = "#111111"
OVERLAY_BORDER = "#2A2A2A"
OVERLAY_TEXT = "#FFFFFF"
OVERLAY_SUBTEXT = "#D0D0D0"
OVERLAY_ACCENT = "#4CC2FF"
OVERLAY_ERROR = "#FF6B6B"
OVERLAY_TRACK = "#2A2A2A"
LIGHT_OVERLAY_BG = "#F7F7F7"
LIGHT_OVERLAY_BORDER = "#C8C8C8"
LIGHT_OVERLAY_TEXT = "#111111"
LIGHT_OVERLAY_SUBTEXT = "#404040"
LIGHT_OVERLAY_ACCENT = "#0067C0"
LIGHT_OVERLAY_ERROR = "#B10E1E"
LIGHT_OVERLAY_TRACK = "#D8D8D8"
AUTO_HIDE_MS = 1400
ERROR_AUTO_HIDE_MS = 2800
PROGRESS_STYLE = "VolumeOverlay.Horizontal.TProgressbar"
OVERLAY_BOTTOM_MARGIN = 88
OVERLAY_SIDE_MARGIN = 24
OVERLAY_CONTENT_PADX = 12
OVERLAY_CONTENT_PADY = 10
OVERLAY_LABEL_FONT = ("Segoe UI", 9)
OVERLAY_VALUE_FONT = ("Segoe UI", 20, "bold")
OVERLAY_BAR_LENGTH = 176
OVERLAY_BAR_THICKNESS = 5
OVERLAY_ERROR_WRAP = 240
LOGGER = get_logger(__name__)


@dataclass(frozen=True)
class OverlayGeometry:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class OverlayPalette:
    background: str
    border: str
    text: str
    subtext: str
    accent: str
    error: str
    track: str
    alpha: float


def calculate_overlay_geometry(
    requested_width: int,
    requested_height: int,
    display_area: DisplayArea,
) -> OverlayGeometry:
    work_area = display_area.work_area
    scale_percent = max(100, display_area.scale_percent)
    side_margin = round(OVERLAY_SIDE_MARGIN * scale_percent / 100)
    bottom_margin = round(OVERLAY_BOTTOM_MARGIN * scale_percent / 100)
    top_margin = round(32 * scale_percent / 100)

    available_width = max(1, work_area.width - (2 * side_margin))
    available_height = max(1, work_area.height - top_margin - bottom_margin)
    width = min(max(1, requested_width), available_width)
    height = min(max(1, requested_height), available_height)
    x = work_area.left + ((work_area.width - width) // 2)
    y = work_area.bottom - bottom_margin - height
    y = max(work_area.top + top_margin, min(y, work_area.bottom - height))
    return OverlayGeometry(x=x, y=y, width=width, height=height)


class VolumeOverlay:
    def __init__(
        self,
        root: tk.Tk,
        dark_mode: bool = True,
        high_contrast: bool = False,
    ) -> None:
        self.root = root
        self._hide_after_id: str | None = None
        self._style = ttk.Style(root)
        self._palette = self._get_palette(dark_mode, high_contrast)

        self.window = tk.Toplevel(root, takefocus=False)
        self.window.withdraw()
        self.window.overrideredirect(True)
        try:
            self.window.attributes("-toolwindow", True)
        except tk.TclError:
            pass

        self.title_var = tk.StringVar(value="Volume")
        self.volume_var = tk.StringVar(value="0%")
        self.error_var = tk.StringVar(value="")

        self.border = tk.Frame(self.window, bd=0, highlightthickness=0)
        self.border.pack()

        self.content = tk.Frame(
            self.border,
            padx=OVERLAY_CONTENT_PADX,
            pady=OVERLAY_CONTENT_PADY,
        )
        self.content.pack(padx=1, pady=1)

        self.title_label = tk.Label(
            self.content,
            textvariable=self.title_var,
            font=OVERLAY_LABEL_FONT,
        )
        self.title_label.pack(anchor="w")

        self.value_label = tk.Label(
            self.content,
            textvariable=self.volume_var,
            font=OVERLAY_VALUE_FONT,
        )
        self.value_label.pack(anchor="w", pady=(1, 8))

        self.error_label = tk.Label(
            self.content,
            textvariable=self.error_var,
            font=OVERLAY_LABEL_FONT,
            justify="left",
            wraplength=OVERLAY_ERROR_WRAP,
        )

        self.progress = ttk.Progressbar(
            self.content,
            style=PROGRESS_STYLE,
            orient=tk.HORIZONTAL,
            mode="determinate",
            length=OVERLAY_BAR_LENGTH,
            maximum=100,
        )
        self.progress.pack(fill="x")

        self.apply_theme(dark_mode, high_contrast)
        self.window.update_idletasks()
        self._configure_no_activate()

    @staticmethod
    def _get_palette(dark_mode: bool, high_contrast: bool) -> OverlayPalette:
        if high_contrast:
            return OverlayPalette(
                background="SystemWindow",
                border="SystemWindowText",
                text="SystemWindowText",
                subtext="SystemWindowText",
                accent="SystemHighlight",
                error="SystemWindowText",
                track="SystemWindow",
                alpha=1.0,
            )
        if dark_mode:
            return OverlayPalette(
                background=OVERLAY_BG,
                border=OVERLAY_BORDER,
                text=OVERLAY_TEXT,
                subtext=OVERLAY_SUBTEXT,
                accent=OVERLAY_ACCENT,
                error=OVERLAY_ERROR,
                track=OVERLAY_TRACK,
                alpha=0.7,
            )
        return OverlayPalette(
            background=LIGHT_OVERLAY_BG,
            border=LIGHT_OVERLAY_BORDER,
            text=LIGHT_OVERLAY_TEXT,
            subtext=LIGHT_OVERLAY_SUBTEXT,
            accent=LIGHT_OVERLAY_ACCENT,
            error=LIGHT_OVERLAY_ERROR,
            track=LIGHT_OVERLAY_TRACK,
            alpha=0.85,
        )

    def apply_theme(self, dark_mode: bool, high_contrast: bool = False) -> None:
        self._palette = self._get_palette(dark_mode, high_contrast)
        palette = self._palette
        self.window.configure(bg=palette.border)
        self.border.configure(bg=palette.border)
        self.content.configure(bg=palette.background)
        self.title_label.configure(bg=palette.background, fg=palette.subtext)
        self.value_label.configure(bg=palette.background, fg=palette.text)
        self.error_label.configure(bg=palette.background, fg=palette.text)
        try:
            self.window.attributes("-alpha", palette.alpha)
        except tk.TclError:
            pass
        self._style.configure(
            PROGRESS_STYLE,
            background=palette.accent,
            troughcolor=palette.track,
            bordercolor=palette.track,
            lightcolor=palette.accent,
            darkcolor=palette.accent,
            thickness=OVERLAY_BAR_THICKNESS,
        )

    def show(
        self,
        volume: int,
        preferred_display_device_name: str | None = None,
    ) -> None:
        volume = max(0, min(volume, 100))
        self.title_var.set("Volume")
        self.volume_var.set(f"{volume}%")
        self.value_label.configure(fg=self._palette.text)
        self.error_var.set("")
        self.error_label.pack_forget()
        if not self.progress.winfo_manager():
            self.progress.pack(fill="x")
        self.progress.configure(value=volume)
        self._show_window(AUTO_HIDE_MS, preferred_display_device_name)

    def show_error(
        self,
        message: str,
        preferred_display_device_name: str | None = None,
    ) -> None:
        self.title_var.set("Monitor volume")
        self.volume_var.set("Unavailable")
        self.value_label.configure(fg=self._palette.error)
        self.error_var.set(message.strip() or "Selected monitor is unavailable.")
        self.progress.pack_forget()
        if not self.error_label.winfo_manager():
            self.error_label.pack(anchor="w")
        self._show_window(ERROR_AUTO_HIDE_MS, preferred_display_device_name)

    def _show_window(
        self,
        auto_hide_ms: int,
        preferred_display_device_name: str | None,
    ) -> None:
        if self._hide_after_id is not None:
            self.window.after_cancel(self._hide_after_id)
            self._hide_after_id = None

        placement = self._position_window(preferred_display_device_name)
        hwnd = self._configure_no_activate()
        if placement is None or not hwnd:
            self.window.withdraw()
            return

        self.window.deiconify()
        if not show_window_no_activate(
            hwnd,
            placement.x,
            placement.y,
            placement.width,
            placement.height,
        ):
            LOGGER.warning("Showing the volume overlay without activation failed.")
            self.window.withdraw()
            return
        self._hide_after_id = self.window.after(auto_hide_ms, self.hide)

    def _configure_no_activate(self) -> int:
        try:
            hwnd = get_toplevel_window_handle(self.window.winfo_id())
        except tk.TclError:
            return 0
        if not configure_no_activate_window(hwnd):
            LOGGER.warning("Applying the volume overlay no-activate style failed.")
            return 0
        return hwnd

    def _position_window(
        self,
        preferred_display_device_name: str | None,
    ) -> OverlayGeometry | None:
        self.window.update_idletasks()
        display_area = get_overlay_display_area(preferred_display_device_name)
        if display_area is None:
            LOGGER.warning("No Windows display work area is available for the volume overlay.")
            return None
        placement = calculate_overlay_geometry(
            self.window.winfo_reqwidth(),
            self.window.winfo_reqheight(),
            display_area,
        )
        self.window.geometry(
            f"{placement.width}x{placement.height}{placement.x:+d}{placement.y:+d}"
        )
        return placement

    def hide(self) -> None:
        self._hide_after_id = None
        self.window.withdraw()

    def close(self) -> None:
        if self._hide_after_id is not None:
            self.window.after_cancel(self._hide_after_id)
            self._hide_after_id = None
        if self.window.winfo_exists():
            self.window.destroy()
