"""Write the three demo personas to data/synth/{hanh,tu,control}.json (SIMULATED data)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chaoba.core.synth import generate_persona  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=str(ROOT / "data" / "synth"))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for key in ("hanh", "tu", "control"):
        p = generate_persona(key, days=a.days, seed=a.seed)
        (out / f"{key}.json").write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding="utf-8")
        lights = [l["light"] for l in p["lights"]]
        first = {c: next((l["day"] for l in p["lights"] if l["light"] == c and l["day"] > 21), None)
                 for c in ("yellow", "red")}
        print(f"{key:8s} first yellow={first['yellow']} first red={first['red']} "
              f"green_after_intervention={p['dmaic'].get('green_day')} last={lights[-1]} -> {out / (key + '.json')}")


if __name__ == "__main__":
    main()
