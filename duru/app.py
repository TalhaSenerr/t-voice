"""Desktop lifecycle. No server, cloud client, transcript database or telemetry."""
from __future__ import annotations

import os
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
os.environ["DO_NOT_TRACK"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import copy
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Signal, QEvent, QLockFile, QSaveFile, QIODevice
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QAction
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QSystemTrayIcon, QMenu

from duru.cleanup import clean_text
from duru.engine import SpeechEngine, discover_models, MODEL_SPECS
from duru.recorder import Recorder, decode_file
from duru.storage import data_dir, load_settings, save_settings, validate_settings
from duru.ui import MainWindow, RecordingIndicator
from duru.windows import HotkeyManager, foreground_window, is_own_window, insert_text, keys_released


class SpeechWorker(QObject):
    result = Signal(dict)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, engine, settings, audio=None, path=None):
        super().__init__()
        self.engine, self.settings = engine, settings
        self.audio, self.path = audio, path
        self.cancelled = threading.Event()

    def run(self):
        try:
            if self.cancelled.is_set():
                return
            if self.path:
                self.audio = decode_file(self.path, self.cancelled)
            if self.cancelled.is_set():
                return
            self.engine.load(self.settings["model"])
            if self.cancelled.is_set():
                return
            result = self.engine.transcribe(self.audio, self.settings["language"], self.settings["terms"])
            if not self.cancelled.is_set():
                result["cleaned"] = clean_text(result["text"], self.settings["cleanup"], self.settings["replacements"])
                self.result.emit(result)
        except ValueError as exc:
            if not self.cancelled.is_set():
                self.failed.emit(str(exc))
        except Exception:
            if not self.cancelled.is_set():
                self.failed.emit("Ses çözümlenemedi. Model dosyalarını ve ses dosyasının açılabildiğini kontrol et; daha kısa bir kayıtla tekrar dene.")
        finally:
            if self.audio is not None:
                self.audio.fill(0)
                self.audio = None
            self.path = None
            self.finished.emit()


class ModelWarmup(QObject):
    finished = Signal()
    failed = Signal(str)

    def __init__(self, engine, model):
        super().__init__()
        self.engine, self.model = engine, model
        self.cancelled = threading.Event()

    def run(self):
        try:
            if not self.cancelled.is_set():
                self.engine.load(self.model)
        except Exception:
            if not self.cancelled.is_set():
                self.failed.emit("Model önceden hazırlanamadı. Kayıt bittiğinde yeniden denenecek.")
        finally:
            self.finished.emit()


class Controller(QObject):
    def __init__(self, app, window, initial_settings, *, enable_tray=False, preload=False):
        super().__init__(app)
        self.app, self.window = app, window
        self.settings = initial_settings
        self.engine = SpeechEngine()
        self.recorder = Recorder(self)
        self.hotkey = HotkeyManager(self)
        self.indicator = RecordingIndicator()
        self.indicator.set_hotkey(self.settings.get("hotkey", "F10"))
        self.indicator_active = False
        self.indicator.stop_requested.connect(self.stop_recording)
        self.indicator.cancel_requested.connect(self.cancel)
        self.state = "idle"
        self.thread = self.worker = None
        self.warmup_thread = self.warmup_worker = None
        self.tray = None
        self.quitting = False
        self.target = None
        self.closing = False
        self.started = 0
        self.raw_text = ""
        self.has_result = False
        self.pending_insert = None
        self.preload_pending = False
        self.feedback_timer = QTimer(self)
        self.feedback_timer.setSingleShot(True)
        self.feedback_timer.timeout.connect(self.indicator.hide)
        self.elapsed_timer = QTimer(self)
        self.elapsed_timer.setInterval(100)
        self.elapsed_timer.timeout.connect(self._tick)
        self.insertion_timer = QTimer(self)
        self.insertion_timer.setInterval(30)
        self.insertion_timer.timeout.connect(self._try_insert)
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(350)
        self.save_timer.timeout.connect(self._save_preferences)
        window.installEventFilter(self)
        window.record_requested.connect(self.toggle_recording)
        window.cancel_requested.connect(self.cancel)
        window.import_requested.connect(self.import_audio)
        window.clear_requested.connect(self.clear)
        window.copy_requested.connect(self.copy_text)
        window.save_requested.connect(self.export_text)
        window.settings_changed.connect(self.settings_changed)
        self.recorder.level.connect(window.set_level)
        self.recorder.failed.connect(self.capture_failed)
        self.recorder.limit_reached.connect(self.stop_recording)
        self.hotkey.triggered.connect(self.hotkey_triggered)
        available = self.available_models = discover_models()
        window.set_models({k: MODEL_SPECS[k]["label"] for k in available})
        if self.settings["model"] not in available and available:
            self.settings["model"] = next(iter(available))
        window.apply_settings(self.settings)
        if not available:
            window.show_status("Yerel model bulunamadı. Kullanım kılavuzundaki model kurulumu adımını tamamla.", True)
        if not self.hotkey.start(self.settings.get("hotkey", "F10")):
            window.show_status(self.hotkey.last_error + " Kayıt düğmesini kullanabilir veya Ayarlar'dan başka bir kısayol seçebilirsin.", True)
        if enable_tray and QSystemTrayIcon.isSystemTrayAvailable():
            self._setup_tray()
        if preload and available:
            QTimer.singleShot(200, self.start_preload)

    def _setup_tray(self):
        self.tray = QSystemTrayIcon(self.app.windowIcon(), self)
        self.tray.setToolTip("T-Voice · " + self.settings.get("hotkey", "F10") + " ile konuş")
        self._tray_menu = QMenu()
        open_action = QAction("T-Voice'u aç", self._tray_menu)
        open_action.triggered.connect(self.show_window)
        self._tray_menu.addAction(open_action)
        self._tray_menu.addSeparator()
        exit_action = QAction("Çıkış", self._tray_menu)
        exit_action.triggered.connect(self.request_exit)
        self._tray_menu.addAction(exit_action)
        self.tray.setContextMenu(self._tray_menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()
        self.app.setQuitOnLastWindowClosed(False)

    def _tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_window()

    def show_window(self):
        if not self.closing:
            self.window.showNormal()
            self.window.raise_()
            self.window.activateWindow()

    def start_preload(self):
        if self.closing or self.warmup_thread is not None or self.thread is not None or self.state == "recording":
            return
        self.preload_pending = False
        model = self.window.get_settings()["model"]
        if model not in self.available_models or getattr(self.engine, "model_key", None) == model:
            return
        self.warmup_thread = QThread(self)
        self.warmup_worker = ModelWarmup(self.engine, model)
        self.warmup_worker.moveToThread(self.warmup_thread)
        self.warmup_thread.started.connect(self.warmup_worker.run)
        self.warmup_worker.failed.connect(self._preload_failed)
        self.warmup_worker.finished.connect(self.warmup_thread.quit)
        self.warmup_worker.finished.connect(self.warmup_worker.deleteLater)
        self.warmup_thread.finished.connect(self._preload_finished)
        self.warmup_thread.finished.connect(self.warmup_thread.deleteLater)
        self.warmup_thread.start()

    def _preload_failed(self, message):
        if self.state == "idle" and not self.closing:
            self.window.show_status(message, True)

    def _preload_finished(self):
        self.warmup_thread = self.warmup_worker = None
        if self.closing:
            self.window.close()
        elif self.preload_pending:
            QTimer.singleShot(0, self.start_preload)

    def _feedback(self, message, error=False):
        """Keep background failures visible without exposing dictated content."""
        self.window.show_status(message, error)
        if not self.closing and (self.indicator_active or not self.window.isVisible()):
            self.indicator.show_feedback(message, error)
            self.indicator.show()
            self.feedback_timer.start(6000 if error else 3500)

    def request_exit(self):
        self.quitting = self.closing = True
        self.cancel()
        if self.warmup_worker is not None:
            self.warmup_worker.cancelled.set()
        self.window.close()

    def _set_state(self, state, message=""):
        self.state = state
        self.window.set_state(state, message)
        if self.tray is not None:
            shortcut = self.settings.get("hotkey", "F10")
            self.tray.setToolTip("T-Voice · " + {"recording": f"Dinliyor · {shortcut} ile bitir", "transcribing": "Metne dönüştürülüyor"}.get(state, f"{shortcut} ile konuş"))
        if self.indicator_active and state in {"recording", "loading", "transcribing"}:
            self.feedback_timer.stop()
            self.indicator.set_state(state)
            self.indicator.show()
        elif not self.feedback_timer.isActive() or self.closing:
            self.indicator.hide()

    def toggle_recording(self):
        if self.state == "recording":
            self.stop_recording()
        elif self.state in {"idle", "error"}:
            self.start_recording(None)

    def hotkey_triggered(self):
        if self.closing:
            return
        if self.state == "recording":
            self.stop_recording()
        elif self.state in {"idle", "error"}:
            target = foreground_window()
            self.start_recording(target if target and not is_own_window(target) else None)

    def start_recording(self, target):
        if self.thread is not None or self.closing:
            return
        self.settings = validate_settings(self.window.get_settings())
        self._cancel_insertion()
        self.feedback_timer.stop()
        self.indicator.hide()
        self.indicator_active = bool(target)
        if self.settings["model"] not in self.available_models:
            self._feedback("Seçili konuşma modeli bu bilgisayarda bulunamadı.", True)
            return
        try:
            self.recorder.start()
        except RuntimeError as exc:
            self._feedback(str(exc), True)
            return
        self.target = target
        self.indicator_active = bool(target)
        self.started = time.monotonic()
        self.indicator.set_elapsed(0)
        self.window.set_elapsed(0)
        self._set_state("recording")
        self.elapsed_timer.start()

    def _tick(self):
        elapsed = time.monotonic() - self.started
        self.window.set_elapsed(elapsed)
        self.indicator.set_elapsed(elapsed)

    def stop_recording(self):
        if self.state != "recording":
            return
        self.elapsed_timer.stop()
        try:
            audio = self.recorder.stop()
        except Exception:
            self.capture_failed("Mikrofon kapatılırken hata oluştu. Kaydı tekrar dene.")
            return
        self.window.set_level(0)
        if len(audio) < 4000:
            audio.fill(0)
            self._set_state("idle", "Kayıt çok kısaydı. Biraz daha uzun konuşmayı dene.")
            self._feedback("Kayıt çok kısaydı. Biraz daha uzun konuşmayı dene.")
            if self.preload_pending:
                QTimer.singleShot(0, self.start_preload)
            return
        self._run_worker(audio=audio)

    def capture_failed(self, message):
        if self.state != "recording":
            return
        self.elapsed_timer.stop()
        try:
            self.recorder.discard()
        except Exception:
            pass
        self.target = None
        self._set_state("error", message)
        self._feedback(message, True)
        if self.preload_pending:
            QTimer.singleShot(0, self.start_preload)

    def _run_worker(self, audio=None, path=None):
        self.settings = validate_settings(self.window.get_settings())
        self._set_state("transcribing", "Sesin bu bilgisayarda işleniyor. İlk çözümlemede model yüklenir.")
        self.thread = QThread(self)
        self.worker = SpeechWorker(self.engine, copy.deepcopy(self.settings), audio, path)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.result.connect(self._result)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self._worker_finished)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def _result(self, result):
        if self.closing or self.worker.cancelled.is_set():
            return
        self.raw_text = result["text"]
        self.has_result = True
        self.window.set_result(result["text"], result["cleaned"], result["duration"])
        if not result["cleaned"].strip():
            self._feedback("Konuşma algılanmadı. Mikrofonu kontrol edip yeniden deneyebilirsin.", True)
        elif (self.worker.settings["auto_insert"] and self.window.get_settings()["auto_insert"]
              and self.target):
            self.pending_insert = (result["cleaned"], self.target, time.monotonic() + 2)
            self.insertion_timer.start()
        else:
            self._feedback("Metnin T-Voice penceresinde hazır.")

    def _failed(self, message):
        self._feedback(message, True)

    def _worker_finished(self):
        cancelled = self.worker.cancelled.is_set() if self.worker else False
        self.thread = self.worker = None
        self.target = None
        self._set_state("idle")
        if cancelled:
            self.window.show_status("İşlem iptal edildi; ses bellekteki çalışma alanından temizlendi.")
        if self.closing:
            self.window.close()
        elif self.preload_pending:
            QTimer.singleShot(0, self.start_preload)

    def _try_insert(self):
        if self.pending_insert is None:
            self.insertion_timer.stop()
            return
        text, target, deadline = self.pending_insert
        if not self.window.get_settings()["auto_insert"] or foreground_window() != target:
            self._cancel_insertion()
            self._feedback("Aktif pencere değişti; metnin T-Voice penceresinde hazır.", True)
            return
        if keys_released(self.hotkey.virtual_key):
            self._cancel_insertion()
            ok, message = insert_text(text, target, self.hotkey.virtual_key)
            self._feedback(message, not ok)
        elif time.monotonic() >= deadline:
            self._cancel_insertion()
            self._feedback("Kısayol tuşları basılı kaldı; metnin T-Voice penceresinde hazır.", True)

    def _cancel_insertion(self):
        self.insertion_timer.stop()
        self.pending_insert = None

    def cancel(self):
        self._cancel_insertion()
        self.feedback_timer.stop()
        self.indicator.hide()
        if self.state == "recording":
            self.elapsed_timer.stop()
            try:
                self.recorder.discard()
            except Exception:
                pass
            self.target = None
            self.window.set_level(0)
            self._set_state("idle", "Kayıt iptal edildi.")
            if self.preload_pending:
                QTimer.singleShot(0, self.start_preload)
        elif self.worker:
            self.worker.cancelled.set()
            self.window.show_status("İptal ediliyor. Devam eden model adımı bitince ses temizlenecek.")

    def import_audio(self):
        if self.state not in {"idle", "error"} or self.thread is not None:
            return
        path, _ = QFileDialog.getOpenFileName(self.window, "Ses dosyası seç · en fazla 10 dakika", "",
                                             "Ses dosyaları (*.wav *.mp3 *.m4a *.ogg *.flac *.aac *.wma);;Tüm dosyalar (*)")
        if path:
            self._cancel_insertion()
            self.feedback_timer.stop()
            self.indicator.hide()
            self.target = None
            self.indicator_active = False
            self._run_worker(path=path)

    def settings_changed(self, settings):
        previous_model = self.settings["model"]
        previous_hotkey = self.settings.get("hotkey", "F10")
        self.settings = validate_settings(settings)
        self.save_timer.start()
        if self.settings["hotkey"] != previous_hotkey:
            if self.hotkey.start(self.settings["hotkey"]):
                self.window._hotkey_shortcut = self.settings["hotkey"]
                self.window.set_state(self.state)
                self.indicator.set_hotkey(self.settings["hotkey"])
                self.window.show_status(f"Kayıt kısayolu {self.settings['hotkey']} olarak ayarlandı.")
            else:
                error = self.hotkey.last_error
                self.hotkey.start(previous_hotkey)
                self.settings["hotkey"] = previous_hotkey
                self.window.apply_settings(self.settings)
                self.window.show_status(error, True)
        if self.settings["model"] != previous_model:
            self.preload_pending = True
            QTimer.singleShot(0, self.start_preload)

    def _save_preferences(self):
        try:
            save_settings(self.settings)
        except (OSError, ValueError):
            self.window.show_status("Ayarlar kaydedilemedi; bu oturumda kullanılmaya devam edecek.", True)

    def clear(self):
        self._cancel_insertion()
        self.raw_text = ""
        self.has_result = False
        self.window.clear_result()

    def copy_text(self):
        text = self.window.editor_text()
        if text.strip():
            self.app.clipboard().setText(text)
            self.window.show_status("Metin panoya kopyalandı. Windows pano geçmişi ve eşitleme ayarların burada geçerlidir.")

    def export_text(self):
        text = self.window.editor_text()
        if not text.strip():
            return
        path, _ = QFileDialog.getSaveFileName(self.window, "Metni kaydet", "T-Voice-metin.txt", "Metin dosyası (*.txt)")
        if not path:
            return
        output = QSaveFile(path)
        content = text.encode("utf-8")
        if not output.open(QIODevice.WriteOnly) or output.write(content) != len(content) or not output.commit():
            self.window.show_status("Metin dosyası kaydedilemedi.", True)
        else:
            self.window.show_status("Metin seçtiğin dosyaya kaydedildi.")

    def eventFilter(self, watched, event):
        if watched is self.window and event.type() == QEvent.Close:
            self._cancel_insertion()
            self.feedback_timer.stop()
            self.indicator.hide()
            if self.state == "recording":
                self.cancel()
            if self.tray is not None and not self.quitting and not self.closing:
                self.settings = validate_settings(self.window.get_settings())
                self._save_preferences()
                self.window.hide()
                event.ignore()
                return True
            if self.thread is not None or self.warmup_thread is not None:
                self.closing = True
                self.cancel()
                if self.warmup_worker is not None:
                    self.warmup_worker.cancelled.set()
                event.ignore()
                return True
            self.hotkey.stop()
            self.indicator.close()
            if self.tray is not None:
                self.tray.hide()
                QTimer.singleShot(0, self.app.quit)
            self.save_timer.stop()
            self.settings = validate_settings(self.window.get_settings())
            self._save_preferences()
            self.clear()
        return super().eventFilter(watched, event)


def app_icon():
    pixmap = QPixmap(128, 128)
    pixmap.fill(QColor("#205447"))
    painter = QPainter(pixmap)
    painter.setPen(QColor("#f7f6ef"))
    painter.setFont(QFont("Segoe UI", 70, QFont.Bold))
    painter.drawText(pixmap.rect(), 0x84, "T")
    painter.end()
    return QIcon(pixmap)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("T-Voice")
    app.setOrganizationName("T-Voice")
    app.setWindowIcon(app_icon())
    app.setStyle("Fusion")
    lock = QLockFile(str(data_dir() / "app.lock"))
    if not lock.tryLock(100):
        QMessageBox.information(None, "T-Voice hazır", "T-Voice zaten çalışıyor. Yazı alanını seçip kayıt kısayoluna basabilirsin. Pencereyi sistem tepsisindeki T-Voice simgesinden açabilirsin.")
        return 0
    warning = ""
    try:
        settings = load_settings()
    except (ValueError, OSError, UnicodeError):
        settings = validate_settings({})
        warning = "Korunan ayarlar okunamadı. Varsayılan ayarlarla açıldı; sözlüğünü yeniden girebilirsin."
    window = MainWindow()
    window.setWindowIcon(app.windowIcon())
    controller = Controller(app, window, settings, enable_tray=True, preload=True)
    window.show()
    if warning:
        window.show_status(warning, True)
    code = app.exec()
    lock.unlock()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
