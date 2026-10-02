from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
from pathlib import Path

from .exceptions import (
    ClipDurationError,
    OutputAlreadyExistsError,
    VideoProcessingError,
)
from .ffmpeg import FFmpegRunner
from .service import VideoService, duration_tolerance

logger = logging.getLogger(__name__)

# Synthetic sources (container, duration, fps, with audio, codec args) - no downloads.
_SELFTEST_SOURCES = [
    ("src.mp4", 12, "30", True, ["-c:v", "libx264", "-c:a", "aac"]),
    ("src.mkv", 12, "24000/1001", False, ["-c:v", "libx264"]),
    ("src.mov", 4, "25", True, ["-c:v", "libx264", "-c:a", "aac"]),
    ("src.avi", 4, "25", True, ["-c:v", "mpeg4", "-q:v", "5", "-c:a", "libmp3lame"]),
    ("src.webm", 4, "30", True, ["-c:v", "libvpx-vp9", "-deadline", "realtime", "-c:a", "libopus"]),
]


def _generate(runner: FFmpegRunner, path: Path, seconds: int, fps: str, audio: bool, codec: list[str]) -> None:
    args = ["-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=duration={seconds}:size=320x240:rate={fps}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    runner.run_ffmpeg([*args, *codec, str(path)], target=str(path))


def run_selftest(workdir: Path, runner: FFmpegRunner | None = None) -> float:
    """Exercise the engine against real FFmpeg; returns the max duration error seen."""
    runner = runner or FFmpegRunner()
    print(f"ffmpeg:  {runner.ffmpeg_path}\nffprobe: {runner.ffprobe_path}")
    service = VideoService(runner)
    max_error = 0.0

    def clip(src: Path, name: str, start: float, duration: float, **kw: bool) -> None:
        nonlocal max_error
        info = service.probe(src)
        out = service.extract_clip(src, workdir / name, start, duration, **kw)
        error = abs(out.actual_duration - duration)
        max_error = max(max_error, error)
        tol = duration_tolerance(info.fps)
        assert error <= tol, f"{name}: error {error:.4f}s > {tol:.4f}s"
        assert out.has_audio == info.has_audio, f"{name}: audio mismatch"
        print(
            f"  PASS {src.suffix:5} {info.fps:6.3f}fps audio={info.has_audio!s:5} "
            f"requested={duration:.3f}s actual={out.actual_duration:.6f}s error={error:.4f}s"
        )

    for name, seconds, fps, audio, codec in _SELFTEST_SOURCES:
        _generate(runner, workdir / name, seconds, fps, audio, codec)

    print("Exact-duration clips:")
    clip(workdir / "src.mp4", "a_5s.mp4", 2.0, 5.0)
    clip(workdir / "src.mp4", "a_odd.mp4", 1.37, 7.777)
    clip(workdir / "src.mkv", "v_5s.mp4", 2.0, 5.0)
    clip(workdir / "src.mkv", "v_odd.mp4", 3.333, 7.777)
    for name in ("src.mov", "src.avi", "src.webm"):
        clip(workdir / name, f"{Path(name).suffix[1:]}_2s.mp4", 1.0, 2.0)

    print("Rejections:")
    too_long = workdir / "too_long.mp4"
    try:
        service.extract_clip(workdir / "src.mp4", too_long, 10.0, 5.0)
        raise AssertionError("clip beyond source end was accepted")
    except ClipDurationError:
        assert not too_long.exists(), "rejected clip left an output file"
        print("  PASS clip beyond source end rejected, no output written")
    try:
        service.extract_clip(workdir / "src.mp4", workdir / "a_5s.mp4", 0.0, 1.0)
        raise AssertionError("existing output was overwritten")
    except OutputAlreadyExistsError:
        print("  PASS existing output not overwritten without overwrite=True")
    clip(workdir / "src.mp4", "a_5s.mp4", 0.0, 1.0, overwrite=True)

    leftovers = list(workdir.glob(".partial-*"))
    assert not leftovers, f"temporary files left behind: {leftovers}"
    print(f"All checks passed. Max duration error: {max_error:.4f}s")
    return max_error


def main() -> int:
    parser = argparse.ArgumentParser(description="Local FFmpeg video engine (developer CLI)")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("probe", help="print video metadata as JSON")
    p.add_argument("input")

    e = sub.add_parser("extract", help="extract an exact-duration MP4 clip")
    e.add_argument("input")
    e.add_argument("output")
    e.add_argument("--start", type=float, required=True)
    e.add_argument("--duration", type=float, required=True)
    e.add_argument("--overwrite", action="store_true")

    sub.add_parser("selftest", help="verify the engine against real FFmpeg using synthetic video")

    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")

    try:
        if args.command == "probe":
            print(json.dumps(VideoService().probe(args.input).to_dict(), indent=2))
        elif args.command == "extract":
            result = VideoService().extract_clip(args.input, args.output, args.start, args.duration, args.overwrite)
            print(json.dumps(result.to_dict(), indent=2))
        else:
            with tempfile.TemporaryDirectory() as tmp:
                run_selftest(Path(tmp))
    except (VideoProcessingError, AssertionError) as exc:
        logger.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
