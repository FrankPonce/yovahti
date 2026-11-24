"""Signed agent identity on Streamable HTTP (I20).

`SignedAgents` is ASGI middleware in front of the MCP app: it verifies the RFC 9421 request
signature (`trust.httpsig`) and puts the identity proven by the key binding
(`trust.identity`) on the request, where the tools read it. Unsigned, tampered, replayed or
unknown-key requests get 401 before the MCP server sees them.

`SignedAuth` is the client side: an httpx auth hook that signs every request.
"""

from __future__ import annotations

import json
from typing import Any

import httpx2

from yovahti.trust.httpsig import sign_request
from yovahti.trust.identity import KeyRegistry


class SignedAgents:
    def __init__(self, app: Any, registry: KeyRegistry):
        self.app, self.registry = app, registry

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        body, more = b"", True
        while more:
            msg = await receive()
            body += msg.get("body", b"")
            more = msg.get("more_body", False)
        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope["headers"]}
        host = headers.get("host", "")
        url = f"{scope.get('scheme', 'http')}://{host}{scope.get('path', '/')}"
        v = self.registry.verifier.verify(scope["method"], url, headers, body)
        ident = self.registry.identity(v["keyid"]) if v["ok"] else None
        if ident is None:
            reason = v.get("reason") or "key has no binding"
            data = json.dumps({"error": "agent authentication failed", "reason": reason}).encode()
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"application/json"),
                                    (b"www-authenticate", b'Signature tag="yovahti-mcp"')]})
            await send({"type": "http.response.body", "body": data})
            return
        scope.setdefault("state", {})["agent"] = ident
        sent = False

        async def replay() -> dict:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


class SignedAuth(httpx2.Auth):
    """Signs each request with the agent's private JWK (RFC 9421 profile `yovahti-mcp`)."""
    requires_request_body = True

    def __init__(self, private_jwk: dict):
        self.key = private_jwk

    def auth_flow(self, request: httpx2.Request):
        for k, v in sign_request(request.method, str(request.url), request.content,
                                 self.key).items():
            request.headers[k] = v
        yield request
