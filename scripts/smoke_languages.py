"""Real Turkish/bilingual inference on non-personal, locally synthesized audio.

Uses installed Windows SAPI Tolga/Zira voices and never opens the microphone.
The socket audit covers Python audit events in this process; it is not an OS
packet capture or a security guarantee for native dependencies/subprocesses.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

NETWORK_ATTEMPTS: list[str] = []


def prohibit_network(event, args):
    if event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo", "socket.bind"}:
        NETWORK_ATTEMPTS.append(event)
        raise RuntimeError("Network forbidden during local language smoke test")


sys.addaudithook(prohibit_network)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from duru.engine import SpeechEngine
from duru.recorder import decode_file

ARTIFACTS = ROOT / ".test-artifacts"
TR_REFERENCE = "Bugün toplantıda yeni projemizi konuştuk. Yarın uygulamayı test edip sonuçları birlikte inceleyeceğiz."
MIXED_REFERENCE = "Bugün GitHub üzerinden bir pull request açtım ve TypeScript uygulamasını test ettim."
TERMS = ["GitHub", "pull request", "TypeScript"]
PHRASES = [
    ("tr", "Bugün"),
    ("en", "GitHub"),
    ("tr", "üzerinden bir"),
    ("en", "pull request"),
    ("tr", "açtım ve"),
    ("en", "TypeScript"),
    ("tr", "uygulamasını test ettim."),
]


def synthesize_mixed_clip() -> Path:
    directory = ARTIFACTS / "language-chunks"
    directory.mkdir(parents=True, exist_ok=True)
    chunks = [
        {"language": language, "text": text, "path": str(directory / f"{index:02d}-{language}.wav")}
        for index, (language, text) in enumerate(PHRASES)
    ]
    manifest = directory / "chunks.json"
    manifest.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
    subprocess.run(
        [
            "powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", str(ROOT / "scripts" / "synthesize_language_chunks.ps1"),
            "-ChunksJson", str(manifest),
        ],
        check=True,
        timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    parts = []
    mixed = None
    try:
        for index, chunk in enumerate(chunks):
            if index:
                parts.append(np.zeros(1600, dtype=np.float32))
            parts.append(decode_file(chunk["path"]))
        mixed = np.concatenate(parts)
        output = ARTIFACTS / "turkish-english-mixed.wav"
        with wave.open(str(output), "wb") as destination:
            destination.setnchannels(1)
            destination.setsampwidth(2)
            destination.setframerate(16_000)
            destination.writeframes((np.clip(mixed, -1, 1) * 32767).astype("<i2").tobytes())
        return output
    finally:
        for part in parts:
            part.fill(0)
        if mixed is not None:
            mixed.fill(0)


def normalized_tokens(text: str) -> list[str]:
    # Strip punctuation/case only; never fuzzy-correct names to improve scores.
    return re.findall(r"[^\W_]+", text.casefold(), flags=re.UNICODE)


def word_error_metrics(reference: str, actual: str) -> dict:
    expected, recognized = normalized_tokens(reference), normalized_tokens(actual)
    previous = list(range(len(recognized) + 1))
    for reference_index, reference_word in enumerate(expected, start=1):
        current = [reference_index]
        for actual_index, actual_word in enumerate(recognized, start=1):
            current.append(min(
                previous[actual_index] + 1,
                current[actual_index - 1] + 1,
                previous[actual_index - 1] + (reference_word != actual_word),
            ))
        previous = current
    return {
        "word_errors": previous[-1],
        "reference_word_count": len(expected),
        "normalized_word_error_rate": round(previous[-1] / max(1, len(expected)), 4),
    }


def term_hits(text: str) -> dict[str, bool]:
    normalized = " " + " ".join(normalized_tokens(text)) + " "
    return {term: " " + " ".join(normalized_tokens(term)) + " " in normalized for term in TERMS}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-synthesis", action="store_true", help="Reuse the existing synthetic mixed WAV")
    parser.add_argument("--models", nargs="+", choices=("small", "medium"), default=["small", "medium"])
    args = parser.parse_args()
    ARTIFACTS.mkdir(exist_ok=True)
    mixed_path = ARTIFACTS / "turkish-english-mixed.wav" if args.skip_synthesis else synthesize_mixed_clip()
    tests = [
        ("turkish", ARTIFACTS / "turkish.wav", TR_REFERENCE),
        ("turkish_english_mixed", mixed_path, MIXED_REFERENCE),
    ]
    engine = SpeechEngine()
    results = []
    for model in dict.fromkeys(args.models):
        load_started = time.perf_counter()
        engine.load(model)
        load_seconds = time.perf_counter() - load_started
        for label, path, reference in tests:
            audio = decode_file(str(path))
            try:
                started = time.perf_counter()
                result = engine.transcribe(audio, language="tr", terms=TERMS)
                elapsed = time.perf_counter() - started
                record = {
                    "model": model,
                    "case": label,
                    "source": str(path.relative_to(ROOT)),
                    "reference": reference,
                    "transcript": result["text"],
                    "language": result["language"],
                    "duration_seconds": result["duration"],
                    "model_load_seconds": round(load_seconds, 3),
                    "transcribe_seconds": round(elapsed, 3),
                    "word_error_metrics": word_error_metrics(reference, result["text"]),
                    "expected_terms": TERMS if label.endswith("mixed") else [],
                    "term_hits": term_hits(result["text"]) if label.endswith("mixed") else {},
                    "network_attempts": list(NETWORK_ATTEMPTS),
                }
                results.append(record)
                print(json.dumps(record, ensure_ascii=True), flush=True)
            finally:
                audio.fill(0)
    report = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "audio_source": "Synthetic speech from locally installed Microsoft Tolga OneCore (tr) and Zira Desktop (en); no microphone or cloud synthesis",
        "mixed_clip_construction": "Alternating independently synthesized Turkish and English phrases, resampled to mono 16kHz with 0.1 second gaps",
        "recognition_settings": {"language": "tr", "terms": TERMS, "compute_type": "int8", "device": "cpu"},
        "metric_notes": "Word error rate ignores case and punctuation only. Foreign terms require exact normalized words. No accuracy threshold is asserted.",
        "limitations": "Synthetic single-voice Turkish and spliced bilingual phrases do not measure real user accuracy, accent robustness, natural code-switching or noisy microphones. Audit covers Python socket events, not OS-level network capture.",
        "network_attempts": list(NETWORK_ATTEMPTS),
        "results": results,
    }
    output = ARTIFACTS / "language-results.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Report: {output}", flush=True)
    return 1 if NETWORK_ATTEMPTS else 0


if __name__ == "__main__":
    raise SystemExit(main())
