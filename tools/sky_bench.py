"""What the weather popover's sky costs: to open, and then to keep moving.

    python tools/sky_bench.py                  # the rain by day
    python tools/sky_bench.py cloud night --seconds 6

It opens the popover on a sky of your choosing (as ``tools/sky_preview.py``
does), says how long that took and what the time went on, and then lets it
run, taking its moving parts away one at a time. Each line is what a frame
costs with what is left: the time to work out where everything is, and the
time Tk takes to draw it - the middle one of all the frames, which a busy
machine does not move much, and the slow tenth. The difference between two
lines is what the part taken away costs. The share of a processor core is
there too, but it moves with whatever else the machine is doing.
"""

from __future__ import annotations

import argparse
import ctypes
import cProfile
import pstats
import sys
import time
import tkinter as tk
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
for path in (PROJECT, PROJECT / "tools"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import sky_preview  # noqa: E402
import weather as weather_module  # noqa: E402
from ui import popover as popover_module  # noqa: E402
from ui.theme import load_theme  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("icon", nargs="?", default="cloud-rain", choices=sorted(sky_preview.SKIES))
    parser.add_argument("phase", nargs="?", default="day", choices=sky_preview.PHASES)
    parser.add_argument("--wind", type=float, help="the wind in metres a second (the sample weather's own otherwise)")
    parser.add_argument("--seconds", type=float, default=8.0, help="how long each measurement runs")
    parser.add_argument("--warm", type=float, default=6.0, help="how long it runs before the first one")
    parser.add_argument("--profile", action="store_true", help="say where the time to open went")
    args = parser.parse_args()

    ctypes.windll.user32.SetProcessDPIAware()
    root = tk.Tk()
    root.geometry("1x1+0+0")
    root.overrideredirect(True)
    popover = popover_module.Popover(root, load_theme(root, mode="dark"))
    weather_module.Weather.phase = lambda _self, _now: args.phase
    sky_preview.WIND["speed"] = args.wind
    sample = sky_preview.sample(args.icon, args.phase)

    profile = cProfile.Profile() if args.profile else None
    started, used = time.perf_counter(), time.process_time()
    if profile:
        profile.enable()
    popover.show("weather", 200, 760, sample)
    root.update()
    if profile:
        profile.disable()
    print(f"{args.icon}, {args.phase}")
    print(f"to open: {time.perf_counter() - started:.2f} s ({time.process_time() - used:.2f} s of the processor)")
    if profile:
        stats = pstats.Stats(profile)
        stats.sort_stats("cumulative")
        rows = []
        for (file, _line, name), (_cc, calls, _tt, cumulative, _callers) in stats.stats.items():
            if "calendar-mode" in file.replace("\\", "/") and "tools" not in file and cumulative > 0.01:
                rows.append((cumulative, calls, f"{Path(file).name}:{name}"))
        for cumulative, calls, where in sorted(rows, reverse=True)[:16]:
            print(f"  {cumulative:6.2f} s  {calls:7d} calls  {where}")
    popover.hide()
    started = time.perf_counter()
    popover.show("weather", 200, 760, sample)
    root.update()
    print(f"to open again: {time.perf_counter() - started:.2f} s")
    # As the widget opens it: the bare sky at once, the rest a moment later.
    other = popover_module.Popover(root, popover.theme)
    other.eager = False
    started = time.perf_counter()
    other.show("weather", 520, 760, sample)
    root.update_idletasks()
    shown = time.perf_counter() - started
    while other._unfinished:
        root.update()
    print(f"as in the widget: shown in {shown:.2f} s, whole in {time.perf_counter() - started:.2f} s")
    other.hide()
    other.window.destroy()
    # And with its sky made ready beforehand, as the widget has it by the time it is asked.
    third = popover_module.Popover(root, popover.theme)
    third.eager = False
    popover.hide()  # nothing else of the widget's is moving when it does this
    root.update()
    started = time.perf_counter()
    third.prepare(sample)
    longest = 0.0
    while third._making is not None:
        at = time.perf_counter()
        root.update()
        longest = max(longest, time.perf_counter() - at)
        time.sleep(0.002)
    ready = time.perf_counter() - started
    started = time.perf_counter()
    third.show("weather", 520, 760, sample)
    root.update_idletasks()
    print(
        f"made ready beforehand: in {ready:.2f} s behind the widget (which was held up for"
        f" {1000 * longest:.0f} ms at the most), then shown whole in {time.perf_counter() - started:.2f} s"
    )
    third.hide()
    third.window.destroy()
    popover.show("weather", 200, 760, sample)
    root.update()

    canvas = popover.canvas

    def hide(items) -> None:
        for item in items:
            canvas.itemconfigure(item, state="hidden")

    def images(photos) -> list[int]:
        names = {str(photo) for photo in photos}
        return [
            item for item in canvas.find_all()
            if canvas.type(item) == "image" and canvas.itemcget(item, "image") in names
        ]

    def without_trickles() -> None:
        hide(popover._trickles)
        popover._trickles = ()

    def without_splashes() -> None:
        hide(popover._splashes)
        popover._splashes = ()

    def without_glass() -> None:
        hide(images([popover._sky[8]] if popover._sky[8] else []))

    def without_rain() -> None:
        hide([item for items in popover._rain for item in items])
        popover._rain = ()

    def without_clouds() -> None:
        hide(popover._clouds)
        popover._clouds = ()

    def without_sun() -> None:
        if popover._sun is not None:
            canvas.itemconfigure(popover._sun, state="hidden")
        popover._sun = None

    stages = [("everything", lambda: None)]
    if popover._sun is not None:
        stages.append(("without the sun's rays (their picture is drawn twelve times a second)", without_sun))
    if popover._trickles:
        stages.append(("without the drops running down", without_trickles))
    if popover._splashes:
        stages.append(("  and without the splashes", without_splashes))
    if len(popover._sky) > 8 and popover._sky[8]:
        stages.append(("  and without the drops on the glass", without_glass))
    if popover._rain:
        stages.append(("  and without the falling rain", without_rain))
    if popover._clouds:
        stages.append(("  and without the clouds: nothing moves", without_clouds))
    # Its own loop is stopped: here a frame is moved and drawn at once, and timed.
    if popover._drift_job is not None:
        popover.window.after_cancel(popover._drift_job)
        popover._drift_job = None
    step = popover_module.DRIFT_MS / 1000.0

    def run(seconds: float):
        """Frame after frame for so long; how long each took to work out and to draw."""
        moved, drawn = [], []
        until = time.perf_counter() + seconds
        while time.perf_counter() < until:
            at = time.perf_counter()
            popover._slide()
            then = time.perf_counter()
            root.update()
            done = time.perf_counter()
            moved.append(then - at)
            drawn.append(done - then)
            time.sleep(max(0.0, step - (done - at)))
        return moved, drawn

    run(args.warm)
    print("  a frame, in milliseconds: to work out + to draw (the middle one of all; and the slow tenth)")
    for label, change in stages:
        change()
        used = time.process_time()
        clock = time.perf_counter()
        moved, drawn = run(args.seconds)
        share = 100.0 * (time.process_time() - used) / (time.perf_counter() - clock)
        moved.sort()
        drawn.sort()
        middle, slow = len(drawn) // 2, len(drawn) * 9 // 10
        print(
            f"  {1000 * moved[middle]:5.2f} + {1000 * drawn[middle]:5.2f}"
            f"   ({1000 * moved[slow]:5.2f} + {1000 * drawn[slow]:5.2f})   {share:4.1f} % of a core   {label}"
        )
    root.destroy()
    return 0


if __name__ == "__main__":
    sys.exit(main())
