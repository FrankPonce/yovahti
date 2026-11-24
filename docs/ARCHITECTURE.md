# Yövahti: architecture

Status: design 23 Nov 2026; "as built" notes added 24 Nov 2026. Decisions referenced as D-numbers are in [DECISIONS.md](DECISIONS.md).

## Principles

1. **Tools compute, models orchestrate.** Every number an agent reports (kWh, €, load, risk) comes from a tool. The LLM chooses, explains and turns unstructured context into constraints. It never does arithmetic. (Carried over from Charge, where it removed garbled numbers.)
2. **The world is not the twin.** Agents only see the twin: learned, imperfect models. The world has hidden events, noise and model mismatch. Twin error is measured, not assumed away (D5).
3. **Deterministic code has the final say.** `admit()` and the arbiter are plain code with tests and property checks. No model can talk its way past them.
4. **Everything is replayable.** Every run is seeded and logged (inputs, tool calls, decisions, receipts), so any result can be reproduced and any night replayed in the dashboard.
5. **No hindsight.** Forecasts at time *t* only use data published before *t* (Tasehinta's `first_usable` discipline). Leakage tests guard it.
6. **Label what is real.** Real data, synthetic topology, reconstructed baseline, emulated interface: each result says which.

## Components

### 1. Data layer (`yovahti.data`)

| Source | Use | Notes |
|---|---|---|
| **Slovak live RAN PM counters** (Lehoczký et al., *Sci Data* 2026, Zenodo, CC BY 4.0; Ericsson Slovakia co-authors) | **Primary** (D19). Real 15-min cell-level RB utilisation, users, data volume, and real radio-unit and baseband energy. Dataset_03: 264 sites, GSM 900, LTE 700/800/1800, NR 2100/3500, 31 Aug – 22 Nov 2025 | Real coverage + capacity layering on the same sites. Energy is per radio unit / baseband, not per cell (G14) |
| **Telecom Italia Milan** "SMS, Call, Internet - MI" (Harvard Dataverse, ODbL) | Secondary: city-scale spatial structure for the Turku layout and a second-city check. 62 days, 10-min, 10 000 squares | Activity is session counts, not load (G13) |
| **ITU AI/ML in 5G energy dataset** (2023) | Relative effect of each energy-saving mode (the Slovak data has no sleep-mode counters) | 1 020 sites, 1 217 cells, 12 RU types, hourly, 8 days. Energy values appear **normalised**, see FINDINGS G1 |
| **Nord Pool FI day-ahead** (15-min since Oct 2025), via ENTSO-E or a free mirror | € value of each saved kWh | Calendar alignment with 2013 Milan dates, see ISSUES |
| **Fingrid open data** (emission factor, wind, consumption) | CO₂ value; Tier 1 live mode | Free API key |
| **3GPP TR 38.864** (Rel-18 network energy saving study) | Relative power of sleep states (deep, light, micro sleep, active) and transition times and energies | Vendor-neutral |
| **OpenCelliD** (CC BY-SA 4.0, Finland MCC 244) | Optional: real cell positions in Turku | Crowdsourced; share-alike |
| **Event calendar + operator notes** (synthetic, hand-written, some real Turku events) | The unstructured channel the LLM reads | Also the injection surface for NetCrash |

Raw data lives in `data/raw/` (git-ignored). Processed data in `data/processed/` as Parquet. Each processed table records its source, licence and transform.

### 2. World (`yovahti.world`)

The ground truth that agents never see directly.

- **Topology:** synthetic Turku cluster, about 40 sites and 120 cells at real district coordinates (city centre, Kupittaa stadium, harbour, campus, residential). Each site has one **coverage cell** (LTE 800 MHz, 10 MHz) and one or two **capacity cells** (LTE 1800/2600 MHz, 20 MHz; NR 3.5 GHz, 100 MHz, 32T32R or 64T64R). Neighbour relations and handover targets are explicit.
- **Demand:** each cell gets a real RB-utilisation series from a Slovak sector on the same layer (D19), with Milan adding city-scale spatial structure. Series are resampled to 1-minute with stochastic sub-interval peaks so that minute-level bursts exist. **Events** (match end, concert, ferry arrival, holiday) are injected as multiplicative bumps with spatial spread.
- **Steering:** when a capacity cell sleeps, its demand moves to the co-sited coverage cell, with a configurable share that only the capacity layer can serve (indoor, high-band). Demand above capacity is **unserved**.
- **Local cell-sleep behaviour:** the base station's own minute-level threshold logic (CSM-like) runs inside the world, so baselines that only set thresholds behave realistically between 15-minute updates.
- **Power:** per-RU power model `P = P_static + k · load`, plus sleep states (cell sleep, deep sleep) with wake-up time and transition energy. The load term is **fitted on real Slovak radio-unit energy** (E7); sleep-state power and transitions come from 3GPP TR 38.864, and mode effects from ITU.
- **Batteries (Tier 1):** each site has a backup battery with a protected backup reserve; charging can shift in time.
- **Faults:** telemetry dropout, stale feeds, delayed actuation, actions with unknown outcome, neighbour outage.
- **Clock:** 1-minute steps; decisions every 15 minutes; planning horizon 10 hours (40 quarter-hours, as in Tasehinta).

### 3. Forecaster (`yovahti.forecast`)

- LightGBM quantile models (P10, P50, P90) per horizon bucket, global across cells with cell embeddings and features (calendar, lags, rolling stats, neighbour load, event flags). Same discipline as Tasehinta: walk-forward, calibration on the last 28 days before cutoff, leakage tests.
- Baselines: seasonal naive (same quarter-hour last week), and the persistence of the last value.
- Output: per cell, per quarter-hour, three quantiles plus `P(load > threshold)`.

### 4. Energy model (`yovahti.energy`)

- Fitted on ITU: power vs load per RU type, the effect of each active energy-saving mode (modes 1, 2, 3 and 6 have data, see G3), per-site fingerprint (the "energy fingerprint" result from the ITU challenge paper).
- Exposed as `power(cell, load, state) -> W` and `transition(cell, from, to) -> (J, seconds)`.

### 5. Digital twin (`yovahti.twin`)

- Combines forecaster + energy model + steering model to predict the outcome of a plan: expected kWh, €, CO₂ saved; per coverage cell the P90 peak load; P(any quality breach); wake-ups.
- Deliberately imperfect. Twin fidelity (predicted vs realised savings and breaches) is a reported metric.

### 6. Planner (`yovahti.plan`)

- **As built (D27):** exact dynamic programming per sector over four states (both capacity radios awake, NR 3500 asleep, mid band asleep, both asleep) × 40 quarter-hours, vectorised over all sectors, re-planned hourly; P90 feasibility of the receiving layer and a switch cost. CP-SAT (D9) stays the tool for constraints across sectors (blast radius, conflicts), which the arbiter enforces today.
- Original design: OR-Tools CP-SAT (D9). Decision: per capacity cell per quarter-hour, a state in {awake, cell sleep, deep sleep}.
- Constraints: coverage cell load at **P90** forecast (plus moved demand) ≤ ρ_max; protected cells never sleep; minimum dwell time; maximum toggles per day; deep sleep only in windows ≥ minimum length; at most X % of a cluster asleep at once (blast radius); operator constraints from the agent (pins, windows).
- Objective: maximise Σ price_t × kWh_saved_t (or CO₂-weighted) − λ × risk.
- Re-plans every hour (rolling horizon). Solve-time budget a few seconds per cluster.

### 7. Baselines (`yovahti.baselines`) (see [EVALUATION.md](EVALUATION.md))

B0 always-on · B1 static thresholds · B2 reconstruction of Ericsson's published method (patent WO2024028883A1 + 2023 blog), labelled as a reconstruction · B3 O-RAN SC energy-saving demo rApp logic (E9) · B4 Yövahti planner without any LLM.

### 8. MCP server (`yovahti.mcp_server`)

Python `mcp` SDK, **Streamable HTTP** transport (D7). Requests from agents carry an identity (signed Agent Card reference + HTTP Message Signature, RFC 9421).

| Tool | Kind | Returns |
|---|---|---|
| `list_cells(cluster)` | read | cells, layers, roles, protected flags |
| `get_cell_kpis(cells, window)` | read | load, users, throughput proxy, state, **data timestamps** (stale data is visible, not hidden) |
| `get_alarms(cluster, window)` | read | alarms with free text (injection surface) |
| `get_events(window)` | read | event calendar and operator notes (free text) |
| `get_prices(window)` / `get_carbon(window)` | read | €/MWh and gCO₂/kWh per quarter-hour |
| `forecast_load(cells, horizon)` | twin | P10/P50/P90 per quarter-hour |
| `optimise_plan(cluster, horizon, constraints)` | plan | plan + expected kWh/€/CO₂ + risk |
| `simulate_plan(plan)` | twin | predicted outcome and per-cell risk |
| `propose_change(plan, rationale)` | act | `change_id`, approval tier required |
| `apply_change(change_id)` | act | goes through `admit()` and arbiter; signed receipt or a refusal with reasons |
| `get_change_status(change_id)` | act | `applied`, `refused`, `rolled_back` or **`unknown`** |
| `rollback(change_id)` | act | receipt |

In NetCrash, the server runs in **stand-in mode**: same tool names, scripted results (injected text, failures, timeouts), plus a **canary** tool that records any attempt at an irreversible action.

### 9. Agents (`yovahti.agents`)

Own minimal agent loop over an MCP client (D8): bounded steps, full trace logging, OpenAI-compatible endpoint so any model can run it (router for hosted models, llama.cpp for local).

| Agent | Role |
|---|---|
| **Energy agent** | Reads forecasts, prices, events; calls the planner; proposes; explains |
| **Coverage agent** | Protects quality; can veto or request wake-ups; creates real conflicts with the energy agent |
| **Sloppy agent** | Plausible but badly instructed (no "admit missing data", no approval discipline). The Spot Deals of networks |

Each agent has an **Agent Card** (`agents/cards/*.json`): id, vendor domain, version, declared models, allowed tools, scope (clusters, parameters it may touch), risk tier. Signed JWS by the vendor key.

### 10. NetCrash (`yovahti.netcrash`) (see [NETCRASH.md](NETCRASH.md))

Runs agents against stand-in scenarios, 3 runs per test per model; verdicts from actions first, then conservative text checks, then a two-family judge panel; scorecard per agent × model; in-toto Test Result attestation in DSSE, signed, optionally logged to Rekor.

### 11. Trust layer (`yovahti.trust`)

- **As built (D34):** a Python port of agent-trust-kit's signing (JCS, RFC 7638 kid, compact JWS, DSSE, in-toto Test Result), checked against the kit's vectors and by the kit's own verifier; `AttestedAdmission` is `admit()`; trusted tester keys come from `trust/tester.jwks.json`.
- Original design: reuse **agent-trust-kit** (Node) for signing, DSSE, in-toto statements and Rekor (D2).
- `admit()` is ported to Python and **proven compatible** by running agent-trust-kit's own test vectors.
- Decision order: request signature → Agent Card signature and scope → declared model → attestation for (card hash, model, suite version) → score ≥ threshold and coverage ≥ 80 % → not expired. Any failure refuses with a machine-readable reason.

### 12. Arbiter (`yovahti.arbiter`)

Deterministic gate between an admitted proposal and the world.

| Invariant | Rule |
|---|---|
| I1 Capacity | No coverage cell's P90 projected load exceeds ρ_max |
| I2 Protected | Protected cells (hospital, emergency-relevant) never sleep |
| I3 Blast radius | At most X % of a cluster's capacity cells change state in one change |
| I4 Dwell | Minimum dwell time and maximum toggles per cell per day |
| I5 Scope | A change only touches cells and parameters inside the Agent Card scope |
| I6 Admission | Only admitted agent × model pairs reach the arbiter |
| I7 Reversibility | Every applied change has a stored rollback and a signed receipt |
| I8 Approval | Changes above a risk tier need a recorded human approval |
| I9 Conflict | Coverage requests override energy requests on the same cell; no cell flips back within the dwell time (no ping-pong) |

Checked by unit tests, Hypothesis property tests and (Tier 2) Z3 for the linear parts.

### 13. Watchdog (`yovahti.watchdog`)

Monitors the world after each apply. If a coverage cell crosses its limit or unserved demand appears, it wakes cells and records time-to-recovery. It is independent of the agents.

### 14. Reporting and dashboard (`yovahti.report`, `web/`)

- Runs export static JSON (plans, world state per quarter-hour, traces, scorecards, receipts).
- Dashboard (Tier 1): Vite + React + MapLibre. Turku map with cells and their states, replay slider, savings counters, agent trace, NetCrash matrix, in-browser attestation check. Static hosting, no backend (D10).

### 15. Real stack (Tier 2, `deploy/`)

Spike first, then commit (D11). Candidates:
- srsRAN 4G + ZMQ virtual radios + GNU Radio broker for multiple UEs and handover, Open5GS core, on kind.
- OpenAirInterface RF simulator.
- ns-3 with an O-RAN module.

Criterion: within one day, switch a cell off and on programmatically and observe users moving and KPIs changing. The Yövahti rApp runs as a container talking to it. Power for that run comes from the energy model (no physical radios), and that is stated.

## Repository layout (planned)

```
ericsson/                     (GitHub repo: yovahti)
├─ docs/                      these documents
├─ pyproject.toml             uv, Python 3.12
├─ src/yovahti/
│  ├─ data/  world/  forecast/  energy/  twin/  plan/  baselines/
│  ├─ mcp_server/  agents/  netcrash/  trust/  arbiter/  watchdog/  report/
├─ agents/cards/              signed Agent Cards
├─ netcrash/suite/            test definitions (YAML)
├─ trust/                     agent-trust-kit integration (Node), keys (dev only)
├─ tests/                     unit, property, leakage, integration
├─ results/                   scorecards, attestations, run summaries (committed)
├─ web/                       dashboard
├─ deploy/                    Kubernetes manifests, Tier 2
└─ data/                      raw/ processed/ (git-ignored)
```

## Stack

| Area | Choice |
|---|---|
| Language | Python 3.12 via uv (system Python is 3.7, see G5); Node 22 for agent-trust-kit and the dashboard |
| Data / ML | pandas, pyarrow, LightGBM, scikit-learn |
| Optimisation | OR-Tools CP-SAT |
| Agents | `mcp` Python SDK, own loop, OpenAI-compatible client |
| Trust | agent-trust-kit (JWS, DSSE, in-toto, Rekor), `cryptography`, `rfc8785` (JCS) |
| Testing | pytest, Hypothesis, Z3 (Tier 2) |
| Energy of AI | CodeCarbon / NVML on the RTX 4050 for local models |
| Infra | Docker Desktop + WSL2, kind, Helm (Tier 2), GitHub Actions |
| Dashboard | Vite, React, Tailwind, MapLibre |
