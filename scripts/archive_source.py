"""Create a source handoff excluding environments, private preferences and audio."""
from pathlib import Path
import os
import zipfile

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {'.venv', '.venv-openvino', 'dist', 'build', 'build-1.2', '__pycache__', '.pytest_cache', '.git', '.test-artifacts', 'release'}


def main():
    target = ROOT / 'release'
    target.mkdir(exist_ok=True)
    archive = target / 'T-Voice-1.2.0-kaynak.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as output:
        for current, dirs, files in os.walk(ROOT):
            dirs[:] = [name for name in dirs if name not in EXCLUDED]
            for name in files:
                path = Path(current) / name
                if path.suffix.lower() in {'.wav', '.mp3', '.dpapi', '.pyc', '.log'} or name.startswith('.test-'):
                    continue
                output.write(path, 'T-Voice/' + str(path.relative_to(ROOT)).replace('\\', '/'))
        reports = {'offline-results.json', 'language-results.json', 'model-integrity.json', 'frozen-smoke-final.json', 'startup-smoke.json', 'tvoice-workflow-source.json', 'tvoice-workflow-frozen.json', 'tvoice-frozen-smoke.json'}
        # Only structured verification reports; microphone/audio artifacts stay
        # excluded along with the rest of the private test-artifact directory.
        reports.update(path.name for path in (ROOT / '.test-artifacts').glob('turbo-*.json'))
        reports.update(path.name for path in (ROOT / '.test-artifacts').glob('openvino-*.json'))
        for name in sorted(reports):
            path = ROOT / '.test-artifacts' / name
            if path.exists():
                output.write(path, 'T-Voice/verification/' + name)
        audit = ROOT / '.test-artifacts-audit.json'
        if audit.exists():
            output.write(audit, 'T-Voice/verification/dependency-audit.json')
    print(archive)
    print(f'{archive.stat().st_size} bytes')


if __name__ == '__main__':
    main()
