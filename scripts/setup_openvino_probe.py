"""Install verified, pinned official OpenVINO weights without replacing models.

Only public model metadata/weights are transferred. No microphone/audio is read.
An existing valid model is reused. New downloads stay in a sibling staging
directory until every asset passes its pinned checksum; existing invalid model
directories are preserved and require an explicit user repair/removal decision.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import time

REPOSITORY = "OpenVINO/whisper-large-v3-turbo-int8-ov"
REVISION = "b568445dd5dc8c695bde596f8acbb4694fd6ba64"
ROOT = Path(__file__).resolve().parents[1]
TARGET = Path(os.environ["LOCALAPPDATA"]) / "T-Voice" / "models" / "turbo-ov"


def verify_assets(directory: Path, files) -> list[dict]:
    """Read-only verification against immutable Hub metadata, including small files."""
    checked = []
    for entry in files:
        path = directory / entry.rfilename
        if not path.is_file() or path.stat().st_size != entry.size:
            raise ValueError(f"Model dosyası eksik veya boyutu yanlış: {entry.rfilename}")
        with path.open("rb") as source:
            sha256 = hashlib.file_digest(source, "sha256").hexdigest()
        if entry.lfs and sha256 != entry.lfs.sha256:
            raise ValueError(f"Model SHA256 doğrulaması başarısız: {entry.rfilename}")
        if not entry.lfs:
            digest = hashlib.sha1(f"blob {entry.size}\0".encode())
            with path.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
            if digest.hexdigest() != entry.blob_id:
                raise ValueError(f"Model Git blob doğrulaması başarısız: {entry.rfilename}")
        checked.append({"name": entry.rfilename, "size": entry.size, "sha256": sha256,
                        "verified_against": "lfs_sha256" if entry.lfs else "git_blob_sha1"})
    return checked


def main(target: Path | None = None) -> Path:
    os.environ["HF_HUB_OFFLINE"] = "0"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
    from huggingface_hub import HfApi, snapshot_download
    target = Path(target) if target is not None else TARGET
    info = HfApi().model_info(REPOSITORY, revision=REVISION, files_metadata=True, token=False)
    if info.sha != REVISION:
        raise RuntimeError("Unexpected repository revision")
    files = [entry for entry in info.siblings if entry.rfilename.endswith((".bin", ".xml", ".json", ".txt"))]
    for entry in files:
        if Path(entry.rfilename).name != entry.rfilename or not entry.blob_id:
            raise RuntimeError("Unexpected nested model asset")
    started = time.perf_counter()
    if target.exists() or target.is_symlink():
        if not target.is_dir():
            raise ValueError(f"Model konumunda bir dosya var; korunuyor: {target}")
        try:
            checked = verify_assets(target, files)
        except (OSError, ValueError) as exc:
            raise ValueError(
                f"Mevcut model değiştirilmedi: {exc}. Ayarlardan Small modelini kullan; "
                f"bu klasörü yedekleyip kaldırdıktan sonra kurulumu yeniden başlat: {target}"
            ) from None
        reused = True
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=target.name + "-staging-", dir=target.parent))
        snapshot_download(REPOSITORY, revision=REVISION, local_dir=staging,
                          allow_patterns=[entry.rfilename for entry in files], token=False,
                          max_workers=2)
        checked = verify_assets(staging, files)
        # The active model directory is never populated with partial downloads.
        # Do not replace a directory published by another installer in the meantime.
        if target.exists() or target.is_symlink():
            raise ValueError(f"Kurulum sırasında model konumu oluşturuldu; korunuyor: {target}. Yeniden çalıştır.")
        os.replace(staging, target)
        reused = False
    report = {"repository": REPOSITORY, "revision": REVISION, "path": str(target),
              "reused_existing": reused,
              "elapsed_seconds": time.perf_counter() - started,
              "size_bytes": sum(entry["size"] for entry in checked), "files": checked}
    report_path = ROOT / ".test-artifacts" / "openvino-model.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "files"}), flush=True)
    return target


if __name__ == "__main__":
    main()
