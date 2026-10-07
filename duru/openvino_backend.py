"""Local Whisper Turbo on Intel graphics; the caller owns audio validation/wiping."""
from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Any

import numpy as np


class OpenVinoBackend:
    """A reusable GPU pipeline. SpeechEngine serializes all calls to this object."""

    def __init__(self, local_model: Path):
        self._pipeline: Any = None
        local_model = Path(local_model)
        if not local_model.is_dir():
            raise ValueError("Turbo GPU modeli cihazda bulunamadı. Modeli kur veya Small modelini seç.")
        for flag in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY", "DO_NOT_TRACK"):
            os.environ[flag] = "1"
        # OpenVINO's optional conversion telemetry otherwise initializes during
        # import. Blocking the import selects its own official telemetry_stub;
        # environment flags alone do not disable this dependency's network calls.
        sys.modules["openvino_telemetry"] = None
        try:
            import openvino as ov
            import openvino_genai as genai
            if "GPU" not in ov.Core().available_devices:
                raise ValueError("Intel grafik işlemcisi kullanılamıyor. Ayarlardan Small modelini seç.")
            cache = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "T-Voice" / "cache" / "openvino"
            cache.mkdir(parents=True, exist_ok=True)
            # This cache contains compiled model weights/kernels, never speech.
            self._pipeline = genai.WhisperPipeline(str(local_model), "GPU", CACHE_DIR=str(cache))
        except ValueError:
            raise
        except Exception:
            raise ValueError("Turbo GPU modeli hazırlanamadı. Ayarlardan Small modelini seçip tekrar dene.") from None

    def transcribe(self, working: np.ndarray, language: str, hints: str | None) -> dict[str, str]:
        empty = {"text": "", "language": language}
        if not working.size:
            return empty
        import onnxruntime
        onnxruntime.disable_telemetry_events()
        from faster_whisper.vad import VadOptions, get_speech_timestamps
        speech = get_speech_timestamps(
            working,
            vad_options=VadOptions(min_silence_duration_ms=500, speech_pad_ms=250),
            sampling_rate=16000,
        )
        if not speech:
            return empty
        # VAD is only a speech-presence gate. Concatenating its regions caused
        # this model to omit brief English words in Turkish synthetic speech.
        # Keep every original sample and its timing after the presence check.
        config = {"task": "transcribe", "num_beams": 1, "return_timestamps": True}
        if language != "auto":
            config["language"] = f"<|{language}|>"
        if hints:
            config["hotwords"] = hints
        # Intel GPU beam search >1 currently raises a native remote tensor error.
        # Timestamp generation preserves Whisper's long-form processing path.
        waveform = working.tolist()
        result = None
        try:
            result = self._pipeline.generate(waveform, **config)
            text = " ".join(part.strip() for part in result.texts).strip()
            languages = getattr(result, "languages", None)
            detected = languages[0] if languages else getattr(result, "language", language)
            if not isinstance(detected, str) or not detected.strip():
                detected = language
            detected = detected.strip().removeprefix("<|").removesuffix("|>")
            return {"text": text, "language": detected}
        finally:
            # Release Python float references even if native inference fails.
            # Native/OS copies cannot be promised to be securely erased.
            waveform.clear()
            result = None
