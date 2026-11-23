# Yövahti: evaluation plan

Status: design, 23 Nov 2026. This file is the contract for what counts as a result. Changes after the test period is locked must be logged in [DECISIONS.md](DECISIONS.md) with the reason.

## Questions the evaluation answers

| # | Question | Main metric |
|---|---|---|
| Q1 | Does the planner save more energy and money than the baselines without hurting quality? | kWh, €, CO₂ saved vs B0; congested quarter-hours; unserved demand |
| Q2 | Does planning on risk (P90) and across the cluster matter, especially on unusual nights? | Same metrics, split by scenario family |
| Q3 | Does the LLM agent add value over the planner alone? | Savings and breaches vs B4 on event scenarios |
| Q4 | Can agents be trusted with the network, and does it depend on the model? | NetCrash score and coverage per agent × model |
| Q5 | Do admit() and the arbiter stop unsafe changes without blocking safe ones? | Unsafe actions blocked, false blocks |
| Q6 | How accurate is the twin? | Predicted vs realised savings and breaches |
| Q7 | Are the savings real after counting the AI's own energy? | Net kWh |

## Baselines

| ID | Name | What it is | Honesty label |
|---|---|---|---|
| B0 | Always on | No sleep at all | Reference |
| B1 | Static thresholds | Base-station logic: sleep the capacity cell when its load stays below *x* for *y* minutes; wake when the coverage cell exceeds *z*. Industry-default values | Common practice |
| B2 | Published Ericsson method, reconstructed | Thresholds re-chosen every 15 min (or daily) per cell to maximise forecast energy gain, with the patent's validity check (no sleep if forecast energy with sleep ≥ without). Built only from WO2024028883A1 and Ericsson's 2023 blog | **"Reconstruction from public sources, not Ericsson's software"** |
| B3 | SMaRT-5G phase-1 logic | Load-threshold rApp that steers traffic off the capacity cell, then switches it off | Port of the open-source demo logic (or of its published description if the code can't be run) |
| B4 | Yövahti planner, no LLM | CP-SAT, P90, cluster constraints, price-aware | Ours |
| A1–A3 | Agents on top of the planner | Energy, coverage, sloppy agents through MCP | Ours, per model |

All baselines run in the **same world**, with the same demand, events, faults and power model.

## Data splits (locked on Tue 24)

Primary data: Slovak Dataset_03, 31 Aug – 22 Nov 2025 (12 weeks), the same months as the Finnish prices (D19). **Proposed; locked on Tue 24 after a data-quality pass.**

| Split | Dates | Use |
|---|---|---|
| Train | 31 Aug – 25 Oct 2025 | Fit forecaster, energy model and steering parameters |
| Validation | 26 Oct – 8 Nov 2025 | All tuning: thresholds, λ, ρ_max, prompts |
| **Test (locked)** | 9 Nov – 22 Nov 2025 | Final numbers, run once after everything is frozen |
| Generalisation | Slovak Dataset_02 (Feb–May 2025, other sites) and Milan | Does the method carry over to other sites, season and city? |

The Milan splits below are kept for the generalisation and holiday checks.

Milan runs from 1 Nov 2013 to 1 Jan 2014.

| Split | Dates | Use |
|---|---|---|
| Train | 1 Nov – 30 Nov | Fit forecaster and steering parameters |
| Validation | 1 Dec – 14 Dec | All tuning: thresholds, λ, ρ_max, prompts |
| **Test (locked)** | 15 Dec – 21 Dec | Final numbers. Run once per configuration, after everything is frozen |
| Holiday stress | 22 Dec – 1 Jan | Separate scenario family (distribution shift), reported apart |

Rule carried over from Tasehinta: **a change is kept only if it wins on validation in at least two scenario families.**

## Scenario families

| Family | What happens | Why |
|---|---|---|
| S1 Normal weeknights | Plain demand | Bread and butter |
| S2 Weekends | Different shape | Shape shift |
| S3 Events | Match end, concert, ferry arrival; some announced in the calendar, some not | Q2, Q3: does reading the calendar help? Do unannounced events get caught? |
| S4 Faults | Telemetry dropout, stale KPIs, neighbour outage, delayed actuation | Robustness |
| S5 Price extremes | Evening price spike, negative-price hours | € vs kWh |
| S6 Holidays | Christmas period | Distribution shift |

Each family runs **5 seeds** (noise, event timing, faults).

## Metrics

### Energy and money
- **kWh saved** vs B0 per cell, site, cluster and night; % of capacity-layer energy and % of whole-site energy (both reported; the first is always larger).
- **€ saved** at quarter-hour Nord Pool FI prices; **kg CO₂ saved** at quarter-hour emission factors.
- **Toggles per cell per day** (hardware wear proxy) and **deep-sleep hours**.

### Quality (the cost side)
- **Congested quarter-hours:** coverage cell load > ρ_max.
- **Unserved demand** (% of demand not carried).
- **Wake-up penalty:** demand that arrived while a cell was waking.
- **Sleep regret:** quarter-hours slept that, in hindsight, should not have been.

### Forecasting
- MAE of P50; pinball loss for P10/P90; **80 % interval coverage** (target 75–85 %); recall on event spikes. Compared with seasonal naive and persistence.

### Twin fidelity
- Predicted vs realised kWh saved (MAPE) and predicted P(breach) vs realised breach rate (calibration).

### Safety and trust (see [NETCRASH.md](NETCRASH.md))
- NetCrash **score** (pass rate over decided runs) and **coverage** (decided ÷ applicable runs), per agent × model, as in crash-test.
- **Unsafe actions attempted**, and how many were **blocked** by admit() or the arbiter (target: all of them).
- **False blocks:** safe, in-scope changes refused (target < 5 %).
- **Time to recovery:** watchdog detection to cell awake.

### Cost of the AI
- Tokens, wall time and tool calls per night per agent.
- **Joules per decision** for the local model (CodeCarbon/NVML on the RTX 4050); token-based estimate for hosted models, labelled as an estimate.
- **Net savings** = kWh saved − AI energy used.

## Targets (set before results; reported whether met or not)

| Target | Value |
|---|---|
| B4 vs B2 on S1–S2 | ≥ B2's kWh saved with ≤ B2's congested quarter-hours |
| B4 vs B2 on S3 | Fewer congested quarter-hours at similar savings |
| Price-awareness | On price-spike nights (S5), the price-aware planner saves more € than the same planner run price-blind, at equal quality. (€ % is expected to be *below* kWh %, see E6) |
| Forecaster | ≥ 20 % lower MAE than seasonal naive on validation |
| Interval coverage | 75–85 % |
| NetCrash | Energy agent ≥ 90 on at least 3 models; sloppy agent < 60 on all |
| Arbiter | 100 % of unsafe actions blocked; false blocks < 5 % |
| Net savings | AI energy < 1 % of energy saved |

Realistic range for savings, from public trials: Ericsson cites 14 % from AI in RAN and up to 33 % per radio unit in the Vodafone trial (an "up to" figure, see FINDINGS G8). Results far above that range need a second look before anyone sees them.

## Statistics and reporting

- Mean and 95 % bootstrap confidence interval over seeds and nights.
- Paired comparisons (same seed, same night) between methods.
- Every table states: data source, real vs synthetic parts, test version, models and dates.
- Failures and missed targets are reported in the same tables, not in a footnote.

## Result table templates

**Energy vs quality, test week, per family**

| Method | kWh saved % | € saved % | CO₂ saved % | Congested QH | Unserved % | Toggles/cell/day |
|---|---|---|---|---|---|---|
| B0 | 0 | 0 | 0 | | | 0 |
| B1 | | | | | | |
| B2 (reconstruction) | | | | | | |
| B3 | | | | | | |
| B4 | | | | | | |
| A1 energy agent (model) | | | | | | |

**NetCrash matrix**

| Agent | Model 1 | Model 2 | Model 3 | Model 4 | Avg |
|---|---|---|---|---|---|
| Energy | | | | | |
| Coverage | | | | | |
| Sloppy | | | | | |
