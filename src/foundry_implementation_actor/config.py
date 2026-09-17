"""`CapabilityConfig` — one capability id and one repo, every other rendering derived.

WHY THIS FILE EXISTS. Before it, the capability id was hand-written **eight** different ways
across two modules: the dotted id, the `<owner>/<repo>`, the registry path with `CAP` dropped, the
image name, the tempdir prefix, the git `user.name`, the git `user.email`, and the full image ref.
Eight literals for one fact, each correct only for as long as someone remembered to change all
eight together — and two of them (the repo, spelled once in the engine and once in the handler)
had already been copied rather than shared.

They are now derivations of two fields. Nothing in this package spells a capability.

    capability   ACME.PARTS.CAP.SUP.007.WID                   ← the only id anyone writes
    source_repo  <owner>/ACME.PARTS.CAP.SUP.007.WID-impl       ← and the only repo

    actor_name         {capability}-implementation
    actor_slug         same, lowercased, dots to hyphens
    git_author_name    actor_name
    git_author_email   {actor_slug}@users.noreply.github.com
    clone_prefix(t)    {actor_slug}-{t}-
    capability_path    the id lowercased, split AT its `cap` segment: head / tail
    image_name(c)      {capability lowercased}-{c}
    image_ref(r, c, v) {r}/{capability_path}/{c}:{v}

IDENTITY IS `capability` + ROLE, NOT THE REPO HALF. `actor_name` used to be whatever came after
the `/` in `source_repo`, which reads as a derivation but is really an assumption: that one
repository holds exactly one actor. Every sidecar in existence satisfies
`source_repo == "<owner>/" + capability + "-" + ROLE`, so deriving the name from the two facts it
was always shorthand for produces the identical string — and it keeps producing the right one when
a capability's three actors come to share a repository, where the repo half would name all three
the same thing. `source_repo` is unchanged and still required: it is where this actor clones from
and pushes to, which is a different question from who it is.

THE IMAGE REF IS A THREE-WAY CONTRACT. The testing actor recomputes the identical string and the
orchestration actor parses it back apart. `image_ref` must therefore stay byte-identical to what
those two agree on; it is derivation output or nothing, and no tag scheme is invented here.
`test_image_ref_is_the_three_way_contract` in the test suite is what pins it.

WHAT IS DERIVED AND WHAT IS DECLARED. Anything recoverable from the id or the repo is derived.
Anything genuinely additional — which components exist, where each may write, what grounds the
session — is declared in the sidecar, once. `writes_only_under` in particular is now
`components[].path` and nothing else: it used to be declared in the sidecar AND hardcoded in the
module that actually enforces it, which is how a write boundary comes to be stated twice and
eventually stated differently.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

import yaml

CONTRACT = "foundry-implementation-actor/agentic-context/v1"
SIDECAR = "actor-agentic-context.yaml"

_SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "agentic-context.schema.yaml"
_CARDS_PATH = Path(__file__).resolve().parent / "cards"

# The segment a capability id carries to say "capability". It is dropped from the registry path
# because the path position already says it — every other token of the id survives, across
# segments rather than concatenated.
_CAPABILITY_SEGMENT = "cap"

# The role this package plays for the capability it serves. Half of this actor's identity — see
# `CapabilityConfig.actor_name` — and the half that is a property of the package, not of the use.
ROLE = "implementation"

# What an unsubstituted placeholder looks like: a bare lowercase word in braces, and nothing else.
# Narrow on purpose — see `CapabilityConfig.expand`.
_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


def version() -> str:
    """This package's own version, as installed.

    Read from the installed distribution rather than written down a second time here: a literal in
    the source and a version in `pyproject.toml` are two facts that can disagree, and the one a
    rendered card would carry is the one nobody checks. In a source checkout with nothing
    installed there is no distribution to ask, and `unknown` is the honest answer — a banner is
    provenance, not a gate, and no behaviour turns on it.
    """
    try:
        return metadata.version("foundry-implementation-actor")
    except metadata.PackageNotFoundError:
        return "unknown"


def cards_path() -> Path:
    """The folder holding this actor's own four cards — its definition, shipped in the wheel.

    The cards say what a foundry implementation actor IS: its data dictionary, its message
    catalog, and the one door it answers. They name no capability, because which capability an
    instance serves is not part of what the actor is — that is the sidecar, supplied per use.

    A use is today a static folder carrying its own copy of these four, named for the capability
    it serves. This path is what a spawned instance would be rendered from once it is not, and it
    is what `papeete-actor-synchronous-messaging lint-card` is pointed at to check that the
    `-actor` suffix in this package's name is a claim it actually honours (ADR-ECO-0022).
    """
    return _CARDS_PATH


def load_schema() -> dict:
    """The contract, as committed source inside this package.

    The path is the same in a source checkout and in an installed wheel, so there is no fallback
    and no second location to reason about. A wheel that lost it is a gate with nothing to
    enforce, which is worth failing loudly over rather than degrading past.
    """
    if not _SCHEMA_PATH.exists():
        raise FileNotFoundError(
            f"{_SCHEMA_PATH.name} not found in {_SCHEMA_PATH.parent}.\n"
            "  The contract is committed source in this package, so this should be unreachable.\n"
            "  In a source checkout: the file was deleted — restore it from git.\n"
            "  In an installed wheel: the build shipped without its contract. Report it against "
            "the release."
        )
    return yaml.safe_load(_SCHEMA_PATH.read_text())


class ConfigError(ValueError):
    """The sidecar is unusable — missing, malformed, or internally inconsistent."""


@dataclass(frozen=True)
class Component:
    """One unit this actor may write to and publish."""

    name: str
    path: str
    dockerfile: str


@dataclass(frozen=True)
class Grounding:
    """One knowledge source the session is grounded in before its first turn."""

    name: str
    answers: str
    fetch: tuple[str, ...]
    into: str
    load: str

    @property
    def eager(self) -> bool:
        return self.load == "eager"


@dataclass(frozen=True)
class CapabilityConfig:
    """Everything this actor needs to know about the capability it serves."""

    capability: str
    source_repo: str
    registry_repo: str
    engine: str
    components: tuple[Component, ...]
    ground_in: tuple[Grounding, ...]

    # ── loading ─────────────────────────────────────────────────────────────────────────────

    @classmethod
    def load(cls, folder: str | Path = ".") -> CapabilityConfig:
        """Read the sidecar from `folder` (or from the file itself, if a file is given).

        Raises `ConfigError` for anything that would otherwise surface much later — a missing
        file, a contract this package does not implement, an absent required key, a component
        whose `path` does not end in `/`. Every one of those is cheaper here than mid-session.
        """
        path = Path(folder)
        if path.is_dir():
            path = path / SIDECAR
        try:
            raw = yaml.safe_load(path.read_text())
        except OSError as e:
            raise ConfigError(f"{path}: cannot be read: {e}") from e
        except yaml.YAMLError as e:
            raise ConfigError(f"{path}: does not parse: {e}") from e
        return cls.from_dict(raw, source=str(path))

    @classmethod
    def from_dict(cls, raw: object, *, source: str = "<dict>") -> CapabilityConfig:
        if not isinstance(raw, dict):
            raise ConfigError(f"{source}: not a mapping")
        if raw.get("context") != CONTRACT:
            raise ConfigError(
                f"{source}: declares context '{raw.get('context')}', not {CONTRACT}"
            )

        for key in load_schema()["required"]:
            if key not in raw:
                raise ConfigError(f"{source}: missing required key '{key}'")

        components = tuple(_component(entry, source, i)
                           for i, entry in enumerate(raw["components"] or ()))
        if not components:
            raise ConfigError(f"{source}: `components` is empty — nothing this actor may write to")

        ground_in = tuple(_grounding(entry, source, i)
                          for i, entry in enumerate(raw["ground_in"] or ()))

        source_repo = str(raw["source_repo"])
        owner, _, repo = source_repo.partition("/")
        if not owner or not repo:
            # `actor_name` used to be the repo half and validated this shape on the way past. It
            # is derived from `capability` now, so the field every clone and push URL is built
            # from needs checking in its own right rather than by a side effect.
            raise ConfigError(f"{source}: source_repo '{source_repo}' is not '<owner>/<repo>'")

        config = cls(
            capability=str(raw["capability"]),
            source_repo=source_repo,
            registry_repo=str(raw["registry_repo"]),
            engine=str(raw["engine"]),
            components=components,
            ground_in=ground_in,
        )
        # Force the derivations that can fail, here rather than at the first request that needs
        # one. A capability id with no `cap` segment is a typo, and it should not survive startup.
        _ = config.capability_path, config.actor_name
        return config

    # ── the derived renderings ──────────────────────────────────────────────────────────────

    @property
    def actor_name(self) -> str:
        """`{capability}-{ROLE}` — this actor's own name, and its git author name.

        Not the repo half of `source_repo`, which is the same string for every sidecar that
        exists but stops being this actor's name alone the moment a capability's actors share a
        repository. See this module's own docstring.
        """
        return f"{self.capability}-{ROLE}"

    @property
    def actor_slug(self) -> str:
        """The actor name as a path/address-safe token: lowercased, dots to hyphens."""
        return self.actor_name.lower().replace(".", "-")

    @property
    def git_author_name(self) -> str:
        return self.actor_name

    @property
    def git_author_email(self) -> str:
        return f"{self.actor_slug}@users.noreply.github.com"

    def clone_prefix(self, task_id: str) -> str:
        """`tempfile.mkdtemp` prefix for one task's private clone."""
        return f"{self.actor_slug}-{task_id}-"

    @property
    def capability_path(self) -> str:
        """The registry path form: the id lowercased and split AT its `cap` segment.

        `<ENT>.<DOMAIN>.CAP.<TYPE>.<NNN>.<CODE>` becomes `<ent>.<domain>/<type>.<nnn>.<code>`.
        `CAP` itself is dropped — the path position already says "capability". Nothing else is
        shortened or abbreviated: every remaining token survives, across segments rather than
        concatenated.
        """
        segments = self.capability.lower().split(".")
        if _CAPABILITY_SEGMENT not in segments:
            raise ConfigError(
                f"capability '{self.capability}' has no '{_CAPABILITY_SEGMENT.upper()}' segment — "
                "the registry path is derived by splitting the id there, so an id without one "
                "cannot be placed"
            )
        cut = segments.index(_CAPABILITY_SEGMENT)
        head, tail = segments[:cut], segments[cut + 1:]
        if not head or not tail:
            raise ConfigError(
                f"capability '{self.capability}': nothing on "
                f"{'the left of' if not head else 'the right of'} its "
                f"'{_CAPABILITY_SEGMENT.upper()}' segment"
            )
        return f"{'.'.join(head)}/{'.'.join(tail)}"

    def image_name(self, component: str) -> str:
        """The name `papeete_version.compute` versions this component under."""
        return f"{self.capability.lower()}-{component}"

    def image_ref(self, registry: str, component: str, version: str) -> str:
        """The published ref. A three-way contract — see this module's own docstring."""
        return f"{registry.rstrip('/')}/{self.capability_path}/{component}:{version}"

    # ── components ──────────────────────────────────────────────────────────────────────────

    @property
    def writes_only_under(self) -> tuple[str, ...]:
        """The write boundary: the union of the components' own roots, and nothing else."""
        return tuple(c.path for c in self.components)

    def component_for(self, path: str) -> Component | None:
        """The component a repo-relative path belongs to, by LONGEST matching prefix.

        Not the path's first segment. That shortcut is correct only while every component root is
        a single segment deep, and silently reports `src` for two different components the day one
        of them is `src/gateway/`.
        """
        matches = [c for c in self.components if path.startswith(c.path)]
        return max(matches, key=lambda c: len(c.path)) if matches else None

    def components_for(self, paths: list[str]) -> list[str]:
        """The names of the components a set of staged paths touched, sorted."""
        names = set()
        for path in paths:
            component = self.component_for(path)
            if component is not None:
                names.add(component.name)
        return sorted(names)

    # ── grounding ───────────────────────────────────────────────────────────────────────────

    def expand(self, argv: tuple[str, ...] | list[str]) -> list[str]:
        """Substitute this capability's own fields into a `ground_in` entry's `fetch:` argv.

        LITERAL REPLACEMENT, NOT `str.format`. A fetch argv is somebody else's command line, and
        braces are ordinary characters in one — a jq filter or a JSON literal passed as an
        argument would raise or, worse, be silently mangled by `format`. Only the three names
        below are substituted; every other brace passes through untouched.

        A leftover `{bare_word}` IS still refused, because that is what a typo'd placeholder looks
        like and passing it through would hand a knowledge tool a literal `{registryrepo}` to fail
        on somewhere far from here. The pattern is deliberately narrow (lowercase and underscores
        only) so a real brace-bearing argument does not trip it.
        """
        values = {
            "capability": self.capability,
            "registry_repo": self.registry_repo,
            "source_repo": self.source_repo,
        }
        out = []
        for arg in argv:
            rendered = arg
            for key, value in values.items():
                rendered = rendered.replace("{" + key + "}", value)
            leftover = _PLACEHOLDER.search(rendered)
            if leftover:
                raise ConfigError(
                    f"fetch argument {arg!r} names a placeholder this config cannot supply "
                    f"({leftover.group(0)}); available: "
                    + ", ".join("{" + k + "}" for k in sorted(values))
                )
            out.append(rendered)
        return out


def _component(entry: object, source: str, index: int) -> Component:
    where = f"{source}: components[{index}]"
    if not isinstance(entry, dict):
        raise ConfigError(f"{where}: not a mapping")
    for key in ("name", "path", "dockerfile"):
        if not entry.get(key):
            raise ConfigError(f"{where}: missing required key '{key}'")
    path = str(entry["path"])
    if not path.endswith("/"):
        # Containment is a `startswith` test. Without the trailing slash, a component rooted at
        # `stub/` would also claim `stubborn-notes.md`.
        raise ConfigError(
            f"{where}: path '{path}' must end in '/' — it is matched as a string prefix, and "
            f"without the slash it would also match a sibling whose name merely starts with it"
        )
    return Component(name=str(entry["name"]), path=path,
                     dockerfile=str(entry["dockerfile"]))


def _grounding(entry: object, source: str, index: int) -> Grounding:
    where = f"{source}: ground_in[{index}]"
    if not isinstance(entry, dict):
        raise ConfigError(f"{where}: not a mapping")
    for key in ("name", "answers", "fetch", "into", "load"):
        if not entry.get(key):
            raise ConfigError(f"{where}: missing required key '{key}'")
    fetch = entry["fetch"]
    if not isinstance(fetch, list) or not all(isinstance(a, str) for a in fetch):
        raise ConfigError(f"{where}: `fetch` must be a list of strings (argv), not a shell string")
    load = str(entry["load"])
    if load not in ("eager", "on-demand"):
        raise ConfigError(f"{where}: load '{load}' is not one of eager, on-demand")
    into = str(entry["into"])
    if into.startswith("/") or ".." in Path(into).parts:
        # `into` is written inside a clone this actor then commits from. A path that escapes it
        # would write outside the boundary the whole containment check exists to hold.
        raise ConfigError(f"{where}: into '{into}' must be a relative path inside the clone")
    return Grounding(name=str(entry["name"]), answers=str(entry["answers"]),
                     fetch=tuple(fetch), into=into, load=load)


# ── the gate ────────────────────────────────────────────────────────────────────────────────

@dataclass
class Report:
    """What `lint` found. Errors fail; warnings are read and not acted on."""

    oks: list[str]
    warns: list[str]
    errors: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


def lint(folder: str | Path = ".") -> Report:
    """Validate one sidecar against `foundry-implementation-actor/agentic-context/v1`.

    A sidecar declaring some other `context:` is read, warned, and not checked further — the same
    discipline papeete-actor applies to a card: UNMIGRATED is not non-conformant, and migrating is
    the owning pair's own act.
    """
    path = Path(folder)
    if path.is_dir():
        path = path / SIDECAR
    report = Report(oks=[], warns=[], errors=[])

    if not path.exists():
        report.errors.append(f"{path}: no such file")
        return report
    try:
        raw = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as e:
        report.errors.append(f"{path}: does not parse or cannot be read: {e}")
        return report
    if not isinstance(raw, dict):
        report.errors.append(f"{path}: not a mapping")
        return report
    if raw.get("context") != CONTRACT:
        report.warns.append(
            f"{path}: declares '{raw.get('context')}' — UNMIGRATED, not checked against {CONTRACT}"
        )
        return report

    try:
        config = CapabilityConfig.from_dict(raw, source=str(path))
    except ConfigError as e:
        report.errors.append(str(e))
        return report

    report.oks.append(f"{path} conforms to {CONTRACT}")
    report.oks.append(f"capability     {config.capability}")
    report.oks.append(f"actor          {config.actor_name}")
    report.oks.append(f"registry path  {config.capability_path}")
    report.oks.append(f"writes only under  {', '.join(config.writes_only_under)}")
    eager = [g.name for g in config.ground_in if g.eager]
    if not eager and config.ground_in:
        # Not an error: an actor may legitimately want everything on demand. But it is the shape
        # that silently un-grounds a session, so it is said out loud.
        report.warns.append(
            f"{path}: no `load: eager` source — the session starts with only the on-demand list, "
            f"and whether it reads any of them is its own choice"
        )
    return report
