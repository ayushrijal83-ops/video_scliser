"""M08 timestamp grounding: the AI decides WHAT (quote), Python decides WHERE (transcript times)."""

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest

from app.ai.client import OllamaClient, OllamaConfig
from app.ai.grounding import (
    MIN_QUOTE_TOKENS,
    ground_quote,
    normalize_tokens,
    transcript_tokens,
)
from app.ai.service import AIReasoningConfig, AIReasoningService
from app.clipping import InsufficientCandidatesError, compute_window, select_moments
from app.transcription.models import (
    TranscriptionResult,
    TranscriptSegment,
    WordTimestamp,
)


def seg(start: float, end: float, text: str, words: list[tuple[float, float, str]] | None = None) -> TranscriptSegment:
    return TranscriptSegment(start, end, text, [WordTimestamp(s, e, w, 0.9) for s, e, w in (words or [])])


def transcript(*segments: TranscriptSegment, duration: float = 120.0) -> TranscriptionResult:
    return TranscriptionResult("t.mp4", "en", 1.0, duration, list(segments), "small")


SEGMENTS = transcript(
    seg(0.0, 10.0, "Welcome everyone to the weekly sync."),
    seg(40.0, 45.0, "Here is the interesting sentence about deployment."),
    seg(45.0, 52.0, "It continues into the next segment, believe it or not."),
    seg(90.0, 95.0, "Let's discuss the printer on the second floor."),
)

WORDS = transcript(
    seg(80.0, 82.0, " We should change the deployment process.", [
        (80.10, 80.25, " We"), (80.25, 80.41, " should"), (80.41, 80.62, " change"),
        (80.62, 80.77, " the"), (80.77, 81.01, " deployment"), (81.01, 81.40, " process."),
    ]),
    seg(82.0, 84.0, " Logged-out users don't log in.", [
        (82.0, 82.6, " Logged-out"), (82.6, 82.9, " users"), (82.9, 83.3, " don't"), (83.3, 83.5, " log"),
        (83.5, 83.9, " in."),
    ]),
)


def ground(quote: str, t: TranscriptionResult = SEGMENTS, hint: tuple[object, object] = (None, None)):
    return ground_quote(quote, transcript_tokens(t), *hint)


# --- normalization ---------------------------------------------------------------------------


def test_normalize_tokens() -> None:
    assert normalize_tokens("I Think We Should Change The Deployment Process.") == normalize_tokens(
        "i think we should change the deployment process"
    )
    assert normalize_tokens("  “Don’t”   stop,\tme!  ") == ["dont", "stop", "me"]
    assert normalize_tokens("logged-out users") == ["logged", "out", "users"]
    assert normalize_tokens("Ünïcode café 40%") == ["ünïcode", "café", "40"]


# --- 1-4: exact, case, punctuation, whitespace -----------------------------------------------------


@pytest.mark.parametrize("quote", [
    "Here is the interesting sentence about deployment.",          # 1 exact
    "HERE IS THE INTERESTING sentence ABOUT deployment",           # 2 case
    '"Here is the interesting sentence - about deployment!"',      # 3 punctuation / surrounding quotes
    "  here   is\tthe\ninteresting sentence about    deployment ",  # 4 whitespace
    "the interesting sentence",                                     # sub-span of a segment
])
def test_formatting_differences_ground_to_transcript_times(quote: str) -> None:
    g = ground(quote)
    assert g.ok and (g.start, g.end) == (40.0, 45.0) and g.occurrences == 1


# --- 5-7: multi-segment, word-level, segment-level ---------------------------------------------------


def test_quote_spanning_two_segments_uses_both_ranges() -> None:
    g = ground("about deployment. It continues into the next segment")
    assert (g.start, g.end) == (40.0, 52.0)
    assert g.text == "about deployment it continues into the next segment"


def test_word_level_timestamps_preferred() -> None:
    g = ground("we should change the deployment process", WORDS)
    assert (g.start, g.end) == (80.10, 81.40)
    assert (ground("change the deployment", WORDS).start, ground("change the deployment", WORDS).end) == (80.41, 81.01)


def test_word_level_across_segments_with_hyphen_and_apostrophe() -> None:
    g = ground("process. Logged out users dont", WORDS)
    assert (g.start, g.end) == (81.01, 83.3)


def test_segment_level_when_no_word_timestamps() -> None:
    g = ground("discuss the printer")
    assert (g.start, g.end) == (90.0, 95.0)  # the whole segment: no finer timing exists


# --- 8-10: not found, ambiguous, repeated -------------------------------------------------------------


@pytest.mark.parametrize("quote", [
    "the interesting sentence about kubernetes",   # one word differs
    "interesting deployment sentence",             # words out of order
    "Here is the interesting sentence about deployment and more",  # runs past the real text
    "../../etc/passwd; rm -rf / && curl evil",     # hostile text is just unmatched words
])
def test_quote_not_found(quote: str) -> None:
    g = ground(quote)
    assert not g.ok and g.reason == "quote not found in transcript"


def test_token_boundaries_respected() -> None:
    t = transcript(seg(0, 5, "The category of cats matters a lot."))
    assert not ground("the cat egory", t).ok
    assert ground("category of cats", t).ok


def test_short_quote_rejected() -> None:
    g = ground("the printer")
    assert not g.ok and "too short" in g.reason and MIN_QUOTE_TOKENS == 3


REPEATED = transcript(
    seg(10.0, 15.0, "Thank you all very much for coming."),
    seg(60.0, 65.0, "Thank you all very much for coming."),
)


def test_ambiguous_quote_without_ai_time_rejected() -> None:
    g = ground("thank you all very much", REPEATED)
    assert not g.ok and g.occurrences == 2 and "ambiguous" in g.reason


@pytest.mark.parametrize(("hint", "expected"), [((58.0, 66.0), (60.0, 65.0)), ((11.0, 12.0), (10.0, 15.0))])
def test_repeated_quote_ai_time_selects_exactly_one_occurrence(hint: tuple[float, float],
                                                               expected: tuple[float, float]) -> None:
    g = ground("thank you all very much", REPEATED, hint)
    assert g.ok and (g.start, g.end) == expected and g.occurrences == 2  # times are the transcript's


@pytest.mark.parametrize("hint", [(30.0, 40.0), (0.0, 100.0), (65.0, 60.0), (float("nan"), 62.0), ("10", "12")])
def test_repeated_quote_unresolvable_hint_rejected(hint: tuple[object, object]) -> None:
    g = ground("thank you all very much", REPEATED, hint)
    assert not g.ok and "ambiguous" in g.reason


def test_grounding_is_deterministic() -> None:
    tokens = transcript_tokens(SEGMENTS)
    results = {ground_quote("interesting sentence about deployment", tokens) for _ in range(5)}
    assert len(results) == 1


# --- 11-16: through the real M03 service and M05 selection ------------------------------------------------


def analyze(t: TranscriptionResult, *candidates: dict) -> tuple[list, list[str]]:
    client = Mock(spec=OllamaClient)
    client.is_available.return_value = True
    client.is_model_available.return_value = True
    client.generate.return_value = json.dumps({"candidates": list(candidates)})
    result = AIReasoningService(AIReasoningConfig(OllamaConfig()), client=client).analyze(t, "interesting moments")
    return result.candidates, result.rejected


def test_incorrect_ai_timestamp_does_not_move_the_clip() -> None:
    """Regression (G): AI quotes the 40-45 s sentence but claims 90-95 s; the clip is cut around 40-45 s."""
    cands, rejected = analyze(SEGMENTS, {"quote": "the interesting sentence about deployment", "start": 90.0,
                                         "end": 95.0, "reason": "key point", "score": 0.9})
    assert not rejected
    (c,) = cands
    assert (c.start, c.end) == (40.0, 45.0) and (c.ai_start, c.ai_end) == (90.0, 95.0)
    (moment,) = select_moments(cands, 1, 10.0, 120.0)
    assert (moment.window.start, moment.window.end) == (37.5, 47.5)
    assert moment.window.end <= 90.0  # nowhere near the claimed 90-95 s


def test_correct_quote_without_usable_ai_timestamp() -> None:
    cands, _ = analyze(SEGMENTS, {"quote": "discuss the printer on the second floor", "start": "soon",
                                  "reason": "r", "score": 0.7})
    assert (cands[0].start, cands[0].end) == (90.0, 95.0) and cands[0].ai_start is None


def test_ungrounded_candidate_is_rejected_others_continue() -> None:
    cands, rejected = analyze(
        SEGMENTS,
        {"quote": "a sentence that was never spoken", "start": 40.0, "end": 45.0, "reason": "r", "score": 0.99},
        {"quote": "thank you", "start": 0.0, "end": 10.0, "reason": "r", "score": 0.95},
        {"quote": "Welcome everyone to the weekly sync", "start": 1.0, "end": 2.0, "reason": "r", "score": 0.5},
    )
    assert [(c.start, c.end) for c in cands] == [(0.0, 10.0)]
    assert rejected[0].startswith("quote not found") and rejected[1].startswith("quote too short")


def test_multiple_grounded_candidates_rank_and_window_exactly() -> None:
    cands, _ = analyze(
        SEGMENTS,
        {"quote": "discuss the printer", "start": 0, "end": 1, "reason": "printer", "score": 0.6},
        {"quote": "interesting sentence about deployment", "start": 0, "end": 1, "reason": "deploy", "score": 0.9},
        {"quote": "welcome everyone to the weekly sync", "start": 0, "end": 1, "reason": "welcome", "score": 0.8},
    )
    moments = select_moments(cands, 3, 6.0, 120.0)
    assert [m.candidate.reason for m in moments] == ["deploy", "welcome", "printer"]
    for m in moments:  # 16: exact-duration windows computed from grounded times
        assert m.window.end - m.window.start == pytest.approx(6.0)
        assert m.window == compute_window(m.candidate.start, m.candidate.end, 6.0, 120.0)
    assert [m.window.start for m in moments] == [39.5, 2.0, 89.5]


def test_grounded_overlap_is_deduplicated_by_m05() -> None:
    """Two quotes from the same place collapse even if the AI claimed far-apart times."""
    cands, _ = analyze(
        SEGMENTS,
        {"quote": "the interesting sentence", "start": 0.0, "end": 5.0, "reason": "a", "score": 0.9},
        {"quote": "sentence about deployment", "start": 100.0, "end": 110.0, "reason": "b", "score": 0.8},
    )
    with pytest.raises(InsufficientCandidatesError) as e:
        select_moments(cands, 2, 10.0, 120.0)
    assert e.value.found == 1


def test_repeated_quote_end_to_end_uses_ai_time_only_to_choose() -> None:
    cands, rejected = analyze(
        REPEATED,
        {"quote": "thank you all very much for coming", "start": 61.0, "end": 64.0, "reason": "a", "score": 0.9},
        {"quote": "thank you all very much for coming", "reason": "b", "score": 0.8},
    )
    assert [(c.start, c.end) for c in cands] == [(60.0, 65.0)]
    assert rejected == ["ambiguous quote: 2 occurrences, no usable AI time to choose: 'thank you all very much for coming'"]


def test_numpy_word_times_become_plain_floats() -> None:
    """Regression (M08 real run): faster-whisper word times are numpy floats; results must be JSON-safe."""
    np = pytest.importorskip("numpy")
    t = transcript(seg(0.0, 2.0, "alpha beta gamma delta", [
        (np.float64(0.1), np.float64(0.5), " alpha"), (np.float64(0.5), np.float64(0.9), " beta"),
        (np.float64(0.9), np.float64(1.3), " gamma"), (np.float64(1.3), np.float64(1.8), " delta"),
    ]))
    g = ground("beta gamma delta", t)
    assert type(g.start) is float and type(g.end) is float
    assert json.dumps({"ok": g.start < g.end, "span": [g.start, g.end]}) == '{"ok": true, "span": [0.5, 1.8]}'
