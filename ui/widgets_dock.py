"""The second pill on the taskbar: the weather and four small indicators.

``panel.pen``, frame "Вариант 4", the "Widgets" pill. The weather is always
readable; the rest are icons, each with a popover of its own (``ui/popover.py``).
A number appears next to an icon only when something needs attention - a
keyboard at 15 %, a processor at 97 %:

    ┌──────────────────────────────────────┐
    │ ⛅ +8° │  ∿   ◷   🎧   ⌨ 15%          │
    └──────────────────────────────────────┘

It is a window of its own, to the left of the calendar's pill (``ui/dock.py``):
glass cannot have a see-through gap in the middle, so two pills are two windows.
It is drawn with the same glass, edge and height as that pill.

What the pill shows is decided in ``build_items`` and where each part goes in
``layout``; both are plain functions, tested without a display.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass
from typing import Callable

import devices as devices_module
from .dock import DOCK_HEIGHT, DOCK_TINT, GLASS_RADIUS, TEXT_LIFT, TEXT_SIZE, TRAY_HOVER_FILL
from .glass import apply_glass
from .shapes import ShapeCache
from .svg_icon import ASSETS, stroke_image
from .theme import Theme

WEATHER = "weather"
SYSTEM = "system"
APPS = "apps"
HEADPHONES = "headphones"
KEYBOARD = "keyboard"

#: The mockup's metrics: 6 px inside the pill, 4 px between its parts; a button
#: is 32 px tall with 8 px at its sides and rounded at 8 px; the icon is 16 px.
PILL_PADDING = 6
ITEM_GAP = 4
ITEM_HEIGHT = 32
ITEM_PADDING = 8
ITEM_RADIUS = 8
ICON_SIZE = 16
#: Between an icon and its text: 8 px for the weather, 6 px for a warning.
WEATHER_TEXT_GAP = 8
TEXT_GAP = 6
DIVIDER_HEIGHT = 18
#: Air between this pill and the calendar's.
PILL_GAP = 8
#: A battery bar beside an icon: 3 px wide, as tall as the icon, 6 px from it,
#: with round ends. Its charged part is white, its track the theme's soft grey.
BAR_WIDTH = 3
BAR_HEIGHT = ICON_SIZE
BAR_GAP = 6
BAR_RADIUS = BAR_WIDTH / 2
BAR_ACTIVE_COLOR = "#FFFFFF"
#: The bar turns this yellow at ``devices.LOW_BATTERY`` percent and below.
LOW_BAR_COLOR = "#FABD23"


@dataclass(frozen=True)
class Item:
    """One button of the pill."""

    name: str  # WEATHER, SYSTEM, ...
    icon: str  # a file in assets/, without ".svg"
    text: str = ""
    tone: str = "fg_dim"  # the icon's colour, a theme key
    level: int | None = None  # a battery bar of this many percent, when there is one
    level_tone: str = "active"  # the bar's fill: "active" (white) or a theme key; low is yellow


@dataclass(frozen=True)
class Slot:
    """Where an item is drawn."""

    item: Item
    x: int
    width: int
    text_x: int


def build_items(weather=None, load=None, apps: bool = True, devices=()) -> list[Item]:
    """The pill's buttons for the current readings, in the mockup's order.

    ``weather`` is a ``weather.Weather`` or None (no item then), ``load`` a
    ``system_load.Load`` or None, ``devices`` what ``devices.scan`` returned.
    """
    from weather import format_temperature

    items = []
    if weather is not None:
        items.append(Item(WEATHER, weather.icon, format_temperature(weather.temperature), "fg"))
    problem = load.problem if load is not None else None
    if problem:
        items.append(Item(SYSTEM, "activity", f"{problem[1]}%", "warn"))
    else:
        items.append(Item(SYSTEM, "activity"))
    if apps:
        items.append(Item(APPS, "timer"))
    for name, kind in ((HEADPHONES, devices_module.HEADPHONES), (KEYBOARD, devices_module.KEYBOARD)):
        device = devices_module.choose(list(devices), kind)
        # A bar whenever the device reports a charge, even when it is away: the
        # last level it reported, drawn faint.
        level = device.battery if device is not None else None
        level_tone = "active" if device is not None and device.connected else "fg_faint"
        if device is None or not device.connected:
            items.append(Item(name, name, tone="fg_faint", level=level, level_tone=level_tone))
        elif device.low:
            tone = "danger" if device.battery <= devices_module.CRITICAL_BATTERY else "warn"
            items.append(Item(name, name, f"{device.battery}%", tone, level, level_tone))
        else:
            items.append(Item(name, name, level=level, level_tone=level_tone))
    return items


def layout(items: list[Item], measure: Callable[[str], int]) -> tuple[int, list[Slot], int | None]:
    """``(pill width, slots, divider x)``; the divider follows the weather."""
    slots = []
    divider = None
    x = PILL_PADDING
    for index, item in enumerate(items):
        if index:
            x += ITEM_GAP
        gap = WEATHER_TEXT_GAP if item.name == WEATHER else TEXT_GAP
        bar = BAR_GAP + BAR_WIDTH if item.level is not None else 0
        text_x = x + ITEM_PADDING + ICON_SIZE + bar + gap
        width = 2 * ITEM_PADDING + ICON_SIZE + bar
        if item.text:
            width += gap + measure(item.text)
        slots.append(Slot(item, x, width, text_x))
        x += width
        if item.name == WEATHER and index < len(items) - 1:
            divider = x + ITEM_GAP
            x = divider + 1
    return (x + PILL_PADDING if slots else 0), slots, divider


class WidgetsDock:
    """The overlay pill. It owns no readings, only the items it was given."""

    def __init__(self, root: tk.Misc, theme: Theme, on_click: Callable[[str], None] | None = None) -> None:
        self.theme = theme
        self.on_click = on_click
        self.items: list[Item] = []
        self.slots: list[Slot] = []
        self.width = 0
        self._hover: str | None = None
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
            self.window, width=1, height=DOCK_HEIGHT, highlightthickness=0, bd=0,
            bg=theme.get("bg"), cursor="hand2",
        )
        self.canvas.pack()
        self._shapes = ShapeCache(self.canvas)
        self._icons: dict[tuple[str, str, str], tk.PhotoImage] = {}
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<Motion>", lambda event: self._set_hover(self.item_at(event.x)))
        self.canvas.bind("<Leave>", lambda _event: self._set_hover(None))
        self.window.withdraw()

    # -- placement ---------------------------------------------------------

    def place(self, x: int, y: int) -> None:
        self._position = (x, y)
        if self.width:
            self.window.geometry(f"{self.width}x{DOCK_HEIGHT}+{x}+{y}")

    def show(self) -> None:
        """Put the pill on screen; with nothing to show it stays hidden."""
        if not self.width:
            self.window.withdraw()
            return
        was_hidden = self.window.state() == "withdrawn"
        self.window.deiconify()
        if was_hidden:
            self.window.update()
        # As for the calendar's pill: glass is asked for on every call, and the
        # pill is lifted back above the taskbar.
        if self.theme.glass:
            apply_glass(self.window, *DOCK_TINT, border=None, classic=True)
        self.window.attributes("-topmost", True)
        self.window.lift()

    def hide(self) -> None:
        self.window.withdraw()

    def item_x(self, name: str) -> int | None:
        """Screen x of an item's left edge, for the popover to line up with."""
        for slot in self.slots:
            if slot.item.name == name and self._position is not None:
                return self._position[0] + slot.x
        return None

    # -- content -----------------------------------------------------------

    def set_items(self, items: list[Item]) -> bool:
        """Show ``items``. True when the pill's width changed with them."""
        if items == self.items:
            return False
        self.items = list(items)
        width = self.width
        self.render()
        return self.width != width

    def item_at(self, x: int) -> str | None:
        for slot in self.slots:
            if slot.x <= x < slot.x + slot.width:
                return slot.item.name
        return None

    def _set_hover(self, name: str | None) -> None:
        if name != self._hover:
            self._hover = name
            self.render()

    def _on_press(self, event: tk.Event) -> None:
        name = self.item_at(event.x)
        if name is not None and self.on_click is not None:
            self.on_click(name)

    def _battery_bar(self, slot: Slot, item: Item) -> None:
        """A vertical bar beside the icon, filled from the bottom to the item's level %."""
        level = item.level
        left = slot.x + ITEM_PADDING + ICON_SIZE + BAR_GAP
        top = (DOCK_HEIGHT - BAR_HEIGHT) // 2
        background = self.theme.get("bg")
        self._shapes.draw(
            self.canvas, left, top, BAR_WIDTH, BAR_HEIGHT, BAR_RADIUS,
            self.theme.get("border_soft"), None, background,
        )
        filled = round(BAR_HEIGHT * max(0, min(level, 100)) / 100)
        if not filled:
            return
        if level <= devices_module.LOW_BATTERY:
            color = LOW_BAR_COLOR
        elif item.level_tone == "active":
            color = BAR_ACTIVE_COLOR
        else:
            color = self.theme.get(item.level_tone)
        # The fill's ends are as round as the track's, but never rounder than it is tall.
        self._shapes.draw(
            self.canvas, left, top + BAR_HEIGHT - filled, BAR_WIDTH, filled,
            min(BAR_RADIUS, filled / 2), color, None, background,
        )

    def render(self) -> None:
        canvas = self.canvas
        canvas.delete("all")
        theme = self.theme
        font = theme.px(TEXT_SIZE, 500)
        width, self.slots, divider = layout(
            self.items, tkfont.Font(root=canvas, font=font).measure
        )
        if width != self.width:
            self.width = width
            canvas.configure(width=max(1, width))
            if self._position is not None:
                self.place(*self._position)
        if not width:
            return

        self._shapes.draw(
            canvas, 0, 0, width, DOCK_HEIGHT, GLASS_RADIUS,
            theme.get("bg"), theme.get("border_soft"),
        )
        top = (DOCK_HEIGHT - ITEM_HEIGHT) // 2
        middle = DOCK_HEIGHT / 2
        for slot in self.slots:
            item = slot.item
            # A hovered button is filled as a tray item is, the way the calendar's pill does it.
            under = theme.get("bg")
            if item.name == self._hover:
                under = TRAY_HOVER_FILL
            if under != theme.get("bg"):
                self._shapes.draw(
                    canvas, slot.x, top, slot.width, ITEM_HEIGHT, ITEM_RADIUS,
                    under, None, theme.get("bg"),
                )
            key = (item.icon, theme.get(item.tone), under)
            if key not in self._icons:
                self._icons[key] = stroke_image(
                    canvas, ASSETS / f"{item.icon}.svg", ICON_SIZE, key[1], key[2]
                )
            canvas.create_image(
                slot.x + ITEM_PADDING, (DOCK_HEIGHT - ICON_SIZE) // 2,
                anchor="nw", image=self._icons[key],
            )
            if item.level is not None:
                self._battery_bar(slot, item)
            if item.text:
                canvas.create_text(
                    slot.text_x, middle - TEXT_LIFT, text=item.text, fill=theme.get("fg"), font=font, anchor="w"
                )
        if divider is not None:
            divider_top = (DOCK_HEIGHT - DIVIDER_HEIGHT) // 2
            canvas.create_rectangle(
                divider, divider_top, divider + 1, divider_top + DIVIDER_HEIGHT,
                fill=theme.get("border_soft"), width=0,
            )
