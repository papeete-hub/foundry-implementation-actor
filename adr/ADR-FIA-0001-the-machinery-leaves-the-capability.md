---
id: ADR-FIA-0001
title: "The machinery leaves the capability — a published actor any capability can instantiate"
status: Accepted
date: 2026-09-07
supersedes: []
references:
  - src/foundry_implementation_actor/config.py
  - src/foundry_implementation_actor/grounding.py
  - src/foundry_implementation_actor/schemas/agentic-context.schema.yaml
  - https://github.com/papeete-foundry/ecosystem-governance/blob/main/ecosystem/decisions/ADR-ECO-0022-artifact-kind-suffixes.md
---

# ADR-FIA-0001 — The machinery leaves the capability

## Context

One capability's implementation repository held two unrelated things: **891 lines of generic
machinery** for running a headless Claude Code session against a capability's own repo, and the
source of the business capability itself. Nothing about the machinery was capability-specific
except the literals it had been written with.

Both files that moved said so themselves. The engine's docstring:

> Extracting this into its own `papeete-hub` package later (once this pattern is proven, the way
> `papeete-version` was pulled out of `papeete-actor`'s own `build.py`) should be a near-mechanical
> move.

and the sidecar's header said it was kept structural *"specifically so extracting this into a real
published package later (once proven) is a move, not a rewrite."*

The pattern is proven — it has run tasks end to end — and the intuition held: this is a move.

Two things were wrong enough to fix in the same act rather than port faithfully:

1. **One capability id, eight hand-written renderings.** The dotted id, the `<owner>/<repo>`, the
   registry path with `CAP` dropped, the image name, the tempdir prefix, the git `user.name`, the
   git `user.email`, and the full image ref — eight literals for one fact, across two modules, two
   of which had already been copied rather than shared.
2. **The write boundary stated twice.** The sidecar declared `writes_only_under`, and the module
   that actually *enforces* containment carried its own hardcoded copy. Only one of the two was
   load-bearing, and a spec document described them as one thing. A boundary that can be stated
   twice will eventually be stated differently.

And one thing was not broken, but was weaker than it looked: **grounding was advisory**. The
capability's business and process context was fetched into a tempdir **beside** the clone, and the
session was asked in prose to "read it before you start". Whether it entered the model's window was
the model's choice, re-made every session, and a session that skipped it looked exactly like one
that had read it.

## Decision

**1. A standalone, PyPI-published package: `foundry-implementation-actor`.** An actor, for one use,
with a `papeete-actor` underneath — the `-actor` suffix is that claim (`ADR-ECO-0022`). Runtime
dependencies are `papeete-actor-synchronous-messaging` (for the `Engine` port and `EngineError`),
`papeete-version`, and `pyyaml`. Nothing else.

**2. `CapabilityConfig` is the single source of every identifier.** Two declared fields —
`capability` and `source_repo` — and every one of the eight renderings is derived from them. The
image ref in particular is derivation output or nothing: peer actors recompute the identical string
and parse it back apart, so it stays byte-identical and no tag scheme is invented here.

**3. The write boundary is `components[].path`, and only that.** `writes_only_under` as a declared
field is gone. Which component a staged path belongs to is resolved by longest declared prefix, not
by taking the path's first segment — a shortcut that is correct only while every component root is
one segment deep, and reports the wrong component the day one is `src/gateway/`.

**4. Grounding is a precondition.** Envelopes are written **inside the clone** and named from a
generated `CLAUDE.md` at its root, which the `claude` CLI loads before the first turn and whose
`@relative/path.md` imports it resolves eagerly. Verified live in this actor's exact invocation
shape: a question only the fetched context could answer came back in `num_turns: 1` with zero tool
calls. The prose paragraph asking the session to go and read its context is deleted — it is done,
not requested.

**5. Two load tiers, `eager` and `on-demand`, chosen by measurement.** `eager` costs its full token
weight on every session unconditionally; `on-demand` costs one line and the session pays the rest
only if it opens the file. Neither is right in general.

**6. The package knows no knowledge tool.** Each `ground_in` entry supplies its own `fetch:` argv,
so the machinery knows only *"run this, ground the session in the output"*. The tools a capability
grounds itself in are the **consumer's** dependencies, declared where the sidecar that names them
lives. A fourth knowledge source is a YAML entry, not a release of this package.

**7. The sidecar gets an owner and a schema.** `foundry-implementation-actor/agentic-context/v1`,
shipped as committed source inside the package and checked by
`foundry-implementation-actor lint`. It was previously the one file in the org following the
`actor-<concern>.yaml` / `<package>/<thing>/vN` idiom with no owning package and no schema.

**8. No lab reference survives.** The repo is public. `tests/test_portability.py` greps `src/` for
the instance's identifiers and for any knowledge tool name, and fails the build on either. The
fixture capability in the test suite is fictional for the same reason — a test suite is source too.

## Rationale

**Why not generic across actor kinds.** There are no hooks, no base classes, and no strategy
objects here. Generic across *capabilities* is a claim this package can honour today, and the
sidecar is what discharges it. Generic across actor *kinds* would be designing for a second
consumer that does not exist, and the shape it would take cannot be known from one example. One
shape, done properly, beats an extension point aimed at a guess.

**Why `correlation.py` moved verbatim.** Its `_emit`/`event`/`stage` bodies are the observability
contract — a dashboard reads `event="step"` with `phase` start/ok/failed, `duration_ms` on the ok
record, and `correlation_id`/`task_id` as structured metadata. The *step names* are free (checked:
no dashboard query pins one this actor emits), which is what let the grounding stages be renamed in
the same move. The record schema is not, so the file's code below the docstring is byte-identical
to what it replaced.

**Why a factory rather than a module-level handler.** `make_implement_task(config)` binds the
config, instead of the handler reaching for `actor.engines["claude-code"]`. The engine's registered
name comes from the sidecar; looking the config up through a hardcoded engine key would reintroduce
exactly the literal this package exists to remove.

**Why the `CLAUDE.md` appends.** The consuming repo has no `CLAUDE.md` today — which is precisely
why the clean-slate case is the one to get right now. The day it commits one, that file is its own
standing guidance for anyone working in it, and silently replacing it with a generated block would
remove the very thing a session most needs to obey.

**Why `str.format` is not used on a `fetch:` argv.** A fetch argv is somebody else's command line,
and braces are ordinary characters in one — a jq filter or a JSON literal would raise or be
mangled. Only the three known placeholders are substituted, literally. A leftover bare `{word}` is
still refused, because that is what a typo looks like.

## Consequences

- **The consuming repo loses three modules and gains a pin.** `engine.py`, `handler.py` and
  `correlation.py` are deleted; the entrypoint imports from this package; the `Dockerfile` pins
  `foundry-implementation-actor==0.1.0` beside the knowledge tools its own sidecar names.
- **The sidecar becomes load-bearing.** `ground_in:` was a flat list of two strings whose own
  comment admitted nothing read it. It is now what the engine actually runs, and `components:` is
  what the handler actually enforces.
- **Two contracts that were unstated become checkable.** A component's `dockerfile:` must exist in
  the clone — previously a late `buildctl` failure naming a temp path, *after* a commit and a push
  had already landed — and its `path` must end in `/`, because containment is a prefix test.
- **A version pin now sits between two repos that used to be one.** The ordering constraint is
  real: this package must tag and publish `0.1.0` before the consuming repo's cutover commit can
  build. That seam is also where a two-act extraction would go if preferred later — `ADR-PV-0001`'s
  *"Extraction now, cutover later, as two separate acts"*.
- **The first tests this machinery has ever had.** 891 lines had none. The suite pins the eight
  renderings, containment refusal against a real git repo, the two load tiers, append-not-clobber,
  and the portability gate — including a test that the gate itself can still fail.
- **Not decided here:** caching (envelopes are fetched fresh every session, and
  `ADR-DSN-0002` Decision 4 currently mandates that); whether a `ground_in` entry should be able to
  name a literal file rather than a `fetch:` argv, which is what carrying a skill's knowledge into
  the session would need; and whether `papeete-context` should eventually replace `correlation.py`,
  which is far from a 1:1 swap and belongs to its own cutover.
