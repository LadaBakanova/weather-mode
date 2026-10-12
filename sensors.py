"""The slow readings behind the dock's widgets, taken off the UI thread.

The weather needs the network and the device list walks the device tree; either
can take seconds, so both are read by one daemon thread and left in plain
attributes that the Tk timer looks at. Assigning an attribute is atomic, so no
lock is needed - the same arrangement as the calendar sync in ``widget.pyw``.

The quick readings (processor load, the foreground program) are taken on the Tk
timer itself and do not pass through here.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

import devices as devices_module
import weather as weather_module

#: How often the paired devices are looked at; a battery level moves slowly.
DEVICES_SECONDS = 60


class SensorWorker:
    def __init__(
        self,
        directory: Path,
        city: str = "",
        want_weather: bool = True,
        log: Callable[..., None] | None = None,
    ) -> None:
        self.directory = Path(directory)
        self.city = city
        self.want_weather = want_weather
        self._log = log or (lambda *args, **kwargs: None)
        self.weather: weather_module.Weather | None = (
            weather_module.load(self.directory, city) if want_weather else None
        )
        self.devices: list[devices_module.Device] = []
        self._weather_failed = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="sensors", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        next_weather = 0.0
        if self.weather is not None:
            # A saved answer is good until it is REFRESH_SECONDS old.
            next_weather = self.weather.fetched + weather_module.REFRESH_SECONDS
        while not self._stop.is_set():
            self.devices = devices_module.scan()
            if self.want_weather and time.time() >= next_weather:
                next_weather = time.time() + (
                    weather_module.REFRESH_SECONDS
                    if self._read_weather()
                    else weather_module.RETRY_SECONDS
                )
            self._stop.wait(DEVICES_SECONDS)

    def _read_weather(self) -> bool:
        try:
            self.weather = weather_module.fetch(self.city)
        except (OSError, ValueError) as exc:
            # Said once per outage, not every five minutes.
            if not self._weather_failed:
                self._log(f"weather unavailable: {exc!r}", level="WARN")
            self._weather_failed = True
            return False
        self._weather_failed = False
        weather_module.save(self.directory, self.weather, self.city)
        return True

    def current_weather(self) -> weather_module.Weather | None:
        """The weather to show: None when there is none or it has gone stale."""
        weather = self.weather
        return weather if weather is not None and weather.fresh() else None
