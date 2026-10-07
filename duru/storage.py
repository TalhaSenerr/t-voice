"""Per-Windows-user protected preferences. Never persists audio or transcripts."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path

DEFAULTS = {
    "model": "turbo-ov", "language": "tr", "cleanup": True, "auto_insert": True,
    "hotkey": "F10", "terms": [], "replacements": {},
}


def data_dir() -> Path:
    path = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "T-Voice"
    path.mkdir(parents=True, exist_ok=True)
    return path


class DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _protect(data: bytes, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        raise OSError("T-Voice ayar koruması Windows gerektiriyor.")
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source, output = DataBlob(len(data), buffer), DataBlob()
    # CRYPTPROTECT_UI_FORBIDDEN; default user scope, never machine scope.
    if decrypt:
        fn = crypt.CryptUnprotectData
        fn.argtypes = [ctypes.POINTER(DataBlob), ctypes.c_void_p, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DataBlob)]
        ok = fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output))
    else:
        fn = crypt.CryptProtectData
        fn.argtypes = [ctypes.POINTER(DataBlob), wintypes.LPCWSTR, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DataBlob)]
        ok = fn(ctypes.byref(source), "T-Voice preferences", None, None, None, 1, ctypes.byref(output))
    if not ok:
        raise OSError("Windows ayar koruması başarısız oldu.")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.memset(output.pbData, 0, output.cbData)
        kernel.LocalFree(output.pbData)
        ctypes.memset(buffer, 0, len(data))


def validate_settings(value: dict) -> dict:
    if not isinstance(value, dict):
        raise ValueError("Geçersiz ayarlar.")
    result = {**DEFAULTS, "terms": [], "replacements": {}}
    for key, choices in (("model", {"turbo-ov", "small", "medium"}), ("language", {"tr", "en", "auto"})):
        if value.get(key) in choices:
            result[key] = value[key]
    for key in ("cleanup", "auto_insert"):
        if isinstance(value.get(key), bool):
            result[key] = value[key]
    if "auto_insert" in value and not isinstance(value["auto_insert"], bool):
        result["auto_insert"] = False
    hotkey = value.get("hotkey", "F10")
    if isinstance(hotkey, str) and len(hotkey) <= 40:
        result["hotkey"] = hotkey
    terms = value.get("terms", [])
    if isinstance(terms, list):
        result["terms"] = list(dict.fromkeys(t.strip()[:80] for t in terms[:200]
                                            if isinstance(t, str) and t.strip()))
    aliases = value.get("replacements", {})
    if isinstance(aliases, dict):
        result["replacements"] = {k.strip()[:80]: v.strip()[:80] for k, v in list(aliases.items())[:200]
                                  if isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip()}
    return result


def load_settings(path: Path | None = None) -> dict:
    use_legacy = path is None
    path = path or data_dir() / "preferences.dpapi"
    if not path.exists():
        if use_legacy:
            legacy = path.parent.parent / "Duru" / "preferences.dpapi"
            if legacy.is_file():
                migrated = load_settings(legacy)
                # The requested one-key workflow replaces v1.0's opt-in setup.
                # Later explicit preferences in T-Voice are always preserved.
                migrated["auto_insert"] = True
                save_settings(migrated, path)
                return migrated
        return validate_settings({})
    if path.stat().st_size > 128_000:
        raise ValueError("Ayar dosyası beklenenden büyük.")
    return validate_settings(json.loads(_protect(path.read_bytes(), decrypt=True)))


def save_settings(settings: dict, path: Path | None = None) -> None:
    path = path or data_dir() / "preferences.dpapi"
    encrypted = _protect(json.dumps(validate_settings(settings), ensure_ascii=False).encode("utf-8"))
    temp = path.with_suffix(".tmp")
    try:
        temp.write_bytes(encrypted)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
