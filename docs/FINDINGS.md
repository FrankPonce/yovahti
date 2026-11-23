# Findings: eurekas and gotchas

A dated log of what building Yövahti teaches us. **Eureka (E)** = an insight that changes how we think about the problem. **Gotcha (G)** = a trap in data, tools or assumptions that would have produced a wrong result. Entries are never deleted; if one turns out wrong, add a new entry that corrects it.

Format: ID · date · title, then **What**, **Why it matters**, **Action**.

---

## Eurekas

### E1 · 2026-11-23 · Value and risk enter through the same door
**What:** The planner handles numbers. The only thing an LLM agent adds that a forecaster can't is reading unstructured context: event calendars, operator notes, alarm text, tickets. That same text is where injected instructions, misleading notes and pressure ("I'm the NOC lead") arrive.
**Why it matters:** It ties the energy half and the trust half into one argument. You can't get the agent's value without opening the attack surface, so the agent has to be tested and admitted.
**Action:** Scenario family S3 (events) measures the value; NetCrash N1–N3, N7, N11 measure the risk on the same channel. Report them side by side.

### E2 · 2026-11-23 · Ericsson checks actions; nobody publicly checks agents
**What:** Ericsson's published design (agentic AI white paper, digital twin blog, EIAP with AWS) tests each proposed action in a twin, with policy limits, approval tiers and rollback. Benchmarks test skill. Standards bodies ask for agent identity and trust but haven't defined behavioural attestation.
**Why it matters:** This is the gap. A twin can't catch an agent that is safe on today's action and gets talked into a bad one tomorrow.
**Action:** Yövahti does both: arbiter + twin for actions, NetCrash + admit() for agents.

### E3 · 2026-11-23 · The timescale gap in threshold-based cell sleep
**What:** The base station compares utilisation to sleep and wake thresholds within seconds, but an rApp can only change those thresholds every 15 minutes or more (arXiv 2607.17747).
**Why it matters:** Sudden events between updates (a match ending, a ferry docking) are where a threshold-only method can be caught out. Hypothesis, not a known flaw.
**Action:** The world simulates at 1-minute resolution with local threshold logic, so B1/B2 behave realistically between updates. Test in S3.

### E4 · 2026-11-23 · Optimising each cell alone ignores the shared coverage layer
**What:** Published per-cell methods choose thresholds per cell. Neighbouring capacity cells falling asleep together all push users onto the same coverage cells.
**Why it matters:** Cluster-aware planning could avoid congestion that per-cell methods can't see. Hypothesis to test.
**Action:** Planner constraint I1 on the coverage cell's P90 load with all moved demand; compare B2 vs B4 on congested quarter-hours.

### E5 · 2026-11-23 · Sleeping changes the data you learn from
**What:** Ericsson's 2023 blog notes they needed field experiments because static thresholds produce no varied data. Any learned sleep policy also shapes its own future training data.
**Why it matters:** A method that looks good offline can drift once it runs. Worth a sentence in the paper even if we don't solve it.
**Action:** Log it as a limitation; Phase 2 idea: off-policy evaluation in the world.

---

## Gotchas

### G1 · 2026-11-23 · ITU "energy" values are not absolute kWh
**What:** ECdata shows values like 64 per site-hour. A real site drawing 64 kW is implausible; the values look normalised or anonymised.
**Why it matters:** Absolute kWh and € from this data would be invented.
**Action:** Use ITU only for **shapes and relative effects** (load slope, mode savings, per-site fingerprint). Calibrate absolute watts from literature and say so in every table.

### G2 · 2026-11-23 · ITU has no geography and few multi-cell sites
**What:** 1 020 sites, 1 217 cells: 827 sites with one cell, 191 with two, 2 with four. No coordinates, no neighbour relations.
**Why it matters:** Coverage/capacity layering and cluster effects can't come from ITU.
**Action:** Synthetic Turku topology (D4); ITU fits per-RU power models only.

### G3 · 2026-11-23 · Some ITU energy-saving modes are almost never active
**What:** Rows with each mode active: ESMode1 6 241, ESMode2 6 053, ESMode3 222, ESMode4 0, ESMode5 3, ESMode6 7 330 (of ~125 k).
**Why it matters:** Only modes 1, 2 and 6 (and weakly 3) can be fitted; 4 and 5 cannot.
**Action:** Model only what the data supports; mark others as literature-based.

### G4 · 2026-11-23 · ITU covers only 8 days
**What:** 1–8 Jan 2023, hourly; median ~110 hours of energy data per site.
**Why it matters:** Far too short to train or test a forecaster.
**Action:** Traffic forecasting uses Milan (62 days, 10-min); ITU stays for energy (D3).

### G5 · 2026-11-23 · System Python is 3.7.9
**What:** `python` on PATH is 3.7.9; uv 0.13.9 is installed.
**Why it matters:** Modern libraries (mcp, OR-Tools, LightGBM wheels) need 3.10+.
**Action:** uv-managed Python 3.12, never the system interpreter.

### G6 · 2026-11-23 · Disk and memory are tight for Tier 2
**What:** 50 GB free of 476 GB (90 % full); 15.7 GB RAM; 20 threads; RTX 4050.
**Why it matters:** Docker images for a real RAN stack plus Kubernetes can take 15–20 GB, and Docker's WSL disk doesn't shrink by itself. A full O-RAN SC deployment is heavy on RAM.
**Action:** Core stays under ~5 GB (download subsets, Parquet). Free ~20 GB before Tier 2. Deploy only the parts of the stack we need.

### G7 · 2026-11-23 · SMaRT-5G is only partly open
**What:** Phase 1 (2023, Rimedo Labs ES-rApp + TS-xApp) code was announced as open on GitHub; in the 2025 Aether phase the rApp algorithm internals are proprietary.
**Why it matters:** B3 must use phase-1 logic, and we must find the actual repo.
**Action:** ISSUES I3.

### G8 · 2026-11-23 · Trial numbers are "up to" figures
**What:** Vodafone/Ericsson: "up to 33 %" daily power reduction at 5G radio units in trial sites; Deep Sleep "up to 70 %" in low-traffic hours; Telefónica "up to 8 %" of a site's 24 h. AI in RAN: 14 %.
**Why it matters:** Comparing our averages to their peaks would flatter them or us.
**Action:** Compare like with like (per radio unit vs per site, low-traffic hours vs 24 h) and say which.

### G9 · 2026-11-23 · Milan is 2013, prices are 2025–2026
**What:** Traffic and price data come from different years.
**Why it matters:** Pairing them is a synthetic composition, and calendars differ (weekday, holidays).
**Action:** Align by weekday and quarter-hour of the week; label it in every result. ISSUES I5.

### G10 · 2026-11-23 · The free price API forbids external use
**What:** Energy-Charts (Fraunhofer ISE) returns FI day-ahead prices without a key, but its licence says the data is "for private and internal use only" and external use, raw or derived, is prohibited.
**Why it matters:** Published € results built on it could break those terms.
**Action:** Use it for development only (data/ is git-ignored). Before publishing numbers, switch to ENTSO-E Transparency (free token) and check its reuse terms (ISSUES I24).

### G11 · 2026-11-23 · Milan is 20.8 GB and behind a guestbook
**What:** 62 daily files of ~320 MB. Harvard Dataverse refuses API downloads without a guestbook response (name, email, institution) for guestbook 96.
**Why it matters:** Too big for the free disk if kept raw; and the guestbook is personal data, which only Frank can agree to send.
**Action:** The downloader streams one day at a time, aggregates over country codes to Parquet and deletes the raw file (~1 GB total). Waiting on Frank for the guestbook (ISSUES I23).

### G12 · 2026-11-23 · The MCP Python SDK is at 2.x
**What:** `mcp` resolved to 2.3.0. Most examples online are for 1.x (FastMCP).
**Why it matters:** Copying 1.x examples may not work.
**Action:** Pin `mcp>=2.3,<3` and read the 2.x API before building the server.

### E6 · 2026-11-23 · Cells sleep when power is cheapest, so € savings lag kWh savings
**What:** FI day-ahead, Oct 2025 – Nov 2026 (40 129 quarter-hours): median price by local hour is about 20 €/MWh at 03:00 and 47 €/MWh at 19:00; 1 % of quarter-hours are negative; the maximum is 655 €/MWh.
**Why it matters:** Night-time cell sleep saves kWh exactly when they're worth least. The € share of savings will be *below* the kWh share. The original EVALUATION target (€ % > kWh %) was wrong. Price-awareness pays off in spike hours, evening MIMO-style partial sleep and battery timing, not in the night-time bulk.
**Action:** Target replaced before any results (DECISIONS D17). Report € and kWh shares side by side and show where price-awareness changes a decision.

### G13 · 2026-11-23 · Milan's "internet activity" barely dips at night
**What:** On 1 Nov 2013, citywide internet activity at its lowest hour (05:00) is still 48 % of the peak hour. Real RAN load usually falls much further at night. 1 Nov is also a public holiday in Italy (All Saints' Day). Per-square daily totals vary about 25× from p10 to p90.
**Why it matters:** Milan's internet activity counts data sessions (including background keep-alive traffic), not bytes or PRBs. Used raw as cell load, it would make night-time savings look far smaller than they are. Used carelessly the other way, it could inflate them.
**Action:** The demand mapping (ISSUES I6) needs an explicit activity-to-load transform, calibrated to published day/night load ratios and stated in every result, with a sensitivity check. Check normal weekdays before drawing conclusions from 1 Nov. The wide spread across squares is good: it gives sites very different profiles.

### E7 · 2026-11-23 · An open dataset of a live RAN with real energy, co-authored by Ericsson Slovakia
**What:** Lehoczký et al., *Scientific Data* (July 2026), Zenodo 10.5281/zenodo.17815388, CC BY 4.0. 15-minute sector-level PM counters (RB utilisation, RRC and active users, data volume, CQI, MIMO rank) plus radio-unit and baseband energy from a commercial operator. Dataset_03: 264 sites with GSM 900, LTE 700/800/1800 and NR 2100/3500 on the same sites, 31 Aug – 22 Nov 2025. First look at Dataset_01 (LTE 2100, 25 sites, Mar–Oct 2023): median RB utilisation falls to 12 % of its peak at 05:00; a linear fit puts radio-unit energy at 0 % load at about 45 % of its value at 50 % load.
**Why it matters:** Real load and energy on real multi-layer sites replace most of the synthetic guesswork (G1, G2, G4, G13). The fixed energy share is exactly what sleep modes save. The authors include Ericsson people, so building on their dataset is a natural conversation opener.
**Action:** Primary data source (D19). Cite both the data descriptor and the Zenodo DOI.

### G14 · 2026-11-23 · Slovak energy is per radio unit and baseband, not per cell; units unconfirmed
**What:** The README says energy is reported at radio-unit and baseband level. Medians of 47 (radio unit) and 85 (baseband) per 15 minutes would be about 190 W and 340 W if they are Wh, which is plausible, but the descriptor must confirm. One multi-band radio unit can serve several carriers.
**Why it matters:** Savings from sleeping one carrier can't be read off directly.
**Action:** Read the field dictionary (ISSUES I26); model energy per radio unit with per-carrier load terms; state units in every table.

### G15 · 2026-11-23 · The Turku Linked Events API doesn't resolve
**What:** `api.turku.fi/linkedevents/v1/` fails DNS (curl exit 6). Older pages list it as CC BY 4.0 open data.
**Why it matters:** A real Turku event calendar would make the unstructured channel (E1) concrete.
**Action:** ISSUES I25: find the current endpoint, or hand-write events from public schedules (ferry arrivals 07:35 and 19:50 daily, published match dates).

### G16 · 2026-11-23 · Prices before October 2025 are hourly
**What:** FI prices are hourly until 30 Sep 2025 and 15-minute from 1 Oct 2025.
**Why it matters:** September in the training period has hourly prices.
**Action:** Forward-fill hourly prices to quarter-hours and flag them.

### G17 · 2026-11-23 · API hosts: Otari keys are region-bound; Fingrid's API is on data.fingrid.fi
**What:** Otari answers 421 "This API key belongs to eu.api.otari.ai" on the global host. The Fingrid API is `https://data.fingrid.fi/api/datasets/{id}/data` with an `x-api-key` header (the `data.api.fingrid.fi` host doesn't exist).
**Why it matters:** Wasted calls and confusing errors.
**Action:** `.env` uses `eu.api.otari.ai`. All three keys tested: Fingrid dataset 265 returns 3-minute values (~26.5 gCO₂/kWh on 1 Nov 2025), Featherless lists 50 models, Otari lists 311 models and answered a test chat.

### E8 · 2026-11-23 · Radio energy savings count toward Ericsson's own climate target
**What:** Ericsson's SBTi-approved targets: net zero in own activities by 2030, a 50 % cut in supply-chain and **portfolio-use** emissions by 2030, and net zero across the value chain by 2040 (90 % absolute cut from 2020). Portfolio use means operators running Ericsson equipment. Ericsson's own activities are under 0.5 % of its footprint, so product use dominates.
**Why it matters:** Energy saved in operators' radio networks reduces Ericsson's own reported scope 3 emissions, not just the operator's bill. Savings are a climate commitment as much as a cost cut.
**Action:** Report CO₂ alongside kWh and € (Fingrid emission factors) in every result.

### G18 · 2026-11-23 · G14 resolved: Slovak energy is Wh per 15 minutes, per radio unit and baseband
**What:** The data descriptor (open full text, PMC13696700) confirms: "Radio unit energy consumption" and "Baseband energy consumption" are **watt-hours over a 15-minute interval**; data volume is in **megabytes**; RB utilisation is a **%**. Channel bandwidths: LTE B20/B28 10 MHz, LTE B1/B3 20 MHz, NR n28 10 MHz, NR n1/n3 20 MHz, NR n78 100 MHz. Site layout: baseband 1 = GSM on 700/800/900 multi-band RRUs; baseband 2 = all LTE FDD and NR FDD on 1800/2100 and 700/800/900 multi-band RRUs; baseband 3 = NR TDD 3500 on massive-MIMO units. Data source: CETIN Networks (Slovakia). About **17 % of records have at least one missing KPI**; outliers (maintenance, counter resets) are kept on purpose. Dataset_03: 84 days, 264 sites, 30.2 M records.
**Why it matters:** Absolute energy numbers are real (median radio unit ~47 Wh per 15 min ≈ 190 W). Per-cell energy is not observable because one multi-band radio serves several carriers. NR 3500 has its own massive-MIMO radio, so it is the cleanest case for per-carrier sleep.
**Action:** Model energy per radio unit with per-carrier load terms; start with NR 3500 (own radio) and LTE 1800/NR 2100 vs LTE 700/800 (shared radio). Handle missing values explicitly; flag outliers, don't drop them.

### E9 · 2026-11-23 · The open-source state of the art is a single-cell threshold
**What:** O-RAN SC's official energy-saving demo rApp (`o-ran-sc/nonrtric-plt-rappmanager`, `sample-rapp-generator/es-demo-rapp`) asks a served ML model for load predictions and locks a cell (`administrativeState: LOCKED` through NCMP) when **all** predictions are below 0.04, unlocking it otherwise. No coverage-layer check, no risk margin, no coordination between neighbouring cells, no price or CO₂.
**Why it matters:** This is a clean, citable, open baseline (B3), better than SMaRT-5G whose phase-2 logic is proprietary. It also comes with a Kubernetes SMO install flavour (`ranpm-pynts-es-rapp`) and DU simulators, which is a realistic path for the "real stack" tier with standard O1-style actuation.
**Action:** B3 = this logic, ported faithfully. Tier 2 spike: try the O-RAN SC SMO flavour first (ISSUES I16, I17).

### G19 · 2026-11-23 · The 3GPP sleep-state numbers circulating online are often wrong
**What:** Secondary sources mix up the base-station model with the UE model (1/20/45 units). The spec (TR 38.864 V18.1.0, Tables 5.1-3 to 5.1-5) says, for BS Category 1: deep sleep 1 (50 ms, E=1000), light sleep 25 (6 ms, E=90), micro sleep 55/50/38, active DL 280/200/152, active UL 110/90/80 for Sets 1/2/3. Category 2: deep sleep 1 (10 s, E=17000), light sleep 2.1 (640 ms, E=1088), micro sleep 5.5/5/3, active DL 32/26/17.6.
**Why it matters:** The sleep model now comes from the spec itself.
**Action:** Encoded in `yovahti.energy.tr38864` with tests against the tables.

### E10 · 2026-11-23 · The unit that sleeps is a radio unit, and there are two or three per sector
**What:** `scripts/slovak_quality.py` on Dataset_03 (264 sites, 83 days, every 15-min interval present). Rows on the same site, sector and time report **identical** radio-unit energy for GSM 900 = LTE 700 = LTE 800 (100 %) and for LTE 1800 = NR 2100 (100 %), and different energy across those groups (< 3 % identical). NR 3500 is its own massive-MIMO radio (101 sites). Baseband energy is one value per site and time (100 %). Median energy by own-carrier load decile: mid-band radio (LTE 1800 + NR 2100) 35 Wh/15 min at ~1 % load vs 78 at ~35 % (idle share 0.45); low-band radio 56 vs 92 (0.61); NR 3500 60 vs 98 (0.61). Median load trough/peak by hour: LTE 1800 0.16, LTE 700 0.11, LTE 800 0.17, NR 3500 0.34, NR 2100 0.49, GSM 900 0.63.
**Why it matters:** Each sector is a **low-band coverage radio** (GSM/LTE 700/800) plus a **mid-band capacity radio** (LTE 1800 + NR 2100), plus on some sites an **NR 3500 radio**. Sleeping the mid-band radio removes ~140 W of idle draw per sector but moves both its carriers' users onto 2 × 10 MHz of low band: the coverage-capacity check is the heart of the planner. NR 3500 idles at ~240 W and is the cleanest sleep candidate. The idle shares are large enough that night-time sleep matters, and real enough to quote.
**Action:** World and planner model sleep per radio unit, not per carrier; capacity check on the low-band radio's carriers (I1 in ARCHITECTURE). Energy model: per radio unit, energy ~ f(load of every carrier on it).

### G20 · 2026-11-23 · Data gaps and calendar traps in the primary data
**What:** LTE 700 utilisation is missing in 35.6 % of rows (likely not configured on every sector); GSM 9.8 %, LTE 1800 5.5 %, NR 2100 3.0 %. Radio-unit energy is missing in 2.5 % (mid-band) to 4.5 % (NR 3500) of rows and is never zero. Dataset_03 has 7 968 intervals (31 Aug – 22 Nov 2025, 83 days). EU daylight saving ended on **26 Oct 2025**, the first day of validation. Slovak public holidays in the window (1 Sep, 15 Sep, 1 Nov, 17 Nov) need checking, since 2025 austerity measures may have changed some.
**Why it matters:** Missing carrier data must not read as "zero load" (that would invite unsafe sleep). Local-hour features break across the DST switch if computed naively.
**Action:** Treat a carrier with no utilisation on a sector as absent, not idle; compute local time with tz conversion, never fixed offsets; holiday flags from a checked calendar (ISSUES I28).

### E11 · 2026-11-23 · Most of a capacity radio's energy doesn't depend on load
**What:** Energy model per radio unit (`yovahti.energy.model`, `scripts/fit_energy_model.py`), fitted on the training weeks, scored on validation (never seen in fitting). Energy = own idle fingerprint + shared slopes x carrier load.

| Radio unit | Units | Idle median | Slopes (Wh/15 min per % load) | Validation MAE | Validation R² | Idle share of mean energy |
|---|---|---|---|---|---|---|
| Mid-band (LTE 1800 + NR 2100) | 725 | 37.2 Wh/15 min (~149 W) | LTE 1800 +0.76, NR 2100 +1.04 | 3.0 Wh (6.6 %) | 0.917 | 0.72 |
| NR 3500 (massive MIMO) | 280 | 62.8 Wh/15 min (~251 W) | +1.17 | 2.1 Wh (2.8 %) | 0.962 | 0.88 |
| Low-band (GSM 900 + LTE 700/800) | 741 | 69.8 Wh/15 min (~279 W) | GSM -0.13, LTE 700 +0.78, LTE 800 +0.72 | 5.7 Wh (8.7 %) | 0.840 | 0.99 |

With the TR 38.864 ratios, deep sleep removes 98 % (Category 1) or 80 % (Category 2) of that idle draw.
**Why it matters:** On real hardware, 72 % (mid-band) and 88 % (NR 3500) of capacity-radio energy is spent just being on. That is the pool sleep can reach, and it is measured, not assumed. The low-band slopes tell the planner what it costs to push moved traffic onto the coverage layer.
**Action:** Use these models in the world and twin. Report savings under both 3GPP categories.

### G21 · 2026-11-23 · The low-band model drifts in validation, and GSM gets a negative slope
**What:** Low-band validation bias is +4.8 Wh (over-predicts by ~6 %), against +0.7 (mid) and +0.3 (NR 3500). The GSM time-slot utilisation slope is -0.13, which is physically odd.
**Why it matters:** Likely a seasonal effect (colder weather from late October, which can change radio and cooling efficiency) and GSM time-slot use reflecting signalling more than traffic. It doesn't affect sleep savings directly (the low band never sleeps), but it would bias the cost of moving traffic onto it.
**Action:** Phase 2: add a time-varying baseline (week or temperature term) and check whether the drift disappears; report the low-band bias next to any result that depends on it.

### E12 · 2026-11-24 · How much traffic each band carries, measured; burstiness isn't
**What:** On the training weeks, median downlink MB per (% utilisation x MHz), over quarter-hours above 5 % load: LTE 700 3.03, LTE 800 3.18, LTE 1800 2.55, NR 2100 4.42, NR 3500 4.28. The low band (LTE 700/800) never exceeds 49 % utilisation in the data (p99 ~35 %); LTE 1800 reaches 99 %. The "max active users" counter is often *below* the average (median ratio 0.9 for LTE 1800), so it can't serve as an intra-interval peak factor.
**Why it matters:** The world converts moved traffic into extra load on the receiving layer with measured, not assumed, efficiencies. The low band's practical ceiling sets how much can be moved. Intra-interval peaks have to be a stated assumption.
**Action:** Efficiencies in `yovahti.world.data.EFFICIENCY`; low-band ceiling 50 %; a peak margin of 1.25 on 15-minute averages, varied in sensitivity runs.

### E13 · 2026-11-24 · First numbers: an oracle saves 22.6 % of radio energy; static thresholds pay for theirs with quality
**What:** Validation weeks (26 Oct – 8 Nov 2025), 744 real sectors (291 with NR 3500), TR 38.864 deep sleep, coverage limit 40 % low-band load with a 1.25 peak margin, watchdog on.

| Method | kWh saved | Capacity-radio energy saved | € saved | CO₂ saved | Mid radio asleep | Congested QH per sector-day | Pushed beyond capacity | Watchdog wake-ups | Switches per sector-day |
|---|---|---|---|---|---|---|---|---|---|
| B0 always on | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| B1 static thresholds (Cat 1) | 18.2 % | 47.5 % | 16.4 % | 18.1 % | 64 % | 3.64 | 6.1 TB | 37 897 | 13.4 |
| Oracle, perfect foresight (Cat 1) | 22.6 % | 55.4 % | 20.9 % | 22.6 % | 63 % | 0 | 0 | 0 | 10.4 |
| B1 (Cat 2, conservative sleep) | 14.4 % | 40.3 % | 12.9 % | 14.3 % | | | | | |
| Oracle (Cat 2) | 17.6 % | 45.7 % | 16.1 % | 17.5 % | | | | | |

Savings are a share of the energy of all three radios per sector (baseband excluded). The oracle saves 3.3 kWh per sector per day.
**Why it matters:** There is real room (the oracle), and the naive way to take it (B1) costs congestion, thousands of emergency wake-ups and constant switching. A forecasting planner's job is to get close to the oracle's savings with close to the oracle's quality. € savings trail kWh savings, as E6 predicted.
**Action:** These are validation numbers for development; the test weeks stay untouched (D23). Next: forecaster, planner, B2 and B3 on the same table.

### G22 · 2026-11-24 · "No congestion" isn't "no quality loss": moved users get a smaller pipe
**What:** The oracle keeps the low band under 40 % load, but users moved from 2 x 20 MHz (and NR) onto 2 x 10 MHz of LTE get lower peak rates even without congestion. The world doesn't model per-user throughput yet. The B0 low-band energy is also 10 % above measured in these weeks (the drift of G21).
**Why it matters:** The coverage limit (rho_max) is the knob between energy and experience; 40 % is permissive compared with industry practice (capacity cells usually sleep only below ~10–20 % load).
**Action:** Report savings as a curve over rho_max rather than one point; add a per-user throughput proxy (capacity per active user before vs after moving) (ISSUES I29).

### G23 · 2026-11-24 · LTE 700 load is missing 60 % of the time even where it exists
**What:** Among sectors where LTE 700 is configured, 60 % of its utilisation values are missing (other carriers 4–6 %).
**Why it matters:** Its load is mostly imputed, which affects the low band's energy and capacity estimate.
**Action:** Sensitivity run treating LTE 700 as absent; check whether the gaps follow a pattern (night only, some sites only).

### E14 · 2026-11-24 · Same energy as the published method, a fifth of the congestion
**What:** Validation weeks, 749 real sectors, TR 38.864 Category 1, low-band limit 40 %, everyone using the same forecasts and the same watchdog (`scripts/compare_methods.py`).

| Method | kWh saved | € saved | Congested QH per sector-day | Pushed beyond capacity | Watchdog wake-ups | Switches per sector-day |
|---|---|---|---|---|---|---|
| B1 static thresholds | 18.1 % | 16.4 % | 3.67 | 6.2 TB | 38 470 | 13.5 |
| B2 published method (reconstruction) | 17.1 % | 15.3 % | 5.03 | 38.5 TB | 52 755 | 18.6 |
| B3 O-RAN SC demo rApp | 12.6 % | 10.7 % | 0.88 | 1.8 TB | 9 192 | 7.3 |
| **B4 Yövahti (P90)** | **17.8 %** | **16.4 %** | **0.90** | **2.2 TB** | **9 433** | **9.4** |
| B4 with margin 1.5 | 14.1 % | | 0.23 | 1.1 TB | 2 363 | |
| Oracle (perfect foresight) | 22.6 % | 20.9 % | 0 | 0 | 0 | 10.3 |

**Why it matters:** B4 matches the published method's savings with 5.6x fewer congested quarter-hours, 17x less traffic pushed past capacity and half the switching; it saves 42 % more than the O-RAN SC rApp at the same congestion. Raising the margin traces a curve (17.8 % / 0.90 → 14.1 % / 0.23) on which every point beats every baseline: B4 dominates the savings-quality trade-off. The low-band limit curve (20–40 %) shows the same: B4 congestion stays ~0.84–0.90 while B2's is 5–7.
**Action:** Report the curve, not one point. Validation only; the test weeks run once at the end (D23).

### E15 · 2026-11-24 · Risk-awareness is what buys the quality
**What:** The same planner on P50 instead of P90 saves 19.7 % (vs 17.8 %) but congests 3.30 QH per sector-day (vs 0.90) and pushes 6.0 TB past capacity (vs 2.2). Switch cost barely changes savings (17.83 % with or without) but cuts switching from 10.8 to 9.4 per sector-day.
**Why it matters:** Confirms D16 with numbers: the published method's expected-energy criterion is exactly the P50 trap.
**Action:** Keep P90 + margin as the default; show the P50 ablation in the results.

### G24 · 2026-11-24 · The forecaster misses its target, and the morning ramp is where it hurts
**What:** Skill vs seasonal naive (MAE): mid band +14.7 %, NR 3500 +13.7 %, low band +19.1 % (target ≥ 20 %). After conformal calibration on the last two training weeks, P10–P90 coverage is 73 % (mid), 64 % (NR 3500), 77 % (low); 11.5–19.7 % of outcomes land above P90 (ideal 10 %). Calibration traded some accuracy for honest intervals. Drift features (recent level vs weekly profile) helped little. 30 % of B4's congestion falls between 06:00 and 09:00 local, when traffic ramps up. Assumption: forecasts use each layer's real demand history even while a radio slept (operators can estimate it from per-user counters on the coverage cell).
**Why it matters:** The planner is only as safe as P90. The remaining congestion is mostly forecast misses on the ramp, not a planning flaw.
**Action:** Phase 2: time-of-day-specific calibration, a ramp feature, NR 3500 drift. Meanwhile the margin curve and the watchdog handle it; the misses are reported, not hidden.

### G25 · 2026-11-24 · Price-weighting doesn't change sleep decisions
**What:** Weighting energy by quarter-hour price saves 16.1 % of € vs 16.4 % for the energy-weighted planner; CO₂ weighting is identical to energy weighting. Price weighting does reduce switching (6.6 vs 9.4 per sector-day) and congestion slightly.
**Why it matters:** Sleep is worth taking whenever it is safe, so feasibility decides, not price (as E6 predicted). The D17 price target is not met by sleep alone. Price and CO₂ matter where energy can be *shifted* in time: site batteries (Elisa-style), not sleep.
**Action:** Report as a negative result. If batteries are added (Tier 1), revisit.

### G26 · 2026-11-24 · The "UTC" timestamps are local Slovak time, and that was most of the forecast error
**What:** The data descriptor says timestamps are UTC. The data says otherwise: the weekday morning traffic ramp sits at 07:00 in the raw stamps in both fortnights around the end of daylight saving (26 Oct 2025); in true UTC it would have moved an hour. The stamps are Europe/Bratislava wall-clock time. Treating them as UTC shifted every "local hour" feature by 2 h in summer and 1 h in winter, so the model learned one alignment in training and met another in validation, starting exactly on the validation's first day. The error breakdown showed it: bias by hour of +350 MB at midnight and -300 MB at 07–08 (mid band), 40–53 % of outcomes above P90 at 07–08, identical at every horizon and on every day. It also misaligned the Slovak traffic with Finnish prices and CO₂ by 1–2 h.
**Why it matters:** One wrong assumption, inherited from documentation, cost about 10 points of forecast skill. After re-stamping (local → UTC, ambiguous hour read as standard time): skill vs seasonal naive mid +14.7 % → **+25.6 %**, NR 3500 +13.7 % → **+25.0 %**, low +19.1 % → **+26.4 %**; P10–P90 coverage mid 78 %, low 81 % (targets met); above P90 mid 9.9 %, low 9.6 %. The energy model was unaffected (it doesn't use clock time).
**Action:** `yovahti.data.slovak.local_to_utc` with a test across the DST switch; existing Parquet migrated (`--fix-timezone`). Worth telling the dataset authors. Lesson: check documented assumptions against the data's own behaviour.

### E16 · 2026-11-24 · After the fix, three specific misses remain, and they have known causes
**What:** (1) NR 3500 is under-forecast at every hour and day (bias -130 to -560 MB, 15.9 % above P90): its weekly traffic grew 34 % in 12 weeks (476 → 638 TB), 12 % in the last four, while mid- and low-band traffic fell from late October (users moving to 5G). (2) Low-band P90 under-covers at night (01–05: 14–23 % above P90) and over-covers by day: one calibration shift for all hours. (3) A mild mid-band under-forecast tied to the same migration.
**Why it matters:** Each has a standard remedy. Literature check: LightGBM-type global models are the strongest family on real 5G traffic (KDMiLe 2025; Computer Communications 2024), while zero-shot time-series foundation models do worse than seasonal naive on comparable ops data (arXiv 2502.12944), so the model family is not the problem; drift and calibration are. Hour-conditional (Mondrian) conformal calibration around gradient boosting is used for the same pattern in energy forecasting (arXiv 2607.11470), with rolling windows under drift (arXiv 2611.24329).
**Action:** F1 level-normalised targets (each sector relative to its last-7-day level), F2 Mondrian calibration by local hour, F3 daily rolling recalibration on realised outcomes only. Each must win on two windows (D29).

### G27 · 2026-11-24 · Calibrating over sectors that don't have the carrier silently disabled NR 3500 calibration
**What:** 61 % of sectors have no NR 3500. Their traffic is zero and is forecast as zero, so they flooded the calibration residuals with exact zeros and pinned the conformal shifts at (or near) zero. Symptom: "global" and "Mondrian" calibration gave *identical* NR 3500 results, and NR's P90 stayed at 15.9 % above (it had even got worse after the first calibration). Restricting calibration to sectors where the carrier exists: NR 3500 coverage 70.9 % → **79.2 %**, above P90 15.9 % → **11.3 %**.
**Why it matters:** The "NR 3500 drift" miss was mostly this bug, not drift. Identical results from two methods that must differ are a red flag worth chasing.
**Action:** `sectors=` mask in every calibration function; regression test with 60 % absent sectors.

### E17 · 2026-11-24 · Fixing the misses one by one: what worked, what didn't
**What:** Each candidate fix scored on an inner backtest (12–26 Oct) and validation (26 Oct–9 Nov) (`scripts/forecast_experiments.py`, `results/forecast/experiments.json`).

| Fix | Result |
|---|---|
| G26 local-time stamps | +10 points skill on every layer; the morning-ramp bias disappeared |
| G27 calibrate only where the carrier exists | NR 3500 coverage 71 → 79 %, above P90 16 → 11 % |
| F1 level-normalised targets (DeepAR-style) | **Rejected**: worse skill and pinball on both windows for every layer (the existing drift features already carry it) |
| F2 Mondrian calibration by local hour | Night under-coverage fixed on the inner window; mixed on validation for NR |
| F3 daily rolling Mondrian on realised outcomes | **Adopted**: per-hour P90 error mid 3.6 → 0.3 pp (inner) / 1.1 → 0.4 pp (val); low 3.6 → 0.4 / 5.0 → 2.9; NR 5.0 → 0.5 / 1.45 → 1.48 (tie); worst hour above P90 ~20–25 % → 11–16 %; pinball equal or better except a ≤0.2 % tie |

Final validation forecasts: skill vs seasonal naive mid **+25.6 %**, NR 3500 **+24.7 %**, low **+28.5 %** (target ≥ 20 % met); P10–P90 coverage 78.9 / 79.2 / 81.7 % (target 75–85 % met); above P90 10.0 / 11.3 / 8.9 %.
**Why it matters:** Two of the three original "model limits" were data and code bugs. The model family (gradient boosting) was right, as the literature suggested; calibration under drift was the real lever.
**Action:** Production config: no level normalisation, rolling Mondrian calibration (D30).

### E18 · 2026-11-24 · Better forecasts cut the planner's congestion by a third at the same savings
**What:** Same validation comparison as E14 with the fixed forecasts. B4 saves 17.7 % (was 17.8 %), congested quarter-hours 0.90 → **0.60** per sector-day, traffic pushed past capacity 2.2 → 1.8 TB, watchdog wake-ups 9 433 → 6 252. B4 now beats the O-RAN SC rApp on both axes at once (17.7 % vs 12.6 % saved; 0.60 vs 0.77 congestion) and has 8.4x less congestion than the published-method reconstruction (5.01) at slightly higher savings (17.1 %). Margin curve: 1.0 → 17.7 % / 0.60; 1.15 → 16.4 % / 0.34; 1.3 → 15.1 % / 0.22; 1.5 → 13.7 % / 0.14. Congestion is now spread evenly over the day (06–09 share 30 % → 21 %): what remains is the designed P90 tail, controlled by the margin.
**Why it matters:** Forecast quality turns directly into network quality. At margin 1.5 B4 saves more than the O-RAN SC rApp with 5.7x less congestion.
**Action:** Use the updated table and curve in results; G24 is resolved by G26, G27 and F3.
