# A complete use of this actor, as an image. Four lines, one of which is a gate.
#
# Compare it with what a use used to carry: four hand-copied cards, a sixty-line `app.py`, and a
# ninety-line Dockerfile of which exactly two lines were about the capability. All of that is the
# base image now (ADR-FIA-0005). What is left below is the capability and nothing else — which is
# the claim this package's README has always made, finally true of a real folder.
#
# The tag is pinned deliberately. A use upgrades by changing this line, which is also how it takes
# a new definition of the cards: `render-cards` below writes them from whatever wheel this image
# carries, so a door added in a later version arrives with the `FROM`, not with an editor.
# The whole ref is one ARG, not just the tag: this repo's own CI builds the base image from the
# checkout and points this line at it, which is how the example is proven to build against the
# version being released rather than against the last one published.
#
# The default names the product registry rather than GHCR for one reason: it is the copy a reader
# can actually pull. The GHCR package is private, so an unauthenticated `docker build` here fails
# with a 401 and the example teaches nothing. ACR is where the pull token, the node bypass and the
# `acr-pull` Secret already point (ADR-FIA-0006 publishes the same digest to both). Override it if
# you are somewhere else:
#     docker build --build-arg ACTOR_IMAGE=ghcr.io/papeete-hub/foundry-implementation-actor:0.5.0 .
ARG ACTOR_IMAGE=papeetefoundry.azurecr.io/foundry/foundry-implementation-actor:0.5.0
FROM ${ACTOR_IMAGE}

# THE KNOWLEDGE TOOLS THIS SIDECAR NAMES, and the one thing the base image deliberately does not
# install. A `ground_in:` entry supplies its own `fetch:` argv and the machinery runs whatever argv
# it is given, so which tools exist is the consumer's fact, declared where the sidecar that names
# them lives. Add a `ground_in` entry reaching a new tool and this line grows with it.
#
# This example's `fetch:` argvs are `printf`, so it needs nothing — the line stays, commented, as
# the shape a real use fills in. A real one reads:
#     RUN pip install --no-cache-dir kpack==2.0.1 kontract==0.1.0
#RUN pip install --no-cache-dir <tools>

# THE BINDING. One file: the capability, its repo, its registry, its components, its grounding.
COPY actor-agentic-context.yaml /actor/

# Render the cards from the definition in the image, then refuse to build if the result does not
# conform. `render-cards` cannot really produce a non-conformant card set — that is its whole
# point — but `lint` also checks the SIDECAR, which is hand-written and can be wrong about the
# capability it names. Failing here is failing while someone is watching a build, rather than at a
# door with a caller on the other side.
RUN foundry-implementation-actor render-cards /actor \
 && foundry-implementation-actor lint /actor

# No CMD: the base image's is `foundry-implementation-actor serve /actor`, and a use that restates
# it is a use that can get it wrong.
