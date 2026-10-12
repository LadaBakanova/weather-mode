"""The sky behind the weather popover, painted without a graphics card.

``panel.pen`` fills the weather window with the shader ``pen-assets/sky.glsl``:
a three-stop gradient, the glow and rays of the sun, a night of stars with the
Milky Way across it, clouds gathering at the top, rain. This is that shader in plain Python,
layer for layer and with the same constants, so the window looks like the
mockup. A few layers are worked out by the cell rather than by the pixel -
stars, streaks of rain and drops are each a handful of pixels in their cell -
and the cloud noise by the table. That brings a picture down to about a fifth
of a second, and ``ui/popover.py`` keeps the last one.

The clouds can also be had apart from the sky, as a strip that goes round:
the popover slides it over the picture, and the clouds drift. So can the
streaks of rain, as layers that slide down their slant: the rain falls. And in
a thunderstorm there is the light of a flash to lay over the sky now and then.
"""

from __future__ import annotations

import math
import random
from typing import NamedTuple

from .shapes import _rgb, tinted

#: The mockup's window width; the shader's patterns are sized in these pixels.
DESIGN_WIDTH = 300.0


class Scene(NamedTuple):
    """The shader's uniforms."""

    top: str
    mid: str
    bottom: str
    light: str
    cloud: str
    light_x: float
    light_y: float
    sun: float
    rays: float = 0.0
    #: How much of the sun's light lies over the whole sky, not only near it.
    wash: float = 0.0
    moon: float = 0.0
    stars: float = 0.0
    clouds: float = 0.0
    rain: float = 0.0
    shade: float = 0.0
    seed: float = 1.0
    #: A night by starlight: stars of every size, the Milky Way across them and
    #: four-pointed sparkles, and clouds that are shapes barely lighter than the
    #: sky. The mockup's lit moon for such a night is not painted here: no sky
    #: has one yet.
    moonlit: float = 0.0
    milky: float = 0.0
    sparkle: float = 0.0
    #: A thunderstorm: now and then the sky is lit by a flash (``flash_level``).
    lightning: float = 0.0
    #: Snow falling (``snow_layers``).
    snow: float = 0.0
    #: A blizzard: the snow is driven nearly flat by the wind, and there is
    #: so much of it in the air that the sky is half hidden.
    gale: float = 0.0
    #: The wind, in metres a second, which sets how fast the clouds drift
    #: (``cloud_speed``); ``None`` when it is not known.
    wind: float | None = None


# The four skies of the mockup ("Вариант 3"), each as drawn for a clear day.
_PHASES = {
    "morning": Scene("#4E7FC4", "#BF86A2", "#E8915A", "#FFE2B0", "#E6C2BC", 0.16, 1.08, 0.35, seed=4),
    "day": Scene("#1C62C8", "#3C8FE4", "#6DB4F2", "#FFF6D6", "#E3ECF8", 0.68, 0.10, 0.8, rays=0.5, seed=12),
    "evening": Scene("#6F7FC8", "#E79A78", "#F26A2A", "#FFC27A", "#DDA291", 0.78, 1.08, 0.6, seed=7),
    # "НОЧЬ · ЯСНО · МЛЕЧНЫЙ ПУТЬ": a moonless night.
    "night": Scene(
        "#03061A", "#0A1338", "#1C3262", "#DDE6FF", "#59618E", 0.82, 0.17, 0.0,
        stars=1.0, seed=30, moonlit=1.0, milky=1.0, sparkle=0.3,
    ),
}

#: By the weather's icon: cloud cover, rain, and how much of the light is left.
_SKIES = {
    "sun": (0.15, 0.0, 1.0),
    "moon": (0.15, 0.0, 1.0),
    "cloud-sun": (0.5, 0.0, 1.0),
    "cloud-moon": (0.5, 0.0, 1.0),
    "cloud": (0.9, 0.0, 0.4),
    "cloud-snow": (0.9, 0.0, 0.4),
    "cloud-sun-rain": (0.75, 1.0, 0.3),
    "cloud-rain": (0.75, 1.0, 0.3),
    "cloud-lightning": (0.9, 1.0, 0.2),
}


#: In a light wind the clouds are few and slow, and hard to see move: they
#: are made this much more of (a share of the sky) up to ``LIGHT_WIND`` metres
#: a second, and the less the nearer the wind comes to ``LIGHT_WIND_END``.
LIGHT_WIND_CLOUDS = 0.12
LIGHT_WIND = 2.0
LIGHT_WIND_END = 6.0


def _light_wind_clouds(wind: float) -> float:
    """How much more cloud a light wind brings (0 from ``LIGHT_WIND_END`` on)."""
    fade = (LIGHT_WIND_END - max(wind, LIGHT_WIND)) / (LIGHT_WIND_END - LIGHT_WIND)
    return LIGHT_WIND_CLOUDS * max(0.0, fade)


def scene_for(phase: str, icon: str, blizzard: bool = False, wind: float | None = None) -> Scene:
    """The sky for a part of the day (``Weather.phase``) and a weather icon;
    ``blizzard`` when its snow is driven by a gale (``Weather.blizzard``); ``wind``
    is ``Weather.wind``."""
    base = _PHASES.get(phase, _PHASES["day"])
    clouds, rain, light = _SKIES.get(icon, _SKIES["cloud"])
    overcast = light < 1.0
    night = phase == "night"
    # What a clear night shows goes out in the rain and all but out under cloud.
    snow = 1.0 if icon == "cloud-snow" else 0.0
    seen = 0.0 if rain or snow else 0.25 if overcast else 1.0
    if wind is not None:
        clouds = min(1.0, clouds + _light_wind_clouds(wind))
    return base._replace(
        wind=wind,
        sun=round(base.sun * light, 3),
        rays=0.0 if overcast else base.rays,
        # The sun's light lies over the window a little, warm, and fades with distance.
        wash=round(base.sun * light * 0.13, 3) if not overcast else 0.0,
        moon=0.0 if overcast else base.moon,
        stars=base.stars * seen,
        milky=base.milky * seen,
        sparkle=base.sparkle * seen,
        clouds=clouds,
        rain=rain,
        lightning=1.0 if icon == "cloud-lightning" else 0.0,
        snow=snow,
        gale=1.0 if snow and blizzard else 0.0,
        # The mockup dims a bright sky a little, and a grey one a little more,
        # so that white text stays readable on it.
        shade=0.0 if night else 0.12 if overcast else 0.09,
    )


def _unit(color: str) -> tuple[float, float, float]:
    red, green, blue = _rgb(color)
    return red / 255, green / 255, blue / 255


def _smooth(low: float, high: float, value: float) -> float:
    """GLSL's ``smoothstep``; ``low`` may be above ``high``."""
    t = (value - low) / (high - low)
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    return t * t * (3.0 - 2.0 * t)


def _hash(x: float, y: float) -> float:
    x = x * 123.34 % 1.0
    y = y * 456.21 % 1.0
    both = x * (x + 45.32) + y * (y + 45.32)
    return (x + both) * (y + both) % 1.0


def _backdrop(scene: Scene, height: int) -> list[tuple[float, float, float]]:
    """The gradient, row by row, greyed by the cloud cover, the rain and the snow."""
    top, mid, bottom = _unit(scene.top), _unit(scene.mid), _unit(scene.bottom)
    overcast = min(1.0, max(0.0, scene.clouds - 0.3, scene.rain * 0.9, scene.snow * 0.7)) * 0.75
    dim = (1.0 - 0.3 * scene.rain) * (1.0 - 0.1 * scene.snow)
    rows = []
    for row in range(height):
        v = (row + 0.5) / height
        to_mid, to_bottom = _smooth(0.0, 0.58, v), _smooth(0.42, 1.0, v)
        color = [a + (b - a) * to_mid for a, b in zip(top, mid)]
        color = [a + (b - a) * to_bottom for a, b in zip(color, bottom)]
        luma = 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]
        grey = (luma * 0.78, luma * 0.85, luma * 0.97)
        color = [(a + (b - a) * overcast) * dim for a, b in zip(color, grey)]
        if scene.gale:
            # The air is full of snow: everything is nearer one pale colour,
            # by day nearly white and by night a lighter dark.
            pale = min(1.0, luma * 1.5 + 0.08)
            veil = (pale * 0.94, pale * 0.96, pale)
            color = [a + (b - a) * 0.42 * scene.gale for a, b in zip(color, veil)]
        rows.append(tuple(color))
    return rows


def _cloud_noise(width: int, height: int, scale: float, seed: float) -> list[list[float]]:
    """The noise the clouds are cut out of, at every pixel."""
    return _fbm(width, height, 0.0085 * scale, 0.019 * scale, seed * 1.7, seed * 0.6)


def _fbm(
    width: int, height: int, step_x: float, step_y: float, start_x: float, start_y: float,
    octaves: int = 5,
) -> list[list[float]]:
    """The shader's ``fbm`` at every pixel: five octaves of value noise, or
    fewer for a smoother one. A pixel is a step on from the one before, and
    the first is at the start.

    An octave's lattice is a small table, and along a row only the fraction
    between two lattice columns changes, so both are worked out once.
    """
    field = [[0.0] * width for _ in range(height)]
    start_x += 0.5 * step_x
    start_y += 0.5 * step_y
    weight = 0.5
    for _ in range(octaves):
        columns = []
        for column in range(width):
            p = start_x + column * step_x
            cell = math.floor(p)
            f = p - cell
            columns.append((cell, f * f * (3.0 - 2.0 * f)))
        first = columns[0][0]
        span = range(first, columns[-1][0] + 2)
        columns = [(cell - first, f) for cell, f in columns]
        lattice: dict[int, list[float]] = {}
        for row in range(height):
            p = start_y + row * step_y
            cell = math.floor(p)
            f = p - cell
            f = f * f * (3.0 - 2.0 * f)
            for k in (cell, cell + 1):
                if k not in lattice:
                    lattice[k] = [_hash(x, k) for x in span]
            upper, lower = lattice[cell], lattice[cell + 1]
            # The row's own lattice line, then one lookup and one mix a pixel.
            line = [a + (b - a) * f for a, b in zip(upper, lower)]
            out = field[row]
            for column, (k, fx) in enumerate(columns):
                a = line[k]
                out[column] += weight * (a + (line[k + 1] - a) * fx)
        step_x *= 2.03
        step_y *= 2.03
        start_x = start_x * 2.03 + 17.1
        start_y = start_y * 2.03 + 9.2
        weight *= 0.5
    return field


def _stars(width: int, height: int, scale: float, scene: Scene) -> list[dict[int, float]]:
    """Per row, the brightness of the pixels a star lights: one star to a
    15 px cell, in under a third of the cells, thinning out towards the horizon."""
    rows: list[dict[int, float]] = [{} for _ in range(height)]
    cell = 15.0 / scale  # in real pixels
    for cy in range(int(height / cell) + 1):
        for cx in range(int(width / cell) + 1):
            chance = _hash(cx + scene.seed, cy + scene.seed)
            if chance < 0.7:
                continue
            radius = (0.03 + 0.07 * chance) * cell
            x = (cx + 0.5 + (_hash(cx + 1.7, cy + 1.7) - 0.5) * 0.7) * cell
            y = (cy + 0.5 + (_hash(cx + 9.2, cy + 9.2) - 0.5) * 0.7) * cell
            for row in range(max(0, int(y - radius)), min(height, int(y + radius) + 1)):
                fade = scene.stars * (1.0 - (row + 0.5) / height * 0.85)
                for column in range(max(0, int(x - radius)), min(width, int(x + radius) + 1)):
                    glow = _smooth(radius, 0.0, math.hypot(column + 0.5 - x, row + 0.5 - y))
                    if glow:
                        rows[row][column] = glow * fade
    return rows


def _cells(width: int, height: int, scale: float, cell: float, offset: float):
    """The cells of a ``cell`` px grid (design pixels, moved by ``offset``)
    that the picture touches: each with its id and the pixels inside it."""
    for cy in range(math.floor(offset / cell), math.ceil((offset + height * scale) / cell)):
        top = max(0, math.ceil((cy * cell - offset) / scale - 0.5))
        bottom = min(height, math.ceil(((cy + 1) * cell - offset) / scale - 0.5))
        for cx in range(math.floor(offset / cell), math.ceil((offset + width * scale) / cell)):
            left = max(0, math.ceil((cx * cell - offset) / scale - 0.5))
            right = min(width, math.ceil(((cx + 1) * cell - offset) / scale - 0.5))
            yield cx, cy, left, top, right, bottom


def _starfield(
    rows: list[dict[int, float]], scale: float, cell: float, chance: float, seed: float,
    offset: float, strength, fade: list[float],
) -> None:
    """Add the shader's ``starfield``: a star in ``chance`` of the cells, most
    of them faint, a bright one with a soft halo. ``strength`` is a number or
    what gives one for a place in design pixels; ``fade`` is by the row."""
    width, height = max(1, round(DESIGN_WIDTH / scale)), len(fade)
    for cx, cy, left, top, right, bottom in _cells(width, height, scale, cell, offset):
        if _hash(cx + seed, cy + seed) < 1.0 - chance:
            continue
        x = (cx + 0.5 + (_hash(cx + seed + 1.7, cy + seed + 1.7) - 0.5) * 0.7) * cell
        y = (cy + 0.5 + (_hash(cx + seed + 9.2, cy + seed + 9.2) - 0.5) * 0.7) * cell
        size = _hash(cx + seed + 4.4, cy + seed + 4.4) ** 3
        core, halo = 0.6 + 0.6 * size, 0.8 + 4.0 * size
        reach = max(core, math.sqrt(halo * 4.6)) if size > 0.05 else core  # the halo down to a hundredth
        gain = strength(x, y) if callable(strength) else strength
        if gain <= 0.002:
            continue
        for row in range(top, bottom):
            dy = (row + 0.5) * scale + offset - y
            if abs(dy) > reach or not fade[row]:
                continue
            lit = rows[row]
            for column in range(left, right):
                dx = (column + 0.5) * scale + offset - x
                if abs(dx) > reach:
                    continue
                distance = math.hypot(dx, dy)
                value = _smooth(core, 0.0, distance) * (0.3 + 0.7 * size)
                value += math.exp(-distance * distance / halo) * 0.3 * size
                if value > 0.003:
                    lit[column] = lit.get(column, 0.0) + value * gain * fade[row]


def _sparkles(
    rows: list[dict[int, float]], scale: float, cell: float, chance: float, seed: float,
    offset: float, strength: float, fade: list[float],
) -> None:
    """Add the shader's ``sparkles``: four-pointed stars, each a concave
    diamond with a small glow in the middle."""
    width, height = max(1, round(DESIGN_WIDTH / scale)), len(fade)
    for cx, cy, left, top, right, bottom in _cells(width, height, scale, cell, offset):
        if _hash(cx + seed, cy + seed) < 1.0 - chance:
            continue
        x = (cx + 0.5 + (_hash(cx + seed + 2.9, cy + seed + 2.9) - 0.5) * 0.5) * cell
        y = (cy + 0.5 + (_hash(cx + seed + 7.3, cy + seed + 7.3) - 0.5) * 0.5) * cell
        size = cell * (0.07 + 0.1 * _hash(cx + seed + 5.5, cy + seed + 5.5))
        gain = strength * (0.55 + 0.45 * _hash(cx + seed + 8.8, cy + seed + 8.8))
        reach, root = size * 1.6, math.sqrt(size)
        for row in range(top, bottom):
            dy = abs((row + 0.5) * scale + offset - y)
            if dy > reach or not fade[row]:
                continue
            lit = rows[row]
            for column in range(left, right):
                dx = abs((column + 0.5) * scale + offset - x)
                if dx > reach:
                    continue
                value = _smooth(0.0, 0.22, 1.0 - (math.sqrt(dx) + math.sqrt(dy)) / root)
                value += math.exp(-(dx * dx + dy * dy) / (size * size * 0.5)) * 0.35
                if value > 0.003:
                    lit[column] = lit.get(column, 0.0) + value * gain * fade[row]


#: The Milky Way lies across this line: through a point at the sky's top, in
#: design pixels, and along a direction; and it is this wide.
_MILKY_AT = 135.0
_MILKY_ACROSS = (0.8, -0.6)
_MILKY_WIDTH = 1800.0


def _night(width: int, height: int, scale: float, scene: Scene):
    """What only a clear night shows, each as rows of ``{column: amount}``:
    the Milky Way's dust, its crowd of faint stars, the sparkles and the stars.
    All of them fade out towards the horizon."""
    seed = scene.seed
    horizon = [_smooth(1.0, 0.3, (row + 0.5) / height) for row in range(height)]
    dust: list[dict[int, float]] = [{} for _ in range(height)]
    crowd: list[dict[int, float]] = [{} for _ in range(height)]
    sparks: list[dict[int, float]] = [{} for _ in range(height)]
    stars: list[dict[int, float]] = [{} for _ in range(height)]

    def band(x: float, y: float) -> float:
        across = (x - _MILKY_AT) * _MILKY_ACROSS[0] + y * _MILKY_ACROSS[1]
        return math.exp(-across * across / _MILKY_WIDTH)

    if scene.milky:
        # A slanted band of dust with a dark lane along it.
        cloud = _fbm(width, height, 0.021 * scale, 0.021 * scale, seed * 2.3, seed * 2.3)
        lanes = _fbm(width, height, 0.034 * scale, 0.034 * scale, seed * 5.1, seed * 5.1)
        for row in range(height):
            if not horizon[row]:
                continue
            y = (row + 0.5) * scale
            gain = 0.25 * scene.milky * horizon[row]
            cloud_row, lane_row, lit = cloud[row], lanes[row], dust[row]
            for column in range(width):
                across = ((column + 0.5) * scale - _MILKY_AT) * _MILKY_ACROSS[0] + y * _MILKY_ACROSS[1]
                wide = math.exp(-across * across / _MILKY_WIDTH)
                if wide < 0.01:
                    continue
                lane = _smooth(0.42, 0.7, lane_row[column]) * math.exp(-across * across / 300.0)
                lit[column] = wide * (0.25 + cloud_row[column]) * (1.0 - 0.75 * lane) * gain
        _starfield(
            crowd, scale, 6.0, 0.55, seed + 8.0, 7.0,
            lambda x, y: band(x - 7.0, y - 7.0) * 0.7 * scene.milky, horizon,
        )
    if scene.sparkle:
        # More of them as the setting grows, the large ones only in its upper
        # half; and they stay in the upper sky, clear of what is laid out below.
        upper = [
            horizon[row] * _smooth(0.66, 0.36, (row + 0.5) / height) * min(1.0, scene.sparkle * 4.0)
            for row in range(height)
        ]
        _sparkles(sparks, scale, 46.0, 0.1 + 0.2 * scene.sparkle, seed + 2.0, 0.0, 1.0, upper)
        large = _smooth(0.5, 1.0, scene.sparkle)
        if large:
            _sparkles(sparks, scale, 78.0, 0.35, seed + 6.0, 23.0, large, upper)
    if scene.stars:
        # A dust of faint stars and a few bright ones.
        _starfield(stars, scale, 13.0, 0.35, seed, 0.0, 0.6 * scene.stars, horizon)
        _starfield(stars, scale, 44.0, 0.4, seed + 3.0, 19.0, scene.stars, horizon)
    return dust, crowd, sparks, stars


def _cloud_body(scene: Scene) -> tuple[float, float]:
    """A cloud's tone at its thin edge, and how much of it its thick middle
    loses: by starlight it is a shape barely lighter than the sky."""
    if scene.moonlit > 0.5:
        return 0.7, 0.2
    dim = 1.0 - 0.32 * scene.rain
    return dim, 0.26 * dim


def _streaks(
    rows: list[dict[int, float]], width: int, scale: float,
    cell_x: float, cell_y: float, seed: float, shift: float, strength: float,
    lines: int = 0, left: float = 0.0, lean: float = 0.2,
) -> None:
    """Add a layer of slanted rain: one random drop per cell of a tall grid.

    A streak is under two pixels wide, so each row visits the grid's columns
    and lights the pixels at the middle of each, not every pixel of the row.

    With ``lines`` the grid's rows repeat after that many, so the picture is
    the same ``lines`` cells further down its slant; ``left`` is where the
    picture's left edge is, in real pixels from the sky's, and ``lean`` how far
    left a streak goes for every pixel it comes down.
    """
    lengths: dict[tuple[int, int], float] = {}  # 0 where the cell has no drop
    reach = 0.9 / scale  # how far from its middle line a streak is seen
    for row, lit in enumerate(rows):
        qy = (row + 0.5) * scale + shift
        slant = qy * lean
        gy = qy / cell_y
        first = math.floor(((left - reach) * scale + slant + shift) / cell_x - 0.5)
        last = math.ceil(((left + width + reach + 1.0) * scale + slant + shift) / cell_x)
        for column in range(first, last):
            fall = gy + _hash(column, seed) * 13.0
            line = math.floor(fall)
            f = fall - line
            if lines:
                line %= lines
            key = (column, line)
            if key not in lengths:
                on = _hash(column + seed, line + seed) >= 0.64
                lengths[key] = 0.35 + 0.5 * _hash(column + seed + 3.3, line + seed + 3.3) if on else 0.0
            length = lengths[key]
            if not length:
                continue
            body = _smooth(0.0, length * 0.6, f) * _smooth(length, length - 0.12, f)
            if not body:
                continue
            # The streak's middle line in real pixels, then the pixels beside it.
            middle = ((column + 0.5) * cell_x - slant - shift) / scale - 0.5 - left
            for x in range(max(0, math.ceil(middle - reach)), min(width, math.floor(middle + reach) + 1)):
                edge = _smooth(0.9, 0.15, abs(x - middle) * scale)
                if edge:
                    lit[x] = lit.get(x, 0.0) + edge * body * strength


def _drops(width: int, height: int, scale: float, seed: float) -> list[dict[int, tuple[float, float]]]:
    """Drops on the glass: per row, ``(drop, shine)`` for the pixels of each."""
    rows: list[dict[int, tuple[float, float]]] = [{} for _ in range(height)]
    cell = 34.0 / scale
    for cy in range(int(height / cell) + 1):
        for cx in range(int(width / cell) + 1):
            if _hash(cx + seed + 20.0, cy + seed + 20.0) < 0.62:
                continue
            radius = 0.05 + 0.08 * _hash(cx + 2.2, cy + 2.2)  # in cells
            x = cx + 0.5 + (_hash(cx + 5.1, cy + 5.1) - 0.5) * 0.6
            y = cy + 0.5 + (_hash(cx + 8.7, cy + 8.7) - 0.5) * 0.6
            reach = radius * cell / 0.85 + 1
            for row in range(max(0, int(y * cell - reach)), min(height, int(y * cell + reach) + 1)):
                dy = (row + 0.5) / cell - y
                for column in range(max(0, int(x * cell - reach)), min(width, int(x * cell + reach) + 1)):
                    dx = (column + 0.5) / cell - x
                    drop = _smooth(radius, radius - 0.03, math.hypot(dx, dy * 0.85))
                    if drop:
                        shine = _smooth(radius * 0.55, 0.0, math.hypot(dx + radius * 0.3, dy + radius * 0.3))
                        rows[row][column] = (drop, shine)
    return rows


#: How much of a cloud strip's width is spent on joining its ends, in pixels.
SEAM = 80
#: The middle of the cloud noise: what its two ends are blended about.
_NOISE_MIDDLE = 0.484


def drifts(scene: Scene) -> bool:
    """Whether the scene's clouds move."""
    return scene.clouds > 0.001


#: How fast the clouds drift, in design pixels a second, by the wind in metres
#: a second: slowly in a calm, and faster the harder it blows, between the
#: points of this table and no faster than its last. When the wind is not
#: known, they drift as they drifted before it set the speed.
CLOUD_SPEEDS = ((0.0, 1.4), (2.0, 9.0), (6.0, 13.0), (12.0, 22.0), (20.0, 36.0), (30.0, 46.0))
CLOUD_SPEED_MOST = CLOUD_SPEEDS[-1][1]
CLOUD_SPEED_UNKNOWN = 4.0
#: A blizzard's clouds go at least this fast, and then this many times as fast
#: again as that.
CLOUD_SPEED_GALE = 22.0
CLOUD_SPEED_GALE_TIMES = 2.0


def _by_wind(table: tuple, wind: float) -> float:
    """A value from ``table``, rows of ``(wind, value)`` from the calmest on,
    for a wind: straight between its rows, and the last row's past the last."""
    for (low, slow), (high, fast) in zip(table, table[1:]):
        if wind <= high:
            return slow + (fast - slow) * (max(wind, low) - low) / (high - low)
    return table[-1][1]


def cloud_speed(scene: Scene) -> float:
    """How fast the scene's clouds drift, in pixels a second, for its wind."""
    speed = CLOUD_SPEED_UNKNOWN if scene.wind is None else _by_wind(CLOUD_SPEEDS, scene.wind)
    return max(speed, CLOUD_SPEED_GALE) * CLOUD_SPEED_GALE_TIMES if scene.gale else speed


#: The sun's rays turn slowly round it, and their beams breathe - wider and
#: narrower - in their own time. The rays are their own layer, drawn again
#: this many times a second, at half the window's size (``sun_rays``).
#: Often enough that their turning and breathing do not step.
RAYS_FPS = 12
#: They are drawn at half the window's size and enlarged: at a third the blocks of the enlarging showed.
RAYS_SCALE = 2
RAYS_TURN_S = 70.0
RAYS_BREATH_S = 14.0
#: How fast the rays fade with distance from the sun: lower, and they reach further.
RAYS_FALLOFF = 0.45
#: How many beams the two waves that make the rays have all the way round the
#: sun (whole numbers, or the pattern would break where it meets itself).
#: Fewer: wider beams.
RAYS_LOBES = (6.0, 11.0)
#: Among the wide beams there are thin ones: this many all the way round, how
#: thin (the power of the wave), and how much of the light they carry.
RAYS_THIN_LOBES = 11.0
RAYS_THIN_POWER = 3.0
RAYS_THIN_SHARE = 0.4


def _ray_pattern(angle: float, seed: float) -> float:
    """How bright the rays are at an angle round the sun, 0 to 1: wide beams
    with thin ones between them."""
    wide = (0.5 + 0.5 * math.sin(angle * RAYS_LOBES[0] + seed)) * (
        0.5 + 0.5 * math.sin(angle * RAYS_LOBES[1] + seed * 2.3 + 1.7)
    )
    thin = (0.5 + 0.5 * math.sin(angle * RAYS_THIN_LOBES + seed * 1.7 + 0.6)) ** RAYS_THIN_POWER
    return min(1.0, wide * (1.0 - RAYS_THIN_SHARE * 0.5) + thin * RAYS_THIN_SHARE)


#: Round the sun there is also a soft disc of light, the rays' own glow: whole
#: out to ``RAYS_HALO_CORE`` (a share of the window's width) and fading away by
#: ``RAYS_HALO_REACH``. Near the top edge it is cut off, as a half circle.
#: ``RAYS_HALO_STRENGTH`` is its opacity at its brightest.
RAYS_HALO_CORE = 0.2
RAYS_HALO_REACH = 0.55
RAYS_HALO_STRENGTH = 0.55


def sun_moves(scene: Scene) -> bool:
    """Whether the scene has the sun's rays, which move (``sun_rays``)."""
    return scene.rays > 0.001


#: The rays' pattern depends on the angle alone, so it is kept as a table of
#: this many steps round the sun (a power of two: the turn wraps with a mask)
#: and only looked up per pixel: the cost of a frame is what lets them be
#: drawn often enough to turn smoothly.
_RAY_STEPS = 4096
_ray_cache: dict = {}


def _ray_pixels(width: int, height: int, scene: Scene, scale: int):
    """What of the rays does not change from frame to frame: for each pixel its
    place round the sun in table steps, and the share of the ray's strength
    that its distance leaves (0 at the sun itself), and the alpha of the soft
    disc of light round the sun. Kept for the last window."""
    key = (width, height, scale, scene.light_x, scene.light_y, scene.seed, scene.sun, scene.rays)
    if _ray_cache.get("key") != key:
        w, h = width // scale, height // scale
        aspect = width / height
        steps, seed = _RAY_STEPS, scene.seed
        places, shares, halos = [], [], []
        glow = scene.sun * scene.rays * RAYS_HALO_STRENGTH * 255.0
        for row in range(h):
            down = (row * scale + scale / 2) / height - scene.light_y
            for column in range(w):
                across = ((column * scale + scale / 2) / width - scene.light_x) * aspect
                distance = math.hypot(across, down)
                places.append(round(math.atan2(down, across) / math.tau * steps))
                halos.append(_smooth(RAYS_HALO_REACH, RAYS_HALO_CORE, distance) * glow)
                shares.append(
                    0.0 if distance <= 0.03
                    else math.exp(-distance * RAYS_FALLOFF) * _smooth(0.03, 0.3, distance) * 255.0
                )
        base = []  # the pattern itself, before the beams are narrowed
        for step in range(steps):
            angle = math.tau * step / steps
            base.append(_ray_pattern(angle, seed))
        _ray_cache.update(key=key, places=places, shares=shares, halos=halos, base=base)
    return _ray_cache["places"], _ray_cache["shares"], _ray_cache["halos"], _ray_cache["base"]


def sun_rays(width: int, height: int, scene: Scene, seconds: float, scale: int = RAYS_SCALE) -> bytes:
    """The sun's rays as they are ``seconds`` into their turn, as RGBA rows of
    the window's size divided by ``scale``: the rays of ``render``, with the
    pattern turned round the sun and its beams narrowed or widened."""
    places, shares, halos, base = _ray_pixels(width, height, scene, scale)
    turn = round(seconds / RAYS_TURN_S * _RAY_STEPS)
    breath = 0.5 + 0.5 * math.sin(math.tau * seconds / RAYS_BREATH_S)
    sharpness = 1.0 + 0.6 * breath  # higher: narrower beams
    strength = scene.sun * scene.rays * 0.95 * (0.85 + 0.15 * breath)
    # The table as it is this moment: the beams' width and strength folded in,
    # and turned, so that a pixel is looked up at its own place.
    mask = _RAY_STEPS - 1
    table = [value ** sharpness * strength for value in base]
    alpha = bytes(
        [
            min(255, int(table[(place - turn) & mask] * share + halo + 0.5))
            for place, share, halo in zip(places, shares, halos)
        ]
    )
    out = bytearray(b"\xff" * (4 * len(alpha)))
    out[3::4] = alpha
    return bytes(out)


def falls(scene: Scene) -> bool:
    """Whether the scene's rain moves (``rain_layers``)."""
    return scene.rain > 0.001


def snows(scene: Scene) -> bool:
    """Whether there is snow falling in the scene (``snow_layers``)."""
    return scene.snow > 0.001


#: The snow's layers, the far ones first: the grid's cell, its seed, its shift
#: and its strength as in the shader; in how many of the grid's cells there is
#: a flake; how fast it falls (design pixels a second); and how it sways - how
#: far either way, how many times a second, and from which moment of the
#: swing. The far flakes are fine and slow; the near ones are large, out of
#: focus, quicker, and swing wider.
#:
#: A layer is one picture, so all its flakes fall as one. The shader has three
#: sizes of flake; here each size is dealt out among two or three layers that
#: fall at different speeds, so that flakes of a size overtake each other, as
#: flakes do. Together a size's layers have as many flakes as the shader's one.
SNOW_LAYERS = (
    (11.0, 0.0, 0.0, 0.4, 0.28, 15.0, (3, 0.11, 0.0)),
    (11.0, 2.3, 23.0, 0.4, 0.27, 25.0, (4, 0.09, 0.52)),
    (19.0, 5.0, 47.0, 0.7, 0.19, 24.0, (5, 0.085, 0.37)),
    (19.0, 7.9, 71.0, 0.7, 0.18, 35.0, (4, 0.1, 0.83)),
    (19.0, 9.4, 97.0, 0.7, 0.18, 47.0, (6, 0.07, 0.14)),
    (37.0, 11.0, 113.0, 0.45, 0.28, 41.0, (8, 0.065, 0.71)),
    (37.0, 14.2, 151.0, 0.45, 0.27, 63.0, (10, 0.055, 0.26)),
)
#: A flake leans this far left for every pixel it comes down; and a layer's
#: picture repeats after this many rows of its grid - which times the cell and
#: the slant is a whole number of pixels, so that it repeats exactly.
SNOW_SLANT = 0.1
_SNOW_LINES = 10
#: As ``SNOW_SLANT`` when the wind is known (``snow_slant``): straight down in a
#: calm, and the harder it blows the more it is carried sideways - not as far
#: as rain, which is heavier to the wind than snow is to the air.
SNOW_SLANTS = ((0.0, 0.0), (2.0, 0.06), (6.0, 0.16), (12.0, 0.35), (20.0, 0.6), (30.0, 0.9))


def snow_slant(scene: Scene) -> float:
    """How far left the scene's snow goes for every pixel it comes down."""
    return SNOW_SLANT if scene.wind is None else _by_wind(SNOW_SLANTS, scene.wind)

#: The snow is moved in this many steps to a pixel, across and down.
SNOW_STEPS = (2, 3)
_SNOW_TINT = (0.95, 0.97, 1.0)


def _flakes(
    rows: list[dict[int, float]], width: int, scale: float, cell: float, seed: float, shift: float,
    strength: float, share: float, lines: int = 0, left: float = 0.0,
    slant: float = 0.1, streak: float = 0.0,
) -> None:
    """Add a layer of snow: one soft round flake in ``share`` of the cells of
    a grid that leans by ``slant``, each somewhere inside its cell. ``lines``
    and ``left`` are as for ``_streaks``. With ``streak`` a flake is drawn out
    that many pixels along its way, as one going fast is seen."""
    height = len(rows)
    way = math.hypot(slant, 1.0)
    way_x, way_y = -slant / way, 1.0 / way
    # A column's flakes are up to thirteen cells higher than their rows say.
    first_row = math.floor((0.5 * scale + shift) / cell) - 1
    last_row = math.ceil(((height + 0.5) * scale + shift) / cell) + 15
    lean = ((height + 0.5) * scale + shift) * slant
    first = math.floor((left * scale + shift) / cell) - 1
    last = math.ceil(((left + width) * scale + shift + lean) / cell) + 1
    for column in range(first, last):
        drop = _hash(column, seed) * 13.0
        for line in range(first_row, last_row):
            name = line % lines if lines else line
            if _hash(column + seed, name + seed) < 1.0 - share:
                continue
            radius = (0.06 + 0.09 * _hash(column + seed + 3.3, name + seed + 3.3)) * cell
            # Where in the grid its middle is, and so where in the picture.
            gx = column + 0.5 + (_hash(column + seed + 1.3, name + seed + 1.3) - 0.5) * 0.7
            gy = line + 0.5 + (_hash(column + seed + 6.1, name + seed + 6.1) - 0.5) * 0.7 - drop
            qy = gy * cell
            y = (qy - shift) / scale
            x = (gx * cell - qy * slant - shift) / scale - left
            if streak:
                radius *= 0.62
            half = streak * (0.6 + 0.8 * _hash(column + seed + 8.2, name + seed + 8.2)) / 2
            reach = (radius + half) / scale
            for row in range(max(0, int(y - reach)), min(height, int(y + reach) + 1)):
                lit = rows[row]
                for at in range(max(0, int(x - reach)), min(width, int(x + reach) + 1)):
                    dx, dy = (at + 0.5 - x) * scale, (row + 0.5 - y) * scale
                    if half:
                        # How far along its way this pixel is, and how far off it.
                        along = max(-half, min(half, dx * way_x + dy * way_y))
                        away = math.hypot(dx - along * way_x, dy - along * way_y)
                        flake = _smooth(radius, radius * 0.25, away) * (1.0 - 0.6 * (along / half) ** 2)
                    else:
                        flake = _smooth(radius, radius * 0.25, math.hypot(dx, dy))
                    if flake > 0.0:
                        lit[at] = lit.get(at, 0.0) + flake * strength


#: A blizzard's layers, the far ones first: the cell, the seed, the shift, the
#: strength and the share of cells as for ``SNOW_LAYERS``; how fast the snow
#: comes down (it goes ``GALE_SLANT`` times as fast sideways); how long it is
#: drawn out; after how many rows of the grid the picture repeats; and from
#: which moment of the gust it goes. There is more snow in the air than in a
#: snowfall, it is finer, and all of it is streaks.
GALE_LAYERS = (
    (13.0, 0.0, 0.0, 0.42, 0.36, 62.0, 5.0, 10, 0.0),
    (13.0, 2.3, 23.0, 0.42, 0.34, 96.0, 7.5, 10, 0.07),
    (21.0, 5.0, 47.0, 0.62, 0.32, 78.0, 8.0, 6, 0.03),
    (21.0, 7.9, 71.0, 0.62, 0.3, 124.0, 11.0, 6, 0.1),
    (34.0, 11.0, 113.0, 0.5, 0.42, 148.0, 16.0, 4, 0.05),
)
#: Blown, the snow goes this far left for every pixel it comes down.
GALE_SLANT = 2.0
#: The gusts: by how much of its speed the snow goes faster and slower, and
#: how many times a second. None: a blizzard that slackens every few seconds
#: looks as if it were stopping, so it blows at one speed.
GALE_GUST = (0.0, 0.16)


def snow_layers(width: int, height: int, scene: Scene) -> list[RainLayer]:
    """The scene's falling snow alone, over ``render(..., streaks=False)``,
    the near layer first, as the rain's are: each a picture to slide down its
    slant and to swing from side to side as it goes (``fall_place``). In a
    blizzard they are driven nearly flat, and fast."""
    scale = DESIGN_WIDTH / width
    keep = (1.0 - scene.shade) * 255.0
    tint = bytes(int(part * keep + 0.5) for part in _SNOW_TINT)
    if scene.gale:
        table = [
            (cell, seed, shift, strength, share, speed, streak, lines, GALE_SLANT, (0, 0.0, 0.0), (1, 1),
             (GALE_GUST[0], GALE_GUST[1], moment))
            for cell, seed, shift, strength, share, speed, streak, lines, moment in GALE_LAYERS
        ]
    else:
        table = [
            (cell, seed, shift, strength, share, speed, 0.0, _SNOW_LINES, SNOW_SLANT, sway, SNOW_STEPS, (0.0, 0.0, 0.0))
            for cell, seed, shift, strength, share, speed, sway in SNOW_LAYERS
        ]
    layers = []
    for cell, seed, shift, strength, share, speed, streak, lines, slant, sway, steps, gust in table:
        reach = sway[0]
        period = round(lines * cell / scale)
        if not scene.gale:  # as the rain's: a whole number of pixels sideways over a period
            slant = round(period * snow_slant(scene)) / period
        lean = math.ceil(period * slant)
        wide = width + lean + 2 * reach
        rows: list[dict[int, float]] = [{} for _ in range(height + period)]
        _flakes(
            rows, wide, scale, cell, scene.seed + seed, shift, strength * scene.snow, share,
            lines, -lean - reach, slant, streak,
        )
        empty = bytes(4 * wide)
        out = []
        for lit in rows:
            if not lit:
                out.append(empty)
                continue
            line = bytearray(empty)
            for column, flake in lit.items():
                at = column * 4
                line[at:at + 3] = tint
                line[at + 3] = min(255, int(flake * 255.0 + 0.5))
            out.append(bytes(line))
        layers.append(RainLayer(
            wide, height + period, b"".join(out), period, speed / scale, (), slant, sway, steps, tint, gust,
        ))
    return layers[::-1]


#: The snow the wind carries along in a blizzard, besides the flakes: veils of
#: it, streaming across the whole window. How fast they go (design pixels a
#: second, to the left), and how much they hide at their thickest.
VEIL_SPEED = 240.0
VEIL_DEPTH = 0.4


def gale_veil(width: int, height: int, scene: Scene, period: int) -> bytes:
    """A blizzard's veils of blown snow, as ``period`` x ``height`` rows of
    RGBA: long wisps lying along the wind, thicker lower down where the snow
    is lifted from the ground. Like the clouds' strip its ends meet, so that
    two of it side by side go round without a join (``veil_place``)."""
    scale = DESIGN_WIDTH / width
    keep = 1.0 - scene.shade
    lit = 0.6 if scene.moonlit > 0.5 else 1.0
    tint = bytes(int(part * lit * keep * 255.0 + 0.5) for part in _SNOW_TINT)
    noise = _fbm(period + SEAM, height, 0.0052 * scale, 0.034 * scale, scene.seed * 2.1 + 70.0, scene.seed + 50.0, 4)
    depth = VEIL_DEPTH * scene.gale * 255.0
    rows = []
    for row in range(height):
        line = noise[row]
        low = 0.55 + 0.45 * (row + 0.5) / height
        joined = []
        for column in range(SEAM):
            t = column / SEAM
            lift = 1.0 / math.hypot(t, 1.0 - t)
            joined.append(0.47 + lift * ((line[column] - 0.47) * t + (line[column + period] - 0.47) * (1.0 - t)))
        joined += line[SEAM:period]
        rows.append(bytes(int(_smooth(0.4, 0.72, value) * low * depth + 0.5) for value in joined))
    return tinted(tint, b"".join(rows))


def veil_place(seconds: float, period: int, scale: float = 1.0) -> int:
    """How far left the first of the two veils is by now; the second is a
    ``period`` to its right."""
    return -(int(seconds * VEIL_SPEED / scale) % period)


#: The rain's two layers, the near one and the far: the grid's cell and its
#: seed, shift and strength as in the shader; then how many of the grid's rows
#: a layer's picture repeats after, and how fast it falls, in design pixels a
#: second. The far one is fainter, finer and slower. A layer's rows times its
#: cell's height times the slant is a whole number of pixels, so that where
#: the picture repeats it does so exactly.
RAIN_LAYERS = (
    (9.0, 46.0, 0.0, 0.0, 0.24, 5, 330.0),
    (6.0, 30.0, 7.0, 31.0, 0.1, 9, 210.0),
)
#: A streak leans this far left for every pixel it comes down: this much when
#: the wind is not known, and otherwise by the wind (``rain_slant``) - straight
#: down in a calm, and the harder it blows the flatter the rain goes.
RAIN_SLANT = 0.2
RAIN_SLANTS = ((0.0, 0.03), (2.0, 0.1), (6.0, 0.22), (12.0, 0.42), (20.0, 0.7), (30.0, 1.0))


def rain_slant(scene: Scene) -> float:
    """How far left the scene's rain goes for every pixel it comes down."""
    return RAIN_SLANT if scene.wind is None else _by_wind(RAIN_SLANTS, scene.wind)
#: A streak is light added to the sky; laid over it as a translucent pixel it
#: needs this much opacity for its strength to look the same.
_RAIN_OPACITY = 2.0
_RAIN_TINT = (0.85, 0.92, 1.0)


class RainLayer(NamedTuple):
    """A layer of rain to slide down its slant over the sky."""

    width: int
    height: int
    pixels: bytes  # RGBA rows
    period: int  # the picture is the same this many pixels further down
    speed: float  # pixels a second
    #: Where each streak's lower end is before the layer has fallen at all, as
    #: ``(x, y)`` from the sky's corner, with ``y`` inside the first period.
    heads: tuple = ()
    #: How far left it goes for every pixel it comes down.
    slant: float = 0.2
    #: Snow does not come straight down: the whole layer swings from side to
    #: side as it falls - this many pixels either way, this many times a
    #: second, and from this moment of the swing.
    sway: tuple = (0, 0.0, 0.0)
    #: In how many steps to a pixel it is moved, across and down: the rain is
    #: fast and is put at whole pixels, but snow drifts, and a slow thing put
    #: at whole pixels is seen to shake (``fall_place``, ``layer_phases``).
    steps: tuple = (1, 1)
    #: The colour of what is in it, for the pictures of it between two pixels.
    tint: bytes = b""
    #: The wind comes in gusts: the layer goes faster and slower by this share
    #: of its speed, this many times a second, from this moment of the gust.
    gust: tuple = (0.0, 0.0, 0.0)


def rain_layers(width: int, height: int, scene: Scene) -> list[RainLayer]:
    """The scene's streaks of rain alone, over ``render(..., streaks=False)``.

    A layer is taller than the sky by its ``period`` and wider by what a
    streak leans over that far. Put at ``rain_place`` it covers the sky, and
    moving it only carries each streak along its own line.
    """
    scale = DESIGN_WIDTH / width
    keep = (1.0 - scene.shade) * 255.0
    tint = bytes(int(part * keep + 0.5) for part in _RAIN_TINT)
    layers = []
    wanted = rain_slant(scene)
    for cell_x, cell_y, seed, shift, strength, lines, speed in RAIN_LAYERS:
        period = round(lines * cell_y / scale)
        # Over a period a streak goes a whole number of pixels sideways, so that
        # where the picture repeats it does so exactly: the slant is made so.
        slant = round(period * wanted) / period
        lean = math.ceil(period * slant)
        rows: list[dict[int, float]] = [{} for _ in range(height + period)]
        _streaks(
            rows, width + lean, scale, cell_x, cell_y, scene.seed + seed, shift,
            strength * scene.rain, lines, -lean, slant,
        )
        empty = bytes(4 * (width + lean))
        out = []
        for lit in rows:
            if not lit:
                out.append(empty)
                continue
            line = bytearray(empty)
            for column, streak in lit.items():
                at = column * 4
                line[at:at + 3] = tint
                line[at + 3] = min(255, int(streak * _RAIN_OPACITY * 255.0 + 0.5))
            out.append(bytes(line))
        heads = []
        own = scene.seed + seed
        reach = (width + (height + period) * slant + 2.0) * scale + shift
        for column in range(math.floor(shift / cell_x) - 1, math.ceil(reach / cell_x) + 1):
            for line in range(lines):
                if _hash(column + own, line + own) < 0.64:
                    continue
                length = 0.35 + 0.5 * _hash(column + own + 3.3, line + own + 3.3)
                # Just short of the streak's very end, where it is still seen.
                fall = line + length - 0.08 - _hash(column, own) * 13.0
                y = ((fall * cell_y - shift) / scale - 0.5) % period
                aside = ((y + 0.5) * scale + shift) * slant
                heads.append((((column + 0.5) * cell_x - aside - shift) / scale - 0.5, y))
        layers.append(
            RainLayer(width + lean, height + period, b"".join(out), period, speed / scale, tuple(heads), slant)
        )
    return layers


#: How plainly the wet glass is drawn: it is there for the mood of it, and
#: is not to be looked at.
GLASS_STRENGTH = 0.34


#: The drops on the glass, a kind to a line: the grid's cell, in how many of
#: its cells there is a drop, and the smallest and the largest radius - most
#: are nearer the smallest. Large ones and ones of middling size, and no mist
#: of tiny ones between: at this size that is not water, it is noise.
_GLASS = (
    (48.0, 0.3, 5.0, 11.5),
    (21.0, 0.26, 2.6, 5.0),
)
#: A drop is felt this many radii out, so that two near each other run together.
_GLASS_REACH = 1.6
#: Its outline wanders by up to this many pixels.
_GLASS_WANDER = 5.0


def _wet(width: int, height: int, scale: float, seed: float) -> tuple[list[list[float]], list[list[float]]]:
    """The water on the glass at every pixel: how much of it there is nearby,
    and from that whether the pixel is in a drop - from 0 to 1 across its edge.

    Each drop adds to the pixels round it, the more the nearer, and where that
    comes to enough there is water: so drops close to each other join into one
    with a waist. They are not discs either - each is a little longer one way,
    and the glass is looked at through a slow ripple that bends every outline.
    Here and there is a lane down the glass where a drop ran: it took most of
    the others with it, and the few left in it are long.
    """
    # The ripple, and the lanes: narrow, and many times longer than wide.
    bend_x = _fbm(width, height, 0.09 * scale, 0.09 * scale, seed * 3.1 + 40.0, seed * 1.3 + 40.0, 2)
    bend_y = _fbm(width, height, 0.09 * scale, 0.09 * scale, seed * 2.7 + 90.0, seed * 4.9 + 90.0, 2)
    lanes = _fbm(width, height, 0.085 * scale, 0.005 * scale, seed * 1.9 + 60.0, seed + 60.0, 2)
    near = [[0.0] * width for _ in range(height)]
    wander = _GLASS_WANDER / 0.75  # the noise is within 0.75 of its span
    for kind, (cell, chance, small, large) in enumerate(_GLASS):
        own = seed + 20.0 + kind * 11.3
        offset = kind * 17.0
        for cx, cy, _left, _top, _right, _bottom in _cells(width, height, scale, cell, offset):
            if _hash(cx + own, cy + own) < 1.0 - chance:
                continue
            radius = small + (large - small) * _hash(cx + own + 2.2, cy + own + 2.2) ** 1.8
            x = (cx + _hash(cx + own + 5.1, cy + own + 5.1)) * cell - offset
            y = (cy + _hash(cx + own + 8.7, cy + own + 8.7)) * cell - offset
            wide = 1.0 + 0.5 * (_hash(cx + own + 4.1, cy + own + 4.1) - 0.5)
            tall = 1.0 + 0.6 * _hash(cx + own + 6.3, cy + own + 6.3)  # a drop hangs
            column, row = int(x / scale), int(y / scale)
            if 0 <= row < height and 0 <= column < width and row > height * 0.12:
                if lanes[row][column] > 0.55:
                    if _hash(cx + own + 9.9, cy + own + 9.9) < 0.75:
                        continue  # washed away
                    wide, tall = wide * 0.75, tall * 2.4
            reach_x, reach_y = radius * wide * _GLASS_REACH, radius * tall * _GLASS_REACH
            for row in range(
                max(0, int((y - reach_y - _GLASS_WANDER) / scale)),
                min(height, int((y + reach_y + _GLASS_WANDER) / scale) + 1),
            ):
                line, shift_x, shift_y = near[row], bend_x[row], bend_y[row]
                py = (row + 0.5) * scale - y
                for column in range(
                    max(0, int((x - reach_x - _GLASS_WANDER) / scale)),
                    min(width, int((x + reach_x + _GLASS_WANDER) / scale) + 1),
                ):
                    dx = ((column + 0.5) * scale - x + (shift_x[column] - 0.375) * wander) / reach_x
                    dy = (py + (shift_y[column] - 0.375) * wander) / reach_y
                    away = dx * dx + dy * dy
                    if away < 1.0:
                        line[column] += (1.0 - away) ** 2
    return near, [[_smooth(0.36, 0.52, value) for value in line] for line in near]


def glass_drops(width: int, height: int, scene: Scene) -> bytes:
    """The rain on the window's glass, as RGBA rows to lay over all of the sky
    - its clouds and its falling rain too: they are behind the glass.

    A drop is a small lens, and what is seen in it is upside down: so its
    upper edge is darker than what is behind it and its lower edge lighter,
    and its middle hardly differs. A pixel of the layer is black or white, the
    more opaque the darker or the lighter it makes what is under it.
    """
    scale = DESIGN_WIDTH / width
    keep = 1.0 - scene.shade
    light = _unit(scene.light)
    white = bytes(int((part + (1.0 - part) * 0.6) * keep * 255.0 + 0.5) for part in light)
    glow = 0.6 if scene.moonlit > 0.5 else 1.0  # there is less to glint by night
    strength = GLASS_STRENGTH * scene.rain * 255.0
    near, water = _wet(width, height, scale, scene.seed)
    rows = []
    for row in range(height):
        line = bytearray(4 * width)
        here, mass = water[row], near[row]
        up, down = max(0, row - 1), min(height - 1, row + 1)
        for column in range(width):
            wet = here[column]
            edge = water[down][column] - water[up][column]
            if not wet and not edge:
                continue
            left, right = max(0, column - 1), min(width - 1, column + 1)
            # Its edge, and across the whole of a large one the slope of its dome.
            dome = min(1.5, near[down][column]) - min(1.5, near[up][column])
            net = -0.5 * edge - 0.14 * (here[right] - here[left]) - 1.1 * dome * wet + 0.04 * wet
            at = column * 4
            if net > 0.0:
                line[at:at + 3] = white
                line[at + 3] = min(125, int(net * glow * strength + 0.5))
            else:
                line[at + 3] = min(105, int(-net * strength + 0.5))
        rows.append(bytes(line))
    return b"".join(rows)


def frosted(
    width: int, still: bytes, box: tuple[int, int, int, int], over: list[tuple[bytes, int]], blur: int
) -> bytes:
    """What is behind a pane of frosted glass, as RGB rows the size of ``box``
    (``x, y, width, height``): the sky ``still`` (rows ``width`` wide) with the
    layers ``over`` it - each RGBA rows and how wide they are - all of it
    blurred until nothing in it has an outline. The clouds and the drops on
    the window are still there, as lighter and darker places.

    The blur is a box of ``blur`` pixels each way, run twice: near enough to
    the bell-shaped one, and a sum that slides along a row costs the same
    whatever its width. And it is done on the picture at half its size, which
    is a quarter of the work: blurred this much, nobody can tell.
    """
    x, y, wide, tall = box
    height = len(still) // (width * 3)
    # With a margin to blur in from, where there is sky for it.
    left, top = max(0, x - 2 * blur), max(0, y - 2 * blur)
    right, bottom = min(width, x + wide + 2 * blur), min(height, y + tall + 2 * blur)
    span = right - left
    rows = []
    for row in range(top, bottom):
        line = list(still[(row * width + left) * 3:(row * width + right) * 3])
        for pixels, stride in over:
            start = (row * stride + left) * 4
            layer = pixels[start:start + span * 4]
            for column in range(span):
                alpha = layer[column * 4 + 3]
                if alpha:
                    at, part = column * 3, alpha / 255.0
                    for channel in range(3):
                        line[at + channel] += (layer[column * 4 + channel] - line[at + channel]) * part
        rows.append(line)

    def smear(lines: list[list[float]], step: int) -> list[list[float]]:
        """Each value as the mean of those within ``blur`` of it along the line."""
        out = []
        for line in lines:
            count = len(line) // step
            mixed = [0.0] * len(line)
            for channel in range(step):
                values = line[channel::step]
                total = sum(values[:blur + 1])
                size = min(count, blur + 1)
                for at in range(count):
                    mixed[at * step + channel] = total / size
                    if at + blur + 1 < count:
                        total += values[at + blur + 1]
                        size += 1
                    if at - blur >= 0:
                        total -= values[at - blur]
                        size -= 1
            out.append(mixed)
        return out

    # Halved: every two pixels by two as their mean.
    if len(rows) % 2:
        rows.append(rows[-1])
    small = []
    for upper, lower in zip(rows[0::2], rows[1::2]):
        if span % 2:
            upper, lower = upper + upper[-3:], lower + lower[-3:]
        small.append([
            (upper[at] + upper[at + 3] + lower[at] + lower[at + 3]) * 0.25
            for pixel in range(0, len(upper), 6) for at in (pixel, pixel + 1, pixel + 2)
        ])
    blur = max(1, blur // 2)
    for _ in range(2):
        small = smear(small, 3)
        # Down the columns: turn it on its side, smear, and turn it back.
        columns = smear([list(column) for column in zip(*small)], 1)
        small = [list(row) for row in zip(*columns)]
    out = []
    for row in range(y, y + tall):
        line = bytes(min(255, max(0, int(value + 0.5))) for value in small[(row - top) // 2])
        # Each pixel of the small one twice over.
        doubled = bytearray(len(line) * 2)
        for channel in range(3):
            doubled[channel::6] = line[channel::3]
            doubled[channel + 3::6] = line[channel::3]
        out.append(bytes(doubled[(x - left) * 3:(x - left + wide) * 3]))
    return b"".join(out)


def rain_hits(layer: RainLayer, level: float) -> list[tuple[float, float]]:
    """When and where a layer's streaks come down on a horizontal line
    ``level`` pixels below the sky's top: each as how far the layer has fallen
    by then, within its period, and the place along the line. In that order."""
    return sorted(
        ((level - y) % layer.period, x - (level - y) * layer.slant) for x, y in layer.heads
    )


#: Lightning: there is one flash in every stretch of this many seconds, at a
#: moment of its own, so they come unevenly - two to ten seconds apart.
FLASH_EVERY = 6.0
#: A flash as (until this many seconds in, how bright): the stroke, the dark
#: after it, the second stroke that most flashes have, and its light dying away.
_FLASH = ((0.07, 1.0), (0.15, 0.2), (0.28, 0.8))
_FLASH_FADE = 0.3
#: How many pictures of a flash there are, from the faintest to the full one.
FLASH_STEPS = 5
_FLASH_TINT = (0.84, 0.89, 1.0)


def flash_level(seconds: float, seed: float = 0.0) -> float:
    """How bright the lightning is this long after the window was opened:
    0 nearly always, and for under a second at a time up to 1."""
    stretch = math.floor(seconds / FLASH_EVERY)
    since = seconds - stretch * FLASH_EVERY - (0.3 + _hash(stretch + 3.1, seed + 1.9) * (FLASH_EVERY - 1.3))
    if since < 0.0:
        return 0.0
    single = _hash(stretch + 7.7, seed + 5.3) < 0.3
    for until, level in _FLASH[:1] if single else _FLASH:
        if since < until:
            return level
    left = 1.0 - (since - (_FLASH[0][0] if single else _FLASH[-1][0])) / _FLASH_FADE
    return max(0.0, left) * 0.5


def flash_step(seconds: float, scene: Scene) -> int:
    """Which of ``flashes`` to show now, counted from 1; 0 for none."""
    if not scene.lightning:
        return 0
    return math.ceil(flash_level(seconds, scene.seed) * scene.lightning * FLASH_STEPS - 0.001)


def flashes(width: int, height: int, scene: Scene) -> list[bytes]:
    """The lightning's light as ``FLASH_STEPS`` pictures of RGBA rows, each
    brighter than the one before: laid over the sky and its clouds, under the
    rain. It is brightest in the clouds at the top and to one side of them,
    and reaches the bottom of the window faintly."""
    tint = bytes(int(part * 255.0 + 0.5) for part in _FLASH_TINT)
    at = 0.25 + 0.5 * _hash(scene.seed + 2.2, scene.seed + 6.6)  # where it struck, across the sky
    glow = []
    for row in range(height):
        v = (row + 0.5) / height
        down = 0.1 + 0.5 * (1.0 - v) ** 1.6
        line = []
        for column in range(width):
            away = math.hypot(((column + 0.5) / width - at) * 0.9, v * 0.8)
            line.append(down + 0.4 * math.exp(-away * away * 9.0))
        glow.append(line)
    pictures = []
    for step in range(1, FLASH_STEPS + 1):
        level = step / FLASH_STEPS * 255.0
        pictures.append(b"".join(
            b"".join(tint + bytes((min(255, int(value * level)),)) for value in line) for line in glow
        ))
    return pictures


#: The snow lying on a ledge: how deep it would get at its deepest (design
#: pixels), and how much of that has gathered - it lies as it has come to lie,
#: and does not grow while it is looked at.
SNOW_CAP = 13.0
CAP_GATHERED = 0.7
#: It falls away to nothing over this many pixels at the ledge's ends: a long, soft
#: slope, not an edge.
_CAP_ENDS = 22.0


def snow_cap(
    width: int, scene: Scene, scale: float = 1.0, gathered: float = CAP_GATHERED
) -> tuple[int, int, bytes]:
    """The snow lying on a ledge ``width`` pixels long, as its width, its
    height and RGBA rows, to be put with its bottom edge on the ledge.

    It lies in drifts - deeper here, shallower there, by a slow noise along
    the ledge - over an even dusting; the more of it has ``gathered``, the
    more the drifts stand out. Its top is the snow's own white, by the light
    there is; lower down it is in its own shade.
    """
    keep = 1.0 - scene.shade
    light = _unit(scene.light)
    # By night it is lit by little, and is the colour of that.
    lit = 0.62 if scene.moonlit > 0.5 else 1.0
    top = [(tint + (part - tint) * (1.0 - lit) * 0.6) * lit * keep for tint, part in zip(_SNOW_TINT, light)]
    shade = [top[0] * 0.78, top[1] * 0.82, top[2] * 0.9]
    drifts = _fbm(width, 1, 0.036 * scale, 1.0, scene.seed * 1.7 + 11.0, scene.seed + 4.0, 2)[0]
    bumps = _fbm(width, 1, 0.12 * scale, 1.0, scene.seed * 2.9 + 31.0, scene.seed + 8.0, 2)[0]
    height = math.ceil(SNOW_CAP / scale) + 2
    deep = []
    for column in range(width):
        ends = _smooth(0.0, _CAP_ENDS / scale, min(column + 0.5, width - column - 0.5))
        drift = min(1.0, max(0.0, (drifts[column] - 0.22) / 0.42))
        # An even dusting, and the drifts that come of it as it gathers.
        lies = 0.3 + 0.7 * drift * gathered + 0.045 * (bumps[column] - 0.375)
        deep.append(max(0.0, SNOW_CAP / scale * gathered ** 0.8 * lies * ends))
    rows = bytearray()
    for row in range(height):
        under = height - row - 0.5  # how far over the ledge this row is
        for column in range(width):
            depth = deep[column]
            cover = min(1.0, max(0.0, depth - under + 0.5))  # a soft top edge
            if cover <= 0.0:
                rows += b"\0\0\0\0"
                continue
            low = _smooth(0.5, max(2.5, depth), depth - under) * 0.85  # how far down in it
            for a, b in zip(top, shade):
                rows.append(min(255, int((a + (b - a) * low) * 255.0 + 0.5)))
            rows.append(int(cover * 255.0 + 0.5))
    return width, height, bytes(rows)


def fall_place(layer: RainLayer, seconds: float) -> tuple[int, int, int]:
    """Where a layer's top left corner is after falling for ``seconds``, and
    which of its pictures (``layer_phases``) is to be shown there: the layer
    is at a place between pixels, and the picture is of it moved on by the
    part of a pixel that the corner is short of that place."""
    across, down = layer.steps
    if across == down == 1:
        return (*rain_place(layer, seconds), 0)
    fallen = _gusted(layer, seconds) * layer.speed % layer.period
    reach, rate, phase = layer.sway
    x = -fallen * layer.slant + reach * math.sin(math.tau * (rate * seconds + phase)) - reach
    y = fallen - layer.period
    left, top = math.floor(x), math.floor(y)
    return left, top, min(down - 1, int((y - top) * down)) * across + min(across - 1, int((x - left) * across))


#: Every byte as so many parts of it out of ``index`` of the table's steps.
_SHARES: dict[tuple[int, int], bytes] = {}


def _share(part: int, of: int) -> bytes:
    if (part, of) not in _SHARES:
        _SHARES[part, of] = bytes(value * part // of for value in range(256))
    return _SHARES[part, of]


def _between(here: bytes, before: bytes, part: int, of: int) -> bytes:
    """Two rows of bytes mixed, ``part`` in ``of`` of the second: all of it in
    three strokes - each scaled by a table, and the two added as the two huge
    numbers they also are, which never carry from one byte into the next."""
    if not part:
        return here
    mixed = int.from_bytes(here.translate(_share(of - part, of)), "big")
    mixed += int.from_bytes(before.translate(_share(part, of)), "big")
    return mixed.to_bytes(len(here), "big")


def layer_phases(layer: RainLayer) -> list[bytes]:
    """A layer's picture at every place between two pixels that it is put at,
    as RGBA rows: the picture moved right by each part of a pixel, for each
    part of a pixel it is moved down (``fall_place`` says which one to show).
    Moved by part of a pixel, each pixel is that much of its neighbour."""
    across, down = layer.steps
    width = layer.width
    alpha = layer.pixels[3::4]
    out = []
    for lower in range(down):
        rows = _between(alpha, bytes(width) + alpha[:-width], lower, down)
        for right in range(across):
            out.append(tinted(layer.tint, _between(rows, b"\0" + rows[:-1], right, across)))
    return out


def rain_place(layer: RainLayer, seconds: float) -> tuple[int, int]:
    """Where a layer's top left corner is after falling for ``seconds``."""
    fallen = int(_gusted(layer, seconds) * layer.speed) % layer.period
    reach, rate, phase = layer.sway
    swing = round(reach * math.sin(math.tau * (rate * seconds + phase))) - reach if reach else 0
    return -round(fallen * layer.slant) + swing, fallen - layer.period


def _gusted(layer: RainLayer, seconds: float) -> float:
    """The time a layer has fallen for, as its gusts make it: now ahead of the
    clock and now behind, and never going back."""
    share, rate, phase = layer.gust
    if not share:
        return seconds
    turn = math.tau * rate
    return seconds + share / turn * (math.sin(turn * seconds + math.tau * phase) - math.sin(math.tau * phase))


def cloud_strips(width: int, height: int, scene: Scene, period: int, phases: int = 1) -> list[bytes]:
    """The scene's clouds alone, as ``period`` x ``height`` rows of RGBA bytes.

    It is what ``render`` lays over the sky, kept apart so that it can slide:
    over ``render(..., clouds=False)`` it gives the same picture. ``width`` is
    the window's, for the scale. The strip's ends meet - its first ``SEAM``
    pixels fade from the noise that follows its last ones - so two copies side
    by side go round without a join.

    There are ``phases`` of it, each the one before moved right by a ``phases``-th
    of a pixel: a strip can only be put at a whole pixel, and a pixel at a
    time the clouds would be seen to step.
    """
    scale = DESIGN_WIDTH / width
    cloud = _unit(scene.cloud)
    noise = _cloud_noise(period + SEAM, height, scale, scene.seed)
    threshold = 0.8 - 0.5 * scene.clouds
    thin, lost = _cloud_body(scene)
    tone = (1.0 - scene.shade) * 255.0
    # A cloud's pixel depends only on how far the noise is over the threshold,
    # so the pixels are a table by that, in steps of a thousandth; the noise
    # stays well inside -1.5 .. 1.5, and under zero there is no cloud.
    steps, low = 1000, 1.5
    table = [bytes(4)] * int(low * steps + 1)
    for step in range(1, int(low * steps) + 1):
        over = step / steps
        body = (thin - lost * _smooth(0.0, 0.55, over)) * tone
        table.append(bytes((
            int(cloud[0] * body + 0.5), int(cloud[1] * body + 0.5), int(cloud[2] * body + 0.5),
            int(0.9 * 0.78 * _smooth(0.0, 0.22, over) * 255.0 + 0.5),
        )))
    # Two noises mixed are flatter than either; the last factor undoes that.
    joins = []
    for column in range(SEAM):
        t = column / SEAM
        joins.append((t, 1.0 - t, 1.0 / math.hypot(t, 1.0 - t)))
    strips: list[list[bytes]] = [[] for _ in range(phases)]
    for row in range(height):
        line = noise[row]
        lean = (0.45 - (row + 0.5) / height) * 0.3 - threshold + low
        joined = [
            (_NOISE_MIDDLE + lift * ((line[column] - _NOISE_MIDDLE) * own + (line[column + period] - _NOISE_MIDDLE) * other) + lean) * steps
            for column, (own, other, lift) in enumerate(joins)
        ]
        joined += [(value + lean) * steps for value in line[SEAM:period]]
        before = joined[-1:] + joined[:-1]  # each pixel's neighbour on the left, round the join
        strips[0].append(b"".join([table[int(value)] for value in joined]))
        for phase in range(1, phases):
            part = phase / phases
            strips[phase].append(
                b"".join([table[int(a + (b - a) * part)] for a, b in zip(joined, before)])
            )
    return [b"".join(rows) for rows in strips]


def render(
    width: int, height: int, scene: Scene, clouds: bool = True, streaks: bool = True, glass: bool = True,
    rays: bool = True,
) -> bytes:
    """The sky as ``width`` x ``height`` rows of RGB bytes; without its clouds
    when they are to drift over it (``cloud_strips``), without its streaks of
    rain or its snow when they are to fall (``rain_layers``, ``snow_layers``),
    and without the mockup's few
    drops on the glass when ``glass_drops`` is to be laid over it all."""
    scale = DESIGN_WIDTH / width
    aspect = width / height
    light = _unit(scene.light)
    cloud = _unit(scene.cloud)
    backdrop = _backdrop(scene, height)
    seed = scene.seed

    noise = _cloud_noise(width, height, scale, seed) if clouds and scene.clouds > 0.001 else None
    threshold = 0.8 - 0.5 * scene.clouds
    thin, lost = _cloud_body(scene)
    moonlit = scene.moonlit > 0.5
    stars = _stars(width, height, scale, scene) if scene.stars and not moonlit else None
    night = _night(width, height, scale, scene) if moonlit else None
    milky_tint = [a + (b - a) * 0.35 for a, b in zip(light, (1.0, 0.84, 0.92))]
    spark_tint = [(a + 1.0) * 0.5 for a in light]
    star_tint = [1.0 + (a - 1.0) * 0.4 for a in light]
    rain = drops = None
    if scene.rain:
        if streaks:
            rain = [{} for _ in range(height)]
            for cell_x, cell_y, offset, shift, strength, _lines, _speed in RAIN_LAYERS:
                _streaks(rain, width, scale, cell_x, cell_y, seed + offset, shift, strength * scene.rain, lean=rain_slant(scene))
        if glass:
            drops = _drops(width, height, scale, seed)
    snow = None
    if scene.snow and streaks:
        snow = [{} for _ in range(height)]
        if scene.gale:
            for cell, offset, shift, strength, share, _speed, streak, _lines, _moment in GALE_LAYERS:
                _flakes(
                    snow, width, scale, cell, seed + offset, shift, strength * scene.snow, share,
                    slant=GALE_SLANT, streak=streak,
                )
        else:
            for cell, offset, shift, strength, share, _speed, _sway in SNOW_LAYERS:
                _flakes(snow, width, scale, cell, seed + offset, shift, strength * scene.snow, share)

    sun, rays, moon = scene.sun, (scene.rays * 0.95 if rays else 0.0), scene.moon
    sun_wash = scene.wash
    moon_radius = 0.062
    keep = 1.0 - scene.shade
    grain = random.Random(int(seed)).random
    exp, hypot, atan2, sin = math.exp, math.hypot, math.atan2, math.sin
    # The light's distance along a row: the horizontal part does not change.
    across = [((column + 0.5) / width - scene.light_x) * aspect for column in range(width)]
    pixels = bytearray(width * height * 3)
    at = 0
    for row in range(height):
        v = (row + 0.5) / height
        down = v - scene.light_y
        base_r, base_g, base_b = backdrop[row]
        noise_row = noise[row] if noise else None
        lean = (0.45 - v) * 0.3 - threshold  # the clouds gather at the top
        star_row = stars[row] if stars else None
        dust_row, crowd_row, spark_row, lit_row = (layer[row] for layer in night) if night else (None,) * 4
        nightly = dust_row or crowd_row or spark_row or lit_row
        rain_row = rain[row] if rain else None
        snow_row = snow[row] if snow else None
        drop_row = drops[row] if drops else None
        for column in range(width):
            dx = across[column]
            distance = hypot(dx, down)
            # Sun or moon: a glow and soft rays fanning out of it.
            shine = (exp(-distance * 2.6) * 0.5 + exp(-distance * 9.0) * 0.7) * sun
            if rays and distance > 0.03:
                angle = atan2(down, dx)
                ray = _ray_pattern(angle, seed)
                shine += ray ** 1.0 * exp(-distance * RAYS_FALLOFF) * _smooth(0.03, 0.3, distance) * rays
            if sun_wash:
                shine += sun_wash * exp(-distance * 0.8)
            r = base_r + light[0] * shine * (1.0 - base_r)
            g = base_g + light[1] * shine * (1.0 - base_g)
            b = base_b + light[2] * shine * (1.0 - base_b)
            if star_row:
                star = star_row.get(column)
                if star:
                    r += star
                    g += star
                    b += star
            if nightly:
                # A cloud puts the night's lights out.
                clear = 1.0
                if noise_row and noise_row[column] + lean > 0.0:
                    clear -= _smooth(0.0, 0.22, noise_row[column] + lean)
                if clear:
                    amount = dust_row.get(column)
                    if amount:
                        amount *= clear
                        r += milky_tint[0] * amount
                        g += milky_tint[1] * amount
                        b += milky_tint[2] * amount
                    amount = crowd_row.get(column)
                    if amount:
                        amount *= clear
                        r += amount
                        g += amount
                        b += amount
                    amount = spark_row.get(column)
                    if amount:
                        amount = min(1.0, amount) * clear
                        r += (spark_tint[0] - r) * amount
                        g += (spark_tint[1] - g) * amount
                        b += (spark_tint[2] - b) * amount
                    amount = lit_row.get(column)
                    if amount:
                        amount *= clear
                        r += star_tint[0] * amount
                        g += star_tint[1] * amount
                        b += star_tint[2] * amount
            if moon and distance < moon_radius + 0.004:
                # Crescent: a disc with a shifted disc cut out of it.
                disc = _smooth(moon_radius + 0.004, moon_radius - 0.004, distance)
                edge = moon_radius * 0.86
                cut = _smooth(edge - 0.004, edge + 0.004, hypot(dx - 0.034, down + 0.018))
                part = disc * cut * moon
                r += (light[0] - r) * part
                g += (light[1] - g) * part
                b += (light[2] - b) * part
            if noise_row:
                over = noise_row[column] + lean
                if over > 0.0:
                    mask = 0.9 * _smooth(0.0, 0.22, over)
                    body = (thin - lost * _smooth(0.0, 0.55, over)) * 0.78
                    r += (cloud[0] * body + r * 0.22 - r) * mask
                    g += (cloud[1] * body + g * 0.22 - g) * mask
                    b += (cloud[2] * body + b * 0.22 - b) * mask
            if rain_row:
                streak = rain_row.get(column)
                if streak:
                    r += streak * 0.85
                    g += streak * 0.92
                    b += streak
            if drop_row:
                drop = drop_row.get(column)
                if drop:
                    amount, glint = drop
                    amount *= scene.rain
                    tone = 0.8 + 0.25 * (r + g + b) * 0.333 - 1.0
                    r += r * tone * amount
                    g += g * tone * amount
                    b += b * tone * amount
                    glint *= amount * (0.05 + 0.25 * (r + g + b) * 0.333)
                    r += glint
                    g += glint
                    b += glint
            if snow_row:
                flake = snow_row.get(column)
                if flake:
                    if flake > 1.0:
                        flake = 1.0
                    r += (_SNOW_TINT[0] - r) * flake
                    g += (_SNOW_TINT[1] - g) * flake
                    b += (_SNOW_TINT[2] - b) * flake
            noisy = (grain() - 0.5) * 0.012
            r = r * keep + noisy
            g = g * keep + noisy
            b = b * keep + noisy
            pixels[at] = 0 if r <= 0.0 else 255 if r >= 1.0 else int(r * 255.0 + 0.5)
            pixels[at + 1] = 0 if g <= 0.0 else 255 if g >= 1.0 else int(g * 255.0 + 0.5)
            pixels[at + 2] = 0 if b <= 0.0 else 255 if b >= 1.0 else int(b * 255.0 + 0.5)
            at += 3
    return bytes(pixels)
