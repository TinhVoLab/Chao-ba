"""Per-call speech and language metrics (M1-M3) computed from text + VAD timings only.

Design decisions (documented for reviewers):

* **Syllables.** Vietnamese orthography is monosyllabic: every whitespace-separated orthographic
  token is one syllable ("chóng mặt" = 2). A token counts as a syllable if, after stripping
  punctuation/symbols at both ends, it contains at least one letter. Pure numbers ("5", "2026") are
  not counted (ASR usually writes numbers as digits, so their syllable count is unknown; we ignore
  them rather than guess).
* **Tokens = syllables.** We deliberately do *not* use a Vietnamese word segmenter (underthesea etc.):
  it would add a heavy dependency and its errors on ASR text are themselves noisy. Every metric is
  compared against the *same person's* baseline computed with the same tokenizer, so a consistent
  syllable-level unit is sufficient for detecting change.
* **M1 speech_rate_sps** = elder syllables / elder voiced time, where voiced time = sum of elder turn
  durations minus the VAD-measured silent gaps (>= 0.4 s) inside those turns.
* **M2a pause_ratio** = sum of within-turn pauses with 0.4 s <= p <= 3 s / total elder turn time.
  Gaps > 3 s are treated as disengagement / line noise, not hesitation, and are excluded from the
  numerator (but still removed from voiced time).
* **M2b filled_pause_rate** = filler tokens (ờ, ơ, à, ừm, ừ, ậm, hmm, ư, ...) / all elder tokens.
* **M3 mattr** = moving-average type-token ratio, window 40, on lower-cased tokens with fillers
  removed (fillers are hesitation, not vocabulary). ``None`` if fewer than 60 lexical tokens.
* **Validity gate.** If elder voiced speech < ``min_elder_sec`` (default 45 s) the call is marked
  ``valid=False, invalid_reason="too_short"``. Metric values are still returned when computable, but
  the control chart ignores invalid days.
"""
from __future__ import annotations

import unicodedata

from .models import CallMetrics, Turn

PAUSE_MIN = 0.4
PAUSE_MAX = 3.0
MATTR_WINDOW = 40
MATTR_MIN_TOKENS = 60

# Vietnamese hesitation tokens, compared after lower-casing and NFC normalisation.
FILLERS = frozenset(
    unicodedata.normalize("NFC", w)
    for w in (
        "ờ", "ơ", "ờm", "ơm", "à", "ừm", "ừ", "ư", "ừa", "ậm", "ầm", "ẩm", "ừhm", "hmm", "hm", "ừmm",
        "uhm", "um", "mmm", "ừh",
    )

)


def _strip_token(tok: str) -> str:
    """Strip leading/trailing punctuation and symbols (Unicode categories P* and S*)."""
    start, end = 0, len(tok)
    while start < end and unicodedata.category(tok[start])[0] in "PS":
        start += 1
    while end > start and unicodedata.category(tok[end - 1])[0] in "PS":
        end -= 1
    return tok[start:end]


def tokenize(text: str) -> list[str]:
    """Lower-cased syllable tokens (letters only; punctuation stripped; numbers dropped)."""
    if not text:
        return []
    text = unicodedata.normalize("NFC", text).lower()
    out = []
    for raw in text.split():
        tok = _strip_token(raw)
        # split on internal hyphens/slashes e.g. "ừ-ừ", "chợ/quán"
        for part in tok.replace("-", " ").replace("/", " ").split():
            part = _strip_token(part)
            if part and any(ch.isalpha() for ch in part):
                out.append(part)
    return out


def count_syllables(text: str) -> int:
    """Number of Vietnamese syllables (= letter-bearing whitespace tokens) in ``text``."""
    return len(tokenize(text))


def is_filler(token: str) -> bool:
    return unicodedata.normalize("NFC", token.lower()) in FILLERS


def mattr(tokens: list[str], window: int = MATTR_WINDOW, min_tokens: int = MATTR_MIN_TOKENS) -> float | None:
    """Moving-average type-token ratio. ``None`` if fewer than ``min_tokens`` tokens."""
    n = len(tokens)
    if n < min_tokens:
        return None
    if n <= window:
        return len(set(tokens)) / n
    counts: dict[str, int] = {}
    for t in tokens[:window]:
        counts[t] = counts.get(t, 0) + 1
    total = len(counts)
    for i in range(window, n):
        new, old = tokens[i], tokens[i - window]
        counts[new] = counts.get(new, 0) + 1
        counts[old] -= 1
        if counts[old] == 0:
            del counts[old]
        total += len(counts)
    return total / (window * (n - window + 1))


def compute_call_metrics(turns: list[Turn], min_elder_sec: float = 45.0) -> CallMetrics:
    """Compute M1-M3 for the elder's turns of one call. See module docstring for definitions."""
    turn_time = 0.0
    pause_counted = 0.0   # pauses in [0.4, 3] s
    gap_removed = 0.0     # all silent gaps >= 0.4 s (removed from voiced time)
    tokens: list[str] = []
    for t in turns:
        if t.speaker != "elder":
            continue
        dur = max(0.0, float(t.end) - float(t.start))
        turn_time += dur
        for p in t.pauses or []:
            p = float(p)
            if p >= PAUSE_MIN:
                gap_removed += p
                if p <= PAUSE_MAX:
                    pause_counted += p
        tokens.extend(tokenize(t.text))

    voiced = max(0.0, turn_time - gap_removed)
    n_tok = len(tokens)
    n_fill = sum(1 for t in tokens if is_filler(t))
    lexical = [t for t in tokens if not is_filler(t)]

    speech_rate = round(n_tok / voiced, 4) if voiced > 0 and n_tok > 0 else None
    pause_ratio = round(min(1.0, pause_counted / turn_time), 4) if turn_time > 0 else None
    filled = round(n_fill / n_tok, 4) if n_tok > 0 else None
    m3 = mattr(lexical)
    m3 = round(m3, 4) if m3 is not None else None

    valid = voiced >= min_elder_sec
    return CallMetrics(
        speech_rate_sps=speech_rate,
        pause_ratio=pause_ratio,
        filled_pause_rate=filled,
        mattr=m3,
        elder_speech_sec=round(voiced, 2),
        word_count=n_tok,
        valid=valid,
        invalid_reason=None if valid else "too_short",
    )
