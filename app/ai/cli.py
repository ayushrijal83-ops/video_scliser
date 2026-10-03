from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from app.transcription import TranscriptionResult, TranscriptionService

from .client import DEFAULT_MODEL, OllamaConfig
from .exceptions import AIError
from .service import AIReasoningConfig, AIReasoningService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Local AI Video Clipper - AI Reasoning CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze existing transcript JSON
  python -m app.ai transcript.json "Find the most interesting moments"

  # Transcribe and analyze in one step
  python -m app.ai input/video.mp4 "Find funny moments" --transcribe

  # With options
  python -m app.ai transcript.json "Find educational moments" --model qwen2.5:0.5b --max-candidates 10
        """,
    )
    parser.add_argument("input", help="Path to transcript JSON or video file (with --transcribe)")
    parser.add_argument("instruction", help="User instruction for clip selection")
    parser.add_argument(
        "--transcribe",
        action="store_true",
        help="Transcribe video file first (input is video path)",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("OLLAMA_MODEL", DEFAULT_MODEL),
        help=f"Ollama model name (default: $OLLAMA_MODEL or {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--host",
        default="http://localhost:11434",
        help="Ollama host (default: http://localhost:11434)",
    )
    parser.add_argument(
        "--max-candidates",
        type=int,
        default=20,
        help="Maximum candidates to return (default: 20)",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.1,
        help="Sampling temperature (default: 0.1)",
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

    try:
        if args.transcribe:
            # Transcribe video first
            logger.info("Transcribing video: %s", args.input)
            transcriber = TranscriptionService(model_name="small", device="cpu", compute_type="int8")
            transcript = transcriber.transcribe(args.input)
            logger.info("Transcription complete: %d segments, %.2fs", transcript.segment_count, transcript.duration)
        else:
            # Load transcript JSON
            input_path = Path(args.input)
            if not input_path.exists():
                logger.error("Input file not found: %s", input_path)
                return 1
            logger.info("Loading transcript: %s", input_path)
            transcript = TranscriptionResult.from_json(input_path.read_text(encoding="utf-8"))

        # Analyze with AI
        logger.info("Analyzing with AI (model=%s, instruction=%s)", args.model, args.instruction[:50])

        config = AIReasoningConfig(
            ollama_config=OllamaConfig(host=args.host, model=args.model),
            max_candidates=args.max_candidates,
            temperature=args.temperature,
        )
        service = AIReasoningService(config)
        result = service.analyze(transcript, args.instruction)

        output_json = result.to_json()

        if args.output:
            output_path = Path(args.output)
            output_path.write_text(output_json, encoding="utf-8")
            logger.info("Analysis saved to: %s", output_path)
        else:
            print(output_json)

        logger.info(
            "Done: %d candidates, top score=%.2f",
            result.total_candidates,
            result.top_candidate.score if result.top_candidate else 0.0,
        )
        return 0

    except AIError as e:
        logger.error("AI error: %s", e)
        return 1
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 130
    except Exception:
        logger.exception("Unexpected error")
        return 1


if __name__ == "__main__":
    sys.exit(main())