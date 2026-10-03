"""Deterministic timestamp grounding: the AI says WHAT (a quote), the transcript says WHERE.

The quote is untrusted text. It is only tokenized and compared with transcript tokens; it never
becomes a path, a command or a timestamp. The returned times are always transcript times
(word-level when Whisper word timestamps exist, segment-level otherwise).
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass

from app.transcription.models import TranscriptionResult

# A 1-2 word quote ("yes", "thank you") cannot identify a moment reliably.
MIN_QUOTE_TOKENS = 3

_TOKEN_RE = re.compile(r"[^\W_]+(?:'[^\W_]+)*")  # letters/digits (any script), internal apostrophes kept
_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'", "`": "'"})


def normalize_tokens(text: str) -> list[str]:
    """Case-, punctuation-, whitespace- and quote-insensitive word tokens.

    "Don't" == "dont", "logged-out" == "logged out", "“Hello,”" == "hello". Number words are not
    converted ("forty" != "40").
    """
    text = unicodedata.normalize("NFKC", text).translate(_APOSTROPHES).lower()
    return [t.replace("'", "") for t in _TOKEN_RE.findall(text)]


@dataclass(frozen=True)
class Token:
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class Grounding:
    """Outcome for one quote. On success start/end are transcript times; otherwise `reason` says why."""

    start: float | None = None
    end: float | None = None
    text: str = ""
    occurrences: int = 0
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.start is not None


def transcript_tokens(transcript: TranscriptionResult) -> list[Token]:
    """Token stream with real timestamps: per word if Whisper gave words, else per segment.

    float() because faster-whisper returns numpy floats; downstream code and JSON expect plain floats.
    """
    tokens: list[Token] = []
    for seg in transcript.segments:
        if seg.words:
            for w in seg.words:
                tokens += [Token(t, float(w.start), float(w.end)) for t in normalize_tokens(w.word)]
        else:
            tokens += [Token(t, float(seg.start), float(seg.end)) for t in normalize_tokens(seg.text)]
    return tokens


def _usable_hint(start: object, end: object) -> tuple[float, float] | None:
    ok = all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (start, end))
    return (float(start), float(end)) if ok and float(start) < float(end) else None  # type: ignore[arg-type]


def ground_quote(
    quote: str,
    tokens: list[Token],
    hint_start: object = None,
    hint_end: object = None,
) -> Grounding:
    """Locate `quote` as a contiguous token run in the transcript.

    One occurrence: grounded. Several identical occurrences: the AI's own (approximate) time range
    may pick one only if it overlaps exactly one occurrence; the returned times are still that
    occurrence's transcript times. Otherwise the quote is rejected - never guessed.
    """
    q = normalize_tokens(quote)
    if len(q) < MIN_QUOTE_TOKENS:
        return Grounding(reason=f"quote too short to ground ({len(q)} words, need {MIN_QUOTE_TOKENS})")
    n = len(q)
    starts = [i for i in range(len(tokens) - n + 1) if all(tokens[i + k].text == q[k] for k in range(n))]
    if not starts:
        return Grounding(reason="quote not found in transcript")

    spans = [(tokens[i].start, max(t.end for t in tokens[i:i + n]), i) for i in starts]
    if len(spans) > 1:
        hint = _usable_hint(hint_start, hint_end)
        if hint is None:
            return Grounding(occurrences=len(spans), reason=f"ambiguous quote: {len(spans)} occurrences, no usable AI time to choose")
        overlapping = [s for s in spans if s[0] < hint[1] and hint[0] < s[1]]
        if len(overlapping) != 1:
            return Grounding(
                occurrences=len(spans),
                reason=f"ambiguous quote: {len(spans)} occurrences, AI time overlaps {len(overlapping)}",
            )
        spans = overlapping
    start, end, i = spans[0]
    if end <= start:
        return Grounding(occurrences=len(starts), reason="grounded span has zero length")
    return Grounding(start=start, end=end, text=" ".join(t.text for t in tokens[i:i + n]), occurrences=len(starts))
