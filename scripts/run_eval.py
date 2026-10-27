"""Run the simulated-cohort evaluation and write data/eval/report.{json,md}.

Simulated cohort - not clinical validation.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chaoba.core.evaluation import run_evaluation, write_report  # noqa: E402
from chaoba.core.synth import generate_cohort  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--out", default=str(ROOT / "data" / "eval"))
    a = ap.parse_args()
    t0 = time.time()
    cohort = generate_cohort(n=a.n, days=a.days, seed=a.seed)
    rep = run_evaluation(cohort)
    rep["cohort_seed"] = a.seed
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    write_report(rep, str(out / "report.json"), str(out / "report.md"))
    o = rep["overall"]
    q = rep["ablation"]["population"]
    print(f"cohort {a.n} x {a.days} days in {time.time() - t0:.1f}s")
    print(f"personal : sensitivity {o['sensitivity']}, median delay {o['median_delay_days']} d, "
          f"FA/person-month {o['false_alarms_per_person_month']}, day specificity {o['specificity_day']}")
    print(f"population: sensitivity {q['sensitivity']}, median delay {q['median_delay_days']} d, "
          f"FA/person-month {q['false_alarms_per_person_month']}, day specificity {q['specificity_day']}")
    print(f"wrote {out / 'report.json'} and {out / 'report.md'}")


if __name__ == "__main__":
    main()
