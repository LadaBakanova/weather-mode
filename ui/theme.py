"""Visual theme: follows the Windows accent colour and light/dark setting.

Nothing here is invented: the colours come from the same registry values the
shell itself uses, which is what makes the widget look native instead of like a
separate dark box.

* accent        ``HKCU\\Software\\Microsoft\\Windows\\DWM\\AccentColor`` plus the
                brightest usable entry of ``HKLM\\...\\DWM\\AccentPalette``
                (AccentColor is stored as ABGR, which is easy to get wrong)
* light or dark ``HKCU\\...\\Themes\\Personalize\\SystemUsesLightTheme``
* corner radius 8 px, the same as WinUI surfaces
* font          Segoe UI Variable Text, falling back to Segoe UI

Values are read once at start-up and again whenever the widget is reopened, so a
theme change does not require restarting anything long-lived.
"""

from __future__ import annotations

import ctypes
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass, field
from pathlib import Path

FALLBACK_ACCENT = "#4C8DFF"

# The design names Inter; it is used when installed, otherwise the system face.
FONT_CANDIDATES = [
    "Inter",
    "Segoe UI Variable Text",
    "Segoe UI Variable",
    "Segoe UI",
]

# The dark palette is the "Calendar Flyout" of design calendar.pen, written for
# a glass window (see ui/glass.py). On glass the window background is black and
# DWM shows the blurred desktop through it, with everything drawn on top *added*
# to it. The design defines its surfaces as white with an alpha, and adding a
# grey of the same level is exactly that, so each token below is the design's
# alpha as a grey: #FFFFFF0F (6 %) becomes #0F0F0F, and so on.
DARK = {
    "bg": "#000000",  # the glass itself; tinted by GLASS_TINT
    "bg_alt": "#0F0F0F",  # el-bg
    "fg": "#FFFFFF",  # text-primary
    "fg_dim": "#B3B3B3",  # text-secondary
    "fg_faint": "#737373",  # text-tertiary
    "text_disabled": "#3D3D3D",
    "border": "#3D3D3D",  # top of the design's gradient stroke
    "border_soft": "#292929",  # bottom of the gradient stroke
    "today": "#141414",  # divider
    "hover": "#1A1A1A",  # el-hover
    "pressed": "#0A0A0A",  # el-pressed
    "footer": "#080808",
    "dot_empty": "#3D3D3D",
    "weekend": "#FFA898",
    "weekend_dim": "#B27669",  # weekday labels: weekend at 70 %
    "danger": "#FF7A7A",
    "danger_bg": "#190C0C",
    "danger_line": "#472222",
    "accent_text": "#FFFFFF",
    # panel.pen (the taskbar widgets and their popovers), alphas as greys again.
    "selected": "#242424",  # the open widget's button, #FFFFFF24
    "switch_on": "#525252",  # the chosen half of a switch: #FFFFFF2E on the track
    "track": "#242424",  # track
    "bar": "#737373",  # a level that is not the first one, #FFFFFF73
    "info": "#7DB7FF",  # accent
    "ok": "#4ADE80",
    "warn": "#FBBF24",
}

#: The design's $glass (#161822 at 60 %) and its accent fill.
GLASS_TINT = ("#161822", 0.60)
DESIGN_ACCENT = "#FFFFFF"

LIGHT = {
    "bg": "#F3F3F3",
    "bg_alt": "#FFFFFF",
    "fg": "#1A1A1A",
    "fg_dim": "#5B5B5B",
    "fg_faint": "#8A8A8A",
    "text_disabled": "#B5B5B5",
    "border": "#DCDCDC",
    "today": "#E8E8E8",
    "hover": "#E2E2E2",
    "footer": "#EAEAEA",
    "dot_empty": "#C8C8C8",
    "border_soft": "#DCDCDC",
    "pressed": "#D8D8D8",
    "weekend": "#B4442C",
    "weekend_dim": "#B4442C",
    "accent_text": "#5B3FE0",
    "danger": "#C42B1C",
    "danger_bg": "#FDECEA",
    "danger_line": "#F4B9B2",
    "selected": "#D8D8D8",
    "switch_on": "#FFFFFF",
    "track": "#DCDCDC",
    "bar": "#8A8A8A",
    "info": "#2F6FD0",
    "ok": "#1E9E4A",
    "warn": "#B7791F",
}


@dataclass
class Theme:
    dark: bool = True
    accent: str = FALLBACK_ACCENT
    colors: dict = field(default_factory=dict)
    font_family: str = "Segoe UI"
    semibold_family: str = ""
    light_family: str = ""
    #: True when the window should be real glass (dark theme only).
    glass: bool = False

    def font(self, size: int = 10, bold: bool = False) -> tuple:
        return (self.font_family, size, "bold") if bold else (self.font_family, size)

    def px(self, size: int, weight: int = 400) -> tuple:
        """A font by pixel size and CSS weight, as the design specifies them.

        Tk only knows normal and bold, so 600 uses the family's Semibold face
        when it is installed; 500 has no face in Segoe UI and stays regular.
        300 is the Light face, or regular without one.
        """
        if weight <= 300 and self.light_family:
            return (self.light_family, -size)
        if weight >= 700:
            return (self.font_family, -size, "bold")
        if weight >= 600:
            if self.semibold_family:
                return (self.semibold_family, -size)
            return (self.font_family, -size, "bold")
        return (self.font_family, -size)

    def get(self, key: str, fallback: str = "") -> str:
        return self.colors.get(key, fallback)


def _registry_value(root, path: str, name: str):
    try:
        import winreg

        with winreg.OpenKey(root, path) as key:
            value, _ = winreg.QueryValueEx(key, name)
            return value
    except OSError:
        return None


def _is_light_theme() -> bool:
    import winreg

    value = _registry_value(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        "SystemUsesLightTheme",
    )
    return bool(value)


def _accent_from_registry() -> str:
    """The Windows accent colour, as hex.

    ``AccentColor`` is a DWORD in ABGR order (0xAABBGGRR); ``AccentPalette`` is a
    blob of eight RGB triplets. The palette entry is preferred because the plain
    AccentColor is sometimes a slot index rather than a colour on customised
    systems.
    """
    import winreg

    palette = _registry_value(
        winreg.HKEY_LOCAL_MACHINE,
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Accent",
        "AccentPalette",
    )
    if isinstance(palette, bytes) and len(palette) >= 24:
        # Entries 4 and 5 are the "accent" shades in the shell's own palette;
        # entry 4 (`AccentPalette[4]`) matches the taskbar and Start accent.
        red, green, blue = palette[16], palette[17], palette[18]
        if red or green or blue:
            return f"#{red:02X}{green:02X}{blue:02X}"

    value = _registry_value(
        winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM", "AccentColor"
    )
    if isinstance(value, int):
        red = value & 0xFF
        green = (value >> 8) & 0xFF
        blue = (value >> 16) & 0xFF
        alpha = (value >> 24) & 0xFF
        if alpha == 0:
            # Some systems store the colour without alpha; treat it as opaque.
            alpha = 0xFF
        return f"#{red:02X}{green:02X}{blue:02X}"
    return FALLBACK_ACCENT


def _pick_font(root: tk.Misc) -> tuple[str, str, str]:
    """The family and its Semibold and Light faces ("" when there is none)."""
    available = set(tkfont.families(root))
    family = next((name for name in FONT_CANDIDATES if name in available), "Segoe UI")
    semibold, light = family + " Semibold", family + " Light"
    return family, semibold if semibold in available else "", light if light in available else ""


def load_theme(root: tk.Misc, mode: str = "auto", accent_override: str = "") -> Theme:
    """Build the theme for this run.

    ``mode`` is ``auto``, ``light`` or ``dark`` (the user-facing setting);
    ``accent_override`` lets the settings file pin a colour.
    """
    dark = True if mode == "dark" else (False if mode == "light" else not _is_light_theme())
    colors = dict(DARK if dark else LIGHT)
    # The dark theme is the design, so it uses the design's accent; the light
    # theme keeps following the Windows accent as before.
    accent = accent_override.strip() or (DESIGN_ACCENT if dark else _accent_from_registry())
    if not accent.startswith("#") or len(accent) not in (4, 7):
        accent = DESIGN_ACCENT if dark else FALLBACK_ACCENT
    family, semibold, light = _pick_font(root)
    return Theme(
        dark=dark,
        accent=accent,
        colors=colors,
        font_family=family,
        semibold_family=semibold,
        light_family=light,
        glass=dark,
    )


def enable_dpi_awareness() -> None:
    """Ask Windows for per-monitor DPI so text is not scaled twice.

    Must be called before the first Tk window exists. Failures are ignored: the
    widget simply looks slightly softer on a high-DPI screen.
    """
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def set_app_user_model_id(app_id: str = "CalendarWidget.TaskbarCalendar") -> None:
    """Give the process its own taskbar identity.

    Without this the widget would group itself under python.exe in the taskbar.
    """
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass


def tint(color: str, background: str, alpha: float) -> str:
    """Blend ``color`` into ``background`` by ``alpha`` (0..1).

    Used for the translucent-looking "today" and selection fills: real alpha is
    not available for child widgets, so the same effect is produced by blending
    against the panel colour.
    """
    try:
        cr, cg, cb = _to_rgb(color)
        br, bg, bb = _to_rgb(background)
    except ValueError:
        return background
    mixed = (
        round(cr * alpha + br * (1 - alpha)),
        round(cg * alpha + bg * (1 - alpha)),
        round(cb * alpha + bb * (1 - alpha)),
    )
    return "#{:02X}{:02X}{:02X}".format(*mixed)


#: Segoe UI's capitals and figures, in em.
CAP_HEIGHT = 0.7
_LINE_BOX: dict[tuple, tuple[int, int]] = {}


def ink_middle(root: tk.Misc, spec: tuple, middle: float) -> float:
    """The y at which to draw text so its capitals, not its line box, are centred on ``middle``.

    Tk centres a text's line box (ascent + descent) on its anchor. Segoe UI's
    box has more room above the letters than below, so text drawn on the middle
    looks pushed down. This works out where Tk puts the baseline for that box
    and moves the anchor up by the gap to the cap centre. Use it for anchors
    ``w``, ``e`` and ``center``.
    """
    if spec not in _LINE_BOX:
        font = tkfont.Font(root=root, font=spec)
        _LINE_BOX[spec] = (font.metrics("ascent"), font.metrics("descent"))
    ascent, descent = _LINE_BOX[spec]
    size = abs(spec[1])
    # Tk takes half the line box in whole pixels, so the baseline is worked out the same way.
    baseline = middle - (ascent + descent) // 2 + ascent
    cap_middle = baseline - CAP_HEIGHT * size / 2
    return middle - (cap_middle - middle)


def readable_on(color: str) -> str:
    """Black or white, whichever is legible on ``color``."""
    try:
        red, green, blue = _to_rgb(color)
    except ValueError:
        return "#FFFFFF"
    # Rec. 709 luma; the usual threshold for picking a foreground colour.
    luma = (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255
    return "#101010" if luma > 0.6 else "#FFFFFF"


def _to_rgb(color: str) -> tuple[int, int, int]:
    value = color.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(character * 2 for character in value)
    if len(value) != 6:
        raise ValueError(f"not a colour: {color!r}")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def icon_path() -> Path | None:
    """The window/tray icon, if the project's .ico was generated."""
    candidate = Path(__file__).resolve().parent.parent / "assets" / "calendar.ico"
    return candidate if candidate.is_file() else None
