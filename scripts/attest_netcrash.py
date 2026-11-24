"""Sign NetCrash scorecards as in-toto Test Result attestations (DSSE, Ed25519).

Run: uv run python scripts/attest_netcrash.py [--date YYYY-MM-DD]
The tester key lives in trust/keys/tester.private.jwk.json (git-ignored, created on first
run); its public JWKS is trust/tester.jwks.json (committed), which is what admit() trusts.
Writes results/netcrash/attestations/<scorecard>.dsse.json. Only scorecards with coverage
>= 80 % are attested (crash-test rule). Nothing is published to a transparency log here.
"""

from __future__ import annotations

import argparse
import json

from yovahti.netcrash.runner import MIN_COVERAGE, timestamp
from yovahti.paths import RESULTS, ROOT
from yovahti.trust.attestation import attest, read_attestation
from yovahti.trust.signing import new_key, public_part

KEY = ROOT / "trust" / "keys" / "tester.private.jwk.json"
JWKS = ROOT / "trust" / "tester.jwks.json"
ISSUER = "https://github.com/FrankPonce/yovahti"


def tester_key() -> dict:
    if not KEY.exists():
        KEY.parent.mkdir(parents=True, exist_ok=True)
        KEY.write_text(json.dumps(new_key()), encoding="utf-8")
    key = json.loads(KEY.read_text(encoding="utf-8"))
    JWKS.write_text(json.dumps({"keys": [public_part(key)]}, indent=1) + "\n", encoding="utf-8")
    return key


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=timestamp())
    a = ap.parse_args()
    key = tester_key()
    jwks = json.loads(JWKS.read_text(encoding="utf-8"))
    out = RESULTS / "netcrash" / "attestations"
    out.mkdir(parents=True, exist_ok=True)
    for p in sorted((RESULTS / "netcrash").glob(f"{a.date}-*-*.json")):
        card = json.loads(p.read_text(encoding="utf-8"))
        s = card["summary"]
        if s["coverage"] < MIN_COVERAGE:
            print(f"skip {p.name}: coverage {s['coverage']} % < {MIN_COVERAGE} %")
            continue
        env = attest(card, key, ISSUER)
        assert read_attestation(env, jwks)["ok"]
        (out / f"{p.stem}.dsse.json").write_text(json.dumps(env, indent=1) + "\n",
                                                encoding="utf-8")
        print(f"attested {p.stem}: score {s['score']}, coverage {s['coverage']} %")


if __name__ == "__main__":
    main()
