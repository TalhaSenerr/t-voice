"""Explicit, pinned model-only download. Never called during dictation.

Only public model files are downloaded; this script accepts no audio input.
The repo is the alias used by faster-whisper's official model map. Hugging Face
currently redirects it to dropbox-dash/faster-whisper-large-v3-turbo.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPOSITORY = "mobiuslabsgmbh/faster-whisper-large-v3-turbo"
REVISION = "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf"
MODEL_SHA256 = "e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da"
FILES = ("config.json", "preprocessor_config.json", "tokenizer.json", "vocabulary.json", "model.bin")
ROOT = Path(__file__).resolve().parents[1]
TARGET = Path(os.environ["LOCALAPPDATA"]) / "T-Voice" / "models" / "turbo"


def hashes(path: Path) -> tuple[str, str]:
    sha256 = hashlib.sha256()
    git = hashlib.sha1(f"blob {path.stat().st_size}\0".encode("ascii"))
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            sha256.update(chunk)
            git.update(chunk)
    return sha256.hexdigest(), git.hexdigest()


def verify(path: Path, metadata: dict) -> dict:
    sha256, git = hashes(path)
    if path.stat().st_size != metadata["size"]:
        raise ValueError(f"Size mismatch: {path.name}")
    lfs = metadata.get("lfs")
    if lfs:
        if sha256 != lfs["sha256"]:
            raise ValueError(f"Public LFS SHA256 mismatch: {path.name}")
    elif git != metadata["blobId"]:
        raise ValueError(f"Pinned Git blob mismatch: {path.name}")
    if path.name.startswith("model.bin") and sha256 != MODEL_SHA256:
        raise ValueError("Pinned model SHA256 mismatch")
    return {"bytes": path.stat().st_size, "sha256": sha256,
            "git_blob": git if not lfs else metadata["blobId"],
            "verified_against": "public pinned LFS SHA256" if lfs else "public pinned Git blob SHA1"}


def main() -> int:
    api_url = f"https://huggingface.co/api/models/{REPOSITORY}/revision/{REVISION}?blobs=true"
    with urllib.request.urlopen(api_url, timeout=60) as response:
        metadata = json.load(response)
    if metadata["sha"] != REVISION:
        raise ValueError("Model revision does not match pinned commit")
    remote_files = {item["rfilename"]: item for item in metadata["siblings"]}
    if remote_files["model.bin"]["lfs"]["sha256"] != MODEL_SHA256:
        raise ValueError("Public model checksum does not match pinned checksum")
    TARGET.mkdir(parents=True, exist_ok=True)
    report = {"checked_at_utc": datetime.now(timezone.utc).isoformat(),
              "requested_repository": REPOSITORY, "resolved_repository": metadata["id"],
              "revision": REVISION, "metadata_url": api_url, "local_path": str(TARGET),
              "files": {}, "audio_uploaded": False}
    for name in FILES:
        target = TARGET / name
        expected = remote_files[name]
        if target.is_file():
            try:
                report["files"][name] = verify(target, expected)
                print(f"Verified existing {name}", flush=True)
                continue
            except ValueError:
                pass
        temporary = TARGET / (name + ".download")
        url = f"https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/{name}"
        print(f"Downloading {name}: {expected['size']:,} bytes", flush=True)
        started = time.perf_counter()
        last_report = started
        received = 0
        with urllib.request.urlopen(url, timeout=120) as response, temporary.open("wb") as stream:
            while chunk := response.read(8 * 1024 * 1024):
                stream.write(chunk)
                received += len(chunk)
                now = time.perf_counter()
                if now - last_report >= 10:
                    print(f"{name}: {received / expected['size']:.0%}, {received / (now - started) / 1e6:.1f} MB/s", flush=True)
                    last_report = now
        verified = verify(temporary, expected)
        temporary.replace(target)
        report["files"][name] = verified
        print(f"Verified {name} in {time.perf_counter() - started:.1f}s", flush=True)
    output = ROOT / ".test-artifacts" / "turbo-model-integrity.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Model ready: {TARGET}", flush=True)
    print(f"Integrity report: {output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
