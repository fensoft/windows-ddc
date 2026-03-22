from __future__ import annotations

import tkinter as tk
from tkinter import ttk


OVERLAY_BG = "#111111"
OVERLAY_BORDER = "#2A2A2A"
OVERLAY_TEXT = "#FFFFFF"
OVERLAY_SUBTEXT = "#D0D0D0"
OVERLAY_ACCENT = "#4CC2FF"
OVERLAY_TRACK = "#2A2A2A"
AUTO_HIDE_MS = 1400
PROGRESS_STYLE = "VolumeOverlay.Horizontal.TProgressbar"
OVERLAY_BOTTOM_MARGIN = 88
OVERLAY_SIDE_MARGIN = 24
OVERLAY_CONTENT_PADX = 12
OVERLAY_CONTENT_PADY = 10
OVERLAY_LABEL_FONT = ("Segoe UI", 9)
OVERLAY_VALUE_FONT = ("Segoe UI", 20, "bold")
OVERLAY_BAR_LENGTH = 176
OVERLAY_BAR_THICKNESS = 5


class VolumeOverlay:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self._hide_after_id: str | None = None
        self._style = ttk.Style(root)
        self._ensure_style()

        self.window = tk.Toplevel(root)
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.configure(bg=OVERLAY_BORDER)
        try:
            self.window.attributes("-topmost", True)
        except tk.TclError:
            pass
        try:
            self.window.attributes("-alpha", 0.7)
        except tk.TclError:
            pass
        try:
            self.window.attributes("-toolwindow", True)
        except tk.TclError:
            pass

        self.volume_var = tk.StringVar(value="0%")

        border = tk.Frame(self.window, bg=OVERLAY_BORDER, bd=0, highlightthickness=0)
        border.pack()

        content = tk.Frame(border, bg=OVERLAY_BG, padx=OVERLAY_CONTENT_PADX, pady=OVERLAY_CONTENT_PADY)
        content.pack(padx=1, pady=1)

        tk.Label(
            content,
            text="Volume",
            bg=OVERLAY_BG,
            fg=OVERLAY_SUBTEXT,
            font=OVERLAY_LABEL_FONT,
        ).pack(anchor="w")

        tk.Label(
            content,
            textvariable=self.volume_var,
            bg=OVERLAY_BG,
            fg=OVERLAY_TEXT,
            font=OVERLAY_VALUE_FONT,
        ).pack(anchor="w", pady=(1, 8))

        self.progress = ttk.Progressbar(
            content,
            style=PROGRESS_STYLE,
            orient=tk.HORIZONTAL,
            mode="determinate",
            length=OVERLAY_BAR_LENGTH,
            maximum=100,
        )
        self.progress.pack(fill="x")

    def _ensure_style(self) -> None:
        self._style.configure(
            PROGRESS_STYLE,
            background=OVERLAY_ACCENT,
            troughcolor=OVERLAY_TRACK,
            bordercolor=OVERLAY_TRACK,
            lightcolor=OVERLAY_ACCENT,
            darkcolor=OVERLAY_ACCENT,
            thickness=OVERLAY_BAR_THICKNESS,
        )

    def show(self, volume: int) -> None:
        volume = max(0, min(volume, 100))
        self.volume_var.set(f"{volume}%")
        self.progress.configure(value=volume)
        self._position_window()
        self.window.deiconify()
        self.window.lift()
        try:
            self.window.attributes("-topmost", True)
        except tk.TclError:
            pass

        if self._hide_after_id is not None:
            self.window.after_cancel(self._hide_after_id)
        self._hide_after_id = self.window.after(AUTO_HIDE_MS, self.hide)

    def _position_window(self) -> None:
        self.window.update_idletasks()
        width = self.window.winfo_reqwidth()
        height = self.window.winfo_reqheight()
        x = max(OVERLAY_SIDE_MARGIN, (self.window.winfo_screenwidth() - width) // 2)
        y = max(32, self.window.winfo_screenheight() - height - OVERLAY_BOTTOM_MARGIN)
        self.window.geometry(f"{width}x{height}+{x}+{y}")

    def hide(self) -> None:
        self._hide_after_id = None
        self.window.withdraw()

    def close(self) -> None:
        if self._hide_after_id is not None:
            self.window.after_cancel(self._hide_after_id)
            self._hide_after_id = None
        if self.window.winfo_exists():
            self.window.destroy()
