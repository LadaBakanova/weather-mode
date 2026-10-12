"""The agenda: what is planned for the selected date, in order.

Layout of one row, the design's "Event Row" (51 px tall, 8 px padding):

    ┌───┬───────┬──────────────────────────────┐
    │ ▌ │ 14:00 │ Созвон с командой            │
    │ ▌ │ 14:30 │ Основной · Офис              │
    └───┴───────┴──────────────────────────────┘

The start time sits above the end time. All-day events come first and show
"весь день" in the same column. The calendar's colour is shown twice: as the
vertical bar and as the calendar name, so the widget still makes sense without
colour vision.

The list is at least ``MIN_VISIBLE_ROWS`` rows tall - a day with fewer events
leaves empty space below them - and grows to ``MAX_VISIBLE_ROWS``, after which
it scrolls. ``height`` tells the window how tall the agenda currently is.

Besides the list there are two more states, each drawn here so the flyout
itself stays dumb about data: an empty day ("Свободный день") and a loading
skeleton while a sync is running and nothing is cached yet.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from datetime import date, datetime
from typing import Callable, Iterable

from .shapes import ShapeCache
from .theme import Theme

WEEKDAYS_FULL = [
    "понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье",
]
MONTHS_GENITIVE = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]

EMPTY_TITLE = "Свободный день"
EMPTY_TEXT = "ничего не запланировано"
YANDEX_CALENDAR_URL = "https://calendar.yandex.ru/"

# Pixel metrics of the design's Agenda block.
VIEW_WIDTH = 360
SIDE = 8  # agenda side padding
HEADER_HEIGHT = 36  # 6 top + 4 + title 18 + 8; the count shares the title's line
ROW_HEIGHT = 51
ROW_GAP = 2
BOTTOM = 10
EMPTY_HEIGHT = 116
#: The list is never shorter than three rows, so the flyout keeps its height
#: from day to day; a fourth event stretches it, a fifth makes it scroll.
MIN_VISIBLE_ROWS = 3
MAX_VISIBLE_ROWS = 4
SKELETON_ROWS = 2
ROW_RADIUS = 7  # the Event Row's cornerRadius
TIME_X = 23  # 8 padding + 3 bar + 12 gap
INFO_X = 75  # time column 40 + 12 gap


def format_day_title(day: date) -> str:
    """"Суббота, 10 октября", the order the design uses."""
    return f"{WEEKDAYS_FULL[day.weekday()].capitalize()}, {day.day} {MONTHS_GENITIVE[day.month - 1]}"


def format_day_long(day: date) -> str:
    """"11 октября", as used in the empty-day sentence."""
    return f"{day.day} {MONTHS_GENITIVE[day.month - 1]}"


def plural_events(count: int) -> str:
    """Russian plural for the event count: 1 событие, 2 события, 5 событий."""
    if count == 0:
        return "Нет событий"
    last_two = count % 100
    last = count % 10
    if last == 1 and last_two != 11:
        word = "событие"
    elif last in (2, 3, 4) and last_two not in (12, 13, 14):
        word = "события"
    else:
        word = "событий"
    return f"{count} {word}"


def event_time_lines(event) -> tuple[str, str]:
    """The two lines of the time column: start, then end.

    All-day events read "Весь" / "день", which keeps the column's two lines
    meaningful without a special case in the layout.
    """
    if event.all_day:
        return "Весь", "день"
    start = event.start_dt
    if not isinstance(start, datetime):
        return "", ""
    end = event.end_dt
    end_text = end.strftime("%H:%M") if isinstance(end, datetime) else ""
    return start.strftime("%H:%M"), end_text


def rows_height(count: int) -> int:
    """Height of ``count`` stacked rows with the gaps between them."""
    return count * ROW_HEIGHT + max(0, count - 1) * ROW_GAP


class DayView:
    def __init__(
        self,
        parent: tk.Misc,
        theme: Theme,
        width: int = VIEW_WIDTH,
        on_open_event: Callable[[object], None] | None = None,
    ) -> None:
        self.theme = theme
        self.width = width
        self.on_open_event = on_open_event
        self.day = date.today()
        self._events: list = []
        self._loading = False
        self._today: date | None = None
        self._body_height = rows_height(MIN_VISIBLE_ROWS)

        bg = theme.get("bg")
        self._shapes = ShapeCache(parent)
        self.frame = tk.Frame(parent, bg=bg, width=width, height=self.height)
        self.frame.pack_propagate(False)

        self.header = tk.Frame(self.frame, bg=bg, width=width, height=HEADER_HEIGHT)
        self.header.pack(fill="x")
        self.title = self._label(self.header, "", theme.get("fg"), theme.px(15, 600))
        self.title.place(x=SIDE + 8, y=8)
        # The count sits on the title's line, against the right edge:
        # "Суббота, 10 октября          Сегодня · 2 события".
        self.summary = self._label(self.header, "", theme.get("fg_faint"), theme.px(12))
        self.summary.place(x=width - SIDE - 8, y=11, anchor="ne")

        # Canvas + inner frame: a scroll area for days with more rows than fit.
        self.canvas = tk.Canvas(
            self.frame,
            width=width - 2 * SIDE,
            height=self._body_height,
            highlightthickness=0,
            bd=0,
            bg=bg,
        )
        self.canvas.pack(padx=SIDE, anchor="n")
        self.canvas.configure(yscrollcommand=self._on_scroll_set)

        self.rows = tk.Frame(self.canvas, bg=bg)
        self._window = self.canvas.create_window((0, 0), window=self.rows, anchor="nw")
        self.rows.bind("<Configure>", self._on_rows_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.rows.bind("<MouseWheel>", self._on_wheel)

        # A 3 px thumb instead of the native scrollbar, which cannot be themed.
        self.thumb = tk.Frame(self.frame, bg=theme.get("text_disabled"), width=3)

    def _label(self, parent: tk.Misc, text: str, color: str, font: tuple) -> tk.Label:
        return tk.Label(
            parent,
            text=text,
            bg=parent.cget("bg"),
            fg=color,
            font=font,
            bd=0,
            padx=0,
            pady=0,
            highlightthickness=0,
            anchor="w",
        )

    # -- size --------------------------------------------------------------

    @property
    def height(self) -> int:
        """Current height of the whole agenda block, in pixels."""
        return HEADER_HEIGHT + self._body_height + BOTTOM

    def _resize(self, body_height: int) -> None:
        self._body_height = body_height
        self.canvas.configure(height=body_height)
        self.frame.configure(height=self.height)

    # -- scrolling ---------------------------------------------------------

    def _on_scroll_set(self, first: str, last: str) -> None:
        start, end = float(first), float(last)
        if start <= 0.0 and end >= 1.0:
            self.thumb.place_forget()
            return
        track = self._body_height
        self.thumb.place(
            x=self.width - 5,
            y=HEADER_HEIGHT + round(start * track),
            height=max(12, round((end - start) * track)),
        )

    def _on_rows_configure(self, _event: tk.Event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)

    def _on_wheel(self, event: tk.Event) -> None:
        if len(self._events) > MAX_VISIBLE_ROWS:
            self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    # -- content -----------------------------------------------------------

    def apply_theme(self, theme: Theme) -> None:
        self.theme = theme
        bg = theme.get("bg")
        for widget in (self.frame, self.header, self.canvas, self.rows):
            widget.configure(bg=bg)
        self.title.configure(bg=bg, fg=theme.get("fg"))
        self.summary.configure(bg=bg, fg=theme.get("fg_faint"))
        self.thumb.configure(bg=theme.get("text_disabled"))
        self.set_day(self.day, self._events, today=self._today)

    def set_day(self, day: date, events: Iterable, today: date | None = None) -> None:
        self.day = day
        self._today = today
        self._events = list(events)
        self._loading = False
        self.title.configure(text=format_day_title(day))

        count_text = plural_events(len(self._events))
        if today is not None and day == today:
            count_text = "Сегодня · " + count_text if self._events else "Сегодня"
        self.summary.configure(text=count_text)
        self._rebuild_rows()

    def set_loading(self, loading: bool) -> None:
        """Show grey placeholder rows while a sync runs and nothing is shown yet.

        Real rows are not replaced by placeholders: a refresh of a day that
        already has events keeps them on screen.
        """
        if loading == self._loading:
            return
        self._loading = loading
        self._rebuild_rows()

    def _rebuild_rows(self) -> None:
        for child in self.rows.winfo_children():
            child.destroy()

        if self._loading and not self._events:
            self._resize(rows_height(MIN_VISIBLE_ROWS))
            for _ in range(SKELETON_ROWS):
                self._build_skeleton()
        elif not self._events:
            self._resize(rows_height(MIN_VISIBLE_ROWS))
            self._build_empty_state()
        else:
            visible = min(max(len(self._events), MIN_VISIBLE_ROWS), MAX_VISIBLE_ROWS)
            self._resize(rows_height(visible))
            for event in self._events:
                self._build_row(event)
        self.canvas.yview_moveto(0)

    def _build_empty_state(self) -> None:
        """The design's Empty State: 48 px icon circle, title, one sentence."""
        theme = self.theme
        bg = theme.get("bg")
        # Centred in the list's minimum height rather than stuck to its top.
        box = tk.Frame(self.rows, bg=bg, height=self._body_height)
        box.pack(fill="x")
        box.pack_propagate(False)
        icon = tk.Canvas(box, width=48, height=48, highlightthickness=0, bd=0, bg=bg)
        icon.pack(pady=(8 + (self._body_height - EMPTY_HEIGHT) // 2, 0))
        self._shapes.draw(icon, 0, 0, 48, 48, 24, theme.get("bg_alt"), theme.get("border_soft"), bg)
        # A 22 px calendar glyph in the accent colour, for calendar-heart.
        accent = theme.get("accent_text")
        icon.create_rectangle(15, 16, 33, 34, outline=accent, width=2)
        icon.create_line(15, 22, 33, 22, fill=accent, width=2)
        icon.create_line(20, 13, 20, 18, fill=accent, width=2)
        icon.create_line(28, 13, 28, 18, fill=accent, width=2)
        self._label(box, EMPTY_TITLE, theme.get("fg"), theme.px(14, 600)).pack(pady=(10, 0))
        self._label(
            box,
            f"На {format_day_long(self.day)} {EMPTY_TEXT}",
            theme.get("fg_faint"),
            theme.px(12),
        ).pack(pady=(2, 0))
        box.bind("<MouseWheel>", self._on_wheel)

    def _row_frame(self) -> tk.Frame:
        # The gap goes above every row but the first, so the list is exactly
        # rows_height() tall and does not scroll when it fits.
        first = not self.rows.winfo_children()
        row = tk.Frame(self.rows, bg=self.theme.get("bg"), height=ROW_HEIGHT)
        row.pack(fill="x", pady=(0 if first else ROW_GAP, 0))
        row.pack_propagate(False)
        return row

    def _build_skeleton(self) -> None:
        block = self.theme.get("hover")
        row = self._row_frame()
        tk.Frame(row, bg=block, width=3, height=34).place(x=8, y=8)
        tk.Frame(row, bg=block, width=34, height=9).place(x=TIME_X, y=14)
        tk.Frame(row, bg=block, width=26, height=9).place(x=TIME_X, y=29)
        tk.Frame(row, bg=block, width=150, height=11).place(x=INFO_X, y=13)
        tk.Frame(row, bg=block, width=90, height=9).place(x=INFO_X, y=30)

    def _fit(self, text: str, font: tuple, limit: int) -> str:
        """Shorten ``text`` with an ellipsis so it fits ``limit`` pixels."""
        text = text.strip()
        measure = tkfont.Font(root=self.frame, font=font).measure
        if measure(text) <= limit:
            return text
        while text and measure(text + "…") > limit:
            text = text[:-1]
        return text.rstrip() + "…"

    def _build_row(self, event) -> None:
        theme = self.theme
        bg = theme.get("bg")
        row = self._row_frame()
        info_width = self.width - 2 * SIDE - INFO_X - 8

        # The hover surface: the row's rounded rectangle, shown under the text
        # while the pointer is over the row. A frame can only be a square
        # block of colour, so the shape is an image (ui/shapes.py).
        row_width = self.width - 2 * SIDE
        backdrop = tk.Label(
            row,
            image=self._shapes.image(
                row_width, ROW_HEIGHT, ROW_RADIUS, theme.get("hover"), None, bg
            ),
            bg=bg,
            bd=0,
            highlightthickness=0,
        )

        color = event.calendar_color or theme.accent
        bar = tk.Frame(row, bg=color, width=3, height=34)
        bar.place(x=8, y=8)

        start_text, end_text = event_time_lines(event)
        start_label = self._label(row, start_text, theme.get("fg"), theme.px(12, 500))
        start_label.place(x=TIME_X, y=9)
        end_label = self._label(row, end_text, theme.get("fg_faint"), theme.px(12))
        end_label.place(x=TIME_X, y=26)

        title_font = theme.px(14, 600)
        title_label = self._label(
            row, self._fit(event.title, title_font, info_width), theme.get("fg"), title_font
        )
        title_label.place(x=INFO_X, y=6)

        tinted = [start_label, end_label, title_label]
        meta_font = theme.px(12)
        measure = tkfont.Font(root=self.frame, font=meta_font).measure
        x = INFO_X
        if event.calendar_name:
            name = self._fit(event.calendar_name, meta_font, info_width // 2)
            calendar_label = self._label(row, name, color, meta_font)
            calendar_label.place(x=x, y=27)
            tinted.append(calendar_label)
            x += measure(name) + 6
        if event.location:
            text = self._fit(event.location, meta_font, INFO_X + info_width - x)
            extra_label = self._label(row, text, theme.get("fg_faint"), meta_font)
            extra_label.place(x=x, y=27)
            tinted.append(extra_label)

        # Hover shows the backdrop and gives the labels its colour, so their
        # own rectangles disappear into it. The calendar bar is never repainted:
        # its colour is the information.
        target = event.url or YANDEX_CALENDAR_URL
        for widget in tinted + [row, bar, backdrop]:
            widget.configure(cursor="hand2")
            widget.bind("<Button-1>", lambda _event, url=target, item=event: self._open(item, url))
            widget.bind("<MouseWheel>", self._on_wheel)
            widget.bind(
                "<Enter>",
                lambda _event, parts=tinted, back=backdrop: self._highlight(parts, back, True),
            )
            widget.bind(
                "<Leave>",
                lambda _event, parts=tinted, back=backdrop: self._highlight(parts, back, False),
            )

    def _highlight(self, parts: list, backdrop: tk.Label, active: bool) -> None:
        if active:
            backdrop.place(x=0, y=0)
            backdrop.lower()
        else:
            backdrop.place_forget()
        color = self.theme.get("hover") if active else self.theme.get("bg")
        for part in parts:
            part.configure(bg=color)

    def _open(self, event, url: str) -> None:
        if self.on_open_event is not None:
            self.on_open_event(event)
            return
        try:
            webbrowser.open(url)
        except Exception:
            pass
