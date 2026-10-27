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

Each phase carries ``status`` = ``done | current | not_started``. A phase that has not started has
``day_from``/``day_to`` = None (no invented ranges); a not-started Improve carries the *recommended* action.

``contacts`` (optional, family calls/visits ``[{"day": d, ...}]``) adds ``contact``: calls+visits per week in the
``contact_window`` days before and from the intervention, and in the last 14 days (``recent_per_week``).

``effect[metric]``: mean of valid values in the ``pre_days`` before the intervention vs. mean of
valid values in the ``post_days`` window that starts after a washout of ``post_days // 2`` days
(recovery is not instant), plus the original baseline center for reference, the difference ``diff`` and an
approximate 95 % interval ``diff_ci95`` (Welch-type standard error inflated by sqrt((1+phi)/(1-phi)), phi = 0.3,
for day-to-day autocorrelation). A pre/post difference is *not* proof that the intervention worked: the
intervention is usually made when values are at their worst, so part of any improvement is regression to the
mean or natural recovery.

``effect_illustrative`` is True when the data are simulated (``simulated=True``, ``define["simulated"]``, or any
record in the pre/post windows flagged ``simulated``, so a live call appended to a scripted persona does not
make the scripted effect look measured): on a scripted persona the "effect" was written into the script, so it only
illustrates the display. ``effect_note_vi`` / ``effect_note_en`` carry the matching caveat ("" when there is
no effect). Recall (0-3) is summarised as counts of calls ("4/12 calls"), never as a percentage.
"""
from __future__ import annotations

import numpy as np

from .control_chart import _as_record
from .explain import recall_counts
from .models import METRICS

AR_INFLATE = ((1 + 0.3) / (1 - 0.3)) ** 0.5   # SE inflation for daily data with lag-1 autocorrelation 0.3
EFFECT_NOTE = {
    True: ("Minh họa (nhân vật mô phỏng theo kịch bản): mức cải thiện này được viết sẵn trong kịch bản, "
           "không phải kết quả đo được.",
           "Illustrative (scripted persona): this improvement was written into the simulation script; it is not "
           "a measured result."),
    False: ("So với mức bình thường riêng của người thân trước khi thay đổi; khoảng dao động cho biết độ chắc chắn. "
            "Cải thiện sau can thiệp có thể một phần do tự hồi phục, không chắc hoàn toàn nhờ can thiệp.",
            "Compared with the person's own pre-change baseline; the range shows the uncertainty. Part of an "
            "improvement after an intervention may be natural recovery or regression to the mean, not the "
            "intervention itself."),
}

LABEL_VI = {"speech_rate_sps": "tốc độ nói", "pause_ratio": "tỉ lệ ngừng nghỉ",
            "filled_pause_rate": "từ đệm (ờ, à)", "mattr": "độ phong phú từ ngữ", "recall_score": "nhớ chuyện hôm trước"}
LABEL_EN = {"speech_rate_sps": "speech rate", "pause_ratio": "pause ratio",
            "filled_pause_rate": "filler rate", "mattr": "vocabulary diversity (MATTR)", "recall_score": "story recall (0–3)"}


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


def contact_rate(contacts, day_from: int, day_to: int) -> float | None:
    """Family contacts (calls + visits) per week in [day_from, day_to] (inclusive); None if the window is empty."""
    n_days = day_to - day_from + 1
    if contacts is None or n_days <= 0:
        return None
    n = sum(1 for c in contacts if day_from <= int(_get(c, "day", -10 ** 6)) <= day_to)
    return round(n * 7.0 / n_days, 1)


def _fmt1(x, vi=False):
    out = f"{x:.1f}"
    return out.replace(".", ",") if vi else out


def _free_recall(recs):
    """(full recalls without hints, recall calls) over valid records with a recall score."""
    rs = [r for r in recs if r.valid and r.recall_score is not None]
    return sum(1 for r in rs if r.recall_score >= 3), len(rs)


def compute_cycle(records, lights, define: dict, intervention_day: int | None, pre_days: int = 14,
                  post_days: int = 14, contacts: list | None = None, contact_window: int = 28,
                  simulated: bool | None = None) -> dict:
    recs = sorted((_as_record(r) for r in records), key=lambda r: r.day)
    lts = sorted(lights, key=lambda l: _get(l, "day"))
    if not recs:
        return {"phases": [], "effect": {}, "new_baseline_day": None, "contact": None,
                "effect_illustrative": False, "effect_note_vi": "", "effect_note_en": ""}
    define = define or {}
    if simulated is None:
        simulated = define.get("simulated")
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
            va = [float(getattr(r, m)) for r in pre if getattr(r, m) is not None]
            vb = [float(getattr(r, m)) for r in post if getattr(r, m) is not None]
            a, b = _mean(va), _mean(vb)
            if a is None or b is None:
                continue
            se = None
            if len(va) > 1 and len(vb) > 1:
                se = AR_INFLATE * float(np.sqrt(np.var(va, ddof=1) / len(va) + np.var(vb, ddof=1) / len(vb)))
            effect[m] = {"pre": round(a, 4), "post": round(b, 4), "diff": round(b - a, 4),
                         "diff_ci95": [round(b - a - 1.96 * se, 4), round(b - a + 1.96 * se, 4)] if se is not None else None,
                         "n_pre": len(va), "n_post": len(vb),
                         "change_pct": round((b - a) / abs(a) * 100.0, 1) if a else None,
                         "baseline": round(base_med[m], 4) if base_med[m] is not None else None,
                         "pre_window": [intervention_day - pre_days, intervention_day - 1],
                         "post_window": [intervention_day + wash, intervention_day + wash + post_days - 1]}

    if simulated is None:  # illustrative if any record behind the pre/post comparison is simulated (scripted)
        win = [r for r in recs if has_iv and intervention_day - pre_days <= r.day < intervention_day + post_days // 2 + post_days]
        simulated = any(bool(r.simulated) for r in (win or recs))

    # family contact frequency (calls + visits per week): the care plan's measurable intervention
    contact = None
    if contacts is not None:
        rw = [max(first, last - 13), last]
        contact = {"recent_per_week": contact_rate(contacts, *rw), "recent_window": rw}
        if has_iv:
            pw = [max(first, intervention_day - contact_window), intervention_day - 1]
            qw = [intervention_day, min(last, intervention_day + contact_window - 1)]
            contact.update({"pre_per_week": contact_rate(contacts, *pw), "pre_window": pw,
                            "post_per_week": contact_rate(contacts, *qw), "post_window": qw})

    # ---- phase summaries ---------------------------------------------------------------
    goals = define.get("goals", [])
    concern_vi = define.get("concern_vi", "theo dõi sức khỏe và trí nhớ hằng ngày")
    concern_en = define.get("concern_en", "daily wellbeing and memory follow-up")
    phases = [{
        "phase": "define", "status": "done", "day_from": first, "day_to": first,
        "summary_vi": f"Mục tiêu chăm sóc: {concern_vi}. " + (f"Mục tiêu đặt cùng gia đình: {'; '.join(goals)}." if goals else ""),
        "summary_en": f"Care goal: {concern_en}. " + (f"{len(goals)} goals agreed with the family." if goals else ""),
    }]
    sr = base_med.get("speech_rate_sps")
    rf, rn = _free_recall(measure_recs)
    rc_vi = (f", tự nhớ lại đầy đủ chuyện đã kể (không cần gợi ý) {rf}/{rn} cuộc gọi" if rn else "")
    rc_en = (f"; recalled the earlier story fully without hints on {rf} of {rn} calls" if rn else "")
    phases.append({
        "phase": "measure", "status": "done" if ready_days else "current", "day_from": first, "day_to": base_end,
        "summary_vi": (f"{n_valid} cuộc gọi hợp lệ trong {base_end - first + 1} ngày đầu ({n_missed} ngày lỡ cuộc gọi) "
                       f"để lập mức bình thường riêng: tốc độ nói {_fmt(sr, 'speech_rate_sps', True)} âm tiết/giây"
                       f"{rc_vi}."),
        "summary_en": (f"{n_valid} valid calls in the first {base_end - first + 1} days ({n_missed} missed) built the "
                       f"personal baseline: speech rate {_fmt(sr, 'speech_rate_sps')} syllables/s{rc_en}."),
    })
    if first_alert is None:
        phases.append({"phase": "analyze", "status": "not_started", "day_from": None, "day_to": None,
                       "summary_vi": "Không có thay đổi kéo dài so với mức bình thường của người thân.",
                       "summary_en": "No sustained change from the person's own baseline."})
    else:
        recall_changed = "recall_score" in changed
        top = sorted(((m, v) for m, v in changed.items() if m != "recall_score"), key=lambda kv: -abs(kv[1]))[:3]
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
        if recall_changed:
            rcn = recall_counts(recs, end_an, baseline_days=base_end - first + 1)
            if rcn:
                txt_vi += (f" Tự nhớ lại đầy đủ chuyện đã kể (không cần gợi ý) {rcn[0]}/{rcn[1]} cuộc gọi gần nhất "
                           f"(thường khoảng {rcn[2]}/{rcn[1]}).")
                txt_en += (f" Recalled the earlier story fully without hints on {rcn[0]} of the last {rcn[1]} calls "
                           f"(usually about {rcn[2]} of {rcn[1]}).")
            else:
                txt_vi += " Cần gợi ý nhiều hơn thường lệ khi nhắc lại chuyện đã kể."
                txt_en += " Needed more hints than usual to recall earlier conversations."
        if sy_vi:
            txt_vi += f" Triệu chứng được nhắc: {sy_vi}."
            txt_en += f" Symptoms mentioned: {sy_en}."
        if define.get("context_vi"):
            txt_vi += " " + define["context_vi"]
            txt_en += " " + define.get("context_en", "")
        phases.append({"phase": "analyze", "status": "done" if has_iv else "current",
                       "day_from": first_alert, "day_to": end_an,
                       "summary_vi": txt_vi, "summary_en": txt_en})
    if has_iv:
        iv_vi = define.get("intervention_vi", "Gia đình và bác sĩ can thiệp")
        iv_en = define.get("intervention_en", "Family and clinician intervention")
        sr_eff = effect.get("speech_rate_sps")
        eff_vi = eff_en = ""
        if sr_eff and sr_eff["change_pct"] is not None:
            tag_vi = " Minh họa (kịch bản mô phỏng):" if simulated else ""
            tag_en = " Illustrative (scripted persona):" if simulated else ""
            eff_vi = (f"{tag_vi} Tốc độ nói {_fmt(sr_eff['pre'], 'speech_rate_sps', True)} → "
                      f"{_fmt(sr_eff['post'], 'speech_rate_sps', True)} âm tiết/giây ({sr_eff['change_pct']:+.0f}%).")
            eff_en = (f"{tag_en} Speech rate {sr_eff['pre']:.2f} → {sr_eff['post']:.2f} syllables/s "
                      f"({sr_eff['change_pct']:+.0f}%).")
        if contact and contact.get("pre_per_week") is not None and contact.get("post_per_week") is not None:
            eff_vi += (f" Gia đình gọi/thăm {_fmt1(contact['pre_per_week'], True)} → "
                       f"{_fmt1(contact['post_per_week'], True)} lần/tuần.")
            eff_en += f" Family calls/visits {contact['pre_per_week']:.1f} → {contact['post_per_week']:.1f} per week."
        g_vi = f" Đèn xanh trở lại sau {days_to_green} ngày (ngày {green_day})." if green_day else " Chưa xanh trở lại."
        g_en = f" Back to green after {days_to_green} days (day {green_day})." if green_day else " Not yet back to green."
        phases.append({"phase": "improve", "status": "done" if green_day else "current",
                       "day_from": intervention_day, "day_to": green_day or last,
                       "summary_vi": f"Ngày {intervention_day}: {iv_vi}.{eff_vi}{g_vi}",
                       "summary_en": f"Day {intervention_day}: {iv_en}.{eff_en}{g_en}"})
    else:
        rec_vi = define.get("recommendation_vi", "Tiếp tục gọi hằng ngày như bình thường.")
        rec_en = define.get("recommendation_en", "Continue daily calls as usual.")
        if first_alert is None:
            rec_vi, rec_en = "Tiếp tục gọi hằng ngày như bình thường.", "Continue daily calls as usual."
        # No action taken yet: the phase has no date range; it carries the recommended next step instead.
        phases.append({"phase": "improve", "status": "not_started", "day_from": None, "day_to": None,
                       "summary_vi": f"Đề xuất: {rec_vi}", "summary_en": f"Recommended: {rec_en}"})
    if green_day:
        ctl_vi = f"Theo dõi tiếp từ ngày {green_day}; tuân thủ kế hoạch chăm sóc."
        ctl_en = f"Monitoring continues from day {green_day}; care plan maintained."
        if new_base:
            ctl_vi += f" Ngày {new_base}: lập mức bình thường mới từ giai đoạn ổn định sau can thiệp."
            ctl_en += f" Day {new_base}: new personal baseline set from the stable post-intervention period."
        if contact and contact.get("recent_per_week") is not None and contact.get("post_per_week") is not None:
            ctl_vi += (f" Gia đình gọi/thăm 14 ngày gần đây: {_fmt1(contact['recent_per_week'], True)} lần/tuần"
                       f" (kế hoạch: {_fmt1(contact['post_per_week'], True)}).")
            ctl_en += (f" Family calls/visits in the last 14 days: {contact['recent_per_week']:.1f} per week"
                       f" (plan: {contact['post_per_week']:.1f}).")
        phases.append({"phase": "control", "status": "current", "day_from": green_day, "day_to": last,
                       "summary_vi": ctl_vi, "summary_en": ctl_en})
    else:
        n_green = sum(1 for c in by_day_light.values() if c == "green")
        # Without an open cycle, Control is the steady state (continuous monitoring); while a change is being
        # analysed and nothing has been tried yet, Control has not started.
        open_cycle = first_alert is not None
        phases.append({"phase": "control", "status": "not_started" if open_cycle else ("current" if ready_days else "not_started"),
                       "day_from": None if open_cycle or not ready_days else base_end + 1,
                       "day_to": None if open_cycle or not ready_days else last,
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
        "contact": contact,
        "effect_illustrative": bool(effect) and bool(simulated),
        "effect_note_vi": EFFECT_NOTE[bool(simulated)][0] if effect else "",
        "effect_note_en": EFFECT_NOTE[bool(simulated)][1] if effect else "",
    }
