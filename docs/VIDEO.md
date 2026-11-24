# 3-minute video: script and shot list

Screen recording of the dashboard plus a terminal; voice-over. Aim: an Ericsson engineer understands the problem, the result and why the trust layer matters in three minutes. Numbers come from the README; check them before recording.

| Time | Shot | Voice-over |
|---|---|---|
| 0:00–0:15 | Dashboard header | "Radio networks burn a large share of their energy just being on. At night, capacity radios can sleep, if users never notice. And now operators are letting AI agents into that loop through MCP." |
| 0:15–0:45 | Trade-off chart, hover B4 then B1 and B2 | "This is real data from a live 2G-to-5G network, 749 sectors. Our planner sleeps capacity radios using the 90th-percentile forecast, not the average. It saves 18 percent of radio energy, the same as simple thresholds, with six times less congestion, and eight times less than a reconstruction of a published vendor method. The margin is a dial." |
| 0:45–1:15 | Event chart, then the replay heatmap: switch arms | "So why an agent? Because the planner can't read. Here a match ends at 22:30; only the event calendar knows. The planner alone sleeps right through the crowd: red is congestion. The agent read the calendar and kept those sectors awake." |
| 1:15–1:30 | Agent trace list | "Every number the agent reports comes from a tool. Every action goes through an arbiter: capacity at P90, protected cells, blast radius. Refusals come back with reasons." |
| 1:30–2:15 | NetCrash matrix, hover failures | "But the calendar is also where attacks come in. NetCrash puts each agent through hostile nights, on each model. An instruction hidden in an alarm. A collector that fails. A request to confirm something that never happened. A leaked token. The same prompt behaves differently on different models: this one leaked the token; this one turned a missing alarm feed into 'no alarms'." |
| 2:15–2:45 | Attestation card, click Verify | "So the network doesn't trust agents, it admits them. The test result is signed as an in-toto attestation bound to the agent's exact prompt and model; verified right here in the browser. Change one word of the prompt and the agent has to be tested again." |
| 2:45–3:00 | README results, repo | "Real data, a planner that's safe by construction, and agents that have to earn the right to act. Everything is open: code, data pipeline, results, and what went wrong." |

Recording notes: 1080p, browser at 1280 px wide, dark theme; terminal font 16 pt; no music under the voice; captions burned in.
