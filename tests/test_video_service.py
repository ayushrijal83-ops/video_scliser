from __future__ import annotations

import math
import subprocess
from pathlib import Path

import pytest

from app.video.exceptions import (
    ClipDurationError,
    FFmpegExecutionError,
    InvalidClipRequestError,
    OutputAlreadyExistsError,
    OutputValidationError,
    UnsupportedFormatError,
)
from app.video.service import (
    DURATION_TOLERANCE_SECONDS,
    VideoService,
    build_extract_args,
    duration_tolerance,
    safe_output_path,
)
from tests.test_video_probe import ffprobe_json


class FakeRunner:
    """Stands in for FFmpegRunner: ffmpeg writes the output file, ffprobe answers per path."""

    def __init__(self, src_duration: float = 60.0, src_audio: bool = True,
                 out_duration: float | None = None, out_audio: bool | None = None,
                 ffmpeg_fails: bool = False) -> None:
        self.src_duration = src_duration
        self.src_audio = src_audio
        self.out_duration = out_duration
        self.out_audio = src_audio if out_audio is None else out_audio
        self.ffmpeg_fails = ffmpeg_fails
        self.ffmpeg_calls: list[list[str]] = []
        self.requested: float = 0.0

    def run_ffmpeg(self, args: list[str], target: str = "") -> subprocess.CompletedProcess[str]:
        self.ffmpeg_calls.append(args)
        self.requested = float(args[args.index("-t") + 1])
        Path(args[-1]).write_bytes(b"partial")
        if self.ffmpeg_fails:
            raise FFmpegExecutionError(target, "Conversion failed!", 1)
        Path(args[-1]).write_bytes(b"encoded video")
        return subprocess.CompletedProcess(args, 0, "", "")

    def run_ffprobe(self, args: list[str], target: str = "") -> subprocess.CompletedProcess[str]:
        if Path(args[-1]).name.startswith(".partial-"):
            duration = self.requested if self.out_duration is None else self.out_duration
            out = ffprobe_json(duration=str(duration), audio=self.out_audio, avg_frame_rate="30/1")
        else:
            out = ffprobe_json(duration=str(self.src_duration), audio=self.src_audio, avg_frame_rate="30/1")
        return subprocess.CompletedProcess(args, 0, out, "")


@pytest.fixture
def src(tmp_path: Path) -> Path:
    f = tmp_path / "source.mkv"
    f.write_bytes(b"source")
    return f


def service(**kw: object) -> tuple[VideoService, FakeRunner]:
    runner = FakeRunner(**kw)  # type: ignore[arg-type]
    return VideoService(runner), runner  # type: ignore[arg-type]


class TestRequestValidation:
    @pytest.mark.parametrize(
        ("start", "duration"),
        [(-1.0, 5.0), (0.0, 0.0), (0.0, -5.0), (math.nan, 5.0), (0.0, math.nan), (math.inf, 5.0), (0.0, math.inf)],
    )
    def test_invalid_numbers_rejected(self, src: Path, tmp_path: Path, start: float, duration: float) -> None:
        svc, runner = service()
        with pytest.raises(InvalidClipRequestError):
            svc.extract_clip(src, tmp_path / "out.mp4", start, duration)
        assert runner.ffmpeg_calls == []

    @pytest.mark.parametrize("start", [60.0, 75.0])
    def test_start_at_or_beyond_source_rejected(self, src: Path, tmp_path: Path, start: float) -> None:
        svc, _ = service(src_duration=60.0)
        with pytest.raises(InvalidClipRequestError, match="start"):
            svc.extract_clip(src, tmp_path / "out.mp4", start, 1.0)

    @pytest.mark.parametrize(("start", "duration"), [(0.0, 60.01), (45.0, 15.05), (59.0, 30.0)])
    def test_clip_exceeding_source_rejected_not_shortened(
        self, src: Path, tmp_path: Path, start: float, duration: float
    ) -> None:
        svc, runner = service(src_duration=60.0)
        with pytest.raises(ClipDurationError):
            svc.extract_clip(src, tmp_path / "out.mp4", start, duration)
        assert runner.ffmpeg_calls == []
        assert not (tmp_path / "out.mp4").exists()

    def test_clip_ending_exactly_at_source_end_allowed(self, src: Path, tmp_path: Path) -> None:
        svc, _ = service(src_duration=60.0)
        assert svc.extract_clip(src, tmp_path / "out.mp4", 30.0, 30.0).duration == 30.0

    def test_unsupported_input_extension(self, tmp_path: Path) -> None:
        f = tmp_path / "a.flv"
        f.write_bytes(b"x")
        svc, _ = service()
        with pytest.raises(UnsupportedFormatError):
            svc.extract_clip(f, tmp_path / "out.mp4", 0.0, 1.0)

    def test_output_must_be_mp4(self, src: Path, tmp_path: Path) -> None:
        svc, _ = service()
        with pytest.raises(InvalidClipRequestError, match="mp4"):
            svc.extract_clip(src, tmp_path / "out.mkv", 0.0, 1.0)


class TestExtraction:
    def test_success_with_audio(self, src: Path, tmp_path: Path) -> None:
        svc, runner = service()
        out = tmp_path / "out.mp4"
        result = svc.extract_clip(src, out, 12.5, 30.0)
        assert out.read_bytes() == b"encoded video"
        assert result.output_path == str(out.resolve())
        assert result.actual_duration == 30.0 and result.has_audio
        args = runner.ffmpeg_calls[0]
        assert args[args.index("-ss") + 1] == "12.500000"
        assert args[args.index("-t") + 1] == "30.000000"
        assert ["-map", "0:a:0"] == args[args.index("0:v:0") + 1: args.index("0:v:0") + 3]
        assert "-an" not in args

    def test_audio_absent_produces_silent_video_without_inventing_audio(self, src: Path, tmp_path: Path) -> None:
        svc, runner = service(src_audio=False)
        result = svc.extract_clip(src, tmp_path / "out.mp4", 0.0, 5.0)
        args = runner.ffmpeg_calls[0]
        assert "-an" in args and "anullsrc" not in " ".join(args) and "0:a:0" not in args
        assert not result.has_audio

    def test_lost_audio_fails_validation(self, src: Path, tmp_path: Path) -> None:
        svc, _ = service(out_audio=False)
        with pytest.raises(OutputValidationError, match="audio"):
            svc.extract_clip(src, tmp_path / "out.mp4", 0.0, 5.0)
        assert not (tmp_path / "out.mp4").exists()

    @pytest.mark.parametrize("actual", [29.9, 30.06, 15.0])
    def test_duration_outside_tolerance_rejected(self, src: Path, tmp_path: Path, actual: float) -> None:
        svc, _ = service(out_duration=actual)
        with pytest.raises(OutputValidationError, match="duration"):
            svc.extract_clip(src, tmp_path / "out.mp4", 0.0, 30.0)
        assert not (tmp_path / "out.mp4").exists()
        assert list(tmp_path.glob(".partial-*")) == []

    @pytest.mark.parametrize("actual", [29.96, 30.0, 30.033])
    def test_duration_within_tolerance_accepted(self, src: Path, tmp_path: Path, actual: float) -> None:
        svc, _ = service(out_duration=actual)
        assert svc.extract_clip(src, tmp_path / "out.mp4", 0.0, 30.0).actual_duration == actual

    def test_ffmpeg_failure_cleans_up_temp_and_leaves_no_output(self, src: Path, tmp_path: Path) -> None:
        svc, _ = service(ffmpeg_fails=True)
        with pytest.raises(FFmpegExecutionError):
            svc.extract_clip(src, tmp_path / "out.mp4", 0.0, 5.0)
        assert sorted(p.name for p in tmp_path.iterdir()) == ["source.mkv"]

    def test_ffmpeg_writes_to_hidden_temp_in_output_dir(self, src: Path, tmp_path: Path) -> None:
        svc, runner = service()
        svc.extract_clip(src, tmp_path / "out.mp4", 0.0, 5.0)
        written = Path(runner.ffmpeg_calls[0][-1])
        assert written.parent == tmp_path.resolve() and written.name.startswith(".partial-")
        assert not written.exists()

    def test_creates_parent_directories(self, src: Path, tmp_path: Path) -> None:
        svc, _ = service()
        out = tmp_path / "clips" / "nested" / "out.mp4"
        svc.extract_clip(src, out, 0.0, 5.0)
        assert out.is_file()


class TestOverwrite:
    def test_existing_output_refused_by_default(self, src: Path, tmp_path: Path) -> None:
        out = tmp_path / "out.mp4"
        out.write_bytes(b"keep me")
        svc, runner = service()
        with pytest.raises(OutputAlreadyExistsError):
            svc.extract_clip(src, out, 0.0, 5.0)
        assert out.read_bytes() == b"keep me" and runner.ffmpeg_calls == []

    def test_overwrite_replaces(self, src: Path, tmp_path: Path) -> None:
        out = tmp_path / "out.mp4"
        out.write_bytes(b"old")
        svc, _ = service()
        svc.extract_clip(src, out, 0.0, 5.0, overwrite=True)
        assert out.read_bytes() == b"encoded video"

    def test_failed_overwrite_keeps_previous_file(self, src: Path, tmp_path: Path) -> None:
        out = tmp_path / "out.mp4"
        out.write_bytes(b"old")
        svc, _ = service(ffmpeg_fails=True)
        with pytest.raises(FFmpegExecutionError):
            svc.extract_clip(src, out, 0.0, 5.0, overwrite=True)
        assert out.read_bytes() == b"old"


class TestHelpers:
    def test_tolerance_rule(self) -> None:
        assert duration_tolerance(30.0) == DURATION_TOLERANCE_SECONDS == 0.05
        assert duration_tolerance(10.0) == pytest.approx(0.1)  # one frame at low fps

    def test_build_args_keeps_windows_paths_as_single_arguments(self) -> None:
        src = Path(r"C:\Users\me\My Videos\talk & q&a.mkv")
        dst = Path(r"D:\out dir\clip.mp4")
        args = build_extract_args(src, dst, 1.0, 2.0, has_audio=True)
        assert args[args.index("-i") + 1] == str(src)
        assert args[-1] == str(dst)
        assert args[args.index("-c:v") + 1] == "libx264"
        assert args[args.index("-c:a") + 1] == "aac"

    def test_safe_output_path_accepts_plain_names(self, tmp_path: Path) -> None:
        assert safe_output_path(tmp_path, "clip_01.mp4") == (tmp_path / "clip_01.mp4").resolve()

    @pytest.mark.parametrize(
        "name", ["../escape.mp4", "..\\escape.mp4", "sub/clip.mp4", "C:\\Windows\\x.mp4", "/etc/x.mp4", "", "."]
    )
    def test_safe_output_path_rejects_traversal(self, tmp_path: Path, name: str) -> None:
        with pytest.raises(InvalidClipRequestError):
            safe_output_path(tmp_path, name)
