"""Small Win32 bridge for an explicit hotkey and clipboard-free Unicode input.

No keyboard hook is installed. The only key-state queries concern modifiers and
the shortcut's F10 key. SendInput has no target-window parameter: checking the
foreground window immediately before dispatch reduces, but cannot eliminate, a
concurrent focus change by another application.
"""

from __future__ import annotations

import ctypes
import os
import sys
import unicodedata

from PySide6 import QtCore


WORD = ctypes.c_uint16
DWORD = ctypes.c_uint32
LONG = ctypes.c_int32
UINT = ctypes.c_uint32
BOOL = ctypes.c_int32
ULONG_PTR = ctypes.c_size_t
HWND = ctypes.c_void_p

WM_HOTKEY = 0x0312
MOD_NOREPEAT = 0x4000
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
VK_F10 = 0x79
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
MAX_INPUT_CHARACTERS = 50_000


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", LONG),
        ("dy", LONG),
        ("mouseData", DWORD),
        ("dwFlags", DWORD),
        ("time", DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", WORD),
        ("wScan", WORD),
        ("dwFlags", DWORD),
        ("time", DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", DWORD), ("wParamL", WORD), ("wParamH", WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    # MOUSEINPUT is required even though we only send keys: Win32 validates the
    # complete INPUT size, which is 40 bytes on x64 and 28 bytes on x86.
    _anonymous_ = ("data",)
    _fields_ = [("type", DWORD), ("data", _INPUTUNION)]


class POINT(ctypes.Structure):
    _fields_ = [("x", LONG), ("y", LONG)]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", HWND),
        ("message", UINT),
        ("wParam", ULONG_PTR),
        ("lParam", ctypes.c_ssize_t),
        ("time", DWORD),
        ("pt", POINT),
        ("lPrivate", DWORD),
    ]


def _load_user32():
    if sys.platform != "win32":
        return None
    library = ctypes.WinDLL("user32", use_last_error=True)
    library.GetForegroundWindow.argtypes = []
    library.GetForegroundWindow.restype = HWND
    library.GetWindowThreadProcessId.argtypes = [HWND, ctypes.POINTER(DWORD)]
    library.GetWindowThreadProcessId.restype = DWORD
    library.IsWindow.argtypes = [HWND]
    library.IsWindow.restype = BOOL
    library.GetAsyncKeyState.argtypes = [ctypes.c_int]
    library.GetAsyncKeyState.restype = ctypes.c_int16
    library.SendInput.argtypes = [UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    library.SendInput.restype = UINT
    library.RegisterHotKey.argtypes = [HWND, ctypes.c_int, UINT, UINT]
    library.RegisterHotKey.restype = BOOL
    library.UnregisterHotKey.argtypes = [HWND, ctypes.c_int]
    library.UnregisterHotKey.restype = BOOL
    return library


_user32 = _load_user32()


def foreground_window() -> int:
    """Return the actual foreground HWND without changing window focus."""
    if _user32 is None:
        return 0
    return int(_user32.GetForegroundWindow() or 0)


def _window_process_id(hwnd: int) -> int:
    if _user32 is None or not hwnd:
        return 0
    process_id = DWORD()
    if not _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id)):
        return 0
    return int(process_id.value)


def is_own_window(hwnd: int) -> bool:
    """Identify all windows of this process, including dialogs and overlays."""
    return bool(hwnd) and _window_process_id(hwnd) == os.getpid()


def keys_released(trigger_key: int = VK_F10) -> bool:
    """Check only shortcut/modifier state; never capture typed characters."""
    if _user32 is None:
        return True
    # Ctrl, Alt, Shift, left/right Windows and the active shortcut key. A held modifier can turn
    # otherwise ordinary text into an application action.
    keys = (0x11, 0x12, 0x10, 0x5B, 0x5C, trigger_key)
    return all(not (_user32.GetAsyncKeyState(key) & 0x8000) for key in keys)


def safe_input_text(text: str) -> str:
    """Flatten whitespace and remove control/format characters before typing.

    Emoji joiners are preserved; isolated UTF-16 surrogates and bidi controls
    are discarded. No Enter, Tab, Escape or other control input is generated.
    """
    characters: list[str] = []
    for character in text:
        if character.isspace():
            characters.append(" ")
        elif unicodedata.category(character).startswith("C"):
            if character in ("\u200c", "\u200d"):
                characters.append(character)
        else:
            characters.append(character)
    return " ".join("".join(characters).split())


def _unicode_inputs(text: str):
    encoded = text.encode("utf-16-le")
    units = [int.from_bytes(encoded[index:index + 2], "little")
             for index in range(0, len(encoded), 2)]
    events = (INPUT * (len(units) * 2))()
    for index, unit in enumerate(units):
        for offset, flags in enumerate((KEYEVENTF_UNICODE,
                                        KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)):
            event = events[index * 2 + offset]
            event.type = INPUT_KEYBOARD
            event.ki = KEYBDINPUT(0, unit, flags, 0, 0)
    return events


def insert_text(text: str, target_hwnd: int, trigger_key: int = VK_F10) -> tuple[bool, str]:
    """Type into an unchanged external foreground window, without clipboard.

    A success reports that Windows accepted the input events, not that every
    application supports Unicode input. A rejected or partial send is never
    retried automatically, because that could duplicate text.
    """
    if _user32 is None:
        return False, "Başka uygulamaya yazma yalnızca Windows'ta kullanılabilir."
    if not isinstance(text, str):
        return False, "Yazılacak metin geçersiz."
    if len(text) > MAX_INPUT_CHARACTERS:
        return False, "Metin otomatik yazma için çok uzun; T-Voice editöründe tutuldu."
    clean_text = safe_input_text(text)
    if not clean_text:
        return False, "Yazılacak bir metin yok."
    if not isinstance(target_hwnd, int) or target_hwnd <= 0:
        return False, "Hedef pencere bulunamadı; metin T-Voice editöründe tutuldu."
    if not _user32.IsWindow(target_hwnd) or not _window_process_id(target_hwnd):
        return False, "Hedef pencere kapandı; metin T-Voice editöründe tutuldu."
    if is_own_window(target_hwnd):
        return False, "Metin T-Voice editöründe hazır."
    if foreground_window() != target_hwnd:
        return False, "Etkin pencere değişti; metin T-Voice editöründe tutuldu."
    if not keys_released(trigger_key):
        return False, "Kısayol tuşlarını bırakın; metin T-Voice editöründe tutuldu."

    events = _unicode_inputs(clean_text)
    # Recheck after allocation so a slow/large conversion cannot send text to a
    # newly foregrounded window. No SetForegroundWindow or clipboard fallback.
    if foreground_window() != target_hwnd or not keys_released(trigger_key):
        return False, "Odak veya tuş durumu değişti; metin T-Voice editöründe tutuldu."
    ctypes.set_last_error(0)
    sent = int(_user32.SendInput(len(events), events, ctypes.sizeof(INPUT)))
    if sent != len(events):
        error = ctypes.get_last_error()
        detail = f" Windows hata kodu: {error}." if error else ""
        return False, (
            f"Windows metnin tamamını gönderemedi ({sent}/{len(events)} olay). "
            "Hedef uygulamanın yönetici yetkisi veya giriş kısıtlaması olabilir. "
            "Otomatik tekrar yapılmadı; metni kontrol edin." + detail
        )
    return True, "Metin etkin uygulamaya yazıldı."


class _HotkeyFilter(QtCore.QAbstractNativeEventFilter):
    def __init__(self, manager: "HotkeyManager"):
        super().__init__()
        self.manager = manager

    def nativeEventFilter(self, event_type, message):  # noqa: N802 (Qt API)
        if bytes(event_type) not in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            return False, 0
        # Shiboken VoidPtr can be false-y because its reported buffer length is
        # zero even when its address is valid. Inspect the address, not bool().
        if not self.manager.registered or message is None or int(message) == 0:
            return False, 0
        native_message = MSG.from_address(int(message))
        if (native_message.message == WM_HOTKEY
                and native_message.wParam == self.manager._hotkey_id):
            self.manager.triggered.emit()
            return True, 0
        return False, 0


def parse_hotkey(shortcut: str) -> tuple[int, int]:
    """Convert one Qt portable key sequence into a Win32 hotkey tuple."""
    sequence = QtGui.QKeySequence(shortcut)
    if sequence.count() != 1 or sequence.isEmpty():
        raise ValueError("Tek bir kısayol tuşu seç.")
    chord = sequence[0].toCombined()
    modifiers = 0
    for qt_modifier, win_modifier in (
        (QtCore.Qt.KeyboardModifier.ControlModifier, MOD_CONTROL),
        (QtCore.Qt.KeyboardModifier.AltModifier, MOD_ALT),
        (QtCore.Qt.KeyboardModifier.ShiftModifier, MOD_SHIFT),
        (QtCore.Qt.KeyboardModifier.MetaModifier, MOD_WIN),
    ):
        if chord & qt_modifier.value:
            modifiers |= win_modifier
    key = chord & ~QtCore.Qt.KeyboardModifier.KeyboardModifierMask.value
    if QtCore.Qt.Key.Key_A <= key <= QtCore.Qt.Key.Key_Z:
        virtual_key = ord("A") + key - int(QtCore.Qt.Key.Key_A)
    elif QtCore.Qt.Key.Key_0 <= key <= QtCore.Qt.Key.Key_9:
        virtual_key = ord("0") + key - int(QtCore.Qt.Key.Key_0)
    elif QtCore.Qt.Key.Key_F1 <= key <= QtCore.Qt.Key.Key_F24:
        virtual_key = 0x70 + key - int(QtCore.Qt.Key.Key_F1)
    else:
        special = {
            int(QtCore.Qt.Key.Key_Space): 0x20,
            int(QtCore.Qt.Key.Key_Tab): 0x09,
            int(QtCore.Qt.Key.Key_Backspace): 0x08,
            int(QtCore.Qt.Key.Key_Insert): 0x2D,
            int(QtCore.Qt.Key.Key_Delete): 0x2E,
            int(QtCore.Qt.Key.Key_Home): 0x24,
            int(QtCore.Qt.Key.Key_End): 0x23,
            int(QtCore.Qt.Key.Key_PageUp): 0x21,
            int(QtCore.Qt.Key.Key_PageDown): 0x22,
            int(QtCore.Qt.Key.Key_Left): 0x25,
            int(QtCore.Qt.Key.Key_Up): 0x26,
            int(QtCore.Qt.Key.Key_Right): 0x27,
            int(QtCore.Qt.Key.Key_Down): 0x28,
        }
        virtual_key = special.get(key, 0)
    if not virtual_key:
        raise ValueError("Bu tuş Windows genel kısayolu olarak kullanılamıyor.")
    if not modifiers and virtual_key not in range(0x70, 0x88):
        raise ValueError("Tek başına yalnızca F1–F24 tuşları kullanılabilir.")
    return modifiers, virtual_key


class HotkeyManager(QtCore.QObject):
    """Register F10 on the Qt GUI thread without a keyboard hook."""

    triggered = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hotkey_id = 0x4455
        self._filter = _HotkeyFilter(self)
        self._app = None
        self._quit_connected = False
        self.registered = False
        self.last_error = ""
        self.shortcut = "F10"
        self.virtual_key = VK_F10

    def start(self, shortcut: str = "F10") -> bool:
        if self.registered:
            if shortcut == self.shortcut:
                return True
            self.stop()
        self.shortcut = shortcut
        app = QtCore.QCoreApplication.instance()
        if _user32 is None or app is None:
            self.last_error = "Genel kısayol için çalışan bir Windows uygulaması gerekli."
            return False
        if QtCore.QThread.currentThread() != app.thread():
            self.last_error = "Genel kısayol ana uygulama iş parçacığında başlatılmalı."
            return False
        try:
            modifiers, virtual_key = parse_hotkey(shortcut)
        except ValueError as exc:
            self.last_error = str(exc)
            return False
        if not _user32.RegisterHotKey(
            None, self._hotkey_id, modifiers | MOD_NOREPEAT, virtual_key
        ):
            self.last_error = f"{shortcut} başka bir uygulama tarafından kullanılıyor olabilir."
            return False
        self._app = app
        self.registered = True
        self.virtual_key = virtual_key
        app.installNativeEventFilter(self._filter)
        if not self._quit_connected:
            app.aboutToQuit.connect(self.stop)
            self._quit_connected = True
        self.last_error = ""
        return True

    @QtCore.Slot()
    def stop(self) -> None:
        if not self.registered:
            return
        if _user32 is not None:
            _user32.UnregisterHotKey(None, self._hotkey_id)
        if self._app is not None:
            self._app.removeNativeEventFilter(self._filter)
        self.registered = False
