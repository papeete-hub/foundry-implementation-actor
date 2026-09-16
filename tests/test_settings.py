"""The session budget, as something an environment can move.

It used to be six constructor keywords that `serve` passed none of, so the only budget any actor
running from the published image could have was the one written here. These tests pin the three
things that makes true: the defaults did not change, every one of them has a variable, and a typo
is refused at boot rather than silently ignored.
"""
from __future__ import annotations

import pytest

from foundry_implementation_actor.engine import BUDGET_VARS, ClaudeCodeEngine
from foundry_implementation_actor.grounding import DEFAULT_FETCH_TIMEOUT_S
from foundry_implementation_actor.settings import ENGINE_KWARGS, ENV, Settings, SettingsError


# ── the defaults, which this pass deliberately did not retune ───────────────────────────────

def test_an_empty_environment_is_the_documented_default():
    """60 turns / 1800s to implement, 15 / 600 to assess. Making the budget movable is not the
    same act as moving it, and these are the numbers every live use is already running."""
    settings = Settings.from_env({})
    assert (settings.max_turns, settings.session_timeout_s) == (60, 1800)
    assert (settings.assess_max_turns, settings.assess_timeout_s) == (15, 600)
    assert settings.clone_timeout_s == 120
    assert settings.fetch_timeout_s == DEFAULT_FETCH_TIMEOUT_S


def test_the_assess_door_is_the_smaller_budget_by_default():
    """It reads and answers; it never writes. Smaller on every axis — see ADR-FIA-0004."""
    settings = Settings.from_env({})
    assert settings.assess_max_turns < settings.max_turns
    assert settings.assess_timeout_s < settings.session_timeout_s


# ── every field has a variable, and every variable moves its field ──────────────────────────

def test_every_field_is_reachable_from_the_environment():
    """`ENV` is the one table. A field added without an entry would raise inside `from_env`
    rather than quietly becoming unreachable, which is the failure this whole change exists to
    remove — so it is asserted here too."""
    from dataclasses import fields
    assert {f.name for f in fields(Settings)} == set(ENV) == set(ENGINE_KWARGS)


@pytest.mark.parametrize("field,variable", sorted(ENV.items()))
def test_each_variable_overrides_its_own_field(field, variable):
    settings = Settings.from_env({variable: "97"})
    assert getattr(settings, field) == 97
    # ...and nothing else moved with it.
    others = {f: getattr(settings, f) for f in ENV if f != field}
    assert others == {f: getattr(Settings(), f) for f in ENV if f != field}


def test_an_unset_or_empty_variable_leaves_the_default():
    """An empty string is what a Deployment leaves behind when someone blanks a value rather than
    deleting the `env:` entry. It means "unset", not "zero"."""
    assert Settings.from_env({"MAX_TURNS": ""}).max_turns == 60


# ── a typo fails at boot, naming itself ─────────────────────────────────────────────────────

def test_a_non_integer_is_refused_and_names_the_variable():
    with pytest.raises(SettingsError) as excinfo:
        Settings.from_env({"MAX_TURNS": "ninety"})
    assert "MAX_TURNS" in str(excinfo.value)
    assert "ninety" in str(excinfo.value)


def test_zero_and_negative_are_refused():
    """A budget of zero is not a budget; it is a door that cannot answer. Refuse it where the
    reason reaches an operator, not at the first request."""
    for value in ("0", "-1"):
        with pytest.raises(SettingsError, match="ASSESS_MAX_TURNS"):
            Settings.from_env({"ASSESS_MAX_TURNS": value})


def test_the_refusal_names_the_variable_that_was_wrong_not_the_first_one():
    with pytest.raises(SettingsError) as excinfo:
        Settings.from_env({"MAX_TURNS": "90", "ASSESS_TIMEOUT_S": "10 minutes"})
    assert "ASSESS_TIMEOUT_S" in str(excinfo.value)
    assert "MAX_TURNS" not in str(excinfo.value)


# ── what `serve` splats into the engine ─────────────────────────────────────────────────────

def test_engine_kwargs_are_the_engines_own_keywords(config, tmp_path, monkeypatch):
    """The two spellings differ — `session_timeout_s` in a Deployment, `session_timeout` in the
    constructor — so this checks the mapping against the real signature rather than a copy."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    settings = Settings.from_env({"MAX_TURNS": "90", "ASSESS_TIMEOUT_S": "300"})
    engine = ClaudeCodeEngine(config, github_token="ghs_fake", **settings.engine_kwargs())
    assert engine.max_turns == 90
    assert engine.assess_timeout == 300
    assert engine.session_timeout == 1800
    assert engine.clone_timeout == 120


# ── the failure message and the table cannot drift apart ────────────────────────────────────

def test_both_doors_name_variables_that_actually_exist():
    """`BUDGET_VARS` is what an out-of-budget failure tells an operator to set. It is keyed off
    `ENV`, and this is what keeps that true."""
    named = {name for pair in BUDGET_VARS.values() for name in pair}
    assert named <= set(ENV.values())
    assert BUDGET_VARS["implement-task"] == ("MAX_TURNS", "SESSION_TIMEOUT_S")
    assert BUDGET_VARS["assess-task"] == ("ASSESS_MAX_TURNS", "ASSESS_TIMEOUT_S")
