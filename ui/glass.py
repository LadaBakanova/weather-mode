"""Real glass for a Tk window: the blurred desktop behind, tinted.

This is what the FrostyGlass taskbar theme does with ``WindhawkBlur`` and what
the design calls ``$glass`` + ``background_blur``. Measured on this machine:

* ``SetWindowCompositionAttribute`` with the acrylic accent (state 4) blurs
  what is behind the window and lays a tint over it. The plain blur accent
  (state 3) leaves a Tk window opaque black, so it is not used;
* Tk paints with GDI, which writes no alpha. DWM therefore treats black as
  fully see-through and *adds* every other colour to the glass - see the
  palette note in ``ui/theme.py``;
* ``DWMWA_WINDOW_CORNER_PREFERENCE`` rounds the corners and draws the 1 px
  edge, so no colour key and no hand-drawn border are needed.

Every call can fail on an older Windows; the window is then simply black and
square, which is still readable.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import tkinter as tk

WCA_ACCENT_POLICY = 19
ACCENT_DISABLED = 0
ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_BORDER_COLOR = 34
DWMWCP_ROUND = 2
DWMWA_COLOR_NONE = 0xFFFFFFFE
DWMWCP_ROUNDSMALL = 3


class _AccentPolicy(ctypes.Structure):
    _fields_ = [
        ("AccentState", ctypes.c_int),
        ("AccentFlags", ctypes.c_int),
        ("GradientColor", ctypes.c_uint),
        ("AnimationId", ctypes.c_int),
    ]


class _CompositionData(ctypes.Structure):
    _fields_ = [
        ("Attribute", ctypes.c_int),
        ("Data", ctypes.c_void_p),
        ("SizeOfData", ctypes.c_size_t),
    ]


def _abgr(color: str, alpha: float) -> int:
    value = color.lstrip("#")
    red, green, blue = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    return (round(alpha * 255) << 24) | (blue << 16) | (green << 8) | red


def toplevel_hwnd(window: tk.Misc) -> int:
    """The real top-level handle: Tk's own id is a child of the frame window."""
    window.update_idletasks()
    inner = int(window.winfo_id())
    try:
        return int(ctypes.windll.user32.GetParent(wintypes.HWND(inner)) or inner)
    except Exception:
        return inner


def apply_glass(
    window: tk.Misc,
    tint: str,
    opacity: float,
    border: str | None = "#4A4A4A",
    small_corners: bool = False,
    classic: bool = False,
    opaque: bool = False,
) -> bool:
    """Turn ``window`` into tinted glass with rounded corners. True on success.

    ``border=None`` removes the 1 px edge: DWM can only draw it opaque, which
    reads as a dark outline on nearly clear glass over a bright wallpaper.

    ``classic=True`` asks for the classic acrylic recipe (``AccentFlags = 0``).
    The modern one (flags 2) adds Windows' own dark base, which leaves what is
    behind the window at 42 % of its brightness; the classic one keeps 84 %,
    which is the taskbar theme's blur-plus-15 %-tint. Both numbers were measured
    for the media widget mod (media-player/CONTEXT.md, "Размытие фона"). The
    dark flyout wants the dark base, the taskbar dock must not have it.

    ``opaque=True`` takes the glass away again and leaves the rounded corners
    and the edge: for a window that paints all of itself, as the weather
    popover does its sky.

    The compositor has nothing to blur for a hidden window, so call this again
    whenever the window is shown.
    """
    try:
        hwnd = wintypes.HWND(toplevel_hwnd(window))
        flags = 0 if classic else 2
        state = ACCENT_DISABLED if opaque else ACCENT_ENABLE_ACRYLICBLURBEHIND
        accent = _AccentPolicy(state, flags, _abgr(tint, opacity), 0)
        data = _CompositionData(
            WCA_ACCENT_POLICY,
            ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p),
            ctypes.sizeof(accent),
        )
        set_attribute = ctypes.windll.user32.SetWindowCompositionAttribute
        set_attribute.argtypes = [wintypes.HWND, ctypes.POINTER(_CompositionData)]
        set_attribute.restype = ctypes.c_int
        ok = bool(set_attribute(hwnd, ctypes.byref(data)))

        dwm = ctypes.windll.dwmapi.DwmSetWindowAttribute
        corner = ctypes.c_int(DWMWCP_ROUNDSMALL if small_corners else DWMWCP_ROUND)
        dwm(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(corner), ctypes.sizeof(corner))
        edge = ctypes.c_uint(DWMWA_COLOR_NONE if border is None else _abgr(border, 0.0))
        dwm(hwnd, DWMWA_BORDER_COLOR, ctypes.byref(edge), ctypes.sizeof(edge))
        return ok
    except Exception:
        return False
