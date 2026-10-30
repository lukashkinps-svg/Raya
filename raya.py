"""Raya Prime v0.3 — stable-window avatar, embedded chat and optional voice.

Windows 11 / PySide6. One frameless top-level window: chat is a child
widget docked next to Raya, not a separate operating-system window.
"""

import json
from html import escape
import logging
import math
import os
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QByteArray, QPoint, QRect, QRectF, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPixmap, QRegion
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from voice import VoiceController, SpeechSynthesizer
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

BASE_DIR = Path(__file__).resolve().parent
ART = BASE_DIR / "assets" / "raya.png"
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
SETTINGS_PATH = DATA_DIR / "settings.json"
AVATAR_WIDTH, AVATAR_HEIGHT = 345, 470
CHAT_WIDTH = 410
PANEL_GAP = 10
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
OLLAMA_MODEL = "raya-prime"


def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("raya")
    log.setLevel(logging.INFO)
    if not log.handlers:
        handler = RotatingFileHandler(
            LOG_DIR / "raya.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
        log.addHandler(handler)
    return log


logger = setup_logging()


def load_settings():
    try:
        if SETTINGS_PATH.is_file():
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        logger.exception("Settings could not be loaded")
    return {}


def save_settings(data):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(SETTINGS_PATH)
    except OSError:
        logger.exception("Settings could not be saved")


class EmbeddedChat(QWidget):
    """Child panel: never creates its own Windows top-level window."""

    def __init__(self, avatar):
        super().__init__(avatar)
        self.avatar = avatar
        self.setObjectName("rayaChat")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("""
            QWidget#rayaChat {
                background-color: #111a2c;
                border: 1px solid #4b709a;
                border-radius: 15px;
            }
            QLabel { background: transparent; color: #aebfd8; font: 10pt 'Segoe UI'; }
            QLabel#chatTitle { color: #99dbff; font: bold 12pt 'Segoe UI'; }
            QTextBrowser {
                background: #1a2842; color: #eff7ff;
                border: 1px solid #324766; border-radius: 9px;
                padding: 8px; font: 10pt 'Segoe UI';
            }
            QLineEdit {
                background: #1a2842; color: white;
                border: 1px solid #547396; border-radius: 9px;
                padding: 9px; font: 10pt 'Segoe UI';
            }
            QPushButton {
                background: #3272bb; color: white; border: 0;
                border-radius: 8px; padding: 9px 12px;
                font: bold 9pt 'Segoe UI';
            }
            QPushButton:disabled { background: #30445d; color: #98abc3; }
            QPushButton#collapseButton {
                background: #283951; color: #d7eaff;
                padding: 5px; min-width: 30px; max-width: 30px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(13, 13, 13, 13)
        layout.setSpacing(9)

        heading = QHBoxLayout()
        heading.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Райя-Прайм  ·  Ollama", self)
        title.setObjectName("chatTitle")
        heading.addWidget(title, 1)
        self.collapse_button = QPushButton("×")
        self.collapse_button.setObjectName("collapseButton")
        self.collapse_button.setToolTip("Скрыть чат (Райя останется на экране)")
        self.collapse_button.clicked.connect(self.avatar.hide_chat)
        heading.addWidget(self.collapse_button)
        layout.addLayout(heading)

        self.history_view = QTextBrowser(self)
        self.history_view.setOpenExternalLinks(False)
        layout.addWidget(self.history_view, 1)

        entry = QHBoxLayout()
        self.input = QLineEdit(self)
        self.input.setPlaceholderText("Напиши Райе...")
        self.input.returnPressed.connect(self.send_message)
        entry.addWidget(self.input, 1)
        self.send_button = QPushButton("Отправить", self)
        self.send_button.clicked.connect(self.send_message)
        entry.addWidget(self.send_button)
        layout.addLayout(entry)
        self.mic_button = QPushButton("🎙 Сказать команду", self)
        self.mic_button.clicked.connect(self.avatar.toggle_microphone)
        layout.addWidget(self.mic_button)

        self.status = QLabel("Локальная модель: raya-prime", self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.network = QNetworkAccessManager(self)
        self.messages = []  # Session-only; do not save private conversations to GitHub.
        self.pending = None
        self._add_line("Райя", "Я на связи. Слушаю тебя.")
        self.hide()

    def _add_line(self, who, message):
        safe_name = escape(who)
        safe_body = escape(message).replace("\n", "<br>")
        self.history_view.append(
            f'<p style="margin:8px 0; color:#e9f4ff">'
            f'<b style="color:#93d6ff">{safe_name}</b><br>{safe_body}</p>'
        )
        scroll = self.history_view.verticalScrollBar()
        scroll.setValue(scroll.maximum())

    def focus_input(self):
        self.input.setFocus(Qt.FocusReason.OtherFocusReason)

    def send_message(self):
        self.send_text(self.input.text().strip())

    def send_text(self, question):
        if self.pending is not None:
            self.avatar.tell("Подожди, я ещё думаю…", 3)
            return
        question = question.strip()
        if not question:
            return
        self.input.clear()
        self._add_line("Ты", question)
        self.messages.append({"role": "user", "content": question})
        payload = json.dumps(
            {"model": OLLAMA_MODEL, "messages": self.messages[-24:], "stream": False},
            ensure_ascii=False,
        ).encode("utf-8")
        req = QNetworkRequest(QUrl(OLLAMA_URL))
        req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        req.setTransferTimeout(180_000)
        self.status.setText("Райя думает…")
        self.send_button.setEnabled(False)
        self.input.setEnabled(False)
        self.avatar.tell("Думаю…", 180)
        reply = self.network.post(req, QByteArray(payload))
        self.pending = reply
        reply.finished.connect(lambda r=reply: self._request_finished(r))
        logger.info("Ollama request started (message omitted)")

    def _request_finished(self, reply):
        if self.pending is not reply:
            reply.deleteLater()
            return
        self.pending = None
        self.send_button.setEnabled(True)
        self.input.setEnabled(True)
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                code = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
                raise RuntimeError(f"Request failed: {reply.errorString()}, HTTP {code}")
            result = json.loads(bytes(reply.readAll()).decode("utf-8", errors="replace"))
            answer = result.get("message", {}).get("content", "").strip()
            if not answer:
                raise ValueError("Ollama returned an empty answer")
        except Exception as exc:
            if self.messages and self.messages[-1].get("role") == "user":
                self.messages.pop()
            logger.warning("Ollama request failed: %s", exc)
            error_text = str(exc).lower()
            if "404" in error_text or "not found" in error_text:
                note = "Модель raya-prime не найдена. Проверь команду: ollama list"
            elif "refused" in error_text or "host not found" in error_text:
                note = "Не могу подключиться к Ollama. Проверь, запущена ли она."
            else:
                note = "Не удалось получить ответ. Детали в logs/raya.log."
            self._add_line("Система", note)
            self.status.setText("Нет ответа от Ollama")
            self.avatar.tell("Ошибка подключения", 5)
        else:
            self.messages.append({"role": "assistant", "content": answer})
            self._add_line("Райя", answer)
            self.status.setText("Райя на связи  ·  локальный ИИ")
            self.avatar.tell("Ответила", 2)
            logger.info("Ollama response received (%d characters)", len(answer))
            self.avatar.say(answer)
        finally:
            reply.deleteLater()


class RayaAvatar(QWidget):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.setWindowTitle("Raya Prime")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.setAutoFillBackground(False)
        # Keep the SAME native window geometry forever. On Windows, resizing a
        # translucent layered window can leave stale copies of its pixels.
        self.setFixedSize(AVATAR_WIDTH + PANEL_GAP + CHAT_WIDTH, AVATAR_HEIGHT)
        saved_anchor = QPoint(int(self.settings.get("x", 100)),
                              int(self.settings.get("y", 150)))
        self.avatar_offset_x, self.panel_x, root_x = self._choose_layout(saved_anchor)
        self.move(root_x, saved_anchor.y())

        if not ART.is_file():
            raise FileNotFoundError(f"Avatar image is missing: {ART}")
        self.pixmap = QPixmap(str(ART))
        if self.pixmap.isNull():
            raise RuntimeError(f"Cannot load avatar image: {ART}")
        original = self.pixmap.size()
        fit = min((AVATAR_WIDTH - 20) / original.width(),
                  (AVATAR_HEIGHT - 60) / original.height())
        self.draw_width = original.width() * fit
        self.draw_height = original.height() * fit

        self.float_enabled = bool(self.settings.get("float_enabled", True))
        self.text_chat_enabled = bool(self.settings.get("text_chat_enabled", True))
        self.chat_open = False
        self.chat = None
        self.message = ""
        self.message_expires = 0.0
        self.drag_offset = None
        self.was_dragged = False
        self.started_at = time.perf_counter()
        self.voice = VoiceController(self)
        self.voice.recognized.connect(self._voice_recognized)
        self.voice.status_changed.connect(self._voice_status)
        self.voice.error.connect(self._voice_error)
        self.tts = SpeechSynthesizer(self)
        self.voice_mode = "off"
        self.tts_enabled = bool(self.settings.get("tts_enabled", True))

        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.update)
        self.timer.start(16)
        self._update_hit_region()
        logger.info("Starting Raya Prime v0.3, optional microphone + Windows speech")

    def avatar_origin(self):
        """Location of Raya's image region on the desktop (not panel origin)."""
        return self.pos() + QPoint(self.avatar_offset_x, 0)

    def paintEvent(self, event):
        painter = QPainter(self)
        # Transparent background is repainted on the same fixed-size surface.
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        elapsed = time.perf_counter() - self.started_at
        wave = math.sin(2 * math.pi * elapsed / 8.0)
        scale = 1.0 + (0.0045 * wave if self.float_enabled else 0.0)
        draw_w = self.draw_width * scale
        draw_h = self.draw_height * scale
        x = self.avatar_offset_x + (AVATAR_WIDTH - draw_w) / 2
        y = 40.0 + self.draw_height - draw_h
        painter.drawPixmap(QRectF(x, y, draw_w, draw_h),
                           self.pixmap, QRectF(self.pixmap.rect()))

        if self.message and time.perf_counter() < self.message_expires:
            painter.setPen(QColor("#63bdf9"))
            painter.setBrush(QColor("#141c37"))
            painter.drawRoundedRect(
                QRectF(self.avatar_offset_x + 5, 2, AVATAR_WIDTH - 10, 42), 8, 8
            )
            painter.setPen(QColor("#e8f5ff"))
            painter.setFont(QFont("Segoe UI", 9))
            text = self.message if len(self.message) <= 45 else self.message[:43] + "…"
            painter.drawText(
                QRectF(self.avatar_offset_x + 9, 2, AVATAR_WIDTH - 18, 42),
                Qt.AlignmentFlag.AlignCenter,
                text,
            )
        painter.end()

    def tell(self, text, seconds=4):
        self.message = text
        self.message_expires = time.perf_counter() + seconds
        self.update()

    def _choose_layout(self, anchor):
        """Choose the dock side ONCE, without later resizing/repositioning the window."""
        screen = QGuiApplication.screenAt(anchor + QPoint(AVATAR_WIDTH // 2, AVATAR_HEIGHT // 2))
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        bounds = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        total_width = AVATAR_WIDTH + PANEL_GAP + CHAT_WIDTH
        if anchor.x() + total_width <= bounds.right() + 1:
            return 0, AVATAR_WIDTH + PANEL_GAP, anchor.x()
        if anchor.x() - (CHAT_WIDTH + PANEL_GAP) >= bounds.left():
            return CHAT_WIDTH + PANEL_GAP, 0, anchor.x() - CHAT_WIDTH - PANEL_GAP
        # If neither side fits fully, choose the side with most visible space.
        right_room = bounds.right() - (anchor.x() + AVATAR_WIDTH)
        left_room = anchor.x() - bounds.left()
        if right_room >= left_room:
            return 0, AVATAR_WIDTH + PANEL_GAP, anchor.x()
        return CHAT_WIDTH + PANEL_GAP, 0, anchor.x() - CHAT_WIDTH - PANEL_GAP

    def _update_hit_region(self):
        """The invisible dock must not block mouse clicks on other programs."""
        region = QRegion(QRect(self.avatar_offset_x, 0, AVATAR_WIDTH, AVATAR_HEIGHT))
        if self.chat_open:
            region = region.united(QRegion(QRect(self.panel_x, 8, CHAT_WIDTH, AVATAR_HEIGHT - 16)))
        self.setMask(region)

    def open_chat(self):
        if not self.text_chat_enabled:
            self.tell("Чат выключен. Голос подключим позже.", 5)
            return
        if self.chat_open:
            self.chat.focus_input()
            return
        if self.chat is None:
            self.chat = EmbeddedChat(self)
            self.chat.setGeometry(self.panel_x, 8, CHAT_WIDTH, AVATAR_HEIGHT - 16)
        self.chat_open = True
        self._update_hit_region()
        self.chat.show()
        self.chat.raise_()
        self.chat.focus_input()
        self.update()

    def hide_chat(self):
        if not self.chat_open:
            return
        self.chat.hide()
        self.chat_open = False
        self._update_hit_region()
        self.update()
        self.save_state()

    def mousePressEvent(self, event):
        if (event.button() == Qt.MouseButton.LeftButton
                and self.avatar_offset_x <= event.position().x()
                < self.avatar_offset_x + AVATAR_WIDTH):
            self.drag_offset = event.globalPosition().toPoint() - self.pos()
            self.drag_start = event.globalPosition().toPoint()
            self.was_dragged = False

    def mouseMoveEvent(self, event):
        if self.drag_offset is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            at = event.globalPosition().toPoint()
            if (at - self.drag_start).manhattanLength() > 3:
                self.was_dragged = True
            self.move(at - self.drag_offset)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.drag_offset is not None:
            self.drag_offset = None
            if self.was_dragged:
                self.save_state()
            elif not self.chat_open:
                self.open_chat()
            else:
                self.hide_chat()

    def toggle_microphone(self):
        if self.voice.isRunning():
            self.voice.stop()
            self.voice_mode = "off"
            self.tell("Микрофон выключен", 3)
        else:
            self._start_voice("once")

    def _start_voice(self, mode):
        self.voice_mode = mode
        if not self.voice.start_listening(mode):
            self.voice_mode = "off"
            self.tell("Нужна модель Vosk в models/ru", 5)
        else:
            self.tell("Слушаю…" if mode == "once" else "Жду обращения «Райя»", 4)

    def _voice_status(self, status):
        if self.chat is not None:
            self.chat.mic_button.setText("■ Выключить микрофон" if status == "listening" else "🎙 Сказать команду")

    def _voice_error(self, problem):
        logger.error("Speech recognition error: %s", problem)
        self.tell("Ошибка микрофона — см. logs/raya.log", 6)
        self.voice_mode = "off"

    def _voice_recognized(self, phrase):
        logger.info("Voice command recognized (content omitted)")
        # Avoid recording the assistant's synthetic reply as a new command.
        self.voice.stop()
        self.voice_mode = "off"
        if self.chat is None:
            self.chat = EmbeddedChat(self)
            self.chat.setGeometry(self.panel_x, 8, CHAT_WIDTH, AVATAR_HEIGHT - 16)
        self.chat.send_text(phrase)
        self.tell("Услышала команду", 3)

    def say(self, text):
        if self.tts_enabled:
            self.tts.speak(text)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        open_action = menu.addAction("Показать / скрыть встроенный чат")
        open_action.setEnabled(self.text_chat_enabled)
        chat_action = menu.addAction("Текстовый чат включён")
        chat_action.setCheckable(True)
        chat_action.setChecked(self.text_chat_enabled)
        chat_action.setToolTip("Если выключить, Райя останется на экране; голос добавим позже")
        breathe_action = menu.addAction("Плавное дыхание")
        breathe_action.setCheckable(True)
        breathe_action.setChecked(self.float_enabled)
        menu.addSeparator()
        once_action = menu.addAction("🎙 Слушать одну команду")
        wake_action = menu.addAction("Активация по имени «Райя»")
        wake_action.setCheckable(True)
        wake_action.setChecked(self.voice.isRunning() and self.voice_mode == "wake")
        mute_action = menu.addAction("Озвучивать ответы")
        mute_action.setCheckable(True)
        mute_action.setChecked(self.tts_enabled)
        menu.addSeparator()
        logs_action = menu.addAction("Открыть папку логов")
        exit_action = menu.addAction("Выход")
        action = menu.exec(event.globalPos())

        if action == open_action:
            self.hide_chat() if self.chat_open else self.open_chat()
        elif action == chat_action:
            self.text_chat_enabled = chat_action.isChecked()
            if not self.text_chat_enabled:
                self.hide_chat()
                self.tell("Чат скрыт. Голос подключим позже.", 5)
            else:
                self.tell("Текстовый чат включён", 3)
            self.save_state()
        elif action == breathe_action:
            self.float_enabled = breathe_action.isChecked()
            self.save_state()
        elif action == once_action:
            self.voice.stop()
            self._start_voice("once")
        elif action == wake_action:
            if wake_action.isChecked():
                self.voice.stop()
                self._start_voice("wake")
            else:
                self.voice.stop()
                self.voice_mode = "off"
                self.tell("Ожидание имени выключено", 3)
        elif action == mute_action:
            self.tts_enabled = mute_action.isChecked()
            if not self.tts_enabled:
                self.tts.stop()
            self.save_state()
        elif action == logs_action:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(str(LOG_DIR))
        elif action == exit_action:
            self.close()

    def save_state(self):
        position = self.avatar_origin()
        self.settings.update({
            "x": position.x(),
            "y": position.y(),
            "float_enabled": self.float_enabled,
            "text_chat_enabled": self.text_chat_enabled,
            "tts_enabled": self.tts_enabled,
        })
        save_settings(self.settings)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self.chat_open:
            self.hide_chat()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self.voice.stop()
        self.tts.stop()
        self.save_state()
        logger.info("Raya Prime closed")
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    avatar = RayaAvatar()
    avatar.show()
    return app.exec()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        logger.exception("Fatal Raya Prime error")
        raise
