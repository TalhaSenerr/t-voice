import json
import os
import sys
import types
from pathlib import Path

import numpy as np
import pytest

import duru.engine as engine


def make_model(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "model.bin").write_bytes(b"local model fixture")
    (path / "config.json").write_text(json.dumps({"model_type": "Whisper"}), encoding="utf-8")
    (path / "tokenizer.json").write_text(json.dumps({"version": "1.0"}), encoding="utf-8")
    (path / "vocabulary.json").write_text('["hello"]', encoding="utf-8")
    return path


@pytest.fixture
def local_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "app"))
    monkeypatch.setattr(engine.sys, "frozen", True, raising=False)
    monkeypatch.setattr(engine.sys, "executable", str(tmp_path / "portable" / "Duru.exe"))
    monkeypatch.setattr(engine, "_cache_roots", lambda: [tmp_path / "cache"])
    return tmp_path


def test_discovery_prefers_app_model_and_ignores_incomplete_cache(local_environment):
    root = local_environment
    app = make_model(root / "app" / "Duru" / "models" / "small")
    make_model(root / "cache" / "models--Systran--faster-whisper-small" / "snapshots" / ("a" * 40))
    incomplete = make_model(root / "cache" / "models--Systran--faster-whisper-medium" / "snapshots" / ("b" * 40))
    (incomplete / "tokenizer.json").unlink()
    assert engine.discover_models() == {"small": app.resolve()}


def test_discovery_reads_hf_snapshot_without_network(local_environment):
    repository = local_environment / "cache" / "models--Systran--faster-whisper-medium"
    model = make_model(repository / "snapshots" / ("b" * 40))
    (repository / "refs").mkdir()
    (repository / "refs" / "main").write_text("b" * 40)
    assert engine.discover_models() == {"medium": model.resolve()}


def test_discovery_loads_portable_model_next_to_executable(local_environment):
    portable = make_model(local_environment / "portable" / "models" / "small")
    assert engine.discover_models() == {"small": portable.resolve()}


def test_discovery_loads_source_checkout_model(local_environment, monkeypatch):
    monkeypatch.setattr(engine.sys, "frozen", False)
    monkeypatch.setattr(engine, "__file__", str(local_environment / "source" / "duru" / "engine.py"))
    portable = make_model(local_environment / "source" / "models" / "small")
    assert engine.discover_models() == {"small": portable.resolve()}


@pytest.mark.parametrize("damage", ["empty_model", "lfs_pointer", "bad_json", "missing_vocabulary", "bad_vocabulary"])
def test_discovery_rejects_partial_models(local_environment, damage):
    model = make_model(local_environment / "app" / "Duru" / "models" / "small")
    if damage == "empty_model":
        (model / "model.bin").write_bytes(b"")
    elif damage == "lfs_pointer":
        (model / "model.bin").write_bytes(b"version https://git-lfs.github.com/spec/v1\noid sha256:123")
    elif damage == "bad_json":
        (model / "tokenizer.json").write_text("{unfinished")
    elif damage == "bad_vocabulary":
        (model / "vocabulary.json").write_text("unfinished")
    else:
        (model / "vocabulary.json").unlink()
    assert engine.discover_models() == {}


def test_load_requires_complete_local_model_and_forces_offline(monkeypatch, tmp_path):
    calls = []
    privacy_events = []

    def construct(*args, **kwargs):
        assert privacy_events == ["onnx-telemetry-disabled"]
        calls.append((args, kwargs))
        return object()

    monkeypatch.setitem(sys.modules, "onnxruntime", types.SimpleNamespace(
        disable_telemetry_events=lambda: privacy_events.append("onnx-telemetry-disabled")
    ))
    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=construct))
    monkeypatch.setattr(engine, "discover_models", lambda: {"small": tmp_path})
    speech = engine.SpeechEngine()
    speech.load("small")
    speech.load("small")
    assert len(calls) == 1
    assert calls[0][0] == (str(tmp_path),)
    assert calls[0][1]["local_files_only"] is True
    assert calls[0][1]["device"] == "cpu"
    assert calls[0][1]["compute_type"] == "int8"
    assert speech.model_key == "small"
    assert os.environ["HF_HUB_OFFLINE"] == "1"
    assert os.environ["ORT_DISABLE_TELEMETRY"] == "1"
    with pytest.raises(FileNotFoundError):
        speech.load("medium")
    assert len(calls) == 1
    assert speech.model_key == "small"


class FakeModel:
    def __init__(self, *, silence=False, fail=False):
        self.silence = silence
        self.fail = fail
        self.kwargs = None
        self.working = None
        self.closed = False

    def transcribe(self, working, **kwargs):
        self.kwargs = kwargs
        self.working = working
        if self.fail:
            raise RuntimeError("inference failed")
        owner = self

        class Segments:
            def __iter__(self):
                if owner.silence:
                    pytest.fail("VAD-rejected silence must never decode a prompt")
                yield types.SimpleNamespace(text=" Eee, bugün")
                yield types.SimpleNamespace(text=" deployment yapalım.")

            def close(self):
                owner.closed = True

        return Segments(), types.SimpleNamespace(
            language="tr", duration_after_vad=0 if self.silence else 1.0
        )


def with_model(model):
    speech = engine.SpeechEngine()
    speech._model = model
    return speech


def test_raw_transcription_is_local_bounded_and_erases_only_working_copy():
    model = FakeModel()
    original = np.full(16_000, 0.2, dtype=np.float32)
    result = with_model(model).transcribe(original, terms=["Next.js", "Next.js", "Duru"])
    assert result == {"text": "Eee, bugün deployment yapalım.", "language": "tr", "duration": 1.0}
    assert model.kwargs["task"] == "transcribe"
    assert model.kwargs["vad_filter"] is True
    assert model.kwargs["condition_on_previous_text"] is False
    assert model.kwargs["hotwords"] == "Next.js, Duru"
    assert model.closed
    assert np.all(model.working == 0)
    assert np.all(original == 0.2)


def test_silence_does_not_hallucinate_from_hints():
    model = FakeModel(silence=True)
    result = with_model(model).transcribe(np.zeros(16_000, dtype=np.float32), terms=["SecretProject"])
    assert result["text"] == ""
    assert model.closed
    assert np.all(model.working == 0)


def test_inference_error_also_erases_working_copy():
    model = FakeModel(fail=True)
    original = np.full(1600, 0.3, dtype=np.float32)
    with pytest.raises(RuntimeError, match="inference failed"):
        with_model(model).transcribe(original)
    assert np.all(model.working == 0)
    assert np.all(original == 0.3)


def test_generator_error_also_closes_and_erases_audio():
    class FailingIteratorModel(FakeModel):
        def transcribe(self, working, **kwargs):
            self.working = working

            def segments():
                try:
                    yield types.SimpleNamespace(text="partial")
                    raise RuntimeError("decoder failed")
                finally:
                    self.closed = True

            return segments(), types.SimpleNamespace(language="tr", duration_after_vad=1)

    model = FailingIteratorModel()
    with pytest.raises(RuntimeError, match="decoder failed"):
        with_model(model).transcribe(np.full(1600, 0.3, dtype=np.float32))
    assert model.closed
    assert np.all(model.working == 0)


@pytest.mark.parametrize(
    "audio",
    [
        "voice.wav",
        np.zeros((10, 2), dtype=np.float32),
        np.array([float("nan")], dtype=np.float32),
        np.array([float("inf")], dtype=np.float32),
        np.array([2.0], dtype=np.float32),
        np.array([12], dtype=np.int16),
        np.zeros(16_000 * 600 + 1, dtype=np.float32),
    ],
)
def test_invalid_audio_rejected_before_inference(audio):
    model = FakeModel()
    with pytest.raises(ValueError):
        with_model(model).transcribe(audio)
    assert model.working is None


def test_hotword_budget_never_splits_a_term_or_accepts_unbounded_hints():
    terms = [f"term{i}" for i in range(1000)]
    result = engine._hotwords(terms)
    assert len(result) <= 400
    assert len(result.split(", ")) <= 32
    assert all(term in terms for term in result.split(", "))
    assert engine._hotwords(["x" * 81, "", "GoodTerm"]) == "GoodTerm"


def test_auto_language_is_detection_not_translation():
    model = FakeModel()
    with_model(model).transcribe(np.full(1600, 0.2, dtype=np.float32), language="auto")
    assert model.kwargs["language"] is None
    assert model.kwargs["task"] == "transcribe"


def test_empty_audio_and_model_lifecycle():
    speech = engine.SpeechEngine()
    with pytest.raises(RuntimeError):
        speech.transcribe(np.zeros(0, dtype=np.float32))
    speech._model = FakeModel()
    assert speech.transcribe(np.zeros(0, dtype=np.float32))["text"] == ""
    assert speech._model.working is None
    with pytest.raises(ValueError):
        speech.load("../../remote")


def test_openvino_discovery_rejects_partial_and_lfs_models(local_environment):
    path = local_environment / "portable" / "models" / "turbo-ov"
    path.mkdir(parents=True)
    for name in ("encoder_model", "decoder_model", "tokenizer", "detokenizer"):
        for suffix in ("bin", "xml"):
            (path / f"openvino_{name}.{suffix}").write_bytes(b"fixture")
    for name in ("config.json", "generation_config.json", "preprocessor_config.json", "tokenizer_config.json"):
        (path / name).write_text("{}")
    assert engine.discover_models() == {"turbo-ov": path.resolve()}
    decoder = path / "openvino_decoder_model.bin"
    decoder.write_bytes(b"version https://git-lfs.github.com/spec/v1\noid sha256:123")
    assert engine.discover_models() == {}
    decoder.unlink()
    assert engine.discover_models() == {}


@pytest.mark.parametrize("fail", [False, True])
def test_gpu_backend_working_audio_is_wiped_after_success_or_failure(fail):
    class Backend:
        def transcribe(self, working, language, hints):
            self.working = working
            assert language == "tr" and hints == "GitHub"
            if fail:
                raise RuntimeError("native failure")
            return {"text": "GitHub", "language": "tr"}

    model = Backend()
    speech = with_model(model)
    speech._model_key = "turbo-ov"
    audio = np.full(16000, 0.25, dtype=np.float32)
    if fail:
        with pytest.raises(RuntimeError, match="native failure"):
            speech.transcribe(audio, terms=["GitHub"])
    else:
        assert speech.transcribe(audio, terms=["GitHub"]) == {"text": "GitHub", "language": "tr", "duration": 1.0}
    assert not np.any(model.working)
    assert np.all(audio == 0.25)
