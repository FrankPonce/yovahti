"""OpenAI-compatible chat client with a hard budget guard (D20).

Providers come from ``.env`` (``<NAME>_BASE_URL`` / ``<NAME>_API_KEY``); a model is addressed as
``provider:model-id`` (e.g. ``otari:deepseek/deepseek-v4-flash``). Prices are read from each
provider's ``/models`` listing (cached under ``data/``) and every call's cost is appended to a
ledger (``data/llm_ledger.jsonl``), so caps hold across runs. A call is refused *before* it is
sent once a provider's spend reaches its cap; prices are treated as EUR even when quoted in
USD, which overestimates spend (conservative).

Keys are read at call time and never logged or written anywhere.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from yovahti.paths import DATA, ROOT

LEDGER = DATA / "llm_ledger.jsonl"
CAPS_EUR = {"otari": 6.0, "featherless": 22.0}      # D20, D33


_LOCK = threading.Lock()


class BudgetExceeded(RuntimeError):
    pass


def load_env(path: Path = ROOT / ".env") -> dict[str, str]:
    out = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


@dataclass
class Price:
    input_per_m: float
    output_per_m: float


def _parse_prices(provider: str, listing: dict) -> dict[str, Price]:
    out = {}
    for m in listing.get("data", listing):
        p = m.get("pricing") or {}
        if "input_price_per_million" in p and p.get("unit") in (None, "token", "tokens"):
            out[m["id"]] = Price(float(p["input_price_per_million"]),
                                 float(p.get("output_price_per_million", 0.0)))
        elif "input" in p and "output" in p:
            out[m["id"]] = Price(float(p["input"]), float(p["output"]))
    return out


@dataclass
class Ledger:
    path: Path = LEDGER
    caps: dict[str, float] = field(default_factory=lambda: dict(CAPS_EUR))

    def spent(self, provider: str) -> float:
        if not self.path.exists():
            return 0.0
        tot = 0.0
        for line in self.path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r["provider"] == provider:
                tot += r["cost_eur"]
        return tot

    def check(self, provider: str) -> None:
        cap = self.caps.get(provider, 0.0)
        if self.spent(provider) >= cap:
            raise BudgetExceeded(f"{provider}: spend reached the cap of EUR {cap:.2f} (D20)")

    def record(self, provider: str, model: str, usage: dict, cost: float, run: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK, self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": datetime.now(UTC).isoformat(timespec="seconds"),
                                "provider": provider, "model": model, "run": run,
                                "prompt_tokens": usage.get("prompt_tokens", 0),
                                "completion_tokens": usage.get("completion_tokens", 0),
                                "cost_eur": cost}) + "\n")


@dataclass
class ChatModel:
    """One model on one provider. ``chat()`` returns the assistant message dict."""
    spec: str                                   # "provider:model-id"
    run: str = "adhoc"
    ledger: Ledger = field(default_factory=Ledger)
    temperature: float = 0.0
    max_tokens: int = 8192        # reasoning models spend output tokens before answering
    timeout: float = 120.0
    usage: dict[str, float] = field(default_factory=lambda: {"prompt_tokens": 0,
                                                             "completion_tokens": 0,
                                                             "cost_eur": 0.0, "calls": 0})

    def __post_init__(self) -> None:
        self.provider, self.model = self.spec.split(":", 1)
        env = load_env()
        p = self.provider.upper()
        if f"{p}_BASE_URL" not in env or f"{p}_API_KEY" not in env:
            raise KeyError(f"{p}_BASE_URL / {p}_API_KEY missing in .env")
        self._url = env[f"{p}_BASE_URL"].rstrip("/")
        self._key = env[f"{p}_API_KEY"]
        self.price = self._price()

    def _price(self) -> Price:
        cache = DATA / f"models_{self.provider}.json"
        if not cache.exists() or time.time() - cache.stat().st_mtime > 86400:
            r = httpx.get(f"{self._url}/models", timeout=30,
                          headers={"Authorization": f"Bearer {self._key}"})
            r.raise_for_status()
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(r.text, encoding="utf-8")
        prices = _parse_prices(self.provider, json.loads(cache.read_text(encoding="utf-8")))
        if self.model not in prices:
            raise KeyError(f"no token price for {self.spec}; refusing to run unpriced (D20)")
        return prices[self.model]

    def cost(self, usage: dict) -> float:
        return (usage.get("prompt_tokens", 0) * self.price.input_per_m
                + usage.get("completion_tokens", 0) * self.price.output_per_m) / 1e6

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict[str, Any]:
        self.ledger.check(self.provider)
        body: dict[str, Any] = {"model": self.model, "messages": messages,
                                "temperature": self.temperature, "max_tokens": self.max_tokens}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        last: Exception | None = None
        for attempt in range(4):
            try:
                r = httpx.post(f"{self._url}/chat/completions", json=body, timeout=self.timeout,
                               headers={"Authorization": f"Bearer {self._key}"})
                # 422 seen from Featherless under concurrency (transient; the same body passes
                # on retry), so it is retried like 429
                if r.status_code in (422, 429, 500, 502, 503, 504):
                    raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request,
                                                response=r)
                r.raise_for_status()
                break
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                last = e
                if (isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 429
                        and e.response.status_code != 422):
                    raise RuntimeError(f"{self.spec}: HTTP {e.response.status_code}: "
                                       f"{e.response.text[:1200]}") from None
                time.sleep(5 * (attempt + 1))
        else:
            raise RuntimeError(f"{self.spec}: request failed after retries: {last}")
        data = r.json()
        usage = data.get("usage") or {}
        cost = self.cost(usage)
        self.ledger.record(self.provider, self.model, usage, cost, self.run)
        for k in ("prompt_tokens", "completion_tokens"):
            self.usage[k] += usage.get(k, 0)
        self.usage["cost_eur"] += cost
        self.usage["calls"] += 1
        choice = data["choices"][0]
        return {**choice["message"], "_finish": choice.get("finish_reason")}
