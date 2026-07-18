from __future__ import annotations

import tkinter as tk

from gui import MonitorVolumeApp
from windows_platform import (
    InstanceAlreadyRunningError,
    PlatformError,
    SingleInstanceGuard,
    request_existing_instance_restore,
)


def main() -> int:
    try:
        instance_guard = SingleInstanceGuard()
    except InstanceAlreadyRunningError:
        try:
            request_existing_instance_restore()
        except PlatformError:
            pass
        return 0

    try:
        root = tk.Tk()
        MonitorVolumeApp(root)
        root.mainloop()
    finally:
        instance_guard.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
