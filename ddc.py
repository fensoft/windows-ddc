from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeAlias

try:
    from monitorcontrol import get_monitors
    from monitorcontrol.vcp import VCPError
except ImportError as exc:
    get_monitors = None
    VCPError = RuntimeError
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


SelectionKey: TypeAlias = tuple[str, int]


@dataclass(frozen=True)
class MonitorRef:
    index: int
    monitor: Any
    description: str
    description_ordinal: int

    @property
    def selection_key(self) -> SelectionKey:
        return self.description, self.description_ordinal

    @property
    def display_name(self) -> str:
        return f"{self.index}. {self.description}"


class DDCError(RuntimeError):
    pass


def clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(value, maximum))


def monitor_name(monitor: Any) -> str:
    description = getattr(getattr(monitor, "vcp", None), "description", "")
    return description.strip() or "Unnamed monitor"


def enumerate_monitors() -> list[MonitorRef]:
    if IMPORT_ERROR is not None:
        raise DDCError(
            "monitorcontrol is not installed. Run: python -m pip install monitorcontrol"
        ) from IMPORT_ERROR

    try:
        monitors = list(get_monitors())
    except (NotImplementedError, VCPError) as exc:
        raise DDCError(f"Failed to detect DDC/CI monitors: {exc}") from exc

    description_counts: dict[str, int] = {}
    monitor_refs: list[MonitorRef] = []
    for index, monitor in enumerate(monitors, start=1):
        description = monitor_name(monitor)
        description_ordinal = description_counts.get(description, 0) + 1
        description_counts[description] = description_ordinal
        monitor_refs.append(
            MonitorRef(
                index=index,
                monitor=monitor,
                description=description,
                description_ordinal=description_ordinal,
            )
        )

    return monitor_refs


def pick_selected_monitor_index(
    monitors: list[MonitorRef],
    selected_key: SelectionKey | None,
) -> int | None:
    if not monitors:
        return None

    if selected_key is not None:
        for index, monitor_ref in enumerate(monitors):
            if monitor_ref.selection_key == selected_key:
                return index

    return 0


def read_monitor_volume(monitor_ref: MonitorRef) -> int:
    try:
        with monitor_ref.monitor:
            return clamp(monitor_ref.monitor.get_volume(), 0, 100)
    except VCPError as exc:
        raise DDCError(f"Failed to read volume from {monitor_ref.description}: {exc}") from exc


def set_monitor_volume(monitor_ref: MonitorRef, target_volume: int) -> int:
    try:
        with monitor_ref.monitor:
            monitor_ref.monitor.set_volume(clamp(target_volume, 0, 100))
            return clamp(monitor_ref.monitor.get_volume(), 0, 100)
    except VCPError as exc:
        raise DDCError(f"Failed to set volume on {monitor_ref.description}: {exc}") from exc


def change_monitor_volume(monitor_ref: MonitorRef, delta: int) -> int:
    try:
        with monitor_ref.monitor:
            current_volume = clamp(monitor_ref.monitor.get_volume(), 0, 100)
            target_volume = clamp(current_volume + delta, 0, 100)
            if target_volume != current_volume:
                monitor_ref.monitor.set_volume(target_volume)
            return clamp(monitor_ref.monitor.get_volume(), 0, 100)
    except VCPError as exc:
        raise DDCError(f"Failed to change volume on {monitor_ref.description}: {exc}") from exc
