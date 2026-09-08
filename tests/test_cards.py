"""The `-actor` suffix, checked rather than asserted.

`ADR-ECO-0022` makes the suffix an obligation: "A package ending in `-actor` asserts a
`papeete-actor` underneath, which lint-card can check. A future `<use>-<tier>-actor` that ships no
conformant card is misnamed, not merely unusual."

This file is that check. It runs the same gate `papeete-actor-synchronous-messaging lint-card` runs,
against the cards this package ships — so the claim in the name is a test, not a sentence in a
record.

The cards live under `src/`, which means `test_portability.py` greps them too: a capability id or a
knowledge tool name written into the actor's own definition fails the build exactly as it would in
the code.
"""
from __future__ import annotations

from papeete_actor_synchronous_messaging import card

from foundry_implementation_actor import cards_path


def test_the_package_ships_the_four_cards():
    """A card folder is four files; `Actor.from_card` opens exactly these and never globs."""
    folder = cards_path()
    missing = [name for name in ("actor.yaml", "actor-data.yaml", "actor-message.yaml",
                                 "actor-synchronous-messaging.yaml")
               if not (folder / name).exists()]
    assert not missing, f"the actor's definition is incomplete — missing: {', '.join(missing)}"


def test_the_shipped_cards_are_conformant():
    """The whole of the `-actor` claim: this folder is a papeete-actor, or the name is wrong."""
    report = card.lint(cards_path())
    assert not report.errors, ("the cards this package ships are not conformant:\n  "
                               + "\n  ".join(report.errors))


def test_the_door_names_the_engine_a_sidecar_must_declare():
    """The card's door and a use's sidecar name the same engine key.

    The entrypoint registers the engine under the sidecar's `engine:`, and the door resolves
    through the card's. They are two statements of one fact, in two repos; this pins the half that
    lives here so a use's `lint` failure is the only way they can disagree.
    """
    loaded = card.load(cards_path())
    assert set(loaded.actions) == {"implement-task"}, (
        f"expected the one implement-task door, got {sorted(loaded.actions)}")
    engines = {offer.engine for offer in loaded.actions.values()}
    assert engines == {"claude-code"}, f"expected the one claude-code door, got {engines}"
