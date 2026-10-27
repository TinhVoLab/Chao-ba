"""DMAIC care-loop summary for one elder (Define - Measure - Analyze - Improve - Control).

``compute_cycle(records, lights, define, intervention_day, pre_days=14, post_days=14)``

* **Define**  day 1: goals and concern from ``define`` ({"goals": [...], "concern_vi", "concern_en"}).
* **Measure** days 1..baseline end: number of valid calls, baseline values of the key metrics.
* **Analyze** first alert day (first yellow/red after the baseline) .. intervention_day-1: which
  signals changed and by how much (from the alert reasons).
* **Improve** intervention_day .. first day of sustained green (``days_to_green``). If there is no
  intervention yet (``intervention_day`` None or beyond the data) the phase holds the *recommended*
  action instead.
* **Control** green day .. last day; ``new_baseline_day`` = green day + baseline_days (21) when that
  falls inside the data (or ``define["new_baseline_day"]`` if the caller fixed it): the stabilised
  post-intervention period becomes the new personal baseline.

``effect[metric]``: mean of valid values in the ``pre_days`` before the intervention vs. mean of
valid values in the ``post_days`` window that starts after a washout of ``post_days // 2`` days
(recovery is not instant), plus the original baseline center for reference.
"""
from __future__ import annotations

import numpy as np

from .control_chart import _as_record
from .models import METRICS

LABEL_VI = {"speech_rate_sps": "tốc độ nói", "pause_ratio": "tỉ lệ ngừng nghỉ",
            "filled_pause_rate": "từ đệm (ờ, à)", "mattr": "độ phong phú từ ngữ", "recall_score": "điểm nhớ lại"}
LABEL_EN = {"speech_rate_sps": "speech rate", "pause_ratio": "pause ratio",
            "filled_pause_rate": "filler rate", "mattr": "vocabulary diversity (MATTR)", "recall_score": "recall score"}


def _get(o, k, d=None):
    return o.get(k, d) if isinstance(o, dict) else getattr(o, k, d)


def _mean(vals):
    vals = [float(v) for v in vals if v is not None]
    return float(np.mean(vals)) if vals else None


def _fmt(x, metric, vi=False):
    if x is None:
        return "n/a"
    out = f"{x:.2f}" if metric in ("speech_rate_sps", "recall_score") else f"{x:.3f}"
    return out.replace(".", ",") if vi else out


def compute_cycle(records, lights, define: dict, intervention_day: int | None, pre_days: int = 14,
                  post_days: int = 14) -> dict:
    recs = sorted((_as_record(r) for r in records), key=lambda r: r.day)
    lts = sorted(lights, key=lambda l: _get(l, "day"))
    if not recs:
        return {"phases": [], "effect": {}, "new_baseline_day": None}
    define = define or {}
    first, last = recs[0].day, recs[-1].day
    by_day_light = {_get(l, "day"): _get(l, "light") for l in lts}
    ready_days = [_get(l, "day") for l in lts if _get(l, "baseline_ready")]
    base_end = (min(ready_days) - 1) if ready_days else last
    measure_recs = [r for r in recs if r.day <= base_end]
    n_valid = sum(1 for r in measure_recs if r.valid and r.answered)
    n_missed = sum(1 for r in measure_recs if not r.answered)
    base_vals = {m: _mean([getattr(r, m) for r in measure_recs if r.valid]) for m in METRICS}
    base_med = {m: (float(np.median([getattr(r, m) for r in measure_recs if r.valid and getattr(r, m) is not None]))
                    if any(r.valid and getattr(r, m) is not None for r in measure_recs) else None) for m in METRICS}

    has_iv = intervention_day is not None and first <= intervention_day <= last
    alert_days = [d for d, c in sorted(by_day_light.items()) if c in ("yellow", "red") and d > base_end]
    if has_iv:
        pre_alerts = [d for d in alert_days if d < intervention_day]
        first_alert = pre_alerts[0] if pre_alerts else (alert_days[0] if alert_days else None)
    else:
        first_alert = alert_days[0] if alert_days else None
    peak = None
    if first_alert is not None:
        upto = intervention_day if has_iv else last + 1
        peak = "red" if any(by_day_light.get(d) == "red" for d in range(first_alert, upto)) else "yellow"
    red_day = next((d for d in alert_days if by_day_light[d] == "red" and (first_alert is None or d >= first_alert)), None)

    # reasons at peak for Analyze
    changed: dict[str, float] = {}
    symptoms: dict[str, int] = {}
    rng_end = intervention_day if has_iv else last + 1
    for l in lts:
        d = _get(l, "day")
        if first_alert is not None and first_alert <= d < rng_end:
            for r in _get(l, "reasons") or []:
                if r.get("code") in ("metric_trend", "metric_shift") and r.get("change_pct") is not None:
                    if abs(r["change_pct"]) > abs(changed.get(r["metric"], 0)):
                        changed[r["metric"]] = r["change_pct"]
                for dd in r.get("details", []) or []:
                    if dd.get("change_pct") is not None and abs(dd["change_pct"]) > abs(changed.get(dd["metric"], 0)):
                        changed[dd["metric"]] = dd["change_pct"]
    if first_alert is not None:
        for r in recs:
            if first_alert - 7 <= r.day < rng_end:
                for s, c in (r.symptoms or {}).items():
                    symptoms[s] = symptoms.get(s, 0) + int(c)

    # green after intervention (first day of a run that stays green for >= 7 days or to the end)
    green_day = None
    if has_iv:
        days = [d for d in sorted(by_day_light) if d >= intervention_day]
        for i, d in enumerate(days):
            if by_day_light[d] != "green":
                continue
            window = [by_day_light[x] for x in days[i:i + 7]]
            if all(c in ("green", "gray") for c in window):
                green_day = d
                break
    days_to_green = (green_day - intervention_day) if green_day is not None else None
    new_base = define.get("new_baseline_day")
    if new_base is None and green_day is not None and green_day + 21 <= last:
        new_base = green_day + 21

    # effect pre vs post
    effect = {}
    if has_iv:
        wash = post_days // 2
        pre = [r for r in recs if intervention_day - pre_days <= r.day < intervention_day and r.valid]
        post = [r for r in recs if intervention_day + wash <= r.day < intervention_day + wash + post_days and r.valid]
        for m in METRICS:
            a, b = _mean([getattr(r, m) for r in pre]), _mean([getattr(r, m) for r in post])
            if a is None or b is None:
                continue
            effect[m] = {"pre": round(a, 4), "post": round(b, 4),
                         "change_pct": round((b - a) / abs(a) * 100.0, 1) if a else None,
                         "baseline": round(base_med[m], 4) if base_med[m] is not None else None,
                         "pre_window": [intervention_day - pre_days, intervention_day - 1],
                         "post_window": [intervention_day + wash, intervention_day + wash + post_days - 1]}

    # ---- phase summaries ---------------------------------------------------------------
    goals = define.get("goals", [])
    concern_vi = define.get("concern_vi", "theo dõi sức khỏe và trí nhớ hằng ngày")
    concern_en = define.get("concern_en", "daily wellbeing and memory follow-up")
    phases = [{
        "phase": "define", "day_from": first, "day_to": first,
        "summary_vi": f"Mục tiêu chăm sóc: {concern_vi}. " + (f"Mục tiêu đặt cùng gia đình: {'; '.join(goals)}." if goals else ""),
        "summary_en": f"Care goal: {concern_en}. " + (f"{len(goals)} goals agreed with the family." if goals else ""),
    }]
    sr = base_med.get("speech_rate_sps")
    rc = base_vals.get("recall_score")
    phases.append({
        "phase": "measure", "day_from": first, "day_to": base_end,
        "summary_vi": (f"{n_valid} cuộc gọi hợp lệ trong {base_end - first + 1} ngày đầu ({n_missed} ngày lỡ cuộc gọi) "
                       f"để lập mức bình thường riêng: tốc độ nói {_fmt(sr, 'speech_rate_sps', True)} âm tiết/giây, "
                       f"điểm nhớ lại trung bình {_fmt(rc, 'recall_score', True)}/3."),
        "summary_en": (f"{n_valid} valid calls in the first {base_end - first + 1} days ({n_missed} missed) built the "
                       f"personal baseline: speech rate {_fmt(sr, 'speech_rate_sps')} syllables/s, mean recall "
                       f"{_fmt(rc, 'recall_score')}/3."),
    })
    if first_alert is None:
        phases.append({"phase": "analyze", "day_from": base_end + 1, "day_to": last,
                       "summary_vi": "Không có thay đổi kéo dài so với mức bình thường của người thân.",
                       "summary_en": "No sustained change from the person's own baseline."})
    else:
        top = sorted(changed.items(), key=lambda kv: -abs(kv[1]))[:3]
        ch_vi = ", ".join(f"{LABEL_VI[m]} {v:+.0f}%" for m, v in top)
        ch_en = ", ".join(f"{LABEL_EN[m]} {v:+.0f}%" for m, v in top)
        sy = sorted(symptoms.items(), key=lambda kv: -kv[1])
        from .explain import SYMPTOM_VI, SYMPTOM_EN
        sy_vi = ", ".join(f"{SYMPTOM_VI.get(s, s)} {c} lần" for s, c in sy)
        sy_en = ", ".join(f"{SYMPTOM_EN.get(s, s)} x{c}" for s, c in sy)
        end_an = (intervention_day - 1) if has_iv else last
        txt_vi = f"Đèn vàng từ ngày {first_alert}" + (f", đỏ từ ngày {red_day}" if red_day and red_day < rng_end else "") + "."
        txt_en = f"Yellow from day {first_alert}" + (f", red from day {red_day}" if red_day and red_day < rng_end else "") + "."
        if ch_vi:
            txt_vi += f" Thay đổi so với mức bình thường: {ch_vi}."
            txt_en += f" Change vs own baseline: {ch_en}."
        if sy_vi:
            txt_vi += f" Triệu chứng được nhắc: {sy_vi}."
            txt_en += f" Symptoms mentioned: {sy_en}."
        if define.get("context_vi"):
            txt_vi += " " + define["context_vi"]
            txt_en += " " + define.get("context_en", "")
        phases.append({"phase": "analyze", "day_from": first_alert, "day_to": end_an,
                       "summary_vi": txt_vi, "summary_en": txt_en})
    if has_iv:
        iv_vi = define.get("intervention_vi", "Gia đình và bác sĩ can thiệp")
        iv_en = define.get("intervention_en", "Family and clinician intervention")
        sr_eff = effect.get("speech_rate_sps")
        eff_vi = eff_en = ""
        if sr_eff and sr_eff["change_pct"] is not None:
            eff_vi = (f" Tốc độ nói {_fmt(sr_eff['pre'], 'speech_rate_sps', True)} → "
                      f"{_fmt(sr_eff['post'], 'speech_rate_sps', True)} âm tiết/giây ({sr_eff['change_pct']:+.0f}%).")
            eff_en = f" Speech rate {sr_eff['pre']:.2f} → {sr_eff['post']:.2f} syllables/s ({sr_eff['change_pct']:+.0f}%)."
        g_vi = f" Đèn xanh trở lại sau {days_to_green} ngày (ngày {green_day})." if green_day else " Chưa xanh trở lại."
        g_en = f" Back to green after {days_to_green} days (day {green_day})." if green_day else " Not yet back to green."
        phases.append({"phase": "improve", "day_from": intervention_day, "day_to": green_day or last,
                       "summary_vi": f"Ngày {intervention_day}: {iv_vi}.{eff_vi}{g_vi}",
                       "summary_en": f"Day {intervention_day}: {iv_en}.{eff_en}{g_en}"})
    else:
        rec_vi = define.get("recommendation_vi", "Tiếp tục gọi hằng ngày như bình thường.")
        rec_en = define.get("recommendation_en", "Continue daily calls as usual.")
        if first_alert is None:
            rec_vi, rec_en = "Tiếp tục gọi hằng ngày như bình thường.", "Continue daily calls as usual."
        phases.append({"phase": "improve", "day_from": last, "day_to": last,
                       "summary_vi": f"Đề xuất: {rec_vi}", "summary_en": f"Recommended: {rec_en}"})
    if green_day:
        ctl_vi = f"Theo dõi tiếp từ ngày {green_day}; tuân thủ kế hoạch chăm sóc."
        ctl_en = f"Monitoring continues from day {green_day}; care plan maintained."
        if new_base:
            ctl_vi += f" Ngày {new_base}: lập mức bình thường mới từ giai đoạn ổn định sau can thiệp."
            ctl_en += f" Day {new_base}: new personal baseline set from the stable post-intervention period."
        phases.append({"phase": "control", "day_from": green_day, "day_to": last,
                       "summary_vi": ctl_vi, "summary_en": ctl_en})
    else:
        n_green = sum(1 for c in by_day_light.values() if c == "green")
        phases.append({"phase": "control", "day_from": base_end + 1, "day_to": last,
                       "summary_vi": f"Theo dõi liên tục: {n_green} ngày đèn xanh sau khi có mức bình thường.",
                       "summary_en": f"Continuous monitoring: {n_green} green days since the baseline was set."})
    return {
        "phases": phases,
        "effect": effect,
        "new_baseline_day": new_base,
        "first_alert_day": first_alert,
        "peak_light": peak,
        "intervention_day": intervention_day if has_iv else None,
        "green_day": green_day,
        "days_to_green": days_to_green,
    }
