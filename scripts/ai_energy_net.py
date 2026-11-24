"""Net savings after the AI's own energy (stretch tier 2, I21), as a labelled ESTIMATE.

Hosted-model energy can't be measured from outside, so each LLM call is priced with published
per-response figures, low and high:

* low  0.24 Wh: median Gemini Apps text prompt, full serving stack incl. idle and PUE
  (Google, "Measuring the environmental impact of delivering AI at Google Scale",
  arXiv 2508.15734, May 2025 data);
* high 1.86 Wh: Llama 3.1 405B per response (University of Michigan ML.ENERGY measurements),

and a 10x stress factor on the high figure for long agent contexts. Calls are counted from
the LLM ledger (every call this project made). Savings per cluster-night come from the B4
validation result (results/compare/validation_cat1.json).

Run: uv run python scripts/ai_energy_net.py
"""

from __future__ import annotations

import json
from collections import defaultdict

from yovahti.agents.llm import LEDGER
from yovahti.paths import RESULTS

WH_LOW, WH_HIGH, STRESS = 0.24, 1.86, 10
NIGHTS, SECTORS, SITES_PER_CLUSTER, SITES = 14, 749, 10, 264
KWH_SAVED_2W = 28_061            # B4 vs always-on, validation weeks (README, handoff)


def main() -> None:
    runs = defaultdict(lambda: {"calls": 0, "tokens": 0})
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        kind = r["run"].split(":")[0]
        key = "agent night" if kind[:4].isdigit() else kind
        runs[key]["calls"] += 1
        runs[key]["tokens"] += r["prompt_tokens"] + r["completion_tokens"]
    night = runs["agent night"]
    clusters = -(-SITES // SITES_PER_CLUSTER)
    kwh_cluster_night = KWH_SAVED_2W / NIGHTS / clusters
    out = {"kwh_saved_per_cluster_night": round(kwh_cluster_night, 1),
           "agent_night": {**night,
                           "wh_low": round(night["calls"] * WH_LOW, 2),
                           "wh_high": round(night["calls"] * WH_HIGH, 2),
                           "wh_stress": round(night["calls"] * WH_HIGH * STRESS, 1)},
           "all_llm_use_so_far": {k: v for k, v in runs.items()}}
    a = out["agent_night"]
    out["agent_share_of_savings_pct"] = {
        k: round(100 * a[f"wh_{k}"] / 1000 / kwh_cluster_night, 4) for k in ("low", "high",
                                                                             "stress")}
    total_calls = sum(v["calls"] for v in runs.values())
    out["testing_kwh_total"] = {"low": round(total_calls * WH_LOW / 1000, 2),
                                "high": round(total_calls * WH_HIGH / 1000, 2)}
    out["testing_paid_back_in_cluster_nights_high"] = round(
        out["testing_kwh_total"]["high"] / kwh_cluster_night, 2)
    out["label"] = ("estimate from published per-response figures, not a measurement; local "
                    "RTX 4050 measurement pending a local model runtime")
    path = RESULTS / "compare" / "ai_energy_net.json"
    path.write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
