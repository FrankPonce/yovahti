"""Publish NetCrash attestations to Rekor and check each entry (D21, I34).

Run: uv run python scripts/publish_rekor.py [--production] [files ...]
Without files: every envelope in results/netcrash/attestations/. Staging unless --production.
Writes results/netcrash/rekor/<name>.json (entry, checks) and rekor/index.md.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

import httpx

from yovahti.paths import RESULTS, ROOT
from yovahti.trust import rekor
from yovahti.trust.signing import public_part


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", type=Path)
    ap.add_argument("--production", action="store_true")
    a = ap.parse_args()
    url = rekor.PRODUCTION if a.production else rekor.STAGING
    jwk = public_part(json.loads((ROOT / "trust/keys/tester.private.jwk.json").read_text()))
    files = ([f.resolve() for f in a.files]
             or sorted((RESULTS / "netcrash/attestations").glob("*.dsse.json")))
    out = RESULTS / "netcrash" / ("rekor" if a.production else "rekor-staging")
    out.mkdir(parents=True, exist_ok=True)
    c = httpx.Client(timeout=30)
    log_pem = rekor.log_key(url, c)
    rows, bad = [], 0
    for f in files:
        env = json.loads(f.read_text())
        e = rekor.upload(env, jwk, url, c)
        res = rekor.check(e, log_pem)
        body = json.loads(base64.b64decode(e["body"]))
        same = body["spec"]["payloadHash"]["value"] == rekor.envelope_hash(env)
        ok = res["ok"] and same
        bad += not ok
        name = f.name.removesuffix(".dsse.json")
        (out / f"{name}.json").write_text(json.dumps(
            {"attestation": f.relative_to(ROOT).as_posix(), "check": res,
             "payload_hash_matches": same, "entry": e}, indent=1))
        print(name, e["logIndex"], res["reason"], "payload ok" if same else "PAYLOAD MISMATCH")
    # the index lists every entry logged so far, not only this call's files
    for f in sorted(out.glob("2026-*.json")):
        r = json.loads(f.read_text())
        e, ok = r["entry"], r["check"]["ok"] and r["payload_hash_matches"]
        rows.append(f"| {f.stem} | {e['logIndex']} | `{e['uuid'][-16:]}` | "
                    f"{'ok' if ok else 'FAILED'} |")
    (out / "index.md").write_text(
        f"# NetCrash attestations in Rekor ({url})\n\nLook up an entry: "
        f"`{url}/api/v1/log/entries?logIndex=<index>` or search.sigstore.dev.\n\n"
        "| attestation | log index | uuid (tail) | inclusion + SET |\n|---|---|---|---|\n"
        + "\n".join(rows) + "\n")
    (out / "log-public-key.pem").write_bytes(log_pem)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
