from __future__ import annotations

import logging
import shutil
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from flask import (
    Flask,
    abort,
    current_app,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge
from werkzeug.wrappers import Response

from app.clipping import (
    MAX_CLIP_COUNT,
    MAX_CLIP_DURATION,
    MAX_INSTRUCTION_CHARS,
    MIN_CLIP_DURATION,
    ClipGenerationService,
    ClipJobRequest,
    JobStatus,
)
from app.video import (
    SUPPORTED_EXTENSIONS,
    VideoInfo,
    VideoProcessingError,
    VideoService,
)

from .config import UIConfig
from .jobs import (
    CLIP_NAME_RE,
    Job,
    JobStore,
    ServiceFactory,
    friendly_video_error,
    is_job_id,
    new_job_id,
    run_job,
)

logger = logging.getLogger(__name__)

DEFAULT_INSTRUCTION = "interesting moments"
STAGES = [
    (JobStatus.VALIDATING, "Checking the video"),
    (JobStatus.TRANSCRIBING, "Transcribing speech (Whisper)"),
    (JobStatus.ANALYZING, "Finding moments with local AI (Qwen)"),
    (JobStatus.SELECTING, "Selecting distinct moments"),
    (JobStatus.GENERATING, "Cutting clips (FFmpeg)"),
    (JobStatus.VALIDATING_OUTPUTS, "Verifying clips"),
]

Probe = Callable[[Path], VideoInfo]


class FormError(ValueError):
    """A user-correctable problem with the submitted form."""


@dataclass
class UIState:
    config: UIConfig
    jobs: JobStore
    service_factory: ServiceFactory
    probe: Probe


def _default_factory(on_status: Callable[[JobStatus, str], None]) -> ClipGenerationService:
    return ClipGenerationService(on_status=on_status)


def _default_probe(path: Path) -> VideoInfo:
    return VideoService().probe(path)


def create_app(
    config: UIConfig | None = None,
    service_factory: ServiceFactory | None = None,
    probe: Probe | None = None,
) -> Flask:
    config = config or UIConfig.from_env()
    config = UIConfig(
        host=config.host,
        port=config.port,
        upload_dir=config.upload_dir.resolve(),
        output_dir=config.output_dir.resolve(),
        max_upload_mb=config.max_upload_mb,
        debug=config.debug,
    )
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = config.max_upload_mb * 1024 * 1024
    app.config["DEBUG"] = config.debug
    app.extensions["clipper"] = UIState(config, JobStore(), service_factory or _default_factory, probe or _default_probe)
    _remove_stale_uploads(config.upload_dir)

    app.add_url_rule("/", "index", index)
    app.add_url_rule("/jobs", "create_job", create_job, methods=["POST"])
    app.add_url_rule("/jobs/<job_id>", "job", job_page)
    app.add_url_rule("/jobs/<job_id>/clips/<name>", "download", download)
    app.register_error_handler(HTTPException, http_error)
    app.jinja_env.filters["timecode"] = timecode
    app.jinja_env.filters["basename"] = lambda p: Path(p).name
    return app


def _state() -> UIState:
    state: UIState = current_app.extensions["clipper"]
    return state


def _remove_stale_uploads(upload_dir: Path) -> None:
    """Uploads are deleted when their job ends; leftovers mean the server stopped mid-job."""
    if upload_dir.is_dir():
        for child in upload_dir.iterdir():
            if child.is_dir() and is_job_id(child.name):
                shutil.rmtree(child, ignore_errors=True)


def _limits() -> dict[str, Any]:
    return {
        "max_count": MAX_CLIP_COUNT,
        "min_duration": MIN_CLIP_DURATION,
        "max_duration": MAX_CLIP_DURATION,
        "max_instruction": MAX_INSTRUCTION_CHARS,
        "max_upload_mb": _state().config.max_upload_mb,
        "extensions": ", ".join(sorted(e.lstrip(".").upper() for e in SUPPORTED_EXTENSIONS)),
        "accept": ",".join(sorted(SUPPORTED_EXTENSIONS)),
    }


def index() -> str:
    return render_template("index.html", form={}, error=None, **_limits())


def create_job() -> Response | tuple[str, int]:
    state = _state()
    job_id = new_job_id()
    upload_dir = state.config.upload_dir / job_id
    output_dir = state.config.output_dir / job_id
    try:
        ext, display_name = _check_upload_name()
        clip_request = _build_request(upload_dir / f"source{ext}", output_dir)
        _save_upload(Path(clip_request.input_path), state.probe)
    except FormError as e:
        shutil.rmtree(upload_dir, ignore_errors=True)
        return render_template("index.html", form=request.form, error=str(e), **_limits()), 400
    except BaseException:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise

    job = Job(job_id, display_name)
    if not state.jobs.add_if_idle(job):
        shutil.rmtree(upload_dir, ignore_errors=True)
        error = "Another job is still running. Please wait for it to finish."
        return render_template("index.html", form=request.form, error=error, **_limits()), 409
    job.thread = threading.Thread(
        target=run_job, args=(job, clip_request, upload_dir, output_dir, state.service_factory), daemon=True
    )
    job.thread.start()
    return redirect(url_for("job", job_id=job_id), code=303)


def _check_upload_name() -> tuple[str, str]:
    """Return (extension, display name). The client filename is never used as a path."""
    file = request.files.get("video")
    if file is None:
        raise FormError("Please choose a video file.")
    name = PurePosixPath((file.filename or "").replace("\\", "/")).name.strip()
    if not name:
        raise FormError("Please choose a video file.")
    ext = PurePosixPath(name).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise FormError(f"Unsupported file type. Allowed formats: {_limits()['extensions']}.")
    return ext, name[:120]


def _build_request(source: Path, output_dir: Path) -> ClipJobRequest:
    """Parse the form, then let the M05 request model enforce its own limits."""
    form = request.form
    try:
        count = int(form.get("clip_count", "").strip())
    except ValueError:
        raise FormError("Number of clips must be a whole number.") from None
    try:
        duration = float(form.get("clip_duration", "").strip())
    except ValueError:
        raise FormError("Clip duration must be a number of seconds.") from None
    instruction = form.get("instruction", "").strip() or DEFAULT_INSTRUCTION
    try:
        return ClipJobRequest(str(source), str(output_dir), count, duration, instruction)
    except ValueError as e:
        raise FormError(f"Invalid request: {e}.") from None


def _save_upload(source: Path, probe: Probe) -> None:
    file = request.files["video"]
    source.parent.mkdir(parents=True, exist_ok=False)
    file.save(source)  # streamed to disk by Werkzeug, never held in RAM
    if source.stat().st_size == 0:
        raise FormError("The uploaded file is empty.")
    try:
        probe(source)
    except VideoProcessingError as e:
        logger.info("Upload rejected by probe: %s", e)
        raise FormError(friendly_video_error(e)) from None


def _get_job(job_id: str) -> Job:
    job = _state().jobs.get(job_id) if is_job_id(job_id) else None
    if job is None:
        abort(404)
    return job


def job_page(job_id: str) -> str:
    job = _get_job(job_id)
    if job.status is JobStatus.COMPLETED:
        return render_template("result.html", job=job, result=job.result)
    if job.status is JobStatus.FAILED:
        return render_template("error.html", title="Generation failed", message=job.error, job=job)
    current = [s for s, _ in STAGES].index(job.status)
    return render_template("progress.html", job=job, stages=STAGES, current=current)


def download(job_id: str, name: str) -> Response:
    job = _get_job(job_id)
    if not CLIP_NAME_RE.match(name) or name not in job.clip_names():
        abort(404)
    job_dir = _state().config.output_dir / job_id
    if not (job_dir / name).resolve().is_relative_to(job_dir):
        abort(404)
    # send_from_directory re-checks the join and 404s on a missing file.
    return send_from_directory(job_dir, name, as_attachment=True, mimetype="video/mp4")


def http_error(e: HTTPException) -> tuple[str, int]:
    if isinstance(e, RequestEntityTooLarge):
        message = f"The upload is larger than the {_state().config.max_upload_mb} MB limit."
    elif e.code == 404:
        message = "This page, job or clip does not exist. Jobs are kept in memory until the server restarts."
    else:
        message = e.description or "Request failed."
    return render_template("error.html", title=e.name, message=message, job=None), e.code or 500


def timecode(seconds: float) -> str:
    ms = round(seconds * 1000)
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    return f"{h:02d}:{m:02d}:{rem // 1000:02d}.{rem % 1000:03d}"
