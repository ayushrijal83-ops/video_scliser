"""Opt-in real end-to-end test: real faster-whisper + Ollama/Qwen + FFmpeg. Never runs by default.

    CLIPPER_REAL_E2E=1 pytest tests/test_real_e2e.py -s
    CLIPPER_REAL_E2E=1 CLIPPER_E2E_VIDEO=input/talk.mp4 pytest tests/test_real_e2e.py -s

Without CLIPPER_E2E_VIDEO a speech video is synthesized with Windows SAPI.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("CLIPPER_REAL_E2E"), reason="set CLIPPER_REAL_E2E=1 to run")


def test_real_pipeline(tmp_path: Path) -> None:
    from app.ai.client import OllamaConfig
    from benchmarks.e2e.run_real_e2e import run, synthesize_video

    video = os.environ.get("CLIPPER_E2E_VIDEO")
    if video:
        source = Path(video)
    elif sys.platform == "win32":
        source = synthesize_video(tmp_path / "speech.mp4")
    else:
        pytest.skip("set CLIPPER_E2E_VIDEO to a local speech video")
    model = OllamaConfig.from_env().model  # default qwen2.5:3b, OLLAMA_MODEL overrides
    report = run(source, 2, 10.0, "funny moments", model, "small", tmp_path / "clips")
    if not report["success"] and report.get("stage") == "selecting":
        pytest.xfail(f"model returned too few distinct moments this run: {report['error']}")
    assert report["success"], report
    assert len(report["clips"]) == 2 and all(c["ok"] for c in report["clips"])
