"""Generate local icon and dependency notices for reproducible personal builds."""
import importlib.metadata
import json
import os
from pathlib import Path
import re
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["QT_QPA_PLATFORM"] = "offscreen"


def main():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from duru.app import app_icon
    app = QApplication.instance() or QApplication([])
    pixmap = app_icon().pixmap(128, 128)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    pixmap.save(buffer, "PNG")
    png = bytes(data)
    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)
    (assets / "tvoice.ico").write_bytes(struct.pack("<HHH", 0, 1, 1) +
        struct.pack("<BBBBHHII", 128, 128, 0, 0, 1, 32, len(png), 22) + png)
    notices = ["T-VOICE — THIRD-PARTY NOTICES", "",
        "The original T-Voice application source is delivered to Talha for unrestricted personal modification and use.",
        "Bundled dependencies and speech models remain subject to their respective licenses.",
        "PySide6/Qt is dynamically linked under its applicable LGPL/GPL/commercial terms; LGPL components are used here.",
        "Qt/PySide DLLs in _internal can be replaced with compatible user-built versions. T-Voice source and build instructions are included.",
        "Qt upstream source: https://code.qt.io/ ; PySide source: https://code.qt.io/cgit/pyside/pyside-setup.git/",
        "Python source: https://www.python.org/downloads/source/",
        "Whisper model source and MIT license: https://github.com/openai/whisper",
        "Converted models: https://huggingface.co/Systran/faster-whisper-small and https://huggingface.co/OpenVINO/whisper-large-v3-turbo-int8-ov", ""]
    names = []
    for line in (ROOT / "requirements.txt").read_text().splitlines():
        match = re.match(r"([a-zA-Z0-9_-]+)==", line)
        if match:
            names.append(match.group(1))
    entries = []
    for name in sorted(set(names)):
        dist = importlib.metadata.distribution(name)
        meta = dist.metadata
        notices.extend(["="*72, f"{meta['Name']} {dist.version}",
                        f"License: {meta.get('License-Expression') or meta.get('License') or 'See license text below'}"])
        notices.extend(meta.get_all("Project-URL") or [])
        included = []
        for item in dist.files or []:
            base = Path(str(item)).name.lower()
            if base.startswith(("license", "copying", "notice")) and not base.endswith((".py", ".pyc")):
                path = Path(dist.locate_file(item))
                if path.is_file() and path.stat().st_size < 400_000:
                    try:
                        content = path.read_text(encoding="utf-8")
                    except (UnicodeError, OSError):
                        continue
                    notices.extend([f"--- {item} ---", content])
                    included.append(str(item))
        entries.append({"name": meta["Name"], "version": dist.version, "license_files": included})
    for license_file in sorted((ROOT / "licenses").glob("*.txt")):
        notices.extend(["="*72, license_file.stem, license_file.read_text(encoding="utf-8")])
    (ROOT / "THIRD_PARTY_LICENSES.txt").write_text("\n".join(notices), encoding="utf-8")
    (ROOT / ".test-artifacts").mkdir(exist_ok=True)
    (ROOT / ".test-artifacts" / "dependencies.json").write_text(json.dumps(entries, indent=2), encoding="utf-8")
    print(f"Icon and license notices generated for {len(entries)} dependencies.")


if __name__ == "__main__":
    main()
