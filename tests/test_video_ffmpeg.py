from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from app.video.exceptions import (
    FFmpegExecutionError,
    FFmpegNotFoundError,
    FFprobeNotFoundError,
)
from app.video.ffmpeg import FFmpegRunner


def completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def test_ffmpeg_missing() -> None:
    with patch("app.video.ffmpeg.shutil.which", return_value=None), pytest.raises(FFmpegNotFoundError):
        FFmpegRunner()


def test_ffprobe_missing() -> None:
    which = {"ffmpeg": "/bin/ffmpeg", "ffprobe": None}
    with patch("app.video.ffmpeg.shutil.which", side_effect=which.get), pytest.raises(FFprobeNotFoundError):
        FFmpegRunner()


def test_explicit_paths_skip_lookup() -> None:
    with patch("app.video.ffmpeg.shutil.which") as which:
        runner = FFmpegRunner("C:\\tools\\ffmpeg.exe", "C:\\tools\\ffprobe.exe")
    which.assert_not_called()
    assert runner.ffmpeg_path == "C:\\tools\\ffmpeg.exe"


def test_uses_argument_list_without_shell() -> None:
    runner = FFmpegRunner("ffmpeg", "ffprobe", timeout=5)
    hostile = "in; rm -rf / & del C:\\*.* | $(whoami).mp4"
    with patch("app.video.ffmpeg.subprocess.run", return_value=completed()) as run:
        runner.run_ffmpeg(["-i", hostile])
    cmd = run.call_args.args[0]
    assert cmd == ["ffmpeg", "-i", hostile]  # passed through as one untouched argument
    assert run.call_args.kwargs.get("shell", False) is False
    assert run.call_args.kwargs["timeout"] == 5


def test_process_failure_raises_with_stderr_tail() -> None:
    runner = FFmpegRunner("ffmpeg", "ffprobe")
    stderr = "x" * 2000 + "Invalid data found when processing input"
    with patch("app.video.ffmpeg.subprocess.run", return_value=completed(1, stderr=stderr)), \
            pytest.raises(FFmpegExecutionError) as exc:
        runner.run_ffmpeg(["-i", "a.mp4"], target="a.mp4")
    assert exc.value.returncode == 1
    assert "Invalid data found" in str(exc.value)
    assert len(str(exc.value)) < 700


def test_ffprobe_returns_nonzero_result_to_caller() -> None:
    runner = FFmpegRunner("ffmpeg", "ffprobe")
    with patch("app.video.ffmpeg.subprocess.run", return_value=completed(1, stderr="bad")):
        assert runner.run_ffprobe(["a.mp4"]).returncode == 1


@pytest.mark.parametrize(
    "error", [subprocess.TimeoutExpired(["ffmpeg"], 1), FileNotFoundError("gone")]
)
def test_subprocess_exceptions_wrapped(error: Exception) -> None:
    runner = FFmpegRunner("ffmpeg", "ffprobe")
    with patch("app.video.ffmpeg.subprocess.run", side_effect=error), pytest.raises(FFmpegExecutionError):
        runner.run_ffmpeg(["-version"])
