"""Rain landing on the hours' plate of the weather popover.

The rain is two pictures sliding down their slant (``sky.rain_layers``), so a
streak is not a thing that can meet anything. But where each streak's head is
in its picture is known, and so is how far the picture has slid: that gives
the moment and the place every streak comes down on the plate's top edge.

What it does there is a splash, as a drop makes on a wet ledge seen from the
side. It flattens, and a film of water runs out along the ledge from under it.
The edge of that film is thrown up as a crown - a thin sheet rising and
leaning outwards on either side - which lasts a few hundredths of a second
and breaks at its rim into droplets; they fly on, slow, fall back and are
gone. With them goes a mist of finer ones, quicker and shorter-lived. And out
of the middle of a larger splash a small jet comes up afterwards, and lets go
of one drop at its top. The rain comes down slanting, so all of it is thrown
further the way the rain was going. A third of a second in all - and then for
as long again there is water lying where it landed, with a ripple running out
through it, before that is gone too.

Besides the splashes the ledge is wet all along (``ledge_water``): a thin
line of water on it that is always there while it rains.

A splash is not reckoned as it goes: it is a
short film, drawn once (``films``) with soft edges and the blur of its own
speed, and there are a few different ones. ``Splashes.advance`` only says
which frame of which film is where, and ``ui/popover.py`` shows them.

A film and not a dot for every droplet, because Tk blends each translucent
picture into what is under it one by one: a splash is one picture however
many droplets are in it.
"""

from __future__ import annotations

import math
import random
from bisect import bisect_right

from functools import lru_cache

from . import sky
from .shapes import tinted

#: A film's frames are this long, and there are this many of them.
FRAME = 0.025
FRAMES = 22
#: A frame's picture; the rain lands at the middle of its bottom edge.
SIZE = (132, 46)
#: A splash is drawn this many times the size the rain's own scale would make
#: it: true to scale it is a few pixels of something happening, and this
#: large it is seen for what it is.
ZOOM = 1.5
#: Rain is drops of every size, and so are its splashes: the films go from one
#: this many times the middling size to one this many times - a tick on the
#: ledge to a proper crown with a jet. And the slight ones are the commoner:
#: the larger the splash, the fewer of them (``RARER``).
SIZES = (0.42, 1.55)
RARER = 1.7
#: Where a drop has landed there is water on the ledge for a while after the
#: splash is over: a little of it, lying flat, which spreads a touch, has a
#: ripple run out through it, and is gone by this long after the landing.
POOL = 0.55
#: The different splashes there are films of, from the slight to the large.
FILMS = 10
#: Droplets fall back at this many pixels a second, each second.
GRAVITY = 900.0
#: Of the streaks that land, this share is seen to splash: every one of them
#: is too busy an edge, and each splash is a picture more for Tk to blend.
SHARE = 0.55
#: A gap in time longer than this is not rain that fell meanwhile: the window
#: was closed, or the clock was moved.
PAUSE = 0.25
#: The rain goes this way along the ledge as it comes down (to the left).
ONWARD = -1.0


@lru_cache(maxsize=None)
def _film(number: int) -> tuple[bytes, ...]:
    """A splash, frame by frame, as how opaque each pixel is (row after row,
    a byte a pixel)."""
    chance = random.Random(number * 7919 + 13)
    uniform = chance.uniform
    width, height = SIZE
    middle, ground = width / 2, height - 0.5
    size = SIZES[0] + (SIZES[1] - SIZES[0]) * (number / (FILMS - 1)) ** 1.3  # how large a splash it is
    scale = ZOOM * size ** 0.75  # a small one is small all over, not only slow

    # The crown: on either side a sheet thrown up from where the film's edge
    # is, leaning outwards. Each: which side, how fast across and up, how
    # long it holds together.
    crown = []
    #: Each: when it comes to be, where (across, up) and how fast (across,
    #: up) it is then, how large, and how long it lasts from then.
    droplets = []
    for side in (-1.0, 1.0):
        onward = 1.18 if side == ONWARD else 0.86
        lean = math.radians(uniform(34.0, 52.0))
        speed = uniform(150.0, 195.0) * size ** 0.5 * onward
        across, up, holds = side * speed * math.sin(lean), speed * math.cos(lean), uniform(0.07, 0.095)
        crown.append((side, across, up, holds))
        # Its rim breaks into droplets, which go on as the rim was going.
        for _ in range(chance.randint(2, 3 if size < 1.0 else 4)):
            when = uniform(0.03, holds * 0.85)
            quick, turn = uniform(0.55, 1.0), math.radians(uniform(-16.0, 16.0))
            vx = (across * math.cos(turn) - (up - GRAVITY * when) * math.sin(turn)) * quick
            vy = (across * math.sin(turn) + (up - GRAVITY * when) * math.cos(turn)) * quick
            vy = min(vy, 125.0)  # they hop; nothing leaves the picture
            vx = max(-115.0, min(115.0, vx))
            droplets.append((
                when, across * when, up * when - 0.5 * GRAVITY * when * when, vx, vy,
                uniform(0.34, 0.62) * size ** 0.5, uniform(0.13, 0.25),
            ))
    # The mist: fine, quick, soon gone, all ways but mostly onward.
    for _ in range(chance.randint(4, 7)):
        lean = math.radians(uniform(-78.0, 78.0) + 10.0 * ONWARD)
        speed = uniform(95.0, 165.0)
        droplets.append((
            uniform(0.0, 0.02), 0.0, 0.5, speed * math.sin(lean), speed * math.cos(lean),
            uniform(0.3, 0.42), uniform(0.05, 0.1),
        ))
    # The jet out of the middle of a larger splash, and the drop it lets go of.
    jet = None
    if size > 1.08:
        tall, sway = uniform(2.8, 4.2) * size, uniform(-0.25, 0.25)
        jet = (0.055, uniform(0.13, 0.16), tall, sway)
        let_go = jet[0] + jet[1] * 0.55
        droplets.append((let_go, sway * tall, tall * 0.95, sway * 20.0, uniform(30.0, 50.0), 0.48 * size ** 0.5, 0.17))

    pool = (1.5 + 2.1 * size) * uniform(0.85, 1.15)  # how far the water lies to either side
    frames = []
    steps = 6  # a frame is the blur of what moved during it
    grow = scale ** 0.7  # a thing twice as far away is not twice as thick
    for frame in range(FRAMES):
        lit = [0.0] * (width * height)

        def dab(across: float, up: float, radius: float, weight: float) -> None:
            """A soft dot, so far to the side of where the drop landed and so
            far over the ledge."""
            x, y, radius = middle + across * scale, ground - up * scale, radius * grow
            reach = radius * 2.2
            for row in range(max(0, int(y - reach)), min(height, int(y + reach) + 1)):
                for column in range(max(0, int(x - reach)), min(width, int(x + reach) + 1)):
                    away = (column + 0.5 - x) ** 2 + (row + 0.5 - y) ** 2
                    lit[row * width + column] += weight * math.exp(-away / (radius * radius))

        for step in range(steps if frame * FRAME < 0.36 else 2):  # the pool hardly moves
            at = (frame + (step + 0.5) / (steps if frame * FRAME < 0.36 else 2)) * FRAME
            share = 1.0 / (steps if frame * FRAME < 0.36 else 2)
            # The drop itself, flattening where it landed.
            if at < 0.03:
                dab(0.0, 0.6, 1.25 * size ** 0.5, 1.5 * (1.0 - at / 0.03) * share)
            # The film of water running out along the ledge: its edge is the
            # brightest of it, and it is gone before it has gone far.
            if at < 0.13:
                left = 1.0 - at / 0.13
                for side in (-1.0, 1.0):
                    far = (2.0 + 46.0 * at ** 0.7 * size) * (1.15 if side == ONWARD else 0.9)
                    parts = max(2, int(far / 1.0))
                    for part in range(parts + 1):
                        along = part / parts
                        dab(side * far * along, 0.1, 0.62, 0.6 * left * (0.3 + 0.7 * along ** 2) * share)
            # The water it leaves lying: a low pool, thickest in the middle,
            # that gathers as the film falls back, lies, and thins away from
            # its edges inwards; with ripples running out through it.
            if 0.02 < at < POOL:
                there = sky._smooth(0.02, 0.16, at) * (1.0 - sky._smooth(POOL * 0.5, POOL, at))
                wide = pool * (0.55 + 0.45 * sky._smooth(0.02, 0.3, at)) * (1.0 - 0.35 * sky._smooth(POOL * 0.6, POOL, at))
                parts = max(4, int(wide * 2 / 0.7))
                for part in range(parts + 1):
                    off = (part / parts * 2.0 - 1.0) * wide
                    deep = math.sqrt(max(0.0, 1.0 - (off / wide) ** 2))
                    ripple = 0.0
                    for started in (0.06, 0.2):
                        ring = (at - started) * 16.0
                        if 0.0 < ring < wide:
                            ripple += math.exp(-(abs(off) - ring) ** 2 / 0.5) * (1.0 - ring / wide)
                    # Flat on the ledge: a swelling of the water that lies there, not a bead.
                    dab(off, 0.12 + 0.16 * deep * there, 0.5, (0.2 * deep + 0.26 * ripple) * there * share)
            # The crown: from the ledge up to its rim, thinner and fainter
            # towards the rim, and bowing outwards.
            for side, across, up, holds in crown:
                if at >= holds:
                    continue
                left = (1.0 - at / holds) ** 0.8
                tip_x, tip_y = across * at, up * at - 0.5 * GRAVITY * at * at
                foot = side * (1.0 + 16.0 * at)
                parts = max(3, int(math.hypot(tip_x - foot, tip_y) / 0.55))
                for part in range(parts + 1):
                    along = part / parts
                    bow = side * 1.1 * size * math.sin(along * math.pi) * (at / holds)
                    dab(
                        foot + (tip_x - foot) * along + bow, tip_y * along,
                        (0.62 - 0.3 * along) * size ** 0.5, 0.72 * left * (1.0 - 0.5 * along) * share,
                    )
            if jet and jet[0] <= at < jet[0] + jet[1]:
                since, lasts, tall, sway = at - jet[0], jet[1], jet[2], jet[3]
                rise = tall * math.sin(since / lasts * math.pi)
                left = min(1.0, (lasts - since) / (lasts * 0.4))
                parts = max(2, int(rise / 0.55))
                for part in range(parts + 1):
                    along = part / parts
                    dab(sway * rise * along, rise * along, (0.6 - 0.25 * along) * size ** 0.5, 0.3 * left * share)
            for when, x, y, vx, vy, radius, life in droplets:
                since = at - when
                if not 0.0 <= since < life:
                    continue
                rise = y + vy * since - 0.5 * GRAVITY * since * since
                if rise < 0.0:
                    continue  # it is back on the ledge
                fade = min(1.0, (life - since) / (0.5 * life))
                dab(x + vx * since, rise, radius * (0.72 + 0.28 * fade), 1.7 * fade * share)
        frames.append(bytes([255 if value >= 1.0 else int(value * 255.0 + 0.5) for value in lit]))
    return tuple(frames)


def ledge_water(width: int, scene: sky.Scene) -> tuple[int, int, bytes]:
    """The water that lies along the whole ledge while it rains, as its
    width, its height and RGBA rows: a thin line of it, here a little deeper
    and there hardly any, with a shine along its top. To be put with its
    bottom edge on the ledge."""
    keep = (1.0 - scene.shade) * 255.0
    tint = bytes(int(part * keep + 0.5) for part in sky._RAIN_TINT)
    height = 3
    deep = sky._fbm(width, 1, 0.11, 1.0, scene.seed * 3.3 + 5.0, scene.seed + 2.0, 3)[0]
    rows = bytearray()
    for row in range(height):
        for column in range(width):
            # It thins out to nothing at the ledge's ends.
            ends = min(1.0, column / 8.0, (width - 1 - column) / 8.0)
            water = max(0.0, deep[column] - 0.2) * 1.9 * ends
            level = (0.0, 0.34, 0.2)[row] if water > 0.35 else (0.0, 0.12, 0.2)[row]
            rows += tint
            rows.append(min(255, int(level * min(1.0, water * 1.6) * 255.0 + 0.5)))
    return width, height, bytes(rows)


def tint(scene: sky.Scene) -> bytes:
    """The colour a splash is, on this sky."""
    keep = (1.0 - scene.shade) * 255.0
    return bytes(int(part * keep + 0.5) for part in sky._RAIN_TINT)


def films(scene: sky.Scene) -> list[list[bytes]]:
    """Every film's frames as RGBA rows, ``SIZE`` each, in the rain's light."""
    colour = tint(scene)
    return [[tinted(colour, frame) for frame in _film(number)] for number in range(FILMS)]


@lru_cache(maxsize=None)
def _cut(number: int, frame: int) -> tuple[int, int, int, int, bytes] | None:
    """The part of a film's frame there is anything in: where its left top
    corner is from where the drop landed, its width and height, and how opaque
    each pixel of it is. ``None`` for a frame with nothing in it."""
    width, height = SIZE
    alpha = _film(number)[frame]
    rows = [alpha[row * width:(row + 1) * width] for row in range(height)]
    used = [row for row in range(height) if any(rows[row])]
    if not used:
        return None
    top, bottom = used[0], used[-1] + 1
    left = min(len(row) - len(row.lstrip(b"\0")) for row in rows[top:bottom] if any(row))
    right = max(len(row.rstrip(b"\0")) for row in rows[top:bottom])
    return (
        left - width // 2, top - height, right - left, bottom - top,
        b"".join(row[left:right] for row in rows[top:bottom]),
    )


def picture(scene: sky.Scene, number: int, frame: int) -> tuple[int, int, int, int, bytes] | None:
    """One frame of one film, as ``ui/popover.py`` shows it: where to put its
    left top corner - across from where the drop landed, and up from the ledge
    (so under 0) - its width, its height and its RGBA rows; or ``None`` when
    there is nothing in the frame.

    Only the part of the frame that has anything in it: most of a frame is
    empty, and Tk blends every pixel of a picture into what is under it,
    empty or not. And one at a time, when it is first wanted: there are a few
    hundred, and working them all out is a second of waiting for the window.
    """
    cut = _cut(number, frame)
    if cut is None:
        return None
    left, top, width, height, alpha = cut
    return left, top, width, height, tinted(tint(scene), alpha)


class Splashes:
    """The splashes on a ledge: ``(left, top, right)``, the stretch of a
    horizontal edge that the rain of ``layers`` comes down on. Only the near
    layer's rain splashes: the far one is too fine to see it of."""

    def __init__(self, layers: list[sky.RainLayer], ledge: tuple[float, float, float], seed: float = 0.0) -> None:
        self.left, self.top, self.right = ledge
        self._random = random.Random(int(seed * 1000) + 17)
        layer = layers[0]
        hits = [hit for hit in sky.rain_hits(layer, self.top) if self.left <= hit[1] <= self.right]
        self._speed, self._period = layer.speed, layer.period
        self._falls = [hit[0] for hit in hits]
        self._places = [hit[1] for hit in hits]
        self._at: float | None = None
        self._live: list[tuple[float, float, int]] = []  # where, since when, which film

    def _landed(self, before: float, now: float) -> list[float]:
        """Where the streaks that came down between two moments did."""
        start = before * self._speed % self._period
        end = now * self._speed % self._period
        first, last = bisect_right(self._falls, start), bisect_right(self._falls, end)
        if end >= start:
            return self._places[first:last]
        return self._places[first:] + self._places[:last]

    def advance(self, seconds: float) -> list[tuple[float, int, int]]:
        """Bring it to ``seconds`` since the rain began; the splashes there are
        then, each as its place along the ledge, its film and the frame of it."""
        before, self._at = self._at, seconds
        if before is None or not 0.0 <= seconds - before <= PAUSE:
            self._live.clear()
            return []
        for place in self._landed(before, seconds):
            if self._random.random() < SHARE:
                film = int(self._random.random() ** RARER * FILMS)
                self._live.append((place, seconds, min(FILMS - 1, film)))
        end = FRAMES * FRAME
        self._live = [splash for splash in self._live if seconds - splash[1] < end]
        return [(place, film, int((seconds - since) / FRAME)) for place, since, film in self._live]
