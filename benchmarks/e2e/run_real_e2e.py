"""M07 real end-to-end check: video -> faster-whisper -> Ollama/Qwen -> selection -> FFmpeg -> verified clips.

Everything runs locally. Requires FFmpeg on PATH, Ollama running with the model pulled, and the
faster-whisper model (downloaded once on first use).

    python -m benchmarks.e2e.run_real_e2e --synthesize            # Windows: make a speech test video first
    python -m benchmarks.e2e.run_real_e2e --video input/talk.mp4 -n 3 -d 10 -i "funny moments"
    python -m benchmarks.e2e.run_real_e2e --synthesize --model qwen2.5:3b

Outputs go to output/e2e/<timestamp>/ (gitignored); delete that folder to clean up.
Exit code 0 = success (exactly N clips, each within the M04 duration tolerance, audio kept).
"""

from __future__ import annotations

import argparse
import itertools
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from app.ai.client import OllamaConfig
from app.ai.service import AIReasoningConfig, AIReasoningService
from app.clipping import (
    ClipGenerationError,
    ClipGenerationService,
    ClipJobRequest,
    JobStatus,
)
from app.transcription import TranscriptionService
from app.video import VideoService, duration_tolerance

OUT_ROOT = Path("output/e2e")
DATASET = Path(__file__).resolve().parents[1] / "ai" / "dataset.json"


def synthesize_video(target: Path) -> Path:
    """Speak the benchmark transcript with Windows SAPI and mux it over an FFmpeg test pattern."""
    if sys.platform != "win32":
        raise SystemExit("--synthesize uses Windows SAPI; on other systems pass --video with any speech video")
    target.parent.mkdir(parents=True, exist_ok=True)
    text = " ".join(s["text"] for s in json.loads(DATASET.read_text(encoding="utf-8"))["segments"])
    with tempfile.TemporaryDirectory() as tmp:
        text_file, wav = Path(tmp) / "script.txt", Path(tmp) / "speech.wav"
        text_file.write_text(text, encoding="utf-8")
        script = (
            "Add-Type -AssemblyName System.Speech;"
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            "$s.SetOutputToWaveFile($env:E2E_WAV);"
            "$s.Speak([IO.File]::ReadAllText($env:E2E_TEXT));$s.Dispose()"
        )
        env = {**os.environ, "E2E_WAV": str(wav), "E2E_TEXT": str(text_file)}
        subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True, env=env)
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30", "-i", str(wav),
             "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(target)],
            check=True,
        )
    return target


def run(video: Path, count: int, duration: float, instruction: str, model: str, whisper_model: str,
        out_dir: Path) -> dict[str, Any]:
    marks: list[tuple[str, float]] = []

    def on_status(status: JobStatus, detail: str) -> None:
        marks.append((status.value, time.perf_counter()))
        print(f"[{time.strftime('%H:%M:%S')}] {status.value:<18} {detail}", flush=True)

    ai_config = AIReasoningConfig.from_env()
    ai_config.ollama_config = OllamaConfig(host=ai_config.ollama_config.host, model=model,
                                           timeout=ai_config.ollama_config.timeout)
    svc = ClipGenerationService(
        transcriber=TranscriptionService(model_name=whisper_model),
        analyzer=AIReasoningService(ai_config),
        on_status=on_status,
    )
    started = time.perf_counter()
    report: dict[str, Any] = {"video": str(video), "count": count, "duration": duration, "instruction": instruction,
                              "model": model, "whisper_model": whisper_model, "output_dir": str(out_dir)}
    try:
        result = svc.generate(ClipJobRequest(str(video), str(out_dir), count, duration, instruction))
    except ClipGenerationError as e:
        report.update(success=False, stage=e.stage.value, error=str(e))
    else:
        probe = VideoService()
        tol = duration_tolerance(probe.probe(video).fps)
        clips = []
        for c in result.clips:
            info = probe.probe(c.path)
            clips.append({"index": c.index, "start": c.start, "end": c.end, "score": c.score, "reason": c.reason,
                          "probed_duration": info.duration, "audio": info.audio_codec, "video": info.video_codec,
                          "ok": abs(info.duration - duration) <= tol and info.has_audio})
        report.update(success=len(clips) == count and all(c["ok"] for c in clips), clips=clips,
                      candidates_returned=result.candidates_returned, candidates_valid=result.candidates_valid)
    report["total_seconds"] = time.perf_counter() - started
    # Stage time = time until the next status callback.
    report["stage_seconds"] = {a[0]: round(b[1] - a[1], 2) for a, b in itertools.pairwise(marks)}
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--video", type=Path, help="speech video (.mp4 .mkv .mov .avi .webm)")
    parser.add_argument("--synthesize", action="store_true", help="create output/e2e/speech_meeting.mp4 (Windows)")
    parser.add_argument("-n", "--count", type=int, default=3)
    parser.add_argument("-d", "--duration", type=float, default=10.0)
    parser.add_argument("-i", "--instruction", default="funny moments")
    parser.add_argument("--model", default=OllamaConfig.from_env().model)
    parser.add_argument("--whisper-model", default="small")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    if not shutil.which("ffmpeg"):
        raise SystemExit("FFmpeg not found on PATH")

    video = args.video
    if args.synthesize:
        video = OUT_ROOT / "speech_meeting.mp4"
        if not video.exists():
            synthesize_video(video)
    if video is None:
        parser.error("pass --video or --synthesize")

    out_dir = OUT_ROOT / time.strftime("%Y%m%d-%H%M%S")
    report = run(video, args.count, args.duration, args.instruction, args.model, args.whisper_model, out_dir / "clips")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "clips"}, indent=2))
    for c in report.get("clips", []):
        print(f"clip {c['index']}: {c['start']:.2f}-{c['end']:.2f}s probed {c['probed_duration']:.3f}s "
              f"audio={c['audio']} score={c['score']} ok={c['ok']} | {c['reason']}")
    print(f"{'SUCCESS' if report['success'] else 'FAILED'} - report: {out_dir / 'report.json'}")
    return 0 if report["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
