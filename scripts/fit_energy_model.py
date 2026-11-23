"""Fit the radio-unit energy model on the training split and score it on validation.

Run: uv run python scripts/fit_energy_model.py
Writes models to results/energy/<unit>.json and a summary to results/energy/summary.json.
The test split is not touched (D23).
"""

from __future__ import annotations

import json

from yovahti.energy.model import RADIO_UNITS, SLEEPABLE, evaluate, fit, load_unit_table
from yovahti.paths import RESULTS

OUT = RESULTS / "energy"


def main() -> None:
    summary = {}
    for unit in RADIO_UNITS:
        train = load_unit_table(unit, "train")
        model = fit(unit, train)
        model.to_json(OUT / f"{unit}.json")
        val = evaluate(model, load_unit_table(unit, "validation"))
        tr = evaluate(model, train)
        s = {"slopes_wh_per_pct": model.slopes, "units": len(model.idle),
             "idle_median_wh": model.idle_default, "within_r2_train": model.fit_r2_within,
             "train": tr, "validation": val}
        if unit in SLEEPABLE:
            s["sleep_ratio"] = {f"cat{c}_{st}": model.sleep_ratio(st, c)
                                for c in (1, 2) for st in ("deep_sleep", "light_sleep")}
        summary[unit] = s
        print(f"\n== {unit} ({', '.join(model.carriers)}): {len(model.idle)} units, "
              f"{model.train_rows:,} train rows")
        print("  slopes (Wh/15min per % load): "
              + ", ".join(f"{c} {b:+.3f}" for c, b in model.slopes.items()))
        print(f"  idle median {model.idle_default:.1f} Wh/15min (~{4 * model.idle_default:.0f} W);"
              f" within-unit R² (train) {model.fit_r2_within:.3f}")
        for name, m in (("train", tr), ("validation", val)):
            print(f"  {name:10s} MAE {m['mae_wh']:.2f} Wh ({m['mape_pct']:.1f}%), "
                  f"bias {m['bias_wh']:+.2f}, R² {m['r2']:.3f}, idle share {m['idle_share']:.2f}")
        if unit in SLEEPABLE:
            print("  sleep ratio vs idle-on: " + ", ".join(f"{k} {v:.3f}"
                                                        for k, v in s["sleep_ratio"].items()))
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(f"\nwritten to {OUT}")


if __name__ == "__main__":
    main()
