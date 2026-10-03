from __future__ import annotations

import json

import pytest

from app.ai.prompts import (
    SYSTEM_PROMPT,
    build_prompt,
    format_transcript_for_prompt,
    parse_ai_response,
)
from app.transcription.models import (
    TranscriptionResult,
    TranscriptSegment,
)


class TestFormatTranscriptForPrompt:
    def test_single_segment(self) -> None:
        seg = TranscriptSegment(start=0.0, end=5.0, text="Hello world")
        result = TranscriptionResult(
            source_file="test.mp4",
            language="en",
            language_probability=0.98,
            duration=5.0,
            segments=[seg],
            model_name="small",
        )
        text, truncated = format_transcript_for_prompt(result, max_chars=8000)
        assert text == "[0.0-5.0] Hello world"
        assert truncated is False

    def test_multiple_segments(self) -> None:
        segs = [
            TranscriptSegment(start=0.0, end=5.0, text="Hello"),
            TranscriptSegment(start=5.0, end=10.0, text="World"),
        ]
        result = TranscriptionResult(
            source_file="test.mp4",
            language="en",
            language_probability=0.98,
            duration=10.0,
            segments=segs,
            model_name="small",
        )
        text, truncated = format_transcript_for_prompt(result, max_chars=8000)
        assert "[0.0-5.0] Hello" in text
        assert "[5.0-10.0] World" in text
        assert truncated is False

    def test_truncation(self) -> None:
        segs = [TranscriptSegment(start=i * 10.0, end=(i + 1) * 10.0, text="X" * 100) for i in range(100)]
        result = TranscriptionResult(
            source_file="test.mp4",
            language="en",
            language_probability=0.98,
            duration=1000.0,
            segments=segs,
            model_name="small",
        )
        text, truncated = format_transcript_for_prompt(result, max_chars=500)
        assert truncated is True
        assert len(text) <= 500


class TestBuildPrompt:
    def test_build_prompt_basic(self) -> None:
        seg = TranscriptSegment(start=0.0, end=5.0, text="Hello world")
        result = TranscriptionResult(
            source_file="test.mp4",
            language="en",
            language_probability=0.98,
            duration=5.0,
            segments=[seg],
            model_name="small",
        )
        system, user, truncated = build_prompt(
            result,
            "Find interesting moments",
            max_candidates=10,
            max_transcript_chars=8000,
        )
        assert "max_candidates" in system or "10" in system
        assert "Find interesting moments" in user
        assert "5.0" in user  # duration
        assert "Hello world" in user
        assert truncated is False


class TestParseAIResponse:
    def test_valid_json(self) -> None:
        response = json.dumps({
            "candidates": [
                {"start": 10.0, "end": 20.0, "reason": "Great moment", "score": 0.9},
                {"start": 30.0, "end": 40.0, "reason": "Another moment", "score": 0.8},
            ]
        })
        candidates = parse_ai_response(response, max_candidates=20)
        assert len(candidates) == 2
        assert candidates[0]["start"] == 10.0
        assert candidates[0]["score"] == 0.9

    def test_with_markdown_fences(self) -> None:
        response = """```json
{
  "candidates": [{"start": 0.0, "end": 10.0, "reason": "Test", "score": 0.9}]
}
```"""
        candidates = parse_ai_response(response, max_candidates=20)
        assert len(candidates) == 1
        assert candidates[0]["reason"] == "Test"

    def test_with_python_fences(self) -> None:
        response = """```
{
  "candidates": [{"start": 0.0, "end": 10.0, "reason": "Test", "score": 0.9}]
}
```"""
        candidates = parse_ai_response(response, max_candidates=20)
        assert len(candidates) == 1

    def test_invalid_json(self) -> None:
        with pytest.raises(ValueError, match="Invalid JSON"):
            parse_ai_response("not json", max_candidates=20)

    def test_raw_newline_inside_string(self) -> None:
        # Seen from qwen2.5:0.5b in the M05 end-to-end run.
        reason = "line one" + chr(10) + "line two"  # a literal newline, not the JSON escape
        response = '{"candidates": [{"start": 1.0, "end": 2.0, "reason": "' + reason + '", "score": 0.9}]}'
        assert parse_ai_response(response)[0]["reason"] == reason

    def test_not_an_object(self) -> None:
        with pytest.raises(TypeError, match="must be a JSON object"):
            parse_ai_response("[]", max_candidates=20)

    def test_missing_candidates(self) -> None:
        with pytest.raises(TypeError, match="'candidates' must be a list"):
            parse_ai_response('{"foo": "bar"}', max_candidates=20)

    def test_candidates_not_list(self) -> None:
        with pytest.raises(TypeError, match="'candidates' must be a list"):
            parse_ai_response('{"candidates": "not a list"}', max_candidates=20)

    def test_candidate_not_object(self) -> None:
        with pytest.raises(TypeError, match="must be an object"):
            parse_ai_response('{"candidates": ["not an object"]}', max_candidates=20)

    def test_max_candidates_limit(self) -> None:
        candidates_list = [{"start": i, "end": i + 1, "reason": f"r{i}", "score": 0.9} for i in range(50)]
        response = json.dumps({"candidates": candidates_list})
        candidates = parse_ai_response(response, max_candidates=20)
        assert len(candidates) == 20

class TestM08QuotePrompt:
    def test_asks_for_exact_unique_quote_and_puts_semantics_first(self) -> None:
        p = SYSTEM_PROMPT
        assert "quote (string)" in p
        assert "copied exactly from the transcript text" in p
        assert "no paraphrasing, no invented words" in p
        assert "appear only once" in p
        assert "Picking the right moment matters more than exact timestamps" in p

    def test_quote_example_is_a_placeholder_and_comes_last(self) -> None:
        example = SYSTEM_PROMPT[SYSTEM_PROMPT.index("JSON FORMAT"):]
        assert '"quote": "<5-20 words copied from the transcript>"' in example
        assert example.index('"score"') < example.index('"quote"')

    def test_m07_rules_kept_verbatim(self) -> None:
        for rule in ("2. Identify self-contained moments that make sense as standalone clips.",
                     "5. Scores represent how well the moment matches the instruction (1.0 = perfect match).",
                     "8. Respect the user's instruction precisely."):
            assert rule in SYSTEM_PROMPT

    def test_no_content_specific_hints(self) -> None:
        lower = SYSTEM_PROMPT.lower()
        for word in ("joke", "funny", "printer", "cache", "deployment", "decision"):
            assert word not in lower
