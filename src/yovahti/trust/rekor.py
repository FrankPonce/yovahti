"""Publish NetCrash attestations to Sigstore Rekor and check them (D21, I34).

Each DSSE envelope goes into Rekor v1 as a ``dsse`` entry with the tester's Ed25519 public key
as verifier: Rekor checks the signature itself before it logs anything. What we keep per entry
(``results/netcrash/rekor/*.json``) lets anyone check, offline, that the entry is in the log:

* the Merkle inclusion proof (RFC 6962 hashing) recomputes the checkpoint's root hash, and
* the Signed Entry Timestamp verifies with the log's public key over
  ``{body, integratedTime, logID, logIndex}`` (canonical JSON).

Production (rekor.sigstore.dev) is public and permanent; staging (rekor.sigstage.dev) is for
tests. Entries hold hashes, the signature and the tester public key: nothing personal.
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from cryptography.hazmat.primitives.serialization import load_pem_public_key as load_pem

from yovahti.trust.signing import from_b64

PRODUCTION = "https://rekor.sigstore.dev"
STAGING = "https://rekor.sigstage.dev"


def pem_of(jwk: dict) -> bytes:
    key = Ed25519PublicKey.from_public_bytes(from_b64(jwk["x"]))
    return key.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)


def proposed(envelope: dict, jwk: dict) -> dict:
    return {"apiVersion": "0.0.1", "kind": "dsse",
            "spec": {"proposedContent": {
                "envelope": json.dumps(envelope, separators=(",", ":")),
                "verifiers": [base64.b64encode(pem_of(jwk)).decode()]}}}


def upload(envelope: dict, jwk: dict, url: str = STAGING, client: Any = None) -> dict:
    """Log one envelope; returns ``{uuid, ...entry}``. An existing identical entry (409) is
    fetched instead, so re-running is safe."""
    c = client or httpx.Client(timeout=30)
    r = c.post(f"{url}/api/v1/log/entries", json=proposed(envelope, jwk))
    if r.status_code == 409:
        loc = r.headers.get("location") or ""
        r = c.get(f"{url}{loc}" if loc.startswith("/") else loc)
    r.raise_for_status()
    (uuid, entry), = r.json().items()
    return {"uuid": uuid, "url": url, **entry}


def log_key(url: str = STAGING, client: Any = None) -> bytes:
    c = client or httpx.Client(timeout=30)
    r = c.get(f"{url}/api/v1/log/publicKey")
    r.raise_for_status()
    return r.content


# ------------------------------------------------------------------ offline checks
def _leaf(body: bytes) -> bytes:
    return hashlib.sha256(b"\x00" + body).digest()


def _node(a: bytes, b: bytes) -> bytes:
    return hashlib.sha256(b"\x01" + a + b).digest()


def root_from_proof(index: int, size: int, leaf: bytes, path: list[bytes]) -> bytes:
    """RFC 9162 section 2.1.3.2: recompute the root from an inclusion proof."""
    if index >= size:
        raise ValueError("index beyond tree size")
    fn, sn, r = index, size - 1, leaf
    for p in path:
        if sn == 0:
            raise ValueError("proof too long")
        if fn & 1 or fn == sn:
            r = _node(p, r)
            if not fn & 1:
                while fn and not fn & 1:
                    fn, sn = fn >> 1, sn >> 1
        else:
            r = _node(r, p)
        fn, sn = fn >> 1, sn >> 1
    if sn != 0:
        raise ValueError("proof too short")
    return r


def check(entry: dict, log_pem: bytes) -> dict:
    """Inclusion proof and Signed Entry Timestamp; ``{"ok": bool, "reason": ...}``."""
    v = entry.get("verification") or {}
    proof = v.get("inclusionProof") or {}
    body = base64.b64decode(entry["body"])
    try:
        root = root_from_proof(proof["logIndex"], proof["treeSize"], _leaf(body),
                               [bytes.fromhex(h) for h in proof["hashes"]])
    except (KeyError, ValueError) as e:
        return {"ok": False, "reason": f"inclusion proof: {e}"}
    if root.hex() != proof["rootHash"]:
        return {"ok": False, "reason": "inclusion proof does not reach the root hash"}
    payload = {"body": entry["body"], "integratedTime": entry["integratedTime"],
               "logID": entry["logID"], "logIndex": entry["logIndex"]}
    msg = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    key = load_pem(log_pem)
    try:
        key.verify(base64.b64decode(v["signedEntryTimestamp"]), msg, ec.ECDSA(hashes.SHA256()))
    except Exception as e:  # noqa: BLE001 - any failure is a failed check
        return {"ok": False, "reason": f"signed entry timestamp: {type(e).__name__}"}
    return {"ok": True, "reason": "included and timestamped"}


def envelope_hash(envelope: dict) -> str:
    """What the logged ``dsse`` body records for the payload (sha256 of the raw payload)."""
    return hashlib.sha256(from_b64(envelope["payload"])).hexdigest()
