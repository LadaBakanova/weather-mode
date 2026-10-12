"""Battery of the wireless headphones and keyboard.

The dock's "Headphones" and "Keyboard" icons. Windows keeps what a paired
Bluetooth device reports about itself as properties of its device node - the
same numbers the Settings app shows under "Bluetooth & devices". They are read
here through SetupAPI, with nothing to install. The battery is on the device's
hands-free service node (``BTHENUM\\{0000111E-...}``) for headsets, not on the
device node itself:

* battery level   ``{104EA319-6EE2-4701-BD47-8DDBF425BBE5} 2``   (a byte, percent)
* connected       ``{83DA6326-97A6-4088-9453-A1923F573B29} 15``  (a boolean)
* class of device ``{2BD67D8B-8BEB-48D5-87E0-6CDA3428040A} 10``  (classic Bluetooth)

Limits, stated plainly:

* only Bluetooth devices are seen (their nodes are BTHENUM / BTHLE / BTHHFENUM). A keyboard on its maker's own radio dongle
  (Logitech Bolt/Unifying, Razer and the like) reports its battery only to the
  maker's program, and no icon is shown for it;
* not every device reports a level; such a device is shown without one;
* which device is "the headphones" and which "the keyboard" is decided by the
  Bluetooth class when there is one, and by words in the name otherwise.

The parsing and choosing is in plain functions so it can be tested without any
device at hand.
"""

from __future__ import annotations

import ctypes
import re
from ctypes import wintypes
from dataclasses import dataclass

HEADPHONES = "headphones"
KEYBOARD = "keyboard"

#: From this level down the dock shows the number, and at CRITICAL in red.
LOW_BATTERY = 20
CRITICAL_BATTERY = 10

_HEADPHONE_WORDS = (
    "headphone", "headset", "earphone", "earbud", "buds", "airpods", "наушник", "гарнитур",
    "wh-", "wf-", "jbl", "bose", "sennheiser", "momentum", "freebuds", "soundcore", "jabra",
    "beats", "tws", "pods", "hands-free",
)
_KEYBOARD_WORDS = ("keyboard", "клавиатур", "keys", "keychron", "k380", "k780", "mx mechanical")


@dataclass(frozen=True)
class Device:
    kind: str  # HEADPHONES or KEYBOARD
    name: str
    connected: bool
    battery: int | None  # percent; None when the device does not say

    @property
    def low(self) -> bool:
        return self.connected and self.battery is not None and self.battery <= LOW_BATTERY


def classify(name: str, class_of_device: int | None = None) -> str | None:
    """HEADPHONES, KEYBOARD or None for a device that is neither."""
    if class_of_device:
        major = (class_of_device >> 8) & 0x1F
        if major == 0x04:  # audio/video
            return HEADPHONES
        if major == 0x05:  # peripheral; bit 6 of the minor class marks a keyboard
            return KEYBOARD if class_of_device & 0x40 else None
    lowered = name.lower()
    if any(word in lowered for word in _KEYBOARD_WORDS):
        return KEYBOARD
    if any(word in lowered for word in _HEADPHONE_WORDS):
        return HEADPHONES
    return None


def choose(devices: list[Device], kind: str) -> Device | None:
    """The one device of ``kind`` to show: connected before not, and among
    equals the one that reports a battery level."""
    candidates = [device for device in devices if device.kind == kind]
    if not candidates:
        return None
    return max(candidates, key=lambda device: (device.connected, device.battery is not None))


def merge(nodes: list[tuple[str, str, bool | None, int | None, int | None]]) -> list[Device]:
    """Devices from raw device nodes ``(address, name, connected, battery, class)``.

    One physical device has several nodes (the device itself and its services);
    the battery may sit on one and the name on another, so nodes are joined by
    the device's address.
    """
    by_address: dict[str, dict] = {}
    for address, name, connected, battery, class_of_device in nodes:
        entry = by_address.setdefault(
            address, {"name": "", "connected": False, "battery": None, "class": None}
        )
        # The device's own node comes first and carries its proper name;
        # service nodes are called "... Hands-Free", "... Avrcp Transport".
        if name and not entry["name"]:
            entry["name"] = name
        entry["connected"] = entry["connected"] or bool(connected)
        if battery is not None and 0 <= battery <= 100:
            entry["battery"] = battery
        if class_of_device:
            entry["class"] = class_of_device
    devices = []
    for entry in by_address.values():
        kind = classify(entry["name"], entry["class"])
        if kind:
            devices.append(Device(kind, entry["name"], entry["connected"], entry["battery"]))
    return devices


# ---------------------------------------------------------------------------
# SetupAPI
# ---------------------------------------------------------------------------


class _Guid(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def parse(cls, text: str) -> "_Guid":
        digits = text.strip("{}").replace("-", "")
        tail = bytes.fromhex(digits[16:])
        return cls(int(digits[0:8], 16), int(digits[8:12], 16), int(digits[12:16], 16),
                   (ctypes.c_ubyte * 8)(*tail))


class _DevInfoData(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("ClassGuid", _Guid),
        ("DevInst", wintypes.DWORD),
        ("Reserved", ctypes.c_void_p),
    ]


class _PropertyKey(ctypes.Structure):
    _fields_ = [("fmtid", _Guid), ("pid", wintypes.ULONG)]


def _key(guid: str, pid: int) -> _PropertyKey:
    return _PropertyKey(_Guid.parse(guid), pid)


_BLUETOOTH_BUS_PREFIXES = ("BTHENUM\\", "BTHLE\\", "BTHHFENUM\\")
_KEY_NAME = ("{a45c254e-df1c-4efd-8020-67d146a850e0}", 14)  # friendly name
_KEY_BATTERY = ("{104EA319-6EE2-4701-BD47-8DDBF425BBE5}", 2)
_KEY_CONNECTED = ("{83DA6326-97A6-4088-9453-A1923F573B29}", 15)
_KEY_CLASS = ("{2BD67D8B-8BEB-48D5-87E0-6CDA3428040A}", 10)
# A keyboard over Bluetooth LE has no class of device. Its HID collection is a
# node of its own, named "Keyboard" / "Клавиатура HID", and it is the only trace
# of the keyboard that says so; see _read_nodes.
_BLE_HID_PREFIX = "HID\\{00001812-"
_KEYBOARD_SETUP_CLASS = "{4D36E96B-E325-11CE-BFC1-08002BE10318}"  # Windows' "Keyboard" class
_KEYBOARD_CLASS = 0x0540  # peripheral, with the keyboard bit set
_DIGCF_PRESENT = 0x02
_DIGCF_ALLCLASSES = 0x04
_INVALID_HANDLE = ctypes.c_void_p(-1).value


def _address(instance_id: str) -> str:
    """The device's Bluetooth address from a node's instance id, or "".

    ``BTHENUM\\DEV_AABBCCDDEEFF\\...`` and ``BTHLE\\DEV_AABBCCDDEEFF\\...`` are
    the device itself; its services carry the address after the last ``&`` or
    ``_`` (``BTHENUM\\{service}_VID...\\7&...&0&AABBCCDDEEFF_C00000000``).
    """
    upper = instance_id.upper()
    marker = upper.find("DEV_")
    if marker >= 0:
        candidate = upper[marker + 4:marker + 16]
        if len(candidate) == 12 and all(c in "0123456789ABCDEF" for c in candidate):
            return candidate
    tail = upper.rsplit("\\", 1)[-1]
    for part in reversed(tail.replace("_", "&").split("&")):
        if len(part) == 12 and all(c in "0123456789ABCDEF" for c in part):
            return part
    return ""


def _ble_hid_address(instance_id: str) -> str:
    """The address of a Bluetooth LE HID node, or "".

    ``HID\\{00001812-...}_DEV_VID&..._D101777C1871&COL01\\...`` carries the address
    of the device just before its collection (``&COL``).
    """
    match = re.search(r"_([0-9A-F]{12})&COL", instance_id.upper())
    return match.group(1) if match else ""


def _read_nodes() -> list[tuple[str, str, bool | None, int | None, int | None]]:
    setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
    setupapi.SetupDiGetClassDevsW.restype = ctypes.c_void_p
    setupapi.SetupDiGetClassDevsW.argtypes = [
        ctypes.POINTER(_Guid), wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD,
    ]
    setupapi.SetupDiEnumDeviceInfo.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DevInfoData),
    ]
    setupapi.SetupDiGetDevicePropertyW.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(_DevInfoData), ctypes.POINTER(_PropertyKey),
        ctypes.POINTER(wintypes.ULONG), ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), wintypes.DWORD,
    ]
    setupapi.SetupDiGetDeviceInstanceIdW.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(_DevInfoData), wintypes.LPWSTR, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    setupapi.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]

    # All classes, not just Bluetooth: the battery sits on the Hands-Free service
    # node (BTHENUM\{0000111E-...}), which Windows files under the System class.
    handle = setupapi.SetupDiGetClassDevsW(None, None, None, _DIGCF_PRESENT | _DIGCF_ALLCLASSES)
    if not handle or handle == _INVALID_HANDLE:
        return []
    keyboard_class = bytes(_Guid.parse(_KEYBOARD_SETUP_CLASS))

    def read(info: _DevInfoData, key: tuple[str, int]) -> bytes | None:
        prop_key = _key(*key)
        kind = wintypes.ULONG()
        size = wintypes.DWORD()
        buffer = ctypes.create_string_buffer(1024)
        ok = setupapi.SetupDiGetDevicePropertyW(
            handle, ctypes.byref(info), ctypes.byref(prop_key), ctypes.byref(kind),
            buffer, len(buffer), ctypes.byref(size), 0,
        )
        return buffer.raw[:size.value] if ok else None

    nodes = []
    try:
        index = 0
        while True:
            info = _DevInfoData()
            info.cbSize = ctypes.sizeof(info)
            if not setupapi.SetupDiEnumDeviceInfo(handle, index, ctypes.byref(info)):
                break
            index += 1
            identifier = ctypes.create_unicode_buffer(512)
            if not setupapi.SetupDiGetDeviceInstanceIdW(
                handle, ctypes.byref(info), identifier, len(identifier), None
            ):
                continue
            if identifier.value.upper().startswith(_BLE_HID_PREFIX):
                # Only the collections set up as keyboards count; the mouse and
                # system-control collections of the same device are skipped.
                if bytes(info.ClassGuid) != keyboard_class:
                    continue
                address = _ble_hid_address(identifier.value)
                raw = read(info, _KEY_CONNECTED)
                connected = bool(raw[0]) if raw else None
                if address:
                    nodes.append((False, address, "", connected, None, _KEYBOARD_CLASS))
                continue
            if not identifier.value.upper().startswith(_BLUETOOTH_BUS_PREFIXES):
                continue
            address = _address(identifier.value)
            if not address:
                continue  # the radio itself and other nodes that are not a device
            raw_name = read(info, _KEY_NAME)
            name = raw_name.decode("utf-16-le", "ignore").rstrip("\x00") if raw_name else ""
            raw = read(info, _KEY_CONNECTED)
            connected = bool(raw[0]) if raw else None
            raw = read(info, _KEY_BATTERY)
            battery = raw[0] if raw else None
            raw = read(info, _KEY_CLASS)
            class_of_device = int.from_bytes(raw[:4], "little") if raw and len(raw) >= 4 else None
            is_service = "DEV_" not in identifier.value.upper()
            nodes.append((is_service, address, name, connected, battery, class_of_device))
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(handle)
    # A device's own node goes before its services, so that its name is the
    # one ``merge`` keeps.
    nodes.sort(key=lambda node: node[0])
    return [node[1:] for node in nodes]


def scan() -> list[Device]:
    """Every paired Bluetooth headphone and keyboard; [] when nothing can be read."""
    try:
        return merge(_read_nodes())
    except Exception:
        return []
