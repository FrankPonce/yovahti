"""Signed agent identity on Streamable HTTP (I20).

`SignedAgents` is ASGI middleware in front of the MCP app: it verifies the RFC 9421 request
signature (`trust.httpsig`) and puts the identity proven by the key binding
(`trust.identity`) on the request, where the tools read it. Unsigned, tampered, replayed or
unknown-key requests get 401 before the MCP server sees them.

With ``cards`` ({card SHA-256: allowed tool names}), a ``tools/call`` for a tool that is not
in the *bound* card's ``allowed_tools`` is answered with a JSON-RPC error and never reaches
the tool (I37); a binding whose card is unknown may call nothing (fail closed).

`SignedAuth` is the client side: an httpx auth hook that signs every request.
"""

from __future__ import annotations

import json
from typing import Any

import httpx2

from yovahti.trust.httpsig import sign_request
from yovahti.trust.identity import KeyRegistry


class SignedAgents:
    def __init__(self, app: Any, registry: KeyRegistry,
                 cards: dict[str, set[str]] | None = None):
        self.app, self.registry, self.cards = app, registry, cards

    def _out_of_card(self, kid: str, body: bytes) -> dict | None:
        """JSON-RPC error for the first tools/call the bound card does not allow, else None."""
        if self.cards is None:
            return None
        try:
            msgs = json.loads(body or b"null")
        except ValueError:
            return None
        allowed = self.cards.get(self.registry.by_kid[kid].card_sha256)
        for m in msgs if isinstance(msgs, list) else [msgs]:
            if not isinstance(m, dict) or m.get("method") != "tools/call":
                continue
            name = (m.get("params") or {}).get("name")
            if allowed is None or name not in allowed:
                why = ("the agent card bound to this key is unknown to the server"
                       if allowed is None else f"tool {name!r} is not in the agent card's "
                                               "allowed_tools")
                return {"jsonrpc": "2.0", "id": m.get("id"),
                        "error": {"code": -32601, "message": f"refused: {why} (I37)"}}
        return None

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
        refused = self._out_of_card(v["keyid"], body)
        if refused is not None:
            await send({"type": "http.response.start", "status": 200,
                        "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": json.dumps(refused).encode()})
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
