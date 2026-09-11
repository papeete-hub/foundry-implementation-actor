"""`ClaudeCodeEngine` — judgement by running a headless Claude Code session against a fresh clone.

WHY A CUSTOM ENGINE, NOT `papeete_actor_synchronous_messaging.engine.resolve("claude")`. The
built-in `ClaudeEngine` shells out to the raw `anthropic` Python SDK — `anthropic.Anthropic()`,
resolving `ANTHROPIC_API_KEY`, then `ANTHROPIC_AUTH_TOKEN`, then an `ant auth login` profile.
Every one of those is a metered API credential. Subscription OAuth tokens (`claude setup-token`
→ `CLAUDE_CODE_OAUTH_TOKEN`) are scoped to the `claude` CLI / claude.ai specifically and are NOT
among the credentials the raw SDK will resolve. So the only way to spend a subscription's own
credit rather than a separate metered key is to shell out to the `claude` CLI itself, which is
what this file does. It still satisfies the `Engine` port (`name` + `judge(system, prompt,
schema=None) -> dict`) — the port makes no promise about how long or heavy a judgement is.

**Do not set `ANTHROPIC_API_KEY` (or `ANTHROPIC_AUTH_TOKEN`) in a container running this engine.**
In `claude -p` non-interactive mode an API key present in the environment is ALWAYS preferred over
`CLAUDE_CODE_OAUTH_TOKEN`, silently routing every session through metered billing instead. There is
no warning and no visible difference in the transcript; the only symptom is the bill.

PAYLOAD-DRIVEN, NOT CARD-DRIVEN. The caller supplies everything a session needs to work — this
engine never clones a repo merely to look up what a task IS. A missing required field is refused
by the framework's own schema gate before any engine time is spent, so there is no eligibility
check here either.

CARRIES NO CAPABILITY LITERAL. Every identifier it needs comes from `CapabilityConfig`, which
derives all of them from one capability id and one repo (see `config.py`). The system prompt is
never invented here either: `Actor.judge()` builds it from the card's own `means:`/`completion:`
prose and hands it in as `system`, which this engine passes straight through via
`--append-system-prompt`, unmodified.

WHAT THIS ENGINE DOES NOT DO. It never commits, pushes, or opens a pull request — that is
`handler.py`'s job, and `handler.py`'s own containment check is the actual enforcement of the
write boundary this engine's prompt only *asks* the session to respect. On success it
deliberately does NOT clean up its own clone: the handler still needs it to commit and push, and
is the one that removes it, on every path including containment failure.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from papeete_actor_synchronous_messaging.engine import EngineError

from . import correlation, grounding
from .config import CapabilityConfig

DEFAULT_CLONE_TIMEOUT_S = 120
DEFAULT_SESSION_TIMEOUT_S = 1800
DEFAULT_MAX_TURNS = 60

# The assess door reads and answers; it never writes. Its budget is smaller than the implement
# door's on every axis, and its tool list is the enforcement — a door that CANNOT write beats one
# asked not to. See ADR-FIA-0004.
DEFAULT_ASSESS_TIMEOUT_S = 600
DEFAULT_ASSESS_MAX_TURNS = 15

IMPLEMENT_TOOLS = "Bash,Read,Edit,Write,Glob,Grep"
ASSESS_TOOLS = "Read,Glob,Grep"

# The door ids this engine answers. They are the card's, not this module's invention — `judge()`
# is handed the id it must dispatch on (see `_door_from_prompt`).
IMPLEMENT_DOOR = "implement-task"
ASSESS_DOOR = "assess-task"


# ── stream-json projection: keeping every emitted log line inside Loki's max_line_size ────────
#
# WHY PROJECT RATHER THAN LOG THE RAW EVENT. `--output-format stream-json` emits one JSON object
# per turn — the inner conversation this actor's audit trail is made of. Two of its fields are
# unbounded: `tool_use.input` (for `Write`, the whole file body; for `Edit`, both sides of the
# replacement) and `tool_result.content` (for `Read`/`Grep`/`Bash`, the whole output). Nothing
# else is: a `text` block is a few hundred bytes. So clipping those two, and only those, keeps
# the entire conversation readable while bounding every line — and what gets clipped is
# recoverable from the branch `handler.py` pushes anyway.
#
# WHY IT MATTERS. Loki's `max_line_size` is 256KB with `max_line_size_truncate: false` — an
# oversized line is REJECTED OUTRIGHT, not trimmed, so a single large `Read` would silently
# delete exactly the turn worth reading while leaving the rest of the session intact. The budget
# below is a quarter of that, which also sidesteps Loki parsing `KB` as 1000 rather than 1024.
#
# AND WHY NOT RECORD ATTRIBUTES. The OTel `LoggingHandler` maps the formatted message to the OTLP
# body (the line Loki measures) and record attributes to log-record attributes, which land in Loki
# structured metadata under their own separate caps (`max_structured_metadata_size: 64KB`,
# `max_structured_metadata_entries_count: 128`). Payload cannot be smuggled out of the line limit
# by moving it there — that channel is for correlation ids, which `correlation.py` stamps onto
# every record this process emits without any call site here passing them.

LINE_BUDGET = 64 * 1024   # bytes per emitted log line
BLOB_HEAD = 2000          # bytes kept from the front of an unbounded value
BLOB_TAIL = 2000          # ...and from the back: a Bash failure lives in the tail, not the head
PROSE = 8000              # text/thinking/result — prose IS the audit trail, give it more room


def _clip(value, head: int = BLOB_HEAD, tail: int = BLOB_TAIL) -> str:
    """Head+tail slice of a value, budgeted in BYTES (not characters — the limit Loki enforces
    is on the UTF-8 encoded line), with the true size recorded in the marker."""
    if not isinstance(value, str):
        value = json.dumps(value, default=str)
    raw = value.encode("utf-8", "replace")
    if len(raw) <= head + tail:
        return value
    return (raw[:head].decode("utf-8", "replace")
            + f"\n…[clipped {len(raw) - head - tail} of {len(raw)} bytes]…\n"
            + raw[-tail:].decode("utf-8", "replace"))


def _project(event: dict) -> dict | None:
    """One stream-json event -> a compact dict, or None to drop it entirely."""
    kind = event.get("type")

    if kind == "system" and event.get("subtype") == "init":
        # The raw init event is ~2.2KB of tools/skills/slash_commands inventory. Four fields of
        # it are worth keeping — `session_id` is the join key to the CLI's own full transcript,
        # which it writes to $HOME/.claude/projects/<slug>/<session_id>.jsonl regardless of
        # --output-format.
        return {"event": "init", "session_id": event.get("session_id"),
                "model": event.get("model"), "cwd": event.get("cwd")}

    if kind == "result":
        usage = event.get("usage") or {}
        return {"event": "result", "session_id": event.get("session_id"),
                "subtype": event.get("subtype"), "is_error": event.get("is_error"),
                "num_turns": event.get("num_turns"), "duration_ms": event.get("duration_ms"),
                "cost_usd": event.get("total_cost_usd"),
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "result": _clip(event.get("result", ""), PROSE, PROSE)}

    if kind not in ("assistant", "user"):
        return None                       # rate_limit_event and friends carry no audit value

    blocks = []
    for block in (event.get("message") or {}).get("content", []):
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype in ("text", "thinking"):
            blocks.append({btype: _clip(block.get(btype, ""), PROSE, PROSE)})
        elif btype == "tool_use":
            blocks.append({"tool_use": block.get("name"), "id": block.get("id"),
                           "input": {k: _clip(v) for k, v in (block.get("input") or {}).items()}})
        elif btype == "tool_result":
            # `content` is a str for a text result and a list of blocks otherwise — `_clip`
            # json-dumps the latter rather than this guessing at its shape.
            blocks.append({"tool_result": block.get("tool_use_id"),
                           "is_error": block.get("is_error", False),
                           "content": _clip(block.get("content", ""))})
    return {"event": kind, "blocks": blocks} if blocks else None


def _line(record: dict) -> str:
    """Serialize, then hard-enforce the budget.

    The per-field clipping in `_project` is what keeps lines small; this is what makes "no line
    exceeds the budget" a property of the code rather than a hope — a `tool_use` carrying a
    hundred just-under-threshold keys would otherwise slip through the sum."""
    line = json.dumps(record, default=str, ensure_ascii=False)
    if len(line.encode("utf-8")) > LINE_BUDGET:
        half = LINE_BUDGET // 2 - 200
        line = json.dumps({"event": record.get("event"), "over_budget": True,
                           "clipped": _clip(line, half, half)}, ensure_ascii=False)
    return line


# ```json … ``` or a bare ``` … ``` block. Non-greedy, DOTALL: one match per fence, in order.
_FENCE = re.compile(r"```(?:json)?\s*\n(.*?)```", re.DOTALL)


def _redact(text: str, secret: str | None) -> str:
    return text.replace(secret, "***") if secret else text


def _payload_from_prompt(prompt: str) -> dict:
    """Recover the full payload dict from `Actor.judge()`'s own fixed prompt format
    (`papeete_actor_synchronous_messaging.actor.Actor.judge`):

        f"verb: {verb}\\ndoor: {offer.id}\\n{as_prompt_json(situation)}"

    where `situation["payload"]` is exactly what the caller sent at this door.
    """
    lines = prompt.split("\n", 2)
    if len(lines) < 3:
        raise EngineError(f"prompt does not follow Actor.judge()'s fixed format: {prompt!r}")
    try:
        situation = json.loads(lines[2])
        return situation["payload"]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise EngineError(f"could not recover payload from prompt: {e}") from e


def _door_from_prompt(prompt: str) -> str:
    """Recover the door id from `Actor.judge()`'s own fixed prompt format — its second line.

    ONE ENGINE, TWO DOORS. The `Engine` port is a single `judge()`, and both this actor's doors
    name the same engine key, so an instance registered under `claude-code` is asked to judge
    both. `Actor.judge()` already puts the door id on line 2 of the prompt it builds, so the
    dispatch needs nothing from the framework that is not already being handed over.
    """
    lines = prompt.split("\n", 2)
    if len(lines) < 2 or not lines[1].startswith("door: "):
        raise EngineError(f"prompt does not follow Actor.judge()'s fixed format: {prompt!r}")
    return lines[1][len("door: "):].strip()


def _extract_json(text: str) -> dict:
    """The single JSON object a judged answer ends with.

    A session's final `result` is prose that HAPPENS to contain the answer, not the answer — it
    reliably wraps it in a fence and unreliably says something either side of it. So: try every
    fenced block, last first (the last one is the conclusion; an earlier one is usually the
    session quoting what it was asked for), then the whole text for the case where it complied
    exactly. Anything else is an `EngineError` — a door that cannot say what it decided has not
    decided anything, and guessing on its behalf would be worse than failing.
    """
    for block in reversed(_FENCE.findall(text)):
        try:
            parsed = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    try:
        parsed = json.loads(text.strip())
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed
    raise EngineError(
        "the session produced no JSON object to read its judgement from; its answer ended: "
        f"{text[-2000:]!r}"
    )


def _as_bool(value) -> bool:
    """A session's idea of a boolean, as a boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "y", "1")
    return bool(value)


class ClaudeCodeEngine:
    """Judgement by shelling out to the `claude` CLI, against a fresh private clone."""

    def __init__(self, config: CapabilityConfig, *,
                 github_token: str | None = None, claude_bin: str = "claude",
                 clone_timeout: int = DEFAULT_CLONE_TIMEOUT_S,
                 fetch_timeout: int = grounding.DEFAULT_FETCH_TIMEOUT_S,
                 session_timeout: int = DEFAULT_SESSION_TIMEOUT_S,
                 max_turns: int = DEFAULT_MAX_TURNS,
                 assess_timeout: int = DEFAULT_ASSESS_TIMEOUT_S,
                 assess_max_turns: int = DEFAULT_ASSESS_MAX_TURNS):
        self.config = config
        # The engine's `name` is what the card's door names, so it comes from the sidecar rather
        # than being fixed here — the port requires the attribute, not a particular value.
        self.name = config.engine

        self.github_token = github_token or os.environ.get("GITHUB_TOKEN")
        if not self.github_token:
            raise RuntimeError(
                "ClaudeCodeEngine needs GITHUB_TOKEN in the environment — a fine-grained PAT with "
                f"contents:write on {config.source_repo}, plus read-only contents on "
                f"{config.registry_repo} and whatever else this capability's `ground_in` fetches "
                "resolve through."
            )
        self.claude_bin = claude_bin
        self.clone_timeout = clone_timeout
        self.fetch_timeout = fetch_timeout
        self.session_timeout = session_timeout
        self.max_turns = max_turns
        # Constructor kwargs, not sidecar fields: how long this actor's own doors may think is
        # operational tuning, not something a capability declares about itself (ADR-FIA-0002).
        self.assess_timeout = assess_timeout
        self.assess_max_turns = assess_max_turns
        self._configure_git_credentials()

    # ── the one Engine method ──────────────────────────────────────────────────────────────

    def judge(self, *, system: str, prompt: str, schema: dict | None = None) -> dict:
        """The one `Engine` method, serving both of this actor's doors.

        The port is a single `judge()`, and both doors name the same engine key, so the dispatch
        is on the door id `Actor.judge()` already puts on line 2 of the prompt. The two paths are
        deliberately asymmetric: `implement-task` hands its clone off live to the handler, which
        commits, pushes and then removes it; `assess-task` owns its clone from end to end and
        writes nothing anywhere.
        """
        door = _door_from_prompt(prompt)
        if door == ASSESS_DOOR:
            return self._assess(_payload_from_prompt(prompt), schema)
        if door == IMPLEMENT_DOOR:
            return self._implement(system, _payload_from_prompt(prompt))
        raise EngineError(
            f"this engine answers {IMPLEMENT_DOOR} and {ASSESS_DOOR}, not '{door}' — a door "
            f"naming this engine must be one it knows how to judge"
        )

    # ── implement-task: the door that builds ───────────────────────────────────────────────

    def _implement(self, system: str, payload: dict) -> dict:
        task_id = payload["task_id"]
        # The FIRST thing this door does, before anything that could fail: from here to the end
        # of this request's own thread, every record — this module's, handler.py's, and the HTTP
        # binding's own access line — carries both ids. `correlation_id()` reads the trace id the
        # orchestrating actor already propagated, so every actor in the pipeline agrees on it
        # without any of them passing it (see correlation.py).
        correlation.bind(correlation_id=correlation.correlation_id(), task_id=task_id)

        clone_dir = Path(tempfile.mkdtemp(prefix=self.config.clone_prefix(task_id)))

        try:
            with correlation.stage("clone-code", repo=self.config.source_repo):
                self._clone(clone_dir)

            branch = f"impl/{task_id}"
            self._git(clone_dir, ["checkout", "-b", branch])

            self._ground(clone_dir)

            situational_prompt = self._situational_prompt(payload)
            with correlation.stage("claude-session", branch=branch,
                                   max_turns=self.max_turns, timeout_s=self.session_timeout):
                summary = self._invoke_claude(clone_dir, system, situational_prompt)
        except BaseException:
            # Every failure path removes the clone. Success does not: the clone is handed off
            # live, and `handler.py` is what removes it once it has committed and pushed — or
            # refused for containment.
            _rmtree(clone_dir)
            raise

        return {
            "implemented": True,
            "clone_dir": str(clone_dir),
            "branch": branch,
            "summary": summary,
        }

    # ── assess-task: the door that only answers ────────────────────────────────────────────

    def _assess(self, payload: dict, schema: dict | None) -> dict:
        """Judge whether the proposed acceptance surface can be delivered. Write nothing.

        THE CLONE IS OWNED HERE, END TO END. `_implement` hands its clone off live because the
        handler still has to commit and push from it. This door has no handler and produces no
        artifact, so the `finally` is unconditional — success removes the clone exactly as
        failure does.

        NO BRANCH IS CHECKED OUT. There is nothing to put on one. The session gets the repository
        as it stands on the default branch, which is the state the expectations are being judged
        against.
        """
        task_id = payload["task_id"]
        correlation.bind(correlation_id=correlation.correlation_id(), task_id=task_id)

        clone_dir = Path(tempfile.mkdtemp(prefix=self.config.clone_prefix(task_id)))
        try:
            with correlation.stage("clone-code", repo=self.config.source_repo):
                self._clone(clone_dir)
            self._ground(clone_dir)

            with correlation.stage("assess-session", max_turns=self.assess_max_turns,
                                   timeout_s=self.assess_timeout):
                answer = self._invoke_claude(
                    clone_dir, self._assess_system(), self._assessment_prompt(payload, schema),
                    allowed_tools=ASSESS_TOOLS, max_turns=self.assess_max_turns,
                    timeout=self.assess_timeout,
                )
        finally:
            _rmtree(clone_dir)

        judged = _extract_json(answer)
        if "feasible" not in judged:
            raise EngineError(
                "the assessment named no `feasible` — the one thing the caller has to be able to "
                f"branch on; it answered: {judged!r}"
            )
        # Coerced rather than trusted: a session reliably means the boolean and unreliably types
        # it, and `Actor.receive()` would refuse the whole reply over a "true" that is a string.
        judged["feasible"] = _as_bool(judged["feasible"])
        return judged

    def _assess_system(self) -> str:
        """The system prompt for the assess door.

        NOT `Actor.judge()`'s own. That one is built from the whole card and ends with "Reply with
        a single JSON object capturing your judgement" — which is right, and is passed through
        unmodified for `implement-task`. But it is handed to this engine as `system` on both
        doors, and this door needs the session to spend its turns READING rather than answering
        from the card's prose alone. Saying so here keeps the framework's own prompt intact for
        the door that wants it.
        """
        return (
            "You are assessing, not building. Read the repository and the capability context you "
            "have been given, decide what is and is not deliverable, and say so. Do not write, "
            "edit or create any file; you have no tools to do so."
        )

    def _ground(self, clone_dir: Path) -> None:
        """Fetch every `ground_in` source into the clone and render its `CLAUDE.md`.

        Grounding is a PRECONDITION, not a request — see grounding.py. It runs before either
        door's prompt is built, and a failure here stops the request before any session time is
        spent, which is the cheapest place for it to stop. Both doors ground identically: the
        question "can this be built" needs the same standing context as building it.
        """
        for entry in self.config.ground_in:
            with correlation.stage(f"ground-{entry.name}", into=entry.into, load=entry.load):
                envelope = grounding.fetch(self.config, entry, timeout=self.fetch_timeout)
                grounding.write_envelope(self.config, entry, clone_dir, envelope)
        grounding.render_claude_md(self.config, clone_dir)

    # ── git ─────────────────────────────────────────────────────────────────────────────────

    def _configure_git_credentials(self) -> None:
        """Make GITHUB_TOKEN available to subprocesses that do their own git clones.

        A `ground_in` tool typically delegates git auth entirely to git's own credential
        resolution and never takes a token itself. A global URL rewrite is the one hook available
        to make those clones use this token too, without patching the tool. Idempotent; safe to
        call on every construction.
        """
        subprocess.run(
            ["git", "config", "--global",
             f"url.https://x-access-token:{self.github_token}@github.com/.insteadOf",
             "https://github.com/"],
            check=True, capture_output=True, text=True,
        )

    def _clone(self, dest: Path) -> None:
        # Full clone, not --depth 1: `papeete_version.compute()`'s own `semver_base()` does `git
        # describe --tags --match <name>/v*` against this clone, which needs the matching tag's
        # commit reachable in local history — a shallow clone only has the tip commit, and breaks
        # the moment the tag isn't that exact commit (verified live: it worked only by accident
        # while the repo's origin/main was still a single commit).
        url = f"https://x-access-token:{self.github_token}@github.com/{self.config.source_repo}.git"
        try:
            subprocess.run(
                ["git", "clone", url, str(dest)],
                check=True, capture_output=True, text=True, timeout=self.clone_timeout,
            )
        except subprocess.CalledProcessError as e:
            raise EngineError(
                f"could not clone {self.config.source_repo}: "
                f"{_redact(e.stderr, self.github_token)}"
            ) from e
        except subprocess.TimeoutExpired as e:
            raise EngineError(
                f"cloning {self.config.source_repo} timed out after {self.clone_timeout}s"
            ) from e

    def _git(self, clone_dir: Path, args: list[str]) -> str:
        try:
            result = subprocess.run(
                ["git", *args], cwd=clone_dir, check=True, capture_output=True, text=True,
            )
        except subprocess.CalledProcessError as e:
            raise EngineError(
                f"git {' '.join(args)} failed: {_redact(e.stderr, self.github_token)}"
            ) from e
        return result.stdout

    # ── situational prompt, built from the caller's own payload ───────────────────────────

    def _situational_prompt(self, payload: dict) -> str:
        """The task, and nothing else.

        NOTE WHAT IS ABSENT: any instruction to go and read the capability's context. That used
        to be a paragraph here, naming two files in a sibling tempdir and asking the session to
        read them "before you start". It is a precondition now — the generated `CLAUDE.md` is
        loaded before turn one — so asking for it again would be asking for something already
        done, in the one place a session is most likely to take the instruction literally and
        spend a turn on it.
        """
        config = self.config
        task_id = payload["task_id"]
        boundary = ", ".join(config.writes_only_under)

        sections = [
            f"# Implement {task_id} for {config.capability}: {payload['title']}\n\n"
            f"You are working inside your own private clone (branch already checked out). "
            f"Write ONLY under {boundary} — nothing else in this clone is yours to change. "
            f"Do not `git add`, `git commit`, or `git push` — that is handled outside this "
            f"session.\n\n"
            f"Scope this session to {task_id}'s own Definition of Done against the CURRENT state "
            f"of {boundary} — extend what's already there for whichever component(s) this task "
            f"touches, don't re-derive or re-verify the whole capability's surface from scratch."
        ]
        if payload.get("context"):
            sections.append(f"## Context\n{payload['context']}")
        sections.append(
            "## Definition of done\n"
            + "\n".join(f"- {item}" for item in payload["definition_of_done"])
        )
        if payload.get("acceptance_surface"):
            # Agreed at the assess door before any of this was built, and binding on the actor
            # that will test it too. Where it says something more precise than the definition of
            # done, it is the more precise one that has to hold.
            sections.append(
                "## Agreed acceptance surface\n"
                "This was agreed with the actor that will black-box test this increment, before "
                "anything was built. Every expectation below must hold, addressable exactly as "
                "its `handle` says — including any value committed to there. Where it is more "
                "specific than the definition of done, it wins.\n\n"
                + json.dumps(payload["acceptance_surface"], indent=2, ensure_ascii=False)
            )
        if payload.get("remediation_context"):
            sections.append(
                "## Remediation — the prior attempt's failing test criteria\n"
                f"{payload['remediation_context']}"
            )
        return "\n\n".join(sections)

    # ── the assessment prompt ───────────────────────────────────────────────────────────────

    def _assessment_prompt(self, payload: dict, schema: dict | None) -> str:
        """What the assess door asks. Nothing about writing, because it cannot.

        THE ANSWER'S SHAPE IS DERIVED, NOT INVENTED HERE. `Actor.judge()` already computes it
        from the door's own `completion_schema` and hands it over as `schema`; rendering that is
        how the prompt and the card cannot come to disagree. When it is absent — an engine driven
        directly, in a test or a probe — the door's own prose is the only contract, and the
        fallback below says the same thing in words.
        """
        config = self.config
        task_id = payload["task_id"]
        surface = payload.get("acceptance_surface") or []

        sections = [
            f"# Can {config.capability} deliver this for {task_id}: {payload['title']}?\n\n"
            f"Another actor will black-box test this increment, and has proposed below what it "
            f"intends to assert. NOTHING HAS BEEN BUILT YET. You are looking at the repository as "
            f"it stands today, to answer one question: can each of those expectations be "
            f"delivered under {', '.join(config.writes_only_under)}?\n\n"
            f"You are READING ONLY. Do not write, edit or create any file — you have no tools to "
            f"do so, and there is no branch and no commit at this door.\n\n"
            f"Judge each expectation on its own and give it its own answer:\n"
            f"- it can be delivered — and if a test could only address it once something is "
            f"pinned (a fixture's id, an endpoint path, an event routing key, the environment "
            f"variable its base URL arrives in), COMMIT to the exact value now. That commitment "
            f"is a promise you will honour when you implement, not a description of anything that "
            f"exists — nothing exists yet.\n"
            f"- it cannot be delivered at all — say why, and counter-propose if you can see one.\n"
            f"- the task does not determine it — say precisely what is missing. This is not a "
            f"failure; it is the question a human has to answer before either of us proceeds.\n"
            f"- it contradicts this capability's own contract, as your standing context states "
            f"it — say which part."
        ]
        if payload.get("context"):
            sections.append(f"## Context\n{payload['context']}")
        sections.append(
            "## Definition of done\n"
            + "\n".join(f"- {item}" for item in payload["definition_of_done"])
        )
        sections.append(
            "## Proposed acceptance surface\n"
            + (json.dumps(surface, indent=2, ensure_ascii=False) if surface
               else "(empty — say so, and say what you would expect to be asserted instead)")
        )
        sections.append(
            "## Your answer\n"
            "End with a single fenced ```json block and nothing after it, holding one object"
            + (f" conforming to:\n\n```json\n{json.dumps(schema, indent=2)}\n```"
               if schema else
               " with `feasible` (boolean), `objections` (one entry per expectation you cannot "
               "meet, each naming its `id`) and `commitments` (what you undertake to pin).")
        )
        return "\n\n".join(sections)

    # ── the judgement itself: a claude -p session against the checked-out clone ────────────

    def _invoke_claude(self, clone_dir: Path, system: str, situational_prompt: str, *,
                       allowed_tools: str = IMPLEMENT_TOOLS,
                       max_turns: int | None = None,
                       timeout: int | None = None) -> str:
        """Run the session, streaming every turn to the log as it happens.

        `--output-format stream-json --verbose` rather than `--output-format json`: the latter
        emits ONE object at the end, holding only the final assistant text, so the whole inner
        conversation — what was read, what was run, what was decided — existed nowhere durable
        once the pod went away. The projection above is what makes streaming it affordable.

        `Popen` rather than `subprocess.run`: reading line by line is what lets each turn be
        logged as it happens rather than after the session ends, and it stops a 30-minute
        session's entire output being buffered in a pod capped at 2Gi.
        """
        max_turns = self.max_turns if max_turns is None else max_turns
        timeout = self.session_timeout if timeout is None else timeout
        cmd = [
            self.claude_bin, "--print", "--output-format", "stream-json", "--verbose",
            "--append-system-prompt", system,
            "--permission-mode", "acceptEdits",
            # The assess door passes a list with no Write, Edit or Bash in it. That is the
            # enforcement, not the prompt's own "you are reading only" — the same discipline as
            # handler.py's containment check standing behind the implement door's write boundary.
            "--allowedTools", allowed_tools,
            "--max-turns", str(max_turns),
            situational_prompt,
        ]
        # stderr to a temp file, not a second pipe: nothing drains a second pipe while the
        # stdout loop below runs, so a chatty stderr would fill its buffer and deadlock the
        # session. Merging it into stdout is not an option either — it would corrupt the stream.
        with tempfile.TemporaryFile("w+") as errfile:
            try:
                proc = subprocess.Popen(cmd, cwd=clone_dir, stdout=subprocess.PIPE,
                                        stderr=errfile, text=True, bufsize=1)
            except FileNotFoundError as e:
                raise EngineError(
                    f"'{self.claude_bin}' is not on PATH — install @anthropic-ai/claude-code"
                ) from e

            # A watchdog, not a deadline checked per line: a session that hangs having emitted
            # nothing would never reach another loop iteration to be checked, and `Popen` has no
            # equivalent of `subprocess.run(timeout=...)` while iterating its output.
            timed_out = threading.Event()

            def _expire() -> None:
                timed_out.set()
                proc.kill()

            watchdog = threading.Timer(timeout, _expire)
            watchdog.start()

            final: dict | None = None
            try:
                for raw in proc.stdout:
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue          # a non-JSON line is noise, never the session's result
                    record = _project(event)
                    if record is not None:
                        # No %-args: `logging` only applies %-formatting when args are passed,
                        # so a stray % in a file body cannot raise here. No `extra=` either —
                        # `correlation.bind()` in `judge()` above already stamps task_id and
                        # correlation_id onto every record emitted on this thread.
                        logging.info(_line(record))
                    if event.get("type") == "result":
                        final = event
                proc.wait()
            finally:
                watchdog.cancel()
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
                proc.stdout.close()

            if timed_out.is_set():
                raise EngineError(
                    f"claude session for this task exceeded {timeout}s"
                )
            errfile.seek(0)
            stderr = errfile.read()

        if final is None:
            raise EngineError(
                f"claude (rc={proc.returncode}) produced no result event: {stderr[-2000:]}"
            )
        if final.get("is_error") or proc.returncode != 0:
            raise EngineError(
                f"claude session failed (subtype={final.get('subtype')}): "
                f"{final.get('result', '')[:4000]}"
            )
        return final.get("result", "")


def _rmtree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
