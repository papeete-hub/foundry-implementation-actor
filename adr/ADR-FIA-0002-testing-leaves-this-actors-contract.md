---
id: ADR-FIA-0002
title: "Testing leaves this actor's contract — a component declares what is built, not how it is verified"
status: Accepted
date: 2026-09-10
supersedes: []
references:
  - src/foundry_implementation_actor/schemas/agentic-context.schema.yaml
  - src/foundry_implementation_actor/config.py
  - src/foundry_implementation_actor/engine.py
---

# ADR-FIA-0002 — Testing leaves this actor's contract

## Context

`components[].tests` has been a **required** field of
`foundry-implementation-actor/agentic-context/v1` since this package's first commit. It was not
chosen here: it was inherited verbatim from the capability repository this machinery was extracted
from (ADR-FIA-0001), where implementation and testing lived side by side in one repo and the
distinction did not exist yet.

It was consumed in exactly one place. `_situational_prompt` interpolated `config.test_paths` into
one sentence — *"Iterate the test suite(s) of whichever component(s) you touch (…) until green
before you finish."* No test was ever executed by this package. No commit, push, or publish was
gated on one. Nothing downstream read it: the e2e testing actor keeps its own accumulated suite in
its **own repository**, so `backend/tests/` in this sidecar and `backend/tests/` in that actor's
write boundary are two unrelated trees that merely spell the same string.

Two things were wrong with it, and they are different in kind:

1. **It is the wrong kind of fact for that list.** `components[]` declares what gets **built and
   shipped**: `path` is the write boundary the handler enforces, `dockerfile` is the context
   `buildctl` is pointed at. Both are inputs to producing an artifact. A test suite is neither.
2. **It made a capability declare testing to an actor that does not test.** End-to-end,
   performance and security testing belong to other actors. A capability that has to name a test
   tree in *this* sidecar is being asked about somebody else's contract.

## Decision

**1. `components[].tests` is removed.** From the schema's `items.required` and its field doc, from
`Component`, from `CapabilityConfig.test_paths`, from `_component`'s parse, and from `show`'s
output.

**2. The prompt clause is deleted, and nothing replaces it** — not in the situational prompt, and
not in the generated `CLAUDE.md`. This actor does a **dev / lead-dev's work**: it may write and run
unit tests inside its session as any developer would, following the conventions of the repository
it is working in. A developer is not told where to put a unit test, and this one has the repo in
front of it.

**3. The contract stays `agentic-context/v1`.** This is a loosening, not a new contract.

**4. What `components[]` means is now stated positively:** the units this actor may write to and
publish — what gets built and shipped, and nothing else.

## Rationale

**The rule worth being able to cite later: the sidecar declares only what this actor itself reads
and acts on.** `tests:` failed that from the first commit — it was read solely to be pasted into an
f-string. A field that only travels through this package on its way to a prompt is documentation
wearing a contract's clothes, and it accumulates exactly the drift ADR-FIA-0001 removed for
`writes_only_under`: two parties believing a declaration is load-bearing when one of them never
looks at it.

**Why no replacement sentence.** Restating "run your tests" to a session that has the component's
existing suite in its clone is supervision, not instruction. The situational prompt is *"the task,
and nothing else"* by this repo's own design, and standing facts were deliberately moved out of it
into the generated `CLAUDE.md`. A capability with something specific to say about its own test
conventions has a natural home for it already: its own committed `CLAUDE.md`, which grounding
**appends** to rather than overwrites.

**Why v1 is loosened rather than superseded.** Verified in code: nothing rejects unknown keys —
`from_dict` checks the top-level `required:` list and `_component` checks its own key tuple, and
neither has a strict mode. So every sidecar written against the earlier v1, including every live
consuming repo, keeps loading and keeps linting green with `tests:` still in it; the key is simply
ignored. **Relaxing a required field is backward-compatible — it is *adding* one that breaks.**

A v2 bump would have been actively worse than cosmetic. `lint` treats a sidecar declaring another
`context:` as *UNMIGRATED, not checked* and returns without validating it at all. Bumping would
therefore stop checking every use that had not yet edited one line — trading a live gate for
purity, and punishing exactly the sidecars that were still perfectly valid.
`test_a_sidecar_still_declaring_tests_is_conformant` pins this, so a strict-mode check added later
cannot break every consuming repo at once and silently.

## Consequences

- **No use has to be edited.** The live consuming sidecars still declare `tests:` and remain
  conformant. They may drop it whenever convenient; nothing forces the edit and nothing warns.
- **Released as `0.3.0`.** A contract field is gone: a minor, not a patch.
- **`conformance.check` is untouched.** It compares the four cards' derived wire contract and never
  opens the sidecar. Nothing test-shaped appears in any declared or outbound position of the
  cards — `implement-task` still completes with `{accepted, branch, images}`.
- **`remediation_context` stays as it is.** It carries the prior attempt's failing test criteria,
  but it is inbound-only orchestration feedback: neither something a capability declares nor
  something this actor emits.
- **The image build context is unaffected and remains the capability's own decision.** `handler.py`
  points `buildctl` at the component root; whether a `tests/` directory reaches the image is
  settled by that component's Dockerfile and `.dockerignore`, where it belongs.
- **Follow-up, deliberately not folded in here:** the schema's `components[].items.required` is not
  read by any code — `_component` carries its own hardcoded key tuple. That is the same fact stated
  twice, the shape this repo already killed once for `writes_only_under`. It has not drifted yet;
  removing `tests` had to touch both copies, which is how it was noticed. Unifying them is its own
  change, not a rider on a subtractive one.
- **Not decided here:** where the dev↔test agreement lives. See ADR-FIA-0003.
