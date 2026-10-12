"""Open the weather popover on a sky of your choosing, not on today's weather.

The sky is the part of the day times the weather, and most of the pairs come
round once in a while at best. This shows any of them, moving as it does in
the widget:

    python tools/sky_preview.py cloud-rain            # the rain, by day
    python tools/sky_preview.py cloud-rain evening
    python tools/sky_preview.py cloud-rain night --shot rain-night.png

In the window: 1 morning, 2 day, 3 evening, 4 night; Left and Right go through
the kinds of weather; Esc closes it. ``--shot`` saves a picture of the window
after a moment and exits.
"""

from __future__ import annotations

import argparse
import ctypes
import sys
import time
import tkinter as tk
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

import weather as weather_module  # noqa: E402
from ui import popover as popover_module  # noqa: E402
from ui.theme import load_theme  # noqa: E402

PHASES = ("morning", "day", "evening", "night")
PHASE_NAMES = {"morning": "Утро", "day": "День", "evening": "Вечер", "night": "Ночь"}
#: What the header says for an icon, and the same icon after sunset.
SKIES = {
    "sun": ("Ясно", "moon"),
    "cloud-sun": ("Переменная облачность", "cloud-moon"),
    "cloud": ("Пасмурно", "cloud"),
    "cloud-sun-rain": ("Местами дождь", "cloud-rain"),
    "cloud-rain": ("Дождь", "cloud-rain"),
    "cloud-lightning": ("Дождь с грозой", "cloud-lightning"),
    "cloud-snow": ("Снег", "cloud-snow"),
    # Not an icon of its own: snow, in a gale.
    "blizzard": ("Метель", "cloud-snow"),
}


#: The wind to show, in metres a second; ``None`` for the sample weather's own.
WIND: dict = {"speed": None}


def sample(icon: str, phase: str) -> weather_module.Weather:
    description, at_night = SKIES[icon]
    blizzard, icon = icon == "blizzard", "cloud-snow" if icon == "blizzard" else icon
    shown = at_night if phase == "night" else icon
    cold = -17 if icon == "cloud-snow" else 0  # it does not snow at fourteen above
    hours = [
        weather_module.Hour(clock, temperature + cold, shown)
        for clock, temperature in (("15:00", 15), ("18:00", 12), ("21:00", 10), ("00:00", 9), ("03:00", 9))
    ]
    return weather_module.Weather(
        temperature=14 + cold, feels_like=10 + cold, description=description, icon=shown, humidity=53,
        wind=WIND["speed"] if WIND["speed"] is not None else (14.2 if blizzard else 4.4), place=PHASE_NAMES[phase], low=7 + cold, high=15 + cold, hours=hours,
        fetched=time.time(), blizzard=blizzard,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("icon", nargs="?", default="cloud-rain", choices=sorted(SKIES))
    parser.add_argument("phase", nargs="?", default="day", choices=PHASES)
    parser.add_argument("--at", nargs=2, type=int, default=(200, 760), metavar=("LEFT", "BOTTOM"))
    parser.add_argument("--wind", type=float, help="the wind in metres a second (the clouds drift by it)")
    parser.add_argument("--shot", help="save a picture of the window here and exit")
    parser.add_argument("--after", type=float, default=1.2, help="how many seconds to wait for the picture")
    args = parser.parse_args()

    ctypes.windll.user32.SetProcessDPIAware()
    root = tk.Tk()
    root.geometry("1x1+0+0")
    root.overrideredirect(True)
    popover = popover_module.Popover(root, load_theme(root, mode="dark"))
    popover.eager = not args.shot  # as in the widget, but a picture is of the whole sky
    WIND["speed"] = args.wind
    state = {"icon": args.icon, "phase": args.phase}
    # The popover asks the weather what part of the day it is: answer for it.
    weather_module.Weather.phase = lambda _self, _now: state["phase"]

    def show(**change) -> None:
        state.update(change)
        popover.update(sample(state["icon"], state["phase"]))

    def turn(step: int) -> None:
        icons = list(SKIES)
        show(icon=icons[(icons.index(state["icon"]) + step) % len(icons)])

    popover.show("weather", *args.at, sample(args.icon, args.phase))
    for key, phase in zip("1234", PHASES):
        popover.window.bind(f"<Key-{key}>", lambda _event, phase=phase: show(phase=phase))
    popover.window.bind("<Left>", lambda _event: turn(-1))
    popover.window.bind("<Right>", lambda _event: turn(1))
    popover.window.bind("<Escape>", lambda _event: root.destroy())

    if args.shot:
        from PIL import ImageGrab

        def shoot() -> None:
            window = popover.window
            x, y = window.winfo_rootx(), window.winfo_rooty()
            box = (x, y, x + window.winfo_width(), y + window.winfo_height())
            ImageGrab.grab(bbox=box, all_screens=True).save(args.shot)
            root.destroy()

        root.after(int(args.after * 1000), shoot)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
