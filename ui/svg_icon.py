"""Stroked SVG icons for glass windows, drawn without an SVG library.

Tk cannot read SVG and the widget ships no imaging library, so this reads the
small subset an outline icon uses - ``<path>`` elements made of ``M L H V C A
Z`` commands (absolute or relative), plus ``<circle>``, ``<rect>`` and
``<line>``, stroked with round caps and joins - and rasterises it the way
``ui/shapes.py`` does its rectangles: each pixel is weighted by how much of it
the stroke covers, and the result is an image to put on a canvas.

The stroke colour in the file is ignored; the caller names the colour, so one
file serves every theme.
"""

from __future__ import annotations

import math
import re
import tkinter as tk
import xml.etree.ElementTree as ET
from pathlib import Path

from .shapes import _rgb, png_bytes

ASSETS = Path(__file__).resolve().parent.parent / "assets"

#: Straight pieces a curve is cut into; plenty for an icon a few pixels across.
CURVE_STEPS = 12
#: Samples per pixel side when measuring coverage.
SAMPLES = 4

_TOKEN = re.compile(r"[MmLlHhVvCcAaZz]|-?(?:\d+\.?\d*|\.\d+)(?:e-?\d+)?")
_ARITY = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "A": 7, "Z": 0}
_SVG = "{http://www.w3.org/2000/svg}"

Segment = tuple[float, float, float, float]
Stroke = tuple[float, list[Segment]]


def _arc_points(
    x0: float, y0: float, rx: float, ry: float, turn: float,
    large: bool, sweep: bool, x1: float, y1: float,
) -> list[tuple[float, float]]:
    """The points of an elliptical arc after its start, by the SVG rules."""
    if rx == 0 or ry == 0 or (x0 == x1 and y0 == y1):
        return [(x1, y1)]
    rx, ry = abs(rx), abs(ry)
    phi = math.radians(turn)
    cos, sin = math.cos(phi), math.sin(phi)
    # The arc in the ellipse's own frame, centred between its two ends.
    dx, dy = (x0 - x1) / 2, (y0 - y1) / 2
    px, py = cos * dx + sin * dy, -sin * dx + cos * dy
    # Radii too small to reach from one end to the other are scaled up.
    reach = (px / rx) ** 2 + (py / ry) ** 2
    if reach > 1:
        rx, ry = rx * math.sqrt(reach), ry * math.sqrt(reach)
    top = (rx * ry) ** 2 - (rx * py) ** 2 - (ry * px) ** 2
    bottom = (rx * py) ** 2 + (ry * px) ** 2
    factor = math.sqrt(max(0.0, top / bottom)) * (-1 if large == sweep else 1)
    centre_x, centre_y = factor * rx * py / ry, -factor * ry * px / rx
    cx = cos * centre_x - sin * centre_y + (x0 + x1) / 2
    cy = sin * centre_x + cos * centre_y + (y0 + y1) / 2
    first = math.atan2((py - centre_y) / ry, (px - centre_x) / rx)
    span = math.atan2((-py - centre_y) / ry, (-px - centre_x) / rx) - first
    if sweep and span < 0:
        span += 2 * math.pi
    elif not sweep and span > 0:
        span -= 2 * math.pi
    steps = max(2, math.ceil(abs(span) / (math.pi / 2) * CURVE_STEPS))
    points = []
    for step in range(1, steps + 1):
        angle = first + span * step / steps
        ex, ey = rx * math.cos(angle), ry * math.sin(angle)
        points.append((cos * ex - sin * ey + cx, sin * ex + cos * ey + cy))
    points[-1] = (x1, y1)
    return points


def _segments(data: str) -> list[Segment]:
    """The straight segments of a path's ``d`` attribute, curves flattened."""
    tokens = _TOKEN.findall(data)
    segments: list[Segment] = []
    x = y = start_x = start_y = 0.0
    index = 0
    command = ""
    relative = False
    while index < len(tokens):
        if tokens[index].upper() in _ARITY:
            relative = tokens[index].islower()
            command = tokens[index].upper()
            index += 1
        count = _ARITY[command]
        values = [float(token) for token in tokens[index:index + count]]
        index += count
        # A relative command counts from the current point. An arc's radii,
        # turn and flags - its first five numbers - are not coordinates.
        if relative and command == "H":
            values[0] += x
        elif relative and command == "V":
            values[0] += y
        elif relative:
            first = 5 if command == "A" else 0
            for k in range(first, count):
                values[k] += y if (k - first) % 2 else x
        if command == "A":
            rx, ry, turn, large, sweep, end_x, end_y = values
            for next_x, next_y in _arc_points(
                x, y, rx, ry, turn, bool(large), bool(sweep), end_x, end_y
            ):
                segments.append((x, y, next_x, next_y))
                x, y = next_x, next_y
            continue
        if command == "M":
            x, y = start_x, start_y = values
            command = "L"  # further pairs after a moveto are lines
            continue
        if command == "C":
            x1, y1, x2, y2, end_x, end_y = values
            last_x, last_y = x, y
            for step in range(1, CURVE_STEPS + 1):
                t = step / CURVE_STEPS
                u = 1.0 - t
                next_x = u**3 * x + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t**3 * end_x
                next_y = u**3 * y + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t**3 * end_y
                segments.append((last_x, last_y, next_x, next_y))
                last_x, last_y = next_x, next_y
            x, y = end_x, end_y
            continue
        if command == "L":
            end_x, end_y = values
        elif command == "H":
            end_x, end_y = values[0], y
        elif command == "V":
            end_x, end_y = x, values[0]
        else:  # Z
            end_x, end_y = start_x, start_y
        segments.append((x, y, end_x, end_y))
        x, y = end_x, end_y
    return segments


def _element_path(element: ET.Element) -> str | None:
    """A shape element as path data; None for anything that is not drawn."""
    def number(name: str) -> float:
        return float(element.get(name, "0"))

    tag = element.tag.removeprefix(_SVG)
    if tag == "path":
        return element.get("d", "")
    if tag == "line":
        return f"M{number('x1')} {number('y1')}L{number('x2')} {number('y2')}"
    if tag == "circle":
        cx, cy, r = number("cx"), number("cy"), number("r")
        return f"M{cx - r} {cy}A{r} {r} 0 1 1 {cx + r} {cy}A{r} {r} 0 1 1 {cx - r} {cy}Z"
    if tag == "rect":
        x, y, w, h = number("x"), number("y"), number("width"), number("height")
        r = min(float(element.get("rx", element.get("ry", "0"))), w / 2, h / 2)
        return (
            f"M{x + r} {y}H{x + w - r}A{r} {r} 0 0 1 {x + w} {y + r}"
            f"V{y + h - r}A{r} {r} 0 0 1 {x + w - r} {y + h}"
            f"H{x + r}A{r} {r} 0 0 1 {x} {y + h - r}"
            f"V{y + r}A{r} {r} 0 0 1 {x + r} {y}Z"
        )
    return None


def load_strokes(path: Path) -> tuple[float, list[Stroke]]:
    """The icon's view box side and its shapes as ``(stroke width, segments)``.

    A shape without its own ``stroke-width`` takes the ``<svg>`` element's.
    """
    root = ET.parse(path).getroot()
    box = [float(value) for value in root.get("viewBox", "0 0 24 24").split()]
    default_width = root.get("stroke-width", "1")
    strokes = []
    for element in root.iter():
        data = _element_path(element)
        if data is not None:
            strokes.append((float(element.get("stroke-width", default_width)), _segments(data)))
    return max(box[2], box[3]), strokes


def _segment_distance(px: float, py: float, segment: Segment) -> float:
    ax, ay, bx, by = segment
    dx, dy = bx - ax, by - ay
    length = dx * dx + dy * dy
    t = 0.0 if length == 0 else min(1.0, max(0.0, ((px - ax) * dx + (py - ay) * dy) / length))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def coverage(
    path: Path,
    size: int,
    shift: tuple[float, float] = (0.0, 0.0),
    angle: float = 0.0,
) -> list[list[float]]:
    """How much of each ``size`` x ``size`` pixel the icon covers, 0 to 1.

    ``angle`` turns the icon clockwise, in degrees, about its centre. It is the
    colour-free part of ``stroke_image``, so a spinning icon can reuse it.
    """
    box, strokes = load_strokes(path)
    scale = box / size
    centre = box / 2
    radians = math.radians(angle)
    cos, sin = math.cos(radians), math.sin(radians)
    # Each segment with its half stroke width and bounding box, so a sample that
    # is nowhere near a segment skips the distance maths.
    segments = []
    for width, group in strokes:
        for ax, ay, bx, by in group:
            half = width / 2
            segments.append((
                half, (ax, ay, bx, by),
                min(ax, bx) - half, min(ay, by) - half, max(ax, bx) + half, max(ay, by) + half,
            ))
    offsets = [(k + 0.5) / SAMPLES for k in range(SAMPLES)]
    rows = []
    for row in range(size):
        cells = []
        for column in range(size):
            hits = 0
            for oy in offsets:
                for ox in offsets:
                    dx = (column + ox - shift[0]) * scale - centre
                    dy = (row + oy - shift[1]) * scale - centre
                    # The sample is turned back by ``angle`` into the icon's own frame.
                    px = dx * cos + dy * sin + centre
                    py = -dx * sin + dy * cos + centre
                    if any(
                        left <= px <= right and top <= py <= bottom
                        and _segment_distance(px, py, segment) <= half
                        for half, segment, left, top, right, bottom in segments
                    ):
                        hits += 1
            cells.append(hits / (SAMPLES * SAMPLES))
        rows.append(cells)
    return rows


def stroke_image(
    master: tk.Misc,
    path: Path,
    size: int,
    color: str,
    background: str = "#000000",
    shift: tuple[float, float] = (0.0, 0.0),
    angle: float = 0.0,
) -> tk.PhotoImage:
    """The icon at ``size`` x ``size`` px in ``color`` on ``background``.

    As with ``rounded_image``, ``background`` is what shows through the
    uncovered part of a pixel, and the caller must keep the result alive.

    ``shift`` moves the drawing by a fraction of a pixel, to land thin straight
    strokes on whole pixels instead of smearing each across two.
    """
    color_rgb = _rgb(color)
    back_rgb = _rgb(background)
    rows = []
    for cells in coverage(path, size, shift, angle):
        pixels = []
        for cover in cells:
            pixels.append(
                "#%02x%02x%02x"
                % tuple(round(color_rgb[k] * cover + back_rgb[k] * (1.0 - cover)) for k in range(3))
            )
        rows.append("{" + " ".join(pixels) + "}")
    image = tk.PhotoImage(master=master, width=size, height=size)
    image.put(" ".join(rows))
    return image


def alpha_image(master: tk.Misc, path: Path, size: int, color: str) -> tk.PhotoImage:
    """The icon in ``color`` with its coverage as alpha, for an opaque window
    where what is under the icon is not one colour (``shapes.glaze_image``)."""
    red, green, blue = _rgb(color)
    pixels = bytearray()
    for cells in coverage(path, size):
        for cover in cells:
            pixels += bytes((red, green, blue, round(255 * cover)))
    return tk.PhotoImage(
        master=master, data=png_bytes(size, size, bytes(pixels), alpha=True), format="png"
    )
