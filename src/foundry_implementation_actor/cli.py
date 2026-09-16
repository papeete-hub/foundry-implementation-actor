"""`foundry-implementation-actor` — the gate, and the derivation table.

Four subcommands. `lint` is what CI runs against a sidecar; `show` prints every rendering
`config.py` derives from the two fields that are actually written down, so an operator can check
the image ref an actor WILL publish before it publishes one — the previous arrangement could only
be checked by reading a running actor's logs after the fact.

`render-cards` and `serve` are what make a use's whole repository one sidecar (ADR-FIA-0005): the
first writes the actor's four cards beside it from the definition in this wheel, the second boots
the thing. Both run inside the image this package publishes, which is where a use meets them; both
work in a plain venv too, which is where this repo's own gates run them.

House rule: every published package in this ecosystem ships a CLI named exactly the package.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import conformance
from .config import CapabilityConfig, ConfigError, lint, version
from .instance import render_cards
from .serve import DEFAULT_PORT, ServeError, serve
from .settings import SettingsError

_REGISTRY_PLACEHOLDER = "<registry>"


def _cmd_lint(args: argparse.Namespace) -> int:
    # Two gates, one command. The sidecar says which capability this use serves; the cards say
    # which actor it claims to be. A use can be wrong about either independently, and the second
    # check is the only thing standing between a hand-copied card set and a caller being refused
    # at a door — see `conformance.py`.
    report = lint(Path(args.folder))
    conformance_report = conformance.check(Path(args.folder))
    report.oks.extend(conformance_report.oks)
    report.warns.extend(conformance_report.warns)
    report.errors.extend(conformance_report.errors)
    for warning in report.warns:
        print(f"  ! {warning}")
    for error in report.errors:
        print(f"  FAIL {error}")
    if not report.ok:
        print(f"✗ {len(report.errors)} error(s)")
        return 1
    for line in report.oks:
        print(f"  ok   {line}")
    checked_cards = any((Path(args.folder) / name).exists() for name in conformance.CARD_FILES)
    print("✓ sidecar and cards conform" if checked_cards else "✓ sidecar conforms")
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    try:
        config = CapabilityConfig.load(Path(args.folder))
    except ConfigError as e:
        print(f"  FAIL {e}")
        return 2
    registry = args.registry or _REGISTRY_PLACEHOLDER

    rows = [
        ("capability", config.capability),
        ("source_repo", config.source_repo),
        ("registry_repo", config.registry_repo),
        ("engine", config.engine),
        ("actor name / git author", config.git_author_name),
        ("git author email", config.git_author_email),
        ("clone prefix", config.clone_prefix("TASK-NNN")),
        ("registry path", config.capability_path),
        ("writes only under", ", ".join(config.writes_only_under)),
    ]
    width = max(len(label) for label, _ in rows)
    for label, value in rows:
        print(f"  {label:<{width}}  {value}")

    print("\n  components")
    for component in config.components:
        print(f"    {component.name}")
        print(f"      path        {component.path}")
        print(f"      dockerfile  {component.dockerfile}")
        print(f"      image name  {config.image_name(component.name)}")
        print(f"      image ref   "
              f"{config.image_ref(registry, component.name, '<version>')}")

    print("\n  ground_in")
    for entry in config.ground_in:
        print(f"    {entry.name}  [{entry.load}] → {entry.into}")
        print(f"      answers   {entry.answers}")
        print(f"      fetch     {' '.join(config.expand(entry.fetch))}")
    return 0


def _cmd_render_cards(args: argparse.Namespace) -> int:
    # The step that deletes the hand copy. Run at `docker build` time, right after the sidecar is
    # COPY'd in: from then on the cards in that folder came from a version, not from someone's
    # editor, and the next version's cards arrive with the next `FROM`.
    try:
        config = CapabilityConfig.load(Path(args.folder))
    except ConfigError as e:
        print(f"  FAIL {e}")
        return 2
    try:
        written = render_cards(config, Path(args.folder))
    except FileNotFoundError as e:
        print(f"  FAIL {e}")
        return 2
    for path in written:
        print(f"  ok   rendered {path}")
    print(f"✓ {config.actor_name} — four cards from the definition in "
          f"foundry-implementation-actor=={version()}")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    # No try/except around the boot itself. A misconfigured actor that starts anyway and refuses
    # every caller at the door is strictly worse than a pod that crash-loops with the reason on
    # stdout, which is what an uncaught ConfigError produces here.
    #
    # `SettingsError` is the same kind of thing one env var over — `MAX_TURNS=ninety` is a
    # misconfiguration an operator has just made and is watching for, and one line naming the
    # variable reads better in `kubectl logs` than the traceback under it.
    try:
        serve(Path(args.folder), port=args.port)
    except (ConfigError, ServeError, SettingsError) as e:
        print(f"  FAIL {e}", file=sys.stderr)
        return 2
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="foundry-implementation-actor",
        description="Inspect and validate one capability's agentic-context sidecar.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    lint_parser = sub.add_parser(
        "lint", help="validate a sidecar against foundry-implementation-actor/agentic-context/v1")
    lint_parser.add_argument(
        "folder", nargs="?", default=".",
        help="the actor's folder, or the sidecar file itself (default: .)")
    lint_parser.set_defaults(func=_cmd_lint)

    show_parser = sub.add_parser(
        "show", help="print every identifier derived from the sidecar's capability and repo")
    show_parser.add_argument("folder", nargs="?", default=".")
    show_parser.add_argument(
        "--registry", help=f"render image refs against this registry (default: {_REGISTRY_PLACEHOLDER})")
    show_parser.set_defaults(func=_cmd_show)

    render_parser = sub.add_parser(
        "render-cards",
        help="write the actor's four cards into a use's folder, from the definition in this wheel")
    render_parser.add_argument(
        "folder", nargs="?", default=".",
        help="the folder holding this use's actor-agentic-context.yaml (default: .)")
    render_parser.set_defaults(func=_cmd_render_cards)

    serve_parser = sub.add_parser(
        "serve", help="boot this actor and answer its doors (needs the `serve` extra)")
    serve_parser.add_argument(
        "folder", nargs="?", default=".",
        help="the folder holding this use's sidecar and cards (default: .)")
    serve_parser.add_argument(
        "--port", type=int, default=None,
        help=f"override $PORT (default: $PORT, else {DEFAULT_PORT})")
    serve_parser.set_defaults(func=_cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
