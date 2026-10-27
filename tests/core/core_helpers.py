from chaoba.core.models import DailyRecord

BASE = {"speech_rate_sps": 4.5, "pause_ratio": 0.12, "filled_pause_rate": 0.04, "mattr": 0.72, "recall_score": 3.0}


def rec(day, answered=True, valid=True, mood=4, symptoms=None, **over):
    jitter = 0.05 if day % 2 else -0.05
    vals = {}
    if answered and valid:
        vals = {"speech_rate_sps": BASE["speech_rate_sps"] + jitter, "pause_ratio": 0.12 + jitter / 50,
                "filled_pause_rate": 0.04 + jitter / 100, "mattr": 0.72 + jitter / 20, "recall_score": 3.0}
        vals.update(over)
    return DailyRecord(elder_id="t", day=day, date=f"2026-01-{day:02d}" if day < 32 else f"d{day}",
                       channel="sim", answered=answered, valid=valid and answered, mood=mood if answered else None,
                       symptoms=symptoms or {}, **vals)


def series(n=40, overrides=None):
    """n days; overrides: {day: kwargs for rec}"""
    overrides = overrides or {}
    return [rec(d, **overrides.get(d, {})) for d in range(1, n + 1)]
