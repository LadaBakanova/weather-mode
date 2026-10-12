"""The small glass panel that opens above a taskbar widget.

``panel.pen``, frame "Вариант 4": every icon of the Widgets pill has a popover
of its own. The mockup draws one of them, "App Time Popover"; the others here
follow its metrics - 18 px padding, 16 px between blocks, a 14 px semibold
title, 12 px secondary text, 4 px level bars. The weather has a mockup of its
own, "Вариант 3 — Шкала и список": not glass but a painted sky (``ui/sky.py``),
whose clouds drift while the window is open - unless it rains.

    ┌──────────────────────────────────────┐
    │ Время в приложениях     [День|Неделя]│
    │ 6 ч 42 м                             │
    │ за сегодня · на 38 м больше, чем вчера│
    │ Figma     ████████████████   2 ч 14 м│
    │ Chrome    ████████████       1 ч 48 м│
    │ ──────────────────────────────────── │
    │ Больше всего — Figma, треть времени  │
    └──────────────────────────────────────┘

A popover is described before it is drawn: each ``build_*`` function turns the
readings into a list of drawing operations and a height. That keeps the layout
testable without a window, and lets ``Popover.update`` skip the repaint when
a new reading changes nothing that is shown - the processor load arrives every
second, the picture changes far less often.

Operations (``y`` of a text is its middle line):

    ("text", x, y, text, colour, (size, weight), anchor)
    ("rect", x, y, width, height, radius, colour[, colour under it])
    ("icon", x, y, name, colour, size)
    ("hit",  x, y, width, height, action)      a clickable area

and, for the weather's opaque window, where a colour may carry an alpha:

    ("sky",   width, height, scene)            the background
    ("glaze", x, y, width, height, radius, "#RRGGBBAA")
    ("glyph", x, y, name, size)                a white icon

A colour is a key of the theme or, on the sky, a literal "#RRGGBB".
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from ctypes import wintypes
from datetime import datetime
from typing import Callable

import app_time
import devices as devices_module
import system_load
from weather import format_temperature

from . import sky, splash, trickle
from .glass import apply_glass
from .shapes import ShapeCache, glaze_image, png_bytes, rounded_pixels, veil_png
from .svg_icon import ASSETS, alpha_image, stroke_image
from .theme import GLASS_TINT, Theme
from .widgets_dock import APPS, HEADPHONES, KEYBOARD, SYSTEM, WEATHER

PADDING = 18
BLOCK_GAP = 16
WIDTH = 300
APPS_WIDTH = 360  # the mockup's App Time Popover
BAR_HEIGHT = 4
#: The App Time rows: a name column, the mockup's 140 px bar, the time.
APP_NAME_WIDTH = 108
APP_BAR_WIDTH = 140
ROW_GAP = 10

TITLE = (14, 600)
BIG = (28, 600)
BODY = (13, 400)
SMALL = (12, 400)
SMALL_MEDIUM = (12, 500)

Measure = Callable[[str, tuple], int]
Ops = list[tuple]


def fit(text: str, font: tuple, limit: int, measure: Measure) -> str:
    """Shorten ``text`` with an ellipsis so it fits ``limit`` pixels."""
    text = text.strip()
    if measure(text, font) <= limit:
        return text
    while text and measure(text + "…", font) > limit:
        text = text[:-1]
    return text.rstrip() + "…"


def _bar(ops: Ops, x: int, y: int, width: int, share: float, color: str, track: bool = True) -> None:
    """A level bar: ``share`` (0..1) of ``width``, on a track or without one."""
    if track:
        ops.append(("rect", x, y, width, BAR_HEIGHT, BAR_HEIGHT / 2, "track"))
    level = round(width * max(0.0, min(1.0, share)))
    if level >= BAR_HEIGHT:
        ops.append(("rect", x, y, level, BAR_HEIGHT, BAR_HEIGHT / 2, color))


def _divider(ops: Ops, y: int, width: int) -> None:
    ops.append(("rect", PADDING, y, width - 2 * PADDING, 1, 0, "border_soft"))


def _number(value: float) -> str:
    """A decimal the Russian way: 8,6."""
    return f"{value:g}".replace(".", ",")


# ---------------------------------------------------------------------------
# App time
# ---------------------------------------------------------------------------


def build_apps(day: app_time.Summary, week: app_time.Summary, show_week: bool, measure: Measure):
    width = APPS_WIDTH
    summary = week if show_week else day
    ops: Ops = []
    right = width - PADDING

    # Header: the title and the День / Неделя switch, a 28 px row.
    y = PADDING
    ops.append(("text", PADDING, y + 14, "Время в приложениях", "fg", TITLE, "w"))
    labels = [("Неделя", True), ("День", False)]
    x = right - 2
    cells = []
    for label, is_week in labels:  # laid out from the right edge
        cell = measure(label, SMALL_MEDIUM) + 20
        x -= cell
        cells.append((x, cell, label, is_week))
    ops.append(("rect", x - 2, y, right - x + 2, 28, 8, "track"))
    for cell_x, cell, label, is_week in cells:
        chosen = is_week == show_week
        if chosen:
            ops.append(("rect", cell_x, y + 2, cell, 24, 6, "switch_on", "track"))
        ops.append(
            ("text", cell_x + cell // 2, y + 13, label, "fg" if chosen else "fg_dim",
             SMALL_MEDIUM, "center")
        )
        ops.append(("hit", cell_x, y, cell, 28, "week" if is_week else "day"))
    y += 28 + BLOCK_GAP

    # Total: the big number and what it is compared with.
    ops.append(("text", PADDING, y + 16, app_time.format_duration(summary.total), "fg", BIG, "w"))
    ops.append(
        ("text", PADDING, y + 44, app_time.describe_total(summary, show_week), "fg_dim", SMALL, "w")
    )
    y += 52 + BLOCK_GAP

    if not summary.apps:
        ops.append(("text", PADDING, y + 8, "Пока нечего показать: счёт идёт,", "fg_dim", SMALL, "w"))
        ops.append(("text", PADDING, y + 26, "пока виджет запущен.", "fg_dim", SMALL, "w"))
        return ops, y + 34 + PADDING, width

    longest = summary.apps[0].seconds or 1.0
    bar_x = PADDING + APP_NAME_WIDTH + ROW_GAP
    for index, app in enumerate(summary.apps):
        middle = y + 8
        name = fit(app.name, BODY, APP_NAME_WIDTH, measure)
        ops.append(("text", PADDING, middle, name, "fg", BODY, "w"))
        # The mockup has no track here: the first bar is the measure of the rest.
        _bar(ops, bar_x, middle - BAR_HEIGHT // 2, APP_BAR_WIDTH, app.seconds / longest,
             "info" if index == 0 else "bar", track=False)
        ops.append(
            ("text", right, middle, app_time.format_duration(app.seconds), "fg_dim",
             SMALL_MEDIUM, "e")
        )
        y += 16 + 12
    y += BLOCK_GAP - 12

    _divider(ops, y, width)
    y += 1 + BLOCK_GAP
    leader = fit(app_time.describe_leader(summary), SMALL, width - 2 * PADDING, measure)
    ops.append(("text", PADDING, y + 7, leader, "fg_dim", SMALL, "w"))
    return ops, y + 15 + PADDING, width


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------


def _level_color(percent: int, limit: int) -> str:
    if percent >= limit:
        return "danger"
    if percent >= limit - 15:
        return "warn"
    return "info"


def build_system(load: system_load.Load | None, measure: Measure):
    width = WIDTH
    ops: Ops = [("text", PADDING, PADDING + 10, "Система", "fg", TITLE, "w")]
    y = PADDING + 20 + BLOCK_GAP
    if load is None:
        ops.append(("text", PADDING, y + 8, "Измеряю…", "fg_dim", SMALL, "w"))
        return ops, y + 16 + PADDING, width
    rows = [
        ("cpu", "Процессор", f"{load.cpu} %", load.cpu, system_load.CPU_LIMIT),
        (
            "memory-stick",
            "Память",
            f"{system_load.format_bytes(load.memory_used)} из "
            f"{system_load.format_bytes(load.memory_total)}",
            load.memory,
            system_load.MEMORY_LIMIT,
        ),
        (
            "hard-drive",
            "Системный диск",
            f"свободно {system_load.format_bytes(load.disk_free)}",
            load.disk,
            system_load.DISK_LIMIT,
        ),
    ]
    # The mockup's 16 px icon on a soft rounded tile as tall as the label and
    # the bar beside it (16 + 8 + 4 px), then 12 px of air; the label and the
    # bar both start after it, so the three rows line up.
    tile = 16 + 8 + BAR_HEIGHT
    content = PADDING + tile + 12
    for index, (icon, label, detail, percent, limit) in enumerate(rows):
        if index:
            y += 14
        ops.append(("rect", PADDING, y, tile, tile, 8, "track"))
        # The last item is what the icon lies on: glass shows the tile's grey
        # through the pixels the stroke does not cover.
        ops.append(
            ("icon", PADDING + (tile - 16) // 2, y + (tile - 16) // 2, icon, "fg", 16, "track")
        )
        ops.append(("text", content, y + 8, label, "fg", BODY, "w"))
        ops.append(("text", width - PADDING, y + 8, detail, "fg_dim", SMALL_MEDIUM, "e"))
        y += 16 + 8
        _bar(ops, content, y, width - PADDING - content, percent / 100, _level_color(percent, limit))
        y += BAR_HEIGHT
    return ops, y + PADDING, width


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------


#: The weather window is "Вариант 3 — Шкала и список" of ``panel.pen``: it has
#: the sky for a background and its own metrics - 20 px padding, 18 px between
#: blocks - and everything on it is white, some of it translucent.
SKY_PADDING = 20
SKY_GAP = 18
HERO = (64, 400)
#: How far the big number's first glyph stands in from its origin (a sign, or a
#: digit), so it can be pulled back to the content's left edge.
HERO_BEARING_SIGN = 6
HERO_BEARING_DIGIT = 3
#: The low and the high at the scale's ends: two pixels larger than the labels.
SCALE_TEMPERATURE = (14, 500)
#: Segoe UI: the baseline lies this far (in em) below the middle of the line,
#: and its figures are this tall.
BASELINE_DROP = 0.414
CAP_HEIGHT = 0.7
#: The largest the "feels like" figure may grow to.
FEELS_MAX = 40
HOUR_TEMPERATURE = (13, 500)
SCALE_WIDTH = 176
DOT = 12
#: The hours' plate (#0B0E1A at 45 %) and what lies on it.
PLATE = "#0B0E1A73"
PLATE_PADDING = 14
PLATE_ROW_GAP = 12
PLATE_RADIUS = 12
#: The snow on the plate's top edge stops this short of its sides - past the rounded corners.
CAP_INSET = PLATE_RADIUS  # where the plate's rounded corners end; the snow falls away from there
#: How often it is looked whether a sky being made ready is worked out.
PREPARE_POLL_MS = 40
#: And how often Python switches between that thread and the widget's meanwhile.
PREPARE_SWITCH_S = 0.0005
#: The large layers that move are veiled by squares of this many pixels (``veil_png``).
VEIL_BLOCK = 8
#: In the rain the plate is frosted glass: what is behind it is blurred this far.
PLATE_BLUR = 7
#: The rain comes down on the plate's top edge, clear of its round corners.
LEDGE_INSET = 9
#: The most splashes that are drawn at once.
SPLASHES = 64
#: The most running drops and lengths of their tracks that are drawn at once.
TRICKLES = 72
TIME_WIDTH = 38
TEMPERATURE_WIDTH = 32
ON_SKY = "#FFFFFF"
#: The clouds drift: a strip this wide goes round over the sky at this many
#: pixels a second, looked at every ``DRIFT_MS``. Slow enough to be weather and
#: not a screensaver - and so slow that a pixel at a time it is seen to step,
#: so a step is a ``DRIFT_PHASES``-th of a pixel: twenty steps a second.
CLOUD_PERIOD = 2 * WIDTH
#: A blizzard's veils of blown snow go round over a strip this wide, and its
#: clouds go the way the snow is blown.
VEIL_PERIOD = 2 * WIDTH
DRIFT = 4
DRIFT_PHASES = 5
DRIFT_MS = 25
ON_PLATE_DIM = "#D0D1D4"  # white at 80 % on the plate


def still_sky(op: tuple) -> bytes:
    """The sky that does not move - without its clouds and its rain where
    those are to - as RGB rows."""
    _, width, height, scene, _ledge = op
    drifting, falling = sky.drifts(scene), sky.falls(scene) or sky.snows(scene)
    return sky.render(
        width, height, scene, clouds=not drifting, streaks=not falling, glass=not falling,
        rays=not sky.sun_moves(scene),
    )


def moving_sky(op: tuple, still: bytes) -> dict:
    """All that moves over a sky, worked out and packed as PNG files: most of
    a second's work for a rainy one. Nothing here touches Tk, so it can be
    done on another thread while the widget goes on (``Popover.prepare``);
    the pictures are made of it afterwards (``Popover._pictures``)."""
    _, width, height, scene, ledge = op
    drifting, falling = sky.drifts(scene), sky.falls(scene)
    parts = {
        "strips": [], "rain": [], "lightning": [], "shelter": None, "splashes": None, "glass": None,
        "trickles": None, "wet": None, "caps": [], "veil": None, "sun": None,
    }
    clouds = []
    if drifting:
        clouds = sky.cloud_strips(width, height, scene, CLOUD_PERIOD, DRIFT_PHASES)
        parts["strips"] = [veil_png(CLOUD_PERIOD, height, strip, VEIL_BLOCK) for strip in clouds]
    if falling:
        layers = sky.rain_layers(width, height, scene)
        parts["rain"] = [
            (layer, [veil_png(layer.width, layer.height, layer.pixels, VEIL_BLOCK)]) for layer in layers
        ]
        drops = sky.glass_drops(width, height, scene)
        if ledge:
            # The plate is frosted glass in the rain: neither the rain nor the
            # drops on the window show through it, only a blur of the sky, the
            # clouds and the wet. And on its edge the rain lands.
            x, y, wide, tall, radius = ledge
            behind = [(strip, CLOUD_PERIOD) for strip in clouds[:1]] + [(drops, width)]
            under = sky.frosted(width, still, (x, y, wide, tall), behind, PLATE_BLUR)
            parts["shelter"] = png_bytes(wide, tall, rounded_pixels(wide, tall, radius, under), alpha=True)
            parts["splashes"] = splash.Splashes(layers, (x + LEDGE_INSET, y, x + wide - LEDGE_INSET), scene.seed)
            # And the edge it lands on is wet all along.
            parts["wet"] = veil_png(*splash.ledge_water(wide - 2 * LEDGE_INSET + 6, scene))
        parts["glass"] = png_bytes(width, height, drops, alpha=True)
        # They go behind the plate, not down the strips at its sides.
        sides = (ledge[0], ledge[0] + ledge[2]) if ledge else None
        parts["trickles"] = trickle.Trickles(width, height, scene.seed, sides)
    elif sky.snows(scene):
        # The snow's layers go where the rain's do, and the plate is frosted in
        # the snow too: the flakes come down behind it, not through it.
        parts["rain"] = [
            (layer, [veil_png(layer.width, layer.height, rows, VEIL_BLOCK) for rows in sky.layer_phases(layer)])
            for layer in sky.snow_layers(width, height, scene)
        ]
        if ledge:
            x, y, wide, tall, radius = ledge
            behind = [(strip, CLOUD_PERIOD) for strip in clouds[:1]]
            under = sky.frosted(width, still, (x, y, wide, tall), behind, PLATE_BLUR)
            parts["shelter"] = png_bytes(wide, tall, rounded_pixels(wide, tall, radius, under), alpha=True)
            # And on the plate's top edge the snow lies.
            parts["caps"] = [
                png_bytes(*sky.snow_cap(wide - 2 * CAP_INSET, scene, sky.DESIGN_WIDTH / width), alpha=True)
            ]
        if scene.gale:
            parts["veil"] = png_bytes(
                VEIL_PERIOD, height, sky.gale_veil(width, height, scene, VEIL_PERIOD), alpha=True
            )
    if scene.lightning:
        parts["lightning"] = [veil_png(width, height, light) for light in sky.flashes(width, height, scene)]
    if sky.sun_moves(scene):
        parts["sun"] = (width, height, scene)  # its rays are drawn as they move (``_slide``)
    return parts


def build_weather(weather, measure: Measure, now: datetime | None = None):
    width = WIDTH
    ops: Ops = []
    if weather is None:
        ops.append(("text", PADDING, PADDING + 10, "Погода", "fg", TITLE, "w"))
        y = PADDING + 20 + BLOCK_GAP
        ops.append(("text", PADDING, y + 8, "Нет данных: сервис погоды не отвечает.", "fg_dim", SMALL, "w"))
        return ops, y + 16 + PADDING, width

    left, right = SKY_PADDING, width - SKY_PADDING
    inner = right - left
    ledge = None  # the hours' plate: the rain lands on it and does not show through

    # Header: the place, and the sky in a word on the right.
    y = SKY_PADDING
    description = fit(weather.description, SMALL_MEDIUM, inner * 2 // 3 - 22, measure)
    described = measure(description, SMALL_MEDIUM)
    place = fit(weather.place or "Погода", TITLE, inner - described - 22 - 12, measure)
    ops.append(("text", left, y + 9, place, ON_SKY, TITLE, "w"))
    ops.append(("glyph", right - described - 6 - 16, y + 1, weather.icon, 16))
    ops.append(("text", right, y + 9, description, ON_SKY, SMALL_MEDIUM, "e"))
    y += 18 + SKY_GAP

    # Now: the big thin number, "feels like" standing on its baseline.
    big = format_temperature(weather.temperature)
    # The glyph's own side bearing pushes the number in from the edge; take it
    # back so its left side stands on the same line as the rest of the content.
    bearing = HERO_BEARING_SIGN if big[:1] in "+-−" else HERO_BEARING_DIGIT
    ops.append(("text", left - bearing, y + 29, big, ON_SKY, HERO, "w"))
    # "Feels like" in two lines against the right edge: the words, and under them
    # the figure, as large as makes it exactly as long as the words.
    caption = "ощущается как"
    feels = format_temperature(weather.feels_like)
    room = inner - measure(big, HERO) - 12
    target = min(measure(caption, SMALL), room)
    size = SMALL[0]
    while size < FEELS_MAX and measure(feels, (size + 1, SMALL[1])) <= target:
        size += 1
    # Text is placed by the middle of its line, whose baseline lies BASELINE_DROP
    # of the size below it: the figure stands on the big number's baseline.
    baseline = y + 29 + round(HERO[0] * BASELINE_DROP)
    middle = baseline - round(size * BASELINE_DROP) + 1  # measured on screen
    ops.append(("text", right, baseline - round(size * CAP_HEIGHT) - 16, caption, ON_SKY, SMALL, "e"))
    ops.append(("text", right, middle, feels, ON_SKY, (size, SMALL[1]), "e"))
    y += 64

    # The day's scale: a dot where "now" is between the low and the high.
    if weather.low is not None and weather.high is not None:
        y += 14
        low, high = format_temperature(weather.low), format_temperature(weather.high)
        labels = measure(low, SCALE_TEMPERATURE) + measure(high, SCALE_TEMPERATURE)
        track = min(SCALE_WIDTH, inner - labels - 20)
        x = left + measure(low, SCALE_TEMPERATURE) + (inner - labels - track) // 2
        span = weather.high - weather.low
        share = (weather.temperature - weather.low) / span if span > 0 else 0.5
        dot = x + round(max(0.0, min(1.0, share)) * (track - DOT))
        ops.append(("text", left, y + 8, low, ON_SKY, SCALE_TEMPERATURE, "w"))
        ops.append(("glaze", x, y + 6, track, BAR_HEIGHT, BAR_HEIGHT / 2, "#FFFFFF66"))
        ops.append(("glaze", dot - 1, y + 2, DOT + 2, DOT + 2, DOT / 2 + 1, "#00000038"))  # its shadow
        ops.append(("glaze", dot, y + 2, DOT, DOT, DOT / 2, "#FFFFFFFF"))
        ops.append(("text", right, y + 8, high, ON_SKY, SCALE_TEMPERATURE, "e"))
        y += 16
    y += SKY_GAP

    # The hours ahead, a row each on a dark plate: the sky stays above, and the
    # forecast reads in any weather.
    if weather.hours:
        rows = len(weather.hours)
        plate = 2 * PLATE_PADDING + 16 * rows + PLATE_ROW_GAP * (rows - 1)
        ledge = (left, y, inner, plate, PLATE_RADIUS)
        ops.append(("glaze", left, y, inner, plate, PLATE_RADIUS, PLATE))
        # A bar is the hour's place between the coldest and the warmest shown.
        known = [hour.temperature for hour in weather.hours] + [weather.temperature]
        known += [value for value in (weather.low, weather.high) if value is not None]
        coldest, spread = min(known), max(known) - min(known)
        icon_x = left + PLATE_PADDING + TIME_WIDTH + 10
        bar_x = icon_x + 16 + 10
        bar = right - PLATE_PADDING - TEMPERATURE_WIDTH - 10 - bar_x
        for index, hour in enumerate(weather.hours):
            top = y + PLATE_PADDING + index * (16 + PLATE_ROW_GAP)
            middle = top + 8
            ops.append(("text", left + PLATE_PADDING, middle, hour.time, ON_PLATE_DIM, SMALL, "w"))
            ops.append(("glyph", icon_x, top, hour.icon, 16))
            share = 0.25 + 0.66 * ((hour.temperature - coldest) / spread if spread else 0.5)
            ops.append(("glaze", bar_x, middle - 2, bar, BAR_HEIGHT, BAR_HEIGHT / 2, "#FFFFFF33"))
            ops.append(("glaze", bar_x, middle - 2, round(bar * share), BAR_HEIGHT, BAR_HEIGHT / 2, "#FFFFFFFF"))
            ops.append(
                ("text", right - PLATE_PADDING, middle, format_temperature(hour.temperature),
                 ON_SKY, HOUR_TEMPERATURE, "e")
            )
        y += plate + SKY_GAP

    ops.append(
        ("text", left, y + 8, f"Ветер {_number(weather.wind)} м/с · влажность {weather.humidity} %",
         ON_SKY, SMALL, "w")
    )
    height = y + 16 + SKY_PADDING
    scene = sky.scene_for(weather.phase(now or datetime.now()), weather.icon, weather.blizzard, weather.wind)
    return [("sky", width, height, scene, ledge), *ops], height, width


# ---------------------------------------------------------------------------
# Headphones and keyboard
# ---------------------------------------------------------------------------

_DEVICE_WORDS = {
    HEADPHONES: ("Наушники", "Подключены", "Не подключены", "Bluetooth-наушники не найдены."),
    KEYBOARD: ("Клавиатура", "Подключена", "Не подключена", "Bluetooth-клавиатура не найдена."),
}


def build_device(kind: str, device: devices_module.Device | None, measure: Measure):
    width = WIDTH
    title, on, off, missing = _DEVICE_WORDS[kind]
    ops: Ops = [("text", PADDING, PADDING + 10, title, "fg", TITLE, "w")]
    y = PADDING + 20 + BLOCK_GAP
    if device is None:
        ops.append(("text", PADDING, y + 8, missing, "fg", BODY, "w"))
        ops.append(("text", PADDING, y + 30, "Заряд виден у устройств, которые", "fg_dim", SMALL, "w"))
        ops.append(("text", PADDING, y + 47, "подключены к компьютеру по Bluetooth.", "fg_dim", SMALL, "w"))
        return ops, y + 55 + PADDING, width

    state = on if device.connected else off
    state_width = measure(state, SMALL)
    name = fit(device.name or title, BODY, width - 2 * PADDING - state_width - 12, measure)
    ops.append(("text", PADDING, y + 8, name, "fg", BODY, "w"))
    ops.append(
        ("text", width - PADDING, y + 8, state, "ok" if device.connected else "fg_faint", SMALL, "e")
    )
    y += 16 + BLOCK_GAP
    if device.battery is None:
        ops.append(("text", PADDING, y + 8, "Устройство не сообщает свой заряд.", "fg_dim", SMALL, "w"))
        return ops, y + 16 + PADDING, width

    if device.battery <= devices_module.CRITICAL_BATTERY:
        color = "danger"
    elif device.battery <= devices_module.LOW_BATTERY:
        color = "warn"
    else:
        color = "ok"
    ops.append(("text", PADDING, y + 16, f"{device.battery} %", "fg", BIG, "w"))
    note = "заряд" if device.connected else "заряд при последнем подключении"
    ops.append(("text", width - PADDING, y + 22, note, "fg_dim", SMALL, "e"))
    y += 36 + 10
    _bar(ops, PADDING, y, width - 2 * PADDING, device.battery / 100, color)
    return ops, y + BAR_HEIGHT + PADDING, width


# ---------------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------------


def _foreground_window() -> tuple[int, bool]:
    """The window in front and whether it belongs to this process."""
    try:
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = wintypes.HWND
        hwnd = user32.GetForegroundWindow() or 0
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
        return hwnd, pid.value == os.getpid()
    except Exception:
        return 0, False


class Popover:
    """One window for all the popovers: it shows whichever was asked for."""

    def __init__(self, root: tk.Misc, theme: Theme) -> None:
        self.root = root
        self.theme = theme
        self.kind: str | None = None
        self.visible = False
        self.shown_at = 0.0
        self.hidden_at = 0.0
        self.week = False
        self.width = WIDTH
        self.height = 100
        self._data: tuple = ()
        self._ops: Ops | None = None
        self._hits: list[tuple[int, int, int, int, str]] = []
        self._anchor = (0, 0)  # left edge and bottom edge on screen
        self._return_to = 0
        self._fonts: dict[tuple, tkfont.Font] = {}
        self._icons: dict[tuple, tk.PhotoImage] = {}
        self._glazes: dict[tuple, tk.PhotoImage] = {}
        # The last sky painted: what it is of, its picture, and the strip of
        # clouds that slides over it, in its phases (none when the clouds are
        # in the picture).
        self._sky: tuple = ()
        self._clouds: tuple = ()  # the strip's two canvas items, side by side
        self._rain: tuple = ()  # the canvas items of the rain's layers: one for each picture of a layer
        self._fallen: list = []  # which of a layer's pictures is the one shown
        self._splashes: tuple = ()  # the canvas items of the rain's splashes on the plate
        self._splashed: list = []  # what each of them shows and where; None for a hidden one
        self._trickles: tuple = ()  # the canvas items of the drops running down the glass
        self._trickled: list = []  # what each of them shows and where; None for a hidden one
        self._cap: tuple = ()  # the canvas item of the snow lying on the plate
        self._veil: tuple = ()  # the canvas items of a blizzard's veils of blown snow, side by side
        self._sun: int | None = None  # the canvas item of the sun's rays
        self._sunned = -1  # which frame of them is shown
        self._sun_picture: tk.PhotoImage | None = None  # kept, so that Tk does not drop it
        self._flash: int | None = None  # the canvas item of the lightning's light
        self._flashed = 0  # which of its pictures is shown; 0 for none
        self._drift_job: str | None = None
        self._drifted = -1  # how far the strip was last put, in steps
        self._drift_since = time.monotonic()
        self._opaque = False  # the weather's sky, not glass
        #: Whether a sky is worked out whole before the window is shown. It is
        #: most of a second for a rainy one, so the widget does not wait: it
        #: shows the sky bare at once, and the clouds and the rain come over
        #: it a moment later (``_finish_sky``).
        self.eager = True
        self._unfinished: tuple | None = None  # the sky shown bare, and its still picture
        #: A sky made ready beforehand (``prepare``): the one being made - what
        #: it is of, the thread, what the thread has made, and the pictures as
        #: they are made of that; the one kept by; the weather and the minute
        #: it was last looked into for; and the one the open window waits for.
        self._making: tuple | None = None
        self._patience: float | None = None  # Python's own switch interval, to put back
        self._making_since = 0.0
        #: Told what happened to a sky that was being made ready: a word or
        #: two about it, and how many seconds it took. For the widget's log.
        self.on_prepared: Callable[[str, float], None] | None = None
        self._spare: tuple | None = None
        self._asked: tuple | None = None
        self._awaited: tuple | None = None

        bg = theme.get("bg")
        self.window = tk.Toplevel(root)
        self.window.overrideredirect(True)
        self.window.resizable(False, False)
        self.window.configure(bg=bg)
        if not theme.glass:
            # No glass to round and edge the window: a plain 1 px border.
            self.window.configure(highlightthickness=1, highlightbackground=theme.get("border"))
        try:
            self.window.wm_attributes("-toolwindow", True)
            self.window.attributes("-topmost", True)
        except tk.TclError:
            pass
        self.canvas = tk.Canvas(
            self.window, width=self.width, height=self.height, highlightthickness=0, bd=0, bg=bg
        )
        self.canvas.pack()
        self._shapes = ShapeCache(self.canvas)
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<Motion>", self._on_motion)
        self.window.bind("<Escape>", lambda _event: self.hide())
        self.window.withdraw()

    # -- text metrics ------------------------------------------------------

    def _font(self, spec: tuple) -> tkfont.Font:
        if spec not in self._fonts:
            self._fonts[spec] = tkfont.Font(root=self.canvas, font=self.theme.px(*spec))
        return self._fonts[spec]

    def measure(self, text: str, spec: tuple) -> int:
        return self._font(spec).measure(text)

    # -- visibility --------------------------------------------------------

    def show(self, kind: str, left: int, bottom: int, *data) -> None:
        """Open the popover for ``kind`` with its bottom-left corner at the point."""
        self.kind = kind
        self._anchor = (left, bottom)
        self._ops = None  # another kind, or the same after a while: draw anew
        self.update(*data)
        self.window.deiconify()
        self.window.update_idletasks()
        self._surface()
        self.window.attributes("-topmost", True)
        self.window.lift()
        try:
            self.window.focus_force()
        except tk.TclError:
            pass
        self.visible = True
        self.shown_at = time.monotonic()
        self._drift()

    def _surface(self) -> None:
        """Glass, or none of it under a sky that fills the window."""
        if self.theme.glass:
            apply_glass(self.window, *GLASS_TINT, opaque=self._opaque)

    def hide(self, restore: bool = True) -> None:
        """Close the popover. ``restore=False`` when another of the widget's
        windows is about to take the keyboard itself."""
        was_visible = self.visible and restore
        if self.visible:
            self.hidden_at = time.monotonic()
        self.visible = False
        if self._drift_job is not None:
            self.window.after_cancel(self._drift_job)
            self._drift_job = None
        self.window.withdraw()
        # Closed with Esc or by its own icon, the popover would leave the
        # keyboard with the pill on the taskbar. Give it back - but only then:
        # when another window was clicked, that window already has it.
        if was_visible and self._return_to and _foreground_window()[1]:
            try:
                ctypes.windll.user32.SetForegroundWindow(wintypes.HWND(self._return_to))
            except Exception:
                pass

    def note_foreground(self) -> None:
        """Remember the window the user is in, to hand the keyboard back to.

        Called on a timer while the popover is closed: by the time a click on
        the pill is handled, the pill itself is already the window in front.
        """
        hwnd, ours = _foreground_window()
        if hwnd and not ours:
            self._return_to = hwnd

    # -- content -----------------------------------------------------------

    def update(self, *data) -> None:
        """Give the open popover fresh readings; repaints only on a change.

        ``data`` is what the kind's builder takes: the weather; the load; the
        day's and the week's summaries; the device.
        """
        self._data = data
        if self.kind == APPS:
            built = build_apps(*data, self.week, self.measure)
        elif self.kind == SYSTEM:
            built = build_system(*data, self.measure)
        elif self.kind == WEATHER:
            built = build_weather(*data, self.measure)
        elif self.kind in (HEADPHONES, KEYBOARD):
            built = build_device(self.kind, *data, self.measure)
        else:
            return
        ops, height, width = built
        if ops == self._ops:
            return
        self._ops = ops
        opaque = ops[0][0] == "sky"
        if opaque != self._opaque:
            self._opaque = opaque
            if self.visible:  # the weather came, or went, while the window is open
                self._surface()
        self._paint(ops)
        if self.visible and self._drift_job is None:
            self._drift()  # clouds came into a window that had none
        if (width, height) != (self.width, self.height):
            self.width, self.height = width, height
            self.canvas.configure(width=width, height=height)
        self._place()

    def _place(self) -> None:
        """Keep the bottom edge where it was put and the panel on the screen."""
        left, bottom = self._anchor
        try:
            left = max(8, min(left, self.root.winfo_screenwidth() - self.width - 8))
        except tk.TclError:
            pass
        self.window.geometry(f"{self.width}x{self.height}+{left}+{max(0, bottom - self.height)}")

    def _slide(self) -> None:
        """Put the strip of clouds where it has drifted to by now, and the
        rain where it has fallen to."""
        seconds = time.monotonic() - self._drift_since
        for index, (items, (layer, _images)) in enumerate(zip(self._rain, reversed(self._sky[3]))):
            x, y, phase = sky.fall_place(layer, seconds)
            was = self._fallen[index]
            if was != phase:
                # Between two pixels it is another picture of the layer, not
                # another place. Each picture is an item of its own, and all
                # but one are hidden: to give one item another picture costs
                # Tk a millisecond for a picture this large, every frame.
                self._fallen[index] = phase
                self.canvas.itemconfigure(items[was], state="hidden")
                self.canvas.itemconfigure(items[phase], state="normal")
            self.canvas.coords(items[phase], x, y)
        if self._splashes:
            films, splashes, scene = self._sky[6], self._sky[7], self._sky[0][3]
            shown = splashes.advance(seconds)[-len(self._splashes):]
            # Dozens of small changes a frame: one script for Tk, not a call each.
            path, script = str(self.canvas), []
            for index, (x, film, frame) in enumerate(shown):
                item, was = self._splashes[index], self._splashed[index]
                now = (round(x), film, frame)
                if was == now:
                    continue
                self._splashed[index] = now
                key = (film, frame)
                if key not in films:  # each is made when it is first wanted
                    cut = splash.picture(scene, film, frame)
                    films[key] = cut and (
                        cut[0], cut[1],
                        tk.PhotoImage(
                            master=self.canvas, format="png",
                            data=veil_png(cut[2], cut[3], cut[4]),
                        ),
                    )
                if films[key] is None:  # nothing in this frame
                    script.append(f"{path} itemconfigure {item} -state hidden")
                    continue
                left, top, image = films[key]
                script.append(f"{path} coords {item} {now[0] + left} {splashes.top + top}")
                script.append(f"{path} itemconfigure {item} -image {image} -state normal")
            for index in range(len(shown), len(self._splashes)):
                if self._splashed[index] is None:
                    break  # the ones in use are always the first ones
                self._splashed[index] = None
                script.append(f"{path} itemconfigure {self._splashes[index]} -state hidden")
            if script:
                self.canvas.tk.eval("\n".join(script))
        if self._trickles:
            pictures, scene = self._sky[9], self._sky[0][3]
            shown = self._sky[10].advance(seconds)[-len(self._trickles):]
            path, script = str(self.canvas), []
            for index, now in enumerate(shown):
                item, was = self._trickles[index], self._trickled[index]
                if was == now:
                    continue
                self._trickled[index] = now
                if now[2] not in pictures:  # each is made when it is first wanted
                    part = trickle.cut(scene, now[2])
                    pictures[now[2]] = part and (
                        part[0], part[1],
                        tk.PhotoImage(
                            master=self.canvas, format="png", data=veil_png(part[2], part[3], part[4])
                        ),
                    )
                if pictures[now[2]] is None:
                    script.append(f"{path} itemconfigure {item} -state hidden")
                    continue
                left, top, image = pictures[now[2]]
                script.append(f"{path} coords {item} {now[0] + left} {now[1] + top}")
                if was is None or was[2] != now[2]:
                    script.append(f"{path} itemconfigure {item} -image {image} -state normal")
            for index in range(len(shown), len(self._trickles)):
                if self._trickled[index] is None:
                    break
                self._trickled[index] = None
                script.append(f"{path} itemconfigure {self._trickles[index]} -state hidden")
            if script:
                self.canvas.tk.eval("\n".join(script))
        if self._flash is not None:
            step = sky.flash_step(seconds, self._sky[0][3])
            if step != self._flashed:
                self._flashed = step
                if step:
                    self.canvas.itemconfigure(self._flash, image=self._sky[4][step - 1], state="normal")
                else:
                    self.canvas.itemconfigure(self._flash, state="hidden")
        if self._sun is not None:
            frame = int(seconds * sky.RAYS_FPS)
            if frame != self._sunned:
                self._sunned = frame
                width, height, scene = self._sky[14]
                rays = sky.sun_rays(width, height, scene, frame / sky.RAYS_FPS)
                data = png_bytes(width // sky.RAYS_SCALE, height // sky.RAYS_SCALE, rays, alpha=True)
                # Drawn small and enlarged (the rays are soft, and it is cheaper).
                self._sun_picture = tk.PhotoImage(master=self.canvas, format="png", data=data).zoom(
                    sky.RAYS_SCALE, sky.RAYS_SCALE
                )
                self.canvas.itemconfigure(self._sun, image=self._sun_picture)
        if self._veil:
            left = sky.veil_place(seconds, VEIL_PERIOD, sky.DESIGN_WIDTH / self.width)
            for item, x in zip(self._veil, (left, left + VEIL_PERIOD)):
                self.canvas.coords(item, x, 0)
        speed = sky.cloud_speed(self._sky[0][3]) if self._sky else DRIFT
        steps = int(seconds * speed * DRIFT_PHASES)
        if self._sky and self._sky[0][3].gale:
            steps = -steps  # blown, and the other way
        steps %= CLOUD_PERIOD * DRIFT_PHASES
        if self._clouds and steps != self._drifted:
            self._drifted = steps
            offset, phase = divmod(steps, DRIFT_PHASES)
            # Whole pixels by moving the strip, the rest by the strip drawn that
            # much further on.
            for item, x in zip(self._clouds, (offset - CLOUD_PERIOD, offset)):
                self.canvas.coords(item, x, 0)
                self.canvas.itemconfigure(item, image=self._sky[2][phase])

    def _drift(self) -> None:
        """Move the clouds and the rain, and again a moment later, while the
        window is open."""
        self._drift_job = None
        if self.visible and (self._clouds or self._rain or self._trickles or self._sun is not None or self._flash is not None):
            self._slide()
            self._drift_job = self.window.after(DRIFT_MS, self._drift)

    def _paint(self, ops: Ops) -> None:
        canvas = self.canvas
        canvas.delete("all")
        self._clouds = ()
        self._rain = ()
        self._splashes = ()
        self._trickles = ()
        self._cap = ()
        self._veil = ()
        self._sun = None
        self._flash = None
        theme = self.theme
        bg = theme.get("bg")
        self._hits = []
        for op in ops:
            if op[0] == "text":
                _, x, y, text, color, spec, anchor = op
                fill = color if color.startswith("#") else theme.get(color)
                canvas.create_text(x, y, text=text, fill=fill, font=self._font(spec), anchor=anchor)
            elif op[0] == "rect":
                _, x, y, width, height, radius, color = op[:7]
                under = theme.get(op[7]) if len(op) > 7 else bg
                if radius:
                    self._shapes.draw(canvas, x, y, width, height, radius, theme.get(color), None, under)
                else:
                    canvas.create_rectangle(x, y, x + width, y + height, fill=theme.get(color), width=0)
            elif op[0] == "icon":
                _, x, y, name, color, size, *under = op
                under_color = theme.get(under[0]) if under else bg
                key = (name, theme.get(color), size, under_color)
                if key not in self._icons:
                    self._icons[key] = stroke_image(
                        canvas, ASSETS / f"{name}.svg", size, key[1], under_color
                    )
                canvas.create_image(x, y, anchor="nw", image=self._icons[key])
            elif op[0] == "sky":
                if self._sky[:1] != (op,) and self._spare is not None and self._spare[0] == op:
                    self._sky, self._spare = self._spare, None  # it was made ready beforehand
                if self._sky[:1] != (op,):
                    still, image = self._still_sky(op)
                    scene = op[3]
                    moving = sky.drifts(scene) or sky.falls(scene) or sky.snows(scene) or scene.lightning
                    if self._making is not None and self._making[0] == op:
                        # It is being made ready this very moment: the bare sky
                        # now, and the rest when that is done (``_collect``).
                        self._sky = (op, image, [], [], [], None, {}, None, None, {}, None, None, [], None, None)
                        self._awaited = op
                    elif self.eager or not moving:
                        self._sky = self._whole_sky(op, still, image)
                    else:
                        # The bare sky at once, and what moves over it in a moment.
                        self._sky = (op, image, [], [], [], None, {}, None, None, {}, None, None, [], None, None)
                        self._unfinished = (op, still)
                        self.window.after(1, self._finish_sky)
                canvas.create_image(0, 0, anchor="nw", image=self._sky[1])
                # The sun's rays, over the sky and under everything else.
                self._sun = canvas.create_image(0, 0, anchor="nw") if self._sky[14] else None
                self._sunned = -1
                if self._sky[2]:
                    self._clouds = tuple(
                        canvas.create_image(0, 0, anchor="nw", image=self._sky[2][0]) for _ in range(2)
                    )
                    self._drifted = -1
                # The rain falls in front of the clouds, the far layer first.
                self._rain = tuple(
                    tuple(
                        canvas.create_image(0, 0, anchor="nw", image=image, state="normal" if not at else "hidden")
                        for at, image in enumerate(images)
                    )
                    for _layer, images in reversed(self._sky[3])
                )
                self._fallen = [0] * len(self._rain)
                # A blizzard's veils of blown snow, over its flakes: two of
                # the strip side by side, going round.
                if self._sky[13]:
                    self._veil = tuple(
                        canvas.create_image(0, 0, anchor="nw", image=self._sky[13]) for _ in range(2)
                    )
                # The drops on the glass are in front of all the weather.
                if self._sky[8]:
                    canvas.create_image(0, 0, anchor="nw", image=self._sky[8])
                    # Some of them run down it.
                    self._trickles = tuple(
                        canvas.create_image(0, 0, anchor="nw", state="hidden")
                        for _ in range(TRICKLES)
                    )
                    self._trickled = [None] * TRICKLES
                # And all of that is behind the plate: its blur covers it there.
                if self._sky[5]:
                    canvas.create_image(op[4][0], op[4][1], anchor="nw", image=self._sky[5])
                if self._sky[7]:
                    # The water lying along its top edge, and the splashes in it.
                    canvas.create_image(
                        op[4][0] + op[4][2] / 2, op[4][1] + 1, anchor="s", image=self._sky[11]
                    )
                    self._splashes = tuple(
                        canvas.create_image(0, 0, anchor="nw", state="hidden")
                        for _ in range(SPLASHES)
                    )
                    self._splashed = [None] * SPLASHES
                # The snow lying on the plate.
                self._cap = tuple(
                    canvas.create_image(op[4][0] + CAP_INSET, op[4][1], anchor="sw", image=image)
                    for image in self._sky[12]
                )
                # A flash of lightning lights all of it.
                if self._sky[4]:
                    self._flash = canvas.create_image(
                        0, 0, anchor="nw", image=self._sky[4][-1], state="hidden"
                    )
                    self._flashed = 0
                self._slide()
            elif op[0] == "glaze":
                _, x, y, *look = op
                if look[0] <= 0:
                    continue
                key = tuple(look)
                if key not in self._glazes:
                    self._glazes[key] = glaze_image(canvas, *look)
                canvas.create_image(x, y, anchor="nw", image=self._glazes[key])
            elif op[0] == "glyph":
                _, x, y, name, size = op
                key = (name, size)
                if key not in self._icons:
                    self._icons[key] = alpha_image(canvas, ASSETS / f"{name}.svg", size, ON_SKY)
                canvas.create_image(x, y, anchor="nw", image=self._icons[key])
            elif op[0] == "hit":
                self._hits.append(op[1:])

    def _still_sky(self, op: tuple) -> tuple[bytes, tk.PhotoImage]:
        """The sky that does not move, as RGB rows and as a picture."""
        _, width, height, _scene, _ledge = op
        still = still_sky(op)
        return still, tk.PhotoImage(master=self.canvas, data=png_bytes(width, height, still), format="png")

    def _pictures(self, op: tuple, image: tk.PhotoImage, parts: dict):
        """Make Tk's pictures of a sky that has been worked out (``moving_sky``),
        one at a step, and at the last step give what the sky is painted from."""
        def picture(data: bytes) -> tk.PhotoImage:
            return tk.PhotoImage(master=self.canvas, format="png", data=data)

        strips = []
        for data in parts["strips"]:
            strips.append(picture(data))
            yield None
        rain = []
        for layer, phases in parts["rain"]:
            images = []
            for data in phases:
                images.append(picture(data))
                yield None
            rain.append((layer, images))
        lightning = []
        for data in parts["lightning"]:
            lightning.append(picture(data))
            yield None
        shelter = parts["shelter"] and picture(parts["shelter"])
        glass = parts["glass"] and picture(parts["glass"])
        wet = parts["wet"] and picture(parts["wet"])
        caps = []
        for data in parts["caps"]:
            caps.append(picture(data))
        veil = parts["veil"] and picture(parts["veil"])
        yield None
        # The splashes' and the running drops' pictures are made as they are wanted.
        yield (
            op, image, strips, rain, lightning, shelter, {}, parts["splashes"], glass, {}, parts["trickles"], wet,
            caps, veil, parts["sun"],
        )

    def _whole_sky(self, op: tuple, still: bytes, image: tk.PhotoImage) -> tuple:
        """Everything the sky is painted from: the still picture and all that
        moves over it. It is most of a second's work for a rainy sky."""
        for whole in self._pictures(op, image, moving_sky(op, still)):
            pass
        return whole

    # -- a sky made ready beforehand -------------------------------------

    def prepare(self, weather, now: datetime | None = None) -> None:
        """Have the sky for this weather ready before the window is asked for.

        Called over and over with the weather there is: it does something
        only when that weather, or the part of the day, would give another
        sky than the one in hand. Then the sky is worked out on a thread of
        its own, so that the widget goes on meanwhile, and its pictures are
        made here a step at a time. When the window is opened the sky is
        simply there.
        """
        if weather is None or self.visible or self._making is not None:
            return
        minute = int(time.time() // 60)
        if self._asked == (weather, minute):
            return  # nothing has changed since it was last looked into
        self._asked = (weather, minute)
        op = build_weather(weather, self.measure, now)[0][0]
        if op[0] != "sky" or self._have(op):
            return
        made: dict = {}

        def work() -> None:
            try:
                still = still_sky(op)
                made["sky"] = png_bytes(op[1], op[2], still)
                made["parts"] = moving_sky(op, still)
            except Exception as exc:  # the window will work it out itself when it is opened
                made["failed"] = exc

        thread = threading.Thread(target=work, name="weather-sky", daemon=True)
        self._making = (op, thread, made, None)
        # While that thread works, Python hands the processor from one thread
        # to the other only this often - and the widget's thread asks for it
        # back every time it returns from Tk, which is dozens of times a
        # frame. At the usual 5 ms that is the widget stuttering for a second.
        self._patience = sys.getswitchinterval()
        sys.setswitchinterval(PREPARE_SWITCH_S)
        self._making_since = time.monotonic()
        thread.start()
        self.window.after(PREPARE_POLL_MS, self._collect)

    def _tell(self, what: str) -> None:
        if self.on_prepared:
            self.on_prepared(what, time.monotonic() - self._making_since)

    def _have(self, op: tuple) -> bool:
        """Whether this sky is in hand, whole."""
        if self._spare is not None and self._spare[0] == op:
            return True
        return self._sky[:1] == (op,) and self._unfinished is None and self._awaited != op

    def _collect(self) -> None:
        """Take what the thread has worked out and make its pictures, a step
        at a time; then keep the sky by, or show it if it is being waited for."""
        if self._making is None:
            return
        op, thread, made, steps = self._making
        if thread.is_alive():
            self.window.after(PREPARE_POLL_MS, self._collect)
            return
        if self._patience is not None:
            sys.setswitchinterval(self._patience)
            self._patience = None
        if "parts" not in made:
            self._making, self._awaited = None, None
            self._tell(f"not made ready: {made.get('failed')!r}")
            return
        if steps is None:
            image = tk.PhotoImage(master=self.canvas, data=made["sky"], format="png")
            steps = self._pictures(op, image, made["parts"])
            self._making = (op, thread, made, steps)
        whole = next(steps)
        if whole is None and self._awaited != op:
            self.window.after(1, self._collect)  # the next picture, when Tk has seen to the rest
            return
        while whole is None:  # the window is waiting: no more pauses
            whole = next(steps)
        self._making = None
        self._tell("made ready" + (" while the window waited" if self._awaited == op else ""))
        if self._awaited == op:
            self._awaited = None
            if self._sky[:1] == (op,):
                self._sky = whole
                if self._ops and self._ops[0] == op:
                    self._paint(self._ops)
                    if self.visible and self._drift_job is None:
                        self._drift()
                return
        self._spare = whole

    def _finish_sky(self) -> None:
        """Work out what moves over the sky that was shown bare, and show it."""
        unfinished, self._unfinished = self._unfinished, None
        if not unfinished or self._sky[:1] != (unfinished[0],):
            return  # another sky has come since
        self._sky = self._whole_sky(unfinished[0], unfinished[1], self._sky[1])
        if self._ops and self._ops[0] == unfinished[0]:
            self._paint(self._ops)
            if self.visible and self._drift_job is None:
                self._drift()

    def _hit(self, x: int, y: int) -> str | None:
        for left, top, width, height, action in self._hits:
            if left <= x < left + width and top <= y < top + height:
                return action
        return None

    def _on_motion(self, event: tk.Event) -> None:
        self.canvas.configure(cursor="hand2" if self._hit(event.x, event.y) else "")

    def _on_press(self, event: tk.Event) -> None:
        action = self._hit(event.x, event.y)
        if action in ("day", "week"):
            self.week = action == "week"
            self.update(*self._data)
