// Cross-check: does agent-trust-kit's own verifyAttestation accept an attestation signed by
// Yovahti's Python port? Usage (kit checked out anywhere, never modified):
//   node scripts/check_trust_kit_compat.mjs <path-to-agent-trust-kit> <envelope.json> <jwks.json> <card-sha256>
import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";
import { resolve } from "node:path";

const [kitDir, envPath, jwksPath, cardHash] = process.argv.slice(2);
const kit = await import(pathToFileURL(resolve(kitDir, "src/attestation.js")).href);
const envelope = JSON.parse(await readFile(envPath, "utf8"));
const jwks = JSON.parse(await readFile(jwksPath, "utf8"));
const ok = await kit.verifyAttestation(envelope, {
  issuer: "https://github.com", jwks, expect: { network_sha256: cardHash, minScore: 50, minCoverage: 80 },
});
const forged = structuredClone(envelope);
forged.payload = Buffer.from(Buffer.from(envelope.payload, "base64").toString().replace('"score":95', '"score":99')).toString("base64");
const bad = await kit.verifyAttestation(forged, { issuer: "https://github.com", jwks });
console.log(JSON.stringify({ genuine: { ok: ok.ok, reason: ok.reason, score: ok.statement?.score, model: ok.statement?.model, sub: ok.statement?.sub }, forged: { ok: bad.ok, reason: bad.reason } }));
process.exit(ok.ok && !bad.ok ? 0 : 1);
