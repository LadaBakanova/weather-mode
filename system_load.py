"""How busy the computer is: processor, memory and the system disk.

The numbers behind the dock's "System" icon. Everything is asked from Windows
directly (``GetSystemTimes``, ``GlobalMemoryStatusEx``, the disk's free space),
so nothing has to be installed and a reading costs microseconds.

The processor load is the share of time that was not idle *between two
readings*, so ``LoadMeter.sample`` is meant to be called about once a second.
One busy second is not a problem worth a number on the taskbar; ``problem``
therefore looks at the average of the last ``WINDOW`` readings.
"""

from __future__ import annotations

import ctypes
import os
import shutil
from collections import deque
from ctypes import wintypes
from dataclasses import dataclass

#: Readings the processor load is averaged over before it counts as a problem.
WINDOW = 10
#: From these levels the dock shows the number next to the icon.
CPU_LIMIT = 90
MEMORY_LIMIT = 90
DISK_LIMIT = 95


@dataclass(frozen=True)
class Load:
    cpu: int  # percent, the last reading
    cpu_average: int  # percent, over the last WINDOW readings
    memory: int  # percent in use
    memory_used: int  # bytes
    memory_total: int
    disk: int  # percent in use
    disk_free: int  # bytes
    disk_total: int

    @property
    def problem(self) -> tuple[str, int] | None:
        """What is close to its limit - ``("cpu", 97)`` - or None when all is well."""
        if self.cpu_average >= CPU_LIMIT:
            return "cpu", self.cpu_average
        if self.memory >= MEMORY_LIMIT:
            return "memory", self.memory
        if self.disk >= DISK_LIMIT:
            return "disk", self.disk
        return None


class _MemoryStatus(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def cpu_times() -> tuple[int, int] | None:
    """``(idle, total)`` processor time since start-up, in 100 ns units."""
    idle, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
    try:
        ok = ctypes.windll.kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
        )
    except Exception:
        return None
    if not ok:
        return None

    def ticks(value: wintypes.FILETIME) -> int:
        return (value.dwHighDateTime << 32) | value.dwLowDateTime

    # Kernel time includes the idle time.
    return ticks(idle), ticks(kernel) + ticks(user)


def cpu_percent(before: tuple[int, int], after: tuple[int, int]) -> int:
    """The share of time between two ``cpu_times`` readings that was not idle."""
    total = after[1] - before[1]
    if total <= 0:
        return 0
    idle = after[0] - before[0]
    return max(0, min(100, round(100 * (total - idle) / total)))


def memory() -> tuple[int, int, int]:
    """``(percent in use, bytes in use, bytes installed)``."""
    status = _MemoryStatus()
    status.dwLength = ctypes.sizeof(status)
    try:
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return 0, 0, 0
    except Exception:
        return 0, 0, 0
    used = status.ullTotalPhys - status.ullAvailPhys
    return int(status.dwMemoryLoad), int(used), int(status.ullTotalPhys)


def system_disk() -> tuple[int, int, int]:
    """``(percent in use, bytes free, bytes in all)`` of the disk Windows is on."""
    drive = os.environ.get("SystemDrive", "C:") + "\\"
    try:
        usage = shutil.disk_usage(drive)
    except OSError:
        return 0, 0, 0
    percent = round(100 * usage.used / usage.total) if usage.total else 0
    return percent, usage.free, usage.total


class LoadMeter:
    """Turns successive readings into a :class:`Load`."""

    def __init__(self) -> None:
        self._last = cpu_times()
        self._recent: deque[int] = deque(maxlen=WINDOW)

    def sample(self) -> Load:
        now = cpu_times()
        cpu = cpu_percent(self._last, now) if self._last and now else 0
        self._last = now
        self._recent.append(cpu)
        average = round(sum(self._recent) / len(self._recent))
        return Load(cpu, average, *memory(), *system_disk())


def format_bytes(count: int) -> str:
    """Bytes the way the popover writes them: "11,8 ГБ", "512 МБ"."""
    gigabytes = count / 1024**3
    if gigabytes >= 100:
        return f"{round(gigabytes)} ГБ"
    if gigabytes >= 1:
        return f"{gigabytes:.1f} ГБ".replace(".", ",")
    return f"{round(count / 1024**2)} МБ"
