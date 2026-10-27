"""Vietnamese text normalisation helpers shared by the spotter, guardrails and analysis.

Design choice: we match on *diacritic-preserving* text first, because in Vietnamese the tone marks carry
meaning ("té" = to fall, "tế" = economy/sacrifice, "ngã" = fall, "nga" = Russia). Only when an utterance
contains no Vietnamese diacritics at all (typed on a keyboard without IME, or a degraded STT result) do we
fall back to accent-stripped matching against accent-stripped patterns.
"""
from __future__ import annotations

import re
import unicodedata

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text or "")


def normalize(text: str) -> str:
    """Lower-case, NFC, punctuation -> space, collapse whitespace. Keeps diacritics."""
    t = nfc(text).lower()
    t = _PUNCT.sub(" ", t)
    return _WS.sub(" ", t).strip()


def strip_diacritics(text: str) -> str:
    t = unicodedata.normalize("NFD", text)
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Mn")
    return t.replace("đ", "d").replace("Đ", "D")


def has_vietnamese_diacritics(text: str) -> bool:
    return strip_diacritics(nfc(text)) != nfc(text)


def tokens(text: str) -> list[str]:
    n = normalize(text)
    return n.split(" ") if n else []


def contains_phrase(norm_text: str, phrase: str) -> bool:
    """Whole-word phrase match on already-normalised text."""
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", norm_text) is not None


def find_phrase(norm_text: str, phrase: str) -> list[int]:
    return [m.start() for m in re.finditer(rf"(?<!\w){re.escape(phrase)}(?!\w)", norm_text)]


_SENT = re.compile(r"(?<=[\.\!\?…;])\s+|\n+")


def sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENT.split(nfc(text)) if p and p.strip()]
    return parts or ([nfc(text).strip()] if text and text.strip() else [])


def word_count(text: str) -> int:
    return len(tokens(text))
