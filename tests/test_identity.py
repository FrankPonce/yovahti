"""Signed agent identity (I20): RFC 9421 request signatures and operator-signed key bindings,
end to end over Streamable HTTP."""

import anyio
import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from test_mcp_server import make

from yovahti.mcp_server.auth import SignedAgents, SignedAuth
from yovahti.mcp_server.server import build_server
from yovahti.trust.httpsig import Verifier, sign_request
from yovahti.trust.identity import KeyRegistry, bind_key
from yovahti.trust.signing import new_key, public_part

URL = "http://127.0.0.1:8765/mcp"
OPERATOR = new_key()
JWKS = {"keys": [public_part(OPERATOR)]}


def test_signature_round_trip_and_failures():
    key = new_key()
    v = Verifier({key["kid"]: public_part(key)})
    h = sign_request("POST", URL, b'{"a":1}', key, now=1000)
    assert v.verify("POST", URL, h, b'{"a":1}', now=1001)["ok"]
    assert "replayed" in v.verify("POST", URL, h, b'{"a":1}', now=1002)["reason"]
    h = sign_request("POST", URL, b'{"a":1}', key, now=1000)
    assert "Content-Digest" in v.verify("POST", URL, h, b'{"a":2}', now=1001)["reason"]
    h = sign_request("POST", URL, b"", key, now=1000)
    assert not v.verify("POST", URL.replace("/mcp", "/other"), h, b"", now=1001)["ok"]
    assert "time window" in v.verify("POST", URL, h, b"", now=2000)["reason"]
    other = new_key()
    h = sign_request("POST", URL, b"", other, now=1000)
    assert "unknown keyid" in v.verify("POST", URL, h, b"", now=1001)["reason"]
    assert "unsigned" in v.verify("POST", URL, {}, b"")["reason"]


def test_bindings_must_be_signed_by_the_operator():
    agent = new_key()
    good = bind_key("energy-agent", "ab" * 32, "deepseek:v4-flash", agent, OPERATOR)
    forged = bind_key("energy-agent", "ab" * 32, "deepseek:v4-flash", new_key(), new_key())
    reg = KeyRegistry(JWKS, [good, forged])
    assert reg.identity(agent["kid"]).model == "deepseek:v4-flash"
    assert len(reg.by_kid) == 1 and reg.rejected


def call(net, registry, key, steps):
    """Run ``steps(client)`` against the signed HTTP app; returns its result."""
    mcp = build_server(net, None)
    app = mcp.streamable_http_app(host="127.0.0.1")
    out = {}

    async def go():
        async with app.router.lifespan_context(app):
            hc = httpx2.AsyncClient(transport=httpx2.ASGITransport(SignedAgents(app, registry)),
                                    auth=SignedAuth(key) if key else None, timeout=30)
            async with hc, Client(streamable_http_client(URL, http_client=hc)) as c:
                out["r"] = await steps(c)
    anyio.run(go)
    return out["r"]


def test_tools_act_as_the_agent_the_signature_proves():
    net = make()
    key = new_key()
    reg = KeyRegistry(JWKS, [bind_key("energy-agent", "cd" * 32, "qwen:3.8-27b", key, OPERATOR)])

    async def steps(c):
        p = await c.call_tool("propose_change", {"actions": [{"cell": "s0-1/mid",
                              "action": "sleep", "from_qh": 0, "quarter_hours": 8}],
                              "rationale": "night"})
        return await c.call_tool("apply_change", {"change_id": p.structured_content["change_id"]})

    r = call(net, reg, key, steps)
    assert r.structured_content["status"] == "applied"
    ch = next(iter(net.changes.values()))
    assert ch.agent == "energy-agent"


def test_coverage_binding_cannot_sleep_cells():
    net = make()
    key = new_key()
    reg = KeyRegistry(JWKS, [bind_key("coverage-agent", "ef" * 32, "m", key, OPERATOR,
                                      role="coverage")])

    async def steps(c):
        p = await c.call_tool("propose_change", {"actions": [{"cell": "s0-1/mid",
                              "action": "sleep", "from_qh": 0, "quarter_hours": 8}],
                              "rationale": "pretend"})
        return await c.call_tool("apply_change", {"change_id": p.structured_content["change_id"]})

    r = call(net, reg, key, steps)
    assert r.structured_content["status"] == "refused"
    assert "may not put cells to sleep" in " ".join(r.structured_content["reasons"])


@pytest.mark.parametrize("which", ["unsigned", "unbound"])
def test_unsigned_or_unbound_clients_never_reach_the_tools(which):
    net = make()
    bound, stranger = new_key(), new_key()
    reg = KeyRegistry(JWKS, [bind_key("energy-agent", "00" * 32, "m", bound, OPERATOR)])

    async def steps(c):
        return await c.list_tools()

    with pytest.raises(BaseException):  # noqa: B017 - the transport refuses with 401
        call(net, reg, None if which == "unsigned" else stranger, steps)
    assert not net.changes
