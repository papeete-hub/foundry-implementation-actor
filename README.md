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
  - {name: backend, path: backend/, tests: backend/tests/, dockerfile: backend/deployment/local}
  - {name: stub,    path: stub/,    tests: stub/tests/,    dockerfile: stub/deployment/local}
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

and four lines in the consuming entrypoint:

```python
from foundry_implementation_actor import CapabilityConfig, ClaudeCodeEngine, make_implement_task

config = CapabilityConfig.load(".")
actor = Actor.from_card(".", mailbox=mailbox,
                        engines={config.engine: ClaudeCodeEngine(config)},
                        actions={"implement-task": make_implement_task(config)})
```

A second capability instantiates the same actor by writing that file. Nothing here is subclassed,
hooked, or configured with a strategy object — there is one shape, and it is this one.

## The definition, and a use

This package is where the actor is **defined**. `src/foundry_implementation_actor/cards/` holds its
four cards — who it is, the data it knows, the messages it exchanges, and the one `implement-task`
door it answers — and they ship in the wheel, reachable as `cards_path()`. They name no capability,
because which capability an instance serves is not part of what the actor *is*.

A **use** of this actor is one capability's own folder: its own copy of those four cards, named for
the capability it serves, beside the `actor-agentic-context.yaml` that binds it to that capability's
repository and knowledge base. Today that folder is a static repository, and the copy is made by
hand. Once an instance can be spawned from a capability id alone, the cards here are what it would
be rendered from — which is why they live in the wheel rather than in an `examples/` folder.

The split is what the name asserts. `ADR-ECO-0022` makes the `-actor` suffix an obligation: a
package ending in `-actor` claims a `papeete-actor` underneath, *"and a `<use>-<tier>-actor` that
ships no conformant card is misnamed, not merely unusual."* `tests/test_cards.py` runs that check
in the suite, and CI runs it again against the built wheel:

```bash
papeete-actor-synchronous-messaging lint-card \
  "$(python -c 'from foundry_implementation_actor import cards_path; print(cards_path())')"
```

A use's copy is made by hand, so it can drift: both folders pass `lint-card` independently, and
neither gate has an opinion about the other. `foundry-implementation-actor lint` therefore runs a
second check — `conformance.check` — comparing the use's cards against the definition's on the
**derived wire contract**: the set of doors, and each door's `request_schema`, `completion_schema`
and `engine`. Those derivations already fold in the data dictionary and the message catalog, so a
renamed item or a changed reference lands in the payload a caller is validated against.

Prose is not compared, on purpose: a use *should* name its real capability and its real peers, and
`actor.yaml`'s `name:` is its own identity and is required to differ.

Because the cards sit under `src/`, `tests/test_portability.py` greps them too — a capability id or
a knowledge tool name written into the actor's own definition fails the build exactly as it would
in the code.

## What one request does

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

## CLI

```bash
foundry-implementation-actor lint .                        # validate the sidecar
foundry-implementation-actor show . --registry reg.example.com   # every derived rendering
```

`lint` is the gate CI runs. A sidecar declaring some other `context:` is read, warned, and not
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

## Development

```bash
uv run --extra dev pytest -q     # what CI runs
uv build
```

There is no separate lint/format command configured in this repo.
