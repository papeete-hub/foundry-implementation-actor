#!/usr/bin/env python3
"""Prove an INSTALLED wheel can still ground a session.

Run against a scratch venv holding nothing but this package, in CI and again in the release job
before anything is uploaded. It exercises the whole grounding path — run each `fetch:`, write each
envelope into a clone, render the `CLAUDE.md`, then check that every `@`-import it emitted resolves
to a file that actually exists.

That last check is the point. An `@`-import naming a file that is not there produces a session
grounded in nothing, and it looks exactly like a session grounded correctly: same exit code, same
transcript shape, same `num_turns`. Nothing downstream would notice. So it is asserted here, before
the wheel is published, rather than inferred later from a task that came out wrong.

    python scripts/probe_grounding.py <folder holding an actor-agentic-context.yaml>
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from foundry_implementation_actor import CapabilityConfig, grounding


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    config = CapabilityConfig.load(argv[1])
    clone = Path(tempfile.mkdtemp(prefix="grounding-probe-"))

    grounding.ground(config, clone)

    claude_md = clone / grounding.CLAUDE_MD
    if not claude_md.exists():
        print(f"  FAIL no {grounding.CLAUDE_MD} was rendered")
        return 1

    text = claude_md.read_text()
    imports = [line[1:].strip() for line in text.splitlines() if line.startswith("@")]
    eager = [entry for entry in config.ground_in if entry.eager]

    if len(imports) != len(eager):
        print(f"  FAIL {len(eager)} eager source(s) declared, {len(imports)} @-import(s) rendered")
        return 1
    if not imports:
        print("  FAIL nothing is eager — this fixture cannot prove an import resolves")
        return 1

    for target in imports:
        if not (clone / target).is_file():
            print(f"  FAIL @{target} does not resolve to a file in the clone")
            return 1
        print(f"  ok   @{target} resolves ({(clone / target).stat().st_size} bytes)")

    for entry in config.ground_in:
        if not entry.eager and entry.into not in text:
            print(f"  FAIL on-demand source '{entry.name}' is not listed in {grounding.CLAUDE_MD}")
            return 1

    print(f"✓ grounding probe passed — {len(imports)} import(s) resolve, "
          f"{len(config.ground_in) - len(imports)} listed on demand")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
