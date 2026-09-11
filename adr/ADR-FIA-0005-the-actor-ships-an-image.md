---
id: ADR-FIA-0005
title: "The actor ships an image, and renders its own cards into it"
status: Proposed
date: 2026-09-11
supersedes: []
references:
  - ../docker/Dockerfile
  - ../src/foundry_implementation_actor/instance.py
  - ../src/foundry_implementation_actor/serve.py
  - ../examples/ACME.PARTS.CAP.SUP.007.WID-implementation/Dockerfile
---

# ADR-FIA-0005 — The actor ships an image, and renders its own cards into it

## Context

ADR-FIA-0001 moved the machinery out of the capability and into this package. It moved less than
it looked like. A use that installs the wheel still hand-writes three things this package
already knows the whole answer to:

- **its own copy of the four cards.** The definition ships at `cards_path()`, and
  `conformance.check` (0.2.1) compares a use's copy against it — which is a gate standing in for
  the thing that would remove the need for a gate. 0.4.0 proved the cost: one new door, and every
  use in the world is wrong until someone edits four files in each of them by hand.
- **an entrypoint.** Some sixty lines that configure observability, add a console handler beside
  the OTLP one, install the correlation filter, read `PORT`, build an `HttpMailbox`, call
  `Actor.from_card`, and emit an `actor-started` event. Every line of it is this actor's, not the
  capability's. Two uses that diverge here diverge in what an operator can see, which is the worst
  place to drift.
- **a Dockerfile.** Roughly ninety lines: a Python base, `git`, Node and the `claude` CLI,
  `buildctl` copied from a rootless buildkit image, the `papeete-actor` stack pinned version by
  version, a `WORKDIR`, an `EXPOSE`, a `CMD`. Exactly two lines of it belong to the capability:
  the knowledge tools its `ground_in:` argv names, and the sidecar it copies in.

So "instantiate this actor for a second capability" reads, in the README, as "write one sidecar",
and reads in practice as "write one sidecar, then reproduce a hundred and fifty lines you must
keep in step with a package you do not control." The cards drift into a runtime refusal, the
entrypoint drifts into missing telemetry, and the Dockerfile drifts into a `claude` CLI that is
two majors behind the engine driving it.

## Decision

This package ships a **runnable base image** beside the wheel, and grows the two commands that
make a use's image contain nothing but the capability.

1. **`foundry-implementation-actor render-cards <folder>`** writes the four cards into a folder,
   from the definition in the wheel. Three are copied byte-for-byte; `actor.yaml` is emitted with
   `name:` set to the `actor_name` this use's sidecar already derives, and a description naming
   the capability it serves. Every rendered file carries a banner saying it was rendered and from
   which version. A use stops carrying cards at all.

2. **`foundry-implementation-actor serve <folder>`** is the entrypoint, moved verbatim in
   behaviour from the hand-written `app.py` it replaces — including the console handler beside the
   OTLP one and why it exists. It needs a mailbox and an observability backend, which are wire
   concerns this package deliberately does not depend on, so they arrive through a `serve` extra
   rather than the base dependency set.

3. **`docker/Dockerfile`** builds `foundry-implementation-actor:<version>`: the OS-level tools the
   engine and the publisher shell out to, the wheel built in the same CI run installed with its
   `serve` extra, the cards rendered at `/actor`, a non-root `USER`, and
   `CMD ["foundry-implementation-actor", "serve", "/actor"]`.

A use's whole image becomes:

```dockerfile
FROM ghcr.io/papeete-hub/foundry-implementation-actor:0.5.0
RUN pip install --no-cache-dir kpack==2.0.1 kontract==0.1.0   # what this sidecar's ground_in names
COPY actor-agentic-context.yaml /actor/
RUN foundry-implementation-actor lint /actor
```

Four lines, one of which is a gate. The image the wheel is installed from is built in the same run
that publishes that wheel, at the same version — a tag push produces both or neither.

## Rationale

**The cards were always meant to be rendered.** `cards_path()`'s own docstring says a use is "today
a static folder carrying its own copy" and that the path "is what a spawned instance would be
rendered from once it is not." The spawner never arrived, and the image is the cheaper half of it:
the rendering happens at `docker build` rather than at instance-creation, which is early enough to
delete the hand copy and therefore the class of drift `conformance.check` was built to detect.

**Rendering beats checking.** `conformance.check` stays, and stays valuable — a use that pins an
older image, or one that still carries cards from before this change, is still worth refusing. But
a gate that catches drift is strictly worse than a construction that cannot drift, and the two are
not in tension: what cannot drift is never the thing the gate fails on.

**The line stays where ADR-FIA-0002 drew it.** The image carries what this actor itself runs:
`git`, because it clones; Node and `claude`, because the engine shells out to it; `buildctl`,
because the publisher drives it. It does NOT carry `kpack`, `kontract`, or any other knowledge
tool — a `ground_in` entry names its own argv, so those belong to whoever writes the sidecar, and
they stay a `pip install` line in the use's own Dockerfile. The portability gate greps `src/` for
exactly those names and keeps it honest.

**An extra, not a dependency.** `papeete-actor-synchronous-messaging-http` and
`papeete-observability` are how this actor is *carried*, and ADR-PAM-0001 keeps wire out of the
message contract. Putting them in `[project.dependencies]` would push an HTTP server onto every
consumer that only wants `CapabilityConfig` — so they go in a `serve` extra that the image
installs and an embedder does not.

**Rejected: a `cookiecutter`/`init` command that scaffolds the files into the use's repo.** It
produces the same hand copy this ADR is deleting, one generation later, and the copy is stale from
the moment the next version ships. The image is a dependency a use pins; scaffolded files are a
fork a use owns.

**Rejected: keeping `app.py` in the use and only shipping the Dockerfile.** The entrypoint is where
observability is wired, and the reason the console handler exists at all is a failure an operator
could not see. That reasoning should live once, in the package, not be re-derived per capability
from a comment someone copied.

## Consequences

- **Every use can delete four cards and `app.py`,** and cut its Dockerfile to a `FROM` and two
  lines. `BNK.RLVR.CAP.SUP.002.BEN-implementation` is the first, and the migration is a separate
  commit in that repo, not this one.
- **Two artifacts, one version.** The release workflow must publish the wheel to PyPI and the image
  to the registry from the same tag. A version that exists in one and not the other is the failure
  this creates, and CI asserts the image reports the same version the wheel does.
- **`conformance.check`'s warning path becomes the normal path.** A use folder with no cards
  already warns rather than errors, which is the right behaviour once a use is expected to have
  none — but the message still reads as though cards were expected. It is reworded, not
  re-purposed.
- **Rendered prose is thinner than hand-written prose.** A use's `means:` used to name its real peer
  actors ("BNK...-task-orchestration does, once BNK...-testing confirms"); the rendered one says
  "an orchestrating actor does, once a testing actor also confirms," because the sidecar does not
  declare peers. `conformance.check` already refuses to compare prose for this reason, so nothing
  breaks — but `describe` gets less specific for a reader. A `peers:` field in the sidecar would
  buy it back; it is not worth a contract bump on its own, and is left for the first use that
  actually misses it.
- **The base image is a supply-chain surface.** It carries Node, the `claude` CLI and `buildctl`
  for every use at once. That is the point — one place to patch rather than N — but it means this
  repo now owns a rebuild cadence it did not have, independent of whether the Python changed.
