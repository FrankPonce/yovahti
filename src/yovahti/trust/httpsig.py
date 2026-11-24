"""HTTP Message Signatures (RFC 9421) with Content-Digest (RFC 9530) for MCP over Streamable
HTTP (I20). The MCP spec authenticates *users* (OAuth); this authenticates the *agent*: every
request is signed with the agent's Ed25519 key, and the server maps the key to an identity
through an operator-signed key binding (`trust.identity`).

Profile (a strict subset of RFC 9421, so verification is simple and unambiguous):

    covered components: "@method" "@authority" "@path" "content-digest"
    parameters:         created, expires, nonce, keyid, alg="ed25519", tag="yovahti-mcp"
    label:              sig1

Verification checks the digest against the body, the signature, the time window and the
nonce (replays within the window are refused).
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from yovahti.trust.signing import from_b64

TAG = "yovahti-mcp"
COMPONENTS = ("@method", "@authority", "@path", "content-digest")
MAX_AGE = 300


def content_digest(body: bytes) -> str:
    return "sha-256=:" + base64.b64encode(hashlib.sha256(body).digest()).decode() + ":"


def _params(created: int, expires: int, nonce: str, keyid: str) -> str:
    comps = " ".join(f'"{c}"' for c in COMPONENTS)
    return (f'({comps});created={created};expires={expires};nonce="{nonce}";'
            f'keyid="{keyid}";alg="ed25519";tag="{TAG}"')


def signature_base(method: str, url: str, digest: str, params: str) -> bytes:
    u = urlsplit(url)
    lines = [f'"@method": {method.upper()}', f'"@authority": {u.netloc.lower()}',
             f'"@path": {u.path or "/"}', f'"content-digest": {digest}',
             f'"@signature-params": {params}']
    return "\n".join(lines).encode()


def sign_request(method: str, url: str, body: bytes, private_jwk: dict,
                 now: int | None = None) -> dict[str, str]:
    """Headers to add to a request: Content-Digest, Signature-Input, Signature."""
    created = int(now if now is not None else time.time())
    digest = content_digest(body)
    params = _params(created, created + MAX_AGE, secrets.token_urlsafe(12), private_jwk["kid"])
    key = Ed25519PrivateKey.from_private_bytes(from_b64(private_jwk["d"]))
    sig = key.sign(signature_base(method, url, digest, params))
    return {"Content-Digest": digest, "Signature-Input": f"sig1={params}",
            "Signature": "sig1=:" + base64.b64encode(sig).decode() + ":"}


_INPUT = re.compile(r'^sig1=(\((?:"[^"]+"\s?)+\)(?:;[a-z]+=(?:"[^"]*"|\d+))+)$')


@dataclass
class Verifier:
    """Server side: keys by keyid, and a nonce cache for replay protection."""
    keys: dict[str, dict]                        # keyid -> public JWK
    max_age: int = MAX_AGE
    _seen: dict[str, int] = field(default_factory=dict)

    def verify(self, method: str, url: str, headers: dict[str, str], body: bytes,
               now: int | None = None) -> dict:
        now = int(now if now is not None else time.time())
        h = {k.lower(): v for k, v in headers.items()}
        if "signature-input" not in h or "signature" not in h:
            return {"ok": False, "reason": "unsigned request (RFC 9421 signature required)"}
        m = _INPUT.match(h["signature-input"].strip())
        if not m:
            return {"ok": False, "reason": "Signature-Input is not the yovahti-mcp profile"}
        params = m.group(1)
        comps = re.findall(r'"([^"]+)"', params.split(")")[0])
        if tuple(comps) != COMPONENTS:
            return {"ok": False, "reason": f"must cover exactly {COMPONENTS}"}
        p = dict(re.findall(r';([a-z]+)=("?[^";]*"?)', params))
        p = {k: v.strip('"') for k, v in p.items()}
        if p.get("alg") != "ed25519" or p.get("tag") != TAG:
            return {"ok": False, "reason": "wrong alg or tag"}
        try:
            created, expires = int(p["created"]), int(p["expires"])
        except (KeyError, ValueError):
            return {"ok": False, "reason": "created/expires missing"}
        if created > now + 30 or now > expires or now - created > self.max_age:
            return {"ok": False, "reason": "signature outside its time window"}
        digest = h.get("content-digest", "")
        if digest != content_digest(body):
            return {"ok": False, "reason": "Content-Digest does not match the body"}
        jwk = self.keys.get(p.get("keyid", ""))
        if not jwk:
            return {"ok": False, "reason": f"unknown keyid {p.get('keyid')!r}"}
        sm = re.match(r"^sig1=:([A-Za-z0-9+/=]+):$", h["signature"].strip())
        if not sm:
            return {"ok": False, "reason": "malformed Signature header"}
        try:
            Ed25519PublicKey.from_public_bytes(from_b64(jwk["x"])).verify(
                base64.b64decode(sm.group(1)), signature_base(method, url, digest, params))
        except (InvalidSignature, ValueError):
            return {"ok": False, "reason": "signature does not verify"}
        nonce = p.get("nonce", "")
        self._seen = {n: e for n, e in self._seen.items() if e >= now}
        if not nonce or nonce in self._seen:
            return {"ok": False, "reason": "replayed or missing nonce"}
        self._seen[nonce] = expires
        return {"ok": True, "keyid": p["keyid"]}
