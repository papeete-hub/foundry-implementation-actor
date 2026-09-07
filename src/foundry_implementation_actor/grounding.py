"""Grounding — putting the capability's own context in front of the session before turn one.

THE MECHANISM, AND WHY IT IS THIS ONE. `CLAUDE.md` at the working directory's root is loaded by
the `claude` CLI **before the first turn**, and its `@relative/path.md` imports are resolved
eagerly at the same moment. Verified live in this actor's exact invocation shape (`--print
--output-format stream-json --permission-mode acceptEdits`): a question only the fetched context
could answer came back in `num_turns: 1` with zero tool calls. Nothing was read, because nothing
needed to be — it was already in the window.

WHAT THIS REPLACES. The previous arrangement fetched the same envelopes into a tempdir **beside**
the clone and asked the session, in prose, to "read it before you start". That is not broken —
reads outside the cwd work and no permission denial was ever recorded — but it is *advisory*.
Whether the context entered the window at all was the model's choice, re-made every session, and
a session that skipped it looked exactly like one that had read it. Writing the envelopes inside
the clone and naming them from a generated `CLAUDE.md` turns grounding from a request into a
precondition.

WHY INSIDE THE CLONE, SPECIFICALLY. A `@`-import resolves relative to the file that contains it.
An envelope in a sibling tempdir can be *described* to a session but never imported by one, so
the sibling-tempdir arrangement could not have been fixed by writing a better prompt.

TWO TIERS, AND WHY THE CHOICE IS A MEASUREMENT. `load: eager` costs its full token weight on
every session, unconditionally, whether or not the task touches what it describes. `load:
on-demand` costs one line — its `answers:` and its path — and the session pays the rest only if
it opens the file. Neither is the right default in general; the right one for a given source is
whatever its measured envelope size says. One such read was already recorded as putting "40 kB of
JSON on screen", so this is not a hypothetical budget.

CONTAINMENT IS UNAFFECTED. The handler stages only `components[].path`, so everything written
here — the `.foundry/` envelopes and the generated `CLAUDE.md` alike — is never staged, never
committed, and dies with the clone. No `.gitignore` entry is needed, and adding one would be a
second place to state a boundary that is already stated once.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from papeete_actor_synchronous_messaging.engine import EngineError

from .config import CapabilityConfig, Grounding

CLAUDE_MD = "CLAUDE.md"

DEFAULT_FETCH_TIMEOUT_S = 120

# The marker that lets a generated block be told apart from prose a repo wrote for itself. It is
# not parsed — nothing here ever edits a previous block, because every clone is fresh — but a
# human reading a session's clone should be able to see instantly which half is machine-written.
_BEGIN = "<!-- foundry-implementation-actor: generated grounding -->"


def ground(config: CapabilityConfig, clone_dir: Path, *,
           timeout: int = DEFAULT_FETCH_TIMEOUT_S) -> list[Grounding]:
    """Fetch every `ground_in` source, write it into the clone, and render `CLAUDE.md`.

    Returns the entries that were grounded, in declaration order. Raises `EngineError` if any
    fetch fails — a session grounded in half its context is worse than one that never started,
    because only the second is visible.
    """
    for entry in config.ground_in:
        envelope = fetch(config, entry, timeout=timeout)
        write_envelope(config, entry, clone_dir, envelope)
    render_claude_md(config, clone_dir)
    return list(config.ground_in)


def fetch(config: CapabilityConfig, entry: Grounding, *,
          timeout: int = DEFAULT_FETCH_TIMEOUT_S) -> str:
    """Run one entry's `fetch:` argv and return its stdout.

    This package knows no knowledge tool by name. It knows "run this, ground the session in what
    comes back" — which is why a fourth source is a YAML entry rather than a change here.
    """
    argv = config.expand(entry.fetch)
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as e:
        raise EngineError(
            f"grounding '{entry.name}': '{argv[0]}' is not on PATH. The sidecar names the tools "
            f"this capability grounds itself in; installing them is the consuming image's job, "
            f"not this package's."
        ) from e
    except subprocess.TimeoutExpired as e:
        raise EngineError(
            f"grounding '{entry.name}': {' '.join(argv)} timed out after {timeout}s"
        ) from e
    if result.returncode != 0:
        raise EngineError(
            f"grounding '{entry.name}': {' '.join(argv)} failed: {result.stderr.strip()}"
        )
    return result.stdout


def write_envelope(config: CapabilityConfig, entry: Grounding, clone_dir: Path,
                   envelope: str) -> Path:
    """Write one fetched envelope into the clone, as Markdown wrapping the raw payload.

    Markdown rather than the bare `.json` the previous arrangement wrote, for one reason: a
    `CLAUDE.md` `@`-import pulls in a file whole, so the file has to carry its own title and its
    own "what this answers" line, or the session receives a wall of JSON with no idea which
    question it settles. The payload itself is untouched inside the fence.
    """
    destination = clone_dir / entry.into
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        f"# {entry.name}\n\n"
        f"{entry.answers}\n\n"
        f"Fetched fresh for this session by `{' '.join(config.expand(entry.fetch))}`. Read it as "
        f"given — it is this capability's own standing context, not something to re-derive.\n\n"
        f"```json\n{_pretty(envelope)}\n```\n"
    )
    return destination


def render_claude_md(config: CapabilityConfig, clone_dir: Path) -> Path:
    """Write the clone's `CLAUDE.md`, or append to one the repo already commits.

    APPEND, NEVER OVERWRITE. The capability repo has no `CLAUDE.md` of its own today, which is
    exactly why this is safe to introduce now — there is nothing to clobber, so the clean-slate
    case is the one being exercised. The day one is committed, it is the repo's own standing
    guidance for anyone working in it, and silently replacing it with a generated block would
    remove the very thing a session most needs to obey.
    """
    body = _claude_md_body(config)
    path = clone_dir / CLAUDE_MD
    if path.exists():
        existing = path.read_text().rstrip("\n")
        path.write_text(f"{existing}\n\n---\n\n{body}")
    else:
        path.write_text(body)
    return path


def _claude_md_body(config: CapabilityConfig) -> str:
    eager = [g for g in config.ground_in if g.eager]
    on_demand = [g for g in config.ground_in if not g.eager]

    lines = [
        _BEGIN,
        "",
        f"# {config.capability} — context for this session",
        "",
        "You are working inside a private clone made for one task. The context below was fetched "
        "fresh for this session from this capability's own knowledge registry. It is authoritative: "
        "read it as given rather than re-deriving what it already answers.",
        "",
    ]

    if eager:
        lines += ["## Standing context", ""]
        for entry in eager:
            lines.append(f"{entry.answers}:")
            lines.append("")
            lines.append(f"@{entry.into}")
            lines.append("")

    if on_demand:
        lines += [
            "## Available on demand",
            "",
            "Not loaded. Open the file if the task needs what it answers.",
            "",
        ]
        for entry in on_demand:
            lines.append(f"- **{entry.name}** — {entry.answers}. `{entry.into}`")
        lines.append("")

    lines += [
        "## Boundaries",
        "",
        f"Write ONLY under {_join(config.writes_only_under)}. Nothing else in this clone is yours "
        f"to change, and a staged path outside those roots is refused rather than committed.",
        "",
        "Do not `git add`, `git commit`, or `git push` — that is handled outside this session.",
        "",
    ]
    return "\n".join(lines) + "\n"


def _pretty(envelope: str) -> str:
    """Pretty-print a JSON envelope; pass anything else through untouched.

    The fetch contract is "whatever the tool prints", not "JSON" — a source that emits Markdown or
    plain text is equally groundable, and reformatting is a convenience for the JSON case, never a
    requirement placed on the tool.
    """
    text = envelope.strip()
    try:
        return json.dumps(json.loads(text), indent=2, ensure_ascii=False)
    except (json.JSONDecodeError, ValueError):
        return text


def _join(items) -> str:
    return ", ".join(items)
