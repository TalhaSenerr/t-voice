"""T-Voice's local-only desktop interface.

This module deliberately contains no microphone, clipboard, disk or network access.
The application controller owns those actions and connects the public signals.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping

from PySide6 import QtCore, QtGui, QtWidgets


GREEN = "#214F40"
INK = "#263E34"
MUTED = "#79867C"


STYLE = """
QMainWindow, QWidget#root { background: #F6F7F2; color: #263E34; }
QWidget { font-family: 'Segoe UI'; font-size: 13px; color: #263E34; }
QWidget#sidebar { background: #ECEFE6; border-right: 1px solid #DFE5DA; }
QLabel { background: transparent; }
QLabel#brand { font-size: 22px; font-weight: 700; letter-spacing: -0.5px; }
QLabel#brandTagline { color: #6D7D70; font-size: 11px; }
QLabel#eyebrow { color: #7A8978; font-size: 10px; font-weight: 700; letter-spacing: 2px; }
QLabel#pageTitle { font-size: 26px; font-weight: 600; letter-spacing: -0.5px; }
QLabel#subtitle { color: #778278; font-size: 13px; }
QLabel#muted { color: #788477; font-size: 12px; }
QLabel#micro { color: #879184; font-size: 11px; }
QLabel#sectionTitle { font-size: 16px; font-weight: 600; }
QLabel#recordTitle { font-size: 23px; font-weight: 600; letter-spacing: -0.5px; }
QLabel#recordHint { font-size: 12px; color: #778477; }
QLabel#timer { font-size: 15px; font-weight: 600; color: #5F7262; }
QLabel#shortcut { border: 1px solid #DCE3D6; border-radius: 6px; padding: 5px 9px; color: #778477; font-size: 10px; background: #F8FAF5; }
QLabel#badge { color: #41644F; background: #EAF1E6; border-radius: 9px; padding: 4px 9px; font-size: 10px; font-weight: 600; }
QLabel#footer { color: #8A9488; font-size: 11px; }
QLabel#statusMessage { color: #6F7E70; font-size: 12px; }
QLabel#statusMessage[error="true"] { color: #A54238; }
QFrame#card { background: #FFFFFF; border: 1px solid #E1E7DC; border-radius: 16px; }
QFrame#recordCard { background: #FCFEF8; border: 1px solid #DCE6D5; border-radius: 17px; }
QFrame#line { background: #E9EDE5; border: none; max-height: 1px; }
QFrame#privacyNote { background: #E5ECDC; border: 1px solid #DBE4D3; border-radius: 12px; }
QFrame#infoBox { background: #F1F5EC; border: 1px solid #E0E8D8; border-radius: 10px; }
QPushButton { border: 1px solid #DCE3D7; background: #FFFFFF; border-radius: 8px; padding: 9px 15px; font-weight: 500; }
QPushButton:hover { background: #F0F4EA; border-color: #B7C7AD; }
QPushButton:pressed { background: #E5EDDD; }
QPushButton:focus { border: 2px solid #719275; }
QPushButton:disabled { color: #A0AA9C; border-color: #E5E9E1; background: #F5F7F2; }
QPushButton#primary { background: #214F40; color: #FFFFFF; border: 1px solid #214F40; font-weight: 600; border-radius: 9px; padding: 12px 20px; }
QPushButton#primary:hover { background: #2E6350; border-color: #2E6350; }
QPushButton#primary:pressed { background: #163A2E; }
QPushButton#primary:disabled { color: #DAE3D7; background: #819887; border-color: #819887; }
QPushButton#recordButton { background: #214F40; color: white; border: 1px solid #214F40; font-weight: 600; border-radius: 10px; padding: 11px 22px; }
QPushButton#recordButton:hover { background: #2E6350; }
QPushButton#recordButton:disabled { background: #809486; border-color: #809486; color: #E5EBE1; }
QPushButton#recordButton[recording="true"] { background: #A54E3F; border-color: #A54E3F; }
QPushButton#recordButton[recording="true"]:hover { background: #B25D4E; }
QPushButton#nav { background: transparent; border: 1px solid transparent; border-radius: 9px; text-align: left; padding: 10px 12px; color: #657661; font-size: 13px; }
QPushButton#nav:hover { background: #E3E9DB; }
QPushButton#nav:checked { background: #DAE5D0; border-color: #D4E0CA; color: #214F40; font-weight: 600; }
QPushButton#nav:focus { border-color: #789873; }
QPushButton#ghost { border: 1px solid transparent; background: transparent; color: #75826F; padding: 7px 9px; font-size: 12px; }
QPushButton#ghost:hover { background: #EEF3E8; color: #214F40; }
QPushButton#tab { border: none; background: transparent; border-radius: 6px; color: #87917F; padding: 6px 12px; font-size: 11px; }
QPushButton#tab:checked { background: #EAF0E4; color: #375C41; font-weight: 600; }
QTextEdit { background: transparent; border: none; color: #33483B; font-size: 16px; line-height: 1.5; selection-background-color: #DBE8D1; selection-color: #214F40; }
QTextEdit:focus { border: none; }
QComboBox { background: #F8FAF5; border: 1px solid #DEE5D7; border-radius: 7px; padding: 7px 26px 7px 10px; min-height: 19px; }
QComboBox:hover { border-color: #B8C9AF; }
QComboBox:focus { border: 2px solid #719275; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox::down-arrow { image: none; border-left: 4px solid transparent; border-right: 4px solid transparent; border-top: 5px solid #6E826B; width: 0px; height: 0px; margin-right: 7px; }
QComboBox QAbstractItemView { background: #FFFFFF; border: 1px solid #DCE4D6; selection-background-color: #DFEBD5; selection-color: #214F40; padding: 5px; outline: none; }
QCheckBox { spacing: 10px; color: #344C3C; font-size: 13px; padding: 3px 0px; }
QCheckBox::indicator { width: 19px; height: 19px; border: 1px solid #BFCFBA; border-radius: 5px; background: #FFFFFF; }
QCheckBox::indicator:checked { background: #214F40; border: 1px solid #214F40; image: none; }
QCheckBox::indicator:checked:hover { background: #447A56; }
QCheckBox:focus { color: #214F40; }
QTableWidget { background: white; border: 1px solid #E1E7DA; border-radius: 9px; gridline-color: #EDF0E8; alternate-background-color: #F8FAF5; selection-background-color: #E4EDDC; selection-color: #214F40; font-size: 13px; }
QTableWidget::item { padding: 10px; }
QHeaderView::section { background: #F1F5EC; border: none; border-bottom: 1px solid #E0E7D8; padding: 12px; text-align: left; color: #74816D; font-size: 11px; font-weight: 600; }
QLineEdit { background: white; border: 1px solid #AFC3A4; border-radius: 4px; padding: 4px; selection-background-color: #DFEAD7; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical { background: #CED8C5; min-height: 28px; border-radius: 3px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QToolTip { color: #FFFFFF; background: #294F3B; border: none; padding: 7px; }
"""


def _label(text: str, name: str = "", wrap: bool = False) -> QtWidgets.QLabel:
    widget = QtWidgets.QLabel(text)
    widget.setObjectName(name)
    widget.setWordWrap(wrap)
    widget.setTextFormat(QtCore.Qt.TextFormat.PlainText)
    return widget


def _button(text: str, name: str = "", icon: str = "") -> QtWidgets.QPushButton:
    widget = QtWidgets.QPushButton(text)
    widget.setObjectName(name)
    widget.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
    if icon:
        widget.setIcon(_icon(icon, "#FFFFFF" if name in ("primary", "recordButton") else GREEN))
        widget.setIconSize(QtCore.QSize(17, 17))
    return widget


def _icon(name: str, color: str = GREEN, size: int = 20) -> QtGui.QIcon:
    """Small native line icons; no external assets or font glyph dependencies."""
    pixmap = QtGui.QPixmap(size * 2, size * 2)
    pixmap.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    painter.scale(size * 2 / 24, size * 2 / 24)
    pen = QtGui.QPen(QtGui.QColor(color), 1.6)
    pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    if name in ("mic", "dictation"):
        painter.drawRoundedRect(QtCore.QRectF(9, 3, 6, 12), 3, 3)
        path = QtGui.QPainterPath(QtCore.QPointF(6, 11))
        path.cubicTo(6, 21, 18, 21, 18, 11)
        painter.drawPath(path)
        painter.drawLine(12, 18, 12, 22)
        painter.drawLine(8, 22, 16, 22)
    elif name == "stop":
        painter.setBrush(QtGui.QColor(color))
        painter.drawRoundedRect(QtCore.QRectF(6, 6, 12, 12), 2, 2)
    elif name in ("shield", "settings"):
        path = QtGui.QPainterPath(QtCore.QPointF(12, 2))
        for x, y in ((20, 5), (19, 14), (16, 19), (12, 22), (8, 19), (5, 14), (4, 5)):
            path.lineTo(x, y)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawLine(8, 11, 11, 14)
        painter.drawLine(11, 14, 16, 9)
    elif name == "book":
        path = QtGui.QPainterPath(QtCore.QPointF(12, 5))
        path.cubicTo(8, 2, 5, 3, 3, 4)
        path.lineTo(3, 19)
        path.cubicTo(6, 18, 9, 18, 12, 21)
        path.cubicTo(15, 18, 18, 18, 21, 19)
        path.lineTo(21, 4)
        path.cubicTo(18, 3, 15, 2, 12, 5)
        path.lineTo(12, 21)
        painter.drawPath(path)
    elif name == "copy":
        painter.drawRoundedRect(QtCore.QRectF(8, 7, 12, 14), 2, 2)
        path = QtGui.QPainterPath(QtCore.QPointF(15, 4))
        path.lineTo(5, 4)
        path.lineTo(5, 16)
        painter.drawPath(path)
    elif name == "upload":
        painter.drawLine(12, 15, 12, 3)
        painter.drawLine(7, 8, 12, 3)
        painter.drawLine(17, 8, 12, 3)
        painter.drawPolyline([QtCore.QPointF(4, 14), QtCore.QPointF(4, 21), QtCore.QPointF(20, 21), QtCore.QPointF(20, 14)])
    elif name == "save":
        painter.drawLine(12, 3, 12, 15)
        painter.drawLine(7, 10, 12, 15)
        painter.drawLine(17, 10, 12, 15)
        painter.drawPolyline([QtCore.QPointF(4, 16), QtCore.QPointF(4, 21), QtCore.QPointF(20, 21), QtCore.QPointF(20, 16)])
    elif name == "plus":
        painter.drawLine(12, 5, 12, 19)
        painter.drawLine(5, 12, 19, 12)
    elif name == "trash":
        painter.drawLine(4, 6, 20, 6)
        painter.drawLine(9, 3, 15, 3)
        painter.drawPolyline([QtCore.QPointF(6, 6), QtCore.QPointF(7, 21), QtCore.QPointF(17, 21), QtCore.QPointF(18, 6)])
        painter.drawLine(10, 10, 10, 17)
        painter.drawLine(14, 10, 14, 17)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QtGui.QIcon(pixmap)


class CheckBox(QtWidgets.QCheckBox):
    """Native checkbox behavior with a clear, resolution-independent check mark."""

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802
        super().paintEvent(event)
        if self.isChecked():
            option = QtWidgets.QStyleOptionButton()
            self.initStyleOption(option)
            rect = self.style().subElementRect(QtWidgets.QStyle.SubElement.SE_CheckBoxIndicator, option, self)
            painter = QtGui.QPainter(self)
            painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
            pen = QtGui.QPen(QtGui.QColor("#FFFFFF"), 1.8)
            pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            left, top = rect.left(), rect.top()
            painter.drawPolyline([QtCore.QPointF(left + 5, top + 10), QtCore.QPointF(left + 9, top + 14), QtCore.QPointF(left + 16, top + 6)])
            painter.end()


class Waveform(QtWidgets.QWidget):
    """Microphone meter: driven by real input level, never simulated speech."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(160, 56)
        self.setMaximumHeight(76)
        self.setAccessibleName("Mikrofon ses seviyesi")
        self._samples = [0.0] * 36
        self._recording = False

    def set_level(self, level: float) -> None:
        self._samples = self._samples[1:] + [max(0.0, min(1.0, level))]
        self.update()

    def set_recording(self, enabled: bool) -> None:
        self._recording = enabled
        if not enabled:
            self._samples = [0.0] * 36
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        count = len(self._samples)
        spacing = min(8.0, self.width() / count)
        left = (self.width() - spacing * count) / 2
        center = self.height() / 2
        for index, sample in enumerate(self._samples):
            height = 4.0 + (self.height() - 12) * min(1, math.sqrt(sample) * 1.4)
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(QtGui.QColor("#759866" if self._recording else "#CEDBC1"))
            painter.drawRoundedRect(QtCore.QRectF(left + spacing * index, center - height / 2, 3.6, height), 1.8, 1.8)
        painter.end()


class MainWindow(QtWidgets.QMainWindow):
    record_requested = QtCore.Signal()
    cancel_requested = QtCore.Signal()
    import_requested = QtCore.Signal()
    clear_requested = QtCore.Signal()
    copy_requested = QtCore.Signal()
    save_requested = QtCore.Signal()
    settings_changed = QtCore.Signal(dict)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("T-Voice")
        self.setMinimumSize(900, 640)
        self.resize(1020, 720)
        self.setWindowIcon(_icon("mic", GREEN, 64))
        self.setStyleSheet(STYLE)
        self._state = "idle"
        self._applying = False
        self._raw = ""
        self._cleaned = ""
        self._selected_model = "turbo-ov"
        self._has_models = False
        self._duration = 0.0
        self._settings_timer = QtCore.QTimer(self)
        self._settings_timer.setSingleShot(True)
        self._settings_timer.setInterval(350)
        self._settings_timer.timeout.connect(self._emit_settings)

        root = QtWidgets.QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QtWidgets.QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.pages = QtWidgets.QStackedWidget()
        outer.addWidget(self._build_sidebar())
        outer.addWidget(self.pages, 1)
        self.pages.addWidget(self._build_dictation())
        self.pages.addWidget(self._build_glossary())
        self.pages.addWidget(self._build_settings())
        self.nav_buttons[0].setChecked(True)
        self.apply_settings({})
        self.set_state("idle")
        self._refresh_result_controls()

    def _build_sidebar(self) -> QtWidgets.QWidget:
        panel = QtWidgets.QWidget()
        panel.setObjectName("sidebar")
        panel.setFixedWidth(170)
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(14, 23, 14, 20)
        layout.setSpacing(8)
        logo_row = QtWidgets.QHBoxLayout()
        logo_row.setSpacing(6)
        logo = QtWidgets.QLabel()
        logo.setPixmap(_icon("mic", GREEN, 29).pixmap(29, 29))
        logo.setFixedSize(32, 38)
        logo_row.addWidget(logo)
        logo_row.addWidget(_label("T-Voice", "brand"))
        logo_row.addStretch()
        layout.addLayout(logo_row)
        tagline = _label("Türkçe + İngilizce", "brandTagline")
        tagline.setContentsMargins(3, 0, 0, 0)
        layout.addWidget(tagline)
        layout.addSpacing(28)
        self.nav_buttons = []
        self.nav_group = QtWidgets.QButtonGroup(self)
        self.nav_group.setExclusive(True)
        for index, (title, icon) in enumerate((("Dikte", "dictation"), ("Sözlük", "book"), ("Ayarlar", "shield"))):
            button = _button(title, "nav", icon)
            button.setCheckable(True)
            button.setMinimumHeight(43)
            button.clicked.connect(lambda checked=False, page=index: self.pages.setCurrentIndex(page))
            self.nav_group.addButton(button, index)
            self.nav_buttons.append(button)
            layout.addWidget(button)
        layout.addStretch()
        layout.addWidget(_label("●  Tamamen cihazında", "micro"))
        layout.addWidget(_label("Ses buluta gönderilmez.", "micro", True))
        return panel

    def _new_page(self, eyebrow: str, title: str, subtitle: str) -> tuple[QtWidgets.QWidget, QtWidgets.QVBoxLayout, QtWidgets.QHBoxLayout]:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(14)
        header = QtWidgets.QHBoxLayout()
        titles = QtWidgets.QVBoxLayout()
        titles.setSpacing(7)
        if eyebrow:
            titles.addWidget(_label(eyebrow, "eyebrow"))
        titles.addWidget(_label(title, "pageTitle"))
        titles.addWidget(_label(subtitle, "subtitle", True))
        header.addLayout(titles, 1)
        layout.addLayout(header)
        return page, layout, header

    def _build_dictation(self) -> QtWidgets.QWidget:
        page, layout, _ = self._new_page("", "Konuşarak yaz", "Yazacağın alana tıkla. Kısayolunla başla, yeniden basarak bitir.")

        recorder = QtWidgets.QFrame()
        recorder.setObjectName("recordCard")
        record_layout = QtWidgets.QVBoxLayout(recorder)
        record_layout.setContentsMargins(20, 17, 20, 17)
        record_layout.setSpacing(12)
        top = QtWidgets.QHBoxLayout()
        self.record_badge = _label("●  HAZIR", "badge")
        top.addWidget(self.record_badge, 0, QtCore.Qt.AlignmentFlag.AlignLeft)
        top.addStretch()
        self.shortcut_badge = _label("F10", "shortcut")
        top.addWidget(self.shortcut_badge)
        record_layout.addLayout(top)
        center = QtWidgets.QHBoxLayout()
        center.setSpacing(12)
        texts = QtWidgets.QVBoxLayout()
        texts.setSpacing(6)
        self.record_title = _label("F10 → Konuş → F10", "recordTitle")
        self._hotkey_shortcut = "F10"
        self.record_hint = _label("Metin, seçtiğin alana yazılır.", "recordHint", True)
        texts.addWidget(self.record_title)
        texts.addWidget(self.record_hint)
        center.addLayout(texts, 3)
        self.waveform = Waveform()
        center.addWidget(self.waveform, 2)
        record_layout.addLayout(center)
        bottom = QtWidgets.QHBoxLayout()
        bottom.setSpacing(12)
        self.record_button = _button("Başlat · F10", "recordButton", "mic")
        self.record_button.setMinimumWidth(163)
        self.record_button.setMinimumHeight(45)
        self.record_button.setToolTip("Kaydı başlat veya bitir · F10")
        self.record_button.clicked.connect(self.record_requested)
        bottom.addWidget(self.record_button)
        self.cancel_button = _button("İptal", "ghost")
        self.cancel_button.clicked.connect(self.cancel_requested)
        self.cancel_button.hide()
        bottom.addWidget(self.cancel_button)
        bottom.addStretch()
        self.elapsed_label = _label("00:00", "timer")
        bottom.addWidget(self.elapsed_label)
        record_layout.addLayout(bottom)
        layout.addWidget(recorder)

        result_card = QtWidgets.QFrame()
        result_card.setObjectName("card")
        result_layout = QtWidgets.QVBoxLayout(result_card)
        result_layout.setContentsMargins(20, 16, 20, 16)
        result_layout.setSpacing(13)
        result_header = QtWidgets.QHBoxLayout()
        result_header.addWidget(_label("Metnin", "sectionTitle"))
        result_header.addSpacing(8)
        self.edit_hint = _label("Düzenleyebilirsin", "micro")
        result_header.addWidget(self.edit_hint)
        result_header.addStretch()
        self.result_tabs = QtWidgets.QButtonGroup(self)
        self.result_tabs.setExclusive(True)
        self.clean_tab = _button("Düzenlenmiş", "tab")
        self.raw_tab = _button("Ham metin", "tab")
        for index, tab in enumerate((self.clean_tab, self.raw_tab)):
            tab.setCheckable(True)
            self.result_tabs.addButton(tab, index)
            result_header.addWidget(tab)
        self.clean_tab.setChecked(True)
        self.result_tabs.idClicked.connect(self._switch_result)
        result_layout.addLayout(result_header)
        self.editor = QtWidgets.QTextEdit()
        self.editor.setAcceptRichText(False)
        self.editor.setAccessibleName("Düzenlenebilir konuşma metni")
        self.editor.setPlaceholderText("Konuşman burada görünecek.")
        self.editor.setMinimumHeight(145)
        self.editor.document().setDocumentMargin(0)
        self.editor.textChanged.connect(self._editor_changed)
        result_layout.addWidget(self.editor, 1)
        line = QtWidgets.QFrame()
        line.setObjectName("line")
        line.setFixedHeight(1)
        result_layout.addWidget(line)
        result_footer = QtWidgets.QHBoxLayout()
        self.word_count = _label("0 kelime", "micro")
        result_footer.addWidget(self.word_count)
        result_footer.addStretch()
        self.clear_button = _button("Temizle", "ghost", "trash")
        self.clear_button.clicked.connect(self.clear_requested)
        result_footer.addWidget(self.clear_button)
        self.save_button = _button(".txt kaydet", "", "save")
        self.save_button.clicked.connect(self.save_requested)
        result_footer.addWidget(self.save_button)
        self.copy_button = _button("Metni kopyala", "primary", "copy")
        self.copy_button.clicked.connect(self.copy_requested)
        result_footer.addWidget(self.copy_button)
        result_layout.addLayout(result_footer)
        layout.addWidget(result_card, 1)
        footer = QtWidgets.QHBoxLayout()
        self.status_label = _label("Hazır. Ses ve metin geçmişi tutulmaz.", "statusMessage", True)
        self.status_label.setAccessibleName("Uygulama durumu")
        footer.addWidget(self.status_label, 1)
        self.model_status = _label("YEREL MODEL", "footer")
        footer.addWidget(self.model_status, 0, QtCore.Qt.AlignmentFlag.AlignRight)
        layout.addLayout(footer)
        return page

    def _build_glossary(self) -> QtWidgets.QWidget:
        page, layout, header = self._new_page("", "Kelime sözlüğü", "İsimler ve İngilizce terimler için tercih ettiğin yazımı ekle.")
        add_button = _button("Kelime ekle", "primary", "plus")
        add_button.clicked.connect(self._add_term)
        header.addWidget(add_button, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)
        card = QtWidgets.QFrame()
        card.setObjectName("card")
        card_layout = QtWidgets.QVBoxLayout(card)
        card_layout.setContentsMargins(24, 22, 24, 22)
        card_layout.setSpacing(16)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(_label("Kişisel kelime sözlüğün", "sectionTitle"))
        row.addStretch()
        self.term_count = _label("0 kelime", "badge")
        row.addWidget(self.term_count)
        card_layout.addLayout(row)
        card_layout.addWidget(_label("Terimler, konuşma modeline ipucu verir. Alternatif yazımlar, sonuçta tercih ettiğin kelimeyle değiştirilir.", "muted", True))
        self.glossary = QtWidgets.QTableWidget(0, 2)
        self.glossary.setHorizontalHeaderLabels(["TERCİH EDİLEN YAZIM", "ALTERNATİF YAZIMLAR"])
        self.glossary.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.glossary.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.glossary.verticalHeader().setVisible(False)
        self.glossary.verticalHeader().setDefaultSectionSize(46)
        self.glossary.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.glossary.setAlternatingRowColors(True)
        self.glossary.setShowGrid(False)
        self.glossary.setAccessibleName("Kişisel kelime sözlüğü; ilk sütun tercih edilen yazım, ikinci sütun alternatif yazımlar")
        self.glossary.itemChanged.connect(self._settings_updated)
        card_layout.addWidget(self.glossary, 1)
        info = QtWidgets.QFrame()
        info.setObjectName("infoBox")
        info_layout = QtWidgets.QVBoxLayout(info)
        info_layout.setContentsMargins(15, 12, 15, 12)
        info_layout.addWidget(_label("Örnek: GitHub  →  alternatif yazımlar: git hap, git hub", "muted", True))
        info_layout.addWidget(_label("Alternatifleri virgülle ayır. Bir hücreye çift tıklayarak düzenleyebilirsin.", "micro", True))
        card_layout.addWidget(info)
        actions = QtWidgets.QHBoxLayout()
        actions.addWidget(_label("Değişiklikler bu Windows hesabına bağlı olarak şifrelenir.", "micro", True), 1)
        remove = _button("Seçileni sil", "ghost", "trash")
        remove.clicked.connect(self._remove_terms)
        actions.addWidget(remove)
        card_layout.addLayout(actions)
        layout.addWidget(card, 1)
        layout.addWidget(_label("Değişiklikler sonraki çözümlemede uygulanır. Her terimin doğru tanınacağı garanti edilemez.", "footer", True))
        return page

    def _setting_row(self, title: str, description: str, control: QtWidgets.QWidget) -> QtWidgets.QHBoxLayout:
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(25)
        copy = QtWidgets.QVBoxLayout()
        copy.setSpacing(5)
        copy.addWidget(_label(title, "sectionTitle"))
        copy.addWidget(_label(description, "muted", True))
        row.addLayout(copy, 1)
        row.addWidget(control)
        return row

    def _build_settings(self) -> QtWidgets.QWidget:
        page, layout, _ = self._new_page("", "Ayarlar", "Tercihlerin otomatik kaydedilir.")
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QtWidgets.QWidget()
        cards = QtWidgets.QVBoxLayout(content)
        cards.setContentsMargins(0, 0, 4, 0)
        cards.setSpacing(18)

        preferences = QtWidgets.QFrame()
        preferences.setObjectName("card")
        prefs = QtWidgets.QVBoxLayout(preferences)
        prefs.setContentsMargins(24, 23, 24, 23)
        prefs.setSpacing(19)
        prefs.addWidget(_label("Konuşmadan metne", "sectionTitle"))
        self.model_combo = QtWidgets.QComboBox()
        self.model_combo.setMinimumWidth(205)
        self.model_combo.setAccessibleName("Yerel konuşma modeli")
        self.model_combo.addItem("Model bulunamadı", "turbo-ov")
        self.model_combo.currentIndexChanged.connect(self._settings_updated)
        prefs.addLayout(self._setting_row("Konuşma modeli", "Whisper Turbo, Intel ekran kartını kullanır. Small daha az bellek kullanır.", self.model_combo))
        prefs.addWidget(_label("Bazı dizüstü bilgisayarlarda Fn tuşu donanım tarafından eklenir; uygulama Windows'a iletilen tuşu algılar.", "muted", True))
        self.hotkey_edit = QtWidgets.QKeySequenceEdit(QtGui.QKeySequence("F10"))
        self.hotkey_edit.setMaximumSequenceLength(1)
        self.hotkey_edit.setAccessibleName("Kayıt kısayolu")
        self.hotkey_edit.keySequenceChanged.connect(self._settings_updated)
        prefs.addLayout(self._setting_row(
            "Kayıt kısayolu", "Bir tuş veya Ctrl, Alt, Shift ya da Windows tuşuyla birleştirilmiş kısayol seç.", self.hotkey_edit
        ))
        self.language_combo = QtWidgets.QComboBox()
        self.language_combo.setAccessibleName("Konuşma dili")
        self.language_combo.addItem("Türkçe + İngilizce", "tr")
        self.language_combo.addItem("Otomatik dil algılama", "auto")
        self.language_combo.addItem("İngilizce", "en")
        self.language_combo.currentIndexChanged.connect(self._settings_updated)
        prefs.addLayout(self._setting_row("Konuşma dili", "Türkçe cümlelerde İngilizce terimleri de kullanabilirsin.", self.language_combo))
        self.cleanup_checkbox = CheckBox("Duraksama seslerini temizle")
        self.cleanup_checkbox.setChecked(True)
        self.cleanup_checkbox.toggled.connect(self._settings_updated)
        prefs.addWidget(self.cleanup_checkbox)
        hint = _label("‘Eee’, ‘hımm’, ‘umm’ gibi sesleri metinden çıkarır. Ham metni Dikte ekranında karşılaştırabilirsin.", "muted", True)
        hint.setContentsMargins(29, 0, 0, 0)
        prefs.addWidget(hint)
        self.insert_checkbox = CheckBox("Kısayolla konuştuğum metni seçtiğim alana yaz")
        self.insert_checkbox.toggled.connect(self._privacy_updated)
        prefs.addWidget(self.insert_checkbox)
        hint = _label("Önce yazacağın alana tıkla. Kısayolunla başlatıp bitir. Kapalıysa metin yalnızca T-Voice içinde gösterilir. Hassas alanlarda bu seçeneği kapalı tut.", "muted", True)
        hint.setContentsMargins(29, 0, 0, 0)
        prefs.addWidget(hint)
        self.import_button = _button("Ses dosyası aç", "", "upload")
        self.import_button.setToolTip("Bilgisayarındaki bir ses dosyasını yerel olarak yazıya çevir")
        self.import_button.clicked.connect(self.import_requested)
        prefs.addLayout(self._setting_row("Dosyadan yazıya", "Kaydettiğin bir ses dosyasını cihazında çözümle.", self.import_button))
        cards.addWidget(preferences)

        privacy = QtWidgets.QFrame()
        privacy.setObjectName("card")
        privacy_layout = QtWidgets.QVBoxLayout(privacy)
        privacy_layout.setContentsMargins(24, 23, 24, 23)
        privacy_layout.setSpacing(16)
        privacy_layout.addWidget(_label("Gizlilik", "sectionTitle"))
        for title, detail in (
            ("İşleme tamamen cihazında", "Konuşma, yerel modelle çözümlenir. T-Voice sesini bir sunucuya göndermez. Kullanım analitiği toplanmaz."),
            ("Ses ve metin geçmişi yok", "Mikrofon sesi bellekte işlenir. Metin, kaydettiğin dosyada veya yazdırdığın uygulamada saklanabilir."),
            ("Tercihlerin şifrelenir", "Ayarlar ve kelime sözlüğü Windows hesabına bağlı şifrelemeyle korunur. Metin, yalnızca sen kopyaladığında panoya yazılır."),
        ):
            privacy_layout.addWidget(_label(title, "sectionTitle"))
            privacy_layout.addWidget(_label(detail, "muted", True))
        note = QtWidgets.QFrame()
        note.setObjectName("infoBox")
        note_layout = QtWidgets.QVBoxLayout(note)
        note_layout.setContentsMargins(14, 13, 14, 13)
        note_layout.addWidget(_label("Güvenliğin gerçek sınırı", "sectionTitle"))
        note_layout.addWidget(_label("Hiçbir uygulama %100 güvenlik garanti edemez. İşletim sistemi belleği veya takas dosyası, zararlı yazılımlar, panoya kopyalanan metin ve kaydettiğin dosyalar bu korumanın dışındadır.", "muted", True))
        privacy_layout.addWidget(note)
        cards.addWidget(privacy)
        cards.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        layout.addWidget(_label("Tercihler otomatik kaydedilir. Ses modelleri cihazında hazır bulunmalıdır.", "footer", True))
        return page

    @QtCore.Slot()
    def _settings_updated(self, *_args: object) -> None:
        if self._applying:
            return
        current = self.model_combo.currentData()
        if current:
            self._selected_model = str(current)
        self._settings_timer.start()
        self._refresh_term_count()
        self._refresh_model_label()

    def _emit_settings(self) -> None:
        if not self._applying:
            self.settings_changed.emit(self.get_settings())

    def _privacy_updated(self, _checked: bool) -> None:
        if not self._applying:
            if self._state == "idle":
                self.set_state("idle")
            self._settings_timer.stop()
            self._emit_settings()

    def _refresh_term_count(self) -> None:
        count = sum(bool(self.glossary.item(row, 0) and self.glossary.item(row, 0).text().strip()) for row in range(self.glossary.rowCount()))
        self.term_count.setText(f"{count} kelime")

    def _refresh_model_label(self) -> None:
        name = self.model_combo.currentText()
        self.model_status.setText(f"YEREL  /  {name}" if self._has_models else "YEREL MODEL GEREKLİ")

    def _add_term(self) -> None:
        row = self.glossary.rowCount()
        self.glossary.insertRow(row)
        self.glossary.setItem(row, 0, QtWidgets.QTableWidgetItem(""))
        self.glossary.setItem(row, 1, QtWidgets.QTableWidgetItem(""))
        self.glossary.setCurrentCell(row, 0)
        self.glossary.editItem(self.glossary.item(row, 0))

    def _remove_terms(self) -> None:
        rows = {item.row() for item in self.glossary.selectedIndexes()}
        for row in sorted(rows, reverse=True):
            self.glossary.removeRow(row)
        if rows:
            self._settings_updated()

    def _switch_result(self, index: int) -> None:
        self.editor.blockSignals(True)
        self.editor.setReadOnly(index == 1)
        self.editor.setPlainText(self._raw if index == 1 else self._cleaned)
        self.editor.blockSignals(False)
        self.editor.setAccessibleName("Ham konuşma metni" if index else "Düzenlenebilir konuşma metni")
        self.edit_hint.setText("Orijinal çözümleme" if index else "Düzenleyebilirsin")
        self._refresh_result_controls()

    def _editor_changed(self) -> None:
        if self.clean_tab.isChecked():
            self._cleaned = self.editor.toPlainText()
        self._refresh_result_controls()

    def _refresh_result_controls(self) -> None:
        text = self.editor.toPlainText()
        words = len(re.findall(r"\S+", text))
        suffix = f"  ·  {self._duration:.1f} sn ses" if self._duration else ""
        self.word_count.setText(f"{words} kelime{suffix}")
        present = bool(text.strip())
        self.copy_button.setEnabled(present)
        self.save_button.setEnabled(present)
        self.clear_button.setEnabled(bool(self._raw or self._cleaned))

    def apply_settings(self, settings: Mapping[str, object]) -> None:
        """Load preferences without generating settings_changed signals."""
        self._applying = True
        self._settings_timer.stop()
        try:
            self._selected_model = str(settings.get("model", "turbo-ov"))
            self._hotkey_shortcut = str(settings.get("hotkey", "F10"))
            self.hotkey_edit.setKeySequence(QtGui.QKeySequence(self._hotkey_shortcut))
            self.shortcut_badge.setText(self._hotkey_shortcut)
            index = self.model_combo.findData(self._selected_model)
            if index >= 0:
                self.model_combo.setCurrentIndex(index)
            language = self.language_combo.findData(str(settings.get("language", "tr")))
            self.language_combo.setCurrentIndex(max(0, language))
            self.cleanup_checkbox.setChecked(bool(settings.get("cleanup", True)))
            self.insert_checkbox.setChecked(bool(settings.get("auto_insert", True)))
            raw_terms = settings.get("terms", [])
            terms = [str(term) for term in raw_terms if str(term).strip()] if isinstance(raw_terms, (list, tuple)) else []
            replacements = settings.get("replacements", {})
            aliases: dict[str, list[str]] = {}
            if isinstance(replacements, Mapping):
                for alias, preferred in replacements.items():
                    name = str(preferred)
                    aliases.setdefault(name, []).append(str(alias))
                    if name not in terms:
                        terms.append(name)
            self.glossary.setRowCount(0)
            for name in dict.fromkeys(terms):
                row = self.glossary.rowCount()
                self.glossary.insertRow(row)
                self.glossary.setItem(row, 0, QtWidgets.QTableWidgetItem(name))
                self.glossary.setItem(row, 1, QtWidgets.QTableWidgetItem(", ".join(aliases.get(name, []))))
        finally:
            self._applying = False
        self._refresh_term_count()
        self._refresh_model_label()
        self.set_state(self._state)

    def get_settings(self) -> dict:
        terms: list[str] = []
        replacements: dict[str, str] = {}
        for row in range(self.glossary.rowCount()):
            term_item = self.glossary.item(row, 0)
            alias_item = self.glossary.item(row, 1)
            term = term_item.text().strip() if term_item else ""
            if not term:
                continue
            if term not in terms:
                terms.append(term)
            aliases = alias_item.text() if alias_item else ""
            for alias in re.split(r"[,;\n]", aliases):
                alias = alias.strip()
                if alias and alias.casefold() != term.casefold():
                    replacements[alias] = term
        return {
            "model": self._selected_model,
            "hotkey": self.hotkey_edit.keySequence().toString(QtGui.QKeySequence.SequenceFormat.PortableText) or "F10",
            "language": self.language_combo.currentData() or "tr",
            "cleanup": self.cleanup_checkbox.isChecked(),
            "auto_insert": self.insert_checkbox.isChecked(),
            "terms": terms,
            "replacements": replacements,
        }

    def set_models(self, models: dict[str, str]) -> None:
        self._applying = True
        self._has_models = bool(models)
        try:
            self.model_combo.clear()
            if models:
                for key, display in models.items():
                    self.model_combo.addItem(display, key)
                index = self.model_combo.findData(self._selected_model)
                self.model_combo.setCurrentIndex(max(0, index))
                self._selected_model = str(self.model_combo.currentData())
                self.model_combo.setEnabled(True)
            else:
                self.model_combo.addItem("Model bulunamadı", self._selected_model)
                self.model_combo.setEnabled(False)
        finally:
            self._applying = False
        self._refresh_model_label()

    def set_state(self, state: str, message: str = "") -> None:
        self._state = state
        recording = state == "recording"
        busy = state in ("loading", "transcribing")
        self.record_button.setEnabled(not busy)
        shortcut = self._hotkey_shortcut
        self.shortcut_badge.setText(shortcut)
        self.record_button.setToolTip(f"Kaydı başlat veya bitir · {shortcut}")
        self.record_button.setText(f"Bitir · {shortcut}" if recording else f"Başlat · {shortcut}")
        self.record_button.setIcon(_icon("stop" if recording else "mic", "#FFFFFF"))
        self.record_button.setProperty("recording", recording)
        self.record_button.style().unpolish(self.record_button)
        self.record_button.style().polish(self.record_button)
        self.cancel_button.setVisible(recording or busy)
        self.import_button.setEnabled(not recording and not busy)
        self.language_combo.setEnabled(not recording and not busy)
        self.model_combo.setEnabled(not recording and not busy and self._has_models)
        self.waveform.set_recording(recording)
        states = {
            "idle": ("●  HAZIR", f"{shortcut} → Konuş → {shortcut}", "Metin, seçtiğin alana yazılır." if self.insert_checkbox.isChecked() else "Metin burada gösterilir; kopyalayıp kullanabilirsin."),
            "loading": ("●  HAZIRLANIYOR", "Model hazırlanıyor", "İlk kullanım için yerel model yükleniyor."),
            "recording": ("●  DİNLİYOR", "Konuşabilirsin", f"Bitirmek için yeniden {shortcut} tuşuna bas. Ses bu cihazda kalır."),
            "transcribing": ("●  YAZIYA ÇEVİRİYOR", "Metnin hazırlanıyor", "Ses, cihazındaki modelle işleniyor."),
            "error": ("●  SORUN OLUŞTU", "Tekrar deneyebilirsin", "Aşağıdaki durum mesajını kontrol et."),
        }
        badge, title, hint = states.get(state, states["idle"])
        self.record_badge.setText(badge)
        self.record_title.setText(title)
        self.record_hint.setText(hint)
        if message:
            self.show_status(message, state == "error")
        if recording:
            self.set_elapsed(0)
        if busy or recording:
            self.pages.setCurrentIndex(0)
            self.nav_buttons[0].setChecked(True)

    def set_level(self, level: float) -> None:
        self.waveform.set_level(level)

    def set_elapsed(self, seconds: float) -> None:
        seconds = max(0, int(seconds))
        self.elapsed_label.setText(f"{seconds // 60:02d}:{seconds % 60:02d}")

    def set_result(self, raw: str, cleaned: str, duration: float = 0) -> None:
        self._raw = raw
        self._cleaned = cleaned
        self._duration = max(0, duration)
        self.clean_tab.setChecked(True)
        self._switch_result(0)
        self.pages.setCurrentIndex(0)
        self.nav_buttons[0].setChecked(True)

    def editor_text(self) -> str:
        """Text currently displayed, including edits; copy/export follows active tab."""
        return self.editor.toPlainText()

    def clear_result(self) -> None:
        self._raw = ""
        self._cleaned = ""
        self._duration = 0
        self.clean_tab.setChecked(True)
        self._switch_result(0)
        self.set_elapsed(0)

    def show_status(self, message: str, error: bool = False) -> None:
        self.status_label.setText(message)
        self.status_label.setProperty("error", error)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)


class RecordingIndicator(QtWidgets.QFrame):
    """Small recording controls that leave the external text field focused.

    The controller owns visibility and lifetime. This widget never activates
    itself and never infers that a recording exists from its visibility.
    """

    stop_requested = QtCore.Signal()
    cancel_requested = QtCore.Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        flags = (
            QtCore.Qt.WindowType.Tool
            | QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.WindowStaysOnTopHint
            | QtCore.Qt.WindowType.WindowDoesNotAcceptFocus
        )
        super().__init__(parent, flags)
        self.setObjectName("floatingIndicator")
        self.setWindowTitle("T-Voice kayıt göstergesi")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.setFixedSize(450, 66)
        self.setAccessibleName("T-Voice kayıt durumu ve denetimleri")
        self.setStyleSheet(STYLE + """
            QFrame#floatingIndicator { background: #FCFEF8; border: 1px solid #C8D8BC; border-radius: 13px; }
            QLabel#indicatorText { color: #294A37; font-size: 12px; font-weight: 600; }
            QLabel#indicatorText[error="true"] { color: #A54238; }
            QLabel#indicatorTimer { color: #72806A; font-size: 12px; font-weight: 600; }
            QPushButton#indicatorStop { background: #214F40; color: #FFFFFF; border: 1px solid #214F40; border-radius: 7px; padding: 7px 9px; font-size: 11px; font-weight: 600; }
            QPushButton#indicatorStop:hover { background: #30654B; }
            QPushButton#indicatorCancel { background: transparent; color: #6D7B64; border: 1px solid #DCE5D4; border-radius: 7px; padding: 7px 9px; font-size: 11px; }
            QPushButton#indicatorCancel:hover { background: #EDF3E6; }
        """)
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(15, 13, 15, 13)
        row.setSpacing(9)
        self.dot = _label("●")
        self.dot.setFixedWidth(9)
        self.dot.setStyleSheet("color: #B65D48; font-size: 12px;")
        row.addWidget(self.dot)
        microphone = QtWidgets.QLabel()
        microphone.setPixmap(_icon("mic", GREEN, 17).pixmap(17, 17))
        microphone.setFixedSize(18, 24)
        row.addWidget(microphone)
        self.status_text = _label("T-Voice dinliyor", "indicatorText", True)
        row.addWidget(self.status_text, 1)
        self.elapsed_label = _label("00:00", "indicatorTimer")
        self.elapsed_label.setMinimumWidth(35)
        self.elapsed_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.elapsed_label)
        self.stop_button = _button("Bitir · Fn + F10", "indicatorStop")
        self.stop_button.setIcon(_icon("stop", "#FFFFFF", 13))
        self.stop_button.setIconSize(QtCore.QSize(13, 13))
        self.stop_button.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.stop_button.setToolTip("Kaydı bitir ve metne dönüştür · Fn + F10")
        self.stop_button.setAccessibleName("Kaydı bitir ve metne dönüştür")
        self.stop_button.clicked.connect(self.stop_requested)
        row.addWidget(self.stop_button)
        self.cancel_button = _button("İptal", "indicatorCancel")
        self.cancel_button.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.cancel_button.setAccessibleName("Kaydı veya çözümlemeyi iptal et")
        self.cancel_button.clicked.connect(self.cancel_requested)
        row.addWidget(self.cancel_button)
        self.set_state("recording")

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setBrush(QtGui.QColor("#FCFEF8"))
        painter.setPen(QtGui.QPen(QtGui.QColor("#C8D8BC"), 1))
        painter.drawRoundedRect(QtCore.QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 13, 13)
        painter.end()

    def showEvent(self, event: QtGui.QShowEvent) -> None:  # noqa: N802
        screen = QtGui.QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            self.move(
                available.x() + (available.width() - self.width()) // 2,
                available.y() + available.height() - self.height() - 22,
            )
        super().showEvent(event)

    def nativeEvent(self, event_type, message):  # noqa: N802
        # MA_NOACTIVATE also prevents a mouse click on the floating controls
        # from stealing the text target, while still delivering the click.
        if bytes(event_type) == b"windows_generic_MSG":
            import ctypes.wintypes

            native_message = ctypes.wintypes.MSG.from_address(int(message))
            if native_message.message == 0x0021:  # WM_MOUSEACTIVATE
                return True, 3  # MA_NOACTIVATE
        return super().nativeEvent(event_type, message)

    def set_state(self, state: str) -> None:
        recording = state == "recording"
        active = state in ("recording", "loading", "transcribing")
        self.status_text.setProperty("error", False)
        self.status_text.style().unpolish(self.status_text)
        self.status_text.style().polish(self.status_text)
        self.status_text.setText(
            "T-Voice dinliyor" if recording else "Hazırlanıyor" if state == "loading" else "Yazıya çeviriyor" if state == "transcribing" else "T-Voice hazır"
        )
        self.stop_button.setVisible(recording)
        self.cancel_button.setVisible(active)
        self.elapsed_label.setVisible(active)
        self.dot.setStyleSheet(f"color: {'#B65D48' if recording else '#719362'}; font-size: 12px;")

    def set_hotkey(self, shortcut: str) -> None:
        self.stop_button.setText(f"Bitir · {shortcut}")
        self.stop_button.setToolTip(f"Kaydı bitir ve metne dönüştür · {shortcut}")

    def show_feedback(self, message: str, error: bool = False) -> None:
        """Present a result notice without taking focus or changing visibility.

        The controller supplies a short status, never transcript content, and
        owns the duration so new recordings cannot be hidden by an old timer.
        """
        self.status_text.setText(message)
        self.status_text.setProperty("error", error)
        self.status_text.style().unpolish(self.status_text)
        self.status_text.style().polish(self.status_text)
        self.stop_button.hide()
        self.cancel_button.hide()
        self.elapsed_label.hide()
        self.dot.setStyleSheet(f"color: {'#B65D48' if error else '#719362'}; font-size: 12px;")

    def set_elapsed(self, seconds: float) -> None:
        elapsed = max(0, int(seconds))
        self.elapsed_label.setText(f"{elapsed // 60:02d}:{elapsed % 60:02d}")
