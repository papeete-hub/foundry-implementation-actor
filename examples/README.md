# A worked example — one actor, one capability

This folder teaches `foundry-implementation-actor` by showing a complete, working **use** of it:
[`ACME.PARTS.CAP.SUP.007.WID-implementation/`](ACME.PARTS.CAP.SUP.007.WID-implementation/).

The capability is fictional. Everything else is real — this is the exact folder CI and the release
workflow run their gates against, so nothing here can quietly stop being true.

You can run every command below **with no credentials, no network and no cluster.**

---

## What this actor does

One sentence: **it fetches a capability's own context, implements one task inside a private clone
of that capability's repo, and answers with the branch it pushed.**

```
  a caller                    this actor                         the world
  ────────                    ──────────                         ─────────
  POST /implement-task  ─────▶ clone the capability's repo  ────▶ git clone
   task_id, title,             ground the session           ────▶ the knowledge tools
   definition_of_done,           (fetch context, write it            the sidecar names
   context?, remediation?        into the clone)
                                run a headless `claude`      ────▶ Claude Code
                                  session against the task
                                stage ONLY declared          
                                  component roots, commit
                                push the branch              ────▶ git push  impl/TASK-NNN
                                build + push one image       ────▶ your registry
                                  per component it touched
  ◀───────────────────────────  {accepted, branch, images}
```

It **never opens a pull request.** That is a different actor's job, once a testing actor has also
confirmed. This one answers "done, here is the branch and the images" and stops.

### And one thing before that

There is a second door, `assess-task`, asked **before** anything is built. The actor that will
black-box test the increment proposes what it intends to assert; this one answers whether it can
deliver it:

```
  a caller                    this actor
  ────────                    ──────────
  QUERY /assess-task    ─────▶ clone read-only, ground the session
   task_id, title,             judge each proposed expectation
   definition_of_done,         (Read/Glob/Grep only — no Write, no Edit, no Bash)
   acceptance_surface
  ◀───────────────────────────  {feasible, objections, commitments}
```

It writes nothing, commits nothing and publishes nothing — which is why it is a **query** rather
than an action. A disagreement is an answer, not a refusal: the orchestrating actor hands it back
to a human rather than starting a session on a task nobody can satisfy yet.

The agreed surface then rides along as an optional `acceptance_surface` on `implement-task`.

### What it is for

An implementation task is normally a human reading the capability's domain model, opening the
repo, writing the code, and pushing a branch. This actor does that unattended, for one task, with
three properties that make the result trustworthy:

- **It is grounded, not guessing.** The capability's business and process context is fetched fresh
  and put in front of the session *before its first turn* — not offered for it to read if it feels
  like it.
- **It cannot write outside its lane.** The commit is refused if any staged path falls outside the
  component roots declared in the sidecar.
- **Everything it names is derived.** The branch, the image refs, the commit identity — all
  computed from two declared fields, so peer actors can recompute the identical strings.

---

## The one idea: a definition, and a use

This package **is** the actor. It ships the actor's four cards (`cards/` — who it is, the data it
knows, the messages it exchanges, the two doors it answers) plus the machinery behind them.

A **use** is one capability's own folder — and it holds **one hand-written file**, the one that
binds it to that capability. The four cards are rendered into it from the definition at
`docker build` time; nobody copies them (ADR-FIA-0005).

```
  foundry-implementation-actor        ACME.PARTS.CAP.SUP.007.WID-implementation
  (the definition — this package)     (a use — this folder)
  ├── cards/                          ├── actor-agentic-context.yaml   ← THE BINDING. Written.
  │   ├── actor.yaml                  └── Dockerfile                   ← 4 lines, one a gate
  │   ├── actor-data.yaml
  │   ├── actor-message.yaml               …and, after `docker build`, inside the image:
  │   └── actor-synchronous-…yaml          /actor/actor.yaml                   ← rendered:
  ├── the machinery                        /actor/actor-data.yaml              ┐  identity from
  └── the image                            /actor/actor-message.yaml           │  the sidecar,
                                           /actor/actor-synchronous-…yaml      ┘  rest verbatim
```

**`actor-agentic-context.yaml` is the whole binding.** No subclass, no fork, no code. A second
capability instantiates this same actor by writing that file.

---

## Read the sidecar

Open [`ACME.PARTS.CAP.SUP.007.WID-implementation/actor-agentic-context.yaml`](ACME.PARTS.CAP.SUP.007.WID-implementation/actor-agentic-context.yaml).
Four things are worth understanding:

**`capability` and `source_repo`** — the only two identifiers anyone writes. Every other rendering
is derived from them (see the table `show` prints below). Nothing else in the file, and nothing at
all in the package, spells a capability.

**`components:`** — the units this actor may write to and publish: what gets built and shipped.
**Their `path`s are the write boundary**, and nothing else declares it. Each also names its
Dockerfile directory, used when publishing.

**`ground_in:`** — what the session is told before turn one. Each entry is *a command to run* and
*a place to put its output inside the clone*. The package knows no knowledge tool by name: it runs
whatever argv you write here. **A third knowledge source is an entry in this list, not a new
release of this package.**

**`load:`** on each entry — `eager` puts the fetched context into the session's window
unconditionally, every time. `on-demand` costs one line (its `answers:` and its path) and the
session pays the rest only if it opens the file. This example uses one of each so you can see both.

> In this example the `fetch:` argvs are `printf`, so the whole thing runs offline. A real use
> names its actual knowledge tools there, and installs them in its image.

---

## Try it — three commands, no credentials

**1. Is this use valid?**

```bash
foundry-implementation-actor lint examples/ACME.PARTS.CAP.SUP.007.WID-implementation
```

Two gates run: the sidecar conforms to the contract, *and* — once the cards have been rendered —
they still answer the definition's doors. In this folder there are no cards yet, so the second gate
says so and passes: they arrive at `docker build` time, from the definition, which is what stops
them from ever disagreeing with it.

**2. What will it actually do?** This is the one that makes it click:

```bash
foundry-implementation-actor show examples/ACME.PARTS.CAP.SUP.007.WID-implementation \
  --registry registry.example.com
```

You wrote two identifiers. It prints the eight it derives from them — including **the exact image
ref it will publish, before it has published anything**:

```
  capability               ACME.PARTS.CAP.SUP.007.WID
  source_repo              acme-lab/ACME.PARTS.CAP.SUP.007.WID-implementation
  actor name / git author  ACME.PARTS.CAP.SUP.007.WID-implementation
  git author email         acme-parts-cap-sup-007-wid-implementation@users.noreply.github.com
  clone prefix             acme-parts-cap-sup-007-wid-implementation-TASK-NNN-
  registry path            acme.parts/sup.007.wid
  writes only under        backend/, stub/
  …
      image ref   registry.example.com/acme.parts/sup.007.wid/backend:<version>
```

**3. Does the grounding actually reach the session?**

```bash
python scripts/probe_grounding.py examples/ACME.PARTS.CAP.SUP.007.WID-implementation
```

This runs the real grounding path — fetch, write the envelopes into a clone, render its
`CLAUDE.md`, then check every `@`-import resolves. A session grounded in nothing looks exactly
like a correctly grounded one, which is why this is a gate rather than a hope.

**4. Build it — this one needs a credential.** The three above run offline; a `docker build` has to
pull the base image, and both registries that carry it are private. The `ARG ACTOR_IMAGE` default
names the product registry, so log into that one:

```bash
ACR_TF=../../papeete-platform/examples/acr-local     # wherever modules/acr was applied
terraform -chdir="$ACR_TF" output -raw pull_password | docker login papeetefoundry.azurecr.io \
  --username "$(terraform -chdir="$ACR_TF" output -raw pull_username)" --password-stdin

docker build -t acme-wid-actor ACME.PARTS.CAP.SUP.007.WID-implementation
docker run --rm acme-wid-actor foundry-implementation-actor lint /actor
```

The read-only pull token is enough — nothing here pushes. The last line is the interesting one: it
lints the cards the image actually rendered, which is what a caller will be validated against.

---

## What a real request looks like

You send the door a task. The caller supplies everything; this actor looks up no task card:

```bash
curl -X POST http://<actor>/implement-task -H 'Content-Type: application/json' \
  -d '{"from": "you", "payload": {
        "task_id": "TASK-014",
        "title": "Add a health endpoint to the stub",
        "definition_of_done": ["GET /health returns 200 with {\"status\": \"ok\"}"]
      }}'
```

It answers when the work is done:

```json
{"accepted": true,
 "branch": "impl/TASK-014",
 "images": ["registry.example.com/acme.parts/sup.007.wid/stub:0.1.0-task-014-28c22a0"]}
```

…or refuses, and says why — `{"accepted": false, "because": "..."}` — for a containment violation,
or when the session changed nothing.

Along the way it emits one log record per stage, each carrying the correlation id and task id, so a
run is watchable start to finish:

```
clone-code → ground-business → ground-process → claude-session
           → containment-commit → push-branch → publish-image
```

The grounding stages are named from your sidecar (`ground-<name>`), so adding a knowledge source
adds a stage without any code change.

---

## Instantiate one for your own capability

1. **Copy this folder.** Two files. Rename it after your capability's implementation repo.
2. **Edit the sidecar**: your `capability`, your `source_repo`, your `registry_repo`, your
   `components`, and `ground_in` entries naming the knowledge tools you actually use.
3. **Edit one line of the Dockerfile** — the `pip install` of those knowledge tools. The base image
   deliberately carries none: a `ground_in` entry supplies its own argv, so which tools exist is
   your fact, not this package's.

That is the whole instantiation. There is no third step: no cards to copy and keep in step, and no
entrypoint to write — `render-cards` produces the first from the definition in the image, and
`serve` is the second.

Then, before you spend a single session on it:

```bash
foundry-implementation-actor lint .                 # the sidecar you just wrote
foundry-implementation-actor show . --registry <your registry>   # every id it will derive
docker build -t my-actor . && docker run --rm my-actor foundry-implementation-actor lint /actor
```

The last one is the interesting one: it lints the cards the image actually rendered, which is what
a caller will be validated against. It needs the same registry login as step 4 above — or your own
`--build-arg ACTOR_IMAGE=`, if you mirror the base image somewhere of your own.

**Embedding it instead.** If you need your own base image, or the actor inside a larger process,
install the wheel and wire four lines yourself (`assess-task` needs no entry — it is a query with
an engine and no handler, so the engine's judgement is the reply):

```python
from foundry_implementation_actor import CapabilityConfig, ClaudeCodeEngine, make_implement_task

config = CapabilityConfig.load(".")
actor = Actor.from_card(".", mailbox=mailbox,
                        engines={config.engine: ClaudeCodeEngine(config)},
                        actions={"implement-task": make_implement_task(config)})
```

You will want `foundry-implementation-actor render-cards .` first, so that `from_card` has cards to
open.
