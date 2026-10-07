"""Win32 bridge tests use a fake user32; they never type or register real keys."""

import ctypes
import os
import sys

import pytest
from PySide6 import QtCore, QtWidgets

from duru import windows


class FakeUser32:
    def __init__(self):
        self.foreground = 0x1_12345678
        self.pid = os.getpid() + 1
        self.pressed = set()
        self.sent = []
        self.send_result = None
        self.exists = True
        self.registration_ok = True
        self.registrations = []
        self.unregistrations = []

    def GetForegroundWindow(self):
        return self.foreground

    def GetWindowThreadProcessId(self, hwnd, process_id):
        ctypes.cast(process_id, ctypes.POINTER(windows.DWORD))[0] = self.pid
        return 1 if self.exists else 0

    def IsWindow(self, hwnd):
        return self.exists

    def GetAsyncKeyState(self, key):
        return 0x8000 if key in self.pressed else 0

    def SendInput(self, count, events, size):
        self.sent.append((count, bytes(events), size))
        return count if self.send_result is None else self.send_result

    def RegisterHotKey(self, *arguments):
        self.registrations.append(arguments)
        return self.registration_ok

    def UnregisterHotKey(self, *arguments):
        self.unregistrations.append(arguments)
        return True


@pytest.fixture
def user32(monkeypatch):
    fake = FakeUser32()
    monkeypatch.setattr(windows, "_user32", fake)
    return fake


@pytest.fixture(scope="module")
def qt_app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_input_struct_matches_windows_abi():
    is_64_bit = ctypes.sizeof(ctypes.c_void_p) == 8
    assert ctypes.sizeof(windows.INPUT) == (40 if is_64_bit else 28)
    assert ctypes.sizeof(windows.KEYBDINPUT) == (24 if is_64_bit else 16)
    assert windows.INPUT.data.offset == (8 if is_64_bit else 4)
    assert ctypes.sizeof(windows.MSG) == (48 if is_64_bit else 32)


def test_hwnd_and_process_checks_preserve_pointer_width(user32):
    assert windows.foreground_window() == 0x1_12345678
    assert not windows.is_own_window(user32.foreground)
    user32.pid = os.getpid()
    assert windows.is_own_window(user32.foreground)
    assert not windows.is_own_window(0)


def test_unicode_typing_contains_turkish_and_emoji_surrogates(user32):
    text = "İğüşçö ı 👩\u200d💻"
    success, _ = windows.insert_text(text, user32.foreground)
    assert success
    count, raw, size = user32.sent[0]
    assert size == ctypes.sizeof(windows.INPUT)
    events = (windows.INPUT * count).from_buffer_copy(raw)
    expected = text.encode("utf-16-le")
    units = [int.from_bytes(expected[i:i + 2], "little")
             for i in range(0, len(expected), 2)]
    assert count == len(units) * 2
    for i, unit in enumerate(units):
        down, up = events[i * 2:i * 2 + 2]
        assert down.type == up.type == windows.INPUT_KEYBOARD
        assert down.ki.wVk == up.ki.wVk == 0
        assert down.ki.wScan == up.ki.wScan == unit
        assert down.ki.dwFlags == windows.KEYEVENTF_UNICODE
        assert up.ki.dwFlags == windows.KEYEVENTF_UNICODE | windows.KEYEVENTF_KEYUP


def test_control_characters_cannot_submit_or_navigate(user32):
    text = "  ilk\r\nikinci\talan\x00\x1b\x08\u202e!\ud800  "
    assert windows.safe_input_text(text) == "ilk ikinci alan!"
    assert windows.insert_text(text, user32.foreground)[0]
    count, raw, _ = user32.sent[0]
    events = (windows.INPUT * count).from_buffer_copy(raw)
    assert not {event.ki.wScan for event in events} & {0, 8, 9, 10, 13, 27}


@pytest.mark.parametrize("failure", ["focus", "own", "closed", "pid", "held"])
def test_rejected_targets_never_send_input(user32, failure):
    target = user32.foreground
    if failure == "focus":
        user32.foreground += 1
    elif failure == "own":
        user32.pid = os.getpid()
    elif failure == "closed":
        user32.exists = False
    elif failure == "pid":
        user32.pid = 0
    elif failure == "held":
        user32.pressed.add(0x11)
    success, message = windows.insert_text("özel metin", target)
    assert not success
    assert message
    assert user32.sent == []


def test_focus_is_checked_again_after_conversion(user32, monkeypatch):
    original = windows._unicode_inputs
    target = user32.foreground

    def move_focus(text):
        events = original(text)
        user32.foreground += 1
        return events

    monkeypatch.setattr(windows, "_unicode_inputs", move_focus)
    assert not windows.insert_text("özel metin", target)[0]
    assert not user32.sent


@pytest.mark.parametrize("count", [0, 1, 3])
def test_partial_input_is_an_error_and_is_never_retried(user32, count):
    user32.send_result = count
    success, message = windows.insert_text("abc", user32.foreground)
    assert not success
    assert f"{count}/6" in message
    assert "yönetici" in message
    assert len(user32.sent) == 1


@pytest.mark.parametrize("text", ["", "\t\n\x1b", "a" * 50_001],
                         ids=["empty", "controls", "too_long"])
def test_invalid_or_excessive_text_never_sends(user32, text):
    assert not windows.insert_text(text, user32.foreground)[0]
    assert not user32.sent


def test_shortcut_modifier_release_guard(user32):
    assert windows.keys_released()
    for key in (0x11, 0x12, 0x10, 0x5B, 0x5C, windows.VK_F10):
        user32.pressed = {key}
        assert not windows.keys_released()
    user32.pressed = {0x41}
    assert windows.keys_released()  # Ordinary character keys are not inspected.


def test_held_f10_blocks_text_injection(user32):
    user32.pressed = {windows.VK_F10}
    assert not windows.insert_text("text", user32.foreground)[0]
    assert not user32.sent


def test_held_space_does_not_block_text_injection(user32):
    user32.pressed = {0x20}
    assert windows.keys_released()
    assert windows.insert_text("text", user32.foreground)[0]
    assert len(user32.sent) == 1


def test_hotkey_registration_and_native_dispatch(user32, qt_app):
    manager = windows.HotkeyManager()
    triggered = []
    manager.triggered.connect(lambda: triggered.append(True))
    try:
        assert manager.start()
        assert manager.start()
        assert len(user32.registrations) == 1
        assert user32.registrations[0] == (
            None, manager._hotkey_id,
            0x4000,  # MOD_NOREPEAT only: no Ctrl, Alt, Shift or Windows modifier.
            0x79,  # VK_F10.
        )
        message = windows.MSG()
        message.message = windows.WM_HOTKEY
        message.wParam = manager._hotkey_id
        assert manager._filter.nativeEventFilter(
            b"windows_dispatcher_MSG", ctypes.addressof(message)
        ) == (True, 0)
        assert triggered == [True]
        message.wParam += 1
        assert manager._filter.nativeEventFilter(
            b"windows_dispatcher_MSG", ctypes.addressof(message)
        ) == (False, 0)
        assert manager._filter.nativeEventFilter(b"other", 0) == (False, 0)
        assert triggered == [True]
    finally:
        manager.stop()
        manager.stop()
    assert len(user32.unregistrations) == 1
    assert not manager.registered


def test_hotkey_conflict_is_visible(user32, qt_app):
    user32.registration_ok = False
    manager = windows.HotkeyManager()
    assert not manager.start()
    assert not manager.registered
    assert "F10" in manager.last_error
    manager.stop()
    assert not user32.unregistrations


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native dispatcher")
def test_qt_receives_a_native_hotkey_message_without_real_keys(user32, qt_app):
    # Post a message to this test process only. Registration and SendInput stay
    # mocked, so this checks the PySide callback ABI without affecting the user.
    if qt_app.platformName() != "windows":
        pytest.skip("A real Windows Qt platform is required for native messages")
    native_user32 = ctypes.WinDLL("user32", use_last_error=True)
    native_user32.PostThreadMessageW.argtypes = [
        windows.DWORD, windows.UINT, windows.ULONG_PTR, ctypes.c_ssize_t
    ]
    native_user32.PostThreadMessageW.restype = windows.BOOL
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentThreadId.argtypes = []
    kernel32.GetCurrentThreadId.restype = windows.DWORD
    manager = windows.HotkeyManager()
    received = []
    manager.triggered.connect(lambda: received.append(True))
    try:
        assert manager.start()
        assert native_user32.PostThreadMessageW(
            kernel32.GetCurrentThreadId(), windows.WM_HOTKEY,
            manager._hotkey_id, 0,
        )
        loop = QtCore.QEventLoop()
        manager.triggered.connect(loop.quit)
        QtCore.QTimer.singleShot(100, loop.quit)
        loop.exec()
        assert received == [True]
    finally:
        manager.stop()
