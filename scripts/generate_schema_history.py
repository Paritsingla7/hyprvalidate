"""Generate (or extend) the schema corpus in `schemas/` - one schema.json
per tagged Hyprland release, from v0.55.0 (the first Lua-config release)
onward. This is what makes `hyprvalidate.schema.diff` possible at all: it
needs at least two real schemas to compare.

Deliberately NOT "clone Hyprland and build it" - confirmed while scoping
this that `meta/generateLuaStubs.py` is pure regex/brace-matching over
specific C++ source files (`src/config/lua/**/*.cpp`,
`src/config/values/ConfigValues.cpp`, etc.), so a tag's schema can be
generated from a plain checkout of that tag with no compilation at all.

Uses *each tag's own* `generateLuaStubs.py`, not a fixed copy of it - the
generator's own parsing logic has changed between versions (it's not just
the C++ it reads that changes), so using today's script against yesterday's
source would silently misrepresent that version's real schema.

Incremental by design: re-running this only generates schemas for tags that
don't already have one in `schemas/` - safe to run again after every new
Hyprland release without redoing the whole corpus.

Usage:
    python scripts/generate_schema_history.py
    python scripts/generate_schema_history.py --workdir /tmp/hypr-clone
    python scripts/generate_schema_history.py --limit 3   # newest N missing tags only
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SCHEMAS_DIR = REPO_ROOT / "schemas"
HYPRLAND_URL = "https://github.com/hyprwm/Hyprland.git"

sys.path.insert(0, str(REPO_ROOT))
from hyprvalidate.schema.extractor import extract  # noqa: E402


def run(cmd: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, check=True,
    )
    return result.stdout


def clone_hyprland(workdir: Path) -> Path:
    """A partial, blob-less clone with only meta/ and src/config/ checked
    out - generateLuaStubs.py never reads anything outside those two
    directories, and a full checkout of Hyprland's source tree is a lot of
    unrelated weight for what this needs."""
    repo_dir = workdir / "Hyprland"
    if repo_dir.is_dir():
        return repo_dir
    run([
        "git", "clone", "--filter=blob:none", "--no-checkout",
        HYPRLAND_URL, str(repo_dir),
    ])
    run(["git", "sparse-checkout", "set", "meta", "src/config"], cwd=repo_dir)
    return repo_dir


def list_lua_era_tags(repo_dir: Path) -> list[str]:
    """Every tag from v0.55.0 onward, sorted by when it was actually
    created - NOT a naive semver-string sort. Hyprland has ancient
    pre-rewrite tags like v0.6.0beta from years before the Lua config
    existed, which a naive `sort=v:refname` places ahead of v0.55.x/v0.56.x
    (found while scoping this - a real trap, not a hypothetical one)."""
    output = run(
        ["git", "for-each-ref", "--sort=creatordate",
         "--format=%(refname:short) %(creatordate:short)", "refs/tags"],
        cwd=repo_dir,
    )
    tags = []
    for line in output.splitlines():
        name, _, date = line.partition(" ")
        if name.startswith("v0.55.") or name.startswith("v0.56.") or _is_post_055(name, date):
            tags.append(name)
    return tags


def _is_post_055(name: str, date: str) -> bool:
    """Anything tagged on or after v0.55.0's release date (2026-05-09) and
    matching Hyprland's `vX.Y.Z` release-tag shape - covers future v0.57+
    tags without hardcoding a minor-version allowlist that would need
    updating every release."""
    import re
    if not re.fullmatch(r"v\d+\.\d+\.\d+", name):
        return False
    return date >= "2026-05-09"


def generate_schema_for_tag(repo_dir: Path, tag: str, out_path: Path) -> None:
    run(["git", "checkout", "--quiet", tag], cwd=repo_dir)

    stub_path = repo_dir / "hl.meta.lua"
    run([
        sys.executable, str(repo_dir / "meta" / "generateLuaStubs.py"),
        "--root", str(repo_dir), "--output", str(stub_path),
    ])

    schema = extract(stub_path.read_text())
    if not schema.classes and not schema.aliases:
        raise RuntimeError(
            f"extracted ZERO classes/aliases for {tag} - either this tag's "
            "stub format changed in a way extractor.py doesn't handle, or "
            "generateLuaStubs.py's own CLI flags changed. Investigate "
            "before trusting any diff involving this version."
        )
    out_path.write_text(schema.to_json() + "\n")
    stub_path.unlink()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--workdir", type=Path, default=None,
        help="directory to clone Hyprland into (default: a temp dir, cleaned up after)",
    )
    ap.add_argument(
        "--limit", type=int, default=None,
        help="only generate the newest N missing tags (default: all missing tags)",
    )
    args = ap.parse_args()

    SCHEMAS_DIR.mkdir(exist_ok=True)
    existing = {p.stem for p in SCHEMAS_DIR.glob("v*.json")}

    workdir = args.workdir or Path(tempfile.mkdtemp(prefix="hyprland-schema-history-"))
    cleanup = args.workdir is None
    try:
        repo_dir = clone_hyprland(workdir)
        run(["git", "fetch", "--tags", "--quiet"], cwd=repo_dir)
        tags = list_lua_era_tags(repo_dir)
        missing = [t for t in tags if t not in existing]
        if args.limit is not None:
            missing = missing[-args.limit:]

        if not missing:
            print("schemas/ is already up to date with every known Lua-era tag.")
            return 0

        for tag in missing:
            out_path = SCHEMAS_DIR / f"{tag}.json"
            print(f"generating {out_path} ...")
            generate_schema_for_tag(repo_dir, tag, out_path)

        print(f"wrote {len(missing)} schema(s): {', '.join(missing)}")
        return 0
    finally:
        if cleanup:
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
