"""Run the simulated-cohort evaluation (development + held-out cohorts) and write data/eval/:

* report.json / report.md - held-out headline with 95 % bootstrap intervals, corrected (attributed,
  chance-corrected) detection definition, subgroups, personal-vs-population ablation;
* operating_curve.csv / operating_curve.svg - sensitivity vs false alarms across L_yellow, both cohorts;
* specificity per 30-day period, false-referral burden, completion, test-retest reliability, age-band and education
  subgroups, and a sensitivity check with an assumed education/age level effect (same held-out seed).

Deterministic: fixed cohort seeds and bootstrap seed, no timestamps in the outputs.
Simulated cohort - not clinical validation.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chaoba.core.evaluation import (_cfg_at, curve_svg, level_effect_check, report_md, run_holdout,  # noqa: E402
                                    write_curve_csv, write_report)
from chaoba.core.control_chart import ControlConfig  # noqa: E402
from chaoba.core.synth import AGE_SPEECH_SLOPE, EDU_MATTR_SHIFT, generate_cohort  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev-n", type=int, default=200)
    ap.add_argument("--dev-seed", type=int, default=11)
    ap.add_argument("--test-n", type=int, default=400)
    ap.add_argument("--test-seed", type=int, default=2026)
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--boot", type=int, default=1000)
    ap.add_argument("--out", default=str(ROOT / "data" / "eval"))
    a = ap.parse_args()
    if a.dev_seed == a.test_seed:
        ap.error("development and held-out seeds must differ")
    t0 = time.time()
    dev = generate_cohort(n=a.dev_n, days=a.days, seed=a.dev_seed)
    test = generate_cohort(n=a.test_n, days=a.days, seed=a.test_seed)
    rep = run_holdout(dev, test, n_boot=a.boot, seed=0, dev_seed=a.dev_seed, test_seed=a.test_seed)
    rep["cohort_seed"] = a.test_seed
    # sensitivity check: same held-out seed with an assumed education (MATTR) and age (speech rate) level effect
    fx = generate_cohort(n=a.test_n, days=a.days, seed=a.test_seed, level_effects=True)
    rep["level_effect"] = {
        "assumption": {
            "education": "shifted by " + ", ".join(f"{v:+.2f} ({k})" for k, v in EDU_MATTR_SHIFT.items()),
            "age": f"shifted by {AGE_SPEECH_SLOPE:+.2f} syll/s per year of age above 75",
        },
        **level_effect_check(fx, _cfg_at(ControlConfig(), rep["holdout"]["chosen_L_yellow"]), n_boot=a.boot, seed=0),
    }
    rep["markdown"] = report_md(rep)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    write_report(rep, str(out / "report.json"), str(out / "report.md"))
    write_curve_csv(rep, str(out / "operating_curve.csv"))
    (out / "operating_curve.svg").write_text(curve_svg(rep), encoding="utf-8")
    o, op, q, h = rep["overall"], rep["operational"], rep["ablation"]["population"], rep["holdout"]

    def f(s, k):
        ci = s.get(k + "_ci")
        return f"{s[k]:.3f} [{ci[0]:.3f}, {ci[1]:.3f}]" if ci else f"{s[k]}"

    print(f"dev seed {a.dev_seed} (n={a.dev_n}) -> chosen L_yellow {h['chosen_L_yellow']} / L_red {h['chosen_L_red']}; "
          f"held-out seed {a.test_seed} (n={a.test_n}); {time.time() - t0:.1f}s")
    for name, s in (("personal", o), ("population", q)):
        print(f"{name:10s}: sens {f(s, 'sensitivity')}, chance {f(s, 'chance_rate')}, excess {f(s, 'excess_sensitivity')}, "
              f"chart excess {f(s, 'chart_excess_sensitivity')}, FA/p-m {f(s, 'false_alarms_per_person_month')}")
    print(f"operational (missed calls): sens {f(op, 'sensitivity')}, chance {f(op, 'chance_rate')}")
    print(f"stable: specificity/30-day period {f(o, 'specificity_period')}, red alerts/100 p-m "
          f"{f(o, 'red_alerts_per_100_person_months')}, completion {f(o, 'completion_rate')}")
    for m, v in rep["reliability"]["metrics"].items():
        print(f"ICC {m:18s}: weekly mean {f(v, 'weekly_mean')}, single call {f(v, 'single_call')}")
    print(f"wrote {out}/report.json, report.md, operating_curve.csv, operating_curve.svg")


if __name__ == "__main__":
    main()
