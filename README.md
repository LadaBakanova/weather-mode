# weather-mode

Виджет погоды для Windows, вынесенный из [calendar-mode](../calendar-mode): окно с
нарисованным небом (утро, день, вечер, ночь по восходу и закату), облаками, дождём,
снегом, грозой, луной и звёздами. Облака плывут, а дождь и снег косеют тем сильнее,
чем сильнее ветер.

## Состав

| Файл | Назначение |
|---|---|
| `weather.py` | погода с wttr.in, разбор ответа и кэш `weather.json` |
| `sensors.py` | фоновый поток, который обновляет погоду и устройства |
| `ui/popover.py` | окно погоды (и другие поповеры виджетов) |
| `ui/sky.py` | небо: таблицы `CLOUD_SPEEDS`, `RAIN_SLANTS`, `SNOW_SLANTS`, реакция на ветер |
| `ui/splash.py`, `ui/trickle.py` | осадки и облака поверх неба |
| `pen-assets/sky.glsl` | шейдер неба, из которого `ui/sky.py` взят на Python |
| `ui/shapes.py`, `ui/glass.py`, `ui/svg_icon.py`, `ui/theme.py` | рисование, стекло, значки, тема |
| `ui/widgets_dock.py`, `ui/dock.py`, `ui/day_view.py` | плашка виджетов и её зависимости |
| `app_time.py`, `devices.py`, `system_load.py`, `store.py` | остальные данные поповеров и общие файловые утилиты |
| `tools/sky_preview.py` | показать небо для любой погоды и времени суток |
| `tools/sky_bench.py` | замер времени кадра по слоям |
| `assets/*.svg` | значки погоды и виджетов (контуры Lucide, лицензия ISC) |
| `panel.pen` | макет плашек и поповеров |

## Запуск

Нужны Windows и Python 3.12 с tkinter. Внешних пакетов не требуется.

Посмотреть небо для нужной погоды:

```bash
python tools/sky_preview.py cloud-rain day --wind 12
```

Аргументы: погода (`sun`, `cloud-sun`, `cloud`, `cloud-rain`, `cloud-snow`,
`cloud-lightning`, `cloud-sun-rain`, `blizzard`), время суток (`morning`, `day`,
`evening`, `night`), `--wind` в м/с, `--at LEFT BOTTOM` для положения окна.
Клавиши 1–4 переключают время суток, стрелки — погоду.

Замер производительности:

```bash
python tools/sky_bench.py cloud-rain day --wind 12
```

## Примечания

- Место сервис определяет по адресу запроса. Свой город передаётся аргументом
  `city` в `sensors.py` / `weather.fetch` (в calendar-mode он берётся из `weather_city`).
- Последний ответ хранится в `weather.json`; ответ старше трёх часов не показывается.
- Тесты и файлы calendar-mode (календарь, синхронизация CalDAV, `widget.pyw`) сюда не входят.
