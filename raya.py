"""Raya Prime — gentle breathing animation, without pixel-stepping bobbing."""
import json
import logging
import math
import os
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QInputDialog, QMenu, QWidget

BASE_DIR = Path(__file__).resolve().parent
ART = BASE_DIR / 'assets' / 'raya.png'
DATA_DIR = BASE_DIR / 'data'
LOG_DIR = BASE_DIR / 'logs'
SETTINGS_PATH = DATA_DIR / 'settings.json'
WIDTH, HEIGHT = 345, 470


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
        self.start = time.perf_counter()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.update)
        self.timer.start(16)  # target ~60 repaints/s (not guaranteed)
        logger.info('Starting Raya Prime Qt renderer')

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
                self.tell('Привет! Я Райя. Пока я — анимированный прототип ✨')

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        talk = menu.addAction('Поговорить с Райей (демо)')
        hide = menu.addAction('Скрыть подсказку')
        bob_action = menu.addAction('Мягкое дыхание (без покачивания)')
        bob_action.setCheckable(True)
        bob_action.setChecked(self.float_enabled)
        menu.addSeparator()
        logs = menu.addAction('Открыть папку логов')
        exit_action = menu.addAction('Выход')
        chosen = menu.exec(event.globalPos())
        if chosen == talk:
            value, ok = QInputDialog.getText(self, 'Райя — демонстрация', 'Напиши сообщение:')
            if ok:
                self.tell('ИИ и голос ещё не подключены. Вижу: ' + value[:34], 6)
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

    def save_state(self):
        save_settings({'x': self.x(), 'y': self.y(),
                       'float_enabled': self.float_enabled})

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()

    def closeEvent(self, event):
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
