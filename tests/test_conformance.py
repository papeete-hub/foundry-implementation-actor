"""A use answers the actor's doors, or it is not a use of that actor.

The definition and a use are two folders, each independently conformant, and neither gate has any
opinion about the other. `conformance.check` is the one that does — see `conformance.py` for what
it compares and, just as deliberately, what it does not.
"""
from __future__ import annotations

import shutil

import pytest
import yaml

from foundry_implementation_actor import cards_path, conformance

FIXTURE = "tests/fixtures/valid"


def _use(tmp_path, source=None):
    """A complete use folder, copied so a test can bend one thing in it."""
    folder = tmp_path / "use"
    folder.mkdir()
    for name in conformance.CARD_FILES:
        shutil.copy((source or cards_path()) / name, folder / name)
    return folder


def test_a_verbatim_copy_conforms(tmp_path):
    assert conformance.check(_use(tmp_path)).ok


def test_the_committed_fixture_conforms():
    """The fixture the wheel gates run against is a real use, not a sidecar on its own."""
    report = conformance.check(FIXTURE)
    assert report.ok, report.errors
    assert any("answers the definition's doors" in line for line in report.oks)


def test_no_cards_warns_rather_than_fails(tmp_path):
    """`lint` is also run against a bare sidecar. That is incomplete, not malformed."""
    (tmp_path / "empty").mkdir()
    report = conformance.check(tmp_path / "empty")
    assert report.ok
    assert any("no cards here" in w for w in report.warns)


def test_an_incomplete_card_set_fails(tmp_path):
    folder = _use(tmp_path)
    (folder / "actor-message.yaml").unlink()
    report = conformance.check(folder)
    assert not report.ok
    assert "actor-message.yaml" in report.errors[0]


def test_a_drifted_payload_is_caught(tmp_path):
    """The whole point: the use still lints, and still answers a different door.

    A reference dropped from the door's own message is the cheapest realistic drift — the card set
    remains internally valid, so every existing gate stays green.
    """
    folder = _use(tmp_path)
    path = folder / "actor-message.yaml"
    doc = yaml.safe_load(path.read_text())
    doc["messages"][0]["references"].remove("title")
    path.write_text(yaml.safe_dump(doc, sort_keys=False))

    report = conformance.check(folder)
    assert not report.ok
    assert any("accepts a different payload" in e for e in report.errors)


def test_a_dropped_completion_outcome_is_caught(tmp_path):
    folder = _use(tmp_path)
    path = folder / "actor-synchronous-messaging.yaml"
    doc = yaml.safe_load(path.read_text())
    doc["actions"][0]["completion_schema"] = ["task-implemented-result"]
    path.write_text(yaml.safe_dump(doc, sort_keys=False))

    report = conformance.check(folder)
    assert not report.ok
    assert any("different completion set" in e for e in report.errors)


def test_a_different_engine_is_caught(tmp_path):
    folder = _use(tmp_path)
    path = folder / "actor-synchronous-messaging.yaml"
    doc = yaml.safe_load(path.read_text())
    doc["actions"][0]["engine"] = "some-other-engine"
    path.write_text(yaml.safe_dump(doc, sort_keys=False))

    report = conformance.check(folder)
    assert not report.ok
    assert any("resolves through engine" in e for e in report.errors)


def test_prose_and_identity_are_not_compared(tmp_path):
    """A use SHOULD name its own capability and its own peers. That is not drift."""
    folder = _use(tmp_path)

    identity = folder / "actor.yaml"
    doc = yaml.safe_load(identity.read_text())
    doc["name"] = "ACME.PARTS.CAP.SUP.007.WID-implementation"
    doc["description"] = "Implements TASK-NNN cards for ACME.PARTS.CAP.SUP.007.WID."
    identity.write_text(yaml.safe_dump(doc, sort_keys=False))

    doors = folder / "actor-synchronous-messaging.yaml"
    doc = yaml.safe_load(doors.read_text())
    doc["actions"][0]["means"] = "the door for 'implement TASK-NNN for ACME.PARTS.CAP.SUP.007.WID'."
    doors.write_text(yaml.safe_dump(doc, sort_keys=False))

    assert conformance.check(folder).ok
