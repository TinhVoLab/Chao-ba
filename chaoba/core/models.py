"""Shared data types for Chào Bà. This file is the contract between core, server and agent.

Do not change field names without updating CONTRACT.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Literal, Optional

Light = Literal["green", "yellow", "red", "gray"]
Channel = Literal["web", "pstn", "sim"]  # sim = simulated data
Speaker = Literal["elder", "agent", "other"]

METRICS = ("speech_rate_sps", "pause_ratio", "filled_pause_rate", "mattr", "recall_score")
# Direction in which a metric gets worse: -1 = lower is worse, +1 = higher is worse.
BAD_DIRECTION = {
    "speech_rate_sps": -1,
    "pause_ratio": +1,
    "filled_pause_rate": +1,
    "mattr": -1,
    "recall_score": -1,
}
SYMPTOMS = ("pain", "insomnia", "skipped_meal", "dizziness", "fall", "sadness", "missed_medication")


@dataclass
class Turn:
    """One utterance in a call. Times are seconds from call start."""
    speaker: Speaker
    text: str
    start: float
    end: float
    # Silent gaps (seconds) inside this utterance, as measured by VAD. Only gaps 0.4-3 s count as pauses.
    pauses: list[float] = field(default_factory=list)


@dataclass
class CallMetrics:
    speech_rate_sps: Optional[float]      # M1 syllables / second of elder voiced time
    pause_ratio: Optional[float]          # M2a total pause time / elder turn time
    filled_pause_rate: Optional[float]    # M2b filler tokens ("ờ", "à", "ừm", "ừ"...) / total tokens
    mattr: Optional[float]                # M3 moving-average type-token ratio, window 40, needs >= 60 words
    elder_speech_sec: float
    word_count: int                       # Vietnamese tokens (syllables) spoken by elder
    valid: bool
    invalid_reason: Optional[str] = None  # "too_short" | "bad_audio" | "not_elder"


@dataclass
class CallAnalysis:
    summary_vi: str                       # 1-2 sentence family-facing summary
    summary_en: str
    mood: int                             # 1 (very low) .. 5 (very good)
    symptoms: dict[str, list[str]]        # symptom -> verbatim quotes; keys from SYMPTOMS
    recall_score: Optional[int]           # M4 0..3, None if not asked
    recall_cue_level: Optional[str]       # "free" | "cued" | "failed"
    memory_facts_new: list[str]
    followup_hooks: list[str]
    emergency: bool
    prompt_version: str


@dataclass
class DailyRecord:
    """One row per elder per day; the unit the control chart works on."""
    elder_id: str
    day: int                              # day index from enrolment (1-based)
    date: str                             # ISO date
    channel: Channel
    answered: bool
    valid: bool
    speech_rate_sps: Optional[float] = None
    pause_ratio: Optional[float] = None
    filled_pause_rate: Optional[float] = None
    mattr: Optional[float] = None
    recall_score: Optional[float] = None
    mood: Optional[int] = None
    symptoms: dict[str, int] = field(default_factory=dict)   # symptom -> count that day
    summary_vi: str = ""
    summary_en: str = ""
    simulated: bool = True
    emergency: bool = False               # an emergency was triggered during that day's call (forces red)


@dataclass
class DailyLight:
    elder_id: str
    day: int
    date: str
    light: Light
    reasons: list[dict]                   # e.g. {"code": "metric_trend", "metric": "speech_rate_sps", "days": 4, "change_pct": -15.2}
    z: dict[str, Optional[float]]         # EWMA z-score per metric (signed; positive = worse direction)
    baseline_ready: bool
    explanation_vi: str = ""
    explanation_en: str = ""


def to_dict(obj) -> dict:
    return asdict(obj)
