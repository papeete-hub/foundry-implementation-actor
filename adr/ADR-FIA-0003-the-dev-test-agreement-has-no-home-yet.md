---
id: ADR-FIA-0003
title: "The dev↔test agreement has no home yet — and it is not this actor's to emit"
status: Superseded
superseded_by: ADR-FIA-0004
date: 2026-09-10
supersedes: []
references:
  - adr/ADR-FIA-0004-the-three-amigos-round.md
  - adr/ADR-FIA-0002-testing-leaves-this-actors-contract.md
  - src/foundry_implementation_actor/schemas/agentic-context.schema.yaml
---

# ADR-FIA-0003 — The dev↔test agreement has no home yet

> **Superseded by [ADR-FIA-0004](./ADR-FIA-0004-the-three-amigos-round.md), which answers it.**
> Kept because the gap it names is the reason that decision exists, and because its own
> "Decision" section overshot on one point: it rejected an implementation-emitted manifest *"in
> any form"*, where the distinction that actually matters is **before or after**. A value named
> before anything is built, in answer to a proposal, is a promise; the same value named afterwards
> is a report. 0004 states it properly.
>
> Read below for the gap, the evidence, and the frontend case it correctly identified as the one
> with no upstream author. Read 0004 for what was decided.

## Context

Removing testing from this actor's contract raises the obvious next question: if a capability no
longer tells the implementation actor anything about testing, **what binds the implementation
actor and the e2e testing actor to the same understanding of the increment?**

In human practice that is the *three amigos* — product owner, developer and tester agreeing, before
the work starts, on what will be built and how it will be addressable, so that the tester can write
tests against something other than the developer's own account of what they did.

The investigation turned up three findings.

**1. The artefact largely exists, and it is not in either actor.** Both actors ground themselves in
the capability's own process/contract knowledge — aggregates, commands, policies, read-models, bus,
api, message schemas — fetched fresh for every session. The e2e testing actor's own prompt calls it
*its primary source of truth for exact black-box shapes*. That **is** the three-amigos output: a
specification authored upstream, in the design tier, binding both sides, written by neither. The
seam it arrives through is `ground_in`, which is an open list (ADR-FIA-0001 Decision 6).

**2. The gap is the *deployed addressable* surface, not the domain surface.** The contract model
says what the capability does; it does not say how a black-box caller reaches the thing that was
built. Exactly one dev↔test addressing convention exists today — *"read the target component's base
URL from an environment variable named `<COMPONENT>_URL`"* — and it lives **hardcoded in the testing
actor's private prompt**. The implementation actor has never heard of it. It is correct today and
silently wrong the first time a component is not an HTTP service.

**3. Component kinds need different things, and the gap is widest where nothing exists yet.**

| kind | judged on | where the shapes come from |
|---|---|---|
| stub | fixture fidelity and protocol shape | the contract it impersonates |
| backend | domain behaviour — invariants, published events, idempotency, error codes | the capability's own contract model |
| frontend | flows against selectors / test ids | **nowhere — no upstream author** |

A frontend's test ids are the one case with no other home: they are a pure dev↔test agreement that
no domain model can author. That case does not exist yet in any current use, which is precisely why
designing for it now would be designing for a guess.

## Decision

**Proposed, not accepted. Nothing is built in this package today.** What this ADR fixes is the
*shape* of any future answer:

**1. The agreement must PRECEDE implementation, and must not be emitted by it.** The e2e testing
actor is deliberately blind to the implementation's source — it is told it has not been given it.
If the implementer produced the list of ids and handles, the tester would test **what was built
rather than what was agreed**, and a test could no longer fail for *"you built the wrong thing."* A
manifest produced by the developer afterwards is a report, not an agreement.

This is also why the conclusion is consistent with ADR-FIA-0002 rather than in tension with it:
nothing test-shaped leaves this actor, and the artefact the tester needs is not this actor's to
emit.

**2. It belongs in a source BOTH actors ground themselves in** — the design tier, beside the
contract model, or a small contract owned by neither actor. Not in either actor's prompt, and not
in either actor's own sidecar.

**3. It needs no code here when it arrives.** `ground_in` already carries an arbitrary fetch into
the session before turn one. A new shared source is a YAML entry in each use, not a release of this
package.

## Rationale

**Why not simply add `components[].kind` here.** It is tempting: this actor already enumerates
components, and a `kind:` would let the tester shape its strategy. But **this actor would not act
on it** — it would be parsed, carried, and handed to somebody else. That is precisely what `tests:`
did, and adding it in the release that removes `tests:` would be repeating the mistake in a new
costume, in the same breath as writing down the rule against it (ADR-FIA-0002: *the sidecar declares
only what this actor itself reads and acts on*).

**Why the `<COMPONENT>_URL` convention is the concrete evidence, not an anecdote.** It is a real,
load-bearing agreement between two actors that is written down exactly once, inside one of the two
parties, in a place the other cannot see. That is the failure mode this ADR exists to name, and it
is small enough today to be fixed cheaply and invisible enough to be missed indefinitely.

**Why "Proposed" and not "Accepted".** The strongest case for the artefact is the frontend one, and
there is no frontend component yet. Designing the contract from the two kinds that *are* in use
would produce a shape fitted to HTTP services, which is the shape already causing the problem.

## Consequences

- **Nothing changes in this package.** No schema field, no code, no card.
- **A known gap is now written down** rather than living in one actor's prompt. The next use that
  adds a non-HTTP component will hit it, and this ADR is what it should be read against.
- **Where the work would land, when it lands:** the design tier that already authors the contract
  model, plus one `ground_in` entry per use. Neither is in this repo.
- **What would signal it is time:** a component that is not reachable over HTTP, or a frontend
  component. Either makes the single hardcoded addressing convention wrong rather than merely
  narrow.
- **Explicitly rejected, should it be proposed again:** an implementation-emitted manifest of ids
  and handles, in any form — a completion field, a committed file, or an image label. It would
  dissolve the property the whole implement→test seam is built on.
