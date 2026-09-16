"""`Settings` — how much a session may spend, as opposed to which capability it serves.

WHY THIS IS NOT THE SIDECAR. The sidecar declares facts about a capability: its id, its repo, its
components, what it grounds itself in. How many turns a door may take and how long it may take
them are facts about an ENVIRONMENT — a capability whose code is slow to navigate (a solution that
restores packages on every build, a monorepo whose grep is expensive) needs a larger budget for
exactly the same task definition, and the same capability deployed twice may want two answers.
A capability declares what it is, not how long its actor may think (ADR-FIA-0007; ADR-FIA-0002
drew the same line when it took testing out of the sidecar).

WHY NOT CONSTRUCTOR KEYWORDS ALONE. They were exactly that, and `serve` constructed the engine
with none of them — so the budget of every actor running from the published image was whatever
this file says, and an operator facing an out-of-turns failure had no way to move it short of
editing the package. They are still constructor keywords, for an embedder; `from_env` is how
`serve` fills them from the Pod spec, which is where an operator can actually reach.

WHERE THE DEFAULTS LIVE. Here, not in `engine.py`, because `engine.py` names `ENV` when it
reports a budget that ran out — and one table is what keeps the failure message, `from_env` and
the README from disagreeing about what an operator should set.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, fields, replace

from .grounding import DEFAULT_FETCH_TIMEOUT_S

DEFAULT_CLONE_TIMEOUT_S = 120
DEFAULT_SESSION_TIMEOUT_S = 1800
DEFAULT_MAX_TURNS = 60

# The assess door reads and answers; it never writes. Its budget is smaller than the implement
# door's on every axis, and its tool list is the enforcement — a door that CANNOT write beats one
# asked not to. See ADR-FIA-0004.
DEFAULT_ASSESS_TIMEOUT_S = 600
DEFAULT_ASSESS_MAX_TURNS = 15


class SettingsError(ValueError):
    """An environment variable was set to something this actor cannot use."""


# field name → environment variable. One table, so `from_env`, the engine's own out-of-budget
# message and the README cannot disagree about what to set.
ENV = {
    "max_turns": "MAX_TURNS",
    "session_timeout_s": "SESSION_TIMEOUT_S",
    "assess_max_turns": "ASSESS_MAX_TURNS",
    "assess_timeout_s": "ASSESS_TIMEOUT_S",
    "clone_timeout_s": "CLONE_TIMEOUT_S",
    "fetch_timeout_s": "FETCH_TIMEOUT_S",
}

# Settings field → the `ClaudeCodeEngine` constructor keyword it fills. The two spellings differ
# on purpose: `_s` says "seconds" to whoever reads a Deployment, and the engine's keywords are
# already published API.
ENGINE_KWARGS = {
    "max_turns": "max_turns",
    "session_timeout_s": "session_timeout",
    "assess_max_turns": "assess_max_turns",
    "assess_timeout_s": "assess_timeout",
    "clone_timeout_s": "clone_timeout",
    "fetch_timeout_s": "fetch_timeout",
}


@dataclass(frozen=True)
class Settings:
    max_turns: int = DEFAULT_MAX_TURNS
    session_timeout_s: int = DEFAULT_SESSION_TIMEOUT_S
    assess_max_turns: int = DEFAULT_ASSESS_MAX_TURNS
    assess_timeout_s: int = DEFAULT_ASSESS_TIMEOUT_S
    clone_timeout_s: int = DEFAULT_CLONE_TIMEOUT_S
    fetch_timeout_s: int = DEFAULT_FETCH_TIMEOUT_S

    @classmethod
    def from_env(cls, environ: dict | None = None) -> Settings:
        """Defaults, overridden by whichever of `ENV`'s variables are set and non-empty.

        A typo raises `SettingsError` — at boot, where it is a crash-loop with the reason on
        stdout, rather than silently falling back to the default and leaving an operator who
        raised a budget wondering why nothing changed.
        """
        environ = os.environ if environ is None else environ
        values: dict = {}
        for field in fields(cls):
            variable = ENV[field.name]
            raw = environ.get(variable)
            if raw is None or raw == "":
                continue
            try:
                value = int(raw)
            except ValueError as e:
                raise SettingsError(f"{variable}={raw!r} is not an integer") from e
            if value < 1:
                raise SettingsError(f"{variable}={raw!r} must be at least 1")
            values[field.name] = value
        return replace(cls(), **values)

    def engine_kwargs(self) -> dict:
        """What `serve` splats into `ClaudeCodeEngine(config, **...)`."""
        return {keyword: getattr(self, field) for field, keyword in ENGINE_KWARGS.items()}
