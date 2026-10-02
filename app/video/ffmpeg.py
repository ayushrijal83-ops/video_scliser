from __future__ import annotations

import logging
import shutil
import subprocess

from .exceptions import FFmpegExecutionError, FFmpegNotFoundError, FFprobeNotFoundError

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 600.0


class FFmpegRunner:
    """Safe FFmpeg/FFprobe execution wrapper.

    Every invocation is an argument list passed straight to subprocess.run
    (never shell=True), so paths and values are never interpreted by a shell.
    """

    def __init__(
        self,
        ffmpeg_path: str | None = None,
        ffprobe_path: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        ffmpeg = ffmpeg_path or shutil.which("ffmpeg")
        if not ffmpeg:
            raise FFmpegNotFoundError()
        ffprobe = ffprobe_path or shutil.which("ffprobe")
        if not ffprobe:
            raise FFprobeNotFoundError()
        self.ffmpeg_path: str = ffmpeg
        self.ffprobe_path: str = ffprobe
        self.timeout = timeout

    def run_ffmpeg(self, args: list[str], target: str = "") -> subprocess.CompletedProcess[str]:
        """Run FFmpeg; raises FFmpegExecutionError on failure or timeout."""
        result = self._run(self.ffmpeg_path, args, target)
        if result.returncode != 0:
            raise FFmpegExecutionError(target, result.stderr, result.returncode)
        return result

    def run_ffprobe(self, args: list[str], target: str = "") -> subprocess.CompletedProcess[str]:
        """Run FFprobe and return the result without checking the exit code."""
        return self._run(self.ffprobe_path, args, target)

    def _run(self, exe: str, args: list[str], target: str) -> subprocess.CompletedProcess[str]:
        cmd = [exe, *args]
        logger.debug("Running: %s", cmd)
        try:
            return subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise FFmpegExecutionError(target, f"timed out after {self.timeout}s", -1) from e
        except OSError as e:
            raise FFmpegExecutionError(target, str(e), -1) from e
