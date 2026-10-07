"""Offline integration checks on synthetic fixtures; never opens the microphone."""
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
attempts = []

def audit(event, args):
    if event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo", "socket.bind"}:
        attempts.append(event)
        raise RuntimeError("Network forbidden during local verification")

sys.addaudithook(audit)
import numpy as np
from duru.engine import SpeechEngine
from duru.recorder import decode_file

def main():
    engine = SpeechEngine()
    started = time.perf_counter()
    engine.load("turbo-ov")
    report = {"model": "turbo-ov", "load_seconds": time.perf_counter() - started,
              "synthetic_audio_only": True, "microphone_opened": False,
              "network_attempts": attempts, "cases": [],
              "limitations": "Synthetic examples do not measure personal speech accuracy. Network audit covers Python sockets, not native or OS traffic."}
    try:
        for name, language, repeat in [("turkish", "tr", 1), ("turkish-english-mixed", "tr", 1),
                                       ("english", "auto", 1), ("turkish-english-mixed", "tr", 3)]:
            source = decode_file(str(ROOT / ".test-artifacts" / (name + ".wav")))
            audio = np.tile(source, repeat)
            source.fill(0)
            try:
                started = time.perf_counter()
                result = engine.transcribe(audio, language, [])
                elapsed = time.perf_counter() - started
                record = {"case": name, "repeat": repeat, "seconds": elapsed, **result}
                if name != "turkish":
                    hits = {term: result["text"].casefold().count(term) for term in ("github", "pull request", "typescript")}
                    record["exact_term_counts"] = hits
                    if repeat == 1:
                        assert all(count >= 1 for count in hits.values()), record
                    else:
                        # Long-form check verifies all utterances survive the
                        # 30-second boundary. Report spelling errors honestly;
                        # ASR can render the compound as "type script".
                        variants = hits["typescript"] + result["text"].casefold().count("type script")
                        record["typescript_including_split_spelling"] = variants
                        assert hits["github"] >= repeat and hits["pull request"] >= repeat and variants >= repeat, record
                report["cases"].append(record)
            finally:
                audio.fill(0)
        silent = np.zeros(16000 * 3, dtype=np.float32)
        assert engine.transcribe(silent, "tr", ["GitHub", "TypeScript"])["text"] == ""
        assert not attempts
        report["silence_with_hints_empty"] = True
        report["telemetry_import_blocked"] = sys.modules.get("openvino_telemetry", "absent") is None
        report["ok"] = True
    except Exception as exc:
        report["ok"] = False
        report["error"] = str(exc)
        raise
    finally:
        (ROOT / ".test-artifacts" / "openvino-production-pipeline.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True), flush=True)

if __name__ == "__main__":
    main()
