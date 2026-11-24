# Open issues, risks and questions

Things to address later. Each says when it must be settled. Close an issue by moving it to the bottom with the date and the outcome; don't delete it.

## Needs Frank's input or action

| ID | Issue | Why it matters | When |
|---|---|---|---|
| I8 | **Disk space for Tier 2.** ~20 GB more free space would make the real stack comfortable | 50 GB free now; Docker WSL disk grows and doesn't shrink | Before Wed 25 |
| I11 | **Azure / cloud credits** for the enclave moonshot (confidential VM, AMD SEV-SNP or Intel TDX) | Tier 3 needs hardware we don't have locally | Phase 2 |

## Data

| ID | Issue | Plan | When |
|---|---|---|---|
| I4 | ITU dataset licence is not stated in the mirror repo | Check the ITU challenge terms; until then, use it for research only and don't redistribute the raw files | Tue 24 |
| I5 | Milan (2013) + prices (2025–26) are different years | Align by weekday and quarter-hour; label results as a synthetic composition (G9) | Tue 24 |
| I6 | Milan "internet activity" is a relative activity index, not Mbps or PRBs | Scale per square to a target busy-hour utilisation per cell type; document the mapping and test sensitivity to it | Tue 24 |
| I7 | Milan is ODbL (share-alike for derived databases) | Publish derived per-cell series under ODbL with attribution, separate from code licence | Sun 29 |
| I24 | Energy-Charts prices are for internal use only (G10) | Switch to ENTSO-E (free token) before publishing € results; check reuse terms | Sat 28 |
| I25 | Turku Linked Events API doesn't resolve (G15) | Find the current endpoint or hand-write events from public schedules | Thu 26 |
| I29 | Per-user throughput proxy for moved users (G22) | Capacity per active user before vs after moving; report alongside congestion | S5 |
| I28 | Slovak public holidays Sep–Nov 2025 (some may have changed in 2025) | Check an official calendar before building holiday features (G20) | S4 |

## Baselines and fairness

| ID | Issue | Plan | When |
|---|---|---|---|
| I3 | B3 baseline source | Now the O-RAN SC energy-saving demo rApp (E9); SMaRT-5G only as a reference (its TS-xApp is `onosproject/rimedo-ts`) | S5 |
| I14 | **B2 must be a fair reconstruction**, not a strawman | Implement the patent's steps faithfully, tune it on validation with the same budget as B4, and write down every assumption | Wed 25 |
| I15 | Patented method used in a research prototype | Not distributed as a product; clearly labelled as a research reconstruction from public documents | Ongoing |

## Technical risks

| ID | Issue | Plan | When |
|---|---|---|---|
| I16 | Open-source RAN stacks lack a standard O1 interface for switching cells | First candidate: O-RAN SC SMO flavour `ranpm-pynts-es-rapp` with DU simulators and NCMP `administrativeState` (E9); then srsRAN / OAI / ns-3 | S6 |
| I17 | A full O-RAN SC Non-RT RIC deployment may not fit 16 GB RAM next to the RAN stack | Deploy only the pieces needed, or emulate the rApp interface and say so | Thu 26 |
| I18 | Small models may fail the agent loop for format reasons, not trust reasons | Separate "couldn't use tools" (`error`/`inconclusive`) from "unsafe" (`fail`) | Fri 27 |
| I19 | Judge panel cost and availability | Two cheap models; cache verdicts by run hash | Fri 27 |
| I20 | MCP identity: the MCP spec's auth is OAuth-based, not agent-identity-based | Signed Agent Card + RFC 9421 request signatures on Streamable HTTP; document it as an extension | Thu 26 |
| I21 | Hosted-model energy can't be measured | Token-based estimate with a published per-token figure, labelled as an estimate | Sat 28 |
| I22 | Windows + WSL quirks (paths, Docker networking, line endings) | Run Tier 2 inside WSL Ubuntu; keep core cross-platform | Ongoing |
| I30 | MCP view shows measured (un-slept) traffic: scheduled sleep doesn't yet re-route load or trigger the watchdog | Close the loop with `world.sim` per quarter-hour when agents run (S7) | S7 |
| I31 | MCP clusters are placeholder groups of ten site ids, not real neighbourhoods | Replace with the Turku layout / neighbour relations (S3) | S3 |
| I32 | Arbiter covers I1, I2, I3, I5, and I6 via `AttestedAdmission` (D34); approval tier is reported but not enforced; receipts are hashed, not signed | I4 dwell, I7 DSSE-signed receipts, I8 recorded approval, I9 conflicts in S8 | S8 |
| I33 | Change status `unknown` is never produced yet | Needs fault injection (delayed actuation, lost acks) in the world (S3) and NetCrash N-tests | S9 |

## Opened 24 Nov (session 5)

| # | Issue | Plan | When |
|---|---|---|---|
| I38 | Site, README and paper say "7–8x less congestion than the published method" | Qualify: vs the plain reconstruction; vs B2+ about +1.6 points at matched congestion (E26) | Done in README, site, paper, video script (24 Nov); live site needs a redeploy |
| I39 | Real-model runs of N22 (twin gaming), N23 (coverage agent) and an hourly night | Run after the v2 matrix, within the caps | Next |

## Questions to revisit

- Should the arbiter's limits come from the operator's intent (TM Forum-style intents) rather than config? Phase 2.
- Is there value in an energy-aware **IMS** angle (IMS gateway workloads scaled by traffic) to speak to the IMS GW team directly? Probably not this week; note for the interview.
- Could Elisa-style battery participation in Fingrid reserves be a scenario family (S7)? Tier 1 if time allows.

## Closed

- **I34** (Rekor) · closed 24 Nov: v1 scorecards in production, verified (E34, D44).
- **I35** (real RAN) · closed 24 Nov as a spike: srsRAN 4G in the loop (E33, D43); O-RAN SC interfaces are the next step.
- **I36** (local model energy) · closed 24 Nov: measured 7.6 Wh per agent night on the RTX 4050, 0.035 % of savings (E36).
- **I37** (tool scope) · closed 24 Nov: calls outside the bound card are refused (E35).
- **I14** (fair B2) · 24 Nov: B2+ with predictive wake reported next to B2 (E26, D41).
- **I19** (judge panel) · closed 24 Nov: Gemma + Llama, both must agree, cached (D40).
- **I20** (MCP identity) · closed 24 Nov: RFC 9421 signatures + operator key bindings (D39).
- **I21** (hosted-model energy) · 24 Nov: estimate from published figures (E30); measurement is I36.
- **I29** (per-user throughput) · closed 24 Nov: proxy reported (E27).
- **I30** (closed loop) · closed 24 Nov: the MCP network steps the world (D37).
- **I31** (clusters) · partly 24 Nov: rhythm clusters (E31); no coordinates in the data for real neighbourhoods.
- **I32** (arbiter I4/I7/I8/I9) · closed 24 Nov (D38).
- **I33** (status unknown) · closed 24 Nov: lost acknowledgements in the world faults (D37), NetCrash N21.

- **I27** (Slovak disk use) · closed 23 Nov: converted to Parquet, 3.8 GB → ~485 MB.

- **I26** (Slovak units) · closed 23 Nov: Wh per 15 min per radio unit and baseband (G18).
- **I13** (absolute power calibration) · closed 23 Nov: real Slovak Wh for the load term, TR 38.864 for sleep states (G18, G19).

- **I1** (LLM access and budget) · closed 23 Nov: Otari (EU) and Featherless keys set and tested; caps €6 and ~€10 (D20).
- **I2** (Rekor production) · closed 23 Nov: approved (D21).
- **I9** · closed 23 Nov: resolved privately.
- **I23** (Milan guestbook) · closed 23 Nov: Frank approved sending his details via the API; details live only in the git-ignored .env.
- **I10** (repo visibility and name) · closed 23 Nov: public `FrankPonce/yovahti` (D22).

- **I12** (Milan download size) · closed 23 Nov: 62 files, 20.8 GB; handled by day-by-day processing (D18).
