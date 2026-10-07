"""Bounded offline GPU benchmark on existing synthetic fixtures only.

Run --prepare with the main .venv to resample the synthetic WAV files using the
same decoder as T-Voice. Run inference with .venv-openvino, whose optional
openvino-telemetry package must be absent so OpenVINO uses its official stub.
"""
from __future__ import annotations

import argparse
import gc
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / ".test-artifacts"
NETWORK_ATTEMPTS = []
REFERENCES = {
    "turkish": "Bugün toplantıda yeni projemizi konuştuk. Yarın uygulamayı test edip sonuçları birlikte inceleyeceğiz.",
    "turkish-english-mixed": "Bugün GitHub üzerinden bir pull request açtım ve TypeScript uygulamasını test ettim.",
}
CASES = ("turkish", "turkish-english-mixed", "english")
TERMS = ("GitHub", "pull request", "TypeScript")
for flag in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY", "DO_NOT_TRACK"):
    os.environ[flag] = "1"


def deny_network(event, args):
    if event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo", "socket.bind"}:
        NETWORK_ATTEMPTS.append(event)
        raise RuntimeError("Network blocked during isolated OpenVINO inference")


sys.addaudithook(deny_network)


def tokens(text):
    return re.findall(r"[^\W_]+", text.casefold(), flags=re.UNICODE)


def metrics(reference, text):
    expected, actual = tokens(reference), tokens(text)
    previous = list(range(len(actual) + 1))
    for i, left in enumerate(expected, 1):
        row = [i]
        for j, right in enumerate(actual, 1):
            row.append(min(previous[j] + 1, row[-1] + 1, previous[j - 1] + (left != right)))
        previous = row
    return {"errors": previous[-1], "reference_words": len(expected),
            "wer": previous[-1] / max(1, len(expected))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--device", default="GPU", choices=("GPU", "CPU"))
    parser.add_argument("--beam", type=int, default=5)
    parser.add_argument("--passes", type=int, default=2)
    parser.add_argument("--case", nargs="+", choices=CASES, default=list(CASES))
    parser.add_argument("--hints", action="store_true")
    parser.add_argument("--without-timestamps", action="store_true")
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--label", default="gpu")
    args = parser.parse_args()
    import numpy as np
    if args.prepare:
        sys.path.insert(0, str(ROOT))
        from duru.recorder import decode_file
        for name in CASES:
            audio = decode_file(str(ARTIFACTS / f"{name}.wav"))
            try:
                np.save(ARTIFACTS / f"openvino-fixture-{name}.npy", audio, allow_pickle=False)
            finally:
                audio.fill(0)
        print("Prepared synthetic 16 kHz mono fixtures; no microphone used.", flush=True)
        return
    if importlib.util.find_spec("openvino_telemetry") is not None:
        raise RuntimeError("Remove optional openvino-telemetry from isolated environment before inference.")
    import openvino as ov
    import openvino_genai as genai
    model = Path(os.environ["LOCALAPPDATA"]) / "T-Voice" / "models" / "turbo-ov"
    cache = Path(os.environ["LOCALAPPDATA"]) / "T-Voice" / "cache" / "openvino"
    cache.mkdir(parents=True, exist_ok=True)
    had_cache = any(cache.iterdir())
    report = {
        "model": str(model), "device": args.device,
        "device_name": ov.Core().get_property(args.device, "FULL_DEVICE_NAME"),
        "openvino_version": ov.__version__, "genai_version": genai.__version__,
        "cache": str(cache), "cache_existed_before": had_cache,
        "settings": {"num_beams": args.beam, "return_timestamps": not args.without_timestamps,
                     "task": "transcribe", "hotwords": ", ".join(TERMS) if args.hints else None},
        "audio_source": "Existing synthetic SAPI fixtures only; no microphone/user audio.",
        "reference_notes": "English checked for terms only; original synthesis reference is not available in source.",
        "limitations": "Synthetic small sample; no natural microphone quality or OS-level network capture. No VAD in this isolated runtime benchmark.",
        "api": "WhisperPipeline(str(model), device, CACHE_DIR=str(cache)); pipeline.generate(audio.tolist(), language='<|tr|>'/'<|en|>', task='transcribe', num_beams=n, return_timestamps=True)",
        "results": [], "network_attempts": NETWORK_ATTEMPTS,
    }
    output = ARTIFACTS / f"openvino-benchmark-{args.label}.json"
    def save():
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        started = time.perf_counter()
        print(json.dumps({"phase": "compile", "device": args.device, "cache_existed": had_cache}), flush=True)
        pipeline = genai.WhisperPipeline(str(model), args.device, CACHE_DIR=str(cache))
        report["init_seconds"] = time.perf_counter() - started
        print(json.dumps({"phase": "ready", "init_seconds": report["init_seconds"]}), flush=True)
        save()
        for iteration in range(args.passes):
            for name in args.case:
                audio = np.load(ARTIFACTS / f"openvino-fixture-{name}.npy", allow_pickle=False)
                waveform = audio.tolist()
                try:
                    config = {"language": "<|en|>" if name == "english" else "<|tr|>",
                              "task": "transcribe", "num_beams": args.beam,
                              "return_timestamps": not args.without_timestamps}
                    if args.hints:
                        config["hotwords"] = ", ".join(TERMS)
                    started = time.perf_counter()
                    result = pipeline.generate(waveform, **config)
                    elapsed = time.perf_counter() - started
                    text = " ".join(part.strip() for part in result.texts).strip()
                    normalized = " " + " ".join(tokens(text)) + " "
                    record = {"case": name, "iteration": iteration + 1, "duration_seconds": audio.size / 16000,
                              "elapsed_seconds": elapsed, "text": text,
                              "term_hits": {term: " " + " ".join(tokens(term)) + " " in normalized for term in TERMS} if name != "turkish" else {},
                              "word_error_metrics": metrics(REFERENCES[name], text) if name in REFERENCES else None}
                    report["results"].append(record)
                    print(json.dumps(record, ensure_ascii=True), flush=True)
                    save()
                finally:
                    audio.fill(0)
                    waveform.clear()
        if args.reload:
            del pipeline
            gc.collect()
            started = time.perf_counter()
            pipeline = genai.WhisperPipeline(str(model), args.device, CACHE_DIR=str(cache))
            report["cached_init_seconds"] = time.perf_counter() - started
        report["cache_size_bytes"] = sum(path.stat().st_size for path in cache.rglob("*") if path.is_file())
        report["environment_size_bytes"] = sum(path.stat().st_size for path in Path(sys.prefix).rglob("*") if path.is_file())
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        save()


if __name__ == "__main__":
    main()
