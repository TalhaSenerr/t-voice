"""Explicit model-only download; the dictation process never invokes this script."""
import argparse
import os
from pathlib import Path

MODELS = {
    "small": ("Systran/faster-whisper-small", "536b0662742c02347bc0e980a01041f333bce120"),
    "medium": ("Systran/faster-whisper-medium", "08e178d48790749d25932bbc082711ddcfdfbc4f"),
    "turbo-ov": ("OpenVINO/whisper-large-v3-turbo-int8-ov", "b568445dd5dc8c695bde596f8acbb4694fd6ba64"),
}


def main():
    parser = argparse.ArgumentParser(description="T-Voice: sabit sürümlü yerel model indir. Ses dosyası gönderilmez.")
    parser.add_argument("model", choices=MODELS)
    args = parser.parse_args()
    if args.model == "turbo-ov":
        from setup_openvino_probe import main as install_verified_gpu_model
        install_verified_gpu_model()
        return
    os.environ["HF_HUB_OFFLINE"] = "0"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
    from huggingface_hub import snapshot_download
    repo, revision = MODELS[args.model]
    target = Path(os.environ["LOCALAPPDATA"]) / "T-Voice" / "models" / args.model
    snapshot_download(repo_id=repo, revision=revision, local_dir=target, token=False,
                      allow_patterns=["model.bin", "config.json", "tokenizer.json", "vocabulary.*", "preprocessor_config.json"])
    print(f"Model hazır: {target}")


if __name__ == "__main__":
    main()
