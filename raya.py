"""Raya Prime v0.2 — smooth 2D avatar with local Ollama chat."""
import json
from html import escape
import logging
import math
import os
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer, QByteArray, QUrl
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QLineEdit,
                               QMenu, QPushButton, QTextBrowser, QVBoxLayout,
                               QWidget)

BASE_DIR = Path(__file__).resolve().parent
ART = BASE_DIR / 'assets' / 'raya.png'
DATA_DIR = BASE_DIR / 'data'
LOG_DIR = BASE_DIR / 'logs'
SETTINGS_PATH = DATA_DIR / 'settings.json'
WIDTH, HEIGHT = 345, 470
OLLAMA_URL = 'http://127.0.0.1:11434/api/chat'
OLLAMA_MODEL = 'raya-prime'


def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger('raya')
    log.setLevel(logging.INFO)
    if not log.handlers:
        handler = RotatingFileHandler(LOG_DIR / 'raya.log', maxBytes=1_000_000,
                                      backupCount=3, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'))
        log.addHandler(handler)
    return log


logger = setup_logging()


def load_settings():
    try:
        if SETTINGS_PATH.is_file():
            value = json.loads(SETTINGS_PATH.read_text(encoding='utf-8'))
            return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        logger.exception('Could not load settings')
    return {}


def save_settings(data):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_PATH.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(SETTINGS_PATH)
    except OSError:
        logger.exception('Could not save settings')



class RayaChat(QWidget):
    """Nonblocking local chat. The avatar keeps animating while Ollama answers."""

    def __init__(self, avatar):
        super().__init__()
        self.avatar = avatar
        self.setWindowTitle('Райя-Прайм — диалог')
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.resize(440, 480)
        self.setMinimumSize(350, 360)
        self.setStyleSheet('''
            QWidget {background: #111827; color: #e5eefb; font: 10pt 'Segoe UI';}
            QTextBrowser {background: #192237; border: 1px solid #334155;
                          border-radius: 9px; padding: 10px;}
            QLineEdit {background: #192237; color: white; border: 1px solid #496182;
                       border-radius: 8px; padding: 9px;}
            QPushButton {background: #3269b5; border: 0; border-radius: 8px;
                         padding: 10px 14px; color: white; font-weight: bold;}
            QPushButton:disabled {background: #334155; color: #94a3b8;}
            QLabel {color: #a8b8d4;}
        ''')

        layout = QVBoxLayout(self)
        title = QLabel('Райя-Прайм  •  локальный ИИ')
        title.setStyleSheet('font-size: 13pt; font-weight: bold; color: #9cd9ff;')
        layout.addWidget(title)
        self.history_view = QTextBrowser()
        self.history_view.setOpenExternalLinks(False)
        layout.addWidget(self.history_view, 1)

        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText('Напиши Райе сообщение...')
        self.input.returnPressed.connect(self.send_message)
        row.addWidget(self.input, 1)
        self.send_button = QPushButton('Отправить')
        self.send_button.clicked.connect(self.send_message)
        row.addWidget(self.send_button)
        layout.addLayout(row)
        self.status = QLabel('Ollama: 127.0.0.1:11434  |  Модель: raya-prime')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.network = QNetworkAccessManager(self)
        self.messages = []  # RAM only; never writes private chat history to GitHub/logs
        self.pending = None
        self._add_line('Райя', 'Я на связи. Что у нас сегодня?')

    def _add_line(self, who, message):
        name = escape(who)
        body = escape(message).replace('\n', '<br>')
        self.history_view.append(f'<p><b style="color:#80d2ff">{name}</b><br>{body}</p>')
        self.history_view.verticalScrollBar().setValue(
            self.history_view.verticalScrollBar().maximum())

    def open_near_avatar(self):
        if not self.isVisible():
            # Prefer beside the avatar, not covering the character.
            screen = QApplication.primaryScreen().availableGeometry()
            right_x = self.avatar.x() + self.avatar.width() + 12
            x = right_x if right_x + self.width() <= screen.right() else max(screen.left(), self.avatar.x() - self.width() - 12)
            y = min(max(self.avatar.y(), screen.top()), max(screen.top(), screen.bottom() - self.height()))
            self.move(x, y)
            self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()

    def send_message(self):
        if self.pending is not None:
            return
        question = self.input.text().strip()
        if not question:
            return
        self.input.clear()
        self._add_line('Ты', question)
        self.messages.append({'role': 'user', 'content': question})
        # Keep at most 12 recent user+assistant exchanges in the context window.
        recent = self.messages[-24:]
        payload = json.dumps({
            'model': OLLAMA_MODEL,
            'messages': recent,
            'stream': False,
        }, ensure_ascii=False).encode('utf-8')
        request = QNetworkRequest(QUrl(OLLAMA_URL))
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, 'application/json')
        request.setTransferTimeout(180_000)
        self.status.setText('Райя обдумывает ответ...')
        self.send_button.setEnabled(False)
        self.input.setEnabled(False)
        self.avatar.tell('Думаю...', 180)
        reply = self.network.post(request, QByteArray(payload))
        self.pending = reply
        reply.finished.connect(lambda r=reply: self._request_finished(r))
        logger.info('Ollama request started (content not logged)')

    def _request_finished(self, reply):
        if self.pending is not reply:
            reply.deleteLater()
            return
        self.pending = None
        self.send_button.setEnabled(True)
        self.input.setEnabled(True)
        self.input.setFocus()
        try:
            raw = bytes(reply.readAll()).decode('utf-8', errors='replace')
            if reply.error() != QNetworkReply.NetworkError.NoError:
                status_code = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
                if status_code == 404:
                    raise RuntimeError('HTTP 404: requested Ollama model not found')
                raise RuntimeError(f'Ollama network error: {reply.errorString()} (HTTP {status_code})')
            result = json.loads(raw)
            answer = result.get('message', {}).get('content', '').strip()
            if not answer:
                raise RuntimeError('Ollama returned an empty answer')
        except Exception as exc:
            # Remove the last user turn; on retry it shouldn't be sent twice.
            if self.messages and self.messages[-1].get('role') == 'user':
                self.messages.pop()
            logger.warning('Ollama request failed: %s', exc)
            if 'Connection refused' in str(exc) or 'Connection refused' in reply.errorString():
                note = 'Не могу подключиться к Ollama. Запусти Ollama и повтори запрос.'
            elif '404' in str(exc) or 'model not found' in str(exc).lower():
                note = 'Модель raya-prime не найдена. Проверь: ollama list'
            else:
                note = 'Не получилось получить ответ. Подробности в logs/raya.log.'
            self._add_line('Система', note)
            self.status.setText('Ошибка подключения или ответа Ollama')
            self.avatar.tell('Ошибка подключения', 5)
        else:
            self.messages.append({'role': 'assistant', 'content': answer})
            self._add_line('Райя', answer)
            self.status.setText('Готова  •  Локальный ИИ')
            self.avatar.tell('Ответила в чате', 4)
            logger.info('Ollama reply received (%d characters)', len(answer))
        finally:
            reply.deleteLater()


class RayaAvatar(QWidget):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.setWindowTitle('Raya Prime')
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowStaysOnTopHint |
                            Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(WIDTH, HEIGHT)
        self.move(int(self.settings.get('x', 100)), int(self.settings.get('y', 150)))
        if not ART.is_file():
            raise FileNotFoundError(f'Avatar image is missing: {ART}')
        self.pixmap = QPixmap(str(ART))
        if self.pixmap.isNull():
            raise RuntimeError(f'Cannot load avatar image: {ART}')
        # Keep full-resolution pixels for resampling at fractional geometry.
        original = self.pixmap.size()
        fit = min((WIDTH - 20) / original.width(),
                  (HEIGHT - 60) / original.height())
        self.draw_width = original.width() * fit
        self.draw_height = original.height() * fit
        self.float_enabled = bool(self.settings.get('float_enabled', True))
        self.message = ''
        self.message_expires = 0.0
        self.drag_offset = None
        self.was_dragged = False
        self.chat = None
        self.start = time.perf_counter()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.update)
        self.timer.start(16)  # target ~60 repaints/s (not guaranteed)
        logger.info('Starting Raya Prime v0.2 (Qt renderer + Ollama chat)')

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        elapsed = time.perf_counter() - self.start
        # No vertical bobbing: at this size it looks like pixel stepping.
        # Instead gently scale around a fixed bottom anchor every 8 seconds.
        wave = math.sin(2.0 * math.pi * elapsed / 8.0)
        scale = 1.0 + (0.0045 * wave if self.float_enabled else 0.0)
        draw_w = self.draw_width * scale
        draw_h = self.draw_height * scale
        x = (WIDTH - draw_w) / 2.0
        bottom = 40.0 + self.draw_height
        y = bottom - draw_h
        painter.drawPixmap(QRectF(x, y, draw_w, draw_h),
                           self.pixmap, QRectF(self.pixmap.rect()))
        if self.message and time.perf_counter() < self.message_expires:
            painter.setPen(QColor('#63bdf9'))
            painter.setBrush(QColor('#141c37'))
            painter.drawRoundedRect(QRectF(5, 2, WIDTH - 10, 42), 8, 8)
            painter.setPen(QColor('#e8f5ff'))
            painter.setFont(QFont('Segoe UI', 9))
            text = self.message if len(self.message) <= 45 else self.message[:43] + '…'
            painter.drawText(QRectF(9, 2, WIDTH - 18, 42), Qt.AlignmentFlag.AlignCenter, text)
        painter.end()

    def tell(self, text, seconds=4):
        self.message = text
        self.message_expires = time.perf_counter() + seconds
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_offset = event.globalPosition().toPoint() - self.pos()
            self.drag_start = event.globalPosition().toPoint()
            self.was_dragged = False

    def mouseMoveEvent(self, event):
        if self.drag_offset is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            current = event.globalPosition().toPoint()
            if (current - self.drag_start).manhattanLength() > 3:
                self.was_dragged = True
            self.move(current - self.drag_offset)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_offset = None
            if self.was_dragged:
                self.save_state()
            else:
                self.open_chat()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        talk = menu.addAction('Поговорить с Райей')
        hide = menu.addAction('Скрыть подсказку')
        bob_action = menu.addAction('Мягкое дыхание (без покачивания)')
        bob_action.setCheckable(True)
        bob_action.setChecked(self.float_enabled)
        menu.addSeparator()
        logs = menu.addAction('Открыть папку логов')
        exit_action = menu.addAction('Выход')
        chosen = menu.exec(event.globalPos())
        if chosen == talk:
            self.open_chat()
        elif chosen == hide:
            self.message = ''
            self.update()
        elif chosen == bob_action:
            self.float_enabled = bob_action.isChecked()
            self.save_state()
        elif chosen == logs:
            os.startfile(str(LOG_DIR))
        elif chosen == exit_action:
            self.close()

    def open_chat(self):
        if self.chat is None:
            self.chat = RayaChat(self)
        self.chat.open_near_avatar()

    def save_state(self):
        save_settings({'x': self.x(), 'y': self.y(),
                       'float_enabled': self.float_enabled})

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()

    def closeEvent(self, event):
        if self.chat is not None:
            self.chat.close()
        self.save_state()
        logger.info('Raya Prime closed')
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    avatar = RayaAvatar()
    avatar.show()
    return app.exec()


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        logger.exception('Fatal Raya Prime error')
        raise
