---
id: ADR-FIA-0007
title: "A session's budget is an environment setting — and a door that runs out says what to change"
status: Accepted
date: 2026-09-16
supersedes: []
references:
  - src/foundry_implementation_actor/settings.py
  - src/foundry_implementation_actor/serve.py
  - src/foundry_implementation_actor/engine.py
---

# ADR-FIA-0007 — A session's budget is an environment setting

## Context

`ClaudeCodeEngine` has always taken its budget as constructor keywords: `max_turns`,
`session_timeout`, `assess_max_turns`, `assess_timeout`, plus `clone_timeout` and `fetch_timeout`.
`serve.py` constructed it as `ClaudeCodeEngine(config)` and passed none of them.

So for every actor running from the image this package publishes — which is every actor, since
ADR-FIA-0005 made a use one sidecar and no Python — the budget was whatever `engine.py` said, and
the only way to move it was to edit and re-release the package. The keywords were reachable in
principle and unreachable in practice.

A live end-to-end run on 2026-09-15 turned that into a real cost. An `implement-task` session hit
`--max-turns 60` after 470s of a 1800s timeout. It had made the actual fix by turn 14, then spent
turns 18–60 building a unit test nobody had asked for, and was killed with the work uncommitted.
The repo in question is a .NET solution that restores packages on many of its turns, so 60 turns
buys it materially less reading than it buys a Python one — exactly the case an operator should be
able to answer from a Deployment.

The failure said none of this:

```
EngineError: claude session failed (subtype=error_max_turns):
```

Not what the limit was, not which of the two doors hit it, not what to change. The only way to
learn any of it was to read the CLI's own transcript out of the Pod's `/tmp/.claude/projects`
before the Pod went away.

`foundry-task-orchestration-actor` had already answered the first half of this for its own knobs: a
`settings.py` holding one `field name → environment variable` table, a `from_env` that reads it,
and a `serve` that passes the result.

## Decision

1. **The budget is an environment setting, not a sidecar field.** A new `settings.py`, modelled on
   the orchestration actor's: a frozen `Settings` dataclass, one `ENV` table, `from_env(environ)`,
   and a `SettingsError` for a value that cannot be read. Six variables — `MAX_TURNS`,
   `SESSION_TIMEOUT_S`, `ASSESS_MAX_TURNS`, `ASSESS_TIMEOUT_S`, `CLONE_TIMEOUT_S`,
   `FETCH_TIMEOUT_S`. `serve` reads it at boot and splats `settings.engine_kwargs()` into the
   engine; an embedder passes its own `Settings` and never touches the environment.
2. **A value that is not a positive integer is refused at boot**, naming the variable and what it
   was set to. A misspelt budget crash-loops with the reason on stdout rather than silently
   running under the default it was raised from.
3. **The `actor-started` record carries the four session knobs**, so a run that ran out is
   readable against the budget it actually had.
4. **A door that runs out of budget names the budget, the door and the variable.** Both the
   out-of-turns and the timeout paths, keyed off `ENV` so the remedy cannot drift from what
   `from_env` reads.
5. **The defaults do not move.** 60/1800 to implement, 15/600 to assess — unchanged.

## Rationale

**Why not the sidecar.** The sidecar declares facts about a capability: its id, its repo, its
components, what it grounds itself in. How many turns its actor may take is not one of them. The
same capability deployed twice may want two answers; two capabilities of identical shape in
different languages want different ones for the same task. ADR-FIA-0002 drew this line already when
it took `components[].tests` out of the sidecar — a component declares what is built, not how it is
verified — and this is the same line one field over: a capability declares what it is, not how long
its actor may think.

**Why not raise the default instead.** Raising 60 to 90 would have made this particular run pass
and taught nothing. The run that failed was not short of turns in general; it was short of turns
*for that repository*, and it also spent two thirds of its budget on work outside its task. Those
are two different problems with two different owners, and a default that hides the first also hides
the second. Making the budget reachable lets the one use that needs more say so, in its own
Deployment, where the reason can be written next to the number.

**Why the failure matters as much as the setting.** A knob nobody can find is not much better than
a knob that does not exist. The evidence for this decision is an incident whose diagnosis required
`kubectl exec` into a Pod; the failure message is what makes the next one diagnosable from the log
line alone.

**Why `engine.py` imports the defaults from `settings.py` rather than the reverse.** The engine's
own failure message names the environment variable, so it needs `ENV`. One table, in one direction,
is what keeps the message, `from_env` and the README from disagreeing.

## Consequences

- `serve.py` is no longer the place that decides a budget. An operator raises one on a Deployment.
- `DEFAULT_MAX_TURNS` and its four siblings moved from `engine.py` to `settings.py`. They are
  still importable, under a new module — an embedder that imported them from `engine` must follow.
- The engine's constructor signature is unchanged, so an embedder that passed keywords is
  untouched.
- `tests/test_settings.py` pins the defaults, every variable, the refusals, and that `ENV`,
  `ENGINE_KWARGS` and the dataclass's own fields name the same set — a field added without a
  variable cannot go quiet.
- **Follow-up: `foundry-testing-actor` carries the same shape** — `DEFAULT_MAX_TURNS = 60`, a
  `propose_max_turns` beside it, and a `serve` that passes neither. It deserves the identical
  change, as its own pass and its own release; its doors are not the ones that failed here.
- Not addressed: a session that spends its budget on work outside its task. That is a prompt
  question, and turning it into a budget question is what this ADR declines to do.
