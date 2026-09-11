"""Rendering one use's cards from the definition this package ships.

WHAT A USE USED TO BE. A folder carrying its own copy of the actor's four cards, named for the
capability it serves, beside the sidecar that binds it to that capability. The copy was made by
hand, and `conformance.py` exists because a hand copy drifts: both folders pass `lint-card`
independently, neither gate has an opinion about the other, and the day the definition gains a
door every use in the world is silently wrong until someone edits four files in each of them.

WHAT A USE IS NOW. A folder carrying a sidecar. The cards are rendered into it — at `docker build`
time in the image this package ships, or by hand with `render-cards` anywhere else — from
`cards_path()`, which `cards_path()`'s own docstring always said was "what a spawned instance
would be rendered from". A gate that catches drift is strictly worse than a construction that
cannot drift. `conformance.check` stays for the uses that still carry a copy, and for a use
pinned to an older image; it just stops being the only thing between a stale card and a caller
refused at a door (ADR-FIA-0005).

WHAT IS RENDERED, AND WHAT IS COPIED. Three of the four cards name no capability and are copied
byte-for-byte under a banner — the data dictionary, the message catalog, and the doors are what
the actor IS, and a use that differed in any of them would be a different actor. Only
`actor.yaml` is rendered, because only identity differs per use: `name:` is the `actor_name` the
sidecar already derives, and the description says which capability this instance serves.

WHAT IS DELIBERATELY LOST. The hand-written prose. A use's `means:` used to name its real peers by
name; the rendered one says "an orchestrating actor does, once a testing actor also confirms",
because the sidecar declares no peers. `conformance.check` already refuses to compare prose for
exactly this reason, so nothing is checked that now fails — but a reader of `describe` gets less.
That is the trade, and it is written down in ADR-FIA-0005 rather than discovered.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from .config import CapabilityConfig, cards_path, version

# The four, in the order `papeete_actor_synchronous_messaging.card` opens them. It opens exactly
# these and never globs, which is why a use missing one does not boot rather than booting smaller.
CARD_FILES = ("actor.yaml", "actor-data.yaml", "actor-message.yaml",
              "actor-synchronous-messaging.yaml")

# Only identity differs per use. Everything else about the actor is the same actor.
_RENDERED = "actor.yaml"


def _banner(source: str = "") -> str:
    """The comment that stops someone editing a file which is overwritten on every build."""
    body = (
        f"RENDERED — do not edit. `foundry-implementation-actor render-cards` wrote this from the "
        f"actor's own definition, shipped in foundry-implementation-actor=={version()}{source}. "
        f"Change it by changing the definition and taking a new version of the package, not by "
        f"editing here: the next `docker build` discards whatever is written in this file."
    )
    return _wrap(body, width=98, indent="# ")


def _render_manifest(config: CapabilityConfig, definition: Path) -> str:
    """`actor.yaml`, the only card that differs per use.

    Emitted rather than substituted-into: the definition's own header says "THIS FOLDER IS THE
    DEFINITION, NOT A USE", which would be false the moment it were copied into one. The
    description is the definition's own, with the capability this instance serves appended — so
    the sentence a reader gets still comes from the definition and cannot silently diverge from it.
    """
    card = yaml.safe_load(definition.read_text())
    described = " ".join(str(card["description"]).split())
    return (
        _banner(", named for the capability this use's sidecar declares")
        + f"manifest: {card['manifest']}\n"
        + f"name: {config.actor_name}\n"
        + "description: >-\n"
        + _wrap(f"{described} This instance serves {config.capability}, whose repository is "
                f"{config.source_repo}.")
    )


def _wrap(text: str, width: int = 96, indent: str = "  ") -> str:
    """Fold one paragraph into a YAML block scalar body.

    `textwrap` would do this, and would also collapse the sentence differently across Python
    versions' defaults for `break_on_hyphens` — a capability id is full of dots and a repo name is
    full of hyphens, and a card that reflows between two machines is a diff nobody asked for.
    """
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}" if current else word
        if current and len(indent) + len(candidate) > width:
            lines.append(indent + current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(indent + current)
    return "\n".join(lines) + "\n"


def render_cards(config: CapabilityConfig, dest: str | Path) -> list[Path]:
    """Write this actor's four cards into `dest`, named for the capability `config` serves.

    Returns the paths written, in the order they were written. Overwrites: these files are build
    output, and the banner on each one says so.
    """
    definition = cards_path()
    missing = [name for name in CARD_FILES if not (definition / name).exists()]
    if missing:
        # A wheel that lost its cards. `lint-card` in CI and in the release workflow exists to stop
        # that reaching a registry; this turns the leftover case into a sentence rather than a
        # traceback from inside a `docker build` someone is watching.
        raise FileNotFoundError(
            f"{definition}: this package's own cards are missing ({', '.join(missing)}), so there "
            f"is nothing to render from. The build shipped without them — report it against the "
            f"release."
        )

    out = Path(dest)
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name in CARD_FILES:
        target = out / name
        if name == _RENDERED:
            target.write_text(_render_manifest(config, definition / name))
        else:
            # Byte-for-byte under a banner. Not parsed and re-emitted: a round-trip through
            # `yaml.safe_dump` would drop every comment in the definition, and those comments are
            # where the reasoning for each door and each data item is written down.
            target.write_text(_banner("") + definition.joinpath(name).read_text())
        written.append(target)
    return written
