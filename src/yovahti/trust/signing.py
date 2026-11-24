"""Ed25519 keys, JCS hashing, compact JWS and DSSE: a Python port of agent-trust-kit's
`keys.js`, `canonical.js`, `statements.js` and `dsse.js` (D2).

Compatibility is checked, not assumed: the kit's deterministic test vectors (key id, network
hash, compact JWS) must come out byte for byte (tests/test_trust.py), and DSSE envelopes signed
here verify with the kit's own `verifyEnvelope` (scripts/check_trust_kit_compat.mjs).

Differences on purpose: keys come from a local trusted JWKS instead of an HTTPS key directory
per check (an operator's arbiter shouldn't depend on fetching a vendor's website at apply
time); no RFC 9421 request signing yet (I20).
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

import rfc8785
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

INTOTO_PAYLOAD_TYPE = "application/vnd.in-toto+json"


# ------------------------------------------------------------------ encodings
def b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def from_b64(text: str) -> bytes:
    """Standard or URL-safe base64, padded or not (DSSE verifiers accept both)."""
    std = text.replace("-", "+").replace("_", "/")
    return base64.b64decode(std + "=" * (-len(std) % 4))


def canonical_json(value: Any) -> str:
    return rfc8785.dumps(value).decode("utf-8")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(rfc8785.dumps(value)).hexdigest()


# ------------------------------------------------------------------ keys
def thumbprint(jwk: dict) -> str:
    """RFC 7638 JWK thumbprint of an Ed25519 (OKP) key."""
    members = {"crv": jwk["crv"], "kty": jwk["kty"], "x": jwk["x"]}
    text = json.dumps(members, separators=(",", ":"), sort_keys=True)
    return b64url(hashlib.sha256(text.encode()).digest())


def new_key() -> dict:
    """A new Ed25519 private JWK with kid, alg and use (as the kit's newSiteKey)."""
    sk = Ed25519PrivateKey.generate()
    raw_pub = sk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    from cryptography.hazmat.primitives.serialization import NoEncryption, PrivateFormat
    raw = sk.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    jwk = {"kty": "OKP", "crv": "Ed25519", "x": b64url(raw_pub), "d": b64url(raw)}
    return {**jwk, "kid": thumbprint(jwk), "alg": "EdDSA", "use": "sig"}


def public_part(jwk: dict) -> dict:
    if jwk.get("kty") != "OKP" or jwk.get("crv") != "Ed25519" or not jwk.get("x"):
        raise ValueError("only Ed25519 (OKP) keys are supported")
    return {"kty": "OKP", "crv": "Ed25519", "x": jwk["x"], "kid": jwk.get("kid") or thumbprint(jwk),
            "alg": "EdDSA", "use": "sig"}


def _private(jwk: dict) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(from_b64(jwk["d"]))


def _public(jwk: dict) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(from_b64(jwk["x"]))


def find_key(jwks: dict, kid: str) -> dict | None:
    for k in (jwks or {}).get("keys", []):
        if k.get("kid") == kid and k.get("kty") == "OKP" and k.get("crv") == "Ed25519":
            return k
    return None


# ------------------------------------------------------------------ compact JWS (statements.js)
def sign_statement(statement: dict, private_jwk: dict) -> str:
    if not statement.get("typ"):
        raise ValueError("a statement needs a typ")
    if not private_jwk.get("kid"):
        raise ValueError("the signing key needs a kid")
    header = {"alg": "EdDSA", "kid": private_jwk["kid"], "typ": "JOSE", "cty": statement["typ"]}
    h = b64url(json.dumps(header, separators=(",", ":")).encode())
    p = b64url(canonical_json(statement).encode())
    sig = _private(private_jwk).sign(f"{h}.{p}".encode())
    return f"{h}.{p}.{b64url(sig)}"


def verify_statement(jws: str, jwks: dict) -> dict:
    try:
        h, p, s = jws.split(".")
        header = json.loads(from_b64(h))
    except ValueError:
        return {"ok": False, "reason": "not a compact JWS"}
    if header.get("alg") != "EdDSA" or not header.get("kid"):
        return {"ok": False, "reason": "unsupported algorithm or missing kid"}
    jwk = find_key(jwks, header["kid"])
    if not jwk:
        return {"ok": False, "reason": f"key {header['kid']} is not in the given key directory"}
    try:
        _public(jwk).verify(from_b64(s), f"{h}.{p}".encode())
    except (InvalidSignature, ValueError):
        return {"ok": False, "reason": "signature does not verify"}
    statement = json.loads(from_b64(p))
    if header.get("cty") and statement.get("typ") != header["cty"]:
        return {"ok": False, "reason": "header and payload types differ"}
    return {"ok": True, "statement": statement, "kid": header["kid"]}


# ------------------------------------------------------------------ DSSE (dsse.js)
def pae(payload_type: str, body: bytes) -> bytes:
    t = payload_type.encode()
    return b"DSSEv1 %d %s %d " % (len(t), t, len(body)) + body


def sign_envelope(payload: bytes | str, payload_type: str, keys: dict | list[dict]) -> dict:
    body = payload.encode() if isinstance(payload, str) else payload
    keys = [keys] if isinstance(keys, dict) else keys
    if not keys or any(not k.get("kid") for k in keys):
        raise ValueError("each signing key needs a kid")
    msg = pae(payload_type, body)
    return {"payloadType": payload_type, "payload": b64(body),
            "signatures": [{"keyid": k["kid"], "sig": b64(_private(k).sign(msg))} for k in keys]}


def verify_envelope(envelope: dict | str, jwks: dict, payload_type: str | None = None) -> dict:
    env = envelope
    if isinstance(env, str):
        try:
            env = json.loads(env)
        except json.JSONDecodeError:
            return {"ok": False, "reason": "not a DSSE envelope (not JSON)"}
    if (not isinstance(env, dict) or not isinstance(env.get("payloadType"), str)
            or not isinstance(env.get("payload"), str) or not env.get("signatures")):
        return {"ok": False, "reason": "not a DSSE envelope"}
    if payload_type and env["payloadType"] != payload_type:
        return {"ok": False, "reason": f"payload type is {env['payloadType']}, not {payload_type}"}
    try:
        body = from_b64(env["payload"])
    except ValueError:
        return {"ok": False, "reason": "payload is not base64"}
    msg = pae(env["payloadType"], body)
    known = False
    for s in env["signatures"]:
        jwk = find_key(jwks, s.get("keyid", "")) if isinstance(s, dict) else None
        if not jwk:
            continue
        known = True
        try:
            _public(jwk).verify(from_b64(s["sig"]), msg)
            return {"ok": True, "payload": body, "payloadType": env["payloadType"],
                    "keyid": s["keyid"]}
        except (InvalidSignature, ValueError):
            pass
    return {"ok": False, "reason": "signature does not verify" if known else
            "no signature from a key in the given key directory"}
