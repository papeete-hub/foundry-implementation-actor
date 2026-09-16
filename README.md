# foundry-implementation-actor

Runs a headless [Claude Code](https://claude.com/claude-code) implementation session against one
capability's own repository, then commits, pushes and publishes what it produced — inside a write
boundary the actor enforces rather than requests.

An **actor, for one use**, with a [`papeete-actor`](https://github.com/papeete-hub/papeete-actor)
underneath. The `-actor` suffix is that claim; `papeete-actor-*` names, by contrast, are transverse
features *of* the framework (`ADR-ECO-0022`).

```bash
pip install foundry-implementation-actor
```

> **New here?** [`examples/`](examples/) walks through a complete, working use of this actor —
> what the workflow is, what it is for, and how to instantiate one for your own capability. Every
> command in it runs with no credentials and no network.

## What it is

The actor's **definition** — its four cards, and the machinery behind them. It carries **no
capability of its own**: the capability it serves arrives in a sidecar the consuming repo writes:

```yaml
# actor-agentic-context.yaml
context: foundry-implementation-actor/agentic-context/v1
engine: claude-code
capability: ACME.PARTS.CAP.SUP.007.WID
source_repo: acme-lab/ACME.PARTS.CAP.SUP.007.WID-implementation
registry_repo: acme-lab/acme-governance
components:
  - {name: backend, path: backend/, dockerfile: backend/deployment/local}
  - {name: stub,    path: stub/,    dockerfile: stub/deployment/local}
ground_in:
  - name: business
    answers: the WHAT/WHY — domain vision, business events, ubiquitous language
    fetch: [kpack, pack, "{capability}", --deep, --compact, --registry-repo, "{registry_repo}"]
    into: .foundry/business.md
    load: eager
  - name: process
    answers: the HOW — aggregates, commands, policies, read-models, bus, api, JSON schemas
    fetch: [kontract, fetch, "{capability}", --compact, --registry-repo, "{registry_repo}"]
    into: .foundry/process.md
    load: on-demand
```

and, beside it, a four-line Dockerfile:

```dockerfile
FROM ghcr.io/papeete-hub/foundry-implementation-actor:0.5.1
RUN pip install --no-cache-dir kpack==2.0.1 kontract==0.1.0   # what this sidecar's ground_in names
COPY actor-agentic-context.yaml /actor/
RUN foundry-implementation-actor render-cards /actor && foundry-implementation-actor lint /actor
```

**That is the whole repository.** No cards, no entrypoint, no Python. The cards are rendered from
the definition in the image, the entrypoint is `foundry-implementation-actor serve`, and the only
hand-written line naming anything is the `pip install` of the knowledge tools this capability's own
`ground_in:` argv happens to name — which is the consumer's fact by design (ADR-FIA-0005).

A second capability instantiates the same actor by writing that sidecar. Nothing here is
subclassed, hooked, or configured with a strategy object — there is one shape, and it is this one.

### Embedding it instead

A consumer that wants its own base image, or the actor inside a larger process, skips all of the
above and wires it in four lines:

```python
from foundry_implementation_actor import CapabilityConfig, ClaudeCodeEngine, make_implement_task

config = CapabilityConfig.load(".")
actor = Actor.from_card(".", mailbox=mailbox,
                        engines={config.engine: ClaudeCodeEngine(config)},
                        actions={"implement-task": make_implement_task(config)})
```

`assess-task` needs no entry here: it is a query with an engine and no handler, so the engine's own
judgement is the reply. `pip install foundry-implementation-actor` is enough for this; the mailbox
and the observability backend that `serve` needs live in the `[serve]` extra, so an embedder is not
handed an HTTP server it did not ask for.

## The definition, and a use

This package is where the actor is **defined**. `src/foundry_implementation_actor/cards/` holds its
four cards — who it is, the data it knows, the messages it exchanges, and the one `implement-task`
door it answers — and they ship in the wheel, reachable as `cards_path()`. They name no capability,
because which capability an instance serves is not part of what the actor *is*.

A **use** of this actor is one capability's own folder: the `actor-agentic-context.yaml` that binds
it to that capability's repository and knowledge base, and the four cards named for the capability
it serves — **rendered from the definition, not copied.** `foundry-implementation-actor
render-cards` writes them, the image runs it at `docker build` time, and a use's repository
therefore holds one hand-written YAML file. That is why the cards live in the wheel rather than in
an `examples/` folder: they are build input, not documentation (ADR-FIA-0005).

They used to be copied by hand, which is why the gate below exists.

The split is what the name asserts. `ADR-ECO-0022` makes the `-actor` suffix an obligation: a
package ending in `-actor` claims a `papeete-actor` underneath, *"and a `<use>-<tier>-actor` that
ships no conformant card is misnamed, not merely unusual."* `tests/test_cards.py` runs that check
in the suite, and CI runs it again against the built wheel:

```bash
papeete-actor-synchronous-messaging lint-card \
  "$(python -c 'from foundry_implementation_actor import cards_path; print(cards_path())')"
```

A hand copy drifts: both folders pass `lint-card` independently, and neither gate has an opinion
about the other. `foundry-implementation-actor lint` therefore runs a second check —
`conformance.check` — comparing the use's cards against the definition's on the **derived wire
contract**: the set of doors, and each door's `request_schema`, `completion_schema` and `engine`.
Those derivations already fold in the data dictionary and the message catalog, so a renamed item or
a changed reference lands in the payload a caller is validated against.

Rendering makes that gate cheap to pass rather than redundant, and both are worth having: a use
still carrying a hand copy from before 0.5.0, or one pinned to an older image, is exactly the case
that can be wrong — and a construction that cannot drift is still better than a check that catches
drift, which is why the rendering exists at all.

Prose is not compared, on purpose: a use *should* name its real capability and its real peers, and
`actor.yaml`'s `name:` is its own identity and is required to differ.

Because the cards sit under `src/`, `tests/test_portability.py` greps them too — a capability id or
a knowledge tool name written into the actor's own definition fails the build exactly as it would
in the code.

## Two doors

| door | verb | what it does |
|---|---|---|
| `implement-task` | request | builds the increment, commits, pushes a branch, publishes one image per touched component |
| `assess-task` | query | answers whether a proposed acceptance surface can be delivered. Writes nothing |

Both name the same engine. `Actor.judge()` hands it the door id, and it dispatches on that.

### `implement-task`

```
clone (full, not --depth 1)
  → checkout impl/TASK-NNN
  → run every ground_in fetch, write it into the clone, render CLAUDE.md
  → claude --print --output-format stream-json --permission-mode acceptEdits
  → git add <each component root>; refuse anything staged outside them
  → commit as the actor, push the branch
  → buildctl build + push one image per touched component
```

It never opens a pull request. Rendering a verdict and opening one belongs to whichever actor
orchestrates the pipeline, once its other members have also confirmed.

## The three amigos round

Before any of that, the actor that will black-box test the increment says what it intends to
assert, and this one answers whether that can be delivered:

```
orchestration ──▶ testing:        propose the acceptance surface for this task
              ◀──                 expectations[] — each with a stable id, a statement, a handle
orchestration ──▶ implementation: assess-task — can you deliver this?
              ◀──                 feasible + objections[] + commitments[]

  agreed     → the surface goes to implement-task AND test-task, on every attempt
  disagreed  → orchestration stops and hands the objections back to a human
```

**Exactly one round, then a person.** No counter-proposal and no negotiation loop: a three-amigos
meeting converges because a human is in the room, and here the human *is* the tie-breaker. *"The
task does not determine this"* is a legitimate answer, and it is the most useful one.

`assess-task` is a **query**, not an action — *"a promise to answer, from this actor's own state
and nothing invented."* It clones read-only, grounds itself exactly as the implement door does, and
is invoked with `--tools Read,Glob,Grep`, so `Write`, `Edit` and `Bash` are absent from the session
rather than merely unapproved (0.5.0 passed only `--allowedTools`, which removes nothing — see
ADR-FIA-0004's amendment). A door that **cannot** write
beats a door asked not to. It registers no handler either: with an engine and no handler,
`Actor.receive()` returns the judged dict as the reply, and there is nothing to contain because
nothing is produced.

What it commits to is a **promise, not a report** — nothing has been built when it answers. That
distinction is the whole point (`ADR-FIA-0004`): a tester deriving its assertions from what was
already built can only ever confirm the build. The failure this prevents is real and already in the
wild — an e2e suite carrying three fixture ids its own comment admits were *"discovered black-box
against the running container"*, against a task card that never named them.

`acceptance_surface` then rides along as an **optional** field on `implement-task`. Without it the
door behaves exactly as before; with it, where it is more specific than the definition of done, it
wins.

## Grounding is a precondition, not a request

`CLAUDE.md` at the working directory's root is loaded by the `claude` CLI **before the first
turn**, and its `@relative/path.md` imports resolve eagerly at the same moment. Verified live in
this actor's exact invocation shape: a question only the fetched context could answer came back in
`num_turns: 1` with zero tool calls.

So the envelopes are written **inside the clone** and named from a generated `CLAUDE.md`. The
earlier arrangement — fetch into a sibling tempdir, then ask the session in prose to "read it
before you start" — was not broken, it was *advisory*: whether the context entered the window was
the model's choice, re-made every session, and a session that skipped it looked exactly like one
that had read it. An `@`-import resolves relative to the file containing it, so the sibling-tempdir
arrangement could not have been fixed by writing a better prompt.

If the repo commits its own `CLAUDE.md`, the generated block is **appended**, never substituted.

### The two tiers

| `load:` | cost | when |
|---|---|---|
| `eager` | its full token weight, every session, unconditionally | the session cannot do the work without it |
| `on-demand` | one line — its `answers:` and its path | useful sometimes; the session opens it if the task needs it |

Choose from a measurement of the envelope, not from taste. One such read has already been recorded
as putting *"40 kB of JSON on screen"*.

## One capability id, eight renderings, zero literals

Every identifier is derived from `capability` and `source_repo`. `foundry-implementation-actor
show` prints the table for a given sidecar:

| rendering | from |
|---|---|
| `ACME.PARTS.CAP.SUP.007.WID` | `capability` |
| `acme-lab/ACME.PARTS.CAP.SUP.007.WID-implementation` | `source_repo` |
| `acme.parts/sup.007.wid` | the id, split at its `CAP` segment |
| `acme.parts.cap.sup.007.wid-backend` | the image name `papeete-version` versions |
| `acme-parts-cap-sup-007-wid-implementation-TASK-042-` | the clone's tempdir prefix |
| `ACME.PARTS.CAP.SUP.007.WID-implementation` | git `user.name` |
| `acme-parts-cap-sup-007-wid-implementation@users.noreply.github.com` | git `user.email` |
| `<registry>/acme.parts/sup.007.wid/<component>:<version>` | the published image ref |

**The image ref is a three-way contract.** Peer actors recompute the identical string and parse it
back apart, so it is derivation output or nothing. Never invent a tag scheme.

## The write boundary is stated once

`components[].path` — and nothing else. It used to be declared in the sidecar *and* hardcoded in
the module that actually enforces containment, which is how a boundary comes to be stated twice
and eventually stated differently.

Containment is `git add <each root>`, never `-A` and never a bare `.`, then an assertion that every
staged path starts with one of them. A staged path outside is **refused**, the index reset, and the
door answers a refusal. The session's own prompt only asks for the boundary; this is what holds it.

Which component a staged path belongs to is resolved by **longest declared prefix**, not by taking
the path's first segment — that shortcut is correct only while every root is one segment deep, and
reports the wrong component the day one of them is `src/gateway/`.

## Credentials

Two, both passed at run time, never baked into an image:

| variable | what for |
|---|---|
| `GITHUB_TOKEN` | fine-grained PAT: `contents:write` on `source_repo`, read-only `contents` on whatever the `ground_in` fetches resolve through |
| `CLAUDE_CODE_OAUTH_TOKEN` | from `claude setup-token` on a machine with a browser, tied to a Pro/Max/Team/Enterprise subscription |

> **Do not also set `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN`.** In `claude -p`
> non-interactive mode an API key present in the environment is ALWAYS preferred over
> `CLAUDE_CODE_OAUTH_TOKEN`, silently routing every session through metered billing. There is no
> warning and no visible difference in the transcript; the only symptom is the bill.

Publishing additionally needs `IMAGE_REGISTRY` and `BUILDKIT_HOST`. There is no Docker daemon and
no docker socket anywhere in this design — `buildctl` is a client, which is why an actor running
this can be an ordinary Pod.

## What a session may spend

Environment, read once at boot by `serve`; constructor keywords on `Settings` for an embedder. The
budget is **not** a sidecar field: a capability declares what it is, not how long its actor may
think (ADR-FIA-0007).

| variable | default | what it costs to raise |
|---|---|---|
| `MAX_TURNS` | `60` | `implement-task`'s turns. A turn is a model call plus a tool call; raising it buys a slower-to-navigate repo more room, and buys a session that has lost the plot more room to keep losing it |
| `SESSION_TIMEOUT_S` | `1800` | `implement-task`'s wall clock. The caller's own door timeout has to exceed it, or a slow success arrives as "did not answer" |
| `ASSESS_MAX_TURNS` | `15` | `assess-task`'s turns. It reads and answers; it cannot write |
| `ASSESS_TIMEOUT_S` | `600` | `assess-task`'s wall clock. Round 0 blocks on it, before anything is built |
| `CLONE_TIMEOUT_S` | `120` | the full clone, per door call |
| `FETCH_TIMEOUT_S` | `120` | each `ground_in` fetch, per door call |

**The defaults have not moved** since these became reachable; they are what every use was already
running. A value that is not a positive integer is refused at boot, naming itself, rather than
silently falling back — so a raised budget that was misspelt crash-loops with the reason on stdout
instead of changing nothing. The four session knobs are on the `actor-started` record too, so a run
that ran out of budget can be read against the budget it actually had.

A door that runs out says so in those terms: `implement-task ran out of turns (max_turns=60) and
was stopped mid-work, so nothing it produced is kept — raise MAX_TURNS on this actor's Deployment,
or narrow the task.`

## CLI

```bash
foundry-implementation-actor lint .                        # validate the sidecar and the cards
foundry-implementation-actor show . --registry reg.example.com   # every derived rendering
foundry-implementation-actor render-cards .                # write the four cards from the wheel
foundry-implementation-actor serve .                       # boot it (needs the `serve` extra)
```

`render-cards` and `serve` are what the image runs, and are usable anywhere the wheel is. `lint` is
the gate CI runs. A sidecar declaring some other `context:` is read, warned, and not
checked further — UNMIGRATED is not the same as non-conformant, and migrating is the owning pair's
own act.

## Observability

One JSON object per step, so a dashboard reads them with the same `| json` it uses for the session
transcript and tells them apart by `event`:

```
{level, event: "step",   step, phase: start|ok|failed, duration_ms, error}
{level, event: "event",  step, **fields}
{level, event: "result", cost_usd, input_tokens, output_tokens}
correlation_id, task_id                                    # structured metadata
```

**That schema is the contract; the step names are not.** Step names may be renamed freely — a
drill-down discovers them. `correlation_id` is the W3C trace id the caller propagated, not a second
identifier invented here, so it pastes straight from Loki into Tempo.

Every emitted line is budgeted to 64 KB. Loki's `max_line_size` is 256 KB with
`max_line_size_truncate: false` — an oversized line is **rejected outright**, not trimmed, so one
large `Read` would silently delete exactly the turn worth reading while leaving the rest intact.

## Where this came from

Extracted from one capability's own implementation actor, where 891 lines of this machinery sat
beside the business capability's source. Both files that moved said so themselves: the engine's
docstring called extraction *"a near-mechanical move"*, and the sidecar's header said it was kept
structural *"specifically so extracting this into a real published package later (once proven) is a
move, not a rewrite."*

`adr/` records the decisions. Design rationale belongs there, not in commit messages.

## Releasing, and which registry to pin

A tag (`v*`) publishes two artifacts at one version — the wheel to PyPI, and the image to **two
registries** holding the same digest (ADR-FIA-0006):

| Registry | Pin it when |
|---|---|
| `ghcr.io/papeete-hub/foundry-implementation-actor` | you are writing a use's Dockerfile yourself, and build it with your own Docker |
| a product's own registry, `vars.PRODUCT_IMAGE` | the use is built **in-cluster**, by a builder whose one registry credential is that product's |

The second exists because `buildctl` resolves a `FROM` line client-side against the single registry
credential it was handed — so a use built by the cluster's shared builder can only reach the
product's own registry, whatever the README says. The push is skipped, with a notice, when
`vars.PRODUCT_IMAGE` is unset.

To give an already-released version an image in a registry it missed, run the workflow by hand from
the default branch with the tag as its input — it checks that tag out, and refuses it if it
disagrees with the `pyproject.toml` beside it:

```bash
gh workflow run release.yml --ref main -f tag=v0.5.0
```

That run skips PyPI (which refuses a version it already holds) and does not move `latest` in either
registry.

## Development

```bash
uv run --extra dev pytest -q     # what CI runs
uv build
```

There is no separate lint/format command configured in this repo.
