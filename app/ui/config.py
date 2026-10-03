from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5000
# Large enough for a long 1080p recording, small enough to stop an accidental multi-GB drop.
DEFAULT_MAX_UPLOAD_MB = 2048


@dataclass(frozen=True)
class UIConfig:
    """Local-only defaults; every value can be overridden with a CLIPPER_* environment variable."""

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    upload_dir: Path = Path("input/ui_uploads")
    output_dir: Path = Path("output/ui_jobs")
    max_upload_mb: int = DEFAULT_MAX_UPLOAD_MB
    debug: bool = False

    @classmethod
    def from_env(cls) -> UIConfig:
        env = os.environ.get
        return cls(
            host=env("CLIPPER_HOST", DEFAULT_HOST),
            port=int(env("CLIPPER_PORT", str(DEFAULT_PORT))),
            upload_dir=Path(env("CLIPPER_UPLOAD_DIR", "input/ui_uploads")),
            output_dir=Path(env("CLIPPER_OUTPUT_DIR", "output/ui_jobs")),
            max_upload_mb=int(env("CLIPPER_MAX_UPLOAD_MB", str(DEFAULT_MAX_UPLOAD_MB))),
            debug=env("CLIPPER_DEBUG", "").strip().lower() in {"1", "true", "yes"},
        )
