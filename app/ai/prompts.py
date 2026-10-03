from __future__ import annotations

import json

from app.transcription.models import TranscriptionResult

# M08: the M07 prompt verbatim plus a "quote" per candidate, asked for LAST. The quote is what Python
# grounds in the transcript (app/ai/grounding.py); the model's start/end are only hints.
# Measured alternatives (benchmarks/ai/run_benchmark.py, docs/M07_AI_BENCHMARK.md): asking for the quote
# first made qwen2.5:3b list nearly every line and rank worse, and a sentence-like quote example was copied
# verbatim into every candidate on a real Whisper transcript, so the example is an obvious placeholder.
SYSTEM_PROMPT = """You are an expert video content analyzer. Your task is to identify the most interesting, self-contained moments in a timestamped video transcript based on a user's instruction.

RULES:
1. Return ONLY valid JSON. No markdown, no extra text, no explanations.
2. Identify self-contained moments that make sense as standalone clips.
3. Use ONLY timestamps from the provided transcript. Do not invent timestamps.
4. Each candidate must have: start (float), end (float), reason (string), score (float 0-1), quote (string).
   "quote" is 5 to 20 consecutive words copied exactly from the transcript text of that moment
   (no paraphrasing, no invented words, no "..."). It is used to find the moment in the transcript,
   so choose words that appear only once. Picking the right moment matters more than exact timestamps.
5. Scores represent how well the moment matches the instruction (1.0 = perfect match).
6. Sort candidates by score descending.
7. Avoid overlapping candidates when possible.
8. Respect the user's instruction precisely.
9. Maximum candidates: {max_candidates}.

JSON FORMAT:
{{
  "candidates": [
    {{
      "start": 72.5,
      "end": 105.2,
      "reason": "Clear standalone explanation with a strong hook about the topic.",
      "score": 0.91,
      "quote": "<5-20 words copied from the transcript>"
    }}
  ]
}}"""

USER_PROMPT_TEMPLATE = """INSTRUCTION: {instruction}

TRANSCRIPT DURATION: {duration:.1f} seconds

TRANSCRIPT SEGMENTS:
{transcript_text}

Identify up to {max_candidates} self-contained moments that best match the instruction. Return only the JSON."""


def format_transcript_for_prompt(
    result: TranscriptionResult,
    max_chars: int = 8000,
) -> tuple[str, bool]:
    """Convert transcript to compact text for prompt. Returns (text, was_truncated)."""
    lines = []
    total_chars = 0
    was_truncated = False

    for seg in result.segments:
        line = f"[{seg.start:.1f}-{seg.end:.1f}] {seg.text}"
        if total_chars + len(line) > max_chars:
            was_truncated = True
            break
        lines.append(line)
        total_chars += len(line)

    return "\n".join(lines), was_truncated


def build_prompt(
    result: TranscriptionResult,
    instruction: str,
    max_candidates: int = 20,
    max_transcript_chars: int = 8000,
) -> tuple[str, str, bool]:
    """Build system and user prompts. Returns (system_prompt, user_prompt, was_truncated)."""
    transcript_text, was_truncated = format_transcript_for_prompt(result, max_transcript_chars)

    system = SYSTEM_PROMPT.format(max_candidates=max_candidates)
    user = USER_PROMPT_TEMPLATE.format(
        instruction=instruction,
        duration=result.duration,
        transcript_text=transcript_text,
        max_candidates=max_candidates,
    )

    return system, user, was_truncated


def parse_ai_response(response: str, max_candidates: int = 20) -> list[dict]:
    """Parse and validate AI JSON response. Returns list of candidate dicts."""
    response = response.strip()

    # Remove markdown fences if present
    if response.startswith("```"):
        lines = response.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        response = "\n".join(lines).strip()

    try:
        # strict=False: small models often emit raw newlines/tabs inside JSON strings.
        data = json.loads(response, strict=False)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}")

    if not isinstance(data, dict):
        raise TypeError("Response must be a JSON object")

    candidates = data.get("candidates")
    if not isinstance(candidates, list):
        raise TypeError("'candidates' must be a list")

    if len(candidates) > max_candidates:
        candidates = candidates[:max_candidates]

    validated = []
    for i, c in enumerate(candidates):
        if not isinstance(c, dict):
            raise TypeError(f"Candidate {i} must be an object")
        validated.append(c)

    return validated