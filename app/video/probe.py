from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .exceptions import InvalidVideoError, UnsupportedFormatError
from .ffmpeg import FFmpegRunner
from .models import VideoInfo

SUPPORTED_EXTENSIONS = frozenset({".mp4", ".mkv", ".mov", ".avi", ".webm"})
# ffprobe reports demuxer names, e.g. "mov,mp4,m4a,3gp,3g2,mj2" or "matroska,webm".
SUPPORTED_DEMUXERS = frozenset({"mov", "mp4", "matroska", "webm", "avi"})


def validate_input_path(input_path: str | Path) -> Path:
    """Return the resolved path of an existing file with a supported extension."""
    path = Path(input_path).resolve()
    if not path.exists():
        raise InvalidVideoError(str(path), "file does not exist")
    if not path.is_file():
        raise InvalidVideoError(str(path), "not a file")
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFormatError(str(path), path.suffix.lower() or "no extension")
    return path


def _parse_rate(rate: Any) -> float:
    try:
        num, den = str(rate).split("/")
        value = float(num) / float(den)
    except (ValueError, ZeroDivisionError):
        return 0.0
    return value if math.isfinite(value) and value > 0 else 0.0


def parse_ffprobe_output(path: str, stdout: str) -> VideoInfo:
    """Turn `ffprobe -show_format -show_streams -of json` output into VideoInfo."""
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as e:
        raise InvalidVideoError(path, f"malformed ffprobe output: {e}") from e
    if not isinstance(data, dict):
        raise InvalidVideoError(path, "malformed ffprobe output: not an object")

    fmt = data.get("format") or {}
    streams = data.get("streams") or []
    demuxers = str(fmt.get("format_name", "")).lower().split(",")
    if not SUPPORTED_DEMUXERS.intersection(demuxers):
        raise UnsupportedFormatError(path, fmt.get("format_name", "unknown"))

    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None:
        raise InvalidVideoError(path, "no video stream found")

    raw_duration = fmt.get("duration", video.get("duration"))
    try:
        duration = float(raw_duration)
        width = int(video.get("width", 0))
        height = int(video.get("height", 0))
    except (TypeError, ValueError) as e:
        raise InvalidVideoError(path, f"invalid ffprobe values: {e}") from e

    fps = _parse_rate(video.get("avg_frame_rate")) or _parse_rate(video.get("r_frame_rate"))
    try:
        return VideoInfo(
            path=path,
            format=demuxers[0],
            duration=duration,
            width=width,
            height=height,
            fps=fps,
            video_codec=str(video.get("codec_name") or ""),
            audio_codec=audio.get("codec_name") if audio else None,
            has_video=True,
            has_audio=audio is not None,
        )
    except ValueError as e:
        raise InvalidVideoError(path, str(e)) from e


def probe_video(input_path: str | Path, runner: FFmpegRunner) -> VideoInfo:
    """Probe a media file with ffprobe. Raises InvalidVideoError for corrupt files."""
    path = Path(input_path).resolve()
    if not path.is_file():
        raise InvalidVideoError(str(path), "file does not exist")
    result = runner.run_ffprobe(
        ["-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        target=str(path),
    )
    if result.returncode != 0:
        raise InvalidVideoError(str(path), f"ffprobe failed: {result.stderr.strip()[-300:]}")
    return parse_ffprobe_output(str(path), result.stdout)
