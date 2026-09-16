"""The entrypoint — moved here so two uses cannot wire their observability differently.

WHAT THIS REPLACES. A hand-written `app.py` in every use's repo: some sixty lines that configure
observability, add a console handler beside the OTLP one, install the correlation filter, read
`PORT`, build an `HttpMailbox`, call `Actor.from_card`, and emit an `actor-started` event. Not one
line of it is about the capability. Worse, the reasoning behind the strangest line — the console
handler — was discovered the hard way by an operator and then existed only as a comment someone
would have to copy correctly (ADR-FIA-0005).

WHY THE IMPORTS ARE LAZY. `papeete-actor-synchronous-messaging-http` and `papeete-observability`
are how this actor is CARRIED. ADR-PAM-0001 keeps wire out of the message contract, and the same
discipline keeps an HTTP server out of the dependency set of a consumer that only wants
`CapabilityConfig`. They arrive through the `serve` extra, and importing them inside the function
is what lets `foundry-implementation-actor lint` run in a venv that has neither.
"""
from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path

from . import correlation
from .config import CapabilityConfig
from .engine import ClaudeCodeEngine
from .handler import make_implement_task
from .instance import CARD_FILES, render_cards
from .settings import Settings

DEFAULT_PORT = 8080


class ServeError(RuntimeError):
    """Raised when the wire half of this actor is not installed."""


def _imports():
    try:
        from papeete_actor_synchronous_messaging.actor import Actor
        from papeete_actor_synchronous_messaging_http.mailbox import HttpMailbox
        from papeete_observability import configure
    except ImportError as e:  # pragma: no cover - exercised in the image, not the suite
        raise ServeError(
            f"the `serve` extra is not installed: {e}. `foundry-implementation-actor serve` needs "
            f"a mailbox and an observability backend, which are wire concerns this package does "
            f"not depend on by default — install `foundry-implementation-actor[serve]`, or use "
            f"the image this package publishes, which already has."
        ) from e
    return Actor, HttpMailbox, configure


def _cards_for(config: CapabilityConfig, folder: Path) -> Path:
    """The folder `Actor.from_card` is pointed at.

    Rendered at `docker build` time in the normal case, and this finds them already sitting beside
    the sidecar. A use that skipped that step gets them rendered into a tempdir now — the cards are
    derived from the definition either way, so there is no version of this that reads differently.
    Build time is still the better place: it is inspectable (`cat /actor/actor.yaml`), it fails
    while someone is watching a build rather than at a boot, and it needs no writable filesystem.
    """
    if all((folder / name).exists() for name in CARD_FILES):
        return folder
    rendered = Path(tempfile.mkdtemp(prefix=f"{config.actor_slug}-cards-"))
    render_cards(config, rendered)
    correlation.event(
        "cards-rendered", folder=str(rendered), actor=config.actor_name,
        because="the actor's folder carried no cards; render them at build time to have them "
                "beside the sidecar instead",
    )
    return rendered


def serve(folder: str | Path = ".", port: int | None = None) -> None:
    """Boot this actor and answer its doors until the process is stopped."""
    Actor, HttpMailbox, configure = _imports()

    configure()
    # papeete_observability.configure() attaches an OTLP log handler to the root logger but never
    # raises its level off the stdlib default WARNING, so logging.info(...) calls (including
    # HttpMailbox's own access log) would otherwise never reach it.
    logging.getLogger().setLevel(logging.INFO)
    # ...and a console handler beside it. The OTLP handler alone is write-only from an operator's
    # seat: with nothing on stdout, `kubectl logs` shows this pod's startup line and nothing else —
    # so a record that never reaches the log backend is indistinguishable from a record that was
    # never emitted, exactly when the telemetry backend is the thing under suspicion. Found the
    # hard way, against an HTTP binding that predated its own OTel wiring and emitted no records at
    # all, where `kubectl logs` could not have shown it. `StreamHandler.emit()` flushes per record,
    # so this needs no PYTHONUNBUFFERED to survive a container's block-buffered stdout.
    #
    # The formatter applies to THIS handler only — the OTLP `LoggingHandler` builds its body from
    # `record.getMessage()`, so what the log backend stores stays the bare message (for the
    # engine's own stream-json records, exactly the JSON object it logged).
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(
        correlation.ConsoleFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logging.getLogger().addHandler(console)
    # ...and, on both handlers, the filter that stamps every record with this request's own
    # correlation ids. On the HANDLERS, not the root logger: a record from a named logger (the HTTP
    # binding's own access log, most of all) reaches the root's handlers without the root LOGGER's
    # filters ever seeing it — see correlation.py's own docstring.
    correlation.install()

    folder = Path(folder)
    # The sidecar is the only thing in that folder this package did not put there.
    config = CapabilityConfig.load(folder)
    # Read before the mailbox is built: a misspelt budget is a crash-loop with the reason on
    # stdout, not a surprise at the first door call.
    settings = Settings.from_env()
    cards = _cards_for(config, folder)

    # PORT, not a hardcoded default: an env var is how an environment moves it without editing an
    # image, and it is what a Service's targetPort is set against.
    port = port if port is not None else int(os.environ.get("PORT", str(DEFAULT_PORT)))
    mailbox = HttpMailbox(port=port)  # 0.0.0.0:<port> — one POST per door, plus GET /health
    actor = Actor.from_card(
        cards,
        mailbox=mailbox,
        # One engine instance serves every door that names one: `Actor.judge()` hands it the door
        # id and it dispatches on that. The key comes from the sidecar rather than a literal here,
        # so a use whose sidecar names another engine is caught by its own card.
        # ...constructed with the budget the environment set, so `serve` is no longer the place
        # that decides how long a session may think (ADR-FIA-0007).
        engines={config.engine: ClaudeCodeEngine(config, **settings.engine_kwargs())},
        # `assess-task` needs no entry: it is a query with an engine and no handler, so the
        # engine's own judgement is the reply and there is no deterministic half to contain.
        actions={"implement-task": make_implement_task(config)},
    )
    # An `event` record rather than a `print`: a restart in the middle of a run is one of the most
    # explanatory things a pipeline panel can show, and `print` reaches only the container's own
    # stdout — never the OTLP handler, so never the log backend.
    # The budget is on this record because a run that ran out of it has to be diagnosable from
    # the log alone: "60 turns" in the failure means nothing unless the boot line says whether 60
    # was what this Deployment asked for.
    correlation.event("actor-started", actor=actor.name, port=port, capability=config.capability,
                      cards=str(cards),
                      max_turns=settings.max_turns,
                      session_timeout_s=settings.session_timeout_s,
                      assess_max_turns=settings.assess_max_turns,
                      assess_timeout_s=settings.assess_timeout_s)
    mailbox.serve_forever()
