"""On-disk state for the calendar widget: settings, calendar list, event cache.

Everything the widget owns lives in one directory so it can be inspected,
backed up or deleted as a unit:

    %LOCALAPPDATA%\\CalendarWidget\\
        settings.json     user-visible configuration (never a password)
        calendars.json    display name, colour and visibility of each calendar
        events.json       cached events, raw ICS kept per calendar
        sync-state.json   last sync result, for the header status and backoff
        widget\\           one-shot IPC from the Windhawk taskbar mod
        listcal.log       rotating log, credentials are never written here

All writes are atomic (write to ``*.tmp`` next to the target, then
``os.replace``), because the widget reads these files while a sync may be
writing them.

Times are stored as ISO-8601 strings. Timed events keep their UTC offset
(``2026-02-10T10:00:00+03:00``); all-day events are plain dates
(``2026-02-12``) with ``all_day`` set, which is what the UI keys off.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

APP_DIR_NAME = "CalendarWidget"

# Colours used when a calendar does not publish one (or publishes nonsense).
# Chosen to stay distinguishable in both light and dark themes.
FALLBACK_COLORS = [
    "#4C8DFF",
    "#B763CB",
    "#37A66B",
    "#E0A33A",
    "#E05A6B",
    "#3AB6C4",
    "#8C7AE6",
    "#C97A3A",
]

# How far around today events are kept expanded in ``events.json``: a year each
# way. Months outside it are expanded on demand from the raw ICS, which the sync
# downloads whole (see ``sync.events_for_range``).
CACHE_DAYS_BACK = 365
CACHE_DAYS_FORWARD = 365


def base_dir() -> Path:
    """Root of the widget's state, honouring ``CALENDAR_WIDGET_HOME`` for tests."""
    override = os.environ.get("CALENDAR_WIDGET_HOME")
    if override:
        return Path(override)
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        local = os.path.expanduser("~")
    return Path(local) / APP_DIR_NAME


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False
    )
    try:
        with handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(handle.name, path)
    except BaseException:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


def _read_json(path: Path, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return default
    except (OSError, json.JSONDecodeError):
        # A corrupt state file must not stop the widget; defaults take over and
        # the next successful write repairs the file.
        return default


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


@dataclass
class Event:
    uid: str
    calendar_id: str
    title: str
    start: str  # ISO datetime with offset, or ISO date when all_day
    end: str
    all_day: bool = False
    location: str = ""
    description: str = ""
    recurring: bool = False
    url: str = ""
    calendar_name: str = ""
    calendar_color: str = ""

    def to_dict(self) -> dict:
        return {
            "uid": self.uid,
            "calendar_id": self.calendar_id,
            "title": self.title,
            "start": self.start,
            "end": self.end,
            "all_day": self.all_day,
            "location": self.location,
            "description": self.description,
            "recurring": self.recurring,
            "url": self.url,
            "calendar_name": self.calendar_name,
            "calendar_color": self.calendar_color,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Event":
        return cls(
            uid=str(data.get("uid", "")),
            calendar_id=str(data.get("calendar_id", "")),
            title=str(data.get("title", "")),
            start=str(data.get("start", "")),
            end=str(data.get("end", "")),
            all_day=bool(data.get("all_day", False)),
            location=str(data.get("location", "")),
            description=str(data.get("description", "")),
            recurring=bool(data.get("recurring", False)),
            url=str(data.get("url", "")),
            calendar_name=str(data.get("calendar_name", "")),
            calendar_color=str(data.get("calendar_color", "")),
        )

    @property
    def start_dt(self) -> datetime | date:
        return parse_when(self.start, self.all_day)

    @property
    def end_dt(self) -> datetime | date:
        return parse_when(self.end, self.all_day)

    @property
    def day_keys(self) -> list[str]:
        """Every calendar date this event touches, as ``YYYY-MM-DD``.

        A multi-day event has to mark each day it covers, not just its first
        day, otherwise the month grid shows a three-day trip as one point.
        """
        start = self.start_dt
        end = self.end_dt
        if self.all_day:
            # DTEND is exclusive for all-day events: 12th..13th means the 12th.
            last = end.fromordinal(end.toordinal() - 1) if isinstance(end, date) and end > start else start
        else:
            last_date = end.date() if isinstance(end, datetime) else end
            start_date = start.date() if isinstance(start, datetime) else start
            # An event ending at 00:00 does not occupy the following day.
            if isinstance(end, datetime) and end.hour == 0 and end.minute == 0 and end.second == 0:
                last_date = date.fromordinal(end.date().toordinal() - 1)
            last = max(last_date, start_date)
        first = start.date() if isinstance(start, datetime) else start
        if last < first:
            last = first
        return [
            date.fromordinal(ordinal).isoformat()
            for ordinal in range(first.toordinal(), last.toordinal() + 1)
        ]


def parse_when(value: str, all_day: bool) -> datetime | date:
    """Parse a stored time. Naive values are read as local time."""
    if all_day:
        return date.fromisoformat(value[:10])
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return parsed


def parse_when_utc(value: str, all_day: bool) -> datetime:
    parsed = parse_when(value, all_day)
    if isinstance(parsed, datetime):
        return parsed.astimezone(timezone.utc)
    return datetime(parsed.year, parsed.month, parsed.day, tzinfo=timezone.utc)


def sort_key(event: Event) -> tuple:
    """All-day events first, then by start time, then by title."""
    start = event.start_dt
    if isinstance(start, date) and not isinstance(start, datetime):
        return (0, datetime.min, event.title.lower())
    return (1, start, event.title.lower())


@dataclass
class Calendar:
    id: str
    name: str
    color: str
    order: int = 0
    visible: bool = True
    read_only: bool = False
    description: str = ""
    timezone: str = ""
    ctag: str = ""
    supported: bool = True
    event_count: int = 0
    # The date range the cached raw ICS was downloaded for (ISO dates).
    fetched_start: str = ""
    fetched_end: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "color": self.color,
            "order": self.order,
            "visible": self.visible,
            "read_only": self.read_only,
            "description": self.description,
            "timezone": self.timezone,
            "ctag": self.ctag,
            "supported": self.supported,
            "event_count": self.event_count,
            "fetched_start": self.fetched_start,
            "fetched_end": self.fetched_end,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Calendar":
        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            color=str(data.get("color", "")) or FALLBACK_COLORS[0],
            order=int(data.get("order", 0)),
            visible=bool(data.get("visible", True)),
            read_only=bool(data.get("read_only", False)),
            description=str(data.get("description", "")),
            timezone=str(data.get("timezone", "")),
            ctag=str(data.get("ctag", "")),
            supported=bool(data.get("supported", True)),
            event_count=int(data.get("event_count", 0)),
            fetched_start=str(data.get("fetched_start", "")),
            fetched_end=str(data.get("fetched_end", "")),
        )


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

DEFAULT_WEEK_START = 0  # Monday


@dataclass
class Settings:
    username: str = ""
    refresh_seconds: int = 900
    week_start: int = DEFAULT_WEEK_START
    theme: str = "auto"  # auto | light | dark
    accent: str = ""  # empty means "read the Windows accent colour"
    window_x: int = -1
    window_y: int = -1
    window_width: int = 380
    window_height: int = 640
    pin_on_top: bool = True
    expanded: bool = False  # open as the full-screen month instead of the flyout
    open_at_cursor: bool = True
    show_declined: bool = False
    show_transparent: bool = True
    hidden_calendars: list[str] = field(default_factory=list)
    calendar_colors: dict[str, str] = field(default_factory=dict)
    fetch_days_back: int = CACHE_DAYS_BACK
    fetch_days_forward: int = CACHE_DAYS_FORWARD
    # The taskbar widgets next to the calendar.
    show_widgets: bool = True
    show_weather: bool = True
    weather_city: str = ""  # empty: the weather service places the request itself
    track_app_time: bool = True

    @classmethod
    def load(cls, directory: Path | None = None) -> "Settings":
        directory = directory or base_dir()
        raw = _read_json(directory / "settings.json", {})
        if not isinstance(raw, dict):
            raw = {}
        settings = cls()
        for key, value in raw.items():
            if not hasattr(settings, key):
                continue
            current = getattr(settings, key)
            if isinstance(current, bool):
                setattr(settings, key, bool(value))
            elif isinstance(current, int) and not isinstance(value, bool):
                try:
                    setattr(settings, key, int(value))
                except (TypeError, ValueError):
                    pass
            elif isinstance(current, dict) and isinstance(value, dict):
                setattr(settings, key, {str(k): str(v) for k, v in value.items()})
            elif isinstance(current, list) and isinstance(value, list):
                setattr(settings, key, [str(item) for item in value])
            elif isinstance(current, str):
                setattr(settings, key, str(value))
        settings.refresh_seconds = max(60, min(settings.refresh_seconds, 24 * 3600))
        settings.week_start = 0 if settings.week_start not in (0, 1, 6) else settings.week_start
        settings.fetch_days_back = max(7, min(settings.fetch_days_back, 400))
        settings.fetch_days_forward = max(7, min(settings.fetch_days_forward, 400))
        return settings

    def save(self, directory: Path | None = None) -> None:
        directory = directory or base_dir()
        _atomic_write_json(directory / "settings.json", self.__dict__)

    def calendar_color(self, calendar_id: str, fallback_index: int = 0) -> str:
        return self.calendar_colors.get(calendar_id) or FALLBACK_COLORS[fallback_index % len(FALLBACK_COLORS)]


# ---------------------------------------------------------------------------
# State store
# ---------------------------------------------------------------------------


class StateStore:
    """Reads and writes the widget's files; one instance per process is enough."""

    def __init__(self, directory: Path | None = None) -> None:
        self.dir = Path(directory) if directory else base_dir()
        self.settings_path = self.dir / "settings.json"
        self.calendars_path = self.dir / "calendars.json"
        self.events_path = self.dir / "events.json"
        self.sync_state_path = self.dir / "sync-state.json"
        self.widget_dir = self.dir / "widget"
        self.log_path = self.dir / "listcal.log"

    # -- directories -------------------------------------------------------

    def ensure_dirs(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.widget_dir.mkdir(parents=True, exist_ok=True)

    # -- settings ----------------------------------------------------------

    def load_settings(self) -> Settings:
        return Settings.load(self.dir)

    def save_settings(self, settings: Settings) -> None:
        settings.save(self.dir)

    # -- calendars ---------------------------------------------------------

    def load_calendars(self) -> list[Calendar]:
        raw = _read_json(self.calendars_path, {"calendars": []})
        items: Iterable[dict] = raw.get("calendars", []) if isinstance(raw, dict) else []
        return [Calendar.from_dict(item) for item in items if isinstance(item, dict)]

    def save_calendars(self, calendars: list[Calendar]) -> None:
        _atomic_write_json(
            self.calendars_path,
            {
                "updated": datetime.now().astimezone().isoformat(timespec="seconds"),
                "calendars": [calendar.to_dict() for calendar in calendars],
            },
        )

    # -- events ------------------------------------------------------------

    def load_events(self) -> list[Event]:
        raw = _read_json(self.events_path, {"events": []})
        items: Iterable[dict] = raw.get("events", []) if isinstance(raw, dict) else []
        return [Event.from_dict(item) for item in items if isinstance(item, dict)]

    def save_events(self, events: list[Event], fetched: dict[str, Any] | None = None) -> None:
        _atomic_write_json(
            self.events_path,
            {
                "updated": datetime.now().astimezone().isoformat(timespec="seconds"),
                "fetched": fetched or {},
                "events": [event.to_dict() for event in events],
            },
        )

    def events_window(self) -> tuple[date, date] | None:
        """The date range ``events.json`` holds, or None when it is unknown."""
        raw = _read_json(self.events_path, {})
        fetched = raw.get("fetched") if isinstance(raw, dict) else None
        if not isinstance(fetched, dict):
            return None
        try:
            return (
                date.fromisoformat(str(fetched.get("window_start"))),
                date.fromisoformat(str(fetched.get("window_end"))),
            )
        except ValueError:
            return None

    def events_updated_at(self) -> datetime | None:
        raw = _read_json(self.events_path, {})
        stamp = raw.get("updated") if isinstance(raw, dict) else None
        if not stamp:
            return None
        try:
            return datetime.fromisoformat(stamp)
        except ValueError:
            return None

    def is_stale(self, refresh_seconds: int) -> bool:
        updated = self.events_updated_at()
        if updated is None:
            return True
        age = (datetime.now().astimezone() - updated).total_seconds()
        return age > refresh_seconds

    # -- sync state --------------------------------------------------------

    def load_sync_state(self) -> dict:
        raw = _read_json(self.sync_state_path, {})
        return raw if isinstance(raw, dict) else {}

    def save_sync_state(self, state: dict) -> None:
        _atomic_write_json(self.sync_state_path, state)

    def record_sync(self, ok: bool, message: str = "", calendars: int = 0, events: int = 0) -> dict:
        previous = self.load_sync_state()
        failures = 0 if ok else int(previous.get("consecutive_failures", 0)) + 1
        state = {
            "last_attempt": datetime.now().astimezone().isoformat(timespec="seconds"),
            "last_success": datetime.now().astimezone().isoformat(timespec="seconds")
            if ok
            else previous.get("last_success"),
            "ok": ok,
            "message": message,
            "consecutive_failures": failures,
            "calendars": calendars,
            "events": events,
        }
        self.save_sync_state(state)
        return state

    def backoff_seconds(self, base_seconds: int) -> int:
        """Delay before the next sync attempt after failures (1x..64x, capped 1 h)."""
        failures = int(self.load_sync_state().get("consecutive_failures", 0))
        if failures <= 0:
            return base_seconds
        return min(base_seconds * (2 ** min(failures, 6)), 3600)

    # -- logging -----------------------------------------------------------

    def log(self, message: str, level: str = "INFO") -> None:
        try:
            self.ensure_dirs()
            stamp = datetime.now().astimezone().isoformat(timespec="seconds")
            line = f"{stamp} {level:<5} {message}\n"
            # Keep the log from growing without bound; 512 KiB is plenty for a
            # widget and keeps diagnosis cheap.
            if self.log_path.exists() and self.log_path.stat().st_size > 512 * 1024:
                rotated = self.log_path.with_suffix(".log.1")
                try:
                    os.replace(self.log_path, rotated)
                except OSError:
                    pass
            with open(self.log_path, "a", encoding="utf-8") as handle:
                handle.write(line)
        except OSError:
            # Logging must never be the reason the widget fails.
            pass

    # -- widget IPC --------------------------------------------------------

    def widget_request_path(self) -> Path:
        return self.widget_dir / "open_request.json"

    def widget_ack_path(self) -> Path:
        return self.widget_dir / "open_ack.json"

    def read_widget_request(self) -> dict | None:
        raw = _read_json(self.widget_request_path(), None)
        return raw if isinstance(raw, dict) else None

    def write_widget_request(self, x: int | None, y: int | None) -> None:
        self.ensure_dirs()
        _atomic_write_json(
            self.widget_request_path(),
            {
                "open": True,
                "x": x,
                "y": y,
                "requested": datetime.now().astimezone().isoformat(timespec="milliseconds"),
                "source": "taskbar",
            },
        )

    def ack_widget_request(self, request: dict) -> None:
        self.ensure_dirs()
        _atomic_write_json(
            self.widget_ack_path(),
            {
                "requested": request.get("requested"),
                "handled": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            },
        )

    def widget_request_is_new(self, request: dict) -> bool:
        """True when ``request`` has not been handled by this widget session yet."""
        ack = _read_json(self.widget_ack_path(), {})
        return not isinstance(ack, dict) or ack.get("requested") != request.get("requested")
