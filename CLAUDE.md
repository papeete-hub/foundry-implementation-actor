# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this
repository.

## What this is

`foundry-implementation-actor` runs a headless Claude Code implementation session against one
capability's own repo, then commits, pushes and publishes what it produced. It is the **machinery**
— it carries no capability of its own. The capability arrives in a sidecar
(`actor-agentic-context.yaml`, contract `foundry-implementation-actor/agentic-context/v1`) that the
consuming repo writes.

Extracted from one capability's implementation repo, where it sat beside that capability's own
source. See `adr/ADR-FIA-0001-*.md` and README.md's "Where this came from".

## Commands

```bash
uv run --extra dev pytest -q                                    # full suite (what CI runs)
uv run --extra dev pytest -q tests/test_config.py               # one file
uv run --extra dev pytest -q tests/test_config.py::test_name    # one test
uv build                                                        # sdist/wheel (hatchling)
uv run foundry-implementation-actor lint <folder>               # validate a sidecar
uv run foundry-implementation-actor show <folder> --registry r  # every derived rendering
```

There is no separate lint/format command configured in this repo.

## Architecture

Seven modules under `src/foundry_implementation_actor/`:

- **`config.py`** — `CapabilityConfig`. The heart. Loads the sidecar and derives **every**
  rendering of the capability id from two declared fields (`capability`, `source_repo`). Also
  carries `lint()` and the `Report` it returns.
- **`grounding.py`** — runs each `ground_in` entry's `fetch:`, writes the envelope **inside the
  clone** as Markdown, and renders the `CLAUDE.md` that makes the eager ones enter the session's
  window before turn one.
- **`engine.py`** — `ClaudeCodeEngine`. Satisfies the `Engine` port from
  `papeete-actor-synchronous-messaging`. Clones, branches, grounds, runs `claude --print`, streams
  and projects every turn to the log. Never commits.
- **`handler.py`** — `make_implement_task(config)`. Containment, commit, push, publish. Never
  opens a pull request.
- **`correlation.py`** — the two ids and the step vocabulary. Moved **verbatim** from the repo this
  was extracted from; its code below the docstring is byte-identical.
- **`conformance.py`** — `check(folder)`. Compares a use's cards against the definition's, on
  the derived wire contract only (door ids, each door's request/completion schema and engine).
  Prose and `actor.yaml`'s `name:` are deliberately not compared — a use should name its own
  capability. `lint` runs it beside the sidecar gate.
- **`cli.py`** — argparse wiring only, no logic of its own.

Beside them, two folders of committed contract, both shipped in the wheel:

- **`schemas/agentic-context.schema.yaml`** — the sidecar contract this package owns, which
  `lint` checks a use against.
- **`cards/`** — the actor's own four cards: what this actor IS, as opposed to which capability a
  use of it serves. `cards_path()` returns the folder. They name no capability, and they are what
  a spawned instance would be rendered from once a use is not a static repository.

## Core invariants that any change must preserve

- **A use's cards are a hand copy, and hand copies drift.** Both folders pass `lint-card`
  independently, and neither gate looks at the other — so a definition that gains a field leaves
  every un-updated use linting green and refusing callers at runtime. `conformance.check` is the
  only thing that catches it. Compare the DERIVED contract, never the prose.
- **The `-actor` suffix is a claim, and it is checked.** `ADR-ECO-0022`: a package ending in
  `-actor` asserts a `papeete-actor` underneath, and one that ships no conformant card is
  misnamed. `tests/test_cards.py` runs `lint-card` on `cards/` in the suite; CI and the release
  workflow run it again against the built wheel, so the cards cannot silently stop shipping.
- **No capability literal, ever.** `tests/test_portability.py` greps `src/` for the originating
  instance's identifiers *and* for any knowledge tool name (`kpack`, `kontract`, …), and fails on
  either. The tools a capability grounds itself in are the consumer's dependencies. A fourth
  knowledge source is a `ground_in` entry, never a change here.
- **The image ref is a three-way contract.** `<registry>/<capability_path>/<component>:<version>`
  — peer actors recompute the identical string and parse it back apart. It is `config.image_ref`
  output or nothing. **Never invent a tag scheme.**
- **The write boundary is stated once**, as `components[].path`. It used to be declared in the
  sidecar *and* hardcoded in the enforcing module. Do not reintroduce a second copy.
- **Component resolution is longest-prefix**, not the path's first segment. The shortcut is correct
  only while every component root is one segment deep.
- **The observability record schema is the contract; step names are not.** `{event: "step", step,
  phase, duration_ms}`, `{event: "event", step, **fields}`, `{event: "result", cost_usd,
  input_tokens, output_tokens}`, plus `correlation_id`/`task_id` as structured metadata. Rename a
  step freely; do not change a record's shape.
- **Every emitted log line is budgeted to 64 KB.** Loki rejects an oversized line outright rather
  than truncating it, so one large `Read` would silently delete exactly the turn worth reading.
- **The clone is full, never `--depth 1`.** `papeete_version.compute()` runs `git describe --tags`
  against it and needs the matching tag's commit reachable.
- **The generated `CLAUDE.md` appends** to one the repo already commits. Never overwrite.
- **Never set `ANTHROPIC_API_KEY` in a container running this.** In `claude -p` non-interactive
  mode an API key in the environment is always preferred over `CLAUDE_CODE_OAUTH_TOKEN`, silently
  routing every session through metered billing. There is no warning; the only symptom is the bill.

## Scope discipline

Generic across **capabilities**, not across actor *kinds*. No hooks, no base classes, no strategy
objects for a hypothetical second consumer. If a change would only make sense for an actor that
does not exist yet, it does not belong here.

Design rationale lives in `adr/`. Add a new ADR (copy `adr/template.md`) for any decision of
similar weight rather than only writing it into code comments.

## Releasing

Tag-triggered (`v*`) via `.github/workflows/release.yml`, publishing to PyPI through Trusted
Publishing (OIDC) — no stored token. The release job builds the wheel, installs it into a throwaway
venv, and renders a `CLAUDE.md` from a fixture sidecar, asserting its `@`-imports resolve, before
publishing. `ci.yml` runs the suite plus two gates — *the wheel must carry its contract* and *the
gate must run* — and reaches nothing outside its own checkout.
