"""Time spent in applications: which program was in front, and for how long.

The dock's "App Time" icon. Twice a second the widget asks Windows which window
is in the foreground and adds the time since the last question to that
program's total for the day. Nothing more is looked at: not the window's title,
not its content, and nothing leaves the computer - the totals live in
``app-time.json`` next to the other state:

    {"days": {"2026-10-10": {"chrome.exe": 6480.5, ...}}, "names": {"chrome.exe": "Google Chrome"}}

What is deliberately not counted:

* time without keyboard or mouse input for ``IDLE_SECONDS`` - the computer was
  left alone (a film watched without touching anything is lost with it);
* the lock screen, and the widget's own windows;
* a gap between two questions longer than ``MAX_STEP`` - the computer slept.

A program is named by its executable's "file description" ("Google Chrome"
for ``chrome.exe``), which is what the Task Manager shows as well.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from store import _atomic_write_json, _read_json

FILE_NAME = "app-time.json"
IDLE_SECONDS = 300
MAX_STEP = 5.0
#: Days kept in the file; the popover shows at most a week.
KEEP_DAYS = 14
WEEK_DAYS = 7
#: Never counted: the lock screen, the shell's own surfaces (quick settings, the
#: snipping overlay, the touch keyboard, file pickers) and the helpers of
#: hardware and desktop decoration, which take the foreground without being used.
IGNORED = {"lockapp.exe", "logonui.exe", "searchhost.exe", "startmenuexperiencehost.exe",
           "shellexperiencehost.exe", "shellhost.exe", "screenclippinghost.exe",
           "textinputhost.exe", "pickerhost.exe", "razerappengine.exe", "rgbfusion.exe",
           "wallpaper32.exe", "wallpaper64.exe", "rainmeter.exe"}
#: Windows Store apps all show up as this host; the real program is its child.
FRAME_HOST = "applicationframehost.exe"
#: Names nicer than the file description, which for these says little.
KNOWN_NAMES = {
    "explorer.exe": "Проводник",
    "steamwebhelper.exe": "Steam",
    "telegram.exe": "Telegram",
    "zoom.exe": "Zoom",
    "sketchup.exe": "SketchUp",
    "dota2.exe": "Dota 2",
    "bg3.exe": "Baldur's Gate 3",
    "bg3_dx11.exe": "Baldur's Gate 3",
    "civilizationvi.exe": "Civilization VI",
    "civilizationvi_dx12.exe": "Civilization VI",
}

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


# ---------------------------------------------------------------------------
# Asking Windows
# ---------------------------------------------------------------------------


class _LastInput(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def idle_seconds() -> float:
    """Seconds since the last key press or mouse movement."""
    info = _LastInput()
    info.cbSize = ctypes.sizeof(info)
    try:
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        now = ctypes.windll.kernel32.GetTickCount()
    except Exception:
        return 0.0
    return ((now - info.dwTime) & 0xFFFFFFFF) / 1000.0


def _window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    return int(pid.value)


def _process_path(pid: int) -> str:
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        ok = kernel32.QueryFullProcessImageNameW(
            wintypes.HANDLE(handle), 0, buffer, ctypes.byref(size)
        )
        return buffer.value if ok else ""
    finally:
        kernel32.CloseHandle(wintypes.HANDLE(handle))


def _hosted_pid(hwnd: int, host_pid: int) -> int:
    """The process of the Store app shown inside an ApplicationFrameHost window."""
    found = [0]

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(child, _param):
        pid = _window_pid(child)
        if pid and pid != host_pid:
            found[0] = pid
            return False
        return True

    ctypes.windll.user32.EnumChildWindows(wintypes.HWND(hwnd), visit, 0)
    return found[0]


def foreground_app() -> str:
    """Full path of the program whose window is in front; "" when there is none
    to count (no window, the widget itself, a process that may not be asked)."""
    try:
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = wintypes.HWND
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""
        pid = _window_pid(hwnd)
        if not pid or pid == os.getpid():
            return ""
        path = _process_path(pid)
        if os.path.basename(path).lower() == FRAME_HOST:
            hosted = _hosted_pid(hwnd, pid)
            path = _process_path(hosted) if hosted else ""
        return path
    except Exception:
        return ""


def file_description(path: str) -> str:
    """The "file description" of an executable's version resource, or ""."""
    try:
        version = ctypes.windll.version
        size = version.GetFileVersionInfoSizeW(path, None)
        if not size:
            return ""
        data = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(path, 0, size, data):
            return ""
        value = ctypes.c_void_p()
        length = wintypes.UINT()
        # The resource may hold several languages; the first one listed is used,
        # then the two that programs without a proper table usually have.
        blocks = []
        if version.VerQueryValueW(
            data, "\\VarFileInfo\\Translation", ctypes.byref(value), ctypes.byref(length)
        ) and length.value >= 4:
            pair = ctypes.cast(value, ctypes.POINTER(wintypes.WORD * 2)).contents
            blocks.append(f"{pair[0]:04x}{pair[1]:04x}")
        blocks += ["040904b0", "040904e4"]
        for block in blocks:
            if version.VerQueryValueW(
                data, f"\\StringFileInfo\\{block}\\FileDescription",
                ctypes.byref(value), ctypes.byref(length),
            ) and length.value:
                return ctypes.wstring_at(value.value, length.value).strip("\x00 ").strip()
    except Exception:
        pass
    return ""


def display_name(path: str) -> str:
    """What to call the program at ``path``."""
    base = os.path.basename(path)
    known = KNOWN_NAMES.get(base.lower())
    if known:
        return known
    return file_description(path) or os.path.splitext(base)[0]


# ---------------------------------------------------------------------------
# The log
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AppShare:
    name: str
    seconds: float


@dataclass(frozen=True)
class Summary:
    """What the popover shows for a day or a week."""

    total: float  # seconds
    apps: list[AppShare]  # the busiest first
    previous: float | None  # the day before / None for a week or when unknown
    days: int  # days with any time in the period


class AppTimeLog:
    """Per-day totals by program, kept in memory and written now and then."""

    def __init__(self, directory: Path) -> None:
        self.path = Path(directory) / FILE_NAME
        raw = _read_json(self.path, {})
        raw = raw if isinstance(raw, dict) else {}
        self.days: dict[str, dict[str, float]] = {}
        for day, apps in (raw.get("days") or {}).items():
            if isinstance(apps, dict):
                self.days[str(day)] = {
                    str(key): float(value)
                    for key, value in apps.items()
                    if isinstance(value, (int, float))
                }
        names = raw.get("names")
        self.names: dict[str, str] = (
            {str(key): str(value) for key, value in names.items()} if isinstance(names, dict) else {}
        )
        self.dirty = False

    def add(self, path: str, seconds: float, day: date) -> None:
        """Count ``seconds`` in front for the program at ``path``."""
        key = os.path.basename(path).lower()
        if not key or key in IGNORED or seconds <= 0:
            return
        if key not in self.names:
            self.names[key] = display_name(path)
        apps = self.days.setdefault(day.isoformat(), {})
        apps[key] = apps.get(key, 0.0) + seconds
        self.dirty = True

    def save(self, today: date) -> None:
        if not self.dirty:
            return
        oldest = (today - timedelta(days=KEEP_DAYS - 1)).isoformat()
        self.days = {day: apps for day, apps in self.days.items() if day >= oldest}
        used = {key for apps in self.days.values() for key in apps}
        self.names = {key: name for key, name in self.names.items() if key in used}
        try:
            _atomic_write_json(
                self.path,
                {
                    "days": {
                        day: {key: round(value, 1) for key, value in apps.items()}
                        for day, apps in sorted(self.days.items())
                    },
                    "names": self.names,
                },
            )
            self.dirty = False
        except OSError:
            pass  # the next save tries again; the totals stay in memory

    def _total(self, day: date) -> float:
        apps = self.days.get(day.isoformat(), {})
        return sum(seconds for key, seconds in apps.items() if key not in IGNORED)

    def summary(self, today: date, week: bool = False, limit: int = 5) -> Summary:
        """The totals for today, or for the seven days ending today."""
        span = [today - timedelta(days=back) for back in range(WEEK_DAYS if week else 1)]
        totals: dict[str, float] = {}
        days = 0
        for day in span:
            # The file may hold programs counted before they were ignored.
            apps = {
                key: seconds
                for key, seconds in self.days.get(day.isoformat(), {}).items()
                if key not in IGNORED
            }
            days += 1 if apps else 0
            for key, seconds in apps.items():
                totals[key] = totals.get(key, 0.0) + seconds
        ranked = sorted(totals.items(), key=lambda item: -item[1])[:limit]
        previous = None
        yesterday = today - timedelta(days=1)
        if not week and yesterday.isoformat() in self.days:
            previous = self._total(yesterday)
        return Summary(
            total=sum(totals.values()),
            apps=[
                AppShare(KNOWN_NAMES.get(key) or self.names.get(key, key), seconds)
                for key, seconds in ranked
            ],
            previous=previous,
            days=days,
        )


class AppTimeTracker:
    """Feeds the log from the clock: call :meth:`tick` a few times a second."""

    def __init__(self, log: AppTimeLog) -> None:
        self.log = log
        self._last: float | None = None

    def tick(self, now: float, day: date) -> None:
        """``now`` is a monotonic clock reading, in seconds."""
        last, self._last = self._last, now
        if last is None:
            return
        step = now - last
        if step <= 0 or step > MAX_STEP or idle_seconds() >= IDLE_SECONDS:
            return
        path = foreground_app()
        if path:
            self.log.add(path, step, day)


# ---------------------------------------------------------------------------
# Wording
# ---------------------------------------------------------------------------


def format_duration(seconds: float) -> str:
    """"6 ч 42 м", "1 ч 05 м", "52 м"; under a minute is "0 м"."""
    minutes = int(seconds // 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} ч {minutes:02d} м"
    return f"{minutes} м"


def share_words(share: float) -> str:
    """A share of the whole in words, as in "треть всего времени"."""
    if share >= 0.9:
        return "почти всё время"
    if share >= 0.6:
        return "больше половины всего времени"
    if share >= 0.45:
        return "половина всего времени"
    if share >= 0.3:
        return "треть всего времени"
    if share >= 0.22:
        return "четверть всего времени"
    return f"{round(share * 100)} % всего времени"


def describe_total(summary: Summary, week: bool) -> str:
    """The line under the big number."""
    if week:
        if summary.days > 1:
            return f"за 7 дней · в среднем {format_duration(summary.total / summary.days)} в день"
        return "за 7 дней"
    if summary.previous is None:
        return "за сегодня"
    difference = int(summary.total // 60) - int(summary.previous // 60)
    if difference == 0:
        return "за сегодня · столько же, сколько вчера"
    word = "больше" if difference > 0 else "меньше"
    return f"за сегодня · на {format_duration(abs(difference) * 60)} {word}, чем вчера"


def describe_leader(summary: Summary) -> str:
    """The closing line: "Больше всего — Figma, треть всего времени"."""
    if not summary.apps or summary.total <= 0:
        return ""
    leader = summary.apps[0]
    return f"Больше всего — {leader.name}, {share_words(leader.seconds / summary.total)}"
