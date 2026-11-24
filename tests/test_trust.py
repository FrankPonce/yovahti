"""Trust layer: agent-trust-kit vectors reproduced byte for byte; attestations and admit()."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from yovahti.agents.cards import agent_card, card_sha256, card_uri
from yovahti.trust import signing as sg
from yovahti.trust.admission import AgentIdentity
from yovahti.trust.attestation import (
    AdmitPolicy,
    AttestedAdmission,
    attest,
    attestation_from_scorecard,
    read_attestation,
)

V = Path(__file__).parent / "vectors" / "agent_trust_kit"
KEY = json.loads((V / "test-key.vector-jwk.json").read_text())
EXPECTED = json.loads((V / "expected.json").read_text())
NETWORK = json.loads((V / "network.json").read_text())
JWKS = {"keys": [sg.public_part(KEY)]}


# ------------------------------------------------------------------ kit vectors
def test_kid_is_the_kits_rfc7638_thumbprint():
    assert sg.thumbprint(KEY) == EXPECTED["kid"] == KEY["kid"]


def test_network_hash_is_the_kits_jcs_sha256():
    assert sg.canonical_hash(NETWORK) == EXPECTED["network_sha256"]


def test_compact_jws_matches_the_kit_byte_for_byte():
    payload = json.loads(sg.from_b64(EXPECTED["jws"].split(".")[1]))
    assert sg.sign_statement(payload, KEY) == EXPECTED["jws"]
    v = sg.verify_statement(EXPECTED["jws"], JWKS)
    assert v["ok"] and v["statement"]["network_sha256"] == EXPECTED["network_sha256"]


def test_tampered_jws_is_rejected():
    h, p, s = EXPECTED["jws"].split(".")
    bad = json.loads(sg.from_b64(p))
    bad["origin"] = "https://copycat.example"
    forged = f"{h}.{sg.b64url(sg.canonical_json(bad).encode())}.{s}"
    assert sg.verify_statement(forged, JWKS) == {"ok": False,
                                                 "reason": "signature does not verify"}


# ------------------------------------------------------------------ DSSE
def test_dsse_pae_and_round_trip():
    assert sg.pae("t", b"ab") == b"DSSEv1 1 t 2 ab"
    env = sg.sign_envelope('{"a":1}', sg.INTOTO_PAYLOAD_TYPE, KEY)
    assert sg.verify_envelope(env, JWKS, sg.INTOTO_PAYLOAD_TYPE)["ok"]
    env["payload"] = sg.b64(b'{"a":2}')
    assert not sg.verify_envelope(env, JWKS)["ok"]
    other = sg.new_key()
    assert sg.verify_envelope(sg.sign_envelope("x", "t", other), JWKS)["reason"].startswith(
        "no signature from a key")


# ------------------------------------------------------------------ attestations + admit()
def scorecard(agent="energy-agent", model="deepseek/deepseek-v4-flash", score=95, cov=90,
              failed=(), only=None):
    card = agent_card(agent)
    ids = ("N1", "N4", "N6", "N7", "N10", "N11", "N14", "N15", "N16", "N18", "N19")
    tests = [{"id": t, "verdict": "fail" if t in failed else "pass", "pass_rate": 1.0, "runs": []}
             for t in (only or ids)]
    return {"schema": "crash-test/scorecard@1", "tester": {"test_version": 1},
            "suite": {"uri": "https://example/netcrash"}, "runs_per_test": 3,
            "target": {"network_url": card_uri(agent), "network_sha256": card_sha256(card)},
            "model": {"name": model, "routerHost": "eu.api.otari.ai"}, "judges": [],
            "summary": {"score": score, "coverage": cov, "scoring": "decided/1"},
            "tests": tests}


def test_statement_has_the_kits_shape():
    st = attestation_from_scorecard(scorecard(), "https://tester.example")
    assert st["_type"] == "https://in-toto.io/Statement/v1"
    assert st["predicateType"] == "https://in-toto.io/attestation/test-result/v0.1"
    assert st["subject"][0]["digest"]["jcs_sha256"] == card_sha256(agent_card("energy-agent"))
    assert st["predicate"]["result"] == "PASSED" and st["predicate"]["score"] == 95


def admission(*cards, now=None, **policy):
    envs = [attest(c, KEY, "https://tester.example") for c in cards]
    return AttestedAdmission(JWKS, envs, AdmitPolicy(**policy), now=now)


AGENT = AgentIdentity("energy-agent", model="otari:deepseek/deepseek-v4-flash")


def test_admits_only_the_attested_card_and_model():
    adm = admission(scorecard())
    assert adm.admit(AGENT).admitted
    other_model = AgentIdentity("energy-agent", model="otari:openai/gpt-oss-120b")
    d = adm.admit(other_model)
    assert not d.admitted and d.reasons[0].startswith("attestation: no trusted attestation")
    assert not adm.admit(AgentIdentity("sloppy-agent", model=AGENT.model)).admitted
    assert adm.admit(AgentIdentity("energy-agent")).reasons[0].startswith("model:")


@pytest.mark.parametrize("kw,why", [
    ({"score": 60}, "score 60 < 90"), ({"cov": 50}, "coverage 50 < 80"),
    ({"failed": ("N1",)}, "failed tests"),
])
def test_policy_refusals_name_the_reason(kw, why):
    d = admission(scorecard(**kw)).admit(AGENT)
    assert not d.admitted and why in d.reasons[0]


def test_expired_or_forged_attestations_do_not_count():
    later = datetime.now(UTC) + timedelta(days=31)
    assert "expired" in admission(scorecard(), now=later).admit(AGENT).reasons[0]
    env = attest(scorecard(), sg.new_key(), "https://evil.example")
    d = AttestedAdmission(JWKS, [env]).admit(AGENT)
    assert not d.admitted and "signature" in d.reasons[0]


def test_prompt_change_invalidates_the_attestation(monkeypatch):
    adm = admission(scorecard())
    from yovahti.agents import roles
    monkeypatch.setitem(roles.ROLES, "energy-agent", roles.ENERGY + "\nAlso: be bold.")
    assert not adm.admit(AGENT).admitted


def test_read_attestation_rejects_other_payloads():
    env = sg.sign_envelope(json.dumps({"_type": "x"}), sg.INTOTO_PAYLOAD_TYPE, KEY)
    assert read_attestation(env, JWKS)["reason"] == "not an in-toto Test Result statement"


def test_a_partial_suite_is_never_enough():
    d = admission(scorecard(score=100, cov=100, only=("N20",))).admit(AGENT)
    assert not d.admitted and "suite incomplete" in d.reasons[0]
