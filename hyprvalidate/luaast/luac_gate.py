"""The cheapest possible check, and the one every existing hyprlang->lua
converter skipped: does this file actually parse as Lua at all.

`luac -p` alone would have caught 3 of the 4 competitor tools' fatal defects
(see reference-tools/README.md and docs/PLAN.md). This runs first, before
any schema-aware checking, so a syntactically broken file fails fast with a
clear message instead of the checker tripping over malformed input.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class LuacNotFound(Exception):
    """Raised when the `luac` binary isn't on PATH."""


@dataclass
class LuacResult:
    ok: bool
    message: str | None  # None when ok, luac's stderr output otherwise


def check_source(source: str, *, chunk_name: str = "input") -> LuacResult:
    """Run `luac -p` against Lua source text (via stdin)."""
    if shutil.which("luac") is None:
        raise LuacNotFound(
            "luac not found on PATH - it ships with Hyprland's Lua config "
            "support and any standard Lua install. Install it before running "
            "this check."
        )

    proc = subprocess.run(
        ["luac", "-p", "-"],
        input=source,
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        return LuacResult(ok=True, message=None)
    # luac prefixes messages with "luac: stdin:LINE: ..." when reading from
    # stdin; swap in a friendlier chunk name for the caller.
    message = proc.stderr.strip().replace("luac: stdin:", f"{chunk_name}:")
    return LuacResult(ok=False, message=message)


def check_file(path: str | Path) -> LuacResult:
    path = Path(path)
    return check_source(path.read_text(), chunk_name=str(path))
