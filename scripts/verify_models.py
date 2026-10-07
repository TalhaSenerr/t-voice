"""Explicit online verification tool; never imported by the desktop application.

Fetches public Hugging Face metadata without authentication and compares local
model.bin bytes with the LFS SHA-256 recorded at a pinned repository revision.
Does not download or change model files and does not read or upload any audio.
This establishes a match with that repository revision, not general security.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


PINNED_MODELS = {
    "small": {
        "repository": "Systran/faster-whisper-small",
        "revision": "536b0662742c02347bc0e980a01041f333bce120",
    },
    "medium": {
        "repository": "Systran/faster-whisper-medium",
        "revision": "08e178d48790749d25932bbc082711ddcfdfbc4f",
    },
}
CHUNK_BYTES = 1024 * 1024


def cache_roots() -> list[Path]:
    roots = []
    for name in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
        if os.environ.get(name):
            roots.append(Path(os.environ[name]).expanduser())
    if os.environ.get("HF_HOME"):
        roots.append(Path(os.environ["HF_HOME"]).expanduser() / "hub")
    default_cache = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
    roots.append(default_cache / "huggingface" / "hub")
    roots.append(Path.home() / ".cache" / "huggingface" / "hub")
    return list(dict.fromkeys(roots))


def public_metadata(repository: str, revision: str) -> tuple[str, dict]:
    url = f"https://huggingface.co/api/models/{repository}/revision/{revision}?blobs=true"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "T-Voice-model-integrity/1.1", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        final_url = urlparse(response.geturl())
        if final_url.scheme != "https" or final_url.hostname != "huggingface.co":
            raise ValueError("Metadata was redirected outside the expected HTTPS host.")
        payload = response.read(10 * CHUNK_BYTES + 1)
    if len(payload) > 10 * CHUNK_BYTES:
        raise ValueError("Metadata exceeded the size limit.")
    metadata = json.loads(payload)
    if metadata.get("sha") != revision or metadata.get("id", "").casefold() != repository.casefold():
        raise ValueError("Public metadata did not match the pinned repository and revision.")
    return url, metadata


def verify_model(key: str, roots: list[Path]) -> dict:
    specification = PINNED_MODELS[key]
    repository, revision = specification["repository"], specification["revision"]
    relative = Path("models--" + repository.replace("/", "--")) / "snapshots" / revision / "model.bin"
    candidates = [root / relative for root in roots]
    local_file = next((path for path in candidates if path.is_file()), None)
    if local_file is None:
        raise FileNotFoundError(f"The pinned {key} snapshot is not present in the local cache.")
    url, metadata = public_metadata(repository, revision)
    model_metadata = next((file for file in metadata.get("siblings", []) if file.get("rfilename") == "model.bin"), None)
    if model_metadata is None:
        raise ValueError("Public metadata did not include model.bin.")
    lfs = model_metadata.get("lfs") or {}
    expected_sha256 = lfs.get("sha256", "")
    expected_size = lfs.get("size", model_metadata.get("size"))
    if not re.fullmatch(r"[a-f0-9]{64}", expected_sha256):
        raise ValueError("Public metadata did not contain a valid LFS SHA-256.")
    if not isinstance(expected_size, int) or expected_size <= 0:
        raise ValueError("Public metadata did not contain a valid LFS file size.")
    digest = hashlib.sha256()
    actual_size = 0
    with local_file.open("rb") as model_file:
        while chunk := model_file.read(CHUNK_BYTES):
            digest.update(chunk)
            actual_size += len(chunk)
    actual_sha256 = digest.hexdigest()
    return {
        "model": key,
        "repository": repository,
        "revision": revision,
        "metadata_source": url,
        "local_file": str(local_file.resolve()),
        "expected_sha256": expected_sha256,
        "actual_sha256": actual_sha256,
        "expected_size_bytes": expected_size,
        "actual_size_bytes": actual_size,
        "verified": actual_sha256 == expected_sha256 and actual_size == expected_size,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("models", nargs="*", help="small and/or medium; default verifies both")
    parser.add_argument("--cache-root", type=Path, help="Hugging Face hub cache directory")
    parser.add_argument(
        "--output", type=Path,
        default=Path(__file__).resolve().parents[1] / ".test-artifacts" / "model-integrity.json",
    )
    args = parser.parse_args()
    names = list(dict.fromkeys(args.models or PINNED_MODELS))
    if any(name not in PINNED_MODELS for name in names):
        parser.error("Supported model names: small, medium")
    roots = [args.cache_root.expanduser()] if args.cache_root else cache_roots()
    results = []
    for name in names:
        try:
            result = verify_model(name, roots)
        except Exception as error:
            result = {"model": name, **PINNED_MODELS[name], "verified": False, "error": str(error)}
        results.append(result)
        print(f"{name}: {'VERIFIED' if result['verified'] else 'FAILED'}", flush=True)
    report = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "model.bin SHA-256 and byte size against public Hugging Face LFS metadata at pinned revisions",
        "limitation": "Confirms matching repository bytes, not a general security or provenance guarantee; other model files are outside this hash check.",
        "authentication": "none",
        "audio_read_or_uploaded": False,
        "model_files_modified": False,
        "all_verified": all(result["verified"] for result in results),
        "models": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Report: {args.output}", flush=True)
    return 0 if report["all_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
