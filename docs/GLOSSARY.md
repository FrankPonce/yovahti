# Glossary

## Radio network

| Term | Meaning |
|---|---|
| **RAN** | Radio access network: the sites, radios and basebands that connect phones to the network. Most of an operator's energy goes here |
| **Site / base station** | A physical location with radios. LTE: eNB; 5G: gNB |
| **Cell** | One radio coverage area on one frequency carrier. A site usually has several |
| **Coverage layer** | Low-band cells (e.g. 800 MHz) that reach far and stay on; the safety net |
| **Capacity layer** | Mid/high-band cells (e.g. 1800, 2600 MHz, 3.5 GHz) that add capacity where traffic is high; the ones that can sleep |
| **PRB** | Physical resource block, the unit of radio capacity; **PRB utilisation** is how full a cell is |
| **RRC connection** | A phone's active connection to a cell; counts as "connected users" |
| **KPI** | Key performance indicator: load, throughput, drops, etc. |
| **RU / radio unit** | The hardware that transmits (power amplifiers, antennas). **PA** = power amplifier |
| **Baseband** | The digital processing unit of a site |
| **MIMO, 64T64R** | Many antennas transmitting and receiving in parallel; **MIMO sleep / muting** switches some branches off at low load |
| **Micro sleep** | Switching the PA off in empty sub-millisecond symbols; automatic |
| **Cell sleep (CSM)** | Switching a capacity cell off when load is low; users move to the coverage cell |
| **Deep sleep** | Radio unit nearly fully powered down for hours; big savings, slow wake-up |
| **Handover / steering** | Moving users from one cell to another |
| **UE** | User equipment: a phone or modem |

## Network automation (O-RAN and Ericsson)

| Term | Meaning |
|---|---|
| **SMO** | Service management and orchestration: the management layer above the RAN |
| **Non-RT RIC** | Non-real-time RAN intelligent controller (>1 s decisions); hosts **rApps** |
| **Near-RT RIC** | Near-real-time controller (10 ms – 1 s); hosts **xApps** |
| **rApp / xApp** | Apps that optimise the RAN from the Non-RT / Near-RT RIC |
| **O1, A1, R1, E2** | O-RAN interfaces: O1 management (e.g. switch a cell off), A1 policies from Non-RT to Near-RT RIC, R1 for rApps to reach SMO services, E2 Near-RT RIC to RAN nodes |
| **EIAP** | Ericsson Intelligent Automation Platform: Ericsson's SMO / Non-RT RIC platform; MCP support announced 2026 |
| **Digital twin** | A model of the network used to predict what a change will do before applying it |
| **Intent** | A high-level goal ("save energy, keep quality above X") turned into concrete actions by automation |
| **NOC** | Network operations centre |
| **IMS** | IP Multimedia Subsystem: the core system for voice (VoLTE/VoNR) and messaging; **IMS GW** = IMS gateway |

## Agents and trust

| Term | Meaning |
|---|---|
| **MCP** | Model Context Protocol: a standard way to expose tools and data to AI models |
| **A2A** | Agent-to-agent protocol |
| **Agent Card** | A JSON document describing an agent's identity, capabilities and requirements (3GPP 6G work, A2A) |
| **Attestation** | A signed statement about something (here: how an agent × model behaved in NetCrash) |
| **in-toto** | A framework for supply-chain attestations; **Test Result predicate** is its format for test outcomes |
| **DSSE** | Dead Simple Signing Envelope, the signature wrapper in-toto uses |
| **Sigstore Rekor** | A public, append-only transparency log for signatures |
| **JWS** | JSON Web Signature |
| **JCS (RFC 8785)** | Canonical JSON, so the same document always hashes the same |
| **RFC 9421** | HTTP Message Signatures: signing HTTP requests |
| **TEE / enclave** | Trusted execution environment (AMD SEV-SNP, Intel TDX/SGX): hardware-isolated computing whose code can be remotely attested |
| **Prompt injection** | Instructions hidden in data that an agent mistakes for commands |

## Energy market and forecasting

| Term | Meaning |
|---|---|
| **Day-ahead / spot price** | The Nord Pool price for each quarter-hour of the next day, set the day before |
| **Imbalance price** | The price for deviations from plan, set by the TSO (Tasehinta's topic) |
| **TSO** | Transmission system operator; Fingrid in Finland |
| **FCR / aFRR** | Reserve markets where flexible assets (like Elisa's base-station batteries) earn money by balancing the grid |
| **Emission factor** | gCO₂ per kWh of electricity at a given time |
| **P10 / P50 / P90** | Forecast quantiles: 10 %, 50 % (median) and 90 % |
| **Pinball loss** | Error measure for quantile forecasts |
| **Brier score** | Error measure for probability forecasts |
| **CP-SAT** | Google OR-Tools' constraint solver |
