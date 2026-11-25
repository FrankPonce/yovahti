# Lessons for agent-trust-kit and trust-before-transaction

What building Yövahti's trust layer (a Python port of agent-trust-kit, D34) taught, written as
changes to carry back into the kit. Each item names the finding it comes from
([FINDINGS.md](FINDINGS.md), [DECISIONS.md](DECISIONS.md)).

## 1. Attest the interface, not just the model

The same model scored 83 with free-form tools, 85 when it could only keep cells awake, and 100
when it only filled an event schema (E38). Trust is a property of **agent × model × interface**.

- The attestation subject should cover the tool surface (Yövahti's Agent Card already hashes
  `allowed_tools` into the subject; the kit should require it).
- Add to the Test Result predicate: `interface` (free-form / constrained / workflow) and
  **`modelDecidedTests`**, the number of tests whose outcome still depended on the model. A
  verifier should be able to tell "100 over 20 model decisions" from "100 over 2" (G37).
- Admission policies should be able to require a minimum `modelDecidedTests`, or set a
  different bar per interface.

## 2. Record why a test did not count

Yövahti now separates `not_applicable` reasons: "agent never touched the feed", "prevented by
the interface", "decided by code" (D45, D46). Coverage alone hides the difference between a
test the agent skipped and one it could not fail. Carry a `basis` per run (action, text,
interface, format, provider) into the scorecard.

## 3. Pin the harness, not only the suite

Suite version is not enough: two runs of suite v2 differed because the harness changed how an
empty answer was scored (G35). Put a harness hash (or commit) and the judge prompt hash into
the predicate; refuse to compare or aggregate scorecards across harness versions (D35).

## 4. Score actions before text

An empty final report was scored `error` before the agent's actions were checked, hiding real
failures (G35). Verdict order in the kit's runner: action-based verdict first; a fail on
actions stands even without a report; only then fall back to format errors.

## 5. Strip inline reasoning before text checks

Some providers return reasoning inline, ending in `</think>` (G35). Text verdicts must read
only what follows; otherwise they grade the chain of thought, not the report.

## 6. Prompts are not controls

Every model ignored an explicit "never split to avoid approval" (G36). The kit's guidance and
any "policy in the system prompt" feature should say so plainly, and point users to interface
restrictions and gate-side rules.

## 7. Thresholds must count across actions

Per-action approval tiers were bypassed by splitting (G31). Any tier or budget the kit checks
should be cumulative over a window per agent identity, not per call.

## 8. Bind identity per request

Card hash + model + key, bound by the operator and proven on every request with RFC 9421
signatures (D39), closes the gap between "this agent was tested" and "this request comes from
that agent". Worth porting from `yovahti.trust.httpsig` / `identity` into the kit, with
tool calls outside the bound card refused at the door (E35).

## 9. Prefer trails to explanations

Free-text "explain yourself" output is a leak and confabulation channel (E40). Where the kit
produces or consumes agent reports, prefer structured reports with explicit `unknowns` and
source pointers by id over quoted text.

## 10. Public logs are cheap; do them by default

Rekor `dsse` entries with inclusion proof and signed entry timestamp verified offline (E34)
cost nothing and make a scorecard checkable without trusting the publisher. The kit could log
by default, staging for development and production for final cards (D44).
