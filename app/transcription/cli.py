from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .exceptions import TranscriptionError
from .service import TranscriptionService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Local AI Video Clipper - Transcription CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m app.transcription input/video.mp4
  python -m app.transcription input/video.mp4 --model base --language en
  python -m app.transcription input/video.mp4 --output transcript.json
        """,
    )
    parser.add_argument("input", help="Path to video/audio file to transcribe")
    parser.add_argument(
        "--model",
        default="small",
        choices=["tiny", "base", "small", "medium", "large-v1", "large-v2", "large-v3", "large"],
        help="Whisper model size (default: small)",
    )
    parser.add_argument(
        "--device",
        default="cpu",
        choices=["cpu", "cuda"],
        help="Device to run inference on (default: cpu)",
    )
    parser.add_argument(
        "--compute-type",
        default="int8",
        choices=["int8", "int8_float16", "float16", "float32"],
        help="Compute type for model (default: int8)",
    )
    parser.add_argument(
        "--language",
        help="Force language (e.g., en, zh, ja). Auto-detect if not specified.",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Output JSON file path (default: print to stdout)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable debug logging"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    input_path = Path(args.input)
    if not input_path.exists():
        logger.error("Input file not found: %s", input_path)
        return 1

    try:
        logger.info("Initializing transcription service (model=%s, device=%s, compute_type=%s)",
                    args.model, args.device, args.compute_type)
        service = TranscriptionService(
            model_name=args.model,
            device=args.device,
            compute_type=args.compute_type,
        )

        logger.info("Transcribing: %s", input_path)
        result = service.transcribe(str(input_path), language=args.language)

        output_json = result.to_json()

        if args.output:
            output_path = Path(args.output)
            output_path.write_text(output_json, encoding="utf-8")
            logger.info("Transcription saved to: %s", output_path)
        else:
            print(output_json)

        logger.info(
            "Done: %d segments, %.2fs, language=%s (%.2f%%)",
            result.segment_count,
            result.duration,
            result.language,
            result.language_probability * 100,
        )
        return 0

    except TranscriptionError as e:
        logger.error("Transcription error: %s", e)
        return 1
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 130
    except Exception:
        logger.exception("Unexpected error occurred")
        return 1


if __name__ == "__main__":
    sys.exit(main())