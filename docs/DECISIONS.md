# Decision log

One entry per real choice: what was decided, why, what else was considered. Status is **accepted**, **proposed** (needs Frank's OK or a spike) or **superseded by Dn**.

---

### D1 · Name "Yövahti" · accepted (supersedes the working name "Clearance")
Finnish for "night watch". Both halves in one word: the night, when cells sleep and energy is saved, and the watch, which decides which agents may act. Fits Frank's Finnish naming (Tasehinta, Taloksi) and a Finland-based audience. ASCII slug `yovahti` for the repo and Python package. Considered: Clearance (generic), Nukkumatti (the Finnish Sandman: only the sleep half), Curfew (negative). Avoid "Ericsson" in the name before applying.

### D2 · Python core; reuse agent-trust-kit in Node · accepted
**Why:** The IMS GW posting asks for Python; the ML and optimisation stack is Python. agent-trust-kit already does JWS, DSSE, in-toto and Rekor correctly, with tests.
**How:** Signing and logging call the kit's CLI. `admit()` is ported to Python (small, deterministic) and must pass the kit's own test vectors, which proves the two agree.
**Alternatives:** All Node (wrong for the posting and ML); rewrite all crypto in Python (risk of subtle incompatibility, no gain).

### D3 · Traffic from Milan, energy from ITU, prices and CO₂ from Nord Pool and Fingrid · accepted
**Why:** ITU has real energy and energy-saving-mode data but only 8 days and no geography (G2, G4). Milan has 62 days of 10-minute traffic over 10 000 squares with a known grid. Each source is used for what it's good at.
**Alternatives:** ITU only (too short to forecast); synthetic traffic only (weak); Shanghai Telecom dataset (session logs, harder to map).

### D4 · Synthetic Turku topology · accepted
**Why:** No public dataset has real cell layers and neighbours. A Turku layout makes the demo local and concrete (stadium, harbour, campus). Clearly labelled synthetic.

### D5 · The world is separate from the twin · accepted
**Why:** If agents saw the ground truth, the twin would be perfect and twin-related failures (N12) impossible to test. Real twins are imperfect; measuring fidelity is part of the result.

### D6 · Tools compute, models orchestrate · accepted
**Why:** Charge showed models garble numbers. The planner, twin and energy model produce every number; the LLM handles intent, context and explanation.

### D7 · MCP over Streamable HTTP with signed requests · accepted
**Why:** Matches a networked deployment (EIAP-like), and HTTP lets us carry identity with RFC 9421 signatures. stdio would hide the identity question.
**Note:** MCP's own auth is OAuth-based; agent identity is our extension (I20).

### D8 · Own agent loop instead of an agent framework · accepted
**Why:** NetCrash needs exact control of steps, tool results, budgets and a complete trace. Frameworks add hidden retries and prompt text that change behaviour per version.

### D9 · OR-Tools CP-SAT for the planner · accepted
**Why:** Discrete states, dwell times, toggle limits and cluster constraints are natural in CP-SAT; free, fast, well documented.
**Fallback:** Greedy with the same constraints if solve time is too high.

### D10 · Static dashboard, no live backend · accepted
**Why:** Hosting is free, nothing can break during a recruiter's visit, and no API keys or LLM costs are exposed. Live mode can come later.

### D11 · Tier 2 stack chosen by a one-day spike · proposed
**Candidates:** srsRAN 4G + ZMQ + GNU Radio broker + Open5GS on kind; OAI RF simulator; ns-3 with an O-RAN module.
**Criterion:** switch a cell off and on programmatically and observe UEs moving and KPIs changing within one day of work. If none passes, Tier 2 moves to Phase 2 and the spike becomes a finding.

### D12 · Include a reconstruction of Ericsson's published method as a baseline · accepted
**Why:** Beating "static thresholds" impresses nobody; comparing against their own published approach does. Labelled as a reconstruction from public sources, tuned fairly (I14).

### D13 · Splits locked before results · accepted
Train Nov, validation 1–14 Dec, test 15–21 Dec, holidays separate (see EVALUATION.md). Changes after locking are logged here.

### D14 · Rekor staging by default · accepted
Production Rekor entries are public and permanent; only with Frank's explicit go-ahead (I2).

### D15 · uv with Python 3.12 · accepted
System Python is 3.7 (G5).

### D16 · Plan on P90, not the mean · accepted
**Why:** The cost of a wrong sleep (users without capacity) is much higher than the cost of a missed saving. Planning on an upper quantile makes the risk explicit and tunable (λ, ρ_max). This is the core difference from an expected-energy criterion like the patent's validity check.

### D17 · Replace the "€ % > kWh %" target · accepted (before any results)
**Why:** Price data shows night hours are the cheapest (E6), so the target was based on a wrong assumption. New target: price-aware vs price-blind planner on spike nights, equal quality. Changed on 23 Nov, before the test period was run.

### D18 · Milan is processed day by day, raw files deleted · accepted
**Why:** 20.8 GB raw vs ~50 GB free disk (G6, G11). Aggregating over country codes loses nothing we use.

### D19 · Slovak live-RAN data is the primary source for load and energy · accepted (refines D3)
**Why:** Real 15-min RB utilisation and real radio-unit energy on 264 multi-layer sites, CC BY 4.0, in the same months as the Finnish prices (E7). Removes the weakest assumptions (normalised ITU energy, Milan activity as load, mismatched years).
**Roles now:** Slovak = load, layering, power model, forecasting and the main test. ITU = relative effect of energy-saving modes. 3GPP TR 38.864 = sleep-state power and transitions. Milan = city-scale spatial structure and a second-city check. The Turku topology stays synthetic (D4), optionally placed at real OpenCelliD positions.

### D20 · LLM budget · accepted
Otari: at most **€6** (about €10 of credit available). Featherless: up to about **€10** (about €20 available). A budget guard in the agent client counts tokens per provider and stops runs at the cap. If money runs short, test fewer models before cutting runs per test.

### D21 · Publish attestations to Sigstore Rekor production · accepted (supersedes D14)
Frank approved on 23 Nov. Entries are public and permanent: they contain the attestation envelope (Agent Card hash, model, scores, tester public key), nothing personal. Rekor staging is still used for tests and development runs.

### D22 · Public GitHub repo from the start · accepted
Repo `FrankPonce/yovahti`, public, so the commit history shows the work as it happens. `.env`, keys and data stay git-ignored.

### D23 · Splits locked · accepted
Train 31 Aug – 25 Oct 2025, validation 26 Oct – 8 Nov 2025, test 9 – 22 Nov 2025 (Slovak Dataset_03), boundaries at 00:00 UTC; generalisation on Dataset_02 and Milan. Decided after the quality pass (E10, G20) and before any model was fitted. Changes from here on are logged here with the reason.

### D24 · Sleep is modelled per radio unit · accepted
The data shows energy per radio unit shared by its carriers (E10). The planner chooses a state for each **mid-band radio** (LTE 1800 + NR 2100) and each **NR 3500 radio**; the low-band radio (GSM/LTE 700/800) is the coverage layer and never sleeps.

### D25 · The world runs at the data's 15-minute resolution · accepted
The data is 15-minute; anything finer would be invented. Intra-interval peaks are a stated peak margin (1.25), varied in sensitivity runs. The watchdog acts with a one-interval delay and holds a wake-up for an hour.

### D26 · Quality = congestion on the layer that receives moved traffic · accepted
Congested when average load x peak margin exceeds rho_max on a layer that received moved traffic; traffic pushed beyond the layer's ceiling counts as unserved. rho_max is reported as a curve (G22), not a single tuned point.
