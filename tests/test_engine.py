"""The engine — the port it satisfies, the prompt it builds, and the log budget it holds.

Nothing here starts a `claude` session. What is worth pinning without one is the shape of what
surrounds it: that this class is still an `Engine`, that its prompt is derived rather than
hardcoded, and that no line it emits can exceed the budget Loki rejects outright.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from papeete_actor_synchronous_messaging.engine import Engine, EngineError

from foundry_implementation_actor.engine import (
    ASSESS_TOOLS, IMPLEMENT_TOOLS, LINE_BUDGET, ClaudeCodeEngine, _door_from_prompt,
    _extract_json, _line, _payload_from_prompt, _project,
)

PAYLOAD = {
    "task_id": "TASK-042",
    "title": "Supply the widget",
    "context": "Some background.",
    "definition_of_done": ["tests pass", "the event is published"],
}

# What the testing actor proposes at the assess door, before anything is built. The `id` is the
# load-bearing part: a later verdict names it, so a failure points at an agreed expectation rather
# than at a scraped line of pytest output.
SURFACE = [
    {"id": "EXP-001",
     "statement": "GET /widgets/{widget_id} returns 200 with an ETag",
     "handle": {"component": "backend", "base_url_env": "BACKEND_URL",
                "method": "GET", "path": "/widgets/{widget_id}"}},
    {"id": "EXP-002",
     "statement": "three widgets are pre-seeded, addressable by stable ids",
     "handle": {"component": "stub", "base_url_env": "STUB_URL"}},
]


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

def test_the_prompt_names_the_derived_boundary(engine):
    prompt = engine._situational_prompt(PAYLOAD)
    assert "backend/, stub/" in prompt
    assert "TASK-042" in prompt
    assert "Supply the widget" in prompt


def test_the_prompt_says_nothing_about_a_test_suite(engine):
    """This actor does a developer's work: it may write and run unit tests inside its session as
    any developer would, following the repo it is in. It is not TOLD to, and no test-tree path is
    ever named to it — testing is another actor's contract (ADR-FIA-0002). The prompt used to
    interpolate `components[].tests` here, which is the field that decision removed."""
    prompt = engine._situational_prompt(PAYLOAD)
    assert "tests/" not in prompt
    assert "test suite" not in prompt


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


# ── two doors, one engine ───────────────────────────────────────────────────────────────────

def test_the_door_is_recovered_from_the_framework_prompt():
    """The `Engine` port is one `judge()`, and both doors name the same engine key. The door id
    `Actor.judge()` already puts on line 2 is what tells them apart — nothing extra is needed
    from the framework."""
    assert _door_from_prompt("verb: query\ndoor: assess-task\n{}") == "assess-task"
    assert _door_from_prompt("verb: request\ndoor: implement-task\n{}") == "implement-task"


def test_a_prompt_naming_no_door_is_an_engine_error():
    with pytest.raises(EngineError, match="fixed format"):
        _door_from_prompt("verb: request\nnot-a-door\n{}")


def test_a_door_this_engine_does_not_answer_is_refused(engine):
    """A third door naming `claude-code` would otherwise be judged by whichever branch fell
    through. It is named and refused instead."""
    prompt = "verb: request\ndoor: deploy-task\n" + json.dumps({"payload": PAYLOAD})
    with pytest.raises(EngineError, match="deploy-task"):
        engine.judge(system="s", prompt=prompt)


# ── the assessment prompt ───────────────────────────────────────────────────────────────────

def test_the_assessment_prompt_carries_the_proposed_surface(engine):
    prompt = engine._assessment_prompt({**PAYLOAD, "acceptance_surface": SURFACE}, None)
    assert "EXP-001" in prompt and "EXP-002" in prompt
    assert "BACKEND_URL" in prompt
    assert "backend/, stub/" in prompt            # the derived boundary, not a literal
    assert "TASK-042" in prompt


def test_the_assessment_prompt_asks_for_a_commitment_not_a_report(engine):
    """The distinction the whole round rests on. Nothing is built yet, so a value named here is a
    promise; the same value named afterwards would be a description of what was found."""
    prompt = engine._assessment_prompt({**PAYLOAD, "acceptance_surface": SURFACE}, None)
    assert "NOTHING HAS BEEN BUILT YET" in prompt
    assert "COMMIT to the exact value now" in prompt


def test_the_assessment_prompt_never_asks_for_a_change(engine):
    prompt = engine._assessment_prompt({**PAYLOAD, "acceptance_surface": SURFACE}, None)
    assert "READING ONLY" in prompt
    for forbidden in ("git add", "git commit", "git push", "Write ONLY under"):
        assert forbidden not in prompt


def test_the_answers_shape_is_the_cards_own_when_one_is_given(engine):
    """`Actor.judge()` derives it from the door's `completion_schema` and hands it over. Rendering
    that is how the prompt and the card cannot come to disagree."""
    schema = {"properties": {"feasible": {"type": "boolean"}}, "required": ["feasible"]}
    assert json.dumps(schema, indent=2) in engine._assessment_prompt(PAYLOAD, schema)

    without = engine._assessment_prompt(PAYLOAD, None)
    assert "`feasible` (boolean)" in without


def test_every_entry_is_keyed_by_the_expectation_it_is_about(engine):
    """A live assess session answered commitments as prose strings ("E1: …", "E4/E5: …"), which
    the orchestrating actor could not attach to anything. The card types the lists and no more,
    so the shape is said in words — with a schema rendered and without."""
    schema = {"properties": {"feasible": {"type": "boolean"}}, "required": ["feasible"]}
    for prompt in (engine._assessment_prompt(PAYLOAD, schema),
                   engine._assessment_prompt(PAYLOAD, None)):
        assert '`{"id": "<expectation id>", "commitment":' in prompt
        assert '`{"id": "<expectation id>", "reason":' in prompt
        assert "never a bare string" in prompt


def test_an_empty_surface_is_said_out_loud(engine):
    """A caller that proposed nothing gets asked what it expected, rather than a bare yes."""
    assert "empty" in engine._assessment_prompt(PAYLOAD, None)


# ── the agreed surface reaching the implement door ──────────────────────────────────────────

def test_the_implement_prompt_carries_an_agreed_surface_only_when_given(engine):
    assert "## Agreed acceptance surface" not in engine._situational_prompt(PAYLOAD)

    prompt = engine._situational_prompt({**PAYLOAD, "acceptance_surface": SURFACE})
    assert "## Agreed acceptance surface" in prompt
    assert "EXP-001" in prompt
    # It is more specific than the definition of done, and has to win where they differ.
    assert "it wins" in prompt


# ── reading the judgement back out of a session's prose ─────────────────────────────────────

def test_a_fenced_json_answer_is_read():
    assert _extract_json('Here is what I found.\n```json\n{"feasible": true}\n```') == {
        "feasible": True}


def test_a_bare_fence_is_read_too():
    assert _extract_json('```\n{"feasible": false}\n```') == {"feasible": False}


def test_the_last_fence_wins():
    """A session usually quotes the shape it was asked for before answering in it. The conclusion
    is the last block, not the first."""
    text = ('```json\n{"feasible": "the shape I was given"}\n```\n'
            'and my actual answer:\n```json\n{"feasible": true, "objections": []}\n```')
    assert _extract_json(text) == {"feasible": True, "objections": []}


def test_an_answer_with_no_json_is_an_engine_error():
    with pytest.raises(EngineError, match="no JSON object"):
        _extract_json("I think it is probably fine, yes.")


def test_a_malformed_fence_falls_through_to_an_engine_error():
    with pytest.raises(EngineError, match="no JSON object"):
        _extract_json('```json\n{"feasible": tru\n```')


# ── the assess door end to end, without a session ───────────────────────────────────────────

@pytest.fixture
def assessed(engine, monkeypatch):
    """Drive `_assess` with the three things that need a network stubbed out, and record how the
    session was invoked."""
    seen = {}

    def _fake_invoke(clone_dir, system, prompt, **kwargs):
        seen.update(kwargs, clone_dir=clone_dir, system=system, prompt=prompt)
        return seen["answer"]

    monkeypatch.setattr(engine, "_clone", lambda dest: dest.mkdir(exist_ok=True))
    monkeypatch.setattr(engine, "_ground", lambda clone_dir: None)
    monkeypatch.setattr(engine, "_invoke_claude", _fake_invoke)

    def _run(answer):
        seen["answer"] = answer
        return engine._assess({**PAYLOAD, "acceptance_surface": SURFACE}, None), seen
    _run.seen = seen
    return _run


def test_the_assess_session_is_given_no_tool_that_writes(assessed):
    _, seen = assessed('```json\n{"feasible": true}\n```')
    assert seen["allowed_tools"] == ASSESS_TOOLS
    assert "Write" not in ASSESS_TOOLS and "Edit" not in ASSESS_TOOLS
    assert "Bash" not in ASSESS_TOOLS
    assert IMPLEMENT_TOOLS != ASSESS_TOOLS


FAKE_CLAUDE = """
import json, sys
open(sys.argv[0] + ".argv", "w").write(json.dumps(sys.argv[1:]))
print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "done"}))
"""


def test_the_tool_list_removes_tools_rather_than_only_approving_some(config, tmp_path,
                                                                    monkeypatch):
    """`--allowedTools` only pre-approves what it names; every other built-in stays available,
    and a live assess session reached for Bash through it. `--tools` is what takes the rest
    away, so it has to carry the same list — and, being variadic, never sit last."""
    script = tmp_path / "claude"
    script.write_text(f"#!{sys.executable}\n{FAKE_CLAUDE}")
    script.chmod(0o755)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    engine = ClaudeCodeEngine(config, github_token="ghs_fake", claude_bin=str(script))

    assert engine._invoke_claude(tmp_path, "system", "THE PROMPT",
                                 allowed_tools=ASSESS_TOOLS) == "done"
    argv = json.loads((tmp_path / "claude.argv").read_text())

    assert argv[argv.index("--tools") + 1] == ASSESS_TOOLS
    assert argv[argv.index("--allowedTools") + 1] == ASSESS_TOOLS
    assert argv[-1] == "THE PROMPT"
    assert argv[argv.index("--tools") + 2].startswith("--")


def test_the_assess_session_gets_a_smaller_budget(assessed, engine):
    _, seen = assessed('```json\n{"feasible": true}\n```')
    assert seen["max_turns"] == engine.assess_max_turns < engine.max_turns
    assert seen["timeout"] == engine.assess_timeout < engine.session_timeout


def test_the_assess_door_removes_its_own_clone_on_success(assessed):
    """`_implement` hands its clone off live for the handler to commit from. This door has no
    handler and produces no artifact, so the cleanup is unconditional."""
    _, seen = assessed('```json\n{"feasible": true}\n```')
    assert not Path(seen["clone_dir"]).exists()


def test_the_assess_door_removes_its_own_clone_on_failure(assessed):
    """The `finally` is what makes this true on both paths — the session ran, so the clone
    existed, and the answer was unreadable."""
    with pytest.raises(EngineError):
        assessed("no json here")
    assert not Path(assessed.seen["clone_dir"]).exists()


def test_the_judgement_comes_back_as_the_reply(assessed):
    judged, _ = assessed(
        '```json\n{"feasible": false, "objections": [{"id": "EXP-002", "why": "no such component"}]}\n```')
    assert judged["feasible"] is False
    assert judged["objections"][0]["id"] == "EXP-002"


def test_a_stringly_typed_feasible_is_coerced(assessed):
    """`Actor.receive()` validates the reply against the door's completion schema and would refuse
    the whole thing over a "true" that is a string. A session means the boolean and types it
    however it likes."""
    judged, _ = assessed('```json\n{"feasible": "true"}\n```')
    assert judged["feasible"] is True


def test_an_assessment_that_answers_nothing_is_an_engine_error(assessed):
    with pytest.raises(EngineError, match="feasible"):
        assessed('```json\n{"objections": []}\n```')


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
