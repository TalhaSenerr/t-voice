"""Recorder tests replace sounddevice completely; no real microphone is opened."""

import sys
import threading
import types

import numpy as np
import pytest

import duru.recorder as recording


@pytest.fixture
def fake_audio_device(monkeypatch):
    class CallbackAbort(Exception):
        pass

    class CallbackStop(Exception):
        pass

    state = types.SimpleNamespace(stream=None, fail_start=False, fail_stop=False, fail_close=False)

    class InputStream:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.callback = kwargs["callback"]
            self.closed = False
            self.stopped = False
            state.stream = self

        def start(self):
            if state.fail_start:
                raise RuntimeError("device refused start")

        def stop(self):
            self.stopped = True
            if state.fail_stop:
                raise RuntimeError("device refused stop")

        def close(self):
            self.closed = True
            if state.fail_close:
                raise RuntimeError("device refused close")

    state.module = types.SimpleNamespace(
        InputStream=InputStream, CallbackAbort=CallbackAbort, CallbackStop=CallbackStop
    )
    monkeypatch.setitem(sys.modules, "sounddevice", state.module)
    monkeypatch.setattr(recording, "RATE", 10)
    monkeypatch.setattr(recording, "MAX_SECONDS", 1)
    return state


def feed(state, values, status=None):
    array = np.array(values, dtype=np.float32).reshape(-1, 1)
    state.stream.callback(array, len(values), None, status)


def test_capture_stop_returns_independent_pcm_and_wipes_capture_buffer(fake_audio_device):
    recorder = recording.Recorder()
    recorder.start()
    device = fake_audio_device
    owned_buffer = recorder._buffer
    feed(device, [0.2, 0.3, 0.4])
    audio = recorder.stop()
    np.testing.assert_allclose(audio, [0.2, 0.3, 0.4])
    assert not np.shares_memory(audio, owned_buffer)
    assert np.all(owned_buffer == 0)
    assert recorder._buffer is None
    assert recorder._position == 0
    assert device.stream.closed and device.stream.stopped


def test_discard_erases_buffer_and_late_callback_cannot_write(fake_audio_device):
    recorder = recording.Recorder()
    recorder.start()
    owned_buffer = recorder._buffer
    feed(fake_audio_device, [0.2] * 4)
    recorder.discard()
    assert np.all(owned_buffer == 0)
    with pytest.raises(fake_audio_device.module.CallbackAbort):
        feed(fake_audio_device, [0.9] * 3)
    assert np.all(owned_buffer == 0)


def test_previous_stream_callback_cannot_contaminate_new_recording(fake_audio_device):
    recorder = recording.Recorder()
    recorder.start()
    old_callback = fake_audio_device.stream.callback
    recorder.discard()
    recorder.start()
    errors = []
    recorder.failed.connect(errors.append)
    try:
        with pytest.raises(fake_audio_device.module.CallbackAbort):
            old_callback(np.full((2, 1), 0.9, dtype=np.float32), 2, None, None)
        with pytest.raises(fake_audio_device.module.CallbackAbort):
            old_callback(np.full((2, 1), 0.9, dtype=np.float32), 2, None, "old overflow")
        assert recorder._position == 0
        assert np.all(recorder._buffer == 0)
        assert errors == []
    finally:
        recorder.discard()


def test_capture_limit_stops_at_exact_bound_without_overflow(fake_audio_device):
    recorder = recording.Recorder()
    limits = []
    recorder.limit_reached.connect(lambda: limits.append(True))
    recorder.start()
    owned_buffer = recorder._buffer
    feed(fake_audio_device, [0.1] * 7)
    with pytest.raises(fake_audio_device.module.CallbackStop):
        feed(fake_audio_device, [0.8] * 6)
    assert limits == [True]
    assert recorder._position == 10
    audio = recorder.stop()
    assert audio.size == 10
    np.testing.assert_allclose(audio, [0.1] * 7 + [0.8] * 3)
    assert np.all(owned_buffer == 0)


def test_device_failure_aborts_without_copying_bad_samples(fake_audio_device):
    recorder = recording.Recorder()
    errors = []
    recorder.failed.connect(errors.append)
    recorder.start()
    owned_buffer = recorder._buffer
    with pytest.raises(fake_audio_device.module.CallbackAbort):
        feed(fake_audio_device, [0.9] * 3, status="overflow")
    assert len(errors) == 1
    assert recorder._position == 0
    recorder.discard()
    assert np.all(owned_buffer == 0)


def test_start_failure_closes_device_and_releases_buffer(fake_audio_device):
    fake_audio_device.fail_start = True
    recorder = recording.Recorder()
    with pytest.raises(RuntimeError):
        recorder.start()
    assert recorder._buffer is None
    assert recorder._stream is None
    assert fake_audio_device.stream.closed


@pytest.mark.parametrize("method", ["stop", "discard"])
@pytest.mark.parametrize("failure", ["fail_stop", "fail_close"])
def test_shutdown_failure_still_erases_capture_buffer(fake_audio_device, method, failure):
    recorder = recording.Recorder()
    recorder.start()
    owned_buffer = recorder._buffer
    feed(fake_audio_device, [0.2] * 4)
    setattr(fake_audio_device, failure, True)
    try:
        getattr(recorder, method)()
    except RuntimeError:
        pass
    assert np.all(owned_buffer == 0)
    assert recorder._buffer is None
    assert recorder._stream is None
    assert fake_audio_device.stream.closed


@pytest.fixture
def fake_decoder(tmp_path, monkeypatch):
    state = types.SimpleNamespace(
        samples=[], flush_samples=[], copied=[], decoded=0, has_audio=True,
        opened=0, closed=False, options=None, resampler_args=None, on_decode=None
    )

    class TrackedArray(np.ndarray):
        def copy(self, *args, **kwargs):
            copied = super().copy(*args, **kwargs)
            state.copied.append(copied)
            return copied

    class Frame:
        def __init__(self, samples):
            self.samples = samples

        def to_ndarray(self):
            return np.array(self.samples, dtype=np.float32).reshape(1, -1).view(TrackedArray)

    class Container:
        @property
        def streams(self):
            return types.SimpleNamespace(audio=[object()] if state.has_audio else [])

        def __enter__(self):
            return self

        def __exit__(self, *args):
            state.closed = True

        def decode(self, **kwargs):
            for samples in state.samples:
                state.decoded += 1
                if state.on_decode:
                    state.on_decode()
                yield Frame(samples)

    class Resampler:
        def __init__(self, **kwargs):
            state.resampler_args = kwargs

        def resample(self, frame):
            if frame is None:
                return [Frame(samples) for samples in state.flush_samples]
            return [frame]

    def open_media(path, **kwargs):
        state.opened += 1
        state.options = kwargs.get("options", {})
        return Container()

    monkeypatch.setitem(sys.modules, "av", types.SimpleNamespace(open=open_media, AudioResampler=Resampler))
    monkeypatch.setattr(recording, "RATE", 4)
    monkeypatch.setattr(recording, "MAX_SECONDS", 2)
    state.path = tmp_path / "sample.wav"
    state.path.write_bytes(b"test media; replaced decoder")
    return state


def test_decode_streams_and_resamples_to_mono_while_wiping_chunks(fake_decoder):
    decoder = fake_decoder
    decoder.samples = [[0.1, 0.2], [0.3]]
    decoder.flush_samples = [[0.4]]
    audio = recording.decode_file(str(decoder.path))
    np.testing.assert_allclose(audio, [0.1, 0.2, 0.3, 0.4])
    assert audio.dtype == np.float32
    assert audio.ndim == 1
    assert decoder.resampler_args == {"format": "fltp", "layout": "mono", "rate": 4}
    assert decoder.closed
    assert decoder.copied and all(np.all(chunk == 0) for chunk in decoder.copied)


def test_decode_blocks_network_protocols_even_inside_local_playlist(fake_decoder):
    fake_decoder.samples = [[0.1, 0.2]]
    recording.decode_file(str(fake_decoder.path))
    assert fake_decoder.options.get("protocol_whitelist") == "file"


def test_long_file_rejected_during_streaming_without_decoding_remainder(fake_decoder):
    fake_decoder.samples = [[0.1] * 3] * 1000
    with pytest.raises(ValueError, match="10 dakika"):
        recording.decode_file(str(fake_decoder.path))
    assert fake_decoder.decoded == 3
    assert len(fake_decoder.copied) == 2
    assert all(np.all(chunk == 0) for chunk in fake_decoder.copied)
    assert fake_decoder.closed


def test_resampler_flush_also_obeys_duration_cap(fake_decoder):
    fake_decoder.samples = [[0.1] * 8]
    fake_decoder.flush_samples = [[0.2]]
    with pytest.raises(ValueError, match="10 dakika"):
        recording.decode_file(str(fake_decoder.path))
    assert all(np.all(chunk == 0) for chunk in fake_decoder.copied)
    assert fake_decoder.closed


@pytest.mark.parametrize("has_audio", [True, False])
def test_empty_or_video_only_file_is_rejected(fake_decoder, has_audio):
    fake_decoder.has_audio = has_audio
    with pytest.raises(ValueError):
        recording.decode_file(str(fake_decoder.path))
    assert fake_decoder.closed


def test_decode_missing_file_never_opens_decoder(fake_decoder):
    with pytest.raises(ValueError):
        recording.decode_file(str(fake_decoder.path.parent / "missing.wav"))
    assert fake_decoder.opened == 0


def test_decode_cancellation_stops_between_frames_and_wipes_chunks(fake_decoder):
    cancelled = threading.Event()
    fake_decoder.samples = [[0.1, 0.2]] * 100

    def cancel_after_first():
        if fake_decoder.decoded == 2:
            cancelled.set()

    fake_decoder.on_decode = cancel_after_first
    # A cancelled import may return an empty array or raise a cancellation error;
    # the worker discards either result and must never continue decoding input.
    try:
        result = recording.decode_file(str(fake_decoder.path), cancelled=cancelled)
        assert result.size == 0
    except (ValueError, RuntimeError):
        pass
    assert fake_decoder.decoded == 2
    assert all(np.all(chunk == 0) for chunk in fake_decoder.copied)
    assert fake_decoder.closed


def test_already_cancelled_import_does_not_open_media(fake_decoder):
    cancelled = threading.Event()
    cancelled.set()
    try:
        result = recording.decode_file(str(fake_decoder.path), cancelled=cancelled)
        assert result.size == 0
    except (ValueError, RuntimeError):
        pass
    assert fake_decoder.opened == 0
