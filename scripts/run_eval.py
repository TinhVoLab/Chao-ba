"""Run the simulated-cohort evaluation (development + held-out cohorts) and write data/eval/:

* report.json / report.md - held-out headline with 95 % bootstrap intervals, corrected (attributed,
  chance-corrected) detection definition, subgroups, personal-vs-population ablation;
* operating_curve.csv / operating_curve.svg - sensitivity vs false alarms across L_yellow, both cohorts.

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

from chaoba.core.evaluation import curve_svg, run_holdout, write_curve_csv, write_report  # noqa: E402
from chaoba.core.synth import generate_cohort  # noqa: E402


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
    print(f"wrote {out}/report.json, report.md, operating_curve.csv, operating_curve.svg")


if __name__ == "__main__":
    main()
