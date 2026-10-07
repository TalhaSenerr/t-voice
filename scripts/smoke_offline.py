"""Real inference smoke. Input is synthetic, non-personal test speech."""
import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from duru.engine import SpeechEngine, discover_models
from duru.recorder import decode_file

network_attempts = []
def prohibit_network(event, args):
    if event in {"socket.connect", "socket.getaddrinfo", "socket.bind"}:
        network_attempts.append(event)
        raise RuntimeError("Network forbidden during offline test")
sys.addaudithook(prohibit_network)

def main():
    root = Path(__file__).resolve().parents[1]
    audio = decode_file(str(root / ".test-artifacts" / "english.wav"))
    engine = SpeechEngine()
    results = []
    for model in ("small", "medium"):
        started = time.perf_counter()
        engine.load(model)
        loaded = time.perf_counter()
        result = engine.transcribe(audio, "en", ["Talha", "GitHub", "TypeScript"])
        ended = time.perf_counter()
        silent = engine.transcribe(np.zeros(16000 * 3, dtype=np.float32), "tr", ["GitHub"])
        record = {"model": model, "load_seconds": round(loaded-started, 2),
                  "transcribe_seconds": round(ended-loaded, 2), "result": result,
                  "silence_text": silent["text"], "network_attempts": list(network_attempts)}
        results.append(record)
        print(json.dumps(record, ensure_ascii=True), flush=True)
        assert "github" in result["text"].lower()
        assert "typescript" in result["text"].lower()
        assert silent["text"] == ""
        assert not network_attempts
    audio.fill(0)
    (root / ".test-artifacts" / "offline-results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

if __name__ == "__main__":
    main()
