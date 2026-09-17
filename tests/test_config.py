"""The derivations, and the gate.

The first test in this file is the reason `config.py` exists: eight renderings of one capability
id, each of which used to be a separate literal typed by hand in one of two modules.
"""
from __future__ import annotations

import pytest

from foundry_implementation_actor.config import (
    CONTRACT, CapabilityConfig, ConfigError, lint,
)

from conftest import CAPABILITY, SOURCE_REPO


# ── the eight renderings ────────────────────────────────────────────────────────────────────

def test_all_eight_renderings_derive_from_two_fields(config):
    assert config.capability == CAPABILITY
    assert config.source_repo == SOURCE_REPO
    assert config.capability_path == "acme.parts/sup.007.wid"
    assert config.image_name("backend") == "acme.parts.cap.sup.007.wid-backend"
    assert config.clone_prefix("TASK-042") == \
        "acme-parts-cap-sup-007-wid-implementation-TASK-042-"
    assert config.git_author_name == "ACME.PARTS.CAP.SUP.007.WID-implementation"
    assert config.git_author_email == \
        "acme-parts-cap-sup-007-wid-implementation@users.noreply.github.com"
    assert config.image_ref("reg.example.com", "backend", "1.2.3-task-042-abc1234") == \
        "reg.example.com/acme.parts/sup.007.wid/backend:1.2.3-task-042-abc1234"


def test_image_ref_is_the_three_way_contract(config):
    """`<registry>/<capability path>/<component>:<version>` — nothing else, in that order.

    Two actors this package never imports recompute this string and parse it back apart. It is
    derivation output or nothing; a tag scheme invented here would break both of them silently,
    because a wrong ref still pushes.
    """
    ref = config.image_ref("reg.example.com/ns", "stub", "0.1.0-x-deadbee")
    registry, _, rest = ref.partition(f"/{config.capability_path}/")
    component, _, version = rest.partition(":")
    assert registry == "reg.example.com/ns"
    assert component == "stub"
    assert version == "0.1.0-x-deadbee"


def test_trailing_slash_on_the_registry_is_absorbed(config):
    assert config.image_ref("reg.example.com/", "stub", "v") == \
        config.image_ref("reg.example.com", "stub", "v")


def test_capability_path_drops_only_the_cap_segment(sidecar_dict, write_sidecar):
    sidecar_dict["capability"] = "ZZ.YY.CAP.AA.001.BB"
    sidecar_dict["source_repo"] = "org/ZZ.YY.CAP.AA.001.BB-implementation"
    config = CapabilityConfig.load(write_sidecar(sidecar_dict))
    assert config.capability_path == "zz.yy/aa.001.bb"
    # Every token survives — nothing is shortened or abbreviated, only re-jointed.
    assert set("zz.yy/aa.001.bb".replace("/", ".").split(".")) == \
        set(config.capability.lower().split(".")) - {"cap"}


def test_capability_without_a_cap_segment_is_refused(sidecar_dict, write_sidecar):
    sidecar_dict["capability"] = "ACME.PARTS.SUP.007.WID"
    with pytest.raises(ConfigError, match="no 'CAP' segment"):
        CapabilityConfig.load(write_sidecar(sidecar_dict))


def test_capability_with_nothing_after_cap_is_refused(sidecar_dict, write_sidecar):
    sidecar_dict["capability"] = "ACME.PARTS.CAP"
    with pytest.raises(ConfigError, match="right of"):
        CapabilityConfig.load(write_sidecar(sidecar_dict))


# ── the write boundary, derived rather than declared ────────────────────────────────────────

def test_writes_only_under_is_the_components(config):
    assert config.writes_only_under == ("backend/", "stub/")


def test_a_sidecar_still_declaring_tests_is_conformant(sidecar_dict, write_sidecar):
    """`tests:` was removed from the contract as a LOOSENING of v1, not a new contract
    (ADR-FIA-0002). Nothing here rejects unknown keys, so every sidecar written against the
    earlier v1 keeps loading and keeps linting green, unedited — which is the whole reason the
    contract string did not have to change. A strict-mode check added later would break that
    silently, in every consuming repo at once, so it is pinned here rather than assumed."""
    for component in sidecar_dict["components"]:
        component["tests"] = f"{component['path']}tests/"
    folder = write_sidecar(sidecar_dict)

    config = CapabilityConfig.load(folder)
    assert config.writes_only_under == ("backend/", "stub/")
    assert not hasattr(config.components[0], "tests")
    assert lint(folder).ok


def test_a_component_path_must_end_in_a_slash(sidecar_dict, write_sidecar):
    """`stub` without the slash would also claim `stubborn-notes.md` — containment is a prefix
    test, so the slash is load-bearing rather than cosmetic."""
    sidecar_dict["components"][1]["path"] = "stub"
    with pytest.raises(ConfigError, match="must end in '/'"):
        CapabilityConfig.load(write_sidecar(sidecar_dict))


# ── component discovery, including the depth-2 case the old shortcut got wrong ──────────────

def test_component_for_resolves_by_longest_prefix(sidecar_dict, write_sidecar):
    sidecar_dict["components"] = [
        {"name": "core", "path": "src/", "dockerfile": "src/deploy"},
        {"name": "gateway", "path": "src/gateway/", "dockerfile": "src/gateway/deploy"},
    ]
    config = CapabilityConfig.load(write_sidecar(sidecar_dict))
    # The first-segment shortcut would call both of these "src".
    assert config.component_for("src/thing.py").name == "core"
    assert config.component_for("src/gateway/thing.py").name == "gateway"
    assert config.components_for(["src/a.py", "src/gateway/b.py"]) == ["core", "gateway"]


def test_component_for_returns_none_outside_every_root(config):
    assert config.component_for("docs/readme.md") is None
    assert config.components_for(["docs/readme.md"]) == []


# ── placeholder expansion ───────────────────────────────────────────────────────────────────

def test_fetch_placeholders_expand(config):
    argv = config.expand(config.ground_in[0].fetch)
    assert argv == ["kpack", "pack", CAPABILITY, "--deep", "--compact",
                    "--registry-repo", "acme-lab/acme-governance"]


def test_a_typod_placeholder_is_refused(config):
    """A leftover `{bare_word}` is what a typo looks like; passing it through would hand a
    knowledge tool a literal `{registryrepo}` to fail on far from here."""
    with pytest.raises(ConfigError, match="placeholder"):
        config.expand(["tool", "{registryrepo}"])


def test_braces_in_a_fetch_argv_survive_expansion(config):
    """A fetch argv is somebody else's command line, and braces are ordinary characters in one.
    `str.format` would have raised on both of these."""
    assert config.expand(["jq", "{name: .capability}"]) == ["jq", "{name: .capability}"]
    assert config.expand(["tool", '--json', '{"a": 1}']) == ["tool", "--json", '{"a": 1}']


def test_a_placeholder_inside_a_larger_argument_is_still_substituted(config):
    assert config.expand(["--repo={source_repo}"]) == [f"--repo={config.source_repo}"]


def test_there_is_no_default_registry_repo(sidecar_dict, write_sidecar):
    """A fetch that silently reaches a fallback registry is worse than one that fails."""
    del sidecar_dict["registry_repo"]
    with pytest.raises(ConfigError, match="registry_repo"):
        CapabilityConfig.load(write_sidecar(sidecar_dict))


# ── the gate ────────────────────────────────────────────────────────────────────────────────

def test_lint_accepts_the_fixture(config, tmp_path):
    report = lint(tmp_path)
    assert report.ok, report.errors
    assert any(CONTRACT in line for line in report.oks)


def test_lint_warns_and_stops_on_an_unmigrated_sidecar(sidecar_dict, write_sidecar):
    sidecar_dict["context"] = "something-else/agentic-context/v0"
    report = lint(write_sidecar(sidecar_dict))
    assert report.ok                      # UNMIGRATED is not non-conformant
    assert any("UNMIGRATED" in w for w in report.warns)


def test_lint_warns_when_nothing_is_eager(sidecar_dict, write_sidecar):
    for entry in sidecar_dict["ground_in"]:
        entry["load"] = "on-demand"
    report = lint(write_sidecar(sidecar_dict))
    assert report.ok
    assert any("no `load: eager`" in w for w in report.warns)


def test_lint_reports_a_missing_file(tmp_path):
    report = lint(tmp_path / "nowhere")
    assert not report.ok
    assert "no such file" in report.errors[0]


def test_an_into_path_may_not_escape_the_clone(sidecar_dict, write_sidecar):
    sidecar_dict["ground_in"][0]["into"] = "../outside.md"
    with pytest.raises(ConfigError, match="inside the clone"):
        CapabilityConfig.load(write_sidecar(sidecar_dict))


def test_fetch_must_be_argv_not_a_shell_string(sidecar_dict, write_sidecar):
    sidecar_dict["ground_in"][0]["fetch"] = "kpack pack {capability}"
    with pytest.raises(ConfigError, match="list of strings"):
        CapabilityConfig.load(write_sidecar(sidecar_dict))


def test_an_unknown_load_tier_is_refused(sidecar_dict, write_sidecar):
    sidecar_dict["ground_in"][0]["load"] = "sometimes"
    with pytest.raises(ConfigError, match="eager, on-demand"):
        CapabilityConfig.load(write_sidecar(sidecar_dict))


def test_components_may_not_be_empty(sidecar_dict, write_sidecar):
    sidecar_dict["components"] = []
    with pytest.raises(ConfigError, match="empty"):
        CapabilityConfig.load(write_sidecar(sidecar_dict))


# ── identity: capability + role, not the repo half ──────────────────────────────────────────

def test_the_actor_name_is_exactly_what_the_repo_half_used_to_be(config):
    """The no-op half of the change, pinned.

    `actor_name` was `source_repo.partition("/")[2]`. It is `{capability}-{ROLE}` now. Every
    sidecar that exists satisfies `source_repo == "<owner>/" + capability + "-" + ROLE`, so the
    two derivations agree on all of them — which is what makes this releasable on its own, ahead
    of any repository moving.
    """
    assert config.source_repo == f"acme-lab/{config.capability}-implementation"
    assert config.actor_name == config.source_repo.partition("/")[2]
    assert config.actor_name == "ACME.PARTS.CAP.SUP.007.WID-implementation"


def test_the_actor_name_no_longer_follows_the_repository(sidecar_dict, write_sidecar):
    """The point of the change: three actors in one repository still have three names.

    A consolidated capability repository is named for the capability alone, with no role suffix,
    because all three of its actors live in it. Under the old derivation this actor would have
    been called `ACME.PARTS.CAP.SUP.007.WID` — and so would both of its siblings.
    """
    sidecar_dict["source_repo"] = "acme-lab/ACME.PARTS.CAP.SUP.007.WID"
    config = CapabilityConfig.load(write_sidecar(sidecar_dict))
    assert config.actor_name == "ACME.PARTS.CAP.SUP.007.WID-implementation"
    assert config.git_author_name == config.actor_name
    assert config.actor_slug == "acme-parts-cap-sup-007-wid-implementation"
    assert config.clone_prefix("TASK-042") == \
        "acme-parts-cap-sup-007-wid-implementation-TASK-042-"


def test_a_malformed_source_repo_is_still_refused(sidecar_dict, write_sidecar):
    """`actor_name` used to validate this shape on its way past, and nothing else did.

    `source_repo` is still what every clone and push URL is built from, so a `source_repo` that
    is not `<owner>/<repo>` has to keep failing at load rather than at the first push.
    """
    sidecar_dict["source_repo"] = "just-a-name"
    with pytest.raises(ConfigError, match="<owner>/<repo>"):
        CapabilityConfig.load(write_sidecar(sidecar_dict))
