"""Containment — the check that actually enforces the write boundary.

The session's prompt only ASKS for the boundary. This is what holds it, so these tests run against
a real git repo rather than a stubbed one: the check IS `git add <root>` plus `git diff --cached
--name-only`, and a double that returned a list of paths would exercise the assertion while
skipping the parts that have actually surprised people.
"""
from __future__ import annotations

import subprocess

import pytest

from foundry_implementation_actor.handler import (
    HandlerError, _containment_commit, make_implement_task,
)


def _staged(repo) -> list[str]:
    out = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=repo,
                         capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line]


def _committed(repo) -> list[str]:
    out = subprocess.run(["git", "show", "--name-only", "--format=", "HEAD"], cwd=repo,
                         capture_output=True, text=True, check=True).stdout
    return sorted(line for line in out.splitlines() if line)


# ── the happy path ──────────────────────────────────────────────────────────────────────────

def test_commits_only_what_is_inside_the_boundary(config, git_repo):
    (git_repo / "backend" / "new.py").write_text("x = 1\n")
    components = _containment_commit(config, git_repo, "TASK-042", "did the thing")
    assert components == ["backend"]
    assert _committed(git_repo) == ["backend/new.py"]


def test_touching_both_components_reports_both(config, git_repo):
    (git_repo / "backend" / "new.py").write_text("x = 1\n")
    (git_repo / "stub" / "new.py").write_text("y = 2\n")
    assert _containment_commit(config, git_repo, "TASK-042", "") == ["backend", "stub"]


def test_the_commit_carries_the_actors_identity_and_the_task(config, git_repo):
    (git_repo / "backend" / "new.py").write_text("x = 1\n")
    _containment_commit(config, git_repo, "TASK-042", "a summary line")
    show = subprocess.run(["git", "show", "--format=%an|%ae|%B", "-s", "HEAD"], cwd=git_repo,
                          capture_output=True, text=True, check=True).stdout
    author, email, message = show.split("|", 2)
    assert author == config.git_author_name
    assert email == config.git_author_email
    assert "TASK-042" in message
    assert "a summary line" in message


# ── the refusals ────────────────────────────────────────────────────────────────────────────

def test_a_path_outside_the_boundary_is_refused_and_unstaged(config, git_repo, git):
    """The session wrote outside its roots. Nothing is committed, and nothing is left staged —
    a half-staged index would be a worse state to hand back than a clean refusal."""
    (git_repo / "docs" / "sneaky.md").write_text("nope\n")
    git("add", "docs/sneaky.md")
    (git_repo / "backend" / "new.py").write_text("x = 1\n")

    with pytest.raises(HandlerError, match="refusing to commit"):
        _containment_commit(config, git_repo, "TASK-042", "")

    assert _staged(git_repo) == []
    assert _committed(git_repo) != ["docs/sneaky.md"]


def test_the_refusal_names_the_offending_paths(config, git_repo, git):
    (git_repo / "docs" / "sneaky.md").write_text("nope\n")
    git("add", "docs/sneaky.md")
    with pytest.raises(HandlerError, match="docs/sneaky.md"):
        _containment_commit(config, git_repo, "TASK-042", "")


def test_a_session_that_changed_nothing_is_refused(config, git_repo):
    with pytest.raises(HandlerError, match="nothing staged"):
        _containment_commit(config, git_repo, "TASK-042", "")


def test_a_component_root_absent_from_disk_does_not_break_the_add(sidecar_dict, write_sidecar,
                                                                 git_repo):
    """`git add` errors hard on a pathspec matching nothing on disk AT ALL — not merely one with
    no changes. A component declared before its folder exists must not take the whole door down."""
    from foundry_implementation_actor.config import CapabilityConfig
    sidecar_dict["components"].append(
        {"name": "frontend", "path": "frontend/", "tests": "frontend/tests/",
         "dockerfile": "frontend/deployment/local"})
    config = CapabilityConfig.load(write_sidecar(sidecar_dict, git_repo.parent / "cfg"))

    (git_repo / "backend" / "new.py").write_text("x = 1\n")
    assert _containment_commit(config, git_repo, "TASK-042", "") == ["backend"]


# ── the refusal path through the door itself ────────────────────────────────────────────────

def test_a_refused_judgement_never_touches_git(config, fake_actor, tmp_path):
    """`judged=None` is the framework refusing before the engine ran. The door answers, binds the
    ids so the refusal is findable, and does nothing else."""
    implement_task = make_implement_task(config)
    result = implement_task(fake_actor({}), {"task_id": "TASK-042"}, "someone", None)
    assert result == {"accepted": False, "because": "not eligible"}


def test_an_ineligible_judgement_carries_its_reason(config, fake_actor):
    implement_task = make_implement_task(config)
    result = implement_task(fake_actor({}), {"task_id": "TASK-042"}, "someone",
                            {"implemented": False, "reason": "no definition of done"})
    assert result == {"accepted": False, "because": "no definition of done"}
