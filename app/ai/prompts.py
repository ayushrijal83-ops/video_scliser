from __future__ import annotations

import json

from app.transcription.models import TranscriptionResult

SYSTEM_PROMPT = """You are an expert video content analyzer. Your task is to identify the most interesting, self-contained moments in a timestamped video transcript based on a user's instruction.

RULES:
1. Return ONLY valid JSON. No markdown, no extra text, no explanations.
2. Identify self-contained moments that make sense as standalone clips.
3. Use ONLY timestamps from the provided transcript. Do not invent timestamps.
4. Each candidate must have: start (float), end (float), reason (string), score (float 0-1).
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
      "score": 0.91
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
        data = json.loads(response)
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