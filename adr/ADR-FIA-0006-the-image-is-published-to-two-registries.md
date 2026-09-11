---
id: ADR-FIA-0006
title: "The image is published to two registries, and names neither in its source"
status: Proposed
date: 2026-09-11
supersedes: []
references:
  - ../.github/workflows/release.yml
  - ADR-FIA-0005-the-actor-ships-an-image.md
---

# ADR-FIA-0006 — The image is published to two registries, and names neither in its source

## Context

ADR-FIA-0005 made the base image half of what a release is: a use is one sidecar and a `FROM`
line, so the image is not a convenience beside the wheel, it is the thing a use is built out of.
The first release to carry one (0.5.0) published it to GHCR, because that is the registry a
GitHub-hosted package gets for free and the only one the workflow had a credential for.

That is the wrong registry for the consumer that actually exists. A use is built **inside a
cluster**, by the shared rootless builder `papeete-platform`'s `modules/buildkit` installs, which
resolves a `FROM` line client-side against the registry it holds a push token for — an Azure
Container Registry, provisioned by that repo's `modules/acr` with scope maps over the product's own
repository prefixes. `buildctl` has exactly one registry credential, mounted as its
`$DOCKER_CONFIG/config.json`, and it is not a GHCR one. So a `FROM ghcr.io/...` line inside that
builder resolves against a registry it cannot authenticate to, and the failure is a pull error at
build time rather than anything a gate here would catch.

Meanwhile GHCR is the right registry for the other consumer: someone reading this README and
writing a Dockerfile on their laptop, who has a GitHub account and no relationship with any
product's Azure subscription.

Two consumers, reached by two different credentials. The image has to be in both.

## Decision

The release workflow's `image` job pushes **one build to two registries**:

- **GHCR**, unconditionally, at `ghcr.io/<this repo>` — unchanged.
- **A product's own registry**, when `vars.PRODUCT_IMAGE` names one. The variable is the full
  repository path (`<name>.azurecr.io/<product>/foundry-implementation-actor`); the login server
  is its first segment; `secrets.ACR_PUSH_USERNAME` / `ACR_PUSH_PASSWORD` are the scope-mapped push
  token `modules/acr` already emits as outputs.

`docker tag` re-points the build GHCR already holds, so both registries carry **one digest**. The
job does not build twice.

`vars.PRODUCT_IMAGE` unset is a valid state: a fork, or this repo before its credentials existed,
publishes to GHCR alone and emits a `::notice` saying so. Set-but-broken is a hard failure.

The workflow also gains `workflow_dispatch`, so a version whose wheel is already on PyPI can be
given an image in a registry it missed without inventing a version number. It **takes the tag as an
input** and is run from the default branch: GitHub takes the workflow file from the ref it is
dispatched on, and a tag old enough to need a backfill is by definition older than the workflow
that can perform one — so the checkout takes its content from the named tag while the file comes
from the branch. On a manual run the `publish` job is skipped — PyPI refuses a version it already
holds — and `latest` is **not** moved in either registry, so backfilling an old tag cannot drag it
backwards.

## Rationale

**Why a variable and not a literal.** This package is generic across capabilities and carries no
product's name; `tests/test_portability.py` enforces exactly that over `src/`, and a product name
hardcoded in `release.yml` would be the same mistake one directory over. A product that hosts a
registry names itself in its own repository variable. It also makes "no product registry
configured" expressible rather than a broken default.

**Why one build rather than two.** Two `docker build` invocations in one job can produce two
different images — a base-image tag refreshed between them is enough — and nothing downstream
would ever notice that `:0.5.0` meant different bytes depending on where it was pulled from. That
is the same failure the existing gate *the image and the wheel are one release* exists to prevent,
one level up.

**Why not mirror instead.** ACR can import from another registry (`az acr import`), which would
keep one publishing path. It needs a credential for the source, which means making the GHCR package
public or minting a PAT for it, and it puts a second system between the tag and the image. Pushing
the build we already have in hand is fewer moving parts.

**Why this repo decides this at all.** Where an ecosystem's artifacts live is an `ADR-ECO-*`
question, and there is no ecosystem ADR about registries today. What this ADR owns is narrower and
squarely this repo's: that a release publishes to more than one place, and that this package names
none of them in its own source.

## Consequences

- **Two secrets and one variable must exist** on this repo before the product push does anything:
  `PRODUCT_IMAGE`, `ACR_PUSH_USERNAME`, `ACR_PUSH_PASSWORD`. The credentials come from
  `terraform output` on `papeete-platform`'s `examples/acr-local`, and they are set by a human —
  `papeete-foundry-product/GetSecrets.sh` is TTY-only by design so no credential passes through an
  assistant's context, and that convention holds here.
- **0.5.0 shipped to GHCR only.** Its image exists at
  `ghcr.io/papeete-hub/foundry-implementation-actor:0.5.0` and nowhere else until the manual run
  above is used to backfill it.
- **The token's scope map must admit the repository.** `modules/acr`'s `repository_patterns` is the
  caller's input, and a path outside it is refused at push time with a permissions error rather
  than at configuration time. Widening it is a `papeete-platform` change, not one here.
- **A rotated push token silently stops releases.** The token password is created by Terraform with
  no expiry by default; when that changes, the secret here has to change with it. Nothing in this
  repo can detect the drift — the first symptom is a failed release job.
- **Still to realize:** a use's `FROM` line points at GHCR today
  (`examples/…/Dockerfile`, and the real use in `papeete-foundry`). Pointing it at the product
  registry is what makes the in-cluster builder work, and it belongs in those repos rather than
  here — this ADR only makes the image available to be pointed at.
