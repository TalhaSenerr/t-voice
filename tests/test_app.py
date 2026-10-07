"""Controller lifecycle tests without microphone, model, disk or key access."""

from __future__ import annotations

import copy
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6 import QtCore, QtWidgets

import duru.app as desktop


@pytest.fixture(scope="module")
def qt_app():
    # Windows' platform is retained for the native dispatch tests in the suite.
    # The widgets here are never shown and never acquire foreground focus.
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    previous = application.quitOnLastWindowClosed()
    application.setQuitOnLastWindowClosed(False)
    yield application
    application.setQuitOnLastWindowClosed(previous)


class FakeHotkey(QtCore.QObject):
    triggered = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.started = False

    def start(self):
        self.started = True
        return True

    def stop(self):
        self.started = False


class FakeRecorder(QtCore.QObject):
    level = QtCore.Signal(float)
    limit_reached = QtCore.Signal()
    failed = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.starts = 0
        self.discards = 0

    def start(self):
        self.starts += 1

    def stop(self):
        return np.ones(16_000, dtype=np.float32)

    def discard(self):
        self.discards += 1


class FakeEngine:
    def __init__(self):
        self.loads = []
        self.calls = 0
        self.on_load = None
        self.on_transcribe = None

    def load(self, model):
        self.loads.append(model)
        if self.on_load:
            self.on_load()

    def transcribe(self, audio, language, terms):
        self.calls += 1
        if self.on_transcribe:
            self.on_transcribe()
        return {"text": "Eee, bugün deployment yapalım.", "duration": 1.0,
                "language": "tr"}


def wait_until(qt_app, predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.005)
    assert predicate(), "Qt worker did not reach the expected state"


@pytest.fixture
def controlled(qt_app, monkeypatch):
    monkeypatch.setattr(desktop, "HotkeyManager", FakeHotkey)
    monkeypatch.setattr(desktop, "Recorder", FakeRecorder)
    monkeypatch.setattr(desktop, "SpeechEngine", FakeEngine)
    monkeypatch.setattr(desktop, "discover_models", lambda: {"small": Path("local-fixture")})
    saved, inserted = [], []
    monkeypatch.setattr(desktop, "save_settings", lambda settings: saved.append(copy.deepcopy(settings)))
    monkeypatch.setattr(desktop, "insert_text", lambda text, hwnd: (inserted.append((text, hwnd)) or True, "Yazıldı"))
    monkeypatch.setattr(desktop, "foreground_window", lambda: 789)
    monkeypatch.setattr(desktop, "keys_released", lambda: True)
    window = desktop.MainWindow()
    controller = desktop.Controller(qt_app, window, desktop.validate_settings({"auto_insert": True}))
    release = threading.Event()
    bundle = SimpleNamespace(controller=controller, window=window, saved=saved,
                             inserted=inserted, app=qt_app, release=release)
    try:
        yield bundle
    finally:
        release.set()
        if isinstance(controller.thread, QtCore.QThread):
            controller.cancel()
            wait_until(qt_app, lambda: controller.thread is None)
        else:
            controller.thread = controller.worker = None
        controller.elapsed_timer.stop()
        controller.insertion_timer.stop()
        controller.feedback_timer.stop()
        controller.save_timer.stop()
        window._settings_timer.stop()
        controller.hotkey.stop()
        window.removeEventFilter(controller)
        window.close()
        controller.indicator.close()
        controller.indicator.deleteLater()
        window.deleteLater()
        controller.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)


@pytest.mark.parametrize("outcome", ["success", "value_error", "exception",
                                     "cancel_before", "cancel_load", "cancel_transcribe"])
def test_worker_erases_audio_on_every_exit(qt_app, outcome):
    audio = np.full(16_000, 0.4, dtype=np.float32)
    engine = FakeEngine()
    worker = desktop.SpeechWorker(engine, desktop.validate_settings({}), audio=audio)
    results, errors, finished = [], [], []
    worker.result.connect(results.append)
    worker.failed.connect(errors.append)
    worker.finished.connect(lambda: finished.append(True))

    if outcome == "value_error":
        def fail():
            raise ValueError("Ses biçimi uygun değil.")
        engine.on_transcribe = fail
    elif outcome == "exception":
        def fail():
            raise RuntimeError("private model implementation detail")
        engine.on_transcribe = fail
    elif outcome == "cancel_before":
        worker.cancelled.set()
    elif outcome == "cancel_load":
        engine.on_load = worker.cancelled.set
    elif outcome == "cancel_transcribe":
        engine.on_transcribe = worker.cancelled.set

    worker.run()
    assert np.count_nonzero(audio) == 0
    assert worker.audio is None
    assert worker.path is None
    assert finished == [True]
    if outcome == "success":
        assert len(results) == 1
        assert results[0]["text"].startswith("Eee")
        assert "deployment" in results[0]["cleaned"]
        assert not results[0]["cleaned"].startswith("Eee")
        assert not errors
    elif outcome in {"value_error", "exception"}:
        assert len(errors) == 1
        assert not results
        assert "private model implementation detail" not in errors[0]
    else:
        assert not results and not errors
        if outcome == "cancel_before":
            assert not engine.loads and not engine.calls
        elif outcome == "cancel_load":
            assert not engine.calls


def test_file_worker_wipes_decoded_audio_and_drops_path(qt_app, monkeypatch):
    decoded = np.ones(4000, dtype=np.float32)
    decoded_paths = []

    def decode(path, cancelled):
        decoded_paths.append(path)
        return decoded

    monkeypatch.setattr(desktop, "decode_file", decode)
    worker = desktop.SpeechWorker(FakeEngine(), desktop.validate_settings({}), path="private-fixture.wav")
    worker.run()
    assert decoded_paths == ["private-fixture.wav"]
    assert np.count_nonzero(decoded) == 0
    assert worker.path is None and worker.audio is None


def test_already_cancelled_file_worker_never_opens_file(qt_app, monkeypatch):
    def unexpected(*args):
        pytest.fail("An already cancelled job must not read its audio file")

    monkeypatch.setattr(desktop, "decode_file", unexpected)
    worker = desktop.SpeechWorker(FakeEngine(), desktop.validate_settings({}), path="private-fixture.wav")
    worker.cancelled.set()
    worker.run()
    assert worker.path is None


def test_closing_during_inference_waits_for_worker_and_discards_result(controlled):
    c, window = controlled.controller, controlled.window
    entered = threading.Event()
    audio = np.full(16_000, 0.2, dtype=np.float32)

    def hold_inference():
        entered.set()
        assert controlled.release.wait(3)

    c.engine.on_transcribe = hold_inference
    c._run_worker(audio=audio)
    wait_until(controlled.app, entered.is_set)
    active_thread = c.thread
    active_worker = c.worker
    assert window.close() is False
    assert c.closing
    assert c.thread is active_thread
    assert active_thread.isRunning()
    assert active_worker.cancelled.is_set()
    controlled.release.set()
    wait_until(controlled.app, lambda: c.thread is None)
    assert np.count_nonzero(audio) == 0
    assert not c.raw_text and not c.has_result
    assert not controlled.inserted
    assert not c.hotkey.started


def test_stale_capture_error_cannot_unlock_a_running_job(controlled, monkeypatch):
    c = controlled.controller
    job = object()
    c.thread = job
    c.worker = SimpleNamespace(cancelled=threading.Event(), settings=copy.deepcopy(c.settings))
    c.state = "transcribing"

    def unexpected_dialog(*args):
        pytest.fail("A second import must not open while another job is running")

    monkeypatch.setattr(desktop.QFileDialog, "getOpenFileName", unexpected_dialog)
    c.capture_failed("Late audio callback failure")
    assert c.state == "transcribing"
    c.toggle_recording()
    c.hotkey_triggered()
    c.start_recording(None)
    c.import_audio()
    assert c.thread is job
    assert c.recorder.starts == 0
    assert c.recorder.discards == 0


def test_disabling_auto_insert_before_result_takes_effect_immediately(controlled):
    c, window = controlled.controller, controlled.window
    c.worker = SimpleNamespace(cancelled=threading.Event(), settings=copy.deepcopy(c.settings))
    c.target = 789
    assert c.settings["auto_insert"]
    window.insert_checkbox.setChecked(False)
    # No event processing: the UI debounce has intentionally not fired yet.
    c._result({"text": "Özel metin", "cleaned": "Özel metin", "duration": 1})
    assert c.pending_insert is None
    assert not c.insertion_timer.isActive()
    assert not controlled.inserted
    assert window.editor_text() == "Özel metin"


def test_disabling_auto_insert_cancels_an_already_pending_send(controlled):
    c, window = controlled.controller, controlled.window
    c.pending_insert = ("Özel metin", 789, time.monotonic() + 2)
    c.insertion_timer.start()
    window.insert_checkbox.setChecked(False)
    c._try_insert()
    assert c.pending_insert is None
    assert not c.insertion_timer.isActive()
    assert not controlled.inserted


def test_closing_saves_current_ui_before_settings_debounce(controlled):
    c, window = controlled.controller, controlled.window
    window.insert_checkbox.setChecked(False)
    window.language_combo.setCurrentIndex(window.language_combo.findData("en"))
    window.cleanup_checkbox.setChecked(False)
    assert c.settings["language"] == "tr"
    assert window._settings_timer.isActive()
    assert window.close()
    assert controlled.saved
    saved = controlled.saved[-1]
    assert saved["language"] == "en"
    assert saved["cleanup"] is False
    assert saved["auto_insert"] is False


def test_worker_failure_message_survives_return_to_idle(controlled):
    c, window = controlled.controller, controlled.window
    c.worker = SimpleNamespace(cancelled=threading.Event())
    c.state = "transcribing"
    c._failed("Model açılamadı; yeniden dene.")
    c._worker_finished()
    assert c.state == "idle"
    assert "Model açılamadı" in window.status_label.text()


def test_recording_uses_models_discovered_at_startup(controlled, monkeypatch):
    c = controlled.controller

    def unexpected_discovery():
        pytest.fail("Starting a recording must use the cached model list")

    monkeypatch.setattr(desktop, "discover_models", unexpected_discovery)
    for _ in range(2):
        c.start_recording(None)
        assert c.state == "recording"
        c.cancel()
    assert c.recorder.starts == 2
    assert c.engine.loads == []
    assert c.engine.calls == 0


class FakeTrayIcon(QtCore.QObject):
    activated = QtCore.Signal(object)
    ActivationReason = QtWidgets.QSystemTrayIcon.ActivationReason

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.visible = False
        self.messages = []

    @staticmethod
    def isSystemTrayAvailable():
        return True

    def setIcon(self, icon):
        self.icon = icon

    def setToolTip(self, text):
        self.tooltip = text

    def setContextMenu(self, menu):
        self.menu = menu

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False

    def showMessage(self, *args):
        self.messages.append(args)


@pytest.fixture
def background_controlled(qt_app, monkeypatch):
    monkeypatch.setattr(desktop, "HotkeyManager", FakeHotkey)
    monkeypatch.setattr(desktop, "Recorder", FakeRecorder)
    monkeypatch.setattr(desktop, "SpeechEngine", FakeEngine)
    monkeypatch.setattr(desktop, "QSystemTrayIcon", FakeTrayIcon)
    monkeypatch.setattr(desktop, "discover_models", lambda: {"small": Path("local-fixture")})
    monkeypatch.setattr(desktop, "save_settings", lambda settings: None)
    inserted, quit_calls = [], []
    monkeypatch.setattr(desktop, "insert_text", lambda text, hwnd: (inserted.append((text, hwnd)) or True, "Yazıldı"))
    monkeypatch.setattr(desktop, "foreground_window", lambda: 789)
    monkeypatch.setattr(desktop, "keys_released", lambda: True)
    monkeypatch.setattr(qt_app, "quit", lambda: quit_calls.append(True))
    window = desktop.MainWindow()
    controller = desktop.Controller(qt_app, window, desktop.validate_settings({}),
                                    enable_tray=True, preload=False)
    release = threading.Event()
    bundle = SimpleNamespace(controller=controller, window=window, app=qt_app,
                             release=release, inserted=inserted, quit_calls=quit_calls)
    try:
        yield bundle
    finally:
        release.set()
        controller.request_exit()
        wait_until(qt_app, lambda: controller.thread is None and controller.warmup_thread is None)
        controller.elapsed_timer.stop()
        controller.insertion_timer.stop()
        controller.feedback_timer.stop()
        controller.save_timer.stop()
        window._settings_timer.stop()
        controller.hotkey.stop()
        window.removeEventFilter(controller)
        window.close()
        controller.indicator.close()
        controller.indicator.deleteLater()
        window.deleteLater()
        controller.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)


def test_tray_close_cancels_recording_and_keeps_f10_available(background_controlled):
    c, window = background_controlled.controller, background_controlled.window
    c.start_recording(None)
    assert c.state == "recording"

    assert window.close() is False

    assert c.recorder.discards == 1
    assert c.state == "idle"
    assert not c.closing
    assert c.hotkey.started
    assert not window.isVisible()
    assert not c.indicator.isVisible()
    assert not background_controlled.quit_calls


def test_background_warmup_prepares_model_without_starting_capture(background_controlled):
    c = background_controlled.controller
    entered = threading.Event()

    def hold_load():
        entered.set()
        assert background_controlled.release.wait(3)

    c.engine.on_load = hold_load
    c.start_preload()
    wait_until(background_controlled.app, entered.is_set)
    active_thread = c.warmup_thread
    assert active_thread.isRunning()
    c.start_preload()
    assert c.warmup_thread is active_thread
    assert c.recorder.starts == 0
    assert c.engine.calls == 0
    assert c.thread is None
    # Explicit recording is available while preparation runs in the background.
    c.start_recording(None)
    assert c.state == "recording"
    assert c.recorder.starts == 1
    assert active_thread.isRunning()
    assert c.engine.calls == 0
    c.cancel()
    background_controlled.release.set()
    wait_until(background_controlled.app, lambda: c.warmup_thread is None)
    assert c.engine.loads == ["small"]
    assert c.state == "idle"
    assert c.recorder.starts == 1


def test_exit_waits_for_warmup_to_finish(background_controlled):
    c = background_controlled.controller
    entered = threading.Event()

    def hold_load():
        entered.set()
        assert background_controlled.release.wait(3)

    c.engine.on_load = hold_load
    c.start_preload()
    wait_until(background_controlled.app, entered.is_set)
    active_worker, active_thread = c.warmup_worker, c.warmup_thread

    c.request_exit()

    assert c.closing
    assert active_worker.cancelled.is_set()
    assert active_thread.isRunning()
    assert not background_controlled.quit_calls
    c.hotkey_triggered()
    assert c.recorder.starts == 0
    background_controlled.release.set()
    wait_until(background_controlled.app, lambda: c.warmup_thread is None and background_controlled.quit_calls)
    assert background_controlled.quit_calls == [True]
    assert not c.hotkey.started
    assert c.recorder.starts == 0
    assert c.engine.calls == 0


def test_exit_from_tray_waits_for_inference_and_erases_audio(background_controlled):
    c = background_controlled.controller
    entered = threading.Event()
    audio = np.full(16_000, 0.2, dtype=np.float32)

    def hold_inference():
        entered.set()
        assert background_controlled.release.wait(3)

    c.engine.on_transcribe = hold_inference
    c._run_worker(audio=audio)
    wait_until(background_controlled.app, entered.is_set)
    active_worker, active_thread = c.worker, c.thread

    c.request_exit()

    assert c.closing
    assert active_worker.cancelled.is_set()
    assert active_thread.isRunning()
    assert not background_controlled.quit_calls
    background_controlled.release.set()
    wait_until(background_controlled.app, lambda: c.thread is None and background_controlled.quit_calls)
    assert background_controlled.quit_calls == [True]
    assert np.count_nonzero(audio) == 0
    assert not c.has_result
    assert not background_controlled.inserted


def test_exit_waits_for_both_warmup_and_speech_threads(background_controlled):
    c = background_controlled.controller
    warmup_entered, speech_entered = threading.Event(), threading.Event()
    release_warmup = threading.Event()
    audio = np.full(16_000, 0.2, dtype=np.float32)

    def hold_warmup():
        warmup_entered.set()
        assert release_warmup.wait(3)

    def hold_speech():
        speech_entered.set()
        assert background_controlled.release.wait(3)

    try:
        c.engine.on_load = hold_warmup
        c.start_preload()
        wait_until(background_controlled.app, warmup_entered.is_set)
        c.engine.on_load = None
        c.engine.on_transcribe = hold_speech
        c._run_worker(audio=audio)
        wait_until(background_controlled.app, speech_entered.is_set)

        c.request_exit()
        release_warmup.set()
        wait_until(background_controlled.app, lambda: c.warmup_thread is None)
        assert c.thread is not None
        assert not background_controlled.quit_calls

        background_controlled.release.set()
        wait_until(background_controlled.app, lambda: c.thread is None and background_controlled.quit_calls)
        assert background_controlled.quit_calls == [True]
        assert np.count_nonzero(audio) == 0
        assert not background_controlled.inserted
    finally:
        release_warmup.set()


@pytest.mark.parametrize("outcome", ["success", "cancel_before", "failure", "cancel_failure"])
def test_warmup_worker_always_finishes_and_suppresses_cancelled_errors(qt_app, outcome):
    engine = FakeEngine()
    worker = desktop.ModelWarmup(engine, "small")
    finished, errors = [], []
    worker.finished.connect(lambda: finished.append(True))
    worker.failed.connect(errors.append)

    if outcome == "cancel_before":
        worker.cancelled.set()
    elif outcome in {"failure", "cancel_failure"}:
        def fail():
            if outcome == "cancel_failure":
                worker.cancelled.set()
            raise RuntimeError("private model implementation detail")
        engine.on_load = fail

    worker.run()

    assert finished == [True]
    assert engine.loads == ([] if outcome == "cancel_before" else ["small"])
    assert engine.calls == 0
    assert len(errors) == (1 if outcome == "failure" else 0)
    assert all("private model implementation detail" not in message for message in errors)


def test_hidden_worker_error_stays_visible_after_thread_returns_to_idle(background_controlled):
    c, window = background_controlled.controller, background_controlled.window

    def fail():
        raise RuntimeError("private decoder path and dictated content")

    c.engine.on_transcribe = fail
    c.start_recording(789)
    c.stop_recording()
    wait_until(background_controlled.app, lambda: c.thread is None)

    assert c.state == "idle"
    assert not window.isVisible()
    assert c.indicator.isVisible()
    assert c.feedback_timer.isActive()
    assert c.indicator.status_text.property("error")
    assert c.indicator.status_text.text() == window.status_label.text()
    assert "private decoder" not in c.indicator.status_text.text()
    assert c.indicator.stop_button.isHidden()
    assert c.indicator.cancel_button.isHidden()
    assert not background_controlled.inserted

    # Exercise the actual connected timeout without waiting six seconds.
    c.feedback_timer.start(1)
    wait_until(background_controlled.app, lambda: not c.indicator.isVisible())
    assert c.state == "idle"


@pytest.mark.parametrize("raw", ["", "Eee, hmm."])
def test_no_speech_feedback_is_visible_generic_and_never_inserted(background_controlled, monkeypatch, raw):
    c, window = background_controlled.controller, background_controlled.window
    previous = "Önceki gizli konuşma içeriği"
    window.set_result(previous, previous, 1)
    monkeypatch.setattr(c.engine, "transcribe", lambda *_args: {
        "text": raw, "duration": 1.0, "language": "tr",
    })
    c.start_recording(789)
    c.stop_recording()
    wait_until(background_controlled.app, lambda: c.thread is None)

    assert window.editor_text() == ""
    assert c.raw_text == raw
    assert c.indicator.isVisible()
    message = c.indicator.status_text.text()
    assert "Konuşma algılanmadı" in message
    assert previous not in message
    assert not raw or raw not in message
    assert c.indicator.status_text.property("error")
    assert c.pending_insert is None
    assert not c.insertion_timer.isActive()
    assert not background_controlled.inserted
    assert c.indicator.stop_button.isHidden()
    assert c.indicator.cancel_button.isHidden()


@pytest.mark.parametrize("failure", ["focus_changed", "input_rejected", "shortcut_held"])
def test_hidden_insertion_failure_keeps_text_out_of_feedback(background_controlled, monkeypatch, failure):
    c = background_controlled.controller
    secret = "Bu metin yalnızca düzenleyicide kalmalı."
    c.pending_insert = (secret, 789, time.monotonic() - 1)
    c.insertion_timer.start()
    if failure == "focus_changed":
        monkeypatch.setattr(desktop, "foreground_window", lambda: 790)
    elif failure == "input_rejected":
        monkeypatch.setattr(desktop, "insert_text", lambda *_args: (False, "Windows metni yazamadı."))
    else:
        monkeypatch.setattr(desktop, "keys_released", lambda: False)

    c._try_insert()

    assert c.pending_insert is None
    assert not c.insertion_timer.isActive()
    assert c.indicator.isVisible()
    assert c.feedback_timer.isActive()
    assert c.indicator.status_text.property("error")
    assert secret not in c.indicator.status_text.text()
    assert not background_controlled.inserted
    assert c.indicator.stop_button.isHidden()
    assert c.indicator.cancel_button.isHidden()


def test_new_recording_cancels_old_feedback_timeout(background_controlled):
    c = background_controlled.controller
    c._feedback("Önceki işlem tamamlanamadı.", True)
    c.feedback_timer.start(1)

    c.start_recording(789)

    assert c.state == "recording"
    assert not c.feedback_timer.isActive()
    assert c.indicator.isVisible()
    assert not c.indicator.status_text.property("error")
    assert not c.indicator.stop_button.isHidden()
    assert not c.indicator.cancel_button.isHidden()
    assert not c.indicator.elapsed_label.isHidden()
    # A scheduled event turn must not let the previous result hide this capture.
    reached = []
    QtCore.QTimer.singleShot(20, lambda: reached.append(True))
    wait_until(background_controlled.app, lambda: reached)
    assert c.indicator.isVisible()
    c.cancel()
    assert not c.indicator.isVisible()


@pytest.mark.parametrize("new_model_fails", [False, True])
def test_model_change_during_warmup_prepares_latest_model_once(background_controlled, new_model_fails):
    c, window = background_controlled.controller, background_controlled.window
    c.available_models["turbo-ov"] = Path("local-turbo-fixture")
    window.set_models({"small": "Small", "turbo-ov": "Turbo"})
    entered = threading.Event()

    def load():
        if c.engine.loads == ["small"]:
            entered.set()
            assert background_controlled.release.wait(3)
        elif new_model_fails:
            raise RuntimeError("private model path")
        c.engine.model_key = c.engine.loads[-1]

    c.engine.on_load = load
    c.start_preload()
    wait_until(background_controlled.app, entered.is_set)
    active_thread = c.warmup_thread
    updated = window.get_settings() | {"model": "turbo-ov"}
    window.apply_settings(updated)
    c.settings_changed(updated)
    background_controlled.app.processEvents()

    assert c.preload_pending
    assert c.warmup_thread is active_thread
    assert c.engine.loads == ["small"]
    assert c.recorder.starts == 0

    background_controlled.release.set()
    wait_until(background_controlled.app, lambda: c.engine.loads == ["small", "turbo-ov"]
               and c.warmup_thread is None)
    assert not c.preload_pending
    assert c.state == "idle"
    assert c.recorder.starts == 0
    assert c.engine.calls == 0

    # Drain timer/event turns: a failed warmup must not retry itself forever.
    reached = []
    QtCore.QTimer.singleShot(40, lambda: reached.append(True))
    wait_until(background_controlled.app, lambda: reached)
    assert c.engine.loads == ["small", "turbo-ov"]
    assert c.warmup_thread is None
    if new_model_fails:
        assert "önceden hazırlanamadı" in window.status_label.text()
        assert "private model" not in window.status_label.text()


def test_recording_cancel_resumes_model_change_deferred_by_warmup(background_controlled):
    c, window = background_controlled.controller, background_controlled.window
    c.available_models["turbo-ov"] = Path("local-turbo-fixture")
    window.set_models({"small": "Small", "turbo-ov": "Turbo"})
    entered = threading.Event()

    def load():
        if c.engine.loads == ["small"]:
            entered.set()
            assert background_controlled.release.wait(3)
        c.engine.model_key = c.engine.loads[-1]

    c.engine.on_load = load
    c.start_preload()
    wait_until(background_controlled.app, entered.is_set)
    updated = window.get_settings() | {"model": "turbo-ov"}
    window.apply_settings(updated)
    c.settings_changed(updated)
    c.start_recording(789)
    background_controlled.release.set()
    wait_until(background_controlled.app, lambda: c.warmup_thread is None)
    background_controlled.app.processEvents()

    assert c.state == "recording"
    assert c.preload_pending
    assert c.engine.loads == ["small"]

    c.cancel()

    wait_until(background_controlled.app, lambda: c.engine.loads == ["small", "turbo-ov"]
               and c.warmup_thread is None)
    assert c.state == "idle"
    assert not c.preload_pending
    assert c.recorder.starts == 1
    assert c.recorder.discards == 1
    assert c.engine.calls == 0
