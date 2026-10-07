"""Isolated, microphone-free OpenVINO hardware/API probe; no network permitted."""
from __future__ import annotations

import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
ATTEMPTS = []
for flag in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY", "DO_NOT_TRACK"):
    os.environ[flag] = "1"


def deny_network(event, args):
    if event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo", "socket.bind"}:
        ATTEMPTS.append(event)
        raise RuntimeError("Network disabled during OpenVINO probe")


sys.addaudithook(deny_network)


def main():
    started = time.perf_counter()
    import openvino as ov
    import openvino_genai as genai
    core = ov.Core()
    devices = {}
    for device in core.available_devices:
        devices[device] = {"name": core.get_property(device, "FULL_DEVICE_NAME")}
        try:
            devices[device]["capabilities"] = core.get_property(device, "OPTIMIZATION_CAPABILITIES")
        except RuntimeError:
            pass
    packages = {dist.metadata["Name"]: dist.version for dist in importlib.metadata.distributions()}
    report = {
        "elapsed_seconds": time.perf_counter() - started,
        "devices": devices,
        "whisper_pipeline": hasattr(genai, "WhisperPipeline"),
        "pipeline_init_doc": genai.WhisperPipeline.__init__.__doc__,
        "pipeline_generate_doc": genai.WhisperPipeline.generate.__doc__,
        "packages": packages,
        "network_attempts": ATTEMPTS,
        "limitations": "Python socket auditing only, not an OS network capture.",
    }
    path = ROOT / ".test-artifacts" / "openvino-probe.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if not key.endswith("_doc")}, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()
