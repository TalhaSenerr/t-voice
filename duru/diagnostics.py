"""Explicit developer diagnostic mode, never run on normal application startup."""
import json
import os
import sys
import time
from pathlib import Path


def run(audio_path: str, report_path: str) -> int:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    from duru.engine import SpeechEngine, discover_models
    from duru.recorder import decode_file
    from duru.cleanup import clean_text
    from duru.ui import MainWindow
    import numpy as np
    import sounddevice

    report = Path(report_path)
    network_attempts = []
    def offline_only(event, args):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.bind"}:
            network_attempts.append(event)
            raise RuntimeError("Network forbidden in diagnostic")
    sys.addaudithook(offline_only)
    audio = None
    try:
        app = QApplication.instance() or QApplication([])
        window = MainWindow()
        models = discover_models()
        audio = decode_file(audio_path)
        engine = SpeechEngine()
        started = time.perf_counter()
        from duru.storage import DEFAULTS
        engine.load(DEFAULTS["model"])
        result = engine.transcribe(audio, "en", ["Talha", "GitHub", "TypeScript"])
        elapsed = time.perf_counter() - started
        silence = engine.transcribe(np.zeros(16000, dtype=np.float32), "tr")
        window.set_result(result["text"], clean_text(result["text"]), result["duration"])
        window.show()
        app.processEvents()
        window.grab().save(str(report.with_suffix(".png")))
        # Enumerates hardware capabilities; never opens or listens to a microphone.
        devices = sounddevice.query_devices()
        success = bool(result["text"]) and silence["text"] == "" and not network_attempts
        report.write_text(json.dumps({"ok": success, "frozen": bool(getattr(sys, "frozen", False)),
            "models": {k: str(v) for k, v in models.items()}, "result": result,
            "elapsed_seconds": round(elapsed, 2), "silence": silence["text"],
            "audio_device_count": len(devices), "network_attempts": network_attempts},
            indent=2, ensure_ascii=False), encoding="utf-8")
        window.close()
        return 0 if success else 1
    except Exception as exc:
        report.write_text(json.dumps({"ok": False, "error": type(exc).__name__, "detail": str(exc)},
                                     ensure_ascii=False), encoding="utf-8")
        return 1
    finally:
        if audio is not None:
            audio.fill(0)


def workflow_test(audio_path: str, report_path: str) -> int:
    """Exercise real F10 registration/tray/model with synthetic capture only."""
    import ctypes
    import threading
    import duru.app as desktop
    from duru import windows
    from duru.recorder import decode_file
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QApplication

    source = decode_file(audio_path)
    class SyntheticRecorder(QObject):
        level = Signal(float)
        failed = Signal(str)
        limit_reached = Signal()
        starts = 0
        def start(self):
            self.starts += 1
        def stop(self):
            return source.copy()
        def discard(self):
            pass
    desktop.Recorder = SyntheticRecorder
    desktop.foreground_window = lambda: 0
    desktop.save_settings = lambda *_: None
    application = QApplication.instance() or QApplication([])
    application.setWindowIcon(desktop.app_icon())
    window = desktop.MainWindow()
    settings = desktop.validate_settings({'language': 'en', 'terms': ['Talha', 'GitHub', 'TypeScript']})
    controller = desktop.Controller(application, window, settings, enable_tray=True)
    output = {'ok': False, 'frozen': bool(getattr(sys, 'frozen', False)), 'network_attempts': []}
    def offline_only(event, args):
        if event in {'socket.connect', 'socket.getaddrinfo', 'socket.bind'}:
            output['network_attempts'].append(event)
            raise RuntimeError('Network forbidden in diagnostic')
    sys.addaudithook(offline_only)
    def wait_for(predicate, seconds=40):
        deadline = time.monotonic() + seconds
        while not predicate():
            application.processEvents()
            time.sleep(0.005)
            if time.monotonic() > deadline:
                raise TimeoutError('Workflow diagnostic timed out')
    try:
        output['f10_registered'] = controller.hotkey.registered
        output['key_code'] = windows.VK_F10
        if not controller.hotkey.registered:
            raise RuntimeError('F10 was not available')
        started = time.perf_counter()
        controller.start_preload()
        wait_for(lambda: controller.warmup_thread is None)
        output['preload_seconds'] = round(time.perf_counter() - started, 3)
        output['microphone_starts_during_preload'] = controller.recorder.starts
        kernel = ctypes.WinDLL('kernel32')
        kernel.GetCurrentThreadId.restype = windows.DWORD
        native = ctypes.WinDLL('user32')
        native.PostThreadMessageW.argtypes = [windows.DWORD, windows.UINT, windows.ULONG_PTR, ctypes.c_ssize_t]
        native.PostThreadMessageW.restype = windows.BOOL
        def post_f10():
            if not native.PostThreadMessageW(kernel.GetCurrentThreadId(), windows.WM_HOTKEY, controller.hotkey._hotkey_id, 0):
                raise RuntimeError('Could not dispatch F10 message')
        started = time.perf_counter()
        post_f10()
        wait_for(lambda: controller.state == 'recording', 3)
        output['f10_to_recording_ms'] = round((time.perf_counter() - started) * 1000, 1)
        post_f10()
        wait_for(lambda: controller.has_result and controller.thread is None)
        output['transcript'] = window.editor_text()
        output['synthetic_capture_count'] = controller.recorder.starts
        output['tray_available'] = controller.tray is not None
        window.close()
        application.processEvents()
        output['f10_remains_after_close'] = controller.hotkey.registered
        output['window_hidden'] = not window.isVisible()
        controller.request_exit()
        wait_for(lambda: not controller.hotkey.registered, 3)
        output['exit_unregisters_f10'] = not controller.hotkey.registered
        output['ok'] = (output['tray_available'] and output['f10_remains_after_close']
                        and output['microphone_starts_during_preload'] == 0
                        and output['synthetic_capture_count'] == 1
                        and 'GitHub' in output['transcript'] and not output['network_attempts'])
    except Exception as exc:
        output['error'] = type(exc).__name__ + ': ' + str(exc)
    finally:
        controller.request_exit()
        wait_for(lambda: controller.thread is None and controller.warmup_thread is None)
        source.fill(0)
        Path(report_path).write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding='utf-8')
    return 0 if output['ok'] else 1
