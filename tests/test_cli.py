"""The CLI — the gate CI runs, and the derivation table an operator reads."""
from __future__ import annotations

import pytest

from foundry_implementation_actor import cli


def test_lint_passes_on_a_conformant_sidecar(config, tmp_path, capsys):
    assert cli.main(["lint", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "conforms" in out


def test_lint_fails_on_a_missing_sidecar(tmp_path, capsys):
    assert cli.main(["lint", str(tmp_path / "nowhere")]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_lint_fails_on_a_broken_sidecar(sidecar_dict, write_sidecar, capsys):
    del sidecar_dict["components"]
    folder = write_sidecar(sidecar_dict)
    assert cli.main(["lint", str(folder)]) == 1
    assert "components" in capsys.readouterr().out


def test_show_prints_every_derived_rendering(config, tmp_path, capsys):
    assert cli.main(["show", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert config.capability_path in out
    assert config.git_author_email in out
    assert config.clone_prefix("TASK-NNN") in out
    assert config.image_name("backend") in out
    assert "backend/, stub/" in out


def test_show_renders_the_image_ref_against_a_given_registry(config, tmp_path, capsys):
    assert cli.main(["show", str(tmp_path), "--registry", "reg.example.com"]) == 0
    out = capsys.readouterr().out
    assert "reg.example.com/acme.parts/sup.007.wid/backend:<version>" in out


def test_show_expands_the_fetch_argv(config, tmp_path, capsys):
    assert cli.main(["show", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert config.capability in out
    assert config.registry_repo in out
    assert "{capability}" not in out


def test_the_cli_needs_a_subcommand(capsys):
    with pytest.raises(SystemExit):
        cli.main([])
