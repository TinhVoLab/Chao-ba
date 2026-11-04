"""Evaluation of the daily light on a simulated cohort (NOT clinical validation).

Definitions (person = one simulated elder; monitored day = personal baseline ready, i.e. after day 21):

* **Rule event** for a rule family S - a day whose light is yellow/red, whose reasons include a rule in S,
  and whose previous day did not (the moment rule family S starts driving an alarm).
* **Attributed detection** - an injected decline counts as detected only if a rule event *matching the
  decline's channel* starts within ``window`` (45) days after the true onset (onset <= day <= onset + 45,
  truncated at end of follow-up). Matching families (``MATCHING_RULES``):
  cognitive_drift -> speech/recall control-chart rules; frailty_symptom -> symptom/fall rules or chart;
  mood_withdrawal -> low_mood or chart; missed_calls -> unanswered (an *operational* check, reported
  separately and excluded from the clinical headline because missed calls are the decline itself).
* **Chance rate** - the same attribution rule applied to *stable* elders at pseudo-onsets: every
  (stable elder, decline elder) pair re-uses the decline elder's real onset day and decline type. The mean
  over pairs is the share of "detections" one would score with no decline at all. **Excess sensitivity** =
  attributed sensitivity - chance rate.
* **Chart-only sensitivity** - the same, but only the speech/recall control-chart rules count.
* **False alarms** - alarm episodes (maximal yellow/red runs, any rule) starting on stable monitored
  person-days (all monitored days of stable elders + pre-onset days of decline elders), per person-month
  (30 monitored days). Chart false alarms = chart rule events on stable person-days.
* **Specificity** - person-level: share of stable elders with no alarm episode; day-level: share of
  stable monitored days that are not yellow/red.
* **Period specificity** - share of stable elders' 30-day periods of monitoring (consecutive complete blocks of 30
  monitored days, stable elders only) in which the light was never yellow or red.
* **False-referral burden** - red-alert starts (the displayed light turns red from a non-red day) on monitored days of
  stable elders, per 100 person-months (30 monitored days). Every red goes to qualified human review
  (care_review.py), so this is the review workload created by people with no decline; whether a review becomes a
  referral is a human decision the simulation cannot model.
* **Completion** - share of scheduled daily calls (one per simulated day, all elders) that were answered; *valid* =
  answered and long enough to measure. Both are set by the generator's assumed miss/short-call rates.
* **Test-retest reliability** (``retest_reliability``) - ICC(2,1) (two-way random effects, absolute agreement, single
  measurement; Shrout & Fleiss 1979) of each per-call metric between adjacent monitored weeks on stable elders: (a)
  the weekly mean (>= 3 valid calls) and (b) a single call (the first valid call of the week); averaged over all
  adjacent week pairs. In a simulation it mirrors the assumed between-person spread versus day-to-day noise.
* **Uncertainty** - 95 % percentile intervals from a bootstrap over people (stratified: clinical decline,
  missed-calls decline and stable elders resampled separately; fixed RNG seed -> deterministic).
* **Hold-out** - ``run_holdout`` chooses L_yellow on a development cohort (pre-stated rule
  ``select_threshold``) and reports every headline number on a separate held-out cohort.
* **Ablation** - same rules, but every person is judged against a *population norm* (pooled median /
  MAD of all baseline-period values) instead of their own baseline.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict

import numpy as np

from .control_chart import DISCRETE, ControlConfig, _as_record, _robust, evaluate_series
from .models import METRICS
from .synth import age_band

DISCLAIMER = "Simulated cohort - not clinical validation."
METRIC_CODES = frozenset({"metric_trend", "metric_shift", "multi_metric"})
SYMPTOM_CODES = frozenset({"symptom_repeat", "multi_symptom", "fall"})
MATCHING_RULES = {
    "cognitive_drift": METRIC_CODES,
    "frailty_symptom": METRIC_CODES | SYMPTOM_CODES,
    "mood_withdrawal": METRIC_CODES | {"low_mood"},
    "missed_calls": frozenset({"unanswered"}),
}
CLINICAL_TYPES = ("cognitive_drift", "frailty_symptom", "mood_withdrawal")
OPERATIONAL_TYPES = ("missed_calls",)
FAMILIES = {"chart": METRIC_CODES, **MATCHING_RULES}
WINDOW_DAYS = 45
L_GRID = (1.5, 2.0, 2.25, 2.5, 2.75, 3.0, 3.5, 4.0)
RED_GAP = 1.0           # L_red = L_yellow + 1.0 along the operating curve (default config: 3.0 / 4.0)
FA_BUDGET = 0.30        # selection constraint: all-rule false alarms per person-month on the dev cohort
PERIOD_DAYS = 30        # specificity period and person-month length
RELIABILITY_MIN_CALLS = 3   # valid calls needed for a weekly mean in the test-retest analysis


# ---------------------------------------------------------------------------------------------
# per-person scoring
# ---------------------------------------------------------------------------------------------
def _episodes(lights):
    eps = []
    cur = None
    for l in lights:
        if l.light in ("yellow", "red"):
            if cur is None:
                cur = {"start": l.day, "end": l.day, "peak": l.light,
                       "codes": sorted({r["code"] for r in l.reasons if r.get("level")})}
            else:
                cur["end"] = l.day
                if l.light == "red":
                    cur["peak"] = "red"
        else:
            if cur:
                eps.append(cur)
            cur = None
    if cur:
        eps.append(cur)
    return eps


def _rule_events(lights, codes) -> list[int]:
    """Days on which rule family ``codes`` starts driving a yellow/red light."""
    out, prev = [], False
    for l in lights:
        on = l.light in ("yellow", "red") and any(r.get("level") and r.get("code") in codes for r in l.reasons)
        if on and not prev:
            out.append(l.day)
        prev = on
    return out


def _first_in(days, lo, hi):
    for d in days:
        if d > hi:
            return None
        if d >= lo:
            return d
    return None


def population_baseline(cohort, cfg: ControlConfig | None = None) -> dict:
    cfg = cfg or ControlConfig()
    vals = defaultdict(list)
    for p in cohort:
        for r in p["records"]:
            if r["day"] <= cfg.baseline_days and r["valid"]:
                for m in METRICS:
                    if r.get(m) is not None:
                        vals[m].append(float(r[m]))
    return {m: _robust(v, cfg.sigma_floor.get(m, 1e-6), m in DISCRETE) for m, v in vals.items() if v}


def _score(cohort, cfg, window=WINDOW_DAYS):
    rows = []
    for p in cohort:
        recs = [_as_record(r) for r in p["records"]]
        lights = evaluate_series(recs, cfg)
        truth = p.get("truth", {"decline": False, "onset_day": None, "type": "stable"})
        onset = truth.get("onset_day") if truth.get("decline") else None
        last = max((l.day for l in lights), default=0)
        eps = _episodes(lights)
        events = {k: _rule_events(lights, v) for k, v in FAMILIES.items()}
        mon = [l for l in lights if l.baseline_ready]
        stable_days = [l for l in mon if onset is None or l.day < onset]
        fa = [e for e in eps if (onset is None or e["start"] < onset) and e["start"] > cfg.baseline_days]
        chart_fa = [d for d in events["chart"] if d > cfg.baseline_days and (onset is None or d < onset)]
        # red-alert starts on stable monitored days; complete 30-day blocks of stable monitoring with no yellow/red day
        red_starts = [l.day for k, l in enumerate(lights) if l.light == "red" and l.baseline_ready
                      and (k == 0 or lights[k - 1].light != "red") and (onset is None or l.day < onset)]
        blocks = [stable_days[k:k + PERIOD_DAYS] for k in range(0, len(stable_days) - PERIOD_DAYS + 1, PERIOD_DAYS)]
        row = {
            "id": p["elder"]["id"], "dialect": p["elder"].get("dialect"), "channel": p["elder"].get("channel_pref"),
            "age_band": age_band(p["elder"].get("age")), "education": p["elder"].get("education"),
            "sched_days": len(recs), "answered_days": sum(1 for r in recs if r.answered),
            "valid_days": sum(1 for r in recs if r.answered and r.valid),
            "periods_total": len(blocks),
            "periods_clear": sum(1 for b in blocks if not any(l.light in ("yellow", "red") for l in b)),
            "red_alerts": len(red_starts),
            "type": truth.get("type", "stable"), "decline": bool(truth.get("decline")), "onset": onset,
            "last_day": last, "events": events,
            "stable_days": len(stable_days),
            "stable_alarm_days": sum(1 for l in stable_days if l.light in ("yellow", "red")),
            "false_alarms": len(fa), "fa_codes": [c for e in fa for c in e["codes"]],
            "chart_false_alarms": len(chart_fa),
            "mostly_flagged": bool(stable_days) and onset is None and
            sum(1 for l in stable_days if l.light in ("yellow", "red")) > 0.5 * len(stable_days),
            "detected": False, "delay": None, "detected_chart": False, "delay_chart": None, "det_codes": [],
        }
        if onset is not None:
            hi = min(onset + window, last)
            d = _first_in(events[row["type"]], onset, hi)
            if d is not None:
                lt = next(l for l in lights if l.day == d)
                row.update(detected=True, delay=d - onset,
                           det_codes=sorted({r["code"] for r in lt.reasons
                                             if r.get("level") and r["code"] in MATCHING_RULES[row["type"]]}))
            dc = _first_in(events["chart"], onset, hi)
            if dc is not None:
                row.update(detected_chart=True, delay_chart=dc - onset)
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------------------------
# summaries with bootstrap CIs
# ---------------------------------------------------------------------------------------------
def _hit_matrix(stable, dec, family_of, window):
    """M[j, i] = 1 if stable elder j has a matching rule event in decline elder i's window."""
    m = np.zeros((len(stable), len(dec)), dtype=float)
    for i, r in enumerate(dec):
        fam = family_of(r)
        for j, s in enumerate(stable):
            hi = min(r["onset"] + window, s["last_day"])
            m[j, i] = _first_in(s["events"][fam], r["onset"], hi) is not None
    return m


def _ci(samples):
    a = np.asarray([x for x in samples if x is not None and not np.isnan(x)], dtype=float)
    if a.size == 0:
        return None
    return [round(float(np.percentile(a, 2.5)), 3), round(float(np.percentile(a, 97.5)), 3)]


def _r(x, nd=3):
    return None if x is None else round(float(x), nd)


def _summ(rows, n_boot=1000, seed=0, window=WINDOW_DAYS, types=CLINICAL_TYPES):
    """Headline numbers (with bootstrap CIs) for a set of scored rows.

    ``types`` = decline types counted as detections (clinical by default); stable rows give the chance
    rate and the false-alarm denominator; every row contributes stable person-days.
    """
    dec = [r for r in rows if r["decline"] and r["type"] in types]
    oth = [r for r in rows if r["decline"] and r["type"] not in types]
    sta = [r for r in rows if not r["decline"]]
    nd, ns = len(dec), len(sta)
    det = np.array([r["detected"] for r in dec], dtype=float)
    detc = np.array([r["detected_chart"] for r in dec], dtype=float)
    M = _hit_matrix(sta, dec, lambda r: r["type"], window) if nd and ns else None
    Mc = _hit_matrix(sta, dec, lambda r: "chart", window) if nd and ns else None
    all_rows = dec + oth + sta
    sd = np.array([r["stable_days"] for r in all_rows], dtype=float)
    fa = np.array([r["false_alarms"] for r in all_rows], dtype=float)
    cfa = np.array([r["chart_false_alarms"] for r in all_rows], dtype=float)
    sad = np.array([r["stable_alarm_days"] for r in all_rows], dtype=float)
    s_fa0 = np.array([r["false_alarms"] == 0 for r in sta], dtype=float)
    s_pt = np.array([r.get("periods_total", 0) for r in sta], dtype=float)
    s_pc = np.array([r.get("periods_clear", 0) for r in sta], dtype=float)
    s_red = np.array([r.get("red_alerts", 0) for r in sta], dtype=float)
    s_sd = np.array([r["stable_days"] for r in sta], dtype=float)
    sch = np.array([r.get("sched_days", 0) for r in all_rows], dtype=float)
    ans = np.array([r.get("answered_days", 0) for r in all_rows], dtype=float)
    val = np.array([r.get("valid_days", 0) for r in all_rows], dtype=float)

    def stats(di, si, ai):
        o = {}
        o["sensitivity"] = det[di].mean() if nd else None
        o["chance"] = M[np.ix_(si, di)].mean() if M is not None else None
        o["excess"] = (o["sensitivity"] - o["chance"]) if o["chance"] is not None else None
        o["sensitivity_chart"] = detc[di].mean() if nd else None
        o["chance_chart"] = Mc[np.ix_(si, di)].mean() if Mc is not None else None
        o["excess_chart"] = (o["sensitivity_chart"] - o["chance_chart"]) if o["chance_chart"] is not None else None
        days = sd[ai].sum()
        o["fa"] = fa[ai].sum() / (days / 30.0) if days else None
        o["fa_chart"] = cfa[ai].sum() / (days / 30.0) if days else None
        o["spec_day"] = 1 - sad[ai].sum() / days if days else None
        o["spec_person"] = s_fa0[si].mean() if ns else None
        o["spec_period"] = s_pc[si].sum() / s_pt[si].sum() if ns and s_pt[si].sum() else None
        o["red_100pm"] = 100 * s_red[si].sum() / (s_sd[si].sum() / PERIOD_DAYS) if ns and s_sd[si].sum() else None
        o["completion"] = ans[ai].sum() / sch[ai].sum() if sch[ai].sum() else None
        o["valid_share"] = val[ai].sum() / sch[ai].sum() if sch[ai].sum() else None
        return o

    di0, si0, ai0 = np.arange(nd), np.arange(ns), np.arange(len(all_rows))
    point = stats(di0, si0, ai0)
    boots = defaultdict(list)
    if n_boot:
        rng = np.random.default_rng(seed)
        no = len(oth)
        for _ in range(n_boot):
            di = rng.integers(0, nd, nd) if nd else di0
            si = rng.integers(0, ns, ns) if ns else si0
            oi = rng.integers(0, no, no) if no else np.arange(0)
            ai = np.concatenate([di, nd + oi, nd + no + si]).astype(int)
            for k, v in stats(di, si, ai).items():
                boots[k].append(np.nan if v is None else v)
    delays = [r["delay"] for r in dec if r["detected"]]
    delays_c = [r["delay_chart"] for r in dec if r["detected_chart"]]
    out = {"n": len(rows), "n_decline": nd, "n_stable": ns,
           "stable_person_months": round(float(sd.sum()) / 30.0, 1)}
    names = {"sensitivity": "sensitivity", "chance": "chance_rate", "excess": "excess_sensitivity",
             "sensitivity_chart": "chart_sensitivity", "chance_chart": "chart_chance_rate",
             "excess_chart": "chart_excess_sensitivity", "fa": "false_alarms_per_person_month",
             "fa_chart": "chart_false_alarms_per_person_month", "spec_day": "specificity_day",
             "spec_person": "specificity_person", "spec_period": "specificity_period",
             "red_100pm": "red_alerts_per_100_person_months", "completion": "completion_rate",
             "valid_share": "valid_call_rate"}
    for k, name in names.items():
        out[name] = _r(point[k])
        out[name + "_ci"] = _ci(boots[k]) if n_boot and point[k] is not None else None
    out["median_delay_days"] = float(np.median(delays)) if delays else None
    out["delay_iqr"] = [float(np.percentile(delays, 25)), float(np.percentile(delays, 75))] if delays else None
    out["chart_median_delay_days"] = float(np.median(delays_c)) if delays_c else None
    out["stable_mostly_flagged"] = sum(1 for r in sta if r["mostly_flagged"])
    out["stable_people_with_any_alarm_day"] = sum(1 for r in sta if r["stable_alarm_days"] > 0)
    out["stable_alarm_day_share"] = _r(sad.sum() / sd.sum(), 4) if sd.sum() else None
    out["stable_periods"] = int(s_pt.sum())
    out["stable_people_with_red"] = int(sum(1 for r in sta if r.get("red_alerts", 0) > 0))
    out["stable_red_alerts"] = int(s_red.sum())
    return out


def _group_order(g):
    from .synth import EDUCATION_LEVELS
    return (0, EDUCATION_LEVELS.index(g), "") if g in EDUCATION_LEVELS else (1, 0, str(g))


# ---------------------------------------------------------------------------------------------
# test-retest reliability of the per-call metrics (stable elders, adjacent weeks)
# ---------------------------------------------------------------------------------------------
def icc_2_1(y: np.ndarray) -> float | None:
    """ICC(2,1): two-way random effects, absolute agreement, single measurement (Shrout & Fleiss 1979).
    ``y`` = n subjects x k occasions, no missing values. None if undefined (n < 3 or no variance)."""
    y = np.asarray(y, dtype=float)
    n, k = y.shape
    if n < 3 or k < 2:
        return None
    gm = y.mean()
    ssr = k * ((y.mean(axis=1) - gm) ** 2).sum()
    ssc = n * ((y.mean(axis=0) - gm) ** 2).sum()
    sse = ((y - gm) ** 2).sum() - ssr - ssc
    msr, msc, mse = ssr / (n - 1), ssc / (k - 1), sse / ((n - 1) * (k - 1))
    den = msr + (k - 1) * mse + k * (msc - mse) / n
    return None if den <= 0 else float((msr - mse) / den)


def _weekly(cohort, cfg):
    """{metric: (mean[people, weeks], first[people, weeks])} for stable elders' monitored weeks (NaN = too few calls)."""
    stable = [p for p in cohort if not (p.get("truth") or {}).get("decline")]
    days = max((len(p["records"]) for p in stable), default=0)
    n_weeks = max(0, (days - cfg.baseline_days) // 7)
    out = {}
    for m in cfg.metrics:
        mean = np.full((len(stable), n_weeks), np.nan)
        first = np.full((len(stable), n_weeks), np.nan)
        for i, p in enumerate(stable):
            for w in range(n_weeks):
                lo = cfg.baseline_days + 1 + 7 * w
                v = [float(r[m]) for r in p["records"] if lo <= r["day"] < lo + 7 and r.get("answered")
                     and r.get("valid") and r.get(m) is not None]
                if v:
                    first[i, w] = v[0]
                if len(v) >= RELIABILITY_MIN_CALLS:
                    mean[i, w] = float(np.mean(v))
        out[m] = (mean, first)
    return out, len(stable), n_weeks


def _mean_pair_icc(a: np.ndarray) -> float | None:
    vals = []
    for w in range(a.shape[1] - 1):
        y = a[:, w:w + 2]
        y = y[~np.isnan(y).any(axis=1)]
        v = icc_2_1(y)
        if v is not None:
            vals.append(v)
    return float(np.mean(vals)) if vals else None


def retest_reliability(cohort, cfg: ControlConfig | None = None, n_boot: int = 1000, seed: int = 0) -> dict:
    """Per-metric ICC(2,1) between adjacent monitored weeks on stable elders (weekly mean and single call), mean over
    all adjacent week pairs, with a bootstrap over people. Simulated: reflects the generator's assumptions."""
    cfg = cfg or ControlConfig()
    weekly, n, n_weeks = _weekly(cohort, cfg)
    out = {"n_stable": n, "weeks": n_weeks, "pairs": max(0, n_weeks - 1), "min_calls_per_week": RELIABILITY_MIN_CALLS,
           "method": "ICC(2,1) between adjacent monitored weeks, stable elders, mean over week pairs", "metrics": {}}
    rng = np.random.default_rng(seed)
    idx = [rng.integers(0, n, n) for _ in range(n_boot)] if n and n_boot else []
    for m, (mean, first) in weekly.items():
        res = {}
        for name, a in (("weekly_mean", mean), ("single_call", first)):
            point = _mean_pair_icc(a) if n else None
            boots = [_mean_pair_icc(a[ix]) for ix in idx] if point is not None else []
            res[name] = _r(point)
            res[name + "_ci"] = _ci([np.nan if b is None else b for b in boots]) if boots else None
        out["metrics"][m] = res
    return out


# ---------------------------------------------------------------------------------------------
# subgroups under an assumed level effect (education -> MATTR, age -> speech rate)
# ---------------------------------------------------------------------------------------------
LEVEL_KEYS = ("sensitivity", "excess_sensitivity", "false_alarms_per_person_month", "specificity_day",
              "specificity_period", "red_alerts_per_100_person_months")


def level_effect_check(cohort, cfg: ControlConfig | None = None, n_boot: int = 1000, seed: int = 0,
                       window: int = WINDOW_DAYS) -> dict:
    """Personal baseline vs population norm by education and age band on a cohort generated with
    ``generate_cohort(level_effects=True)``. Only LEVEL_KEYS (with intervals) are kept."""
    cfg = cfg or ControlConfig()
    pop = population_baseline(cohort, cfg)
    scored = {"personal": _score(cohort, cfg, window),
              "population": _score(cohort, ControlConfig(**{**cfg.__dict__, "population_baseline": pop}), window)}
    out = {}
    for key, field in (("by_education", "education"), ("by_age_band", "age_band")):
        out[key] = {}
        for base, rows in scored.items():
            groups = defaultdict(list)
            for r in rows:
                groups[r[field]].append(r)
            out[key][base] = {}
            for g, v in sorted(groups.items(), key=lambda kv: _group_order(kv[0])):
                sm = _summ(v, n_boot=n_boot, seed=seed, window=window)
                out[key][base][g] = {"n": sm["n"], "n_stable": sm["n_stable"],
                                     **{k: sm[k] for k in LEVEL_KEYS}, **{k + "_ci": sm[k + "_ci"] for k in LEVEL_KEYS}}
    return out


def _cfg_at(cfg: ControlConfig, L: float, pop: dict | None = None) -> ControlConfig:
    return ControlConfig(**{**cfg.__dict__, "L_yellow": float(L), "L_red": float(L) + RED_GAP,
                            "population_baseline": pop})


def run_evaluation(cohort: list[dict], cfg=None, n_boot: int = 1000, seed: int = 0,
                   window: int = WINDOW_DAYS) -> dict:
    """Score the light on one cohort from ``synth.generate_cohort``. Returns a JSON-serialisable report."""
    cfg = cfg or ControlConfig()
    rows = _score(cohort, cfg, window)
    report = {"disclaimer": DISCLAIMER, "simulated": True,
              "definition": "attributed (channel-matched rule, alarm starts within "
                            f"{window} days after onset), chance-corrected with pseudo-onsets on stable elders",
              "window_days": window,
              "matching_rules": {k: sorted(v) for k, v in MATCHING_RULES.items()},
              "config": {k: v for k, v in cfg.__dict__.items() if k not in ("population_baseline",)},
              "days": max((len(p["records"]) for p in cohort), default=0)}
    report["config"]["metrics"] = list(cfg.metrics)
    S = lambda rs, **kw: _summ(rs, n_boot=n_boot, seed=seed, window=window, **kw)  # noqa: E731
    report["overall"] = S(rows)
    report["operational"] = S(rows, types=OPERATIONAL_TYPES)
    report["by_decline_type"] = {t: S([r for r in rows if r["type"] in (t, "stable")], types=(t,))
                                 for t in CLINICAL_TYPES + OPERATIONAL_TYPES}
    for key, field in (("by_dialect", "dialect"), ("by_channel", "channel"), ("by_age_band", "age_band"),
                       ("by_education", "education")):
        groups = defaultdict(list)
        for r in rows:
            groups[r[field]].append(r)
        report[key] = {g: S(v) for g, v in sorted(groups.items(), key=lambda kv: _group_order(kv[0]))}
    report["reliability"] = retest_reliability(cohort, cfg, n_boot=n_boot, seed=seed)
    det_codes, fa_codes = defaultdict(int), defaultdict(int)
    for r in rows:
        for c in r["det_codes"]:
            det_codes[c] += 1
        for c in r["fa_codes"]:
            fa_codes[c] += 1
    report["detection_rule_counts"] = dict(sorted(det_codes.items()))
    report["false_alarm_rule_counts"] = dict(sorted(fa_codes.items()))

    # ---- ablation: population norm instead of personal baseline --------------------------
    pop = population_baseline(cohort, cfg)
    prow = _score(cohort, ControlConfig(**{**cfg.__dict__, "population_baseline": pop}), window)
    report["ablation"] = {
        "description": ("Same rules, thresholds and corrected detection definition; personal = each person's own "
                        "21-day baseline, population = one pooled norm (median / 1.4826*MAD over all "
                        "baseline-period calls)."),
        "population_norm": {m: {"center": round(v["center"], 4), "scale": round(v["scale"], 4)} for m, v in pop.items()},
        "personal": report["overall"],
        "population": S(prow),
        "personal_by_type": {t: report["by_decline_type"][t] for t in CLINICAL_TYPES},
        "population_by_type": {t: S([r for r in prow if r["type"] in (t, "stable")], types=(t,))
                               for t in CLINICAL_TYPES},
    }
    report["ablation"]["personal_detail"] = {k: report["overall"][k] for k in
                                             ("stable_people_with_any_alarm_day", "stable_alarm_day_share")}
    report["ablation"]["population_detail"] = {k: report["ablation"]["population"][k] for k in
                                               ("stable_people_with_any_alarm_day", "stable_alarm_day_share")}
    report["persons"] = [{k: v for k, v in r.items() if k != "events"} for r in rows]
    report["markdown"] = report_md(report)
    return report


# ---------------------------------------------------------------------------------------------
# operating curve + hold-out
# ---------------------------------------------------------------------------------------------
CURVE_FIELDS = ("sensitivity", "chance_rate", "excess_sensitivity", "chart_sensitivity", "chart_chance_rate",
                "chart_excess_sensitivity", "false_alarms_per_person_month", "chart_false_alarms_per_person_month",
                "specificity_day")


def operating_curve(cohort, cfg=None, grid=L_GRID, n_boot: int = 0, seed: int = 0, window=WINDOW_DAYS) -> list[dict]:
    """Sensitivity vs false alarms across L_yellow (L_red = L_yellow + 1) for personal and population baselines."""
    cfg = cfg or ControlConfig()
    pop = population_baseline(cohort, cfg)
    out = []
    for base, norm in (("personal", None), ("population", pop)):
        for L in grid:
            s = _summ(_score(cohort, _cfg_at(cfg, L, norm), window), n_boot=n_boot, seed=seed, window=window)
            out.append({"baseline": base, "L_yellow": float(L), "L_red": float(L) + RED_GAP,
                        **{k: s[k] for k in CURVE_FIELDS}})
    return out


def select_threshold(curve: list[dict], budget: float = FA_BUDGET) -> float:
    """Pre-stated rule: on the personal-baseline curve, the L_yellow with the highest excess (chance-corrected)
    clinical sensitivity among those with <= ``budget`` all-rule false alarms per person-month; ties -> higher L."""
    pers = [r for r in curve if r["baseline"] == "personal"]
    ok = [r for r in pers if r["false_alarms_per_person_month"] <= budget] or \
        [min(pers, key=lambda r: r["false_alarms_per_person_month"])]
    return max(ok, key=lambda r: (round(r["excess_sensitivity"], 3), r["L_yellow"]))["L_yellow"]


def run_holdout(dev_cohort, test_cohort, cfg=None, grid=L_GRID, n_boot: int = 1000, seed: int = 0,
                budget: float = FA_BUDGET, window=WINDOW_DAYS, dev_seed=None, test_seed=None) -> dict:
    """Choose L_yellow on ``dev_cohort``; report everything on ``test_cohort`` at that threshold."""
    cfg = cfg or ControlConfig()
    dev_curve = operating_curve(dev_cohort, cfg, grid, window=window)
    L = select_threshold(dev_curve, budget)
    test_curve = operating_curve(test_cohort, cfg, grid, window=window)
    rep = run_evaluation(test_cohort, _cfg_at(cfg, L), n_boot=n_boot, seed=seed, window=window)
    rep["holdout"] = {
        "dev_seed": dev_seed, "test_seed": test_seed, "dev_n": len(dev_cohort), "test_n": len(test_cohort),
        "selection_rule": (f"highest excess (chance-corrected) clinical sensitivity on the development cohort with "
                           f"<= {budget} all-rule false alarms per person-month; L_red = L_yellow + {RED_GAP}"),
        "fa_budget": budget, "grid": list(grid), "chosen_L_yellow": L, "chosen_L_red": L + RED_GAP,
        "default_L_yellow": cfg.L_yellow, "default_L_red": cfg.L_red,
        "dev_at_chosen": next(r for r in dev_curve if r["baseline"] == "personal" and r["L_yellow"] == L),
    }
    rep["operating_curve"] = {"dev": dev_curve, "test": test_curve}
    if L != cfg.L_yellow:  # the shipped default, on the same held-out cohort, with intervals
        rep["holdout"]["at_default"] = _summ(_score(test_cohort, cfg, window), n_boot=n_boot, seed=seed,
                                             window=window)
    rep["markdown"] = report_md(rep)
    return rep


def write_curve_csv(report: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(("cohort", "baseline", "L_yellow", "L_red") + CURVE_FIELDS)
        for coh in ("dev", "test"):
            for r in report["operating_curve"][coh]:
                w.writerow([("development" if coh == "dev" else "held-out"), r["baseline"], r["L_yellow"], r["L_red"]]
                           + [r[k] for k in CURVE_FIELDS])


def curve_svg(report: dict) -> str:
    """Two-panel operating curve (held-out cohort) as a self-contained SVG (no plotting dependency)."""
    curve = report["operating_curve"]["test"]
    chosen = report["holdout"]["chosen_L_yellow"]
    W, H, pad_l, pad_r, pad_t, pad_b, gap = 860, 410, 56, 16, 80, 52, 64
    pw = (W - pad_l - pad_r - gap) / 2
    ph = H - pad_t - pad_b
    col = {"personal": "#1f6feb", "population": "#c2410c"}
    panels = [("Clinical declines, channel-matched rules", "false_alarms_per_person_month", "sensitivity",
               "chance_rate", "False alarms per person-month (all rules)"),
              ("Speech/recall control chart only", "chart_false_alarms_per_person_month", "chart_sensitivity",
               "chart_chance_rate", "Chart false alarms per person-month")]
    xmax = max(max(r[p[1]] for r in curve) for p in panels)
    xmax = float(np.ceil(xmax * 4) / 4) or 1.0
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
         'font-family="Helvetica, Arial, sans-serif" font-size="11">',
         f'<rect width="{W}" height="{H}" fill="#ffffff"/>',
         f'<text x="{pad_l}" y="18" font-size="13" font-weight="bold">Operating curve, held-out simulated cohort '
         f'(L_yellow {curve[0]["L_yellow"]}–{curve[-1]["L_yellow"]}; L_red = L_yellow + {RED_GAP})</text>',
         f'<text x="{pad_l}" y="36" fill="#555">Solid = attributed sensitivity; dashed = chance rate from '
         f'pseudo-onsets on stable elders (same attribution rule, no decline).</text>',
         f'<text x="{pad_l}" y="51" fill="#555">Point labels = L_yellow. Ring = L_yellow {chosen}, chosen on the '
         f'development cohort. {DISCLAIMER}</text>']
    for k, (title, xk, yk, ck, xlabel) in enumerate(panels):
        x0 = pad_l + k * (pw + gap)
        X = lambda v: x0 + pw * min(v, xmax) / xmax  # noqa: E731
        Y = lambda v: pad_t + ph * (1 - v)  # noqa: E731
        s.append(f'<text x="{x0}" y="{pad_t - 6}" font-weight="bold">{title}</text>')
        for t in np.linspace(0, 1, 6):
            s.append(f'<line x1="{x0:.1f}" x2="{x0 + pw:.1f}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" stroke="#e5e7eb"/>')
            s.append(f'<text x="{x0 - 6:.1f}" y="{Y(t) + 4:.1f}" text-anchor="end">{int(round(t * 100))}%</text>')
        for t in np.arange(0, xmax + 1e-9, 0.25):
            s.append(f'<line x1="{X(t):.1f}" x2="{X(t):.1f}" y1="{pad_t}" y2="{pad_t + ph}" stroke="#f1f5f9"/>')
            s.append(f'<text x="{X(t):.1f}" y="{pad_t + ph + 14}" text-anchor="middle">{t:.2f}</text>')
        s.append(f'<rect x="{x0:.1f}" y="{pad_t}" width="{pw:.1f}" height="{ph}" fill="none" stroke="#9ca3af"/>')
        s.append(f'<text x="{x0 + pw / 2:.1f}" y="{H - 14}" text-anchor="middle">{xlabel}</text>')
        for base in ("personal", "population"):
            pts = [r for r in curve if r["baseline"] == base]
            line = " ".join(f"{X(r[xk]):.1f},{Y(r[yk]):.1f}" for r in pts)
            cl = " ".join(f"{X(r[xk]):.1f},{Y(r[ck]):.1f}" for r in pts)
            s.append(f'<polyline points="{line}" fill="none" stroke="{col[base]}" stroke-width="2"/>')
            s.append(f'<polyline points="{cl}" fill="none" stroke="{col[base]}" stroke-width="1.2" '
                     'stroke-dasharray="4 3" opacity="0.8"/>')
            for r in pts:
                s.append(f'<circle cx="{X(r[xk]):.1f}" cy="{Y(r[yk]):.1f}" r="3" fill="{col[base]}"/>')
                if base == "personal":
                    s.append(f'<text x="{X(r[xk]) + 5:.1f}" y="{Y(r[yk]) - 5:.1f}" fill="#374151" '
                             f'font-size="9">{r["L_yellow"]}</text>')
                if r["L_yellow"] == chosen:
                    s.append(f'<circle cx="{X(r[xk]):.1f}" cy="{Y(r[yk]):.1f}" r="7" fill="none" '
                             f'stroke="{col[base]}" stroke-width="1.5"/>')
        ly = pad_t + ph - 34
        for i, base in enumerate(("personal", "population")):
            s.append(f'<line x1="{x0 + pw - 150:.1f}" x2="{x0 + pw - 130:.1f}" y1="{ly + 14 * i}" y2="{ly + 14 * i}" '
                     f'stroke="{col[base]}" stroke-width="2"/>')
            s.append(f'<text x="{x0 + pw - 125:.1f}" y="{ly + 14 * i + 4}">{base} baseline</text>')
    s.append("</svg>")
    return "\n".join(s) + "\n"


# ---------------------------------------------------------------------------------------------
# markdown
# ---------------------------------------------------------------------------------------------
def _pct(x):
    return "n/a" if x is None else f"{100 * x:.1f}%"


def _pci(s, k):
    """'61.2% (95% CI 52.0–70.1)'."""
    v, ci = s.get(k), s.get(k + "_ci")
    if v is None:
        return "n/a"
    return _pct(v) + (f" ({100 * ci[0]:.1f}–{100 * ci[1]:.1f})" if ci else "")


def _nci(s, k):
    v, ci = s.get(k), s.get(k + "_ci")
    if v is None:
        return "n/a"
    return f"{v:.2f}" + (f" ({ci[0]:.2f}–{ci[1]:.2f})" if ci else "")


HDR = ("| Group | N | N clinical decline | Attributed sensitivity | Chance rate | Excess (chance-corrected) | "
       "Chart-only sensitivity | Median delay (d) | False alarms / person-month |\n|---|---|---|---|---|---|---|---|---|")


def _row(name, s):
    d = "n/a" if s["median_delay_days"] is None else f"{s['median_delay_days']:.0f}"
    return (f"| {name} | {s['n']} | {s['n_decline']} | {_pci(s, 'sensitivity')} | {_pci(s, 'chance_rate')} | "
            f"{_pci(s, 'excess_sensitivity')} | {_pci(s, 'chart_sensitivity')} | {d} | "
            f"{_nci(s, 'false_alarms_per_person_month')} |")


def report_md(report: dict) -> str:
    o = report["overall"]
    op = report["operational"]
    cfg = report["config"]
    ho = report.get("holdout")
    W = report["window_days"]
    lines = [
        "# Chào Bà – detection evaluation",
        "",
        f"> **{DISCLAIMER}** All numbers below come from a synthetic cohort generated by `chaoba.core.synth` "
        "(AR(1) noise, weekday effects, missed/invalid calls, injected declines). They show how the pipeline "
        "behaves under stated assumptions; they are not evidence of clinical accuracy.",
        "",
    ]
    if ho:
        lines += [
            f"Held-out cohort (seed {ho['test_seed']}): {ho['test_n']} simulated elders × {report['days']} days; "
            f"{o['n_decline']} with a clinical-type injected decline, {op['n_decline']} with a missed-calls decline, "
            f"{o['n_stable']} stable. The alert threshold L_yellow = **{ho['chosen_L_yellow']}** "
            f"(L_red {ho['chosen_L_red']}) was chosen on a separate development cohort (seed {ho['dev_seed']}, "
            f"n = {ho['dev_n']}) and not re-tuned here. Baseline = first {cfg['baseline_days']} days. "
            "Brackets are 95 % bootstrap intervals over people.",
            "",
        ]
    else:
        lines += [f"Cohort: {o['n']} simulated elders × {report['days']} days. Brackets are 95 % bootstrap "
                  "intervals over people.", ""]
    lines += [
        "## Headline (held-out, corrected definition)" if ho else "## Headline (corrected definition)",
        "",
        f"- **Attributed sensitivity, clinical declines** (cognitive drift, frailty/symptoms, mood/withdrawal; "
        f"a channel-matched rule must start an alarm within {W} days after onset): **{_pci(o, 'sensitivity')}**.",
        f"- **Chance rate** (same rule on stable elders at pseudo-onsets): {_pci(o, 'chance_rate')}. "
        f"**Excess (chance-corrected) sensitivity: {_pci(o, 'excess_sensitivity')}**.",
        f"- **Speech/recall control chart alone**: sensitivity {_pci(o, 'chart_sensitivity')}, chance "
        f"{_pci(o, 'chart_chance_rate')}, excess **{_pci(o, 'chart_excess_sensitivity')}**.",
        f"- **Median delay** (attributed detections): {o['median_delay_days']:.0f} days after onset "
        f"(IQR {o['delay_iqr'][0]:.0f}–{o['delay_iqr'][1]:.0f})." if o["delay_iqr"] else "- Median delay: n/a.",
        f"- **False alarms**: {_nci(o, 'false_alarms_per_person_month')} alarm episodes per person-month of stable "
        f"monitoring (all rules), of which the control chart starts {_nci(o, 'chart_false_alarms_per_person_month')}; "
        f"day-level specificity {_pci(o, 'specificity_day')}; {_pci(o, 'specificity_person')} of stable elders "
        f"never alerted in {report['days'] - cfg['baseline_days']} monitored days.",
        *([f"- **Stable 30-day periods with no yellow/red day**: {_pci(o, 'specificity_period')}; **false-referral "
           f"burden** (red alerts sent to qualified review for stable elders): "
           f"{_nci(o, 'red_alerts_per_100_person_months')} per 100 person-months. Details below."]
          if o.get("specificity_period") is not None else []),
        *([f"- **At the shipped default L_yellow {ho['default_L_yellow']} / L_red {ho['default_L_red']}** (same held-out "
            f"cohort): sensitivity {_pci(ho['at_default'], 'sensitivity')}, chance {_pci(ho['at_default'], 'chance_rate')}, "
            f"excess {_pci(ho['at_default'], 'excess_sensitivity')}, chart-only excess "
            f"{_pci(ho['at_default'], 'chart_excess_sensitivity')}, false alarms "
            f"{_nci(ho['at_default'], 'false_alarms_per_person_month')} per person-month."]
          if ho and ho.get("at_default") else []),
        f"- **Operational check, not clinical** (missed-calls declines flagged by the `unanswered` rule, which is "
        f"close to circular): {_pci(op, 'sensitivity')}, chance {_pci(op, 'chance_rate')}.",
        "",
        "**Definition change.** An earlier version of this report counted *any* alarm from *any* rule that started "
        "on or after the onset day, with no time limit, and pooled missed-calls declines (detected by the "
        "unanswered-calls rule, which is nearly circular) into the headline. It reported 92.0 % sensitivity. A null "
        "test (stable elders given pseudo-onsets from the real onset distribution) showed that this definition "
        "scored about 46 % \"detection\" with no decline at all, and only 40 of 88 detections began with a "
        "control-chart rule. Corrected: a detection must be started by a rule matching the decline's channel within "
        f"{W} days of onset, the chance rate from pseudo-onsets is reported next to it, missed-calls declines are "
        "reported separately as an operational check, the threshold is chosen on a development cohort and "
        "reported on a held-out cohort, and every number carries a bootstrap interval.",
        "",
    ]
    if ho:
        d = ho["dev_at_chosen"]
        lines += [
            "## Threshold choice and operating curve",
            "",
            f"Selection rule (fixed before the held-out cohort was scored): {ho['selection_rule']}. "
            f"On the development cohort L_yellow = {ho['chosen_L_yellow']} gave attributed sensitivity "
            f"{_pct(d['sensitivity'])}, chance {_pct(d['chance_rate'])}, excess {_pct(d['excess_sensitivity'])}, "
            f"{d['false_alarms_per_person_month']:.2f} false alarms per person-month. The control chart's shipped "
            f"default is L_yellow = {ho['default_L_yellow']}"
            + ("." if ho['chosen_L_yellow'] == ho['default_L_yellow'] else
               f" (set earlier under the uncorrected definition); the corrected analysis favours "
               f"{ho['chosen_L_yellow']}: fewer false alarms and a higher chance-corrected sensitivity."),
            "",
            "![Operating curve](operating_curve.svg)",
            "",
            "Held-out cohort, by L_yellow (L_red = L_yellow + 1). Full table incl. development cohort: "
            "`operating_curve.csv`.",
            "",
            "| Baseline | L_yellow | Sensitivity | Chance | Excess | Chart-only sens. | Chart chance | "
            "False alarms / p-m (all) | Chart false alarms / p-m |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for r in report["operating_curve"]["test"]:
            lines.append(f"| {r['baseline']} | {r['L_yellow']} | {_pct(r['sensitivity'])} | {_pct(r['chance_rate'])} | "
                         f"{_pct(r['excess_sensitivity'])} | {_pct(r['chart_sensitivity'])} | "
                         f"{_pct(r['chart_chance_rate'])} | {r['false_alarms_per_person_month']:.2f} | "
                         f"{r['chart_false_alarms_per_person_month']:.2f} |")
        lines.append("")
    lines += ["## By decline type", "", HDR]
    for g, s in report["by_decline_type"].items():
        lines.append(_row(g + (" (operational)" if g in OPERATIONAL_TYPES else ""), s))
    lines += ["", "False-alarm column per type = stable elders plus that type's pre-onset days; chance rate per type uses that type's onsets and matching rules.", ""]
    lines += ["## By dialect (clinical declines)", "", HDR] + [_row(g, s) for g, s in report["by_dialect"].items()]
    lines += ["", "## By channel (clinical declines)", "", HDR] + [_row(g, s) for g, s in report["by_channel"].items()]
    if report.get("by_age_band"):
        lines += ["", "## By age band (clinical declines)", "", HDR] + [_row(g, s) for g, s in report["by_age_band"].items()]
    if report.get("by_education"):
        lines += ["", "## By education (clinical declines)", "", HDR] + [_row(g, s) for g, s in report["by_education"].items()]
        lines += ["", "Age is drawn as before (62–89); education (low = none/primary, mid = secondary, high = post-secondary; "
                  "illustrative 45/40/15 % mix) comes from its own random stream, so adding it left every other number "
                  "unchanged. In this cohort neither has any effect on the signals (no effect is assumed); see "
                  "\"Age and education with an assumed level effect\" below for a version that adds one."]
    ab = report["ablation"]
    p, q = ab["personal"], ab["population"]
    lines += [
        "", "Subgroup intervals are wide (few people per cell); differences between them are not significant.", "",
        "## Personal baseline vs population norm", "",
        ab["description"], "",
        "| Baseline | Attributed sensitivity | Chance | Excess | Chart-only excess | False alarms / p-m | "
        "Specificity (day) |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, s in (("Personal (Chào Bà)", p), ("Population norm", q)):
        lines.append(f"| {name} | {_pci(s, 'sensitivity')} | {_pci(s, 'chance_rate')} | {_pci(s, 'excess_sensitivity')} | "
                     f"{_pci(s, 'chart_excess_sensitivity')} | {_nci(s, 'false_alarms_per_person_month')} | "
                     f"{_pci(s, 'specificity_day')} |")
    lines += [
        "",
        f"Stable elders shown yellow/red on more than half of their monitored days: personal "
        f"**{p['stable_mostly_flagged']}**, population norm **{q['stable_mostly_flagged']}** (of {p['n_stable']}). "
        f"Share of stable monitored days shown yellow/red: personal {_pct(p['stable_alarm_day_share'])}, population "
        f"{_pct(q['stable_alarm_day_share'])}. A person already in alarm before onset cannot produce a new "
        "attributed alarm, so a population norm both raises the chance rate and hides real declines.",
        "",
        "| Decline type | Excess sens. – personal | Excess sens. – population |",
        "|---|---|---|",
    ]
    for g in ab["personal_by_type"]:
        lines.append(f"| {g} | {_pci(ab['personal_by_type'][g], 'excess_sensitivity')} | "
                     f"{_pci(ab['population_by_type'][g], 'excess_sensitivity')} |")
    lines += [
        "",
        "## Which rules fired",
        "",
        "| Rule | Started an attributed detection | False-alarm episodes (start-day rules) |", "|---|---|---|",
    ]
    codes = sorted(set(report["detection_rule_counts"]) | set(report["false_alarm_rule_counts"]))
    for c in codes:
        lines.append(f"| `{c}` | {report['detection_rule_counts'].get(c, 0)} | {report['false_alarm_rule_counts'].get(c, 0)} |")
    lines += _safety_md(report)
    mr = report["matching_rules"]
    lines += [
        "", "## Method", "",
        f"- Personal baseline: first {cfg['baseline_days']} days (≥{cfg['min_valid']} valid calls), center = median, "
        "scale = 1.4826×MAD with a per-metric floor (recall 0–3 is discrete: mean / SD). The scale is inflated "
        f"(k≈1.45) for serial correlation (assumed φ={cfg['assumed_phi']}) and baseline-estimation uncertainty.",
        f"- EWMA λ = {cfg['lam']} on signed z (positive = worse); limits in EWMA-sigma units: yellow {cfg['L_yellow']}, "
        f"red {cfg['L_red']}; yellow after {cfg['yellow_days']} consecutive days, red after {cfg['red_days']}; "
        f"a light steps down only after {cfg['recover_days']} better days.",
        "- Event rules: same symptom ≥2× in 7 days (yellow), ≥3 distinct symptoms in 7 days or a fall (red), "
        "2 / 3 consecutive unanswered days (yellow / red), mood ≤2 on ≥3 of 7 days (yellow).",
        f"- Attributed detection: the first day within [onset, onset + {W}] (truncated at end of follow-up) on which a "
        "matching rule starts driving a yellow/red light (it was not active the day before; an alarm already running "
        "at onset does not count). Matching rules: "
        + "; ".join(f"{k} → {', '.join(f'`{c}`' for c in v)}" for k, v in mr.items()) + ".",
        "- Chance rate: for every (stable elder, decline elder) pair, the stable elder's lights are scored with the "
        "decline elder's onset day and decline type; the mean over pairs is the expected 'detection' rate without "
        "any decline. Excess sensitivity = sensitivity − chance rate.",
        "- False alarms: alarm episodes (any rule) starting on stable monitored person-days; chart false alarms: "
        "control-chart rule starts on those days. 95 % intervals: percentile bootstrap (1 000 resamples, people "
        "resampled within clinical-decline / missed-calls-decline / stable strata, fixed seed).",
        "",
        f"_{DISCLAIMER}_",
    ]
    return "\n".join(lines) + "\n"


METRIC_LABEL = {"speech_rate_sps": "Speech rate", "pause_ratio": "Pause ratio", "filled_pause_rate": "Filler rate",
                "mattr": "Vocabulary variety (MATTR)", "recall_score": "Story recall (0–3)"}


def _ici(s, k):
    v, ci = s.get(k), s.get(k + "_ci")
    if v is None:
        return "n/a"
    return f"{v:.2f}" + (f" ({ci[0]:.2f}–{ci[1]:.2f})" if ci else "")


def _safety_md(report: dict) -> list[str]:
    """Specificity per period, completion, false-referral burden, test-retest reliability, level-effect check."""
    o = report["overall"]
    if o.get("specificity_period") is None:
        return []
    lines = [
        "", "## Specificity, completion and review burden (stable elders)", "",
        f"Stable elders = the {o['n_stable']} with no injected decline; monitored = after the {report['config']['baseline_days']}-day "
        "baseline. Brackets are 95 % bootstrap intervals over people.", "",
        "| Measure | Definition | Value |", "|---|---|---|",
        f"| Specificity per 30-day period | complete 30-day blocks of monitoring ({o['stable_periods']} blocks) with no "
        f"yellow or red day | {_pci(o, 'specificity_period')} |",
        f"| Specificity per person | stable elders never alerted in {report['days'] - report['config']['baseline_days']} "
        f"monitored days | {_pci(o, 'specificity_person')} |",
        f"| Specificity per day | stable monitored days not yellow/red | {_pci(o, 'specificity_day')} |",
        f"| False-referral burden | red-alert starts on stable elders per 100 person-months ({o['stable_red_alerts']} "
        f"red alerts; {o['stable_people_with_red']} of {o['n_stable']} stable elders had at least one) | "
        f"{_nci(o, 'red_alerts_per_100_person_months')} |",
        f"| Completion | scheduled daily calls answered (all {o['n']} elders) | {_pci(o, 'completion_rate')} |",
        f"| Valid calls | answered and long enough to measure | {_pci(o, 'valid_call_rate')} |",
        "",
        "Every red alert waits for a qualified person (clinician or health-station staff) to review it, so the "
        "false-referral burden is the review workload created by people whose signals did not really change. Whether "
        "a review becomes a referral is a human decision this simulation does not model. Completion and valid-call "
        "rates are set by the generator's assumed miss and short-call rates (about 1–6 % and 3–5 %); they check the "
        "bookkeeping, not real-world uptake. Time to clinical assessment cannot be measured on simulated data.",
    ]
    by = [(g, s) for key in ("by_age_band", "by_education", "by_dialect", "by_channel")
          for g, s in (report.get(key) or {}).items()]
    if by:
        lines += ["", "| Group | N stable | Specificity / 30-day period | Red alerts / 100 p-m (stable) | Completion |",
                  "|---|---|---|---|---|"]
        lines += [f"| {g} | {s['n_stable']} | {_pci(s, 'specificity_period')} | "
                  f"{_nci(s, 'red_alerts_per_100_person_months')} | {_pci(s, 'completion_rate')} |" for g, s in by]
    rel = report.get("reliability")
    if rel and rel.get("metrics"):
        lines += [
            "", "## Test–retest reliability of the per-call signals (stable elders)", "",
            f"ICC(2,1) (two-way random effects, absolute agreement, single measurement) between adjacent monitored "
            f"weeks, averaged over {rel['pairs']} week pairs, {rel['n_stable']} stable elders. *Weekly mean* = mean of "
            f"the week's valid calls (≥ {rel['min_calls_per_week']}); *single call* = the first valid call of the week.",
            "", "| Signal | ICC, weekly mean | ICC, single call |", "|---|---|---|",
        ]
        lines += [f"| {METRIC_LABEL.get(m, m)} | {_ici(v, 'weekly_mean')} | {_ici(v, 'single_call')} |"
                  for m, v in rel["metrics"].items()]
        lines += [
            "",
            "These values mirror the generator's assumptions (between-person spread of usual levels versus assumed "
            "day-to-day noise), so they show what reliability those assumptions imply, not what real calls achieve. "
            "Story recall has no person-specific usual level in the generator (every simulated person recalls around "
            "the same 2.85 of 3), so its ICC is near zero by construction: its reliability cannot be judged from this "
            "simulation. Real test–retest reliability must be measured in the pilot.",
        ]
    le = report.get("level_effect")
    if le:
        lines += [
            "", "## Age and education with an assumed level effect", "",
            f"Same held-out seed, regenerated with `generate_cohort(level_effects=True)`: usual vocabulary variety "
            f"(MATTR) {le['assumption']['education']}, and usual speech rate {le['assumption']['age']}. "
            "These are **simulation assumptions** (sized below the between-person spread already in the generator), "
            "not measured effects; every random draw is identical to the main cohort. A level effect moves a person's "
            "usual level, which a personal baseline absorbs and a population norm does not.", "",
            "| Group | Baseline | N stable | Sensitivity | Excess | False alarms / p-m | Specificity / 30-day period | "
            "Red alerts / 100 p-m |", "|---|---|---|---|---|---|---|---|",
        ]
        for key in ("by_education", "by_age_band"):
            for base in ("personal", "population"):
                for g, v in le[key][base].items():
                    lines.append(f"| {g} | {base} | {v['n_stable']} | {_pci(v, 'sensitivity')} | "
                                 f"{_pci(v, 'excess_sensitivity')} | {_nci(v, 'false_alarms_per_person_month')} | "
                                 f"{_pci(v, 'specificity_period')} | {_nci(v, 'red_alerts_per_100_person_months')} |")
    return lines


def write_report(report: dict, json_path: str, md_path: str) -> None:
    rep = {k: v for k, v in report.items() if k != "markdown"}
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(report.get("markdown") or report_md(report))
