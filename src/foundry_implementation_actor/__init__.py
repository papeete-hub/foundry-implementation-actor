"""foundry-implementation-actor — run a headless Claude Code implementation session against one
capability's own repo.

An actor, for one use, with a `papeete-actor` underneath. The capability it serves is supplied by
a sidecar (`actor-agentic-context.yaml`, `foundry-implementation-actor/agentic-context/v1`), never
by this package: a second capability instantiates the same actor by writing that file and nothing
else.

Wiring one up is four lines:

    from foundry_implementation_actor import CapabilityConfig, ClaudeCodeEngine, make_implement_task

    config = CapabilityConfig.load(".")
    actor = Actor.from_card(".", mailbox=mailbox,
                            engines={config.engine: ClaudeCodeEngine(config)},
                            actions={"implement-task": make_implement_task(config)})

`correlation` is exported too — an entrypoint installs its filter on the root logger's handlers
after configuring observability, so every record the process emits carries this request's ids.
"""
from .config import (CapabilityConfig, Component, ConfigError, Grounding, Report,
                     cards_path, lint)
from .engine import ClaudeCodeEngine
from .handler import HandlerError, make_implement_task
from . import conformance, correlation, grounding

__all__ = [
    "CapabilityConfig",
    "ClaudeCodeEngine",
    "Component",
    "ConfigError",
    "Grounding",
    "HandlerError",
    "Report",
    "cards_path",
    "conformance",
    "correlation",
    "grounding",
    "lint",
    "make_implement_task",
]
