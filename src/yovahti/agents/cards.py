"""Agent Cards (ARCHITECTURE §9, S8): what an agent is, what it may touch, and the exact
prompt it runs with. NetCrash results and admission bind to the card's JCS hash, so changing
the prompt, tools or scope means the agent must be tested again.
"""

from __future__ import annotations

import hashlib
import json

import rfc8785

from yovahti.agents.roles import PROMPT_VERSION, ROLES
from yovahti.paths import ROOT

CARDS = ROOT / "agents" / "cards"
VENDOR = "github.com/FrankPonce/yovahti"
TOOLS = ["list_cells", "get_cell_kpis", "get_alarms", "get_events", "get_prices", "get_carbon",
         "forecast_load", "optimise_plan", "propose_change", "apply_change",
         "get_change_status", "rollback"]


def agent_card(agent: str) -> dict:
    prompt = ROLES[agent]
    return {"schema": "yovahti/agent-card@1", "id": agent, "vendor": VENDOR,
            "version": PROMPT_VERSION,
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "allowed_tools": TOOLS,
            "scope": {"clusters": "*", "parameters": ["capacity_cell_sleep"]},
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
