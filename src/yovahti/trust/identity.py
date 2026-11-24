"""Agent key bindings (I20): which agent, card and model a request-signing key speaks for.

A binding is a compact JWS statement signed by the operator's key:

    {"typ": "yovahti/agent-key-binding@1", "agent": "energy-agent",
     "card_sha256": "...", "model": "deepseek:deepseek-v4-flash",
     "key": {public Ed25519 JWK}, "scope": {"clusters": "*"}, "role": "energy",
     "issued_at": "...", "expires_at": "..."}

The binding is separate from the Agent Card on purpose: rotating a key does not change the
card hash, so NetCrash attestations (bound to card hash x model) stay valid. Admission then
works on the identity the *signature* proves, not on what the client claims.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from yovahti.trust.admission import AgentIdentity
from yovahti.trust.httpsig import Verifier
from yovahti.trust.signing import public_part, sign_statement, verify_statement

TYP = "yovahti/agent-key-binding@1"


def bind_key(agent: str, card_sha256: str, model: str, agent_key: dict, operator_key: dict,
             *, role: str = "energy", clusters: list[str] | None = None,
             days: int = 30) -> str:
    now = datetime.now(UTC)
    st = {"typ": TYP, "agent": agent, "card_sha256": card_sha256, "model": model,
          "key": public_part(agent_key), "role": role,
          "scope": {"clusters": clusters or "*"},
          "issued_at": now.isoformat(timespec="seconds"),
          "expires_at": (now + timedelta(days=days)).isoformat(timespec="seconds")}
    return sign_statement(st, operator_key)


@dataclass
class Bound:
    identity: AgentIdentity
    card_sha256: str
    key: dict


class KeyRegistry:
    """Verified bindings by keyid; the request `Verifier` uses their keys."""

    def __init__(self, operator_jwks: dict, bindings: list[str]):
        self.by_kid: dict[str, Bound] = {}
        self.rejected: list[str] = []
        now = datetime.now(UTC)
        for jws in bindings:
            v = verify_statement(jws, operator_jwks)
            st = v.get("statement", {})
            if not v["ok"] or st.get("typ") != TYP:
                self.rejected.append(v.get("reason", "wrong statement type"))
                continue
            if datetime.fromisoformat(st["expires_at"]) < now:
                self.rejected.append(f"binding for {st['agent']} expired")
                continue
            cl = st["scope"]["clusters"]
            ident = AgentIdentity(st["agent"], model=st["model"], role=st.get("role", "energy"),
                                  may_sleep=st.get("role", "energy") != "coverage",
                                  scope_clusters=None if cl == "*" else frozenset(cl))
            self.by_kid[st["key"]["kid"]] = Bound(ident, st["card_sha256"], st["key"])
        self.verifier = Verifier({k: b.key for k, b in self.by_kid.items()})

    def identity(self, kid: str) -> AgentIdentity | None:
        b = self.by_kid.get(kid)
        return b.identity if b else None
