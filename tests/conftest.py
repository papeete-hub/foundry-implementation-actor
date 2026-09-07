"""Fixtures.

THE FIXTURE CAPABILITY IS FICTIONAL, ON PURPOSE. `ACME.PARTS.CAP.SUP.007.WID` is not any real
capability in any real instance. This package is published publicly and carries no reference to
the instance it was extracted from — a test suite is source too, and `tests/test_portability.py`
would be a strange gate to enforce over `src/` while the fixtures next door named a client.

It has the same SHAPE as a real id (`<ENT>.<DOMAIN>.CAP.<TYPE>.<NNN>.<CODE>`), which is what the
derivation tests actually pin. A derivation that is right for this id is right for every id of
that shape, and the shape is the contract.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

CAPABILITY = "ACME.PARTS.CAP.SUP.007.WID"
SOURCE_REPO = "acme-lab/ACME.PARTS.CAP.SUP.007.WID-implementation"
REGISTRY_REPO = "acme-lab/acme-governance"

SIDECAR = {
    "context": "foundry-implementation-actor/agentic-context/v1",
    "engine": "claude-code",
    "capability": CAPABILITY,
    "source_repo": SOURCE_REPO,
    "registry_repo": REGISTRY_REPO,
    "components": [
        {"name": "backend", "path": "backend/", "tests": "backend/tests/",
         "dockerfile": "backend/deployment/local"},
        {"name": "stub", "path": "stub/", "tests": "stub/tests/",
         "dockerfile": "stub/deployment/local"},
    ],
    "ground_in": [
        {"name": "business",
         "answers": "the WHAT/WHY — domain vision, business events, ubiquitous language",
         "fetch": ["kpack", "pack", "{capability}", "--deep", "--compact",
                   "--registry-repo", "{registry_repo}"],
         "into": ".foundry/business.md",
         "load": "eager"},
        {"name": "process",
         "answers": "the HOW — aggregates, commands, policies, read-models, bus, api",
         "fetch": ["kontract", "fetch", "{capability}", "--compact",
                   "--registry-repo", "{registry_repo}"],
         "into": ".foundry/process.md",
         "load": "on-demand"},
    ],
}


@pytest.fixture
def sidecar_dict() -> dict:
    """A deep-enough copy that a test may mutate one key without leaking into the next."""
    import copy
    return copy.deepcopy(SIDECAR)


@pytest.fixture
def write_sidecar(tmp_path):
    """Write a sidecar into a folder and return that folder."""
    def _write(doc: dict, folder: Path | None = None) -> Path:
        folder = folder or tmp_path
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "actor-agentic-context.yaml").write_text(yaml.safe_dump(doc, sort_keys=False))
        return folder
    return _write


@pytest.fixture
def config(sidecar_dict, write_sidecar):
    from foundry_implementation_actor.config import CapabilityConfig
    return CapabilityConfig.load(write_sidecar(sidecar_dict))


@pytest.fixture
def git_repo(tmp_path):
    """A real git repo with the fixture's two component roots, one commit deep.

    A real one rather than a mock: the containment check IS `git add` plus `git diff --cached`,
    and a fake that returns a list of paths would test the assertion while skipping the part that
    has actually surprised people (`git add` erroring on a pathspec that matches nothing on disk).
    """
    repo = tmp_path / "clone"
    (repo / "backend" / "tests").mkdir(parents=True)
    (repo / "stub" / "tests").mkdir(parents=True)
    (repo / "docs").mkdir()
    (repo / "backend" / "keep.txt").write_text("initial\n")
    (repo / "stub" / "keep.txt").write_text("initial\n")
    (repo / "docs" / "keep.txt").write_text("initial\n")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    return repo


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


@pytest.fixture
def git(git_repo):
    def _run(*args: str) -> None:
        _git(git_repo, *args)
    return _run


class FakeActor:
    """Stands in for `Actor` where the handler only reaches for `engines`."""

    def __init__(self, engines: dict):
        self.engines = engines


@pytest.fixture
def fake_actor():
    return FakeActor
