"""The weather outside, for the dock's first item.

One request to wttr.in gives the current weather and the hours ahead:

    https://wttr.in/<place>?format=j1&lang=ru

With no place named, the service takes the location from the address the
request comes from, so nothing about the user is sent beyond the request
itself. ``weather_city`` in ``settings.json`` names a place instead ("Казань",
"Saint Petersburg"), which is also the way to correct a wrong guess.

The last answer is kept in ``weather.json`` so the dock has a temperature right
after start-up and during a short loss of the network; an answer older than
``STALE_SECONDS`` is not shown at all - yesterday's weather is worse than none.

Parsing is separate from fetching so it can be tested on a saved answer.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path

from store import _atomic_write_json, _read_json

FILE_NAME = "weather.json"
SERVICE = "https://wttr.in/"
TIMEOUT = 15
#: How often the weather is asked for, and how soon again after a failure.
REFRESH_SECONDS = 30 * 60
RETRY_SECONDS = 5 * 60
STALE_SECONDS = 3 * 3600
#: Hours shown in the popover's strip; the service gives one every three hours.
HOURS_AHEAD = 5

# The service's condition codes (World Weather Online) by the icon they get.
_ICON_CODES = {
    "sun": {113},
    "cloud-sun": {116},
    "cloud-sun-rain": {176, 263, 293, 299, 305, 353},  # rain in places, between clearings
    "cloud": {119, 122, 143, 248, 260},
    "cloud-lightning": {200, 386, 389, 392, 395},
    "cloud-snow": {
        179, 182, 185, 227, 230, 317, 320, 323, 326, 329, 332, 335, 338, 350, 362, 365, 368,
        371, 374, 377,
    },
}


#: What an icon with the sun in it becomes after sunset.
_NIGHT_ICONS = {"sun": "moon", "cloud-sun": "cloud-moon", "cloud-sun-rain": "cloud-rain"}

#: Sunrise and sunset, in minutes of the day, when the service names none.
SUNRISE = 6 * 60
SUNSET = 19 * 60


def icon_for(code: int, night: bool = False) -> str:
    """The icon in ``assets/`` for a condition code; rain for anything unlisted,
    which is what the remaining codes are. At ``night`` the sun is a moon."""
    for icon, codes in _ICON_CODES.items():
        if code in codes:
            return _NIGHT_ICONS.get(icon, icon) if night else icon
    return "cloud-rain"


# The same codes in words. The service's own Russian text is missing for some
# conditions ("Patchy rain nearby" comes back untranslated), so it is only the
# fallback for a code that is not here.
_DESCRIPTIONS = {
    113: "Ясно",
    116: "Переменная облачность",
    119: "Облачно",
    122: "Пасмурно",
    143: "Дымка",
    176: "Местами дождь",
    179: "Местами снег",
    182: "Местами мокрый снег",
    185: "Местами ледяная морось",
    200: "Местами грозы",
    227: "Позёмок",
    230: "Метель",
    248: "Туман",
    260: "Ледяной туман",
    263: "Местами слабая морось",
    266: "Слабая морось",
    281: "Ледяная морось",
    284: "Сильная ледяная морось",
    293: "Местами небольшой дождь",
    296: "Небольшой дождь",
    299: "Временами дождь",
    302: "Дождь",
    305: "Временами сильный дождь",
    308: "Сильный дождь",
    311: "Слабый ледяной дождь",
    314: "Ледяной дождь",
    317: "Небольшой мокрый снег",
    320: "Мокрый снег",
    323: "Местами небольшой снег",
    326: "Небольшой снег",
    329: "Местами снег",
    332: "Снег",
    335: "Местами сильный снег",
    338: "Сильный снег",
    350: "Ледяная крупа",
    353: "Небольшой ливень",
    356: "Ливень",
    359: "Сильный ливень",
    362: "Небольшой мокрый снег",
    365: "Сильный мокрый снег",
    368: "Небольшой снегопад",
    371: "Сильный снегопад",
    374: "Ледяная крупа",
    377: "Сильная ледяная крупа",
    386: "Местами дождь с грозой",
    389: "Дождь с грозой",
    392: "Местами снег с грозой",
    395: "Снег с грозой",
}


def format_temperature(value: int) -> str:
    """"+8°", "−3°", "0°" - with a real minus sign."""
    if value > 0:
        return f"+{value}°"
    if value < 0:
        return f"−{-value}°"
    return "0°"


@dataclass(frozen=True)
class Hour:
    time: str  # "15:00"
    temperature: int
    icon: str


@dataclass(frozen=True)
class Weather:
    temperature: int
    feels_like: int
    description: str  # "Переменная облачность"
    icon: str
    humidity: int  # percent
    wind: float  # metres per second
    place: str  # "Казань"
    low: int | None = None  # today's range
    high: int | None = None
    hours: list[Hour] = field(default_factory=list)
    fetched: float = 0.0  # time.time() of the answer
    sunrise: int | None = None  # minutes of the day
    sunset: int | None = None
    #: Snow driven by a gale: the service calls it a blizzard or blowing snow,
    #: or it is snowing in a wind of ``BLIZZARD_WIND`` or more.
    blizzard: bool = False

    def fresh(self, now: float | None = None) -> bool:
        return (now if now is not None else time.time()) - self.fetched < STALE_SECONDS

    def is_night(self, minute: int) -> bool:
        """Whether the sun is down at ``minute`` of the day."""
        return _is_night(minute, self.sunrise, self.sunset)

    def phase(self, now: datetime) -> str:
        """The sky the popover is painted for, by the sun and not by the clock:
        ``night`` from sunset to sunrise, ``morning`` for a while after sunrise,
        ``evening`` for a while before sunset, and ``day`` between. The sun's
        times are the service's for the day; without them, the usual ones."""
        minute = now.hour * 60 + now.minute
        sunrise = self.sunrise if self.sunrise is not None else SUNRISE
        sunset = self.sunset if self.sunset is not None else SUNSET
        if minute < sunrise or minute >= sunset:
            return "night"
        if minute < sunrise + 180:
            return "morning"
        return "evening" if minute >= sunset - 150 else "day"

    def clock_part(self, now: datetime) -> str:
        """What to call the part of the day by the clock, whatever the sky is:
        утро, день, вечер or ночь - 5 to 11, 11 to 17, 17 to 23, then ночь."""
        hour = now.hour
        if 5 <= hour < 11:
            return "утро"
        if 11 <= hour < 17:
            return "день"
        if 17 <= hour < 23:
            return "вечер"
        return "ночь"


def _is_night(minute: int, sunrise: int | None, sunset: int | None) -> bool:
    return not (
        (sunrise if sunrise is not None else SUNRISE)
        <= minute
        < (sunset if sunset is not None else SUNSET)
    )


def _minutes(text) -> int | None:
    """The service's "06:12 AM" as minutes of the day."""
    try:
        moment = datetime.strptime(str(text).strip(), "%I:%M %p")
    except ValueError:
        return None
    return moment.hour * 60 + moment.minute


def _text(items) -> str:
    """The service wraps strings as ``[{"value": "..."}]``."""
    try:
        return str(items[0]["value"]).strip()
    except (IndexError, KeyError, TypeError):
        return ""


#: The service's codes for blowing snow and for a blizzard; and the wind, in
#: metres a second, from which any snowfall is one.
_BLIZZARD_CODES = {227, 230}
BLIZZARD_WIND = 10.0


def parse(data: dict, now: datetime, fetched: float | None = None) -> Weather:
    """A :class:`Weather` from the service's answer. Raises on a malformed one."""
    current = data["current_condition"][0]
    area = (data.get("nearest_area") or [{}])[0]
    days = data.get("weather") or []
    today = days[0] if days else {}
    sun = (today.get("astronomy") or [{}])[0]
    sunrise, sunset = _minutes(sun.get("sunrise")), _minutes(sun.get("sunset"))

    hours: list[Hour] = []
    for offset, day in enumerate(days):
        try:
            day_date = datetime.strptime(day["date"], "%Y-%m-%d").date()
        except (KeyError, ValueError):
            day_date = now.date() + timedelta(days=offset)
        for slot in day.get("hourly", []):
            moment = datetime.combine(day_date, datetime.min.time()) + timedelta(
                hours=int(slot["time"]) // 100
            )
            if moment > now.replace(tzinfo=None) and len(hours) < HOURS_AHEAD:
                night = _is_night(moment.hour * 60, sunrise, sunset)
                hours.append(
                    Hour(
                        moment.strftime("%H:%M"),
                        int(slot["tempC"]),
                        icon_for(int(slot["weatherCode"]), night),
                    )
                )

    code = int(current["weatherCode"])
    wind = round(int(current["windspeedKmph"]) / 3.6, 1)
    return Weather(
        temperature=int(current["temp_C"]),
        feels_like=int(current["FeelsLikeC"]),
        description=_DESCRIPTIONS.get(int(current["weatherCode"]))
        or _text(current.get("lang_ru"))
        or _text(current.get("weatherDesc")),
        icon=icon_for(
            int(current["weatherCode"]), _is_night(now.hour * 60 + now.minute, sunrise, sunset)
        ),
        humidity=int(current["humidity"]),
        wind=wind,
        place=_text(area.get("areaName")),
        low=int(today["mintempC"]) if "mintempC" in today else None,
        high=int(today["maxtempC"]) if "maxtempC" in today else None,
        hours=hours,
        fetched=fetched if fetched is not None else time.time(),
        sunrise=sunrise,
        sunset=sunset,
        blizzard=code in _BLIZZARD_CODES or (icon_for(code) == "cloud-snow" and wind >= BLIZZARD_WIND),
    )


def fetch(city: str = "") -> Weather:
    """Ask the service. Raises ``OSError`` or ``ValueError`` when it fails."""
    url = SERVICE + urllib.parse.quote(city.strip()) + "?format=j1&lang=ru"
    request = urllib.request.Request(url, headers={"User-Agent": "CalendarWidget/1.0"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        body = response.read().decode("utf-8")
    try:
        weather = parse(json.loads(body), datetime.now())
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValueError(f"unexpected answer from the weather service: {exc!r}") from exc
    if city.strip():
        # The service names the nearest weather station; the user named a city.
        weather = replace(weather, place=city.strip())
    return weather


def save(directory: Path, weather: Weather, city: str) -> None:
    try:
        _atomic_write_json(Path(directory) / FILE_NAME, {"city": city, "weather": asdict(weather)})
    except OSError:
        pass


def load(directory: Path, city: str) -> Weather | None:
    """The saved answer, if it was for the same place and is still fresh."""
    raw = _read_json(Path(directory) / FILE_NAME, None)
    if not isinstance(raw, dict) or raw.get("city", "") != city:
        return None
    try:
        values = dict(raw["weather"])
        values["hours"] = [Hour(**hour) for hour in values.get("hours", [])]
        weather = Weather(**values)
    except (KeyError, TypeError):
        return None
    return weather if weather.fresh() else None
