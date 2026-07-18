from __future__ import annotations

import tkinter as tk

from diagnostics import close_logging, configure_logging, get_logger
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

    logger = get_logger(__name__)
    try:
        configure_logging()
        logger.info("Application start requested.")
        root = tk.Tk()
        MonitorVolumeApp(root)
        root.mainloop()
    except Exception:
        logger.exception("Unhandled application failure.")
        raise
    finally:
        try:
            logger.info("Application process exiting.")
            close_logging()
        finally:
            instance_guard.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
