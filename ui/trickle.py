"""Drops running down the glass of the weather popover in the rain.

The drops on the window (``sky.glass_drops``) are one still picture. Now and
then one more grows heavy and runs. Most just run down, each at a speed of
its own; a few go fast; and some creep, let go and slide a little way, and
catch again. All wander a pixel or two sideways as they go, and behind each
stays a wet track that dries up in a few seconds.

A drop has no shape of its own and no clock to change it by: its shape is
what its motion makes it. Slow, it is squat and heavy; the faster it goes the
longer and thinner it is drawn out, with a longer neck trailing; and going
sideways its body leans that way under the neck. And its speed never jumps -
it gathers and it slackens - so the shape follows without a jerk, and a drop
that keeps its speed keeps its shape.

``Trickles.advance`` says what there is to draw and where; the pictures are
``picture`` - each drop in its many shapes, and lengths of track of several
widths at several stages of drying. A track is laid in lengths because Tk
cannot show part of a picture, and a drop's whole way is not known before it
has gone it.
"""

from __future__ import annotations

import math
import random
from functools import lru_cache

from . import sky
from .shapes import cropped

#: How many drops run at once at most, and how long till the next one starts.
RUNNERS = 7
WAIT = (0.3, 1.5)
#: A drop does not start over or under another that is running, nor close
#: beside one: not within this many pixels of it or of its track, sideways.
APART = 26.0
#: Where there is a plate over the lower glass, a drop is to go behind it and
#: come out under it, not run down the strip of open glass at its side: that
#: strip is too narrow for a drop to look anything but stuck in it. So a drop
#: keeps this many pixels, and its own half-width, inside the plate's sides.
#: The one exception is a large drop - from this one of ``DROPS`` on - going
#: straight down the plate's very edge, half of it behind the plate: this
#: share of the large ones do.
INSIDE = 4.0
EDGE_FROM = 4
EDGE_SHARE = 0.3
#: One that creeps and slides creeps at this many pixels a second for this
#: long, then slides at this many for this long, and so on.
CREEP = ((5.0, 13.0), (0.5, 1.9))
SLIDE = ((38.0, 80.0), (0.25, 0.8))
#: No two drops are as quick: each goes at its own share of those speeds, the
#: heavy ones several times as fast as the slow.
PACE = (0.45, 2.1)
#: But not every drop goes that way: all of them creeping and letting go at
#: once is a glass full of snails. Most simply run down at a speed of their
#: own, some go fast, and only the rest creep and slide. A manner is: of every
#: how many drops it is, its speed (pixels a second, before the drop's own
#: pace), and how much of the sideways wander it has.
STEADY = (0.56, (17.0, 34.0), 0.25)
SWIFT = (0.2, (48.0, 85.0), 0.5)
#: It wanders sideways by up to this many pixels a second.
WANDER = 9.0
#: How fast a drop comes to the speed it is to go at - gathering it, and
#: slackening, which is the slower - and to its sideways drift; and how fast
#: its shape comes to what that speed makes it. All as shares a second.
GATHER = 4.5
SLACKEN = 2.4
VEER = 1.3
SETTLE = 5.0
#: At this speed a drop is drawn out about two thirds of the way.
DRAWN_AT = 45.0
#: Drifting this fast sideways it leans all the way.
LEAN_AT = 8.0

#: A length of track: how long it is, how long it takes to dry, and in how
#: many steps it is seen to.
TRACK = 30
DRY = 3.6
FADES = 4
#: A large drop leaves a wider track than a small one: the widths there are,
#: as how many times the narrowest, and the first of ``DROPS`` to leave each.
WIDTHS = ((1.0, 0), (1.55, 2), (2.2, 4), (3.0, 5), (3.8, 6))
#: The different lengths of track there are pictures of.
TRACKS = 3
#: A length of track goes from where the drop was at its top to where it was
#: at its bottom, so it can slant - by up to this many pixels either way - and
#: the lengths meet end to end: the track bends where the drop turned, and is
#: not a stair of upright pieces.
SLANT = 7
SLANTS = 2 * SLANT + 1
#: The drops there are pictures of: half-width and half-height of the body
#: of each, in pixels, from the small ones to a few large.
DROPS = ((2.6, 3.6), (3.0, 4.6), (3.6, 5.2), (4.4, 6.4), (5.4, 7.6), (6.6, 9.4), (8.0, 11.0))
#: There is a picture of each drop at this many stages of being drawn out, at
#: each leaning this many ways (the middle one upright), and each of those put
#: this many parts of a pixel further down: a slow drop is seen to move more
#: often than once a pixel.
STRETCHES = 24
LEANS = 5
SHIFTS = 2
DROP_PICTURES = len(DROPS) * STRETCHES * LEANS * SHIFTS
#: How many pictures there are in all: the drops', then the tracks'.
PICTURES = DROP_PICTURES + len(WIDTHS) * TRACKS * SLANTS * FADES
#: How plainly a running drop and its track are drawn, beside the still ones.
DROP_STRENGTH = 1.9
TRACK_STRENGTH = 2.0
#: A gap in time longer than this is not time that the drops ran on through.
PAUSE = 0.25


def _pixels(width: int, height: int, net, white: bytes, glow: float, strength: float) -> bytes:
    """RGBA rows from ``net(column, row)``: over 0 a pixel lightens what is
    under it, under 0 it darkens it."""
    rows = bytearray()
    for row in range(height):
        for column in range(width):
            value = net(column + 0.5, row + 0.5) * strength
            if value > 0.0:
                rows += white
                rows.append(min(150, int(value * glow * 255.0 + 0.5)))
            else:
                rows += b"\0\0\0"
                rows.append(min(120, int(-value * 255.0 + 0.5)))
    return bytes(rows)


def track_width(kind: int) -> int:
    """How wide the picture of a length of track of the ``kind``-th width is."""
    return math.ceil(3.0 * WIDTHS[kind][0]) * 2 + 3 + SLANT + 1


def track_kind(number: int) -> int:
    """Which of ``WIDTHS`` the ``number``-th of ``DROPS`` leaves behind it."""
    return max(kind for kind, (_wide, first) in enumerate(WIDTHS) if number >= first)


def track_picture(kind: int, which: int = 0, slant: int = 0, fade: int = 0) -> int:
    """The number of a length of track's picture: of which width, which of the
    ``TRACKS``, slanting how many pixels to the right on its way down (or,
    under 0, to the left), and at which stage of drying. It is to be put with
    the middle of its top edge at where the track's upper end is, plus half
    the slant rounded down."""
    return DROP_PICTURES + (((kind * TRACKS + which) * SLANTS) + slant + SLANT) * FADES + fade


def drop_picture(number: int, stretch: int = 0, lean: int = LEANS // 2, shift: int = 0) -> int:
    """The number of a drop's picture: which drop, how drawn out (up to
    ``STRETCHES``), leaning which way (up to ``LEANS``) and how many parts of
    a pixel further down (up to ``SHIFTS``)."""
    return ((number * STRETCHES + stretch) * LEANS + lean) * SHIFTS + shift


def picture(scene: sky.Scene, index: int) -> tuple[int, int, bytes]:
    """One of the pictures ``advance`` names by number, as its width, its
    height and RGBA rows. First the drops (``drop_picture``); then every
    length of track - of every width, and at every stage of drying, the
    wettest first.

    One at a time, because there are thousands and a rain shows a few dozen
    of them in its first seconds: ``ui/popover.py`` makes each when it is
    first wanted.
    """
    keep = 1.0 - scene.shade
    white = bytes(int((part + (1.0 - part) * 0.6) * keep * 255.0 + 0.5) for part in sky._unit(scene.light))
    glow = 0.6 if scene.moonlit > 0.5 else 1.0
    strength = sky.GLASS_STRENGTH * scene.rain
    if index < DROP_PICTURES:
        rest, shift = divmod(index, SHIFTS)
        rest, lean = divmod(rest, LEANS)
        number, stretch = divmod(rest, STRETCHES)
        width, height = drop_size(number)
        net = _drop(number, stretch / (STRETCHES - 1), lean / (LEANS - 1) * 2.0 - 1.0, shift / SHIFTS)
        lighter, darker = strength * DROP_STRENGTH * glow * 255.0, strength * DROP_STRENGTH * 255.0
        clear, rows = bytes(4), []
        for line in net:
            for value in line:
                if value > 0.0:
                    rows.append(white + bytes((min(150, int(value * lighter + 0.5)),)))
                elif value < 0.0:
                    rows.append(b"\0\0\0" + bytes((min(120, int(-value * darker + 0.5)),)))
                else:
                    rows.append(clear)
        return width, height, b"".join(rows)
    rest, fade = divmod(index - DROP_PICTURES, FADES)
    rest, slant = divmod(rest, SLANTS)
    slant -= SLANT
    kind, number = divmod(rest, TRACKS)
    # Where its middle line is at the top, from the middle of the picture.
    start = slant / 2 - slant // 2 - slant / 2
    wide = WIDTHS[kind][0]
    width, height = track_width(kind), TRACK
    chance = random.Random(number * 131 + 7)
    # The track is not of one width: it pinches and beads as it dries.
    # (By waves that come to nothing at both ends, so that any two lengths meet.)
    a, b, c = chance.uniform(-0.2, 0.2), chance.uniform(-0.12, 0.12), chance.uniform(-0.08, 0.08)
    left = 1.0 - fade / FADES

    def track(x: float, y: float) -> float:
        turn = y / height * math.tau
        body = 0.72 + a * math.sin(turn / 2) + b * math.sin(turn) + c * math.sin(1.5 * turn)
        # Drying, it breaks up where it was thinnest.
        body = max(0.0, body - (1.0 - left) * 0.55) / (1.0 - (1.0 - left) * 0.3)
        dx = (x - width / 2 - start - slant * y / height) / wide
        middle = math.exp(-dx * dx / (0.9 * body + 0.05))
        rim = math.exp(-(dx + 1.5) ** 2 / 0.6)  # its shaded side
        return (0.34 * middle - 0.2 * rim) * body * (0.35 + 0.65 * left)

    return width, height, _pixels(width, height, track, white, glow, strength * TRACK_STRENGTH)


def cut(scene: sky.Scene, index: int) -> tuple[int, int, int, int, bytes] | None:
    """A picture (``picture``) as ``ui/popover.py`` shows it: only the part of
    it with anything in it - a drop's picture has room in it for the longest
    neck the drop ever has, and is mostly empty - as how far to the right of
    and under the place ``advance`` gives its left top corner goes, its width
    and height, and its rows."""
    width, height, rows = picture(scene, index)
    part = cropped(width, height, rows)
    return part and (part[0] - width // 2, *part[1:])


def drop_size(number: int) -> tuple[int, int]:
    """The size of a drop's picture: its body, the neck above it at its
    longest, and room for it to lean and for its outline to wander."""
    half_wide, half_tall = DROPS[number]
    return math.ceil(half_wide * 4.0) + 4, math.ceil(half_tall * 5.4) + 5


def drop_middle(number: int) -> float:
    """How far under the top of its picture the middle of a drop's body is."""
    return drop_size(number)[1] - DROPS[number][1] * 1.5 - 3.0


def _drop(number: int, stretch: float = 0.0, lean: float = 0.0, shift: float = 0.0) -> list[list[float]]:
    """A running drop, as how much each pixel of its picture lightens (or,
    under 0, darkens) what is under it: ``stretch`` from 0, squat, to 1, drawn
    out; ``lean`` from -1, its body swung to the left, to 1; ``shift`` of a
    pixel further down.

    It is made the way the still drops on the glass are (``sky._wet``): a few
    blobs that run together - a heavy body, the neck it trails, and a bulge on
    one side or the other - looked at through a ripple, so that no outline is
    an oval and no two drops are alike. And it is shaded the same: darker at
    its upper edge, lighter at its lower, a dome between.

    Everything about it but those three is the drop's own and does not change,
    and each of the three moves every part of it a little: so two pictures
    close in them are close in every pixel, and a drop going from one to the
    next is seen to flow.
    """
    side, neck_at, bulge_at, sag_at, seen = _own(number)
    half_wide, half_tall = DROPS[number]
    width, height = drop_size(number)
    middle_x, middle_y = width / 2, drop_middle(number) + shift
    # Drawn out it is longer and thinner, and there is as much water in it;
    # and its neck is longer by more than that.
    half_wide *= 1.24 - 0.52 * stretch
    half_tall *= 0.74 + 0.7 * stretch
    neck = 0.4 + 1.1 * stretch
    swing = 0.24 * lean * half_wide  # the body goes first, the neck trails it
    # Each blob: where its middle is, and its half-width and half-height.
    blobs = [
        (middle_x + swing, middle_y, half_wide, half_tall),
        (  # the neck, off to one side of the top
            middle_x + side * half_wide * neck_at[0] - swing * (0.6 + 0.9 * stretch),
            middle_y - half_tall * (0.75 + 0.45 * neck) * neck_at[1],
            half_wide * neck_at[2], half_tall * neck_at[3] * neck,
        ),
        (  # a bulge
            middle_x - side * half_wide * bulge_at[0] + swing, middle_y + half_tall * bulge_at[1],
            half_wide * bulge_at[2], half_tall * bulge_at[3],
        ),
    ]
    if DROPS[number][0] > 4.0:  # a large one sags unevenly
        blobs.append((
            middle_x + side * half_wide * sag_at[0] + swing, middle_y + half_tall * sag_at[1],
            half_wide * sag_at[2], half_tall * sag_at[3],
        ))

    near = [[0.0] * width for _ in range(height)]
    reach = 0.3 * DROPS[number][0] + 1.0  # how far the ripple can move a pixel
    for at_x, at_y, wide, tall in blobs:
        wide, tall = wide * 1.6, tall * 1.6
        for row in range(max(0, int(at_y - tall - reach)), min(height, int(at_y + tall + reach) + 1)):
            line, places = near[row], seen[row]
            for column in range(max(0, int(at_x - wide - reach)), min(width, int(at_x + wide + reach) + 1)):
                x, y = places[column]
                away = ((x - at_x) / wide) ** 2 + ((y - at_y) / tall) ** 2
                if away < 1.0:
                    line[column] += (1.0 - away) ** 2
    smooth = sky._smooth
    water = [[smooth(0.36, 0.52, value) if value > 0.36 else 0.0 for value in line] for line in near]
    net = []
    last, edge = height - 1, width - 1
    for row in range(height):
        here, mass = water[row], near[row]
        above, below = water[row - 1 if row else 0], water[row + 1 if row < last else last]
        mass_above, mass_below = near[row - 1 if row else 0], near[row + 1 if row < last else last]
        line = [0.0] * width
        for column in range(width):
            wet = here[column]
            rise = below[column] - above[column]
            if not wet and not rise:
                continue
            down, up = mass_below[column], mass_above[column]
            dome = (down if down < 1.5 else 1.5) - (up if up < 1.5 else 1.5)
            line[column] = (
                -0.5 * rise
                - 0.14 * (here[column + 1 if column < edge else edge] - here[column - 1 if column else 0])
                - 1.1 * dome * wet + 0.04 * wet
            )
        net.append(line)
    # The neck of a drop that is going is water thinning out behind it: the
    # further up it, the fainter and the softer, till its tip is hardly there.
    going = sky._smooth(0.08, 0.45, stretch)
    if going:
        _x, neck_y, _wide, neck_tall = blobs[1]
        tip, shoulder = neck_y - neck_tall * 1.45, middle_y - half_tall * 0.55
        for row in range(max(1, int(tip) - 1), min(last, int(shoulder) + 1)):
            thin = going * (1.0 - sky._smooth(tip, shoulder, row + 0.5))
            if thin <= 0.0:
                continue
            line, above, below = net[row], net[row - 1], net[row + 1]
            soft = [
                (line[column - 1] + line[column + 1] + above[column] + below[column]) * 0.125 + line[column] * 0.5
                for column in range(1, edge)
            ]
            keep = 1.0 - 0.8 * thin
            net[row] = [line[0] * keep] + [
                (sharp + (blurred - sharp) * thin) * keep for sharp, blurred in zip(line[1:edge], soft)
            ] + [line[edge] * keep]
    return net


@lru_cache(maxsize=None)
def _own(number: int):
    """What is a drop's own and does not change as it goes: which side its
    neck is off to, where its neck, its bulge and its sag are, and the ripple
    it is looked at through - as where each pixel of its picture is seen."""
    chance = random.Random(number * 977 + 5)
    uniform = chance.uniform
    half_wide, half_tall = DROPS[number]
    width, height = drop_size(number)
    middle_x, middle_y = width / 2, drop_middle(number)
    side = chance.choice((-1.0, 1.0))
    ripple = [(uniform(0.0, math.tau), uniform(0.55, 1.1)) for _ in range(4)]
    bend = 0.085 * half_wide
    neck_at = (uniform(0.05, 0.3), uniform(0.9, 1.1), uniform(0.34, 0.5), uniform(0.6, 0.85))
    bulge_at = (uniform(0.25, 0.45), uniform(-0.3, 0.4), uniform(0.55, 0.75), uniform(0.5, 0.7))
    sag_at = (uniform(0.3, 0.5), uniform(0.3, 0.55), uniform(0.5, 0.65), uniform(0.45, 0.6))
    seen = []
    for row in range(height):
        line = []
        for column in range(width):
            x, y = column + 0.5, row + 0.5
            x += bend * (math.sin((y - middle_y) / half_tall * ripple[0][1] * 1.3 + ripple[0][0])
                         + 0.5 * math.sin((y - middle_y) / half_tall * ripple[1][1] * 2.7 + ripple[1][0]))
            y += bend * (math.sin((x - middle_x) / half_wide * ripple[2][1] * 1.3 + ripple[2][0])
                         + 0.5 * math.sin((x - middle_x) / half_wide * ripple[3][1] * 2.7 + ripple[3][0]))
            line.append((x, y))
        seen.append(line)
    return side, neck_at, bulge_at, sag_at, seen


def drawn(speed: float) -> float:
    """How drawn out a drop going down at ``speed`` comes to be, from 0 to 1."""
    return 1.0 - math.exp(-max(0.0, speed) / DRAWN_AT)


class Drop:
    """One drop on its way down."""

    __slots__ = ("low", "high", "x", "y", "speed", "want", "until", "sliding", "drift", "veer", "number", "laid", "trail", "pace",
                 "shape", "manner")

    def __init__(self, x: float, y: float, number: int, pace: float, manner) -> None:
        self.x, self.y, self.number, self.pace, self.manner = x, y, number, pace, manner
        self.low, self.high = x, x  # how far to either side it may wander
        self.laid = y  # how far down its track has been laid
        self.trail = round(x)  # and where its lower end is
        self.speed = self.want = 0.0  # how fast it goes, and is to go
        self.drift = self.veer = 0.0  # the same, sideways
        self.until, self.sliding = 0.0, False
        self.shape = 0.0  # how drawn out it is


class Trickles:
    """The drops running down a pane ``width`` by ``height``; ``plate`` is
    the left and the right side of what covers the lower part of it, if
    anything does."""

    def __init__(
        self, width: int, height: int, seed: float = 0.0, plate: tuple[float, float] | None = None
    ) -> None:
        self.width, self.height, self.plate = width, height, plate
        self._random = random.Random(int(seed * 1000) + 71)
        self._at: float | None = None
        self._next = 0.0
        self.drops: list[Drop] = []
        #: Each ``(x, top, since, which, slant)``: where its picture goes,
        #: which its width and its kind are, and how far it slants.
        self.tracks: list[tuple[int, int, float, int, int]] = []

    def _pace(self, drop: Drop, now: float, sliding: bool) -> None:
        """Say how fast the drop is to go from now, and till when."""
        uniform = self._random.uniform
        if drop.manner:
            # It keeps to its speed, give or take, and drifts a little.
            _share, speed, wander = drop.manner
            if not drop.want:
                drop.want = uniform(*speed) * (0.6 + 0.4 * drop.pace)
            else:
                drop.want = min(speed[1] * 1.5, max(speed[0] * 0.5, drop.want * uniform(0.88, 1.14)))
            drop.until, drop.sliding = now + uniform(0.7, 2.0), False
            drop.veer = uniform(-WANDER, WANDER) * wander if drop.high > drop.low else 0.0
            return
        speed, lasts = SLIDE if sliding else CREEP
        drop.want, drop.until, drop.sliding = uniform(*speed) * drop.pace, now + uniform(*lasts), sliding
        drop.veer = uniform(-WANDER, WANDER) if sliding and drop.high > drop.low else 0.0

    def advance(self, seconds: float) -> list[tuple[int, int, int]]:
        """Bring it to ``seconds`` since the rain began; what there is to draw
        then, each as where the middle of a picture's top edge is and which
        picture (``picture``) it is. The tracks come first: the drops are
        over them."""
        before, self._at = self._at, seconds
        uniform = self._random.uniform
        if before is None or not 0.0 <= seconds - before <= PAUSE:
            self.drops.clear()
            self.tracks.clear()
            self._next = seconds + uniform(0.3, 1.2)
            return []
        passed = seconds - before
        place = None
        if len(self.drops) < RUNNERS and seconds >= self._next:
            # Most are small and slow; the larger a drop, the quicker it is
            # likely to be, and a few are large.
            pace = PACE[0] + (PACE[1] - PACE[0]) * uniform(0.0, 1.0) ** 1.5
            number = int((pace - PACE[0]) / (PACE[1] - PACE[0]) * len(DROPS) + uniform(-1.0, 1.0))
            number = min(len(DROPS) - 1, max(0, number))
            # Where it may go: anywhere, or behind the plate, or down its edge.
            low, high = 10.0, self.width - 10.0
            if self.plate:
                room = DROPS[number][0] * 1.25 + INSIDE
                low, high = self.plate[0] + room, self.plate[1] - room
                if number >= EDGE_FROM and uniform(0.0, 1.0) < EDGE_SHARE:
                    low = high = float(self._random.choice(self.plate))
            # The freest of a few places; if none is free enough, a little later.
            taken = [drop.x for drop in self.drops] + [float(track[0]) for track in self.tracks]
            tries = [uniform(low, high) for _ in range(12)]
            place = max(tries, key=lambda x: min((abs(x - other) for other in taken), default=self.width))
            if any(abs(place - other) < APART for other in taken):
                place = None
                self._next = seconds + 0.25
        if place is not None:
            self._next = seconds + uniform(*WAIT)
            lot = uniform(0.0, 1.0)
            manner = STEADY if lot < STEADY[0] else SWIFT if lot < STEADY[0] + SWIFT[0] else None
            drop = Drop(place, uniform(-8.0, self.height * 0.45), number, pace, manner)
            drop.low, drop.high = low, high
            self._pace(drop, seconds, False)
            self.drops.append(drop)
        for drop in self.drops:
            if seconds >= drop.until:
                self._pace(drop, seconds, not drop.sliding)
            # Its speed gathers and slackens; it never jumps.
            rate = GATHER if drop.want > drop.speed else SLACKEN
            drop.speed += (drop.want - drop.speed) * min(1.0, rate * passed)
            drop.drift += (drop.veer - drop.drift) * min(1.0, VEER * passed)
            drop.x = min(drop.high, max(drop.low, drop.x + drop.drift * passed))
            if drop.x in (drop.low, drop.high):
                drop.drift = 0.0  # at the end of its room it goes straight
            drop.y += drop.speed * passed
            # And its shape comes after its speed.
            drop.shape += (drawn(drop.speed) - drop.shape) * min(1.0, SETTLE * passed)
            # The track follows a length behind, so that the drop is over its end.
            while drop.laid + TRACK <= drop.y:
                # From where the last length ended to where the drop is now.
                slant = max(-SLANT, min(SLANT, round(drop.x) - drop.trail))
                which = track_kind(drop.number) * TRACKS + self._random.randrange(TRACKS)
                self.tracks.append((drop.trail + slant // 2, round(drop.laid), seconds, which, slant))
                drop.trail += slant
                drop.laid += TRACK
        self.drops = [drop for drop in self.drops if drop.y < self.height + 8.0]
        self.tracks = [track for track in self.tracks if seconds - track[2] < DRY]
        shown = [
            (x, top, track_picture(*divmod(which, TRACKS), slant, int((seconds - since) / DRY * FADES)))
            for x, top, since, which, slant in self.tracks
        ]
        for drop in self.drops:
            stretch = min(STRETCHES - 1, int(drop.shape * (STRETCHES - 1) + 0.5))
            lean = max(-1.0, min(1.0, drop.drift / LEAN_AT))
            top = drop.y - drop_middle(drop.number)
            whole = math.floor(top)
            shown.append((
                round(drop.x), whole,
                drop_picture(
                    drop.number, stretch, int((lean + 1.0) / 2.0 * (LEANS - 1) + 0.5),
                    min(SHIFTS - 1, int((top - whole) * SHIFTS)),
                ),
            ))
        return shown
