"""Evaluation of the daily light on a simulated cohort (NOT clinical validation).

Definitions (person = one simulated elder, monitored day = baseline ready):

* **Alarm episode** - a maximal run of consecutive yellow/red days; its start day is the alert day.
* **Sensitivity** - share of decline elders with an episode starting on/after the true onset day
  (within follow-up). ``sensitivity_30d`` additionally requires detection within 30 days of onset.
* **Detection delay** - first episode start >= onset minus onset (days); median and IQR reported.
* **False alarms** - episodes starting on stable person-days (all monitored days of stable elders +
  monitored pre-onset days of decline elders); rate per person-month (30 monitored days).
* **Specificity** - person-level: share of stable elders with no alarm episode in follow-up;
  day-level: share of stable monitored days that are not yellow/red.
* **Ablation** - same rules, but every person is judged against a *population norm* (pooled median /
  MAD of all baseline-period values) instead of their own baseline.
"""
from __future__ import annotations

import json
from collections import defaultdict

import numpy as np

from .control_chart import DISCRETE, ControlConfig, _as_record, _robust, evaluate_series
from .models import METRICS

DISCLAIMER = "Simulated cohort - not clinical validation."
METRIC_CODES = {"metric_trend", "metric_shift", "multi_metric"}


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


def _score(cohort, cfg):
    rows = []
    for p in cohort:
        recs = [_as_record(r) for r in p["records"]]
        lights = evaluate_series(recs, cfg)
        truth = p.get("truth", {"decline": False, "onset_day": None, "type": "stable"})
        onset = truth.get("onset_day") if truth.get("decline") else None
        eps = _episodes(lights)
        mon = [l for l in lights if l.baseline_ready]
        stable_days = [l for l in mon if onset is None or l.day < onset]
        fa = [e for e in eps if (onset is None or e["start"] < onset) and e["start"] > cfg.baseline_days]
        det = next((e for e in eps if onset is not None and e["start"] >= onset), None)
        rows.append({
            "id": p["elder"]["id"], "dialect": p["elder"].get("dialect"), "channel": p["elder"].get("channel_pref"),
            "type": truth.get("type", "stable"), "decline": bool(truth.get("decline")), "onset": onset,
            "stable_days": len(stable_days),
            "stable_alarm_days": sum(1 for l in stable_days if l.light in ("yellow", "red")),
            "false_alarms": len(fa), "fa_codes": [c for e in fa for c in e["codes"]],
            "false_alarms_metric": sum(1 for e in fa if set(e["codes"]) and set(e["codes"]) <= METRIC_CODES),
            "mostly_flagged": bool(stable_days) and onset is None and
            sum(1 for l in stable_days if l.light in ("yellow", "red")) > 0.5 * len(stable_days),
            "detected": det is not None, "delay": (det["start"] - onset) if det else None,
            "det_peak": det["peak"] if det else None, "det_codes": det["codes"] if det else [],
        })
    return rows


def _summ(rows):
    dec = [r for r in rows if r["decline"]]
    sta = [r for r in rows if not r["decline"]]
    delays = [r["delay"] for r in dec if r["detected"]]
    sdays = sum(r["stable_days"] for r in rows)
    fa = sum(r["false_alarms"] for r in rows)
    out = {
        "n": len(rows), "n_decline": len(dec), "n_stable": len(sta),
        "sensitivity": round(sum(r["detected"] for r in dec) / len(dec), 3) if dec else None,
        "sensitivity_30d": round(sum(1 for r in dec if r["detected"] and r["delay"] <= 30) / len(dec), 3) if dec else None,
        "median_delay_days": float(np.median(delays)) if delays else None,
        "delay_iqr": [float(np.percentile(delays, 25)), float(np.percentile(delays, 75))] if delays else None,
        "specificity_person": round(sum(1 for r in sta if r["false_alarms"] == 0) / len(sta), 3) if sta else None,
        "specificity_day": (round(1 - sum(r["stable_alarm_days"] for r in rows) / sdays, 4) if sdays else None),
        "false_alarms_per_person_month": round(fa / (sdays / 30.0), 3) if sdays else None,
        "metric_false_alarms_per_person_month": (round(sum(r["false_alarms_metric"] for r in rows) / (sdays / 30.0), 3)
                                                 if sdays else None),
        "stable_mostly_flagged": sum(1 for r in sta if r["mostly_flagged"]),
        "stable_person_months": round(sdays / 30.0, 1),
    }
    return out


def run_evaluation(cohort: list[dict], cfg=None) -> dict:
    """Score the light on a cohort from ``synth.generate_cohort``. Returns a JSON-serialisable report."""
    cfg = cfg or ControlConfig()
    rows = _score(cohort, cfg)
    report = {"disclaimer": DISCLAIMER, "simulated": True,
              "config": {k: v for k, v in cfg.__dict__.items() if k not in ("population_baseline",)},
              "days": max((len(p["records"]) for p in cohort), default=0)}
    report["config"]["metrics"] = list(cfg.metrics)
    report["overall"] = _summ(rows)
    for key, field in (("by_decline_type", "type"), ("by_dialect", "dialect"), ("by_channel", "channel")):
        groups = defaultdict(list)
        for r in rows:
            groups[r[field]].append(r)
        report[key] = {g: _summ(v) for g, v in sorted(groups.items())}
    det_codes = defaultdict(int)
    fa_codes = defaultdict(int)
    for r in rows:
        for c in r["det_codes"]:
            det_codes[c] += 1
        for c in r["fa_codes"]:
            fa_codes[c] += 1
    report["detection_rule_counts"] = dict(sorted(det_codes.items()))
    report["false_alarm_rule_counts"] = dict(sorted(fa_codes.items()))

    # ---- ablation: population norm instead of personal baseline --------------------------
    pop = population_baseline(cohort, cfg)
    pcfg = ControlConfig(**{**cfg.__dict__, "population_baseline": pop})
    prow = _score(cohort, pcfg)
    report["ablation"] = {
        "description": ("Same rules and thresholds; personal = each person's own 21-day baseline, "
                        "population = one pooled norm (median / 1.4826*MAD over all baseline-period calls)."),
        "population_norm": {m: {"center": round(v["center"], 4), "scale": round(v["scale"], 4)} for m, v in pop.items()},
        "personal": report["overall"],
        "population": _summ(prow),
        "personal_by_type": report["by_decline_type"],
        "population_by_type": {g: _summ([r for r in prow if r["type"] == g]) for g in sorted({r["type"] for r in prow})},
    }
    # metric-signal-only comparison (fraction of detections / false alarms driven by metric rules)
    def metric_only(rs):
        dec = [r for r in rs if r["decline"]]
        sta_days = sum(r["stable_days"] for r in rs)
        alarm_any = sum(1 for r in rs if not r["decline"] and r["stable_alarm_days"] > 0)
        return {
            "metric_rule_detections": sum(1 for r in dec if r["detected"] and
                                          set(r["det_codes"]) & {"metric_trend", "metric_shift", "multi_metric"}),
            "stable_people_with_any_alarm_day": alarm_any,
            "stable_alarm_day_share": round(sum(r["stable_alarm_days"] for r in rs) / sta_days, 4) if sta_days else None,
        }
    report["ablation"]["personal_detail"] = metric_only(rows)
    report["ablation"]["population_detail"] = metric_only(prow)
    report["persons"] = rows
    report["markdown"] = report_md(report)
    return report


def _pct(x):
    return "n/a" if x is None else f"{100 * x:.1f}%"


def _row(name, s):
    d = "n/a" if s["median_delay_days"] is None else f"{s['median_delay_days']:.0f}"
    return (f"| {name} | {s['n']} | {s['n_decline']} | {_pct(s['sensitivity'])} | {_pct(s['sensitivity_30d'])} | {d} | "
            f"{_pct(s['specificity_person'])} | {_pct(s['specificity_day'])} | "
            f"{'n/a' if s['false_alarms_per_person_month'] is None else s['false_alarms_per_person_month']} |")


HDR = ("| Group | N | N decline | Sensitivity | Sens. ≤30 d | Median delay (d) | Specificity (person) | "
       "Specificity (day) | False alarms / person-month |\n|---|---|---|---|---|---|---|---|---|")


def report_md(report: dict) -> str:
    o = report["overall"]
    lines = [
        "# Chào Bà – detection evaluation",
        "",
        f"> **{DISCLAIMER}** All numbers below come from a synthetic cohort generated by `chaoba.core.synth` "
        "(AR(1) noise, weekday effects, missed/invalid calls, injected declines). They show that the "
        "pipeline behaves as designed; they are not evidence of clinical accuracy.",
        "",
        f"Cohort: {o['n']} simulated elders × {report['days']} days; {o['n_decline']} with an injected decline "
        f"(random onset day 35–{report['days'] - 35}, gradual ramp 14–35 days, random magnitude), "
        f"{o['n_stable']} stable. Baseline = first {report['config']['baseline_days']} days.",
        "",
        "## Headline",
        "",
        f"- **Sensitivity** (decline flagged yellow/red after onset): **{_pct(o['sensitivity'])}** "
        f"({_pct(o['sensitivity_30d'])} within 30 days of onset)",
        f"- **Median detection delay**: **{o['median_delay_days']} days** after onset "
        f"(IQR {o['delay_iqr'][0]:.0f}–{o['delay_iqr'][1]:.0f})" if o["delay_iqr"] else "- Median detection delay: n/a",
        f"- **False alarms**: **{o['false_alarms_per_person_month']} per person-month** of stable monitoring "
        f"(day-level specificity {_pct(o['specificity_day'])}; {_pct(o['specificity_person'])} of stable elders "
        f"never alerted in {report['days'] - report['config']['baseline_days']} monitored days). "
        f"Of these, {o['metric_false_alarms_per_person_month']} per person-month come from the speech/recall "
        "control chart; the rest are event rules (reported falls, repeated symptom mentions, missed calls) "
        "that a family would want to hear about anyway.",
        "",
        "## Overall and by decline type",
        "",
        HDR,
        _row("All", o),
    ]
    for g, s in report["by_decline_type"].items():
        lines.append(_row(g, s))
    lines += ["", "## By dialect", "", HDR] + [_row(g, s) for g, s in report["by_dialect"].items()]
    lines += ["", "## By channel", "", HDR] + [_row(g, s) for g, s in report["by_channel"].items()]
    ab = report["ablation"]
    p, q = ab["personal"], ab["population"]
    lines += [
        "", "## Ablation: personal baseline vs population norm", "",
        ab["description"], "",
        "| Baseline | Sensitivity | Sens. ≤30 d | Median delay (d) | Specificity (person) | Specificity (day) | False alarms / person-month |",
        "|---|---|---|---|---|---|---|",
        f"| Personal (Chào Bà) | {_pct(p['sensitivity'])} | {_pct(p['sensitivity_30d'])} | {p['median_delay_days']} | "
        f"{_pct(p['specificity_person'])} | {_pct(p['specificity_day'])} | {p['false_alarms_per_person_month']} |",
        f"| Population norm | {_pct(q['sensitivity'])} | {_pct(q['sensitivity_30d'])} | {q['median_delay_days']} | "
        f"{_pct(q['specificity_person'])} | {_pct(q['specificity_day'])} | {q['false_alarms_per_person_month']} |",
        "",
        f"Stable elders shown yellow/red on more than half of their monitored days: personal "
        f"**{p['stable_mostly_flagged']}**, population norm **{q['stable_mostly_flagged']}** (of {p['n_stable']}). "
        "With a population norm these people are effectively in permanent alarm, and a decline that starts "
        "while someone is already flagged cannot be noticed (it is not counted as a detection).",
        "",
        "| Decline type | Sensitivity – personal | Sensitivity – population |",
        "|---|---|---|",
    ]
    for g in ab["personal_by_type"]:
        if g == "stable":
            continue
        lines.append(f"| {g} | {_pct(ab['personal_by_type'][g]['sensitivity'])} | "
                     f"{_pct(ab['population_by_type'].get(g, {}).get('sensitivity'))} |")
    pd_, qd = ab["personal_detail"], ab["population_detail"]
    lines += [
        "",
        f"Stable elders with at least one yellow/red day: personal {pd_['stable_people_with_any_alarm_day']}, "
        f"population {qd['stable_people_with_any_alarm_day']} (of {o['n_stable']}). Share of stable monitored days "
        f"shown yellow/red: personal {_pct(pd_['stable_alarm_day_share'])}, population {_pct(qd['stable_alarm_day_share'])}.",
        "",
        "Why it matters: speech rate, pauses and vocabulary differ far more *between* people (dialect, "
        "education, personality, phone line) than a meaningful change *within* one person. A population "
        "norm keeps naturally slow or hesitant speakers permanently flagged while missing a 10–15 % "
        "decline in a fast speaker who is still 'above average'.",
        "",
        "## Which rules fired",
        "",
        "| Rule | First alert of detected declines | False-alarm episodes |", "|---|---|---|",
    ]
    codes = sorted(set(report["detection_rule_counts"]) | set(report["false_alarm_rule_counts"]))
    for c in codes:
        lines.append(f"| `{c}` | {report['detection_rule_counts'].get(c, 0)} | {report['false_alarm_rule_counts'].get(c, 0)} |")
    cfg = report["config"]
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
        "- Sensitivity counts an alert episode that starts on/after onset; episodes starting earlier count as false alarms.",
        "",
        f"_{DISCLAIMER}_",
    ]
    return "\n".join(lines) + "\n"


def write_report(report: dict, json_path: str, md_path: str) -> None:
    rep = {k: v for k, v in report.items() if k != "markdown"}
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(report.get("markdown") or report_md(report))
