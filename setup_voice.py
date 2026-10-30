"""One-time, user-invoked download of the official Vosk Russian model."""
from pathlib import Path
import shutil
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / 'models' / 'ru'
URL = 'https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip'


def main():
    if (TARGET / 'am').is_dir():
        print('Russian speech model already installed:', TARGET)
        return
    (ROOT / 'models').mkdir(exist_ok=True)
    print('Downloading Russian speech recognition model from', URL)
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / 'model.zip'
        urllib.request.urlretrieve(URL, archive)
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                p = Path(info.filename)
                if p.is_absolute() or '..' in p.parts:
                    raise ValueError('Unsafe file path inside archive')
            z.extractall(tmp)
        extracted = Path(tmp) / 'vosk-model-small-ru-0.22'
        if not (extracted / 'am').is_dir():
            raise ValueError('Model files not found in downloaded archive')
        shutil.move(str(extracted), str(TARGET))
    print('Voice recognition is ready:', TARGET)


if __name__ == '__main__':
    main()
