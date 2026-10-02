from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from .exceptions import ClipGenerationError
from .models import ClipJobRequest, JobStatus
from .service import ClipGenerationService

logger = logging.getLogger(__name__)


def _print_status(status: JobStatus, detail: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {status.value:<18} {detail}", file=sys.stderr, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate N exact-duration clips from a video using local AI",
        epilog='Example: python -m app.clipping input/talk.mp4 -n 3 -d 30 -i "funny moments"',
    )
    parser.add_argument("input", help="source video (.mp4 .mkv .mov .avi .webm)")
    parser.add_argument("-n", "--count", type=int, required=True, help="number of clips")
    parser.add_argument("-d", "--duration", type=float, required=True, help="exact seconds per clip")
    parser.add_argument("-i", "--instruction", required=True, help="what the clips should focus on")
    parser.add_argument("-o", "--output-dir", help="job directory (default: output/<video>_<timestamp>)")
    parser.add_argument("--whisper-model", default="small", help="faster-whisper model (default: small)")
    parser.add_argument("--language", help="spoken language code, e.g. en (default: auto-detect)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")

    output_dir = args.output_dir or str(Path("output") / f"{Path(args.input).stem}_{time.strftime('%Y%m%d-%H%M%S')}")
    try:
        request = ClipJobRequest(args.input, output_dir, args.count, args.duration, args.instruction)
    except ValueError as e:
        logger.error("Invalid request: %s", e)
        return 2

    try:
        from app.transcription import TranscriptionError, TranscriptionService

        transcriber = TranscriptionService(model_name=args.whisper_model)
    except TranscriptionError as e:
        logger.error("%s", e)
        return 2

    service = ClipGenerationService(transcriber=transcriber, on_status=_print_status, language=args.language)
    started = time.monotonic()
    try:
        result = service.generate(request)
    except ClipGenerationError as e:
        logger.error("Job failed during %s: %s", e.stage.value, e)
        return 1
    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    print(f"Done in {time.monotonic() - started:.1f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
