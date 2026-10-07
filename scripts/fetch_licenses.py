"""Fetch missing upstream license texts at setup time, never at app runtime."""
import concurrent.futures
from pathlib import Path
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    'Whisper': ['https://raw.githubusercontent.com/openai/whisper/main/LICENSE'],
    'CTranslate2': ['https://raw.githubusercontent.com/OpenNMT/CTranslate2/v4.8.2/LICENSE', 'https://raw.githubusercontent.com/OpenNMT/CTranslate2/master/LICENSE'],
    'Flatbuffers': ['https://raw.githubusercontent.com/google/flatbuffers/v25.12.19/LICENSE', 'https://raw.githubusercontent.com/google/flatbuffers/master/LICENSE'],
    'Tokenizers': ['https://raw.githubusercontent.com/huggingface/tokenizers/v0.23.2/LICENSE', 'https://raw.githubusercontent.com/huggingface/tokenizers/main/LICENSE'],
    'tqdm': ['https://raw.githubusercontent.com/tqdm/tqdm/v4.70.1/LICENCE', 'https://raw.githubusercontent.com/tqdm/tqdm/master/LICENCE'],
    'PortAudio': ['https://raw.githubusercontent.com/PortAudio/portaudio/master/LICENSE.txt'],
    'Python': ['https://raw.githubusercontent.com/python/cpython/v3.12.13/LICENSE'],
    'Qt-LGPL-3': ['https://raw.githubusercontent.com/qt/qtbase/dev/LICENSES/LGPL-3.0-only.txt'],
    'Qt-GPL-3': ['https://raw.githubusercontent.com/qt/qtbase/dev/LICENSES/GPL-3.0-only.txt'],
    'FFmpeg-LICENSE': ['https://raw.githubusercontent.com/FFmpeg/FFmpeg/master/LICENSE.md'],
    'FFmpeg-LGPL-2.1': ['https://raw.githubusercontent.com/FFmpeg/FFmpeg/master/COPYING.LGPLv2.1'],
}


def fetch(entry):
    name, urls = entry
    for url in urls:
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                content = response.read(500_000).decode('utf-8')
            path = ROOT / 'licenses' / f'{name}.txt'
            path.parent.mkdir(exist_ok=True)
            path.write_text(f'Source: {url}\n\n{content}', encoding='utf-8')
            return name, True
        except (urllib.error.URLError, UnicodeError):
            pass
    return name, False


if __name__ == '__main__':
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(fetch, SOURCES.items()))
    for name, okay in results:
        print(name, 'OK' if okay else 'FAILED')
    raise SystemExit(0 if all(okay for _, okay in results) else 1)
