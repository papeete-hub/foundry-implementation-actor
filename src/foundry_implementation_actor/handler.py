"""`implement_task` — the deterministic, auditable half of an implementation door.

`ClaudeCodeEngine.judge()` embodies the creative decision: what to build, grounded in the caller's
own payload and in the capability's own standing context. Everything here is mechanical and never
trusted to the engine's own judgement:

- **Containment.** `git add <component root>` for each declared component — never `-A`, never a
  bare `.` — then assert every `git diff --cached --name-only` path starts with one of those
  roots. This check, not the session's own write-boundary instruction, is what actually enforces
  the write boundary. A staged path outside it is refused rather than committed.
- **The correlation id.** `TASK-NNN` is threaded through the branch name (from the engine), the
  commit message, and — via `correlation.py`, bound at the top of this door — every log record
  this actor emits for the request, alongside the trace id its caller propagated.
- **Publishing.** For each component the commit actually touched, this actor builds an image in
  the cluster's shared buildkit and pushes it to the registry, named and versioned by convention
  (`papeete_version.compute`) — no explicit tag is ever handed to a caller. No Docker daemon is
  involved anywhere: `buildctl` reaches `BUILDKIT_HOST`, which is why an actor running this can
  be an ordinary Pod.
- **Never opens a PR.** This door accepts, pushes, and publishes. Rendering a verdict and opening
  a pull request belongs to whichever actor orchestrates the pipeline, once its other members
  have also confirmed.

THE BOUNDARY IS READ, NOT RESTATED. `WRITES_ONLY_UNDER` used to be a module constant here, kept
in sync by hand with the sidecar's own declaration of the same fact. It is now
`config.writes_only_under`, derived from `components[].path`. There is one source, and this file
is not it.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from papeete_version.version import compute as compute_version
from papeete_version.version import normalize_name

from . import correlation
from .config import CapabilityConfig


class HandlerError(RuntimeError):
    """Raised for anything that stops this door short — including a containment violation.

    `Actor.receive()` turns an uncaught exception from a handler into a `Refusal`
    (`{self.name}'s own handler for '{offer.id}' failed: {e}`), which the HTTP binding replies as
    400 — the same path an undeclared door or a schema violation already takes. A containment
    breach is therefore refused, never silently swallowed or half-committed.
    """


def make_implement_task(config: CapabilityConfig):
    """Bind one capability's config to the `implement-task` handler.

    A factory rather than a module-level function reading `actor.engines["claude-code"]`: the
    engine's registered name comes from the sidecar, so looking the config up through a hardcoded
    engine key would reintroduce exactly the literal this package exists to remove.
    """

    def implement_task(actor, payload: dict, from_: str, judged: dict | None = None) -> dict:
        # Bound again here, not only in the engine's own `judge()`: a refusal path reaches this
        # door with `judged=None`, having never entered the engine at all, and that refusal is
        # exactly the record you want carrying a task id.
        correlation.bind(correlation_id=correlation.correlation_id(),
                         task_id=payload.get("task_id"), door="implement-task", caller=from_)

        if judged is None or not judged.get("implemented"):
            reason = (judged or {}).get("reason", "not eligible")
            correlation.event("implement-task-refused", because=reason)
            return {"accepted": False, "because": reason}

        task_id = payload["task_id"]
        clone_dir = Path(judged["clone_dir"])
        branch = judged["branch"]
        summary = judged.get("summary", "")

        try:
            with correlation.stage("containment-commit",
                                   writes_only_under=list(config.writes_only_under)):
                components = _containment_commit(config, clone_dir, task_id, summary)
            correlation.event("components-touched", components=components)
            with correlation.stage("push-branch", branch=branch, repo=config.source_repo):
                _push(config, clone_dir, branch, _github_token(actor, config))
            images = []
            for component in components:
                with correlation.stage("publish-image", component=component):
                    images.append(_publish_image(config, clone_dir, component, task_id))
                    correlation.event("image-published", component=component, image=images[-1])
            return {"accepted": True, "branch": branch, "images": images}
        finally:
            shutil.rmtree(clone_dir, ignore_errors=True)

    return implement_task


def _github_token(actor, config: CapabilityConfig) -> str:
    engine = actor.engines.get(config.engine)
    token = getattr(engine, "github_token", None) or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise HandlerError("no GITHUB_TOKEN available (neither on the engine nor the environment)")
    return token


def _redact(text: str, secret: str) -> str:
    return text.replace(secret, "***")


def _run(clone_dir: Path, args: list[str], *, redact: str | None = None) -> str:
    try:
        result = subprocess.run(args, cwd=clone_dir, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        stderr = _redact(e.stderr, redact) if redact else e.stderr
        raise HandlerError(f"{' '.join(args[:2])} failed: {stderr}") from e
    return result.stdout


def _containment_commit(config: CapabilityConfig, clone_dir: Path,
                        task_id: str, summary: str) -> list[str]:
    boundary = config.writes_only_under
    for path in boundary:
        # `git add` errors hard (pathspec did not match any files) on a prefix that doesn't exist
        # on disk AT ALL, not just one with zero changes — verified live against a sibling actor
        # that hit exactly this for a tests/ root before any task had touched it. The guard is
        # cheap and keeps two containment checks in different repos genuinely identical.
        if (clone_dir / path).exists():
            _run(clone_dir, ["git", "add", path])
    staged = [line for line in _run(clone_dir, ["git", "diff", "--cached", "--name-only"])
              .splitlines() if line]

    offending = [p for p in staged if not any(p.startswith(prefix) for prefix in boundary)]
    if offending:
        _run(clone_dir, ["git", "reset"])
        raise HandlerError(
            f"{task_id}: refusing to commit — staged path(s) outside "
            f"{', '.join(boundary)}: {offending}"
        )
    if not staged:
        raise HandlerError(
            f"{task_id}: nothing staged under {', '.join(boundary)} — the session made no change "
            f"there"
        )

    message = f"feat({task_id}): implemented by {config.actor_name}\n\nTask: {task_id}"
    if summary:
        message += f"\n\n{summary}"
    _run(clone_dir, [
        "git", "-c", f"user.name={config.git_author_name}",
        "-c", f"user.email={config.git_author_email}",
        "commit", "-m", message,
    ])

    # Which component a staged path belongs to is resolved by LONGEST declared prefix, not by
    # taking the path's first segment. The first-segment shortcut is correct only while every
    # component root is one segment deep, and reports the wrong component — silently — the day
    # one of them is `src/gateway/`.
    return config.components_for(staged)


def _push(config: CapabilityConfig, clone_dir: Path, branch: str, token: str) -> None:
    push_url = f"https://x-access-token:{token}@github.com/{config.source_repo}.git"
    _run(clone_dir, ["git", "push", "--force", push_url, f"HEAD:refs/heads/{branch}"],
         redact=token)


def _image_registry() -> str:
    registry = os.environ.get("IMAGE_REGISTRY")
    if not registry:
        raise HandlerError(
            "no IMAGE_REGISTRY set — this actor publishes to a registry, and refuses to build an "
            "image nothing else could ever pull"
        )
    return registry.rstrip("/")


def _publish_image(config: CapabilityConfig, clone_dir: Path,
                   component: str, task_id: str) -> str:
    """Build this component's own image in the cluster's shared buildkit and push it — versioned
    by convention, never an explicitly-passed tag.

    No Docker daemon and no docker socket: `buildctl` talks to the buildkitd Service named by
    `BUILDKIT_HOST`, which holds the push credential itself. The build runs where buildkitd runs;
    only the ref comes back.

    Pushed rather than left local because the pod that runs this image is not this pod — it is a
    container in an ephemeral namespace the orchestrating actor stands up later, which can only
    reach the image through a registry.

    THE REF IS A CONTRACT WITH ACTORS THIS PACKAGE NEVER SEES. Its peers recompute the identical
    string and parse it back apart, so it is `config.image_ref` output or nothing. Never invent a
    tag scheme here.
    """
    declared = config.component_for(f"{component}/")
    if declared is None:                       # unreachable via `components_for`, cheap to hold
        raise HandlerError(f"{component}: not a declared component of {config.capability}")

    dockerfile_dir = clone_dir / declared.dockerfile
    if not dockerfile_dir.is_dir():
        # Late failure here is expensive: the commit has already landed and the branch is already
        # pushed. Saying which declared path is missing beats `buildctl`'s own error, which names
        # a temp path the operator has no way to map back to the sidecar.
        raise HandlerError(
            f"{component}: declared dockerfile directory '{declared.dockerfile}' does not exist "
            f"in the clone — the sidecar and the repo disagree"
        )

    version = compute_version(
        folder=clone_dir / declared.path.rstrip("/"),
        name=config.image_name(component),
        label="feature",
        feature_name=normalize_name(task_id),
    )
    image = config.image_ref(_image_registry(), component, version)
    _run(clone_dir, [
        "buildctl", "build",
        "--frontend", "dockerfile.v0",
        "--local", f"context={declared.path.rstrip('/')}",
        "--local", f"dockerfile={declared.dockerfile}",
        "--output", f"type=image,name={image},push=true",
    ])
    return image
