# Sources

Collected 23 Nov 2026. Add new sources here with the date and what they were used for.

## The postings
- Software Developer Summer Intern: IMS GW (AI & Automation), Jorvas, req 793299: https://jobs.ericsson.com/careers/job/563121777496581
- Research Summer Interns: Compute and Software Research, Jorvas, req 794859: https://jobs.ericsson.com/careers/job/563121777633381

## Ericsson: energy
- Net Zero targets (SBTi-approved, Jan 2024): https://www.ericsson.com/en/press-releases/2024/1/ericssons-second-round-of-climate-targets-toward-net-zero-approved-by-science-based-target-initiative · climate action: https://www.ericsson.com/en/about-us/sustainability-and-corporate-responsibility/environment/climate-action
- Slovak dataset descriptor, open full text: https://europepmc.org/article/PMC/PMC13696700
- rApp directory (4G Energy Optimizer, Energy Performance Orchestrator, RAN Energy Cockpit, PCEM): https://www.ericsson.com/en/portfolio/cross-portfolio/rapp-directory/a-z-directory
- AI in RAN (14 % energy savings, MIMO sleep): https://www.ericsson.com/en/ai/ran · launch news June 2026: https://www.ericsson.com/en/news/2026/6/the-ran-gets-smarter-ericsson-puts-ai-where-it-matters
- Vodafone UK trial press release: https://www.ericsson.com/en/press-releases/3/2025/vodafone-uk-and-ericsson-trial-ai-solutions-for-improved-5g-energy-efficiency · coverage: https://www.verdict.co.uk/vodafone-ericsson-5g-power-saving/ · https://www.telecoms.com/5g-6g/vodafone-and-ericsson-use-ai-to-cut-5g-power-use-by-a-third
- AI-powered RAN energy efficiency blog (2023, dynamic CSM thresholds): https://www.ericsson.com/en/blog/2023/1/ai-powered-ran-energy-efficiency
- Patent WO2024028883A1, AI-based dynamic cell sleep mode threshold configuration: https://patents.google.com/patent/WO2024028883A1/en
- Sustainable networks, Intelligent Operations guide: https://www.ericsson.com/en/reports-and-papers/further-insights/sustainable-networks-the-intelligent-operations-guide
- MasOrange autonomous networks (third-party energy rApp): https://www.sdxcentral.com/news/ericsson-helps-masorange-advance-autonomous-networks/

## Ericsson: agents, MCP, twins
- Agentic AI for autonomous telecom networks (white paper): https://www.ericsson.com/en/reports-and-papers/white-papers/adapting-agentic-ai
- AI agents and network architecture (white paper): https://www.ericsson.com/en/reports-and-papers/white-papers/ai-agents-and-network-architecture
- Agentic network intelligence blog (June 2026): https://www.ericsson.com/en/blog/2026/6/from-data-to-decisions-make-agentic-ai-driven-telecom-operations-a-reality
- Multivendor agentic AI for Cloud RAN (MCP servers): https://www.ericsson.com/en/blog/2026/5/multivendor-agentic-ai-solution-for-cloud-ran
- EIAP extended into the core, MCP support: https://the-mobile-network.com/2026/06/ericsson-extends-automation-platform-into-the-core-as-operators-seek-unified-ai-control/
- Network APIs for AI agents with Vonage (MCP PoC): https://www.ericsson.com/en/blog/2025/11/network-apis-for-ai-agents
- Network digital twin enables safe autonomy: https://www.ericsson.com/en/blog/2026/4/network-digital-twin-safe-autonomy
- Four moves for operators in the AI-native era: https://www.ericsson.com/en/blog/2026/4/ai-native-network-operator-growth
- Agentic rApp as a Service with AWS: https://www.ericsson.com/en/blog/2026/2/agentic-rapp-as-a-service · AWS side: https://aws.amazon.com/blogs/industries/accelerating-autonomous-network-optimization-agentic-rapp-as-a-service-powered-by-aws-and-ericsson-intelligent-automation-platform/
- Agent fabric for OSS/BSS: https://www.ericsson.com/en/blog/2026/6/how-to-accelerate-automation-in-oss-bss-with-agent-fabric

## Standards and industry on agent trust
- 3GPP Highlights Issue 12 (June 2026), AI agent identity, Agent Card: https://www.3gpp.org/ftp/Information/Highlights/3GPP_Highlights_Issue_12_WEB.pdf
- NGMN Network Automation and Autonomy Phase III (agentic AI): https://www.ngmn.org/wp-content/uploads/2608_NGMN_Network-Automation-and-Autonomy-Phase-III_v1.0.pdf
- TelecomTV on TM Forum's trustworthy AI governance certification: https://www.telecomtv.com/content/network-automation/autonomous-networks-are-one-thing-trusting-ai-to-run-them-is-another-56591/
- TM Forum Innovation Awards 2026: https://inform.tmforum.org/features-and-opinion/tm-forums-innovation-2026-awards-demonstrate-progress-towards-autonomy
- Cross-vendor agent tool trust management (arXiv 2607.25914): https://arxiv.org/pdf/2607.25914
- Agentic to autogenic network management, standards perspective (arXiv 2607.06786): https://arxiv.org/abs/2607.06786v1

## Research: O-RAN conflicts, benchmarks, cell sleep
- Multi-agentic rApp policy orchestration (arXiv 2610.24688): https://arxiv.org/abs/2610.24688
- xTRUCE (arXiv 2608.28532): https://arxiv.org/pdf/2608.28532
- Taming the Agentic RAN (arXiv 2609.18857): https://arxiv.org/pdf/2609.18857
- VeraRAN (arXiv 2608.01047): https://arxiv.org/pdf/2608.01047
- Mobile network control with a world model (CSM timescales; arXiv 2607.17747): https://arxiv.org/pdf/2607.17747
- TelcoAgent-Bench: https://arxiv.org/html/2604.06209v1 · CTBench: https://arxiv.org/pdf/2608.12002 · WirelessBench: https://arxiv.org/pdf/2603.21251
- Red-teaming the agentic red-team (cites AIOps telemetry manipulation): https://arxiv.org/pdf/2606.24496
- RAN energy efficiency survey (sleep modes, ML): https://arxiv.org/pdf/2101.11246

## Published cell-sleep methods by others (checked against the documents, 25 Nov 2026)

Each was read at the source; descriptions below are what the document says, not what a summary claimed. "Baseline" = reproducible on this dataset and planned; "related" = cited only.

- **Ericsson, 2023 blog** "AI-powered RAN: an energy efficiency breakthrough": per-cell sleep thresholds on PRB utilisation **and RRC connections**, grid search on a day-ahead forecast, KPI constraints (accessibility, drops, mobility, latency, throughput); 10-12 % on unnamed pilot sites (self-reported). Already reconstructed as **B2** with patent WO2024028883A1; a closer "as in the blog" variant is planned. https://www.ericsson.com/en/blog/2023/1/ai-powered-ran-energy-efficiency
- **Ericsson, 2021 Technology Review** "Ensuring energy-efficient networks with AI": CVAE + GNN recommendation engine for configuration settings. Related: it needs history where configurations varied; this dataset has one configuration. https://www.ericsson.com/en/reports-and-papers/ericsson-technology-review/articles/ensuring-energy-efficient-networks-with-ai
- **Elisa, WO2022058648A1 = EP4214968B1** (one family, priority FI20205909, inventor S. Holmbacka) "Energy saving management for communication networks": default plan = full shutdown of a capacity cell for a fixed night window (3-7 h, e.g. 01-06); use partial shutdown (MIMO antenna branches off) instead if it matches the default saving within the available window. No fuzzy logic, neighbour-overlap scoring or throughput percentiles in either document (a chatbot summary claimed them). **Baseline** (default plan; partial variant as a labelled side result). https://patents.google.com/patent/WO2022058648A1/en · https://patents.google.com/patent/EP4214968B1/en
- **Nokia, EP4175370A2** (application, priority 2021) "Power saving in radio access network": Q-learning picks switch-on / switch-off / no action per cell group from a load estimate and current state; reward = throughput benefit minus weighted normalised power; freeze time 5-30 min after a switch; online retraining. **Baseline.** https://patents.google.com/patent/EP4175370A2/en
- **Parallel Wireless, US20230127116A1** (granted as US12659852B2): per-cell load forecasts (LSTM/GRU); heuristic powers down a cell predicted near-zero for the next 2 h; re-evaluated every 15-30 min; rolled back if congestion rises beyond its normal spread within an hour. **Baseline.** https://patents.google.com/patent/US20230127116A1/en
- **Reiss, Catalan-Cid, Camps, Sallent, ICC 2026** "A Practical AI-Driven Strategy for Cell On/Off Switching under Adaptable QoS Constraints" (and MSWiM 2025, arXiv 2606.05755): LSTM-based switching on a European operator's data, decision threshold tunable at run time, 63-96 % of the oracle's savings on an unseen week. Closest academic peer; Yövahti B4 reaches 80 % of the oracle on validation (different data). Candidate baseline (classifier with a tunable threshold). https://arxiv.org/abs/2606.05019 · https://arxiv.org/abs/2606.05755
- **Samsung, US20240422667A1**: cell switching as an MDP via adaptive dynamic programming with neural estimators for power, QoS and handovers, adaptive QoS threshold. Related: needs handover data; closest in spirit to Yövahti's constrained optimisation. https://patents.google.com/patent/US20240422667A1/en
- **Aira Technologies, WO2025165735A1**: emulator aligned by Bayesian optimisation, synthetic data, neural predictor, uncertainty-gated shadow mode, then RL control. Related (a training pipeline, not a rule). https://patents.google.com/patent/WO2025165735A1/en
- **Intel, US20240298225A1**: ML selects energy-saving states across neighbouring NG-RAN nodes with feedback over Xn. Related (protocol level). https://patents.google.com/patent/US20240298225A1/en
- **Rakuten, WO2026005834A1**: RIC policies for SSB/SIB1/WUS/PRACH periodicity and power off-peak (e.g. load <= 20 %: SSB 40 ms, -5 dB). Related (signal-level savings, complementary to cell sleep). https://patents.google.com/patent/WO2026005834A1/en
- **ZTE PowerPilot white paper (2020)**: per-cell strategy from historical idle periods plus load thresholds; capacity layer off at low traffic, woken when load exceeds what coverage can carry; users counted. Related (rule family of B1/B3). https://www.zte.com.cn/content/dam/zte-site/res-www-zte-com-cn/mediares/zte/files/newsolution/wireless/ran/white_paper/PowerPilot_5G_Energy_Saving_in_Coordination_with_4G_20201215.pdf
- **Huawei PowerStar** (marketing): AI traffic forecasts and overlap analysis to switch off carriers; no algorithm disclosed. Related. https://www.mobileworldlive.com/huawei-updates/huawei-powerstartm-solution-network-level-ai-based-energy-saving/
- **NEC Technical Journal (2023)**: many operators run vendor cell-sleep parameters at static defaults; per-cell tuning lets capacity layers sleep longer. Related (supports the case for per-cell tuning). https://group.nec/global/en/about/technology/rd/journal/archives/g2301/230104

## Open-source energy saving
- **O-RAN SC energy-saving demo rApp** (baseline B3): https://github.com/o-ran-sc/nonrtric-plt-rappmanager/tree/master/sample-rapp-generator/es-demo-rapp · SMO install flavours: https://github.com/o-ran-sc/it-dep/blob/master/smo-install/README.md
- Rimedo traffic-steering xApp (SMaRT-5G phase 1): https://github.com/onosproject/rimedo-ts · SMaRT-5G white paper: https://opennetworking.org/wp-content/uploads/2023/07/ONF-SMaRT-5G-White-Paper-v11.pdf
- ONF SMaRT-5G demo: https://opennetworking.org/news-and-events/press-releases/onf-demonstrates-smart-5g-open-source-energy-savings-platform-at-fyuz/ · slides: https://opennetworking.org/wp-content/uploads/2023/10/Fyuz-Webinar-Slides.pdf
- Aether SMaRT-5G (2025): https://aetherproject.org/blog/2025/10/lightweight-innovation-in-open-ran-how-aether-smart-5g-is-driving-real-world-energy-and-traffic-optimization-without-e2-a1-interfaces/
- O-RAN SC RIC Testing as a Platform (energy saving use case): https://o-ran-sc.org/blog/2025/02/06/title-ric-testing-as-a-platform-ric-taap-advancing-xapp-rapp-design-and-testing-towards-digital-twin-network-a-case-study-with-orange-and-o-ran-software-community-sc/
- O-RAN Alliance, potential energy savings features (2025): https://mediastorage.o-ran.org/white-papers/O-RAN.SuFG.Potential%20Energy%20Savings%20Features%20in%20O-RAN%20white%20paper%202025-01.pdf

## Data
- **Primary:** Lehoczký et al., "Performance Management Counters from Live 5G, 4G and 2G Radio Access Network", *Scientific Data* (2026): https://www.nature.com/articles/s41597-026-07723-0 · dataset (CC BY 4.0): https://doi.org/10.5281/zenodo.17815388
- 3GPP TR 38.864 V18.1.0, Study on network energy savings for NR (Rel-18), from the 3GPP archive: https://www.3gpp.org/ftp/Specs/archive/38_series/38.864/38864-i10.zip (tables encoded in `yovahti.energy.tr38864`). Summaries: Nokia, "Reducing energy use with 5G-Advanced": https://www.nokia.com/asset/f/213599/ · arXiv 2402.11993: https://arxiv.org/pdf/2402.11993
- Fingrid open data (CC BY 4.0): emission factor of consumed electricity, dataset 265: https://data.fingrid.fi/en/datasets/265 · production emission factor, dataset 266: https://data.fingrid.fi/en/datasets/266
- OpenCelliD (CC BY-SA 4.0): https://wiki.opencellid.org/docs/attribution · per-country mirror: https://github.com/NorthveilSystems/treadstone-celldata
- Turku Linked Events (CC BY 4.0; endpoint unreachable, G15): https://www.lounaistieto.fi/linked-events-tapahtumarajapinta/?lang=en
- Viking Line Stockholm–Turku timetable (ferry arrivals for event scenarios): https://www.sales.vikingline.com/find-trip/timetable/stockholm-turku/
- Considered, not used: DoNext (Dortmund, phone-side measurements): https://ieeexplore.ieee.org/document/10976440/ · Traficom open data (no mobile site locations): https://tieto.traficom.fi/en/open-data · energy-saving vs QoS in offloading on real 4G/5G (arXiv 2606.05752): https://arxiv.org/pdf/2606.05752
- ITU 5G energy consumption dataset (mirror with zip): https://github.com/ITU-AI-ML-in-5G-Challenge/5G-Energy-Consumption-Modelling-Solution-Team-Farzi-Data-Scientists · Zindi page: https://zindi.world/competitions/aiml-for-5g-energy-consumption-modelling/data
- "Energy fingerprint" paper on that dataset (arXiv 2406.16929): https://arxiv.org/abs/2406.16929
- Telecom Italia Milan, SMS/Call/Internet: https://doi.org/10.7910/DVN/EGZHFV · Milano Grid: https://doi.org/10.7910/DVN/QJWLFU · collection: https://dataverse.harvard.edu/dataverse/bigdatachallenge
- Kaggle one-week Milan extract (fallback): https://www.kaggle.com/datasets/ocanaydin/italian-telecom-data-2013-1week

## Energy market context
- Elisa distributed energy storage (base-station batteries in Fingrid reserves): https://www.lightreading.com/sustainability/elisa-squeezes-cash-out-of-its-batteries-through-flexibility · https://www.energymonitor.ai/tech/energy-storage/elisa-to-roll-out-europes-largest-distributed-virtual-power-plant/

## Frank's prior work reused
- Tasehinta (Turku Energia challenge winner): https://github.com/Rdog69/turku-energy-since-ai
- Trust Before Transaction: https://github.com/FrankPonce/trust-before-transaction · crash-test: https://github.com/FrankPonce/crash-test · agent-trust-kit: https://github.com/FrankPonce/agent-trust-kit · taloyhtio-charging: https://github.com/FrankPonce/taloyhtio-charging
- Green Refactoring (private, with University of L'Aquila): https://github.com/Rdog69/green-refactoring
