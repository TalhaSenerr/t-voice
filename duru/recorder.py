"""Microphone capture stays in memory and has an explicit bounded lifetime."""
from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, Signal

RATE = 16_000
MAX_SECONDS = 600


class Recorder(QObject):
    level = Signal(float)
    limit_reached = Signal()
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lock = threading.Lock()
        self._buffer = None
        self._position = 0
        self._stream = None

    def start(self):
        import sounddevice as sd
        if self._stream is not None:
            raise RuntimeError("Kayıt zaten açık.")
        self._buffer = np.zeros(RATE * MAX_SECONDS, dtype=np.float32)
        self._position = 0
        capture_buffer = self._buffer

        def callback(indata, frames, _time, status):
            with self._lock:
                if self._buffer is not capture_buffer:
                    raise sd.CallbackAbort
                if status:
                    self.failed.emit("Mikrofon verisi kesildi. Mikrofonu ve ses ayarlarını kontrol et.")
                    raise sd.CallbackAbort
                remaining = len(self._buffer) - self._position
                count = min(frames, remaining)
                self._buffer[self._position:self._position + count] = indata[:count, 0]
                self._position += count
                rms = float(np.sqrt(np.mean(indata ** 2)))
            self.level.emit(min(1.0, rms * 7))
            if count == remaining:
                self.limit_reached.emit()
                raise sd.CallbackStop

        try:
            self._stream = sd.InputStream(samplerate=RATE, channels=1, dtype="float32",
                                          blocksize=1600, callback=callback)
            self._stream.start()
        except Exception:
            self.discard()
            raise RuntimeError("Mikrofon açılamadı. Windows > Gizlilik > Mikrofon iznini ve varsayılan giriş aygıtını kontrol et.") from None

    def _close_stream(self):
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
            finally:
                stream.close()

    def stop(self) -> np.ndarray:
        try:
            self._close_stream()
            with self._lock:
                return self._buffer[:self._position].copy() if self._buffer is not None else np.empty(0, np.float32)
        finally:
            with self._lock:
                self._wipe()

    def _wipe(self):
        if self._buffer is not None:
            self._buffer.fill(0)
        self._buffer = None
        self._position = 0

    def discard(self):
        try:
            self._close_stream()
        finally:
            with self._lock:
                self._wipe()


def decode_file(path: str, cancelled: threading.Event | None = None) -> np.ndarray:
    """Decode in bounded chunks; reject oversized/long input before accumulating it."""
    import av
    source = Path(path)
    if not source.is_file() or source.stat().st_size > 150 * 1024 * 1024:
        raise ValueError("En fazla 150 MB büyüklüğünde bir ses dosyası seç.")
    chunks = []
    total = 0
    def check_cancelled():
        if cancelled is not None and cancelled.is_set():
            raise ValueError("İşlem iptal edildi.")
    try:
        check_cancelled()
        with av.open(str(source), options={"protocol_whitelist": "file"}) as container:
            if not container.streams.audio:
                raise ValueError("Dosyada ses bulunamadı.")
            resampler = av.AudioResampler(format="fltp", layout="mono", rate=RATE)
            for frame in container.decode(audio=0):
                check_cancelled()
                for converted in resampler.resample(frame):
                    data = converted.to_ndarray().reshape(-1)
                    total += data.size
                    if total > RATE * MAX_SECONDS:
                        raise ValueError("Ses en fazla 10 dakika olabilir.")
                    chunks.append(data.copy())
            for converted in resampler.resample(None):
                data = converted.to_ndarray().reshape(-1)
                total += data.size
                if total > RATE * MAX_SECONDS:
                    raise ValueError("Ses en fazla 10 dakika olabilir.")
                chunks.append(data.copy())
        if not chunks:
            raise ValueError("Dosyada okunabilir ses bulunamadı.")
        check_cancelled()
        return np.concatenate(chunks).astype(np.float32, copy=False)
    finally:
        for chunk in chunks:
            chunk.fill(0)
