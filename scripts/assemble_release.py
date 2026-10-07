"""Copy local models and user documentation into the portable folder."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from duru.engine import discover_models

OPENVINO_FILES = {
    "added_tokens.json", "config.json", "generation_config.json", "merges.txt",
    "normalizer.json", "openvino_config.json", "preprocessor_config.json",
    "special_tokens_map.json", "tokenizer.json", "tokenizer_config.json", "vocab.json",
    *(f"{stem}.{suffix}" for stem in (
        "openvino_encoder_model", "openvino_decoder_model",
        "openvino_tokenizer", "openvino_detokenizer",
    ) for suffix in ("xml", "bin")),
}
SMALL_FILES = {"model.bin", "config.json", "tokenizer.json", "vocabulary.txt",
               "vocabulary.json", "preprocessor_config.json"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=ROOT / "dist" / "T-Voice")
    destination = parser.parse_args().destination.resolve()
    if not (destination / "T-Voice.exe").is_file():
        raise RuntimeError("Build T-Voice.exe first")
    available = discover_models()
    required = ("turbo-ov", "small")
    if not set(required).issubset(available):
        raise RuntimeError("Local OpenVINO Whisper Turbo and Small models are required for this portable release")
    models = {key: available[key] for key in required}
    extras = [path.name for path in (destination / "models").glob("*")
              if path.is_dir() and path.name not in required]
    if extras:
        raise RuntimeError(f"Build into a clean release folder; unexpected models: {', '.join(extras)}")
    for key, source in models.items():
        target = destination / "models" / key
        target.mkdir(parents=True, exist_ok=True)
        if key == "turbo-ov":
            missing = sorted(name for name in OPENVINO_FILES if not (source / name).is_file())
            if missing:
                raise RuntimeError(f"OpenVINO model is missing release assets: {', '.join(missing)}")
        for path in source.iterdir():
            allowed = OPENVINO_FILES if key == "turbo-ov" else SMALL_FILES
            if path.is_file() and path.name in allowed:
                shutil.copyfile(path, target / path.name)
    for name in ("KULLANIM.html", "README.txt", "PLAN.txt", "THIRD_PARTY_LICENSES.txt", "TEST-SONUCLARI.txt"):
        source = ROOT / name
        if source.exists():
            shutil.copyfile(source, destination / name)
    manifest = {}
    for file in destination.rglob("*"):
        if file.is_file() and file.name != "SHA256SUMS.json":
            with file.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            manifest[str(file.relative_to(destination)).replace("\\", "/")] = digest
    (destination / "SHA256SUMS.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Portable release: {len(manifest)} files, models: {', '.join(models)}")


if __name__ == "__main__":
    main()
