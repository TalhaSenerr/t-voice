"""Backend contracts with fake native runtimes; no GPU or microphone required."""
import sys
import types

import numpy as np
import pytest

from duru.openvino_backend import OpenVinoBackend


@pytest.fixture
def native(monkeypatch, tmp_path):
    state = types.SimpleNamespace(devices=["CPU", "GPU"], calls=[], vad_calls=[], privacy=[],
                                  speech=[{"start": 4, "end": 8}], waveforms=[], failure=None,
                                  texts=[" Bugün GitHub ile ", " TypeScript yazdım. "], languages=["<|tr|>"],
                                  constructor_error=None)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setitem(sys.modules, "openvino_telemetry", object())

    class Pipeline:
        def __init__(self, *args, **kwargs):
            assert sys.modules["openvino_telemetry"] is None
            state.constructed = (args, kwargs)
            if state.constructor_error:
                raise state.constructor_error

        def generate(self, audio, **kwargs):
            state.waveforms.append(audio)
            state.calls.append((audio.copy(), kwargs))
            if state.failure:
                raise state.failure
            return types.SimpleNamespace(texts=state.texts, languages=state.languages)

    def detect(audio, **kwargs):
        assert state.privacy, "ONNX telemetry must be disabled before VAD"
        state.vad_calls.append((audio, kwargs))
        return state.speech

    monkeypatch.setitem(sys.modules, "openvino", types.SimpleNamespace(Core=lambda: types.SimpleNamespace(available_devices=state.devices)))
    monkeypatch.setitem(sys.modules, "openvino_genai", types.SimpleNamespace(WhisperPipeline=Pipeline))
    monkeypatch.setitem(sys.modules, "onnxruntime", types.SimpleNamespace(disable_telemetry_events=lambda: state.privacy.append("disabled")))
    monkeypatch.setitem(sys.modules, "faster_whisper.vad", types.SimpleNamespace(
        VadOptions=lambda **kwargs: kwargs, get_speech_timestamps=detect))
    state.model = tmp_path / "model"
    state.model.mkdir()
    state.local = tmp_path / "local"
    return state


def test_local_gpu_initialization_blocks_optional_telemetry_and_uses_model_cache(native):
    OpenVinoBackend(native.model)
    args, options = native.constructed
    assert args == (str(native.model), "GPU")
    assert options["CACHE_DIR"] == str(native.local / "T-Voice" / "cache" / "openvino")
    assert (native.local / "T-Voice" / "cache" / "openvino").is_dir()


def test_unavailable_gpu_has_actionable_error_without_silent_cpu_fallback(native):
    native.devices = ["CPU"]
    with pytest.raises(ValueError, match="Small"):
        OpenVinoBackend(native.model)
    assert not hasattr(native, "constructed")


def test_missing_local_model_is_rejected_before_native_initialization(native):
    with pytest.raises(ValueError, match="cihazda bulunamadı"):
        OpenVinoBackend(native.model / "missing")
    assert not hasattr(native, "constructed")


def test_native_initialization_failure_has_safe_actionable_error(native):
    native.constructor_error = RuntimeError("private native implementation details")
    with pytest.raises(ValueError, match="Small") as error:
        OpenVinoBackend(native.model)
    assert "private" not in str(error.value)


@pytest.mark.parametrize("samples", [0, 16000])
def test_silence_never_reaches_whisper_even_with_hotwords(native, samples):
    native.speech = []
    result = OpenVinoBackend(native.model).transcribe(np.zeros(samples, np.float32), "tr", "GitHub")
    assert result == {"text": "", "language": "tr"}
    assert native.calls == []


def test_speech_gate_preserves_complete_audio_and_uses_gpu_compatible_decode(native):
    audio = np.linspace(-0.2, 0.2, 20, dtype=np.float32)
    result = OpenVinoBackend(native.model).transcribe(audio, "tr", "GitHub, TypeScript")
    assert result == {"text": "Bugün GitHub ile TypeScript yazdım.", "language": "tr"}
    captured, options = native.calls[0]
    assert captured == audio.tolist()  # Includes all samples outside VAD's narrow span.
    assert native.vad_calls[0][0] is audio
    assert options == {"language": "<|tr|>", "task": "transcribe", "num_beams": 1,
                       "return_timestamps": True, "hotwords": "GitHub, TypeScript"}
    assert native.waveforms[0] == []
    assert np.count_nonzero(audio) == 20  # Engine, not backend, owns erasing this array.


@pytest.mark.parametrize("reported,expected", [(["en"], "en"), (["<|tr|>"], "tr"), ([], "auto"), ([""], "auto")])
def test_automatic_language_is_not_forced_and_reports_detected_language(native, reported, expected):
    native.languages = reported
    result = OpenVinoBackend(native.model).transcribe(np.ones(20, np.float32), "auto", None)
    assert result["language"] == expected
    assert "language" not in native.calls[0][1]
    assert "hotwords" not in native.calls[0][1]


def test_inference_failure_releases_waveform_references(native):
    native.failure = RuntimeError("inference failed")
    with pytest.raises(RuntimeError, match="inference failed"):
        OpenVinoBackend(native.model).transcribe(np.ones(20, np.float32), "tr", None)
    assert native.waveforms == [[]]
