"""Rekor entries published for NetCrash (I34) check offline; tampering is caught."""

import base64
import copy
import json

from yovahti.paths import RESULTS
from yovahti.trust import rekor

DIR = RESULTS / "netcrash" / "rekor"


def entries():
    return [json.loads(p.read_text()) for p in sorted(DIR.glob("2026-*.json"))]


def test_published_entries_are_included_and_timestamped():
    pem = (DIR / "log-public-key.pem").read_bytes()
    es = entries()
    assert len(es) >= 8
    for e in es:
        assert rekor.check(e["entry"], pem)["ok"] and e["payload_hash_matches"]


def test_tampered_body_or_timestamp_fails():
    pem = (DIR / "log-public-key.pem").read_bytes()
    e = entries()[0]["entry"]
    body = json.loads(base64.b64decode(e["body"]))
    body["spec"]["payloadHash"]["value"] = "0" * 64
    bad = copy.deepcopy(e)
    bad["body"] = base64.b64encode(json.dumps(body).encode()).decode()
    assert not rekor.check(bad, pem)["ok"]
    late = copy.deepcopy(e)
    late["integratedTime"] += 1
    assert "timestamp" in rekor.check(late, pem)["reason"]


def test_proposed_entry_carries_the_tester_key_only():
    env = {"payloadType": "t", "payload": "e30=", "signatures": [{"keyid": "k", "sig": "AA=="}]}
    jwk = {"kty": "OKP", "crv": "Ed25519", "x": "11qYAYKxCrfVS_7TyWQHOg7hcvPapiMlrwIaaPcHURo"}
    p = rekor.proposed(env, jwk)
    pem = base64.b64decode(p["spec"]["proposedContent"]["verifiers"][0])
    assert pem.startswith(b"-----BEGIN PUBLIC KEY-----") and b"PRIVATE" not in pem
