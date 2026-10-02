from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.video.exceptions import InvalidVideoError, UnsupportedFormatError
from app.video.ffmpeg import FFmpegRunner
from app.video.probe import parse_ffprobe_output, probe_video, validate_input_path


def ffprobe_json(
    duration: Any = "10.000000",
    audio: bool = True,
    format_name: str = "mov,mp4,m4a,3gp,3g2,mj2",
    **video: Any,
) -> str:
    v = {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080,
         "avg_frame_rate": "30000/1001", "r_frame_rate": "30000/1001", **video}
    streams = [v]
    if audio:
        streams.append({"codec_type": "audio", "codec_name": "aac"})
    return json.dumps({"streams": streams, "format": {"format_name": format_name, "duration": duration}})


class TestParse:
    def test_video_with_audio(self) -> None:
        info = parse_ffprobe_output("a.mp4", ffprobe_json())
        assert (info.width, info.height, info.duration) == (1920, 1080, 10.0)
        assert info.fps == pytest.approx(29.97, abs=0.01)
        assert info.format == "mov"
        assert info.has_audio and info.audio_codec == "aac"

    def test_audio_stream_after_other_streams_is_found(self) -> None:
        data = json.loads(ffprobe_json(audio=False))
        data["streams"] += [{"codec_type": "subtitle"}, {"codec_type": "audio", "codec_name": "opus"}]
        assert parse_ffprobe_output("a.mkv", json.dumps(data)).audio_codec == "opus"

    def test_video_without_audio(self) -> None:
        info = parse_ffprobe_output("a.mp4", ffprobe_json(audio=False))
        assert not info.has_audio and info.audio_codec is None

    @pytest.mark.parametrize("format_name", ["matroska,webm", "avi", "mov,mp4,m4a,3gp,3g2,mj2"])
    def test_supported_containers(self, format_name: str) -> None:
        assert parse_ffprobe_output("a", ffprobe_json(format_name=format_name)).has_video

    def test_unsupported_container(self) -> None:
        with pytest.raises(UnsupportedFormatError):
            parse_ffprobe_output("a.flv", ffprobe_json(format_name="flv"))

    def test_fps_falls_back_to_r_frame_rate(self) -> None:
        info = parse_ffprobe_output("a", ffprobe_json(avg_frame_rate="0/0", r_frame_rate="25/1"))
        assert info.fps == 25.0

    @pytest.mark.parametrize("stdout", ["", "not json", "[]", "{"])
    def test_malformed_output(self, stdout: str) -> None:
        with pytest.raises(InvalidVideoError, match="malformed"):
            parse_ffprobe_output("a.mp4", stdout)

    def test_no_video_stream(self) -> None:
        data = {"streams": [{"codec_type": "audio", "codec_name": "aac"}],
                "format": {"format_name": "mov", "duration": "5"}}
        with pytest.raises(InvalidVideoError, match="no video stream"):
            parse_ffprobe_output("a.mp4", json.dumps(data))

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"duration": "N/A"},
            {"duration": "0"},
            {"duration": "-3"},
            {"duration": "nan"},
            {"duration": "inf"},
            {"duration": None},
            {"width": 0},
            {"height": "abc"},
            {"avg_frame_rate": "0/0", "r_frame_rate": "0/0"},
        ],
    )
    def test_invalid_values(self, kwargs: dict[str, Any]) -> None:
        with pytest.raises(InvalidVideoError):
            parse_ffprobe_output("a.mp4", ffprobe_json(**kwargs))


class TestValidateInputPath:
    @pytest.mark.parametrize("suffix", [".mp4", ".MKV", ".mov", ".avi", ".webm"])
    def test_supported_extensions(self, tmp_path: Path, suffix: str) -> None:
        f = tmp_path / f"clip{suffix}"
        f.write_bytes(b"x")
        assert validate_input_path(str(f)) == f.resolve()

    @pytest.mark.parametrize("name", ["clip.txt", "clip.flv", "clip"])
    def test_unsupported_extensions(self, tmp_path: Path, name: str) -> None:
        f = tmp_path / name
        f.write_bytes(b"x")
        with pytest.raises(UnsupportedFormatError):
            validate_input_path(f)

    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(InvalidVideoError, match="does not exist"):
            validate_input_path(tmp_path / "nope.mp4")

    def test_directory(self, tmp_path: Path) -> None:
        d = tmp_path / "dir.mp4"
        d.mkdir()
        with pytest.raises(InvalidVideoError, match="not a file"):
            validate_input_path(d)

    def test_windows_path_with_spaces_and_unicode(self, tmp_path: Path) -> None:
        f = tmp_path / "My Videos" / "clip é (1).mp4"
        f.parent.mkdir()
        f.write_bytes(b"x")
        assert validate_input_path(str(f)) == f.resolve()


class TestProbeVideo:
    def test_runs_ffprobe_with_path_as_single_argument(self, tmp_path: Path) -> None:
        f = tmp_path / "a b.mp4"
        f.write_bytes(b"x")
        runner = MagicMock(spec=FFmpegRunner)
        runner.run_ffprobe.return_value = subprocess.CompletedProcess([], 0, ffprobe_json(), "")
        info = probe_video(f, runner)
        args = runner.run_ffprobe.call_args.args[0]
        assert args[-1] == str(f.resolve())
        assert info.path == str(f.resolve())

    def test_corrupt_file(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.mp4"
        f.write_bytes(b"garbage")
        runner = MagicMock(spec=FFmpegRunner)
        runner.run_ffprobe.return_value = subprocess.CompletedProcess(
            [], 1, "", "moov atom not found\nInvalid data found when processing input"
        )
        with pytest.raises(InvalidVideoError, match="Invalid data found"):
            probe_video(f, runner)
