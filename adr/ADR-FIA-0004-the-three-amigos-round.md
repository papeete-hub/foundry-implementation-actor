---
id: ADR-FIA-0004
title: "The three amigos round — the tester proposes, this actor answers, a human breaks the tie"
status: Accepted
date: 2026-09-10
supersedes: [ADR-FIA-0003]
references:
  - src/foundry_implementation_actor/cards/actor-synchronous-messaging.yaml
  - src/foundry_implementation_actor/engine.py
  - adr/ADR-FIA-0002-testing-leaves-this-actors-contract.md
---

# ADR-FIA-0004 — The three amigos round

## Context

`ADR-FIA-0002` took testing out of what a capability declares to this actor. `ADR-FIA-0003` then
named what that leaves open: if a capability tells the implementation actor nothing about testing,
**what binds the implementation actor and the e2e testing actor to the same understanding of one
increment?** It proposed no answer, only the shape one would have to take.

In human practice that is the *three amigos* — product owner, developer and tester agreeing,
before the work starts, on what will be built and how it will be addressable, so the tester writes
tests against something other than the developer's own account of what they did.

**Today nothing happens before implementation starts.** The orchestrating actor takes a task,
calls `implement-task`, then the testing actor's `test-task`, deploys, runs the tests, and retries
up to three times with the failing criteria as a `remediation_context`. There is no step where the
tester says what it will need, and none where the implementer says whether that is possible.

### The evidence

One capability's e2e test tree hardcodes three fixture UUIDs and a base-URL environment variable,
with a comment stating the ids were *"discovered black-box against the running container."* The
task card had asked only for *"3 fixtures pre-seeded, retrievable by stable UUIDv7 IDs — one per
status."* It never named them. The implementation chose them; the tester reverse-engineered them
from the built artifact.

That is a dev↔test agreement that was never agreed. Regenerate those fixtures with different ids
and the e2e suite breaks with neither side at fault, because neither side was ever bound to
anything. It is not a hypothetical failure mode; it is the current state.

## Decision

**1. A bounded negotiation, once, before implementation.** The orchestrating actor asks the testing
actor what it intends to assert; then asks this actor whether that can be delivered; then either
proceeds or stops.

```
orchestration ──▶ testing:        propose the acceptance surface for this task
              ◀──                 expectations[] + open questions
orchestration ──▶ implementation: assess-task — can you deliver this?
              ◀──                 feasible + objections[] + commitments[]

  agreed     → the surface goes to implement-task AND test-task, on every attempt
  disagreed  → orchestration refuses to its own caller, carrying the objections
```

**2. Exactly one round, then a human.** No counter-proposal, no negotiation loop. A three-amigos
meeting converges because a human is in the room; here the human *is* the tie-breaker, and any
disagreement — including *"the task does not determine this"* — goes back as an answer for a person
to resolve by amending the task.

**3. This actor's half is `assess-task`, a QUERY.** An action is a promise to try; a query is *"a
promise to answer, from this actor's own state and nothing invented."* Assessing changes nothing —
no branch, no commit, no image — and placing it under `queries:` makes that structural rather than
promised. It clones read-only, grounds itself exactly as the implement door does, and is invoked
with `Read,Glob,Grep` and no `Write`, `Edit` or `Bash`. **A door that cannot write beats a door
asked not to** — the same discipline as `handler.py`'s containment check standing behind the
implement door's write boundary.

*Amended in 0.5.1, after the first live run.* Up to 0.5.0 that list was passed only as
`--allowedTools`, which PRE-APPROVES the tools it names and removes nothing: a live assess session
ran Bash three times. The door was asked not to write after all. It is now also passed as
`--tools`, which is what takes every other built-in out of the session, and a test pins both flags.
The same run showed commitments coming back as prose strings ("E1: …", "E4/E5: …") that nothing
could attach to an expectation, so the prompt now requires one `{id, commitment}` object per entry.

**4. `acceptance_surface` is an OPTIONAL payload field on `implement-task`.** The door works
exactly as before without it. The DoD is what the caller asked for; the surface is what dev and
test agreed it means, and where the surface is more specific, it wins.

**5. Escalation needs no new plumbing, deliberately.** Orchestration refuses to its own caller with
the objections. The framework is synchronous by decision (`ADR-PAS-0007`: *"correlation is business
data, not framework plumbing"*), and the orchestrating door is a blocking call — parking it on a
human would be wrong. The human is already at the other end of the thread that started the task.

## Rationale

**Why this supersedes ADR-FIA-0003 rather than contradicting it.** 0003 rejected *"an
implementation-emitted manifest of ids and handles, in any form."* It was reaching for a real
property and overshot the wording. The distinction that actually matters is **before or after**:

- a value named **after** building is a **report**, and a tester deriving assertions from it can
  only ever confirm the build;
- a value named **before**, in answer to a proposal, is a **promise** — nothing exists yet to
  describe.

The property to protect is that *the tester's assertions are never derived from the built
artifact*. One round before implementation preserves it exactly, because the tester proposes first,
from the task and the capability's own standing context, and this actor may only accept, object, or
commit. 0003 was only ever *Proposed*, so superseding it is cheap and honest.

**Why one engine, two doors, and no framework change.** `Actor.judge()` builds its prompt as
`f"verb: {verb}\ndoor: {offer.id}\n{json}"`. The engine already parsed and discarded those two
lines; it now dispatches on the door id it was being handed all along.

**Why the query registers no handler.** `Actor.receive()` does `elif judged is not None: result =
judged` — with an engine and no handler, the engine's dict is the reply. There is no deterministic
half here because there is nothing to contain, and `handler.py` is untouched.

**Why the answer's shape is rendered from the card.** `Actor.judge()` already derives it from the
door's own `completion_schema` and passes it as `schema=`, which this engine previously ignored.
Rendering that into the prompt is how the prompt and the card cannot come to disagree — the same
habit as every other derived string in this package.

**Why the sidecar is untouched.** Nothing here is a capability declaration. Per `ADR-FIA-0002`, the
sidecar declares only what this actor reads and acts on; how long a door may think is operational
tuning, and it is a constructor keyword.

## Consequences

- **Every use must update its cards.** Adding a door to the definition makes each hand copy fail
  `conformance.check` until it gains the same door, messages and data items. That gate is the only
  thing that says so before a caller is refused at runtime, and two tests now pin it. Released as
  `0.4.0`.
- **One extra grounded session per task, on each of two actors.** Grounding is fetched fresh every
  session and eager envelopes cost their full token weight. The assess session is bounded well
  below the implement one — fewer turns, a shorter timeout, three read-only tools — but it is not
  free, and the round buys a feasibility gate and a human escalation with that money.
- **Expectation ids are worth more than this round.** Because each carries a stable `id`, a failing
  verdict can name agreed expectations instead of scraped pytest lines, and `remediation_context`
  can stop being free prose. Neither is done here.
- **The other two halves are specified here and built elsewhere.** The testing actor's
  `propose-acceptance` is `foundry-testing-actor` (ADR-FTA-0002), and the orchestrating actor's
  round 0 is `foundry-task-orchestration-actor` (ADR-FTOA-0002), both extracted from their
  instance repos the way ADR-FIA-0005 extracted this one. The round runs after that actor unpacks
  its payload and before its attempt loop begins.
- **Not decided here:** whether the agreed surface should also be committed somewhere durable
  rather than only passed between doors, and whether `definition_of_done` should eventually be
  absorbed into it rather than sitting beside it.
