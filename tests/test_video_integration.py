"""Real FFmpeg check; skipped when ffmpeg/ffprobe are not on PATH.

Manual equivalent: python -m app.video selftest
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.video.cli import run_selftest

pytestmark = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="FFmpeg not installed"
)


def test_selftest_with_real_ffmpeg(tmp_path: Path) -> None:
    assert run_selftest(tmp_path) <= 0.05
