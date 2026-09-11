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

import pytest
from papeete_actor_synchronous_messaging import card
from papeete_actor_synchronous_messaging.actor import Actor, Refusal

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


def test_the_doors_name_the_engine_a_sidecar_must_declare():
    """Every door and a use's sidecar name the same engine key.

    The entrypoint registers the engine under the sidecar's `engine:`, and each door resolves
    through the card's. They are two statements of one fact, in two repos; this pins the half that
    lives here so a use's `lint` failure is the only way they can disagree.
    """
    loaded = card.load(cards_path())
    assert set(loaded.actions) == {"implement-task"}, (
        f"expected the one implement-task action, got {sorted(loaded.actions)}")
    assert set(loaded.queries) == {"assess-task"}, (
        f"expected the one assess-task query, got {sorted(loaded.queries)}")
    engines = {offer.engine
               for offer in (*loaded.actions.values(), *loaded.queries.values())}
    assert engines == {"claude-code"}, f"expected claude-code on every door, got {engines}"


def test_assessing_is_a_query_and_implementing_is_an_action():
    """An action is a promise to try; a query is a promise to answer, from this actor's own state
    and nothing invented. Assessing whether a proposed acceptance surface can be delivered writes
    nothing, and which list a door sits in IS its nature — see ADR-FIA-0004."""
    loaded = card.load(cards_path())
    assert "assess-task" not in loaded.actions
    assert "implement-task" not in loaded.queries


def test_the_assess_door_is_answered_by_its_engine_with_no_handler_registered():
    """The claim the "no deterministic half" design rests on.

    `Actor.receive()` does `elif judged is not None: result = judged` — a door with an engine and
    no registered handler is answered by the engine directly. `handler.py` is untouched by this
    door because there is nothing to contain: it commits nothing and publishes nothing.
    """
    class StubEngine:
        name = "claude-code"

        def judge(self, *, system, prompt, schema=None):
            assert prompt.splitlines()[1] == "door: assess-task"
            return {"feasible": True, "commitments": ["widget ids 1, 2, 3"]}

    actor = Actor.from_card(cards_path(), engines={"claude-code": StubEngine()})
    reply = actor.receive(verb="query", door="assess-task", from_="a-caller", payload={
        "task_id": "TASK-042",
        "title": "Supply the widget",
        "definition_of_done": ["GET /widgets/{id} returns 200"],
        "acceptance_surface": [{"id": "EXP-001"}],
    })
    assert reply == {"feasible": True, "commitments": ["widget ids 1, 2, 3"]}


def test_the_assess_door_refuses_a_payload_naming_no_surface():
    """`request_schema` is derived from `assess-task-cmd` and is closed. The surface is the one
    thing this door exists to be handed, so its absence is refused at the membrane."""
    actor = Actor.from_card(cards_path(), engines={"claude-code": object()})
    with pytest.raises(Refusal, match="acceptance_surface"):
        actor.receive(verb="query", door="assess-task", from_="a-caller", payload={
            "task_id": "TASK-042", "title": "t", "definition_of_done": ["d"]})
