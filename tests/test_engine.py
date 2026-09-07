"""The engine — the port it satisfies, the prompt it builds, and the log budget it holds.

Nothing here starts a `claude` session. What is worth pinning without one is the shape of what
surrounds it: that this class is still an `Engine`, that its prompt is derived rather than
hardcoded, and that no line it emits can exceed the budget Loki rejects outright.
"""
from __future__ import annotations

import json

import pytest
from papeete_actor_synchronous_messaging.engine import Engine, EngineError

from foundry_implementation_actor.engine import (
    LINE_BUDGET, ClaudeCodeEngine, _line, _payload_from_prompt, _project,
)

PAYLOAD = {
    "task_id": "TASK-042",
    "title": "Supply the widget",
    "context": "Some background.",
    "definition_of_done": ["tests pass", "the event is published"],
}


@pytest.fixture
def engine(config, tmp_path, monkeypatch):
    # `_configure_git_credentials` writes a global git config. Point it at a throwaway file so a
    # test run never touches the developer's own — the rewrite it installs carries a token.
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    return ClaudeCodeEngine(config, github_token="ghs_fake")


# ── the port ────────────────────────────────────────────────────────────────────────────────

def test_it_is_an_engine(engine):
    assert isinstance(engine, Engine)


def test_its_name_comes_from_the_sidecar(engine, config):
    """The card's door names the engine; the port requires the attribute, not a fixed value."""
    assert engine.name == config.engine == "claude-code"


def test_it_refuses_to_start_without_a_token(config, tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="GITHUB_TOKEN"):
        ClaudeCodeEngine(config)


def test_the_token_error_names_the_repos_it_needs(config, tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(RuntimeError) as excinfo:
        ClaudeCodeEngine(config)
    assert config.source_repo in str(excinfo.value)
    assert config.registry_repo in str(excinfo.value)


# ── the prompt ──────────────────────────────────────────────────────────────────────────────

def test_the_prompt_names_the_derived_boundary_and_test_suites(engine):
    prompt = engine._situational_prompt(PAYLOAD)
    assert "backend/, stub/" in prompt
    assert "backend/tests/, stub/tests/" in prompt
    assert "TASK-042" in prompt
    assert "Supply the widget" in prompt


def test_the_prompt_no_longer_asks_the_session_to_go_and_read_its_context(engine):
    """Grounding is a precondition now — the generated CLAUDE.md is loaded before turn one. Asking
    again would spend a turn on something already done."""
    prompt = engine._situational_prompt(PAYLOAD)
    assert "read it before you start" not in prompt
    assert "business.json" not in prompt
    assert "process.json" not in prompt


def test_optional_sections_appear_only_when_supplied(engine):
    bare = dict(PAYLOAD)
    del bare["context"]
    prompt = engine._situational_prompt(bare)
    assert "## Context" not in prompt
    assert "## Remediation" not in prompt

    with_remediation = {**PAYLOAD, "remediation_context": "assert_widget_supplied failed"}
    prompt = engine._situational_prompt(with_remediation)
    assert "## Remediation" in prompt
    assert "assert_widget_supplied failed" in prompt


# ── recovering the payload from Actor.judge()'s fixed prompt format ──────────────────────────

def test_the_payload_is_recovered_from_the_framework_prompt():
    prompt = ("verb: request\ndoor: implement-task\n"
              + json.dumps({"payload": PAYLOAD}))
    assert _payload_from_prompt(prompt) == PAYLOAD


def test_a_prompt_in_another_shape_is_an_engine_error():
    with pytest.raises(EngineError, match="fixed format"):
        _payload_from_prompt("just one line")


def test_a_prompt_with_no_payload_is_an_engine_error():
    with pytest.raises(EngineError, match="could not recover"):
        _payload_from_prompt("verb: request\ndoor: implement-task\n{}")


# ── the log budget ──────────────────────────────────────────────────────────────────────────

def test_a_huge_tool_result_is_clipped_not_dropped():
    event = {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": "x" * 500_000}]}}
    record = _project(event)
    assert record["blocks"][0]["tool_result"] == "t1"
    assert "clipped" in record["blocks"][0]["content"]


def test_no_emitted_line_can_exceed_the_budget():
    """Loki rejects an oversized line outright rather than truncating it, so a single large Read
    would silently delete exactly the turn worth reading. Per-field clipping keeps lines small;
    this is what makes it a property rather than a hope."""
    many_keys = {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Write", "id": "t1",
         "input": {f"k{i}": "y" * 3_000 for i in range(100)}}]}}
    line = _line(_project(many_keys))
    assert len(line.encode("utf-8")) <= LINE_BUDGET


def test_events_with_no_audit_value_are_dropped():
    assert _project({"type": "rate_limit_event"}) is None
    assert _project({"type": "assistant", "message": {"content": []}}) is None


def test_the_result_event_keeps_the_fields_the_dashboard_reads():
    record = _project({"type": "result", "subtype": "success", "is_error": False,
                       "num_turns": 3, "duration_ms": 1234, "total_cost_usd": 0.5,
                       "usage": {"input_tokens": 10, "output_tokens": 20}, "result": "done"})
    assert record["event"] == "result"
    assert record["cost_usd"] == 0.5
    assert record["input_tokens"] == 10
    assert record["output_tokens"] == 20
