"""Agent Cards (ARCHITECTURE §9, S8): what an agent is, what it may touch, and the exact
prompt it runs with. NetCrash results and admission bind to the card's JCS hash, so changing
the prompt, tools or scope means the agent must be tested again.
"""

from __future__ import annotations

import hashlib
import json

import rfc8785

from yovahti.agents.roles import CONSTRAINED, PROMPT_VERSION, ROLES, WORKFLOW
from yovahti.paths import ROOT

CARDS = ROOT / "agents" / "cards"
VENDOR = "github.com/FrankPonce/yovahti"
TOOLS = ["list_cells", "get_cell_kpis", "get_alarms", "get_events", "get_prices", "get_carbon",
         "forecast_load", "optimise_plan", "simulate_plan", "propose_change", "apply_change",
         "get_change_status", "rollback", "get_energy_report"]
SCOPE = {"coverage-agent": ["capacity_cell_wake"]}
# constrained mode (D45): read tools + apply_plan (planner plan minus keep-awake windows)
TOOLS_C = ["list_cells", "get_cell_kpis", "get_alarms", "get_events", "get_prices", "get_carbon",
           "forecast_load", "optimise_plan", "apply_plan", "get_change_status",
           "get_energy_report"]
# workflow mode (D46): the fixed steps code runs; the model itself calls no tool
TOOLS_W = ["list_cells", "get_events", "get_alarms", "get_cell_kpis", "optimise_plan",
           "apply_plan", "get_change_status"]


def agent_card(agent: str) -> dict:
    prompt = ROLES[agent]
    return {"schema": "yovahti/agent-card@1", "id": agent, "vendor": VENDOR,
            "version": PROMPT_VERSION,
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "allowed_tools": (TOOLS_W if agent in WORKFLOW else
                              TOOLS_C if agent in CONSTRAINED else TOOLS),
            "scope": {"clusters": "*",
                      "parameters": SCOPE.get(agent, ["capacity_cell_sleep"])},
            "role": "coverage" if agent == "coverage-agent" else "energy",
            "risk_tier": 1}


def card_sha256(card: dict) -> str:
    return hashlib.sha256(rfc8785.dumps(card)).hexdigest()


def card_uri(agent: str) -> str:
    return f"https://{VENDOR}/blob/main/agents/cards/{agent}.json"


def write_cards() -> dict[str, str]:
    """Write every card to agents/cards/ and return {agent: jcs sha256}."""
    CARDS.mkdir(parents=True, exist_ok=True)
    out = {}
    for agent in ROLES:
        card = agent_card(agent)
        (CARDS / f"{agent}.json").write_text(json.dumps(card, indent=1) + "\n",
                                             encoding="utf-8")
        out[agent] = card_sha256(card)
    return out
