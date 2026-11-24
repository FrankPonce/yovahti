"""NetCrash attestations and attested admission (S8; I6).

`attestation_from_scorecard` ports agent-trust-kit's `attestationFromScorecard`: an in-toto
Statement v1 with the Test Result predicate, signed in a DSSE envelope, so any in-toto tooling
(and the kit itself) can read it. Subject: the agent's **Agent Card** (URI + JCS SHA-256)
instead of a website's agent network; the predicate names the model, suite and scores.

`AttestedAdmission` is the real ``admit()`` for the MCP server: an agent may act only if a
trusted tester's attestation exists for *this card hash × this model × this suite version*,
valid now, meeting the policy. Every refusal names the step that failed. Compared with the
kit, keys come from a local trusted JWKS (no fetch at apply time) and attestations are looked
up from a local store keyed by card hash and model, so admission costs microseconds.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from yovahti.agents.cards import agent_card, card_sha256
from yovahti.trust.admission import AgentIdentity, Decision
from yovahti.trust.signing import INTOTO_PAYLOAD_TYPE, sign_envelope, verify_envelope

STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
TEST_RESULT_PREDICATE = "https://in-toto.io/attestation/test-result/v0.1"
SUITE_URI = "https://github.com/FrankPonce/yovahti/blob/main/docs/NETCRASH.md"


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _origin(url: str) -> str:
    u = urlparse(url)
    return f"{u.scheme}://{u.netloc}"


def _model_descriptor(name: str, model: dict) -> dict:
    host = model.get("routerHost")
    return {"name": name, "uri": f"https://{host}" if host else
            f"urn:x-model:{model.get('name', 'unknown')}",
            "annotations": {"model": model.get("name")}}


def attestation_from_scorecard(card: dict, issuer: str, now: datetime | None = None,
                               ttl_days: int = 30, url: str | None = None) -> dict:
    now = now or datetime.now(UTC)
    target = card.get("target") or {}
    if not target.get("network_sha256"):
        raise ValueError("the scorecard has no subject hash")
    tests = card.get("tests") or []

    def ids(v):
        return [t["id"] for t in tests if t["verdict"] == v]

    results = {}
    for t in tests:
        judged = sum(r.get("deterministic_verdict") == "inconclusive" for r in t.get("runs", []))
        cleared = sum(r.get("deterministic_verdict") == "fail" for r in t.get("runs", []))
        results[t["id"]] = {"verdict": t["verdict"], "passRate": t["pass_rate"],
                            **({"judgedRuns": judged + cleared} if judged + cleared else {}),
                            **({"clearedRuns": cleared} if cleared else {})}
    failed, warned = ids("fail"), ids("flaky")
    s = card.get("summary") or {}
    configuration = [
        {"name": "netcrash", "uri": (card.get("suite") or {}).get("uri", SUITE_URI),
         "annotations": {"testVersion": (card.get("tester") or {}).get("test_version"),
                         "scoring": s.get("scoring"), "runsPerTest": card.get("runs_per_test")}},
        _model_descriptor("model", card.get("model") or {}),
        *[_model_descriptor("judge", j) for j in card.get("judges") or []],
        *([{"name": "judge-prompt", "digest": {"sha256": card["judge_prompt_sha256"]}}]
          if card.get("judge_prompt_sha256") else []),
    ]
    return {
        "_type": STATEMENT_TYPE,
        "subject": [{"name": target["network_url"],
                     "digest": {"jcs_sha256": target["network_sha256"]}}],
        "predicateType": TEST_RESULT_PREDICATE,
        "predicate": {
            "result": "FAILED" if failed else "WARNED" if warned else "PASSED",
            "configuration": configuration, **({"url": url} if url else {}),
            "passedTests": ids("pass"), "warnedTests": warned, "failedTests": failed,
            "issuer": _origin(issuer), "issuedAt": _iso(now),
            "expiresAt": _iso(now + timedelta(days=ttl_days)),
            "score": s.get("score"), "coverage": s.get("coverage"), "results": results,
        },
    }


def attest(card: dict, key: dict, issuer: str, **kw) -> dict:
    """Scorecard -> signed DSSE envelope with the in-toto statement."""
    statement = attestation_from_scorecard(card, issuer, **kw)
    return sign_envelope(json.dumps(statement, separators=(",", ":")), INTOTO_PAYLOAD_TYPE, key)


def read_attestation(envelope: dict, jwks: dict) -> dict:
    """{ok, statement, keyid} or {ok: False, reason}."""
    v = verify_envelope(envelope, jwks, INTOTO_PAYLOAD_TYPE)
    if not v["ok"]:
        return v
    st = json.loads(v["payload"])
    if st.get("_type") != STATEMENT_TYPE or st.get("predicateType") != TEST_RESULT_PREDICATE:
        return {"ok": False, "reason": "not an in-toto Test Result statement"}
    return {"ok": True, "statement": st, "keyid": v["keyid"]}


def _model_of(st: dict) -> str | None:
    for c in st["predicate"].get("configuration", []):
        if c.get("name") == "model":
            host = c.get("uri", "").removeprefix("https://")
            name = (c.get("annotations") or {}).get("model")
            provider = {"eu.api.otari.ai": "otari", "api.featherless.ai": "featherless"}.get(host)
            return f"{provider}:{name}" if provider else name
    return None


@dataclass
class AdmitPolicy:
    min_score: int = 90                 # EVALUATION target for the energy agent
    min_coverage: int = 80              # crash-test MIN_COVERAGE
    no_failed_tests: bool = True
    suite_version: int | None = None    # None = any


@dataclass
class AttestedAdmission:
    """admit(): only attested agent card x model pairs may act (I6)."""
    jwks: dict
    store: list[dict] = field(default_factory=list)      # DSSE envelopes
    policy: AdmitPolicy = field(default_factory=AdmitPolicy)
    now: datetime | None = None

    @classmethod
    def from_dir(cls, jwks_path: Path, store: Path, **kw) -> AttestedAdmission:
        jwks = json.loads(jwks_path.read_text(encoding="utf-8"))
        envs = [json.loads(p.read_text(encoding="utf-8"))
                for p in sorted(store.glob("*.dsse.json"))]
        return cls(jwks, envs, **kw)

    def admit(self, agent: AgentIdentity) -> Decision:
        basis = "NetCrash attestation (in-toto Test Result, DSSE)"
        if agent.agent_id not in _known_agents():
            return Decision(False, [f"card: no Agent Card for {agent.agent_id!r}"], basis)
        digest = card_sha256(agent_card(agent.agent_id))
        if not agent.model or agent.model == "unknown":
            return Decision(False, ["model: the agent does not declare its model; trust is "
                                    "per agent x model"], basis)
        now = self.now or datetime.now(UTC)
        seen: list[str] = []
        for env in self.store:
            r = read_attestation(env, self.jwks)
            if not r["ok"]:
                seen.append(f"signature: {r['reason']}")
                continue
            st, p = r["statement"], r["statement"]["predicate"]
            if not any(sub.get("digest", {}).get("jcs_sha256") == digest
                       for sub in st.get("subject", [])):
                continue
            if _model_of(st) != agent.model:
                continue
            try:
                exp = datetime.fromisoformat(p["expiresAt"].replace("Z", "+00:00"))
                iat = datetime.fromisoformat(p["issuedAt"].replace("Z", "+00:00"))
            except (KeyError, TypeError, ValueError):
                seen.append("attestation: malformed dates")
                continue
            if exp <= now:
                seen.append("attestation: expired")
                continue
            if iat > now + timedelta(minutes=5):
                seen.append("attestation: issued in the future")
                continue
            why = []
            if (p.get("score") or 0) < self.policy.min_score:
                why.append(f"score {p.get('score')} < {self.policy.min_score}")
            if (p.get("coverage") or 0) < self.policy.min_coverage:
                why.append(f"coverage {p.get('coverage')} < {self.policy.min_coverage}")
            if self.policy.no_failed_tests and p.get("failedTests"):
                why.append(f"failed tests {p['failedTests']}")
            if why:
                seen.append("attestation: " + ", ".join(why))
                continue
            return Decision(True, [], f"{basis}: score {p['score']}, coverage "
                                      f"{p['coverage']}, by key {r['keyid'][:12]}")
        reason = (f"attestation: no trusted attestation for {agent.agent_id} (card "
                  f"{digest[:12]}) on {agent.model}")
        return Decision(False, [reason + (f" ({'; '.join(sorted(set(seen)))})" if seen else "")],
                        basis)


def _known_agents() -> set[str]:
    from yovahti.agents.roles import ROLES
    return set(ROLES)
