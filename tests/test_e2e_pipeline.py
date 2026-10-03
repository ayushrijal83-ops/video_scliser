"""M07 deterministic end-to-end regression tests.

Real: FFmpeg/FFprobe (M04), M05 orchestration and selection, M03 prompt/parse/validation, M06 Flask app.
Fake: only the two model runtimes - the Whisper transcriber and the Ollama daemon (a canned JSON reply).
Skipped automatically when FFmpeg is not on PATH. Real Whisper/Ollama runs live in test_real_e2e.py.
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from app.ai.client import OllamaClient, OllamaConfig
from app.ai.exceptions import OllamaUnavailableError
from app.ai.service import AIReasoningConfig, AIReasoningService
from app.clipping import (
    AnalysisStageError,
    ClipGenerationService,
    ClipJobRequest,
    ClipRenderError,
    InsufficientCandidatesError,
    InvalidJobRequestError,
    JobStatus,
    OutputVerificationError,
    SourceTooShortError,
    TranscriptionStageError,
)
from app.transcription.exceptions import TranscriptionFailedError
from app.transcription.models import TranscriptionResult, TranscriptSegment
from app.ui import UIConfig, create_app
from app.video import FFmpegExecutionError, VideoService, duration_tolerance
from app.video.models import ProcessedVideo

pytestmark = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="FFmpeg not installed"
)

SECONDS = 20


def _make_video(path: Path, audio: bool) -> Path:
    args = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=duration={SECONDS}:size=320x240:rate=30"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={SECONDS}", "-c:a", "aac"]
    args += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-shortest", str(path)]
    subprocess.run(args, check=True, capture_output=True)
    return path


@pytest.fixture(scope="module")
def media(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    d = tmp_path_factory.mktemp("media")
    return {"av": _make_video(d / "talk.mp4", True), "video_only": _make_video(d / "silent.mp4", False)}


@pytest.fixture(scope="module")
def video() -> VideoService:
    return VideoService()


class FakeTranscriber:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    def transcribe(self, input_path: str, language: str | None = None) -> TranscriptionResult:
        self.calls += 1
        if self.error:
            raise self.error
        segs = [TranscriptSegment(float(s), float(s + 2), f"sentence {s}") for s in range(0, SECONDS, 2)]
        return TranscriptionResult(input_path, "en", 1.0, float(SECONDS), segs, "small")


class FakeOllama(OllamaClient):
    """The Ollama daemon replaced by a canned reply; everything after it is the real M03 code."""

    def __init__(self, reply: str | dict[str, Any] = "", available: bool = True) -> None:
        super().__init__(OllamaConfig(model="qwen2.5:0.5b"))
        self.reply = reply if isinstance(reply, str) else json.dumps(reply)
        self.available = available
        self.prompts: list[str] = []

    def is_available(self) -> bool:
        return self.available

    def is_model_available(self, model: str | None = None) -> bool:
        return True

    def generate(self, prompt: str, model: str | None = None, options: dict | None = None,
                 stream: bool = False, format: str = "") -> str:
        self.prompts.append(prompt)
        return self.reply


def reply(*cands: tuple[float, float, float]) -> dict[str, Any]:
    return {"candidates": [{"start": s, "end": e, "score": sc, "reason": f"moment at {s}"} for s, e, sc in cands]}


def service(video: VideoService, ai_reply: str | dict[str, Any], transcriber: FakeTranscriber | None = None,
            ollama: FakeOllama | None = None, statuses: list[JobStatus] | None = None) -> ClipGenerationService:
    analyzer = AIReasoningService(AIReasoningConfig(OllamaConfig()), client=ollama or FakeOllama(ai_reply))
    return ClipGenerationService(
        transcriber=transcriber or FakeTranscriber(), analyzer=analyzer, video=video,
        on_status=(lambda s, _d: statuses.append(s)) if statuses is not None else None,
    )


def req(src: Path, out: Path, count: int, duration: float, instruction: str = "funny moments") -> ClipJobRequest:
    return ClipJobRequest(str(src), str(out), count, duration, instruction)


def files(path: Path) -> list[str]:
    return sorted(p.name for p in path.iterdir()) if path.exists() else []


# --- 1/2/3: valid request, durations, audio ----------------------------------------------


def test_valid_request_real_ffmpeg(media: dict[str, Path], video: VideoService, tmp_path: Path) -> None:
    statuses: list[JobStatus] = []
    out = tmp_path / "job"
    result = service(video, reply((2, 4, 0.9), (9, 11, 0.8), (15, 17, 0.7)), statuses=statuses).generate(
        req(media["av"], out, 3, 4.0)
    )
    assert result.status is JobStatus.COMPLETED and len(result.clips) == 3
    assert files(out) == ["clip_001.mp4", "clip_002.mp4", "clip_003.mp4"]
    source = video.probe(media["av"])
    for clip in result.clips:
        info = video.probe(clip.path)  # independent re-probe of the real file
        assert abs(info.duration - 4.0) <= duration_tolerance(source.fps)
        assert info.has_video and info.video_codec == "h264"
        assert info.has_audio and info.audio_codec == "aac"
        assert clip.end - clip.start == pytest.approx(4.0)
    assert statuses == [JobStatus.VALIDATING, JobStatus.TRANSCRIBING, JobStatus.ANALYZING, JobStatus.SELECTING,
                        JobStatus.GENERATING, JobStatus.VALIDATING_OUTPUTS, JobStatus.COMPLETED]


def test_video_only_source_rejected_by_m05(media: dict[str, Path], video: VideoService, tmp_path: Path) -> None:
    transcriber = FakeTranscriber()
    with pytest.raises(InvalidJobRequestError, match="no audio"):
        service(video, reply((2, 4, 0.9)), transcriber).generate(req(media["video_only"], tmp_path / "job", 1, 4.0))
    assert transcriber.calls == 0 and not (tmp_path / "job").exists()


def test_video_only_extraction_gets_no_invented_audio(media: dict[str, Path], video: VideoService,
                                                      tmp_path: Path) -> None:
    out = video.extract_clip(media["video_only"], tmp_path / "c.mp4", 3.0, 4.0)
    assert out.audio_codec is None and not video.probe(out.output_path).has_audio


# --- 4: source boundaries -----------------------------------------------------------------


def test_candidate_near_beginning_shifts_forward(media: dict[str, Path], video: VideoService, tmp_path: Path) -> None:
    (clip,) = service(video, reply((0.0, 1.0, 0.9))).generate(req(media["av"], tmp_path / "j", 1, 6.0)).clips
    assert (clip.start, clip.end) == (0.0, 6.0)
    assert abs(video.probe(clip.path).duration - 6.0) <= 0.05


def test_candidate_near_end_shifts_backward(media: dict[str, Path], video: VideoService, tmp_path: Path) -> None:
    src = video.probe(media["av"]).duration
    (clip,) = service(video, reply((19.0, 20.0, 0.9))).generate(req(media["av"], tmp_path / "j", 1, 6.0)).clips
    assert clip.end == pytest.approx(src, abs=1e-3) and clip.end - clip.start == pytest.approx(6.0)
    assert abs(video.probe(clip.path).duration - 6.0) <= 0.05


def test_exact_source_length_request(media: dict[str, Path], video: VideoService, tmp_path: Path) -> None:
    src = video.probe(media["av"]).duration
    (clip,) = service(video, reply((5, 10, 0.9))).generate(req(media["av"], tmp_path / "j", 1, src)).clips
    assert clip.start == 0.0
    assert abs(video.probe(clip.path).duration - src) <= 0.05


def test_request_just_below_source_duration(media: dict[str, Path], video: VideoService, tmp_path: Path) -> None:
    d = round(video.probe(media["av"]).duration - 0.5, 3)
    (clip,) = service(video, reply((8, 12, 0.9))).generate(req(media["av"], tmp_path / "j", 1, d)).clips
    assert abs(video.probe(clip.path).duration - d) <= 0.05


def test_source_shorter_than_request(media: dict[str, Path], video: VideoService, tmp_path: Path) -> None:
    transcriber = FakeTranscriber()
    with pytest.raises(SourceTooShortError):
        service(video, reply((1, 2, 0.9)), transcriber).generate(req(media["av"], tmp_path / "j", 1, SECONDS + 1.0))
    assert transcriber.calls == 0 and not (tmp_path / "j").exists()


# --- 5: selection through the real M03 parser -----------------------------------------------


def test_ranking_follows_ai_scores(media: dict[str, Path], video: VideoService, tmp_path: Path) -> None:
    result = service(video, reply((15, 17, 0.5), (2, 4, 0.95), (9, 11, 0.7))).generate(
        req(media["av"], tmp_path / "j", 3, 2.0)
    )
    assert [c.start for c in result.clips] == [2.0, 9.0, 15.0]
    assert [c.score for c in result.clips] == [0.95, 0.7, 0.5]


def test_overlapping_and_duplicate_candidates_collapse(media: dict[str, Path], video: VideoService,
                                                       tmp_path: Path) -> None:
    ai = reply((5, 7, 0.9), (5, 7, 0.85), (5.5, 7.5, 0.8), (14, 16, 0.6))
    result = service(video, ai).generate(req(media["av"], tmp_path / "j", 2, 4.0))
    assert [c.start for c in result.clips] == [4.0, 13.0]  # exact windows: centre +- 2 s


def test_insufficient_candidates_renders_nothing(media: dict[str, Path], video: VideoService, tmp_path: Path) -> None:
    with pytest.raises(InsufficientCandidatesError) as e:
        service(video, reply((5, 7, 0.9), (5.2, 7.2, 0.8))).generate(req(media["av"], tmp_path / "j", 2, 4.0))
    assert (e.value.found, e.value.requested) == (1, 2)
    assert not (tmp_path / "j").exists()


def test_ai_timestamps_past_source_are_dropped(media: dict[str, Path], video: VideoService, tmp_path: Path) -> None:
    ai = reply((30, 35, 0.99), (-1, 3, 0.98), (8, 6, 0.97), (10, 12, 0.5))
    (clip,) = service(video, ai).generate(req(media["av"], tmp_path / "j", 1, 2.0)).clips
    assert clip.start == 10.0


# --- 6: failure behavior ---------------------------------------------------------------------


def test_transcription_failure(media: dict[str, Path], video: VideoService, tmp_path: Path) -> None:
    t = FakeTranscriber(TranscriptionFailedError("whisper crashed"))
    with pytest.raises(TranscriptionStageError):
        service(video, reply((2, 4, 0.9)), t).generate(req(media["av"], tmp_path / "j", 1, 2.0))
    assert not (tmp_path / "j").exists()


def test_ai_unavailable(media: dict[str, Path], video: VideoService, tmp_path: Path) -> None:
    with pytest.raises(AnalysisStageError) as e:
        service(video, "", ollama=FakeOllama(available=False)).generate(req(media["av"], tmp_path / "j", 1, 2.0))
    assert isinstance(e.value.__cause__, OllamaUnavailableError)


@pytest.mark.parametrize("bad", ["not json at all", "[1, 2, 3]", '{"candidates": "none"}', '{"candidates": [7]}'])
def test_invalid_ai_output_is_a_clean_stage_error(media: dict[str, Path], video: VideoService, tmp_path: Path,
                                                  bad: str) -> None:
    """Wrong-shape JSON used to escape M05 as a bare TypeError (fixed in M07)."""
    with pytest.raises(AnalysisStageError):
        service(video, bad).generate(req(media["av"], tmp_path / "j", 1, 2.0))
    assert not (tmp_path / "j").exists()


class FlakyVideo(VideoService):
    """Real M04, except that clip `fail_at` fails or is misreported."""

    def __init__(self, fail_at: int, mode: str) -> None:
        super().__init__()
        self.fail_at, self.mode, self.calls = fail_at, mode, 0

    def extract_clip(self, input_path: str | Path, output_path: str | Path, start: float, duration: float,
                     overwrite: bool = False) -> ProcessedVideo:
        self.calls += 1
        if self.calls == self.fail_at and self.mode == "ffmpeg":
            raise FFmpegExecutionError(str(input_path), "Conversion failed!", 1)
        out = super().extract_clip(input_path, output_path, start, duration, overwrite)
        if self.calls == self.fail_at and self.mode == "duration":
            return ProcessedVideo(**{**out.__dict__, "actual_duration": duration + 1.0})
        return out


@pytest.mark.parametrize(("mode", "error"), [("ffmpeg", ClipRenderError), ("duration", OutputVerificationError)])
def test_late_failure_removes_partial_output_keeps_user_files(media: dict[str, Path], tmp_path: Path, mode: str,
                                                              error: type[Exception]) -> None:
    out = tmp_path / "job"
    out.mkdir()
    (out / "notes.txt").write_text("mine")
    svc = service(FlakyVideo(2, mode), reply((2, 4, 0.9), (9, 11, 0.8), (15, 17, 0.7)))
    with pytest.raises(error):
        svc.generate(req(media["av"], out, 3, 2.0))
    assert files(out) == ["notes.txt"]  # clip_001 (really rendered) removed, user file untouched


# --- 7: cleanup / pre-existing files ------------------------------------------------------------


def test_success_keeps_outputs_and_existing_files(media: dict[str, Path], video: VideoService, tmp_path: Path) -> None:
    out = tmp_path / "job"
    out.mkdir()
    (out / "keep.mp4").write_bytes(b"user")
    service(video, reply((2, 4, 0.9), (12, 14, 0.8))).generate(req(media["av"], out, 2, 2.0))
    assert files(out) == ["clip_001.mp4", "clip_002.mp4", "keep.mp4"]
    assert (out / "keep.mp4").read_bytes() == b"user"
    assert not [p for p in out.iterdir() if p.name.startswith(".partial")]


def test_existing_clip_name_is_never_overwritten(media: dict[str, Path], video: VideoService, tmp_path: Path) -> None:
    out = tmp_path / "job"
    out.mkdir()
    (out / "clip_001.mp4").write_bytes(b"old")
    t = FakeTranscriber()
    with pytest.raises(InvalidJobRequestError):
        service(video, reply((2, 4, 0.9)), t).generate(req(media["av"], out, 1, 2.0))
    assert (out / "clip_001.mp4").read_bytes() == b"old" and t.calls == 0


# --- 8: M06 UI over the real M05 + M04 ------------------------------------------------------------


def test_ui_runs_real_pipeline_and_downloads_exact_clips(media: dict[str, Path], tmp_path: Path) -> None:
    ollama = FakeOllama(reply((2, 4, 0.9), (12, 14, 0.8)))

    def factory(on_status: Any) -> ClipGenerationService:
        analyzer = AIReasoningService(AIReasoningConfig(OllamaConfig()), client=ollama)
        return ClipGenerationService(transcriber=FakeTranscriber(), analyzer=analyzer, on_status=on_status)

    cfg = UIConfig(upload_dir=tmp_path / "up", output_dir=tmp_path / "out")
    client = create_app(cfg, service_factory=factory).test_client()  # real M04 probe on upload
    data = {"video": (io.BytesIO(media["av"].read_bytes()), "My Talk.mp4"), "clip_count": "2",
            "clip_duration": "3", "instruction": "funny moments"}
    r = client.post("/jobs", data=data, content_type="multipart/form-data")
    assert r.status_code == 303
    job_id = r.headers["Location"].rsplit("/", 1)[-1]
    job = client.application.extensions["clipper"].jobs.get(job_id)
    job.thread.join(60)
    assert job.status is JobStatus.COMPLETED, job.error
    assert "INSTRUCTION: funny moments" in ollama.prompts[0]  # the form reached M03 through M05 only

    html = client.get(f"/jobs/{job_id}").get_data(as_text=True)
    assert "2 clips ready" in html and str(tmp_path) not in html
    for name in ("clip_001.mp4", "clip_002.mp4"):
        resp = client.get(f"/jobs/{job_id}/clips/{name}")
        assert resp.status_code == 200
        saved = tmp_path / f"dl_{name}"
        saved.write_bytes(resp.data)
        resp.close()
        info = VideoService().probe(saved)
        assert abs(info.duration - 3.0) <= 0.05 and info.has_audio
    for bad in ("..%2F..%2Fup", "clip_003.mp4", "..%5Cclip_001.mp4"):
        assert client.get(f"/jobs/{job_id}/clips/{bad}").status_code == 404
    assert files(cfg.upload_dir) == []


def test_ui_rejects_non_video_with_real_probe(tmp_path: Path) -> None:
    cfg = UIConfig(upload_dir=tmp_path / "up", output_dir=tmp_path / "out")
    client = create_app(cfg, service_factory=lambda _s: None).test_client()  # type: ignore[arg-type,return-value]
    data = {"video": (io.BytesIO(b"definitely not a video" * 100), "fake.mp4"), "clip_count": "1",
            "clip_duration": "3"}
    r = client.post("/jobs", data=data, content_type="multipart/form-data")
    assert r.status_code == 400 and "could not be read" in r.get_data(as_text=True)
    assert files(cfg.upload_dir) == []
