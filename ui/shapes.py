"""Anti-aliased rounded rectangles for glass windows.

A Tk canvas draws its shapes without anti-aliasing, and its "smooth" polygons
are splines, not arcs: a small rounded rectangle comes out lopsided and jagged.
This module computes the shape exactly instead - true circular corners, with
each edge pixel weighted by how much of it the shape covers - and returns it as
an image to put on the canvas.

It relies on how glass composes (``ui/theme.py``): a pixel's colour is *added*
to what is behind the window, so a partly covered pixel is simply a
proportionally darker colour. No alpha channel is needed, and black is "nothing".

The weather popover is the exception: it is an opaque window with a painted sky,
and what lies on the sky is translucent. Tk reads an alpha channel from a PNG
only, so ``png_bytes`` writes one, and ``glaze_image`` is a rounded rectangle
with the design's alpha that the canvas blends over what is under it.
"""

from __future__ import annotations

import math
import struct
import tkinter as tk
import zlib


def _rgb(color: str) -> tuple[int, int, int]:
    value = color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _distance(x: float, y: float, width: float, height: float, radius: float) -> float:
    """Signed distance from a point to a rounded rectangle; negative inside."""
    qx = abs(x - width / 2) - (width / 2 - radius)
    qy = abs(y - height / 2) - (height / 2 - radius)
    outside = math.hypot(max(qx, 0.0), max(qy, 0.0))
    return outside + min(max(qx, qy), 0.0) - radius


def _coverage(distance: float) -> float:
    """How much of a pixel lies inside an edge ``distance`` away from its centre."""
    return min(1.0, max(0.0, 0.5 - distance))


def rounded_image(
    master: tk.Misc,
    width: int,
    height: int,
    radius: float,
    fill: str,
    edge: str | None = None,
    background: str = "#000000",
) -> tk.PhotoImage:
    """A ``width`` x ``height`` rounded rectangle with a 1 px ``edge`` inside it.

    ``background`` is what the shape lies on: the pixels around the corners and
    the uncovered part of each edge pixel. On glass that is black, "nothing";
    an opaque theme passes its panel colour.

    The caller must keep a reference to the result: Tk drops an image that
    nothing in Python holds on to (``ShapeCache`` does that).
    """
    fill_rgb = _rgb(fill)
    edge_rgb = _rgb(edge) if edge else fill_rgb
    back_rgb = _rgb(background)
    rows = []
    for row in range(height):
        cells = []
        for column in range(width):
            distance = _distance(column + 0.5, row + 0.5, width, height, radius)
            shape = _coverage(distance)
            inner = _coverage(distance + 1.0)  # the shape shrunk by the edge
            ring = shape - inner
            cells.append(
                "#%02x%02x%02x"
                % tuple(
                    round(fill_rgb[k] * inner + edge_rgb[k] * ring + back_rgb[k] * (1.0 - shape))
                    for k in range(3)
                )
            )
        rows.append("{" + " ".join(cells) + "}")
    image = tk.PhotoImage(master=master, width=width, height=height)
    image.put(" ".join(rows))
    return image


def png_bytes(width: int, height: int, pixels: bytes, alpha: bool = False) -> bytes:
    """A PNG file from rows of RGB (or, with ``alpha``, RGBA) bytes."""
    stride = width * (4 if alpha else 3)
    rows = b"".join(b"\x00" + pixels[start:start + stride] for start in range(0, len(pixels), stride))

    def chunk(tag: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body))

    header = struct.pack(">IIBBBBB", width, height, 8, 6 if alpha else 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows, 1))
        + chunk(b"IEND", b"")
    )


#: Every byte as it is, but 0 as 1.
_NEVER_CLEAR = bytes([1]) + bytes(range(1, 256))


def veil_png(width: int, height: int, pixels: bytes, block: int = 0) -> bytes:
    """A PNG file from RGBA rows that are to be laid over other things and
    are clear in most places - streaks of rain, drops, a splash.

    Tk keeps, for every picture, the outline of the part of it that is not
    wholly clear, and works it out again a row at a time as the picture comes
    in. For a picture that is clear nearly everywhere and has thousands of
    separate marks in it that outline is enormous: taking such a picture in
    costs thirty times what it should. So no pixel of it is left wholly clear
    - the clearest are 1 part in 255 opaque, which nobody can see - and the
    outline is the rectangle.

    But with the outline Tk also skips what is clear when it draws, and a
    picture veiled all over is blended into what is under it all over, every
    frame. So for a large one there is ``block``: the picture is taken in
    squares of that many pixels, and only a square with a mark in it is
    veiled. The outline is then a few hundred squares, quick to make, and the
    empty most of the picture is still skipped. Which is best for a picture
    is a matter of measuring (``tools/sky_bench.py``).
    """
    alpha = pixels[3::4]
    if not block:
        veiled = alpha.translate(_NEVER_CLEAR)
    else:
        veiled = bytearray(alpha)
        for top in range(0, height, block):
            rows = range(top, min(height, top + block))
            band = [alpha[row * width:(row + 1) * width] for row in rows]
            for left in range(0, width, block):
                right = min(width, left + block)
                if any(any(line[left:right]) for line in band):
                    for row, line in zip(rows, band):
                        veiled[row * width + left:row * width + right] = line[left:right].translate(_NEVER_CLEAR)
    out = bytearray(pixels)
    out[3::4] = veiled
    return png_bytes(width, height, bytes(out), alpha=True)


def cropped(width: int, height: int, pixels: bytes) -> tuple[int, int, int, int, bytes] | None:
    """RGBA rows cut down to the part with anything in it: how far its left
    top corner is from the picture's, its width and height, and its rows.
    ``None`` for a picture that is clear all over."""
    alpha = pixels[3::4]
    rows = [alpha[row * width:(row + 1) * width] for row in range(height)]
    used = [row for row in range(height) if any(rows[row])]
    if not used:
        return None
    top, bottom = used[0], used[-1] + 1
    left = min(width - len(rows[row].lstrip(b"\0")) for row in used)
    right = max(len(rows[row].rstrip(b"\0")) for row in used)
    return (
        left, top, right - left, bottom - top,
        b"".join(pixels[(row * width + left) * 4:(row * width + right) * 4] for row in range(top, bottom)),
    )


def tinted(tint: bytes, alpha: bytes) -> bytes:
    """RGBA rows of one colour - ``tint``, three bytes - as opaque at each pixel
    as ``alpha`` says. In two strokes, not a pixel at a time: pictures of this
    kind are made by the hundred."""
    pixels = bytearray(tint + b"\0") * len(alpha)
    pixels[3::4] = alpha
    return bytes(pixels)


def rounded_pixels(width: int, height: int, radius: float, pixels: bytes) -> bytes:
    """Rows of RGB bytes as rows of RGBA, cut to a rounded rectangle.

    The cut is hard - a pixel is in or out - because Tk draws a picture with
    no half-transparent pixels far faster than one with any. It is for what
    lies under a shape with a smooth edge of its own.
    """
    corner = math.ceil(radius)
    out = bytearray()
    for row in range(height):
        line = pixels[row * width * 3:(row + 1) * width * 3]
        whole = corner <= row < height - corner
        for column in range(width):
            out += line[column * 3:column * 3 + 3]
            if whole or corner <= column < width - corner:
                out.append(255)
            else:
                cover = _coverage(_distance(column + 0.5, row + 0.5, width, height, radius))
                out.append(255 if cover >= 0.5 else 0)
    return bytes(out)


def glaze_image(master: tk.Misc, width: int, height: int, radius: float, color: str) -> tk.PhotoImage:
    """A rounded rectangle in ``color`` - ``#RRGGBBAA`` - with a real alpha.

    For an opaque window only: on glass a colour is already added to what is
    behind it. The caller must keep a reference to the result.
    """
    red, green, blue = _rgb(color)
    alpha = int(color.lstrip("#")[6:8] or "FF", 16)
    solid = bytes((red, green, blue, alpha))
    corner = math.ceil(radius)
    pixels = bytearray()
    for row in range(height):
        if corner <= row < height - corner:
            pixels += solid * width  # only the corners are less than whole
            continue
        for column in range(width):
            if corner <= column < width - corner:
                pixels += solid
                continue
            cover = _coverage(_distance(column + 0.5, row + 0.5, width, height, radius))
            pixels += bytes((red, green, blue, round(alpha * cover)))
    return tk.PhotoImage(
        master=master, data=png_bytes(width, height, bytes(pixels), alpha=True), format="png"
    )


class ShapeCache:
    """Rounded rectangles for one canvas, built once per distinct look.

    A month grid asks for the same few shapes on every repaint (a hovered cell,
    the selected one, today's outline), so they are kept; the cache is also what
    holds the references Tk needs.
    """

    def __init__(self, master: tk.Misc) -> None:
        self._master = master
        self._images: dict[tuple, tk.PhotoImage] = {}

    def draw(
        self,
        canvas: tk.Canvas,
        x: int,
        y: int,
        width: int,
        height: int,
        radius: float,
        fill: str,
        edge: str | None = None,
        background: str = "#000000",
    ) -> int:
        """Put the shape on ``canvas`` with its top-left corner at ``x, y``."""
        image = self.image(width, height, radius, fill, edge, background)
        return canvas.create_image(x, y, anchor="nw", image=image)

    def image(
        self,
        width: int,
        height: int,
        radius: float,
        fill: str,
        edge: str | None = None,
        background: str = "#000000",
    ) -> tk.PhotoImage:
        """The shape itself, for a widget that shows an image rather than a canvas."""
        key = (width, height, radius, fill, edge, background)
        if key not in self._images:
            self._images[key] = rounded_image(
                self._master, width, height, radius, fill, edge, background
            )
        return self._images[key]
