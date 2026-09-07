"""Grounding — the fetch, the envelope, and the CLAUDE.md that makes it a precondition."""
from __future__ import annotations

import json
import sys

import pytest
from papeete_actor_synchronous_messaging.engine import EngineError

from foundry_implementation_actor import grounding
from foundry_implementation_actor.config import CapabilityConfig

ENVELOPE = {"capability": "ACME.PARTS.CAP.SUP.007.WID", "events": ["WidgetSupplied"]}


_CAT = "import sys; sys.stdout.write(open(sys.argv[1]).read())"


@pytest.fixture
def local_config(sidecar_dict, write_sidecar, tmp_path):
    """The fixture sidecar with both fetches replaced by a local read of a fixed payload.

    No tool installed, no network, and no braces in the argv — see `test_braces_in_a_fetch_argv`
    for why that last one is checked separately rather than relied on here.
    """
    payload = tmp_path / "envelope.json"
    payload.write_text(json.dumps(ENVELOPE))
    for entry in sidecar_dict["ground_in"]:
        entry["fetch"] = [sys.executable, "-c", _CAT, str(payload)]
    return CapabilityConfig.load(write_sidecar(sidecar_dict, tmp_path / "cfg"))


# ── fetch ───────────────────────────────────────────────────────────────────────────────────

def test_fetch_returns_the_tools_stdout(local_config):
    out = grounding.fetch(local_config, local_config.ground_in[0])
    assert json.loads(out) == ENVELOPE


def test_a_missing_tool_is_an_engine_error_naming_it(sidecar_dict, write_sidecar):
    sidecar_dict["ground_in"][0]["fetch"] = ["definitely-not-a-real-binary", "x"]
    config = CapabilityConfig.load(write_sidecar(sidecar_dict))
    with pytest.raises(EngineError, match="definitely-not-a-real-binary"):
        grounding.fetch(config, config.ground_in[0])


def test_a_failing_tool_is_an_engine_error(sidecar_dict, write_sidecar):
    sidecar_dict["ground_in"][0]["fetch"] = [
        sys.executable, "-c", "import sys; sys.stderr.write('registry unreachable'); sys.exit(3)"]
    config = CapabilityConfig.load(write_sidecar(sidecar_dict))
    with pytest.raises(EngineError, match="registry unreachable"):
        grounding.fetch(config, config.ground_in[0])


def test_a_hanging_tool_is_an_engine_error(sidecar_dict, write_sidecar):
    sidecar_dict["ground_in"][0]["fetch"] = [sys.executable, "-c", "import time; time.sleep(30)"]
    config = CapabilityConfig.load(write_sidecar(sidecar_dict))
    with pytest.raises(EngineError, match="timed out"):
        grounding.fetch(config, config.ground_in[0], timeout=1)


# ── the envelope, written inside the clone ──────────────────────────────────────────────────

def test_the_envelope_lands_inside_the_clone_as_markdown(local_config, tmp_path):
    clone = tmp_path / "clone"
    clone.mkdir()
    entry = local_config.ground_in[0]
    path = grounding.write_envelope(local_config, entry, clone, json.dumps(ENVELOPE))

    assert path == clone / ".foundry" / "business.md"
    text = path.read_text()
    assert text.startswith("# business\n")
    assert entry.answers in text
    assert "```json" in text
    # The provenance line shows the argv AS RUN, placeholders substituted — an unexpanded
    # `{capability}` there would tell a reader the session was grounded by a command nobody ran.
    assert "{capability}" not in text
    assert local_config.capability in text
    # The payload survives the wrapping untouched — pretty-printing is a convenience, not an edit.
    fenced = text.split("```json\n", 1)[1].rsplit("\n```", 1)[0]
    assert json.loads(fenced) == ENVELOPE


def test_a_non_json_envelope_passes_through_unreformatted(local_config, tmp_path):
    clone = tmp_path / "clone"
    clone.mkdir()
    path = grounding.write_envelope(local_config, local_config.ground_in[0], clone,
                                    "# not json\n\nprose")
    assert "# not json" in path.read_text()


# ── CLAUDE.md ───────────────────────────────────────────────────────────────────────────────

def test_eager_entries_are_imported_and_on_demand_ones_are_only_listed(local_config, tmp_path):
    clone = tmp_path / "clone"
    clone.mkdir()
    grounding.render_claude_md(local_config, clone)
    text = (clone / "CLAUDE.md").read_text()

    # business is eager → an @-import, which the CLI resolves before turn one.
    assert "@.foundry/business.md" in text
    # process is on-demand → named and located, but not imported.
    assert "@.foundry/process.md" not in text
    assert ".foundry/process.md" in text
    assert local_config.ground_in[1].answers in text


def test_the_boundary_is_stated_in_the_generated_file(local_config, tmp_path):
    clone = tmp_path / "clone"
    clone.mkdir()
    grounding.render_claude_md(local_config, clone)
    text = (clone / "CLAUDE.md").read_text()
    assert "backend/, stub/" in text
    assert local_config.capability in text


def test_an_existing_claude_md_is_appended_to_never_clobbered(local_config, tmp_path):
    """The capability repo has no CLAUDE.md today — which is exactly why this must be right
    before it has one. A repo's own standing guidance is the last thing to silently replace."""
    clone = tmp_path / "clone"
    clone.mkdir()
    (clone / "CLAUDE.md").write_text("# House rules\n\nAlways run the linter.\n")

    grounding.render_claude_md(local_config, clone)
    text = (clone / "CLAUDE.md").read_text()

    assert text.startswith("# House rules")
    assert "Always run the linter." in text
    assert "@.foundry/business.md" in text
    assert text.index("House rules") < text.index("@.foundry/business.md")


def test_ground_runs_every_fetch_and_renders_once(local_config, tmp_path):
    clone = tmp_path / "clone"
    clone.mkdir()
    entries = grounding.ground(local_config, clone)

    assert [e.name for e in entries] == ["business", "process"]
    assert (clone / ".foundry" / "business.md").exists()
    assert (clone / ".foundry" / "process.md").exists()
    assert (clone / "CLAUDE.md").exists()


def test_every_eager_import_resolves_to_a_file_that_exists(local_config, tmp_path):
    """The property the release probe asserts: an `@`-import naming a file that isn't there is a
    session grounded in nothing, and it looks identical to one grounded correctly."""
    clone = tmp_path / "clone"
    clone.mkdir()
    grounding.ground(local_config, clone)

    imports = [line[1:].strip() for line in (clone / "CLAUDE.md").read_text().splitlines()
               if line.startswith("@")]
    assert imports, "no eager import was rendered"
    for target in imports:
        assert (clone / target).is_file(), f"@{target} does not resolve"
