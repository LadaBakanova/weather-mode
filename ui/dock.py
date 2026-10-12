"""The left end of the taskbar: a glass pill with the date and the next event.

The design (``design calendar.pen``, frame "Taskbar") puts a glass dock on the
left of the taskbar and the system tray on the right. This is that dock, drawn
to match the real pills of the FrostyGlass taskbar theme next to it, as measured
on this machine from a screenshot of the taskbar (0,1032 1920x48):

* the centre and tray pills start at the taskbar's top edge and are 43 px tall,
  leaving 5 px below them; the tray pill ends 8 px from the screen edge;
* their glass is the theme's ``$Background``: blur with ``SystemChromeDarkColor``
  at 15 %, so the wallpaper shows through blurred but almost undimmed. The dock
  gets the same from the classic acrylic recipe - see ``apply_glass``;
* the system icons are 16 px and white, the clock text is 12 px.

So the dock is a 43 px pill, 8 px from the left edge. What is in it follows
``panel.pen`` (frame "Вариант 4", the "Calendar" pill): a white 16 px calendar
glyph and today's date, then - when there is an event ahead - a divider, a dot
in the calendar's colour, the start time, the title and, in the last hour
before the start, how soon it is ("через час", "через 59 минут", ...):

    ┌──────────────────────────────────────────────────┐
    │ ▦  10 октября │ ● 16:00  Тренировка  через час   │
    └──────────────────────────────────────────────────┘

It is an ordinary window placed over the taskbar, not a change to the taskbar,
so it needs no injected code or extra rights. Its limits, stated plainly:

* it stays on screen over full-screen apps, because it is topmost like the
  taskbar itself; it goes away when the taskbar is hidden (auto-hide);
* the taskbar's own left end must be empty. With the taskbar aligned to the
  left (Start at the left) the dock would cover Start, so it is only meaningful
  for the default centred layout.

The geometry is kept in plain functions so it can be tested without a display.
"""

from __future__ import annotations

import math
import re
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, Iterable

from .day_view import format_day_long
from .glass import apply_glass
from .shapes import ShapeCache
from .svg_icon import ASSETS, stroke_image
from .theme import Theme

#: As tall as the theme's own pills; its width follows the date.
DOCK_HEIGHT = 43
#: The theme's $Background: a blur with SystemChromeDarkColor (#1F1F1F on this
#: machine) at 15 %. The same tint the media widget mod matched its glass to.
DOCK_TINT = ("#1F1F1F", 0.15)
#: White at 6 % and at 7 %, written as the greys glass adds (ui/theme.py).
TRAY_HOVER_FILL = "#0F0F0F"
TRAY_HOVER_EDGE = "#121212"
#: The radius DWM gives glass, the theme's element radius, the tray padding.
GLASS_RADIUS = 8
HOVER_RADIUS = 7
HOVER_INSET = 4
#: Horizontal layout inside the pill, the mockup's: 14 px padding on both
#: sides and 10 px between the parts - the 16 px icon, the date, the 1 x 18 px
#: divider, the 8 px colour dot, the time, the title, the countdown.
ICON_SIZE = 16
ICON_FILE = ASSETS / "vucalendar.svg"
PADDING = 14
GAP = 10
ICON_X = PADDING
TEXT_X = ICON_X + ICON_SIZE + GAP
TEXT_SIZE = 13
#: Tk centres a text on its line box, and Segoe UI's has more room above the
#: letters than below: at 13 px the digits came out 2 px under the pill's
#: middle (measured from a screenshot). The texts are drawn this much higher.
TEXT_LIFT = 2
DIVIDER_HEIGHT = 18
DOT_SIZE = 8
#: A longer title is cut with an ellipsis, and cut further when the pill would
#: otherwise outgrow ``TaskbarDock.max_width``: the dock must stay clear of the
#: taskbar's centred icons. A title with less room than TITLE_MINIMUM is left
#: out - the time and the countdown say more than three letters of a name.
TITLE_LIMIT = 220
TITLE_MINIMUM = 48
#: The share of the taskbar's width, from its left end, the two pills may take.
#: Windows does not say where the centred icons begin; on a 1920 px taskbar
#: with a dozen icons they start at about 37 %.
DOCK_SHARE = 0.34
#: The countdown is shown from this many minutes before the start.
SOON_MINUTES = 60
#: Distance from the taskbar's left edge to the dock, the design's 8 px padding.
DOCK_LEFT_GAP = 8
#: The flyout's left margin and the air between it and the taskbar.
FLYOUT_LEFT_GAP = 12
FLYOUT_GAP = 10


def dock_origin(taskbar_left: int, taskbar_top: int, taskbar_height: int) -> tuple[int, int]:
    """Top-left corner of the dock: at the taskbar's top edge, like its pills.

    A taskbar shorter than the pill (small-taskbar tweaks) keeps it centred.
    """
    x = taskbar_left + DOCK_LEFT_GAP
    y = taskbar_top + min(0, (taskbar_height - DOCK_HEIGHT) // 2)
    return x, y


def flyout_origin(taskbar_left: int, taskbar_top: int, flyout_height: int) -> tuple[int, int]:
    """Top-left corner of the flyout: at the left edge, sitting above the taskbar."""
    return taskbar_left + FLYOUT_LEFT_GAP, max(0, taskbar_top - FLYOUT_GAP - flyout_height)


@dataclass(frozen=True)
class NextEvent:
    """What the dock says about the nearest event, already worded."""

    when: str  # "16:00", "завтра 08:00"
    title: str
    color: str = ""  # the calendar's colour; empty means the theme's accent
    soon: str = ""  # "через час", "через 59 минут"; empty while it is far off


def plural_minutes(count: int) -> str:
    """Russian plural after "через": 1 минуту, 2 минуты, 5 минут."""
    last_two = count % 100
    last = count % 10
    if last == 1 and last_two != 11:
        word = "минуту"
    elif last in (2, 3, 4) and last_two not in (12, 13, 14):
        word = "минуты"
    else:
        word = "минут"
    return f"{count} {word}"


def soon_label(start: datetime, now: datetime) -> str:
    """How soon ``start`` is, for the last hour before it; "" otherwise.

    Minutes are rounded up, the way a countdown is read: with 59 min 20 s to go
    it is still "через час", and the last minute is "через 1 минуту".
    """
    minutes = math.ceil((start - now).total_seconds() / 60)
    if minutes <= 0 or minutes > SOON_MINUTES:
        return ""
    if minutes == 60:
        return "через час"
    return f"через {plural_minutes(minutes)}"


def when_label(start: datetime, now: datetime) -> str:
    """The start as the dock shows it: the time, with the day when not today."""
    start = start.astimezone(now.tzinfo)
    time_text = start.strftime("%H:%M")
    days = (start.date() - now.date()).days
    if days == 0:
        return time_text
    if days == 1:
        return f"завтра {time_text}"
    return f"{format_day_long(start.date())} {time_text}"


def pick_next(events: Iterable, now: datetime):
    """The timed event that starts soonest after ``now`` today, or None.

    Only today's events are shown: a later day is left to the calendar flyout.
    All-day events have no moment to count down to, and an event that has
    already started is no longer ahead.
    """
    best = None
    best_start = None
    for event in events:
        if event.all_day:
            continue
        start = event.start_dt
        if not isinstance(start, datetime) or start <= now:
            continue
        if start.astimezone(now.tzinfo).date() != now.date():
            continue
        if best_start is None or start < best_start:
            best, best_start = event, start
    return best


def describe_next(events: Iterable, now: datetime) -> NextEvent | None:
    """The dock's wording for the nearest event among ``events``."""
    event = pick_next(events, now)
    if event is None:
        return None
    start = event.start_dt
    return NextEvent(
        when=when_label(start, now),
        title=event.title.strip(),
        color=event.calendar_color,
        soon=soon_label(start, now),
    )


_HEX_COLOR = re.compile(r"#[0-9A-Fa-f]{6}\Z")


def _six_digits(color: str) -> str:
    """``#RGB`` written out as ``#RRGGBB``; the shapes take only the long form."""
    if len(color) == 4:
        return "#" + "".join(character * 2 for character in color[1:])
    return color


class TaskbarDock:
    """The overlay button. It owns no calendar data, only what it shows."""

    def __init__(
        self,
        root: tk.Misc,
        theme: Theme,
        on_click: Callable[[], None],
        today: date | None = None,
    ) -> None:
        self.theme = theme
        self.on_click = on_click
        self.today = today or date.today()
        self.event: NextEvent | None = None
        #: The widest the pill may get; None for as wide as its content.
        self.max_width: int | None = None
        self.active = False
        self._hover = False
        self.width = TEXT_X + PADDING
        self._position: tuple[int, int] | None = None

        self.window = tk.Toplevel(root)
        self.window.overrideredirect(True)
        self.window.resizable(False, False)
        self.window.configure(bg=theme.get("bg"))
        try:
            self.window.wm_attributes("-toolwindow", True)
            self.window.attributes("-topmost", True)
        except tk.TclError:
            pass

        self.canvas = tk.Canvas(
            self.window,
            width=self.width,
            height=DOCK_HEIGHT,
            highlightthickness=0,
            bd=0,
            bg=theme.get("bg"),
            cursor="hand2",
        )
        self.canvas.pack()
        self._shapes = ShapeCache(self.canvas)
        self._icons: dict[tuple[str, str], tk.PhotoImage] = {}
        self.canvas.bind("<Button-1>", lambda _event: self.on_click())
        self.canvas.bind("<Enter>", lambda _event: self._set_hover(True))
        self.canvas.bind("<Leave>", lambda _event: self._set_hover(False))

        self.render()
        self._apply_glass()
        self.window.withdraw()

    def _apply_glass(self) -> None:
        if self.theme.glass:
            tint, opacity = DOCK_TINT
            apply_glass(self.window, tint, opacity, border=None, classic=True)

    # -- placement ---------------------------------------------------------

    def place(self, x: int, y: int) -> None:
        self._position = (x, y)
        self.window.geometry(f"{self.width}x{DOCK_HEIGHT}+{x}+{y}")

    def show(self) -> None:
        was_hidden = self.window.state() == "withdrawn"
        self.window.deiconify()
        if was_hidden:
            # The window has to be really on screen before glass is asked for.
            self.window.update()
        # Asked for on every call (the widget calls this every few seconds):
        # the compositor drops the glass of a window that was hidden, and
        # setting the same policy again costs nothing.
        self._apply_glass()
        self.window.attributes("-topmost", True)
        # The taskbar is topmost too; lifting keeps the dock above it after the
        # taskbar has been clicked or has re-raised itself.
        self.window.lift()

    def hide(self) -> None:
        self.window.withdraw()

    # -- content -----------------------------------------------------------

    def set_today(self, day: date) -> None:
        if day != self.today:
            self.today = day
            self.render()

    def set_event(self, event: NextEvent | None) -> None:
        """Show the nearest event after the date, or only the date for None."""
        if event != self.event:
            self.event = event
            self.render()

    def set_max_width(self, width: int | None) -> None:
        """Keep the pill within ``width`` pixels by cutting the event's title."""
        if width != self.max_width:
            self.max_width = width
            self.render()

    def set_active(self, active: bool) -> None:
        """Mark the button as pressed in while the flyout is open."""
        if active != self.active:
            self.active = active
            self.render()

    def _set_hover(self, hover: bool) -> None:
        if hover != self._hover:
            self._hover = hover
            self.render()

    def _fit(self, text: str, font: tkfont.Font, limit: int) -> str:
        """Shorten ``text`` with an ellipsis so it fits ``limit`` pixels."""
        if font.measure(text) <= limit:
            return text
        while text and font.measure(text + "…") > limit:
            text = text[:-1]
        return text.rstrip() + "…"

    def render(self) -> None:
        canvas = self.canvas
        canvas.delete("all")
        theme = self.theme
        fg = theme.get("fg")
        middle = DOCK_HEIGHT / 2

        # Laid out before anything is drawn, because the pill is as wide as its
        # content: "1 мая" and "30 сентября" differ by a third of the date
        # alone, and the event comes and goes. Each text is (x, text, colour,
        # font); the divider and the dot only need their x.
        medium = theme.px(TEXT_SIZE, 500)
        metrics = tkfont.Font(root=canvas, font=medium)
        texts = [(TEXT_X, format_day_long(self.today), fg, medium)]
        x = TEXT_X + metrics.measure(texts[0][1])
        divider_x = dot_x = None
        event = self.event
        if event is not None:
            divider_x = x + GAP
            dot_x = divider_x + 1 + GAP
            x = dot_x + DOT_SIZE + GAP
            texts.append((x, event.when, fg, medium))
            x += metrics.measure(event.when)
            regular = theme.px(TEXT_SIZE)
            soon_width = 0
            if event.soon:
                soon_width = GAP + tkfont.Font(root=canvas, font=regular).measure(event.soon)
            # The title gets what the time, the countdown and the padding leave.
            limit = TITLE_LIMIT
            if self.max_width is not None:
                limit = min(limit, self.max_width - x - GAP - soon_width - PADDING)
            title = self._fit(event.title, metrics, limit) if limit >= TITLE_MINIMUM else ""
            if title:
                texts.append((x + GAP, title, fg, medium))
                x += GAP + metrics.measure(title)
            if event.soon:
                texts.append((x + GAP, event.soon, theme.get("fg_dim"), regular))
                x += soon_width
        width = x + PADDING
        if width != self.width:
            self.width = width
            canvas.configure(width=width)
            if self._position is not None:
                self.place(*self._position)

        # The pill's edge. The theme's BorderBrush is grey at 31 % (#50808080,
        # dipping to #50404040 a quarter of the way down); on glass a colour is
        # added to what is behind it, so that is a grey of about a third of
        # those levels. Without it the pill vanishes over a dark wallpaper.
        # Its radius is the 8 px Windows rounds the glass itself at - the only
        # rounding glass can have (a region does not clip it), so the theme's
        # 10 px is out of reach here.
        self._shapes.draw(
            canvas, 0, 0, width, DOCK_HEIGHT, GLASS_RADIUS,
            theme.get("bg"), theme.get("border_soft"),
        )

        # Hover and "flyout open", as a tray item shows them: Windows fills the
        # item with white at 6 % (SubtleFillColorSecondary) inside a 1 px edge
        # of white at 7 % (ControlStrokeColorDefault), and the theme rounds it
        # at 7 px with its 4 px tray padding above and below. These are the
        # system's documented values, not a measurement: this session cannot
        # make the real tray show its hover to photograph it.
        if self.active or self._hover:
            self._shapes.draw(
                canvas, HOVER_INSET, HOVER_INSET,
                width - 2 * HOVER_INSET, DOCK_HEIGHT - 2 * HOVER_INSET,
                HOVER_RADIUS, TRAY_HOVER_FILL, TRAY_HOVER_EDGE,
            )
        # assets/vucalendar.svg at 16 px and in white, like the tray's system
        # icons. It is drawn once per background it lies on. At this size its
        # strokes are 1 px wide and centred on pixel edges; half a pixel of
        # shift puts the sides and the header line on whole pixels.
        under = TRAY_HOVER_FILL if self.active or self._hover else theme.get("bg")
        key = (fg, under)
        if key not in self._icons:
            self._icons[key] = stroke_image(
                canvas, ICON_FILE, ICON_SIZE, *key, shift=(0.5, 0.5)
            )
        canvas.create_image(
            ICON_X, (DOCK_HEIGHT - ICON_SIZE) // 2, anchor="nw", image=self._icons[key]
        )
        if event is not None:
            # The mockup's divider is the pill's own stroke colour.
            top = (DOCK_HEIGHT - DIVIDER_HEIGHT) // 2
            canvas.create_rectangle(
                divider_x, top, divider_x + 1, top + DIVIDER_HEIGHT,
                fill=theme.get("border_soft"), width=0,
            )
            color = event.color if _HEX_COLOR.match(event.color) else _six_digits(theme.accent)
            self._shapes.draw(
                canvas, dot_x, round(middle - DOT_SIZE / 2), DOT_SIZE, DOT_SIZE,
                DOT_SIZE / 2, color, None, under,
            )
        for text_x, text, color, font in texts:
            canvas.create_text(text_x, middle - TEXT_LIFT, text=text, fill=color, font=font, anchor="w")
