"""Local-only speech recognition. Audio is mono float PCM at 16,000 Hz.

Model installation is deliberately a separate, explicit setup operation. This
module never downloads a missing model and never writes recordings to disk.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
from pathlib import Path
from typing import Any

# Force these BEFORE importing either Hugging Face or faster-whisper. Do not use
# setdefault: an inherited online setting must not weaken the application's mode.
for _flag in (
    "HF_HUB_OFFLINE",
    "TRANSFORMERS_OFFLINE",
    "HF_HUB_DISABLE_TELEMETRY",
    "DO_NOT_TRACK",
    "ORT_DISABLE_TELEMETRY",
):
    os.environ[_flag] = "1"

import numpy as np

SAMPLE_RATE = 16_000
MAX_DURATION_SECONDS = 600
MODEL_SPECS = {
    "turbo-ov": {
        "name": "large-v3-turbo",
        "label": "Turbo · Intel ekran kartı",
        "repo_id": "OpenVINO/whisper-large-v3-turbo-int8-ov",
        "size_mb": 828,
    },
    "small": {
        "name": "small",
        "label": "Small · Dengeli",
        "repo_id": "Systran/faster-whisper-small",
        "size_mb": 484,
    },
    "medium": {
        "name": "medium",
        "label": "Medium · Daha hassas",
        "repo_id": "Systran/faster-whisper-medium",
        "size_mb": 1530,
    },
}


def _complete_openvino_model(directory: Path) -> bool:
    try:
        for name in ("encoder_model", "decoder_model", "tokenizer", "detokenizer"):
            for suffix in ("xml", "bin"):
                path = directory / f"openvino_{name}.{suffix}"
                if not path.is_file() or not path.stat().st_size:
                    return False
                with path.open("rb") as stream:
                    if stream.read(80).startswith(b"version https://git-lfs.github.com/spec/"):
                        return False
        for name in ("config.json", "generation_config.json", "preprocessor_config.json", "tokenizer_config.json"):
            path = directory / name
            if not path.is_file() or not 0 < path.stat().st_size < 16 * 1024 * 1024:
                return False
            if not isinstance(json.loads(path.read_text(encoding="utf-8")), dict):
                return False
        return True
    except (OSError, ValueError, UnicodeError):
        return False


def _complete_model(directory: Path) -> bool:
    """Reject partial downloads, broken symlinks, LFS pointers and invalid JSON.

    This is a completeness check, not a cryptographic authenticity guarantee.
    The native inference library performs the final model-format validation.
    """
    try:
        required = [directory / name for name in ("model.bin", "config.json", "tokenizer.json")]
        vocabulary = [directory / name for name in ("vocabulary.json", "vocabulary.txt")]
        if not all(path.is_file() and path.stat().st_size > 0 for path in required):
            return False
        available_vocabulary = [path for path in vocabulary if path.is_file() and path.stat().st_size > 0]
        if not available_vocabulary:
            return False
        with required[0].open("rb") as model_file:
            if model_file.read(80).startswith(b"version https://git-lfs.github.com/spec/"):
                return False
        for path in required[1:]:
            # Bound metadata parsing; normal Whisper tokenizer files are < 4 MB.
            if path.stat().st_size > 16 * 1024 * 1024:
                return False
            with path.open("r", encoding="utf-8") as metadata:
                if not isinstance(json.load(metadata), dict):
                    return False
        vocabulary_valid = False
        for path in available_vocabulary:
            if path.stat().st_size > 16 * 1024 * 1024:
                continue
            if path.suffix == ".json":
                with path.open("r", encoding="utf-8") as metadata:
                    value = json.load(metadata)
                    vocabulary_valid = isinstance(value, (list, dict)) and bool(value)
            else:
                with path.open("r", encoding="utf-8") as metadata:
                    first_line = metadata.readline(256).strip()
                    vocabulary_valid = bool(first_line) and not first_line.startswith(
                        "version https://git-lfs.github.com/spec/"
                    )
            if vocabulary_valid:
                break
        if not vocabulary_valid:
            return False
        return True
    except (OSError, ValueError, UnicodeError):
        return False


def _cache_roots() -> list[Path]:
    roots = []
    for name in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
        if os.environ.get(name):
            roots.append(Path(os.environ[name]).expanduser())
    if os.environ.get("HF_HOME"):
        roots.append(Path(os.environ["HF_HOME"]).expanduser() / "hub")
    default_cache = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
    roots.append(default_cache / "huggingface" / "hub")
    roots.append(Path.home() / ".cache" / "huggingface" / "hub")
    return list(dict.fromkeys(roots))


def _snapshots(repository: Path) -> list[Path]:
    preferred = []
    try:
        revision = (repository / "refs" / "main").read_text(encoding="utf-8").strip()
        if re.fullmatch(r"[a-fA-F0-9]{40,64}", revision):
            preferred.append(repository / "snapshots" / revision)
    except (OSError, UnicodeError):
        pass
    try:
        snapshots = sorted(
            (path for path in (repository / "snapshots").iterdir() if path.is_dir()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        preferred.extend(snapshots)
    except OSError:
        pass
    return list(dict.fromkeys(preferred))


def discover_models() -> dict[str, Path]:
    """Find complete portable/app-local models or existing HF cache snapshots."""
    app_data = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    local_root = app_data / "T-Voice" / "models"
    legacy_root = app_data / "Duru" / "models"
    portable_root = (
        Path(sys.executable).parent / "models"
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parents[1] / "models"
    )
    result: dict[str, Path] = {}
    for key, spec in MODEL_SPECS.items():
        candidates = [portable_root / key, local_root / key, legacy_root / key]
        for cache in _cache_roots():
            repository = cache / ("models--" + spec["repo_id"].replace("/", "--"))
            candidates.extend(_snapshots(repository))
        for path in candidates:
            complete = _complete_openvino_model(path) if key == "turbo-ov" else _complete_model(path)
            if complete:
                result[key] = path.resolve()
                break
    return result


def _hotwords(terms: list[str] | None) -> str | None:
    """Limit hints so an oversized dictionary cannot dominate the audio."""
    if terms is None:
        return None
    if not isinstance(terms, list):
        raise ValueError("Terimler bir metin listesi olmalıdır.")
    selected: list[str] = []
    seen: set[str] = set()
    for term in terms[:100]:
        if not isinstance(term, str):
            continue
        value = " ".join(term.split())
        if not value or len(value) > 80 or any(ord(char) < 32 for char in value):
            continue
        if value.casefold() in seen:
            continue
        # Never add a partial word or term to the prompt budget.
        if len(", ".join(selected + [value])) > 400 or len(selected) >= 32:
            break
        selected.append(value)
        seen.add(value.casefold())
    return ", ".join(selected) or None


class SpeechEngine:
    """Reusable local model; serialize loading/transcription in a worker thread."""

    def __init__(self) -> None:
        self._model: Any = None
        self._model_key: str | None = None
        self._lock = threading.RLock()

    @property
    def model_key(self) -> str | None:
        return self._model_key

    def load(self, model_key: str) -> None:
        if model_key not in MODEL_SPECS:
            raise ValueError("Desteklenmeyen model. Listeden kurulu bir model seçin.")
        with self._lock:
            if self._model is not None and self._model_key == model_key:
                return
            local_model = discover_models().get(model_key)
            if local_model is None:
                raise FileNotFoundError(
                    f"{MODEL_SPECS[model_key]['label']} modeli cihazda bulunamadı veya eksik. "
                    "Önce model kurulumunu tamamlayın."
                )
            # Keep the import lazy: settings and model discovery work without the
            # native inference DLLs, and a missing model cannot trigger downloads.
            # VAD uses ONNX Runtime. Its telemetry is independent of HF settings.
            # The API must run before faster-whisper creates any VAD session.
            # Windows may emit initialization ETW diagnostics before this call;
            # the environment flag is a full opt-out only on supported platforms.
            import onnxruntime

            onnxruntime.disable_telemetry_events()
            # Release the previous native model before allocating its replacement.
            # Keep it when the requested local files are missing (checked above).
            self._model = None
            self._model_key = None
            if model_key == "turbo-ov":
                from duru.openvino_backend import OpenVinoBackend

                self._model = OpenVinoBackend(local_model)
                self._model_key = model_key
                return
            from faster_whisper import WhisperModel

            loaded = WhisperModel(
                str(local_model),
                device="cpu",
                compute_type="int8",
                cpu_threads=max(1, min(6, (os.cpu_count() or 4) - 1)),
                num_workers=1,
                local_files_only=True,
            )
            self._model = loaded
            self._model_key = model_key

    def transcribe(
        self,
        audio: np.ndarray,
        language: str = "tr",
        terms: list[str] | None = None,
    ) -> dict[str, str | float]:
        """Return raw recognition, with no rewriting or persisted audio.

        The caller supplies mono, normalized floating-point PCM sampled at 16 kHz.
        Sampling rate cannot be inferred from an array. The caller owns and must
        erase its input; this method erases its separate working buffer on exit.
        Native libraries/OS may retain allocations: this is not guaranteed secure
        RAM erasure. ``duration`` is input length in seconds, including silence.
        """
        if not isinstance(audio, np.ndarray) or audio.ndim != 1:
            raise ValueError("Ses 16 kHz, tek kanallı bir NumPy dizisi olmalıdır.")
        if not np.issubdtype(audio.dtype, np.floating):
            raise ValueError("Ses örnekleri -1 ile 1 arasında ondalıklı sayılar olmalıdır.")
        if audio.size > SAMPLE_RATE * MAX_DURATION_SECONDS:
            raise ValueError("Tek kayıt en fazla 10 dakika olabilir.")
        if not np.isfinite(audio).all():
            raise ValueError("Ses geçersiz örnekler içeriyor.")
        if audio.size and (audio.min() < -1 or audio.max() > 1):
            raise ValueError("Ses örnekleri -1 ile 1 arasında olmalıdır.")
        if language not in ("tr", "en", "auto"):
            raise ValueError("Dil Türkçe, İngilizce veya otomatik olmalıdır.")
        hints = _hotwords(terms)
        duration = audio.size / SAMPLE_RATE
        with self._lock:
            if self._model is None:
                raise RuntimeError("Önce konuşma modelini yükleyin.")
            empty = {"text": "", "language": language, "duration": duration}
            if not audio.size:
                return empty
            # Always copy; never overwrite the caller's array unexpectedly.
            working = np.array(audio, dtype=np.float32, copy=True, order="C")
            segments = None
            info = None
            try:
                if self._model_key == "turbo-ov":
                    result = self._model.transcribe(working, language, hints)
                    return {**result, "duration": duration}
                segments, info = self._model.transcribe(
                    working,
                    language=None if language == "auto" else language,
                    task="transcribe",
                    beam_size=5,
                    temperature=0.0,
                    condition_on_previous_text=False,
                    initial_prompt=None,
                    hotwords=hints,
                    vad_filter=True,
                    vad_parameters={"min_silence_duration_ms": 500, "speech_pad_ms": 250},
                    no_speech_threshold=0.6,
                    log_prob_threshold=-1.0,
                    compression_ratio_threshold=2.4,
                    log_progress=False,
                )
                # Avoid decoding a prompt-only segment when VAD finds no speech.
                if info.duration_after_vad <= 0:
                    return empty
                text = " ".join(segment.text.strip() for segment in segments).strip()
                return {"text": text, "language": info.language, "duration": duration}
            finally:
                try:
                    if segments is not None and callable(getattr(segments, "close", None)):
                        segments.close()
                finally:
                    working.fill(0)
                    segments = None
                    info = None
