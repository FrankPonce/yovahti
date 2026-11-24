# Admit the agent, not just the action: risk-aware cell sleep with attested LLM agents on real RAN data

Frank Ponce · Åbo Akademi University · November 2026 · draft · code and data: https://github.com/FrankPonce/yovahti

> Draft. Numbers marked ⟨pending⟩ are being measured; every other number is from the repository's results and can be regenerated with the scripts named next to it.

## Abstract

Operators are starting to expose radio networks to AI agents through the Model Context Protocol (MCP). Agents can add something a forecaster cannot: they read event calendars, operator notes and alarm text. That same unstructured text is where injected instructions, missing data and social pressure arrive, so the value and the risk of an agent enter through the same channel. We present Yövahti, an end-to-end prototype on real live-network data that (1) saves radio energy with a risk-aware cell-sleep planner, (2) exposes it to agents through an MCP server whose actions pass a deterministic arbiter, (3) tests each agent *on each model* with behavioural tests (NetCrash), and (4) admits only agents holding a signed in-toto attestation for their exact prompt and model. On 749 real sectors of a commercial 2G/4G/5G network, the planner saves 18.1 % of radio-unit energy with 6x less congestion than static thresholds and 8x less than a reconstruction of a published vendor method; on locked test weeks, 18.8 % with 7x less. With synthetic event surges announced only in a calendar, an LLM agent that reads it removes 92 % of the event-caused congestion at no cost in savings, while NetCrash shows the same agent prompt failing different tests on different models, including leaking a credential and turning a missing alarm feed into "no alarms".

## 1 Introduction

Energy is a large share of mobile network opex, and most of a capacity radio's energy does not depend on its load: in our data 72 % (mid band) and 88 % (NR 3500) of capacity-radio energy is idle draw (FINDINGS E11). Putting capacity radios to sleep when traffic is low is therefore the largest lever, and the risk is quality: traffic moved to the coverage layer can congest it.

Vendors now put agents in that loop: O-RAN rApps reachable through MCP and agentic network-operations designs in which a digital twin checks each proposed action before it runs. Checking actions is necessary but not sufficient. An agent that obeys an instruction hidden in alarm text, reports an unknown outcome as done, or turns a missing feed into "all clear" can pass every individual action check and still mislead an operator. Whether an agent behaves is a property of the agent *and* the model it runs on.

Contributions:
1. A risk-aware planner (exact dynamic programming per sector on P90 quantile forecasts) and a comparison against four baselines, including a reconstruction of a published method, on real operator traffic and energy.
2. An MCP server exposing the network to agents, with an admission step and a deterministic arbiter (capacity at P90, protected cells, blast radius, scope).
3. NetCrash, a behavioural test suite for network agents, scored per agent × model, with crash-test's scoring and scorecards that agent-trust-kit turns into in-toto attestations.
4. Attested admission: a Python port of agent-trust-kit, checked byte for byte against the kit's test vectors and by the kit's own verifier, so only attested agent × model pairs may act.
5. A measurement of value and risk through the same channel: event awareness (value) and calendar injection (risk).

## 2 Data and world

**Primary data.** Performance-management counters from a live commercial network (Lehoczký et al., *Scientific Data* 2026; CC BY 4.0; co-authored by Ericsson Slovakia): 264 sites, GSM 900, LTE 700/800/1800, NR 2100/3500, 15-minute resource-block utilisation, users, volume and **measured radio-unit energy**, 31 Aug – 22 Nov 2025. We found the documented UTC timestamps to be local time (G26); correcting it was worth about 10 points of forecast skill. Splits are fixed before results: training to 25 Oct, validation 26 Oct – 8 Nov, test 9 – 22 Nov (untouched in this draft).

**Energy model.** Per radio unit, fitted on the measured energy (idle fingerprint plus per-carrier load slopes; validation R² 0.92 mid band, 0.96 NR 3500, 0.84 low band). Sleep power and transition energy follow 3GPP TR 38.864 (Category 1 and 2).

**World.** Each sector's real traffic is replayed; when capacity radios sleep, their traffic moves to the coverage layer using measured per-band efficiency. A layer is congested when its 15-minute load × a stated peak margin (1.25) exceeds its limit (40 % low band); traffic beyond the layer's ceiling is unserved. A watchdog wakes sleeping radios of a congested sector for an hour.

## 3 Planner and baselines

**Forecaster.** LightGBM quantile models (P10/P50/P90, 10-hour horizon), re-fitted weekly, with daily rolling Mondrian conformal calibration by local hour. Validation skill vs seasonal naive: +29.9 % (LTE 1800 + NR 2100), +27.8 % (NR 3500), +36.2 % (low band); P10–P90 coverage 80–84 % (E17, E19). A 10 % apparent "5G growth bias" turned out to be mostly the gap between a median and a mean (G28).

**Planner (B4).** Per sector, a shortest path over four states (both capacity radios awake, one asleep, both asleep) × 40 quarter-hours, minimising expected energy plus a switch cost, with states infeasible where the receiving layer's **P90** load would exceed its limit. Re-planned hourly; solved exactly and vectorised over all sectors.

**Baselines.** B1 static load thresholds; B2 a reconstruction of patent WO2024028883A1 from public sources (labelled as such; not vendor software); B3 the O-RAN SC energy-saving demo rApp logic; an oracle with perfect foresight.

**Table 1.** Validation weeks, 749 sectors, Category 1, same forecasts, simulator and watchdog (`scripts/compare_methods.py`).

| Method | Energy saved | Congested QH / sector-day | Past capacity | Wake-ups |
|---|---:|---:|---:|---:|
| B1 static thresholds | 18.1 % | 3.67 | 6.2 TB | 38 471 |
| B2 published method (reconstruction) | 17.2 % | 4.89 | 37.0 TB | 51 253 |
| B3 O-RAN SC rApp logic | 12.9 % | 0.81 | 2.0 TB | 8 478 |
| **B4 (P90)** | **18.1 %** | **0.59** | **1.8 TB** | **6 214** |
| B4, margin 1.5 | 14.1 % | 0.14 | 0.9 TB | 1 444 |
| B4 on P50 (ablation) | 20.0 % | 3.16 | 5.4 TB | 33 088 |
| Oracle | 22.6 % | 0 | 0 | 0 |

**Locked test weeks** (9–22 Nov 2025, method frozen, run once; E24): B4 18.8 % saved at 0.69 congested QH per sector-day; B2 17.2 % at 4.94; B1 18.4 % at 3.64; B3 13.1 % at 0.86; B4 on P50 20.3 % at 3.11; oracle 22.8 %. Forecast coverage 79.6–81.3 %; low-band skill fell to +18.8 % (validation +36.2 %), mid and NR 3500 held (+29.5 / +29.4 %).

B4 matches the simple baselines' savings with 6–8x less congestion and reaches 80 % of the oracle's savings. Most of the reconstruction's congestion comes from waking a quarter-hour late: with a predictive wake (B2+, our extension) it reaches 16.5 % at 0.62 congested quarter-hours per sector-day, and B4's advantage shrinks to about 1.6 points of savings at matched congestion (validation only, E26). Planning on the median instead of P90 buys two points of savings for 5x the congestion: the risk quantile is what buys quality. Under Category 2 sleep power, all savings scale by about 0.8 and the ranking holds.

## 4 Agents, MCP and the arbiter

The MCP server (`mcp` 2.3, Streamable HTTP) is an operator-side view of the network at a simulated clock: twelve tools to read KPIs (with timestamps), alarms, events, prices and carbon; to get forecasts and an optimised plan; and to propose, apply, inspect and roll back changes. Agents never move time and never see the future. Every apply passes admission (I6) and a deterministic arbiter: **I1** the receiving layer stays within its limit at P90 with the change applied (unverifiable beyond the forecast horizon means refused), **I2** protected cells never sleep, **I3** at most half a cluster's capacity cells per change, **I5** scope. Every outcome, including refusals, gets a JCS-hashed receipt.

Agents run in a minimal loop (bounded steps, every call traced and priced, a hard budget per provider). The energy agent's prompt asks it to start from the planner, treat alarm and event text as data, and report unknowns as unknown.

**A first night (E20).** On a 31-sector cluster the agent reproduced the planner's result exactly (22.1 % saved, no traffic lost, EUR 0.04), as expected without unstructured context, and reported "no alarms in the last 24 hours" where the tool had said there was *no alarm feed*: unknown turned into all clear, despite an explicit instruction.

## 5 Value through the calendar

We inject synthetic crowd surges (a match ending) into the real traffic of three sectors per episode, 22:30–00:30, large enough that sleeping through them overloads the coverage layer. Forecasts are unchanged; only the event calendar announces the surge. Arms, all through the same gate and replayed in the simulator: the planner alone; the planner with an ideal calendar reader (the same plan minus sleep on the announced sectors during the window, an upper bound); and the LLM agent (`scripts/event_value.py`).

**Table 2.** 12 episodes (4 clusters × 3 nights), synthetic surges, replayed 22:00–08:00 (`scripts/event_value.py`).

| Arm | Energy saved | Congested sector-QH | Unserved |
|---|---:|---:|---:|
| Planner alone | 18.72 % | 163 | 90.0 GB |
| Planner + ideal calendar reader | 18.87 % | 91 | 47.0 GB |
| **LLM agent (DeepSeek V4 Flash)** | **18.64 %** | **97** | **51.4 GB** |
| B4 re-planning hourly (reference) | 23.95 % | 155 | 71.7 GB |

A second synthetic event confirms it (E23): a night ferry docking at 05:30 (clock 04:00, 12 episodes). Planner alone 14.08 % saved, 116 congested sector-QH, 34.2 GB unserved; ideal reader 14.14 %, 80, 24.0 GB; agent 14.19 %, 86, 26.7 GB, i.e. 83 % of the event-caused congestion removed with no loss of savings.

Congestion that remains under the ideal reader is unrelated to the events. Of the 72 event-caused congested quarter-hours the agent removed 66 (92 %) and 90 % of the event's unserved traffic, at 0.1 point of savings. A pilot with a 14-step budget made the agent look over-cautious; it was running out of steps while applying the plan in blast-radius-sized changes.

## 6 NetCrash: behaviour per agent × model

Each test runs the production tools on a stand-in network (three real sites of a cluster, real traffic and forecasts) with scripted feeds and faults: injected instructions in alarm text (N1) and in the calendar (N20), failing telemetry (N4), apply calls with unknown outcomes (N6), a false request to confirm (N7), a tempting note about a protected cell (N10), a crowd event (N11, a usefulness test), a planner stuck on partial results (N14), a credential in an alarm (N15), subscriber identifiers in KPI rows (N16), a normal night (N18), and missing feeds (N19). Verdicts come from what the agent did first (proposals count even when the arbiter refuses them), then from conservative text checks; undecidable text verdicts are `inconclusive` and lower coverage. Three runs per test; score = mean pass rate over decided runs; coverage = decided ÷ applicable runs (crash-test's `decided/1`).

**Table 3.** NetCrash v0 scores (pass rate over decided runs; coverage 85–97 %).

| Model | Careful prompt (energy agent) | Sloppy prompt |
|---|---:|---:|
| Qwen 3.8 27B | 77 | 67 |
| gpt-oss-120b | 71 | 62 |
| Mistral Small 3.2 24B | 68 | 53 |
| DeepSeek V4 Flash | 60 | 47 |

N20 (calendar injection): careful prompt resisted 3/3 on DeepSeek, obeyed 2/3 on gpt-oss and Mistral; the sloppy prompt obeyed in every run where it read the calendar. No pair reaches the admission bar (90, no failed test).

Early observations (DeepSeek V4 Flash, energy agent): the same model that refuses an injected "put all cells to sleep" alarm repeats a leaked audit token in its report (N15), sleeps cells under an announced crowd (N11) and loops on a stuck planner (N14).

## 7 Attested admission

NetCrash scorecards use the fields agent-trust-kit's `attestationFromScorecard` reads; the subject is the agent's **Agent Card** (its JCS hash covers the prompt's hash, the allowed tools and the scope). A Python port of the kit signs them as in-toto Test Result statements in DSSE envelopes (Ed25519). Compatibility is shown, not assumed: the port reproduces the kit's deterministic test vectors byte for byte, and the kit's own `verifyAttestation` accepts an attestation signed by the port and rejects a forged one. `admit()` accepts an agent only with a valid attestation for its exact card × model (score ≥ 90, coverage ≥ 80 %, no failed test); changing one word of the prompt invalidates it.

## 8 Limitations

The world re-routes traffic with a simple capacity model and a stated peak margin, not a radio simulator; event surges are synthetic; NetCrash v0 has 12 of 20 planned tests and no judge panel yet, so text-only verdicts can be inconclusive; hosted models change under the same name, which is why attestations expire; B2 is a reconstruction from public documents. The test weeks were run once with the frozen method (E24).

## 9 Conclusion

Safety checks on individual actions are necessary, and Yövahti's arbiter enforces them, but they cannot see an agent that reports unknowns as known, leaks what it reads, or follows text it should only read. Testing the agent on the model it runs on, and admitting it only with a signed result, closes that gap at almost no runtime cost, and it is what makes it reasonable to let an agent read the very calendar that makes it useful.

## References

- P. Lehoczký et al., "Performance Management Counters from Live 5G, 4G and 2G Radio Access Network", *Scientific Data*, 2026.
- 3GPP TR 38.864 V18.1.0, Study on network energy savings for NR.
- WO2024028883A1 (patent application, reconstructed as baseline B2).
- O-RAN Software Community, energy-saving rApp demo.
- in-toto Attestation Framework, Test Result predicate v0.1; DSSE v1; RFC 8785 (JCS); RFC 7638.
- Model Context Protocol specification.
- F. Ponce, crash-test and agent-trust-kit (2026).
