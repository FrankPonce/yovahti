"""Who may act: the admission interface the MCP server calls before the arbiter (I6).

This is the seam for S8. The real ``admit()`` (ported from agent-trust-kit and checked against
its test vectors, D2) verifies the request signature, the signed Agent Card and its scope, the
declared model, and a NetCrash attestation for (card hash, model, suite version). Until then,
``AllowListAdmission`` admits by agent id only and says so in every decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class AgentIdentity:
    agent_id: str
    model: str = "unknown"
    scope_clusters: frozenset[str] | None = None     # None = every cluster
    may_wake: bool = True
    may_sleep: bool = True


@dataclass
class Decision:
    admitted: bool
    reasons: list[str] = field(default_factory=list)
    basis: str = ""


class Admission(Protocol):
    def admit(self, agent: AgentIdentity) -> Decision: ...


@dataclass
class AllowListAdmission:
    """Placeholder: admit listed agent ids (``None`` admits everyone). Not a trust decision."""
    allowed: set[str] | None = None

    def admit(self, agent: AgentIdentity) -> Decision:
        basis = "allow-list placeholder (no attestation check yet, S8)"
        if self.allowed is None or agent.agent_id in self.allowed:
            return Decision(True, [], basis)
        return Decision(False, [f"agent {agent.agent_id!r} is not admitted"], basis)
