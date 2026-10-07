"""Close only the hidden Duru process created by our startup smoke test."""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
report_path = ROOT / '.test-artifacts' / 'startup-smoke.json'
report = json.loads(report_path.read_text(encoding='utf-8-sig'))
target_pid = int(report['Pid'])
u = ctypes.WinDLL('user32', use_last_error=True)
k = ctypes.WinDLL('kernel32', use_last_error=True)
callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
u.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
k.OpenProcess.restype = wintypes.HANDLE
k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
k.CloseHandle.argtypes = [wintypes.HANDLE]

process = k.OpenProcess(0x00100000 | 0x1000, False, target_pid)
if not process:
    raise RuntimeError('The smoke process no longer exists')
try:
    path = ctypes.create_unicode_buffer(32768)
    length = wintypes.DWORD(len(path))
    if not k.QueryFullProcessImageNameW(process, 0, path, ctypes.byref(length)):
        raise RuntimeError('Cannot verify smoke process identity')
    if Path(path.value).resolve() != (ROOT / 'dist' / 'Duru' / 'Duru.exe').resolve():
        raise RuntimeError('Process identity mismatch; no window touched')
    found = []
    @callback_type
    def inspect(hwnd, _):
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == target_pid:
            title = ctypes.create_unicode_buffer(512)
            u.GetWindowTextW(hwnd, title, len(title))
            if title.value.startswith('Duru ·'):
                found.append((hwnd, title.value))
        return True
    u.EnumWindows(inspect, 0)
    if not found:
        raise RuntimeError('Hidden main window not found')
    report.update({'WindowFound': True, 'Title': found[0][1], 'HiddenStartup': True,
                   'CloseRequested': bool(u.PostMessageW(found[0][0], 0x10, 0, 0))})
    report['Closed'] = k.WaitForSingleObject(process, 8000) == 0
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True))
finally:
    k.CloseHandle(process)
