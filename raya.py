"""Raya Prime desktop 2D avatar prototype, Windows 11.

This is an animation/window prototype, not yet an AI agent.
"""
import math
import time
import json
import logging
from logging.handlers import RotatingFileHandler
import tkinter as tk
from tkinter import simpledialog
from pathlib import Path

from PIL import Image, ImageTk

BASE_DIR = Path(__file__).resolve().parent
ART = BASE_DIR / 'assets' / 'raya.png'
KEY = '#ff00ff'
WIDTH, HEIGHT = 345, 470
DATA_DIR = BASE_DIR / 'data'
LOG_DIR = BASE_DIR / 'logs'
SETTINGS_PATH = DATA_DIR / 'settings.json'


def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger('raya')
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(LOG_DIR / 'raya.log', maxBytes=1_000_000,
                                  backupCount=3, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'))
    logger.addHandler(handler)
    return logger


logger = setup_logging()


def load_settings():
    try:
        if SETTINGS_PATH.exists():
            result = json.loads(SETTINGS_PATH.read_text(encoding='utf-8'))
            if isinstance(result, dict):
                return result
    except (OSError, ValueError):
        logger.exception('Failed to read settings; using defaults')
    return {}


def save_settings(settings):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        temp = SETTINGS_PATH.with_suffix('.tmp')
        temp.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(SETTINGS_PATH)
    except OSError:
        logger.exception('Failed to save settings')



class RayaApp:
    def __init__(self):
        self.settings = load_settings()
        logger.info('Starting Raya Prime v0.1.4')
        self.root = tk.Tk()
        self.root.report_callback_exception = self.on_callback_error
        self.root.title('Raya Prime — prototype')
        self.root.overrideredirect(True)
        self.root.wm_attributes('-topmost', True)
        self.root.configure(bg=KEY)
        # Windows supports a transparent chroma-keyed window.
        self.root.wm_attributes('-transparentcolor', KEY)
        x = int(self.settings.get('x', 100))
        y = int(self.settings.get('y', 150))
        self.root.geometry(f'{WIDTH}x{HEIGHT}+{x}+{y}')
        self.canvas = tk.Canvas(self.root, width=WIDTH, height=HEIGHT,
                                bg=KEY, highlightthickness=0, bd=0)
        self.canvas.pack()
        self.image = Image.open(ART).convert('RGBA')
        self.image.thumbnail((WIDTH-12, HEIGHT-52), Image.Resampling.LANCZOS)
        self.frames = self.make_frames()
        self.tk_image = None
        self.start_x = self.start_y = 0
        self.dragging = False
        self.frame_number = 0
        self.animation_started = time.monotonic()
        self.float_enabled = tk.BooleanVar(value=bool(self.settings.get('float_enabled', True)))
        self.message = ''
        self.message_until = 0
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label='Поговорить с Райей (демо)', command=self.demo)
        self.menu.add_command(label='Скрыть подсказку', command=self.clear_message)
        self.menu.add_checkbutton(label='Плавное покачивание', variable=self.float_enabled)
        self.menu.add_separator()
        self.menu.add_command(label='Открыть папку логов', command=self.open_logs)
        self.menu.add_command(label='Выход', command=self.close)
        self.canvas.bind('<ButtonPress-1>', self.mouse_down)
        self.canvas.bind('<B1-Motion>', self.mouse_move)
        self.canvas.bind('<ButtonRelease-1>', self.mouse_up)
        self.canvas.bind('<Button-3>', self.context_menu)
        self.root.bind('<Escape>', lambda _: self.close())
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.float_enabled.trace_add('write', lambda *_: self.save_state())
        self.tick()

    def on_callback_error(self, exc_type, exc_value, exc_tb):
        logger.error('Unhandled UI callback error', exc_info=(exc_type, exc_value, exc_tb))
        try:
            self.tell('Ошибка. Подробности в logs/raya.log', 6)
        except Exception:
            pass

    def save_state(self):
        if not self.root.winfo_exists():
            return
        save_settings({'x': self.root.winfo_x(), 'y': self.root.winfo_y(),
                       'float_enabled': self.float_enabled.get()})

    def open_logs(self):
        import os
        os.startfile(str(LOG_DIR))  # Windows only

    def close(self):
        self.save_state()
        logger.info('Raya Prime closed')
        self.root.destroy()

    def make_frames(self):
        # Until we have independently layered eyes/eyelids, do not draw
        # guessed blink lines over the face: these can cross the eyebrows.
        return {False: self.image.copy()}

    def tell(self, line, secs=4):
        self.message = line
        self.message_until = self.frame_number + int(secs*30)

    def clear_message(self):
        self.message = ''

    def mouse_down(self, event):
        self.start_x, self.start_y = event.x_root, event.y_root
        self.dragging = False

    def mouse_move(self, event):
        dx = event.x_root-self.start_x
        dy = event.y_root-self.start_y
        if abs(dx)+abs(dy) > 3:
            self.dragging = True
        self.root.geometry(f'+{self.root.winfo_x()+dx}+{self.root.winfo_y()+dy}')
        self.start_x, self.start_y = event.x_root, event.y_root

    def mouse_up(self, event):
        if self.dragging:
            self.save_state()
        if not self.dragging:
            self.tell('Привет! Я Райя. Сейчас я — анимированный прототип ✨')

    def context_menu(self, event):
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def demo(self):
        question = simpledialog.askstring('Райя — демонстрация',
                                          'Напиши сообщение:', parent=self.root)
        if question is not None:
            self.tell('ИИ и голос ещё не подключены. Вижу: ' + question[:34], 6)

    def tick(self):
        # Create chroma-key image once, not on every animation frame.
        if not hasattr(self, '_cached_avatar'):
            art = self.frames[False]
            rgb = Image.new('RGB', (WIDTH, HEIGHT), (255, 0, 255))
            x = (WIDTH - art.width) // 2
            # Preserve exact-color transparency without purple halo.
            mask = art.getchannel('A').point(lambda a: 255 if a >= 128 else 0)
            rgb.paste(art.convert('RGB'), (x, 40), mask)
            self._cached_avatar = ImageTk.PhotoImage(rgb)
            self._avatar_item = self.canvas.create_image(
                0, 0, image=self._cached_avatar, anchor='nw', tags='avatar'
            )
            self._last_bob = None
            self._bubble_items = []

        elapsed = time.monotonic() - self.animation_started
        # 8-second cycle, +/-4 px. No large per-frame jumps.
        bob = round(4 * math.sin(2 * math.pi * elapsed / 8.0)) if self.float_enabled.get() else 0
        if bob != self._last_bob:
            self.canvas.coords(self._avatar_item, 0, bob)
            self._last_bob = bob

        # Update hint bubble only when its content or visibility changes.
        show_message = self.message and self.frame_number < self.message_until
        content = (self.message[:43] + '…' if len(self.message) > 45 else self.message) if show_message else ''
        if getattr(self, '_shown_message', None) != content:
            for item in self._bubble_items:
                self.canvas.delete(item)
            self._bubble_items.clear()
            self._shown_message = content
            if content:
                self._bubble_items.append(self.canvas.create_rectangle(
                    5, 2, WIDTH-5, 44, fill='#141c37', outline='#63bdf9'
                ))
                self._bubble_items.append(self.canvas.create_text(
                    WIDTH//2, 23, text=content, fill='#e8f5ff', font=('Segoe UI', 9)
                ))
        if not show_message:
            self.message = ''

        self.frame_number += 1
        self.root.after(16, self.tick)
    def run(self):
        self.root.mainloop()


if __name__ == '__main__':
    try:
        RayaApp().run()
    except Exception:
        logger.exception('Fatal Raya Prime error')
        raise
