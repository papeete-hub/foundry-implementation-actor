# foundry-implementation-actor — the runnable half of what this package ships (ADR-FIA-0005).
#
# NOT a capability's image. This one carries the MACHINERY and nothing else: it names no
# capability, installs no knowledge tool, and has no sidecar. It is a base a use derives from:
#
#     FROM ghcr.io/papeete-hub/foundry-implementation-actor:<version>
#     RUN pip install --no-cache-dir <the tools this sidecar's ground_in names>
#     COPY actor-agentic-context.yaml /actor/
#     RUN foundry-implementation-actor render-cards /actor \
#      && foundry-implementation-actor lint /actor
#
# That is a use's whole image. The four cards are rendered from the definition in this wheel
# rather than hand-copied into every repo, which is what removes the class of drift
# `conformance.check` was built to detect — see ../examples/ for a complete one that builds.
#
# BUILD CONTEXT IS THE REPO ROOT, not this folder:
#     uv build && docker build -f docker/Dockerfile -t foundry-implementation-actor:$(version) .
# The wheel is COPY'd from `dist/` rather than resolved from PyPI on purpose — see below.

FROM python:3.12-slim

# WHAT THIS ACTOR SHELLS OUT TO. Each line is here because a specific piece of the machinery
# execs it; nothing is here "in case".
#   git        — the handler clones the capability's repo into a private copy per request, and
#                commits and pushes the branch it produced.
#   nodejs/npm — the `claude` CLI ships as an npm package and has no pip distribution. The engine
#                drives it as a subprocess rather than using the raw SDK (see engine.py).
#   ca-certificates — https to a git remote, to the npm registry, and to the API behind `claude`.
RUN apt-get update && apt-get install -y --no-install-recommends \
      git curl gnupg ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && apt-get purge -y curl gnupg && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# buildctl only — a CLIENT, not a builder. The handler's own `_publish_image` points it at a
# shared buildkitd ($BUILDKIT_HOST) to build and push one image per component a task actually
# touched. No Docker daemon, no docker socket, nothing bound from the node: that is precisely why
# an actor built on this image can be an ordinary Pod. A client need only be compatible with the
# daemon it talks to, not identical to it.
COPY --from=moby/buildkit:v0.17.2-rootless /usr/bin/buildctl /usr/local/bin/buildctl

# THE WHEEL, FROM THE BUILD THAT PRODUCED THIS IMAGE — never `pip install foundry-implementation-
# actor==<tag>` from PyPI. The image and the wheel are two artifacts of one release, and resolving
# the wheel over the network would let an image tagged 0.5.0 contain some other 0.5.0 — or build
# green before the upload, then never again. CI builds both from the same checkout.
#
# `[serve]` is the wire half — a mailbox and an observability backend. They are an extra rather
# than a dependency so an embedder importing `CapabilityConfig` is not handed an HTTP server
# (ADR-PAM-0001, and pyproject's own note); this image is the consumer that wants them.
COPY dist/*.whl /tmp/wheels/
RUN set -eu; \
    wheels="$(ls /tmp/wheels/*.whl)"; \
    # One wheel, or the `[serve]` below would silently apply to whichever `ls` returned last.
    # `uv build` leaves a stale wheel in dist/ across a version bump, and this is where that turns
    # into a sentence rather than an image pinned to the version before the one it is tagged with.
    [ "$(echo "$wheels" | wc -l)" -eq 1 ] || { echo "expected exactly one wheel in dist/, found:"; echo "$wheels"; exit 1; }; \
    pip install --no-cache-dir "${wheels}[serve]"; \
    rm -rf /tmp/wheels

# DELIBERATELY NOT INSTALLED: any knowledge tool. A `ground_in:` entry names its own `fetch:`
# argv, and this package runs whatever argv it is given — so the tools a capability grounds itself
# in are the CONSUMER's dependencies, installed in the consuming image beside the sidecar that
# names them. `tests/test_portability.py` greps `src/` for those names and fails the build if the
# machinery ever grows an opinion about which tools exist; this line is the same rule, for the
# image. Also not installed: `anthropic` (the engine drives the CLI), and `gh` (this actor never
# opens a pull request — an orchestrating actor does, once a testing actor confirms).

# WHERE A USE'S SIDECAR GOES, and where its cards are rendered beside it. Empty in this image:
# there is no capability here to render them for.
WORKDIR /actor

# NON-ROOT IN THE IMAGE, not only in each deployment's securityContext. A manifest that forgets
# `runAsNonRoot` should still get a non-root container, and a uid fixed here is one an operator can
# grant a volume to without reading every consuming repo. 10001 matches the manifests this actor's
# uses deploy with.
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin actor \
    && chown -R 10001:10001 /actor
USER 10001

# $HOME must be writable: `claude` creates $HOME/.claude on first run, and every deployment of
# this runs with a read-only root filesystem and a writable /tmp. A pod that overrides HOME to
# /tmp keeps working; one that does not gets a real home directory here rather than `mkdir
# '/.claude': EROFS`.
ENV HOME=/home/actor \
    PORT=8080

# Passed at run time, never baked in:
#   GITHUB_TOKEN            clone + push on the capability's own repo, and read on whatever repos
#                           the sidecar's `ground_in:` fetches reach. The scope is set by that
#                           sidecar, not by anything in this image.
#   CLAUDE_CODE_OAUTH_TOKEN from `claude setup-token`. Do NOT also set ANTHROPIC_API_KEY or
#                           ANTHROPIC_AUTH_TOKEN: in `claude -p` non-interactive mode an API key
#                           in the environment is ALWAYS preferred over the subscription login,
#                           silently routing every session through metered billing instead.
#   BUILDKIT_HOST, IMAGE_REGISTRY, DOCKER_CONFIG   where images are built, pushed, and the
#                           credential buildctl resolves CLIENT-side before handing it to the
#                           daemon (the daemon does not authenticate on a client's behalf).
EXPOSE 8080

# `serve`, not a copied-in app.py. Sixty lines of observability wiring used to live in every use's
# repo, including one handler whose reason for existing was found by an operator who could not see
# any logs at all; it lives once, in serve.py, and every use gets the same answer.
CMD ["foundry-implementation-actor", "serve", "/actor"]
