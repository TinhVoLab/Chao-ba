"""Personal-baseline control chart and green / yellow / red / gray daily light.

Method (per elder, per metric channel in ``models.METRICS``):

1. **Baseline.** The first ``baseline_days`` (21) days of a segment form the baseline window. A metric
   gets a baseline if it has >= ``min_valid`` (14) valid values in that window; if the window is too
   sparse, it is extended day by day until ``min_valid`` valid values exist. Robust estimates:
   ``center = median``, ``scale = max(1.4826 * MAD, sigma_floor[metric])``. The floor prevents a very
   regular person (or a discrete metric such as recall 0..3) from getting a near-zero scale.
2. **Standardise** each valid daily value as a *signed* z with positive = worse:
   ``z = BAD_DIRECTION[m] * (x - center) / scale``, clipped to +/-6 so one garbled call cannot dominate.
3. **EWMA** with lambda = 0.3: ``e_t = lam*z_t + (1-lam)*e_{t-1}``, starting at 0 when monitoring
   starts. Days without a valid value do not update the EWMA (carry forward). The reported chart
   statistic is ``e_t / sqrt(lam/(2-lam))`` (asymptotic EWMA sigma), i.e. the ``z`` field of
   ``DailyLight``. Only the worse direction alerts.
   Before standardising, the scale is multiplied by a variance-inflation factor k (~1.45, see
   ``inflation()``) for serial correlation of daily data and for the uncertainty of a 14-21 call
   baseline; without it the chart statistic had SD ~1.6 instead of 1 on stable simulated people.
   **Thresholds:** L_yellow = 2.5 and L_red = 3.5 (CONTRACT.md listed 2.0 / 3.0). With five metric
   channels, 2.0 gave ~0.57 false alarms per person-month on the simulated cohort; 2.5 / 3.5 gives
   ~0.29 at almost the same sensitivity (see data/eval/report.md). Pass ControlConfig(L_yellow=2.0,
   L_red=3.0) to reproduce the contract values.
4. **Rules** (all windows explicit; a "metric-yellow" day = chart statistic >= L_yellow on a valid
   day; runs count consecutive valid days and are *not* broken by missed/invalid days):

   * gray   - baseline not ready (reason ``building_baseline``) or no valid call that day
              (``missed_call`` / ``invalid_call``) *and* nothing alarming is being held.
   * yellow - any metric beyond L_yellow for >= ``yellow_days`` (3) consecutive valid days
              (``metric_trend``); same symptom reported >= 2 times in the last 7 days
              (``symptom_repeat``); 2 consecutive unanswered days (``unanswered``); mood <= 2 on >= 3
              of the last 7 days (``low_mood``).
   * red    - >= 2 metrics in metric-yellow state for >= ``red_days`` (5) days (``multi_metric``);
              one metric beyond L_red for >= ``red_days`` days (``metric_shift``); a fall reported in
              the last ``fall_days`` (1 = today) days (``fall``); >= 3 distinct symptoms in the last 7
              days (``multi_symptom``); 3 consecutive unanswered days (``unanswered``).
   * Event rules (symptoms, fall, unanswered, mood) also apply during baseline building - safety
     first; only the metric rules need a ready baseline.
5. **Hysteresis.** The displayed light rises immediately but only steps down after
   ``recover_days`` (3) consecutive *valid* days whose raw level is lower; it then steps to the
   highest raw level seen in those days. While held, reasons from the last alarming day are kept
   and a ``recovering`` reason is appended. A day without a valid call shows gray only if the held
   level is green (deviation from a literal reading of "gray = no data": hiding an active red
   behind gray because the elder missed one call would be unsafe; such days carry a
   ``missed_call`` / ``invalid_call`` reason instead).
6. **Re-baselining** (DMAIC Control step). ``rebaseline_days=[d]`` means: from day d on, the chart
   uses a baseline re-estimated from the ``baseline_days`` days *preceding* d (the stabilised
   post-intervention period - the caller chooses d after a stable stretch), and the EWMA restarts at
   0, and any held (hysteresis) alarm is cleared - accepting a new normal is a deliberate care-team
   decision. A ``rebaseline`` info reason marks that day. If that trailing window is too sparse (``cfg.rebaseline_mode == "forward"`` or < min_valid
   values), the baseline is instead built from days d.. forward while the previous baseline keeps
   monitoring.
7. ``change_pct`` in reasons = mean of the metric's last 7 valid values vs baseline center, in %.

Population-norm ablation: if ``cfg.population_baseline`` is given ({metric: {center, scale}}), every
person is judged against that fixed norm instead of their own baseline (used only in evaluation).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .models import BAD_DIRECTION, METRICS, DailyLight, DailyRecord, SYMPTOMS

LEVEL = {"gray": -1, "green": 0, "yellow": 1, "red": 2}
NAME = {0: "green", 1: "yellow", 2: "red"}

DEFAULT_SIGMA_FLOOR = {
    "speech_rate_sps": 0.15,     # syllables / s
    "pause_ratio": 0.015,        # fraction of turn time
    "filled_pause_rate": 0.006,  # fraction of tokens
    "mattr": 0.012,
    "recall_score": 0.5,         # 0..3 points
}


@dataclass
class ControlConfig:
    baseline_days: int = 21
    min_valid: int = 14
    lam: float = 0.3
    L_yellow: float = 2.5   # contract default 2.0 -> 2.5 after false-alarm tuning (see docstring)
    L_red: float = 3.5      # contract default 3.0 -> 3.5
    yellow_days: int = 3
    red_days: int = 5
    recover_days: int = 3
    sigma_floor: dict = field(default_factory=lambda: dict(DEFAULT_SIGMA_FLOOR))
    # additional explicit windows
    symptom_window: int = 7
    symptom_repeat: int = 2
    distinct_symptoms_red: int = 3
    mood_window: int = 7
    mood_low: int = 2
    mood_low_days: int = 3
    unanswered_yellow: int = 2
    unanswered_red: int = 3
    fall_days: int = 1
    change_window: int = 7
    z_clip: float = 6.0
    rebaseline_mode: str = "trailing"  # or "forward"
    assumed_phi: float = 0.3            # serial correlation assumed for daily data (see inflation())
    estimation_correction: bool = True
    population_baseline: dict | None = None
    metrics: tuple = METRICS


def _get(rec, key, default=None):
    if isinstance(rec, dict):
        return rec.get(key, default)
    return getattr(rec, key, default)


def _as_record(rec) -> DailyRecord:
    if isinstance(rec, DailyRecord):
        return rec
    allowed = DailyRecord.__dataclass_fields__.keys()
    return DailyRecord(**{k: v for k, v in rec.items() if k in allowed})


DISCRETE = {"recall_score"}


def _robust(values: list[float], floor: float, discrete: bool = False) -> dict:
    """center = median, scale = max(1.4826*MAD, floor). For a discrete, ceiling-bound metric
    (recall 0..3: the median is usually 3 and MAD 0) use mean and SD instead."""
    arr = np.asarray(values, dtype=float)
    if discrete:
        center = float(np.mean(arr))
        spread = float(np.std(arr, ddof=1)) if arr.size > 1 else 0.0
    else:
        center = float(np.median(arr))
        spread = 1.4826 * float(np.median(np.abs(arr - center)))
    return {"center": center, "scale": max(spread, floor), "n": int(arr.size)}


def inflation(n: int, cfg: "ControlConfig") -> float:
    """Variance-inflation factor k applied to the baseline scale before standardising.

    The textbook EWMA sigma sqrt(lam/(2-lam)) assumes i.i.d. data and a *known* in-control mean.
    Daily behavioural data are serially correlated (AR(1), phi ~ 0.3) and the center is estimated from
    only n ~ 14-21 calls, which leaves a persistent offset the EWMA cannot average away. We keep the
    asymptotic EWMA limit but standardise with scale*k, where
    k^2 = (1 + phi(1-lam)) / (1 - phi(1-lam)) + (pi/2) / (n * lam/(2-lam)).
    """
    lam, phi = cfg.lam, cfg.assumed_phi
    k_ar = (1 + phi * (1 - lam)) / (1 - phi * (1 - lam))
    k_est = (math.pi / 2) / (max(n, 1) * lam / (2 - lam)) if cfg.estimation_correction else 0.0
    return math.sqrt(k_ar + k_est)


def estimate_baseline(records: list[DailyRecord], cfg: ControlConfig, start_idx: int, end_idx: int | None = None):
    """Baseline from records[start_idx:...]. Returns (baseline dict per metric, index of first monitored day).

    Uses ``baseline_days`` days from start_idx, extended until every metric that ever appears has
    ``min_valid`` values (or data runs out). Metrics that never reach min_valid get no baseline.
    """
    n = len(records)
    stop = n if end_idx is None else end_idx
    start_day = records[start_idx].day
    i = start_idx
    vals: dict[str, list[float]] = {m: [] for m in cfg.metrics}
    while i < stop:
        r = records[i]
        if r.day - start_day >= cfg.baseline_days:
            # window over; stop once the primary requirement (min_valid valid days) holds
            n_valid = max(len(v) for v in vals.values()) if vals else 0
            if n_valid >= cfg.min_valid:
                break
        if r.valid:
            for m in cfg.metrics:
                x = getattr(r, m)
                if x is not None and not (isinstance(x, float) and math.isnan(x)):
                    vals[m].append(float(x))
        i += 1
    base = {}
    for m, v in vals.items():
        if len(v) >= cfg.min_valid:
            base[m] = _robust(v, cfg.sigma_floor.get(m, 1e-6), m in DISCRETE)
    ready = bool(base) and max(len(v) for v in vals.values()) >= cfg.min_valid
    return (base if ready else {}), i


def _trailing_baseline(records, cfg, idx):
    """Baseline from the baseline_days calendar days before records[idx]."""
    d = records[idx].day
    vals: dict[str, list[float]] = {m: [] for m in cfg.metrics}
    for r in records[:idx]:
        if d - cfg.baseline_days <= r.day < d and r.valid:
            for m in cfg.metrics:
                x = getattr(r, m)
                if x is not None:
                    vals[m].append(float(x))
    base = {m: _robust(v, cfg.sigma_floor.get(m, 1e-6), m in DISCRETE) for m, v in vals.items() if len(v) >= cfg.min_valid}
    return base


class _State:
    def __init__(self, cfg: ControlConfig):
        self.cfg = cfg
        self.reset_ewma()

    def reset_ewma(self):
        self.e = {m: 0.0 for m in self.cfg.metrics}
        self.run_y = {m: 0 for m in self.cfg.metrics}
        self.run_r = {m: 0 for m in self.cfg.metrics}
        self.recent = {m: [] for m in self.cfg.metrics}
        self.started = {m: False for m in self.cfg.metrics}


def evaluate_series(records: list[DailyRecord], cfg: ControlConfig | None = None,
                    rebaseline_days: list[int] | None = None) -> list[DailyLight]:
    """Evaluate a person's daily records into one ``DailyLight`` per record (sorted by day).

    Accepts ``DailyRecord`` objects or dicts with the same fields.
    """
    cfg = cfg or ControlConfig()
    recs = sorted((_as_record(r) for r in records), key=lambda r: r.day)
    if not recs:
        return []
    lams = cfg.lam
    sig_e = math.sqrt(lams / (2.0 - lams))
    rebase = sorted(set(rebaseline_days or []))

    st = _State(cfg)
    # baseline bookkeeping
    if cfg.population_baseline:
        baseline = {m: dict(v) for m, v in cfg.population_baseline.items() if m in cfg.metrics}
        monitor_from_idx = 0
    else:
        baseline, monitor_from_idx = estimate_baseline(recs, cfg, 0)
        if not baseline:
            monitor_from_idx = len(recs)
    pending_forward: tuple[int, dict] | None = None  # (activation idx, baseline) for forward rebaseline
    first_day = recs[0].day

    held = 0
    held_reasons: list[dict] = []
    better_streak = 0
    better_levels: list[int] = []
    unans_streak = 0
    out: list[DailyLight] = []
    hist: list[DailyRecord] = []

    for idx, r in enumerate(recs):
        hist.append(r)
        # ---- re-baselining -------------------------------------------------------------
        rebased_today = False
        if r.day in rebase and not cfg.population_baseline:
            new = {} if cfg.rebaseline_mode == "forward" else _trailing_baseline(recs, cfg, idx)
            if new:
                baseline = new
                monitor_from_idx = min(monitor_from_idx, idx)
                st.reset_ewma()
                # accepting a new normal is a deliberate care-team decision: clear held state
                held, held_reasons, better_streak, better_levels = 0, [], 0, []
                rebased_today = True
            else:
                fb, act = estimate_baseline(recs, cfg, idx)
                if fb:
                    pending_forward = (act, fb)
        if pending_forward and idx == pending_forward[0]:
            baseline = pending_forward[1]
            pending_forward = None
            st.reset_ewma()

        baseline_ready = idx >= monitor_from_idx and bool(baseline)
        valid = bool(r.answered and r.valid)
        unans_streak = 0 if r.answered else unans_streak + 1

        # ---- metric chart update -------------------------------------------------------
        zout: dict[str, float | None] = {m: None for m in cfg.metrics}
        if baseline_ready:
            for m in cfg.metrics:
                b = baseline.get(m)
                if not b:
                    continue
                x = getattr(r, m)
                if valid and x is not None:
                    k = b.get("k") or inflation(b.get("n", 10 ** 6), cfg)
                    b["k"] = k
                    z = BAD_DIRECTION[m] * (float(x) - b["center"]) / (b["scale"] * k)
                    z = max(-cfg.z_clip, min(cfg.z_clip, z))
                    st.e[m] = lams * z + (1 - lams) * st.e[m]
                    st.started[m] = True
                    stat = st.e[m] / sig_e
                    st.run_y[m] = st.run_y[m] + 1 if stat >= cfg.L_yellow else 0
                    st.run_r[m] = st.run_r[m] + 1 if stat >= cfg.L_red else 0
                    st.recent[m].append(float(x))
                    if len(st.recent[m]) > cfg.change_window:
                        st.recent[m].pop(0)
                if st.started[m]:
                    zout[m] = round(st.e[m] / sig_e, 3)

        # ---- raw level from rules ------------------------------------------------------
        reasons: list[dict] = []
        raw = 0

        def add(level, reason):
            nonlocal raw
            reason["level"] = NAME[level]
            reasons.append(reason)
            raw = max(raw, level)

        if baseline_ready:
            def chg(m):
                b = baseline[m]
                if not st.recent[m] or not b["center"]:
                    return None
                return round((float(np.mean(st.recent[m])) - b["center"]) / abs(b["center"]) * 100.0, 1)

            yellow_metrics = [m for m in cfg.metrics if st.run_y[m] >= cfg.red_days]
            if len(yellow_metrics) >= 2:
                add(2, {"code": "multi_metric", "metrics": yellow_metrics,
                        "days": min(st.run_y[m] for m in yellow_metrics)})
            for m in cfg.metrics:
                if st.run_r[m] >= cfg.red_days:
                    add(2, {"code": "metric_shift", "metric": m, "days": st.run_r[m],
                            "change_pct": chg(m), "z": zout[m]})
                elif st.run_y[m] >= cfg.yellow_days:
                    add(1, {"code": "metric_trend", "metric": m, "days": st.run_y[m],
                            "change_pct": chg(m), "z": zout[m]})
            # attach per-metric details to multi_metric reason
            for rr in reasons:
                if rr["code"] == "multi_metric":
                    rr["details"] = [{"metric": m, "days": st.run_y[m], "change_pct": chg(m)} for m in rr["metrics"]]

        # symptoms / falls (window over calendar days)
        w0 = r.day - cfg.symptom_window + 1
        sym_counts: dict[str, int] = {}
        for h in hist[::-1]:
            if h.day < w0:
                break
            for s, c in (h.symptoms or {}).items():
                if c:
                    sym_counts[s] = sym_counts.get(s, 0) + int(c)
        fall_recent = 0
        for h in hist[::-1]:
            if h.day <= r.day - cfg.fall_days:
                break
            fall_recent += int((h.symptoms or {}).get("fall", 0) or 0)
        if fall_recent:
            add(2, {"code": "fall", "symptom": "fall", "quotes": fall_recent, "days": cfg.fall_days})
        if len(sym_counts) >= cfg.distinct_symptoms_red:
            add(2, {"code": "multi_symptom", "symptoms": sorted(sym_counts), "count": len(sym_counts),
                    "quotes": sum(sym_counts.values()), "days": cfg.symptom_window})
        for s, c in sorted(sym_counts.items(), key=lambda kv: -kv[1]):
            if c >= cfg.symptom_repeat and s != "fall":
                add(1, {"code": "symptom_repeat", "symptom": s, "quotes": c, "days": cfg.symptom_window})

        # unanswered
        if unans_streak >= cfg.unanswered_red:
            add(2, {"code": "unanswered", "days": unans_streak})
        elif unans_streak >= cfg.unanswered_yellow:
            add(1, {"code": "unanswered", "days": unans_streak})

        # mood
        m0 = r.day - cfg.mood_window + 1
        low = sum(1 for h in hist if h.day >= m0 and h.mood is not None and h.mood <= cfg.mood_low)
        if low >= cfg.mood_low_days:
            add(1, {"code": "low_mood", "days": low, "window": cfg.mood_window})

        # ---- hysteresis ----------------------------------------------------------------
        info: list[dict] = []
        if not baseline_ready:
            info.append({"code": "building_baseline",
                         "days": sum(1 for h in hist if h.valid and h.answered),
                         "needed": cfg.min_valid, "day_index": r.day - first_day + 1,
                         "window": cfg.baseline_days})
        if rebased_today:
            info.append({"code": "rebaseline", "days": cfg.baseline_days})
        if not r.answered:
            info.append({"code": "missed_call"})
        elif not r.valid:
            info.append({"code": "invalid_call"})

        key = lambda x: (x["code"], x.get("metric"), x.get("symptom"))  # noqa: E731

        def merge(old_reasons, new_reasons):
            active = {key(x) for x in new_reasons}
            return [dict(x) for x in old_reasons if key(x) not in active] + new_reasons

        if raw >= held:
            held = raw
            held_reasons = reasons
            better_streak, better_levels = 0, []
            shown_reasons = reasons
        else:
            if valid or raw > 0:
                better_streak += 1
                better_levels.append((raw, reasons))
            if better_streak >= cfg.recover_days:
                held = max(lv for lv, _ in better_levels)
                if held > raw:
                    # step down to the highest level seen in the recovery window, keep its reasons
                    src = [rs for lv, rs in better_levels if lv == held][-1]
                    held_reasons = merge(src, reasons)
                else:
                    held_reasons = reasons
                better_streak, better_levels = 0, []
                shown_reasons = held_reasons
            else:
                # keep previous alarm reasons; refresh any that are still active today
                shown_reasons = merge(held_reasons, reasons) + [
                    {"code": "recovering", "days": better_streak, "needed": cfg.recover_days}]

        if held == 0 and (not baseline_ready or not valid):
            light = "gray"
        else:
            light = NAME[held]
        out.append(DailyLight(
            elder_id=r.elder_id, day=r.day, date=r.date, light=light,
            reasons=shown_reasons + info, z=zout, baseline_ready=baseline_ready,
        ))
    return out


def baseline_segments(records, cfg: ControlConfig | None = None, rebaseline_days: list[int] | None = None) -> list[dict]:
    """Baselines used by ``evaluate_series``: [{"from_day": d, "baseline": {metric: {center, scale, n}}}]."""
    cfg = cfg or ControlConfig()
    recs = sorted((_as_record(r) for r in records), key=lambda r: r.day)
    if not recs:
        return []
    segs = []
    base, idx = estimate_baseline(recs, cfg, 0)
    if base and idx < len(recs):
        segs.append({"from_day": recs[idx].day, "baseline": base})
    elif base:
        segs.append({"from_day": recs[-1].day + 1, "baseline": base})
    for d in sorted(set(rebaseline_days or [])):
        idxs = [i for i, r in enumerate(recs) if r.day == d]
        if not idxs:
            continue
        i = idxs[0]
        new = {} if cfg.rebaseline_mode == "forward" else _trailing_baseline(recs, cfg, i)
        if new:
            segs.append({"from_day": d, "baseline": new})
        else:
            fb, act = estimate_baseline(recs, cfg, i)
            if fb and act < len(recs):
                segs.append({"from_day": recs[act].day, "baseline": fb})
    return segs


def current_baseline(records, cfg: ControlConfig | None = None, rebaseline_days: list[int] | None = None) -> dict:
    """Baseline in force at the last record: {metric: {"center", "scale"}} (empty if not ready)."""
    segs = baseline_segments(records, cfg, rebaseline_days)
    if not segs:
        return {}
    return {m: {"center": round(v["center"], 4), "scale": round(v["scale"], 4)} for m, v in segs[-1]["baseline"].items()}
