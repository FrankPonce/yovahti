"""Minimal agent loop over an MCP client (D8): bounded steps, every step traced.

No framework, no hidden retries or prompt text: the model sees the system prompt, the task and
the MCP tools as OpenAI-style functions; each tool call goes to the MCP server and its result
(truncated, with a notice) goes back. The run ends when the model answers without tool calls,
or at ``max_steps`` (recorded as such). Format failures are kept apart from safety outcomes
(I18): a model that never manages a tool call ends as ``no_tool_use``.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from mcp import Client

MAX_RESULT_CHARS = 12_000


class Chat(Protocol):
    spec: str
    usage: dict

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict: ...


@dataclass
class Trace:
    agent: str
    model: str
    task: str
    steps: list[dict] = field(default_factory=list)
    outcome: str = "running"     # answered | max_steps | no_tool_use | error
    answer: str = ""
    usage: dict = field(default_factory=dict)
    seconds: float = 0.0

    def tool_calls(self) -> list[dict]:
        return [s for s in self.steps if s["kind"] == "tool"]

    def to_json(self) -> dict:
        return self.__dict__


def tool_specs(tools) -> list[dict]:
    return [{"type": "function", "function": {
        "name": t.name, "description": t.description or "",
        "parameters": t.input_schema or {"type": "object", "properties": {}}}} for t in tools]


def _result_text(res) -> tuple[str, bool]:
    if res.structured_content is not None:
        txt = json.dumps(res.structured_content, ensure_ascii=False)
    else:
        txt = "\n".join(getattr(c, "text", "") for c in res.content)
    if len(txt) > MAX_RESULT_CHARS:
        txt = txt[:MAX_RESULT_CHARS] + f"\n[truncated: {len(txt)} chars; ask for fewer cells]"
    return txt, bool(res.is_error)


async def run_agent(client: Client, model: Chat, agent: str, system: str, task: str,
                    max_steps: int = 16) -> Trace:
    t0 = time.time()
    tr = Trace(agent=agent, model=model.spec, task=task)
    tools = tool_specs((await client.list_tools()).tools)
    messages: list[dict[str, Any]] = [{"role": "system", "content": system},
                                      {"role": "user", "content": task}]
    used_tools = False
    try:
        for step in range(max_steps):
            msg = model.chat(messages, tools)
            calls = msg.get("tool_calls") or []
            tr.steps.append({"kind": "model", "step": step, "content": msg.get("content") or "",
                             "tool_calls": [c["function"]["name"] for c in calls]})
            if not calls:
                tr.answer = msg.get("content") or ""
                tr.outcome = "answered" if used_tools else "no_tool_use"
                break
            messages.append({"role": "assistant", "content": msg.get("content") or "",
                             "tool_calls": calls})
            for c in calls:
                name = c["function"]["name"]
                try:
                    args = json.loads(c["function"].get("arguments") or "{}")
                    res = await client.call_tool(name, args)
                    txt, err = _result_text(res)
                except json.JSONDecodeError as e:
                    args, txt, err = {}, f"invalid JSON arguments: {e}", True
                used_tools = True
                tr.steps.append({"kind": "tool", "step": step, "tool": name, "args": args,
                                 "is_error": err, "result": txt[:2000]})
                messages.append({"role": "tool", "tool_call_id": c.get("id", name),
                                 "content": txt})
        else:
            tr.outcome = "max_steps"
    except Exception as e:  # noqa: BLE001 - recorded, not hidden
        tr.outcome, tr.answer = "error", f"{type(e).__name__}: {e}"
    tr.usage = dict(model.usage)
    tr.seconds = round(time.time() - t0, 1)
    return tr
