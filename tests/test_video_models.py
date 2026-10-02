from __future__ import annotations

import math

import pytest

from app.video.models import ClipRequest, ProcessedVideo, VideoInfo


def make_info(**overrides: object) -> VideoInfo:
    data: dict[str, object] = {
        "path": "a.mp4", "format": "mov", "duration": 10.0, "width": 640, "height": 360,
        "fps": 30.0, "video_codec": "h264", "audio_codec": "aac", "has_video": True, "has_audio": True,
    }
    data.update(overrides)
    return VideoInfo(**data)  # type: ignore[arg-type]


class TestVideoInfo:
    def test_valid_and_round_trip(self) -> None:
        info = make_info()
        assert VideoInfo.from_dict(info.to_dict()) == info

    def test_audio_absent_is_valid(self) -> None:
        info = make_info(audio_codec=None, has_audio=False)
        assert not info.has_audio

    @pytest.mark.parametrize("duration", [0.0, -1.0, math.nan, math.inf])
    def test_rejects_bad_duration(self, duration: float) -> None:
        with pytest.raises(ValueError):
            make_info(duration=duration)

    @pytest.mark.parametrize("field", ["width", "height"])
    def test_rejects_zero_dimension_with_video(self, field: str) -> None:
        with pytest.raises(ValueError, match="width/height"):
            make_info(**{field: 0})

    @pytest.mark.parametrize("fps", [0.0, math.nan, math.inf])
    def test_rejects_bad_fps(self, fps: float) -> None:
        with pytest.raises(ValueError):
            make_info(fps=fps)

    def test_rejects_audio_flag_without_codec(self) -> None:
        with pytest.raises(ValueError, match="audio_codec"):
            make_info(audio_codec=None, has_audio=True)

    def test_is_frozen(self) -> None:
        with pytest.raises(AttributeError):
            make_info().duration = 5.0  # type: ignore[misc]


class TestClipRequest:
    def test_valid(self) -> None:
        req = ClipRequest("in.mp4", "out.mp4", 1.5, 30.0)
        assert req.end == 31.5
        assert ClipRequest.from_dict(req.to_dict()) == req

    def test_zero_start_allowed(self) -> None:
        assert ClipRequest("in.mp4", "out.mp4", 0.0, 1.0).start == 0.0

    @pytest.mark.parametrize("start", [-0.001, math.nan, math.inf, -math.inf])
    def test_rejects_bad_start(self, start: float) -> None:
        with pytest.raises(ValueError, match="start"):
            ClipRequest("in.mp4", "out.mp4", start, 1.0)

    @pytest.mark.parametrize("duration", [0.0, -1.0, math.nan, math.inf])
    def test_rejects_bad_duration(self, duration: float) -> None:
        with pytest.raises(ValueError, match="duration"):
            ClipRequest("in.mp4", "out.mp4", 0.0, duration)

    @pytest.mark.parametrize("value", ["5", None, True])
    def test_rejects_non_numbers(self, value: object) -> None:
        with pytest.raises(ValueError, match="number"):
            ClipRequest("in.mp4", "out.mp4", value, 1.0)  # type: ignore[arg-type]

    def test_rejects_empty_paths(self) -> None:
        with pytest.raises(ValueError):
            ClipRequest("", "out.mp4", 0.0, 1.0)
        with pytest.raises(ValueError):
            ClipRequest("in.mp4", "", 0.0, 1.0)


class TestProcessedVideo:
    def test_valid(self) -> None:
        pv = ProcessedVideo("in.mp4", "out.mp4", 0.0, 5.0, 5.0, 640, 360, 30.0, "h264", None, 100)
        assert not pv.has_audio
        assert ProcessedVideo.from_dict(pv.to_dict()) == pv

    def test_rejects_empty_file(self) -> None:
        with pytest.raises(ValueError, match="file_size"):
            ProcessedVideo("in.mp4", "out.mp4", 0.0, 5.0, 5.0, 640, 360, 30.0, "h264", None, 0)
