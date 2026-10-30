"""Optional offline Russian speech recognition and Windows TTS for Raya Prime.

Microphone is disabled by default. No audio is stored or uploaded.
"""
import base64
import json
import logging
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal

LOG = logging.getLogger('raya')
BASE = Path(__file__).resolve().parent
MODEL = BASE / 'models' / 'ru'


def extract_command(text, mode, armed_until):
    text = text.strip().lower()
    if not text:
        return None, armed_until
    if mode == 'once':
        return text, armed_until
    # Typical speech recognition inflections and short misrecognitions.
    match = re.search(r'\b(райя|рая|райе|райю)\b', text)
    if match:
        remaining = text[match.end():].strip(' ,.!?—:-')
        if remaining:
            return remaining, 0.0
        return None, time.monotonic() + 12.0
    if time.monotonic() < armed_until:
        return text, 0.0
    return None, armed_until


class VoiceController(QObject):
    recognized = Signal(str)
    status_changed = Signal(str)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop = threading.Event()
        self._thread = None
        self._mode = 'once'

    def isRunning(self):
        return self._thread is not None and self._thread.is_alive() and not self._stop.is_set()

    def start_listening(self, mode='once'):
        if not MODEL.is_dir() or not (MODEL / 'am').exists():
            self.error.emit(f'Vosk model missing: {MODEL}. Run setup_voice.py')
            return False
        if self.isRunning():
            return True
        if self._thread is not None and self._thread.is_alive():
            return False
        self._mode = mode
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._listen, args=(self._stop, mode), daemon=True, name='RayaMic')
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()
        self.status_changed.emit('stopped')

    def _listen(self, stop, mode):
        try:
            import sounddevice as sd
            from vosk import Model, KaldiRecognizer, SetLogLevel
            SetLogLevel(-1)
            model = Model(str(MODEL))
            device_info = sd.query_devices(kind='input')
            rate = int(device_info['default_samplerate'])
            recognizer = KaldiRecognizer(model, rate)
            sounds = queue.Queue(maxsize=40)

            def callback(indata, frames, time_info, status):
                if stop.is_set():
                    return
                try:
                    sounds.put_nowait(bytes(indata))
                except queue.Full:
                    pass

            with sd.RawInputStream(samplerate=rate, blocksize=4000, dtype='int16', channels=1, callback=callback):
                self.status_changed.emit('listening')
                armed_until = 0.0
                while not stop.is_set():
                    try:
                        block = sounds.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    if recognizer.AcceptWaveform(block):
                        phrase = json.loads(recognizer.Result()).get('text', '')
                        command, armed_until = extract_command(phrase, mode, armed_until)
                        if command:
                            stop.set()
                            self.recognized.emit(command)
                            break
        except Exception as exc:
            LOG.exception('Voice listener failed')
            self.error.emit(str(exc))
        finally:
            self.status_changed.emit('stopped')


class SpeechSynthesizer(QObject):
    """Speak via Windows System.Speech; selects a female installed voice if available."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process = None

    def stop(self):
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()
        self._process = None

    def speak(self, text):
        if sys.platform != 'win32':
            return
        self.stop()
        # Do not treat generated response as PowerShell code.
        payload = base64.b64encode(text[:3000].encode('utf-8')).decode('ascii')
        script = (
            'Add-Type -AssemblyName System.Speech; '
            '$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; '
            '$v=$s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Gender -eq "Female" } | Select-Object -First 1; '
            'if ($v) { $s.SelectVoice($v.VoiceInfo.Name) }; '
            f'$t=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("{payload}")); '
            '$s.Speak($t); $s.Dispose()'
        )
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        try:
            self._process = subprocess.Popen(
                ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                creationflags=flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except OSError:
            LOG.exception('Speech synthesis failed')
