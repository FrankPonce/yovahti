# Yövahti: roadmap

Status: in progress, 23 Nov 2026. The only fixed date: both applications go in before the portal closes on **30 Nov 2026**. Everything else is a sequence of steps, done as fast as they can be done well. Scope is not cut for time.

## Rules

1. **Every step ends with something that runs** and is committed. Big scope is fine; a half-built everything is not.
2. **Long jobs run in the background** (downloads, Docker images, model training, test matrices) while code is written.
3. **Numbers are locked before they are shown.** Splits and scenarios are fixed before any test-period run (see [EVALUATION.md](EVALUATION.md)).
4. **Log as you go:** surprises → [FINDINGS.md](FINDINGS.md), deferred problems → [ISSUES.md](ISSUES.md), choices → [DECISIONS.md](DECISIONS.md).
5. **Applications go in with whatever is finished** before 30 Nov; the repo keeps growing afterwards.

## Steps and definitions of done

| # | Step | Done when | Status |
|---|---|---|---|
| S0 | Foundation | Repo, uv/Python 3.12, CI, downloader with manifest, keys tested | done |
| S1 | Data | Slovak, ITU, Milan, prices, CO₂ processed to Parquet; data descriptor read; quality report; splits locked | done (Milan still downloading; CO₂ fetch pending) |
| S2 | Energy model | Radio-unit power model fitted on Slovak energy (per carrier load terms), sleep states from 3GPP TR 38.864, mode effects from ITU; error documented | done (ITU mode effects pending) |
| S3 | World | Turku topology on real layering; demand from Slovak sectors; steering, events, faults, local CSM logic; a simulated week in under a minute; B0/B1 results | |
| S4 | Forecaster + twin | Quantile forecaster beats seasonal naive on validation; calibrated intervals; twin predicts plan outcome and risk | |
| S5 | Planner + baselines | CP-SAT planner; B2 (reconstruction), B3 (SMaRT-5G logic), B4; first savings vs quality table on validation | |
| S6 | MCP server | All tools over Streamable HTTP; stand-in mode; signed identity on requests | |
| S7 | Agents | Energy, coverage and sloppy agents complete a night end to end on several models; budget guard | |
| S8 | Trust | Agent Cards, `admit()` passing agent-trust-kit vectors, arbiter I1–I9 with unit + property tests, watchdog rollback | |
| S9 | NetCrash | Full catalogue, judge panel, scorecards, signed attestations logged to Rekor | |
| S10 | Results | Locked test runs for every method and agent; NetCrash matrix; FINDINGS; result tables | |
| S11 | Showcase | Dashboard (Turku map, replay, attestation check), README, 3-minute video, short paper | |
| S12 | Applications | Applications submitted; outreach done | |

## Stretch work (all in scope, done alongside the steps)

| Tier | Item | Fits after |
|---|---|---|
| 1 | Dashboard with Turku map and replay | S10 |
| 1 | Live Finnish prices and CO₂ mode | S3 |
| 1 | Nightly CI publishing signed results | S9 |
| 2 | Real open-source RAN in the loop on Kubernetes (srsRAN / OAI / ns-3, chosen by a spike) | S6 |
| 2 | Net savings after the AI's own energy (local model measured on the RTX 4050) | S7 |
| 2 | Formally checked arbiter invariants (Z3) | S8 |
| 2 | NetCrash as an MCP server (query, compare, rerun tests) | S9 |
| 3 | Arbiter in a hardware enclave with remote attestation | S8 |
| 3 | Automated red-teaming that grows the NetCrash suite | S9 |
| 3 | Multi-vendor agents negotiating through the arbiter (agent-to-agent) | S8 |
| 3 | Draft for an attestation field in the 3GPP-style Agent Card | S9 |

## Critical path

**data → energy model → world → forecaster/twin → planner → MCP → agents → trust/arbiter → NetCrash → locked results → showcase.**

| Risk | Fallback |
|---|---|
| Data units unclear (G14) | Report relative savings until the descriptor confirms units |
| Forecaster weak | Ship the honest result; risk-aware planning matters more |
| CP-SAT too slow | Smaller clusters or a greedy planner with the same constraints |
| Small models fail the agent loop | Report it (trust is agent × model); keep strong models as the main line |
| LLM budget (D20) | Budget guard stops runs at the cap; fewer models before fewer runs |
| Real RAN stack doesn't cooperate | The spike becomes a finding; the simulator stays the main line |
