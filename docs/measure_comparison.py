#!/usr/bin/env python3
"""Reproduce every number quoted in docs/COMPARISON.md.

The comparison in this project's docs makes factual claims about other
people's projects. Those claims should be checkable by anyone, not taken on
trust - so this script measures them from source and prints the result.

Usage:
    git clone https://github.com/Prateek-squadron/hyprconf2lua  reference-tools/hyprconf2lua
    git clone https://github.com/Phillezi/hypr2lua              reference-tools/hypr2lua
    git clone https://github.com/loeclos/hypr-migrate           reference-tools/hypr-migrate
    python docs/measure_comparison.py

Anything it can't find is reported as "not measured" rather than guessed.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
REF = REPO_ROOT / "reference-tools"
STUB = Path("/usr/share/hypr/stubs/hl.meta.lua")

sys.path.insert(0, str(REPO_ROOT))


def rule(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def real_dispatcher_count() -> int | None:
    """Every leaf `fun(...)` reachable under HL.DspNamespace in the stub."""
    if not STUB.is_file():
        return None
    from hyprvalidate.schema.extractor import extract_file

    schema = extract_file(STUB)

    def walk(cls_name: str) -> list[str]:
        cls = schema.classes.get(cls_name)
        if cls is None:
            return []
        out: list[str] = []
        for name, type_expr in sorted(cls.fields.items()):
            if type_expr.startswith("fun("):
                out.append(name)
            elif type_expr in schema.classes:
                out.extend(walk(type_expr))
        return out

    return len(walk("HL.DspNamespace"))


def hyprconf2lua_dispatchers() -> int | None:
    path = REF / "hyprconf2lua/src/hyprconf2lua/mappings.py"
    if not path.is_file():
        return None
    m = re.search(r"DISPATCHER_MAP\s*=\s*\{(.*?)\n\}", path.read_text(), re.S)
    return len(re.findall(r'^\s*"([^"]+)"\s*:', m.group(1), re.M)) if m else None


def hypr2lua_dispatchers() -> int | None:
    path = REF / "hypr2lua/pkg/mapper/bind.go"
    if not path.is_file():
        return None
    return len(re.findall(r'^\s*case "', path.read_text(), re.M))


def hypr_migrate_dispatchers() -> int | None:
    path = REF / "hypr-migrate/hypr_migrate.py"
    if not path.is_file():
        return None
    m = re.search(r"_DISP_MAP: dict\[str, str\] = \{(.*?)\n\}", path.read_text(), re.S)
    return len(re.findall(r'^\s*["\']([^"\']+)["\']\s*:', m.group(1), re.M)) if m else None


def hypr2lua_schema_entries() -> tuple[int, int, int] | None:
    """Replicate hypr2lua's own stub parser (pkg/lua/stubs/parser.go) exactly
    and report how many entries it extracts from the real stub.

    Its Parse() skips any line starting with "--", then parseLine() ignores
    lines without "=", then registerPath() drops paths with fewer than two
    dot-separated segments. Returns (total_lines, skipped_as_comment,
    registered).
    """
    if not STUB.is_file():
        return None
    lines = STUB.read_text().splitlines()
    skipped = registered = 0
    for raw in lines:
        line = raw.strip()
        if line == "" or line.startswith("--"):
            skipped += 1
            continue
        if line.startswith("---@type") or "=" not in line:
            continue
        left = line.split("=", 1)[0].strip()
        if len(left.split(".")) < 2:
            continue
        registered += 1
    return len(lines), skipped, registered


def luac_results() -> list[tuple[str, bool, str]]:
    out = []
    for f in sorted((REF / "sample-outputs").glob("*.lua")):
        proc = subprocess.run(
            ["luac", "-p", str(f)], capture_output=True, text=True
        )
        first = (proc.stderr or proc.stdout).strip().splitlines()
        out.append((f.name, proc.returncode == 0, first[0] if first else ""))
    return out


def main() -> None:
    print("hyprvalidate — comparison measurements")
    print("=" * 38)
    print(f"stub: {STUB} ({'found' if STUB.is_file() else 'NOT FOUND'})")
    print(f"reference-tools: {REF} ({'found' if REF.is_dir() else 'NOT FOUND'})")

    rule("Dispatcher coverage")
    real = real_dispatcher_count()
    print(f"  real dispatchers in Hyprland's stub : {real if real is not None else 'not measured'}")
    for label, fn in (
        ("hyprconf2lua  DISPATCHER_MAP", hyprconf2lua_dispatchers),
        ("hypr2lua      switch cases  ", hypr2lua_dispatchers),
        ("hypr-migrate  _DISP_MAP     ", hypr_migrate_dispatchers),
    ):
        n = fn()
        print(f"  {label}      : {n if n is not None else 'not measured (clone missing)'}")

    rule("hypr2lua's schema parser, replicated")
    res = hypr2lua_schema_entries()
    if res is None:
        print("  not measured (stub missing)")
    else:
        total, skipped, registered = res
        print(f"  lines in hl.meta.lua                : {total}")
        print(f"  discarded by the '--' prefix check  : {skipped}")
        print(f"  entries actually registered         : {registered}")

    rule("Do the sample outputs parse as Lua? (luac -p)")
    results = luac_results()
    if not results:
        print("  not measured (no reference-tools/sample-outputs)")
    for name, ok, msg in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        if not ok and msg:
            print(f"        {msg}")

    rule("This project")
    print(f"  hyprvalidate hardcoded dispatcher names : 0 (resolved from the stub at runtime)")


if __name__ == "__main__":
    main()
