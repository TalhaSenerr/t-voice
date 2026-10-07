"""Bounded offline CPU comparison using existing, synthetic WAV files only.

No microphone is opened and no model is downloaded. These easy synthetic
fixtures cannot measure the user's accuracy, natural code-switching or noise.
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

for flag in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY",
             "HF_HUB_DISABLE_IMPLICIT_TOKEN", "DO_NOT_TRACK", "ORT_DISABLE_TELEMETRY"):
    os.environ[flag] = "1"

NETWORK_ATTEMPTS = []


def prohibit_network(event, args):
    if event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo", "socket.bind"}:
        NETWORK_ATTEMPTS.append(event)
        raise RuntimeError("Network forbidden during offline synthetic benchmark")


sys.addaudithook(prohibit_network)
import onnxruntime
onnxruntime.disable_telemetry_events()
from faster_whisper import WhisperModel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from duru.recorder import decode_file
ARTIFACTS = ROOT / ".test-artifacts"
SMALL = Path.home() / ".cache/huggingface/hub/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120"
TURBO = Path(os.environ["LOCALAPPDATA"]) / "T-Voice/models/turbo"
TERMS = "GitHub, pull request, TypeScript, Talha"
CASES = [
    ("turkish", "turkish.wav", "tr", "Bugün toplantıda yeni projemizi konuştuk. Yarın uygulamayı test edip sonuçları birlikte inceleyeceğiz.", TERMS),
    ("mixed", "turkish-english-mixed.wav", "tr", "Bugün GitHub üzerinden bir pull request açtım ve TypeScript uygulamasını test ettim.", TERMS),
    ("english", "english.wav", "en", "Hello Talha. We will review the GitHub pull request and deploy the TypeScript application tomorrow.", TERMS),
    ("mixed_unhinted", "turkish-english-mixed.wav", "tr", "Bugün GitHub üzerinden bir pull request açtım ve TypeScript uygulamasını test ettim.", None),
]


def word_errors(expected, actual):
    reference = re.findall(r"[^\W_]+", expected.casefold())
    recognized = re.findall(r"[^\W_]+", actual.casefold())
    previous = list(range(len(recognized) + 1))
    for i, a in enumerate(reference, 1):
        current = [i]
        for j, b in enumerate(recognized, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (a != b)))
        previous = current
    return {"errors": previous[-1], "words": len(reference), "wer": previous[-1] / len(reference)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threads", nargs="+", type=int, default=[4, 6])
    parser.add_argument("--beams", nargs="+", type=int, default=[1, 3, 5])
    parser.add_argument("--output", default="turbo-benchmark.json")
    parser.add_argument("--skip-small", action="store_true")
    parser.add_argument("--with-timestamps", action="store_true", help="Compare Turbo using normal timestamp tokens")
    parser.add_argument("--cases", nargs="+", choices=[case[0] for case in CASES], default=[case[0] for case in CASES])
    parser.add_argument("--initial-prompt", default=None, help="Optional generic context; never an expected transcript")
    parser.add_argument("--language", choices=("tr", "en", "auto"), default=None)
    parser.add_argument("--no-vad", action="store_true", help="Diagnostic comparison without speech/silence filtering")
    args = parser.parse_args()
    report = {"checked_at_utc": datetime.now(timezone.utc).isoformat(),
              "audio_source": "Existing local synthetic Windows Tolga/Zira WAV fixtures; no microphone",
              "limitations": "Single synthetic voices and spliced language switches, no real user accuracy claim. Single timed run per case, susceptible to OS scheduling and temperature. Python socket audit is not OS packet capture.",
              "runtime": {"device": "cpu", "compute_type": "int8", "num_workers": 1,
                          "temperature": 0.0, "condition_on_previous_text": False,
                          "vad_filter": not args.no_vad, "vad_parameters": {"min_silence_duration_ms": 500, "speech_pad_ms": 250}},
              "models": {}, "results": [], "network_attempts": NETWORK_ATTEMPTS}
    output = ARTIFACTS / args.output
    if output.parent != ARTIFACTS or not output.name.startswith("turbo-"):
        raise ValueError("Output must be a turbo-* filename within .test-artifacts")
    configs = ([] if args.skip_small else [("small", SMALL, 6, [5], False)])
    configs += [("turbo", TURBO, threads, args.beams, not args.with_timestamps) for threads in args.threads]
    for name, model_path, threads, beams, without_timestamps in configs:
        start = time.perf_counter()
        model = WhisperModel(str(model_path), device="cpu", compute_type="int8", cpu_threads=threads,
                             num_workers=1, local_files_only=True)
        load_seconds = time.perf_counter() - start
        report["models"][f"{name}-{threads}"] = {"path": str(model_path), "load_seconds": round(load_seconds, 3)}
        print(f"Loaded {name} / {threads} threads in {load_seconds:.2f}s", flush=True)
        for beam in beams:
            for case, filename, language, reference, hotwords in CASES:
                if case not in args.cases:
                    continue
                audio = decode_file(str(ARTIFACTS / filename))
                start = time.perf_counter()
                requested_language = args.language or language
                segments, info = model.transcribe(audio, language=None if requested_language == "auto" else requested_language, task="transcribe",
                    beam_size=beam, temperature=0.0, condition_on_previous_text=False,
                    initial_prompt=args.initial_prompt, hotwords=hotwords, vad_filter=not args.no_vad,
                    vad_parameters={"min_silence_duration_ms": 500, "speech_pad_ms": 250},
                    no_speech_threshold=0.6, log_prob_threshold=-1.0, compression_ratio_threshold=2.4,
                    without_timestamps=without_timestamps, log_progress=False)
                text = " ".join(segment.text.strip() for segment in segments).strip()
                elapsed = time.perf_counter() - start
                record = {"model": name, "threads": threads, "beam": beam, "without_timestamps": without_timestamps,
                          "case": case, "duration_seconds": len(audio) / 16000,
                          "transcribe_seconds": round(elapsed, 3), "rtf": round(elapsed / (len(audio) / 16000), 3),
                          "reference": reference, "transcript": text, "language": info.language,
                          "requested_language": requested_language, "initial_prompt": args.initial_prompt,
                          "vad_filter": not args.no_vad,
                          "hotwords": hotwords, "word_errors": word_errors(reference, text)}
                report["results"].append(record)
                print(json.dumps(record, ensure_ascii=True), flush=True)
                output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                audio.fill(0)
        model.model.unload_model()
        del model
        gc.collect()
    report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Report: {output}", flush=True)
    return 1 if NETWORK_ATTEMPTS else 0


if __name__ == "__main__":
    raise SystemExit(main())
