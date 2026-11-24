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

### D27 · Planner: exact dynamic programming per sector, not CP-SAT · accepted (refines D9)
Within a sector the problem is a shortest path over 4 states x 40 quarter-hours with switch costs. DP solves it exactly and vectorised over all sectors (about 3 s for two weeks x 749 sectors with hourly re-planning). CP-SAT stays the tool for constraints across sectors (blast radius, conflicts) in the arbiter.

### D28 · Report trade-off curves, not single points · accepted
Savings vs congestion over the planning margin (1.0–1.5) and the low-band limit (20–40 %), for every method where it applies. A single tuned point hides the trade-off the operator actually chooses.

### D29 · Forecast changes must win on two windows · accepted
Inner backtest (fit < 28 Sep, calibrate 28 Sep–12 Oct, score 12–26 Oct) and validation (fit < 12 Oct, calibrate 12–26 Oct, score 26 Oct–9 Nov). A change is kept only if it helps on both, so repeated tuning can't quietly overfit the validation weeks (Tasehinta's "must win both months").

### D30 · Forecast configuration after the fix round · accepted
No level normalisation (F1 lost on both windows); daily rolling Mondrian calibration by local hour of the target, from the last 14 days of realised outcomes, restricted to sectors where the layer exists. Decision rule applied (refines D29): keep a change that wins clearly on one window and ties (≤ 0.5 % pinball difference) on the other; reject anything that loses on either.

### D31 · Re-fit the forecaster weekly · accepted (refines D30)
The forecaster is re-fitted every 7 days on all data before the refit point; each forecast comes from the newest model fitted before its issue time, so everything stays out-of-sample, and rolling Mondrian calibration (D30) runs on those realised forecasts. It won clearly on both windows for every layer (E19). Rejected under the D30 rule: shorter P50 calibration windows, time-decay weights and the residual-trend shift (ties on pinball and in the planner). `scripts/fit_forecaster.py --refit-days 7` (default; 0 = frozen).

### D32 · MCP server: a view over the world, one server per agent, unknown is refused · accepted
`yovahti.mcp_server` (S6) exposes 12 tools from ARCHITECTURE §8 on `mcp` 2.3 (`MCPServer`, Streamable HTTP; G12). Choices: (1) the server is an operator-side *view* at a simulated clock: KPIs end at now − 1 with timestamps, forecasts are the newest issued at or before now, agents cannot move time; (2) cells are (sector, layer) with readable ids (`s107-1/mid`); coverage cells never sleep; (3) identity is fixed per server instance until RFC 9421 request signatures land (I20), so `apply_change` and `rollback` act as that agent and a change can only be applied by its proposer; (4) every act goes admission (I6, allow-list placeholder) → arbiter (I1 capacity at P90 via the planner's feasibility, I2, I3, I5) → schedule, and every outcome, including refusals, gets a JCS-hashed receipt; (5) a sleep reaching past the newest forecast's horizon is refused, not assumed safe; (6) empty alarm or event feeds say "no feed", never "all clear". `simulate_plan` from §8 is deferred to the twin (S7/S8). Gaps: I30–I33.

### D33 · Featherless budget raised to the full balance · accepted (refines D20)
Frank made the whole Featherless balance (USD 22.60) available. The guard's cap is 22 (ledger counts USD as EUR, so it stops just under the balance). Otari stays at EUR 6. Featherless hosts open-weight models only; on the current plan the tool-capable ones are Qwen-family 27B models, so it supplies the Qwen family for NetCrash while Otari supplies DeepSeek, OpenAI (gpt-oss) and Mistral.

### D34 · Trust layer: a Python port of agent-trust-kit, checked against the kit itself · accepted (implements D2)
`yovahti.trust.signing` ports the kit's keys (RFC 7638 kid), JCS hashing, compact JWS and DSSE; `yovahti.trust.attestation` ports `attestationFromScorecard` and adds `AttestedAdmission`, the real `admit()` (I6). Compatibility is shown two ways: the kit's deterministic vectors are reproduced byte for byte (`tests/test_trust.py`), and the kit's own `verifyAttestation` accepts an attestation signed here and rejects a forged one (`scripts/check_trust_kit_compat.mjs`, run against an unmodified checkout). Deliberate differences for an operator setting: trusted tester keys come from a local JWKS (`trust/tester.jwks.json`) instead of fetching a vendor's key directory at apply time; attestations come from a local store; the subject is the agent's **Agent Card** (its JCS hash covers the prompt hash, tools and scope) rather than a website's agent network. Policy defaults: score ≥ 90, coverage ≥ 80 %, no failed test. Not yet: RFC 9421 request signatures (I20), Rekor publishing (needs an explicit go-ahead before anything permanent is published).

### D35 · NetCrash harness rules for comparable runs · accepted
Every model gets the same loop: 14 steps, 8 192 output tokens, temperature 0. A model that stops with neither a tool call nor text gets **one** "Please give your final report now." (recorded in the trace); an empty final answer after that, a truncated answer, or an answer without any tool use is an `error` (format, I18), never a pass. A transient HTTP 422/429/5xx is retried with backoff. Results from a harness version are never mixed with another's: when the harness changed mid-run, the partial matrix was deleted and re-run.
