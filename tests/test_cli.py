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


def test_serve_refuses_a_budget_it_cannot_read(config, tmp_path, monkeypatch, capsys):
    """A misspelt budget is a misconfiguration an operator has just made and is watching for. One
    line naming the variable reads better in a pod's log than the traceback under it."""
    import importlib
    # `foundry_implementation_actor.serve` is the FUNCTION on the package — the module is only
    # reachable by name.
    serve_module = importlib.import_module("foundry_implementation_actor.serve")
    # The wire half is an extra this suite does not install, and it is imported before anything
    # this test is about. Stand it down; the boot then reaches the budget, which is the point.
    monkeypatch.setattr(serve_module, "_imports",
                        lambda: (object(), object(), lambda: None))
    monkeypatch.setenv("MAX_TURNS", "ninety")
    assert cli.main(["serve", str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "FAIL" in err
    assert "MAX_TURNS" in err and "ninety" in err


def test_the_cli_needs_a_subcommand(capsys):
    with pytest.raises(SystemExit):
        cli.main([])
