from __future__ import annotations

import tkinter as tk

from gui import MonitorVolumeApp


def main() -> int:
    root = tk.Tk()
    MonitorVolumeApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
