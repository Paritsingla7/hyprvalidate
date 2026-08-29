# Changelog

Notable changes. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added

- **Foundation for schema-diff** (no CLI surface yet — this lays the
  groundwork, doesn't expose it): `hyprvalidate/schema/diff.py` structurally
  compares two `Schema` snapshots — classes/fields/aliases/config-keys
  added, removed, or type-changed — plus a conservative "possible rename"
  heuristic that only fires on a clean 1:1 match (exactly one removed name
  and one added name sharing the same normalized type within a class or
  the config-key namespace). Backed by `schemas/` — one real schema
  snapshot per tagged Hyprland release from v0.55.0 onward, not synthetic
  fixtures, generated via the new `scripts/generate_schema_history.py`
  (verified end-to-end against the live Hyprland repo, byte-identical
  output to hand-generation).

  Tested against two real, dated Hyprland regressions:
  `hl.permission{}`'s `allow` → `mode` (broke one day after Lua config
  first shipped, [hyprwm/Hyprland#14400](https://github.com/hyprwm/Hyprland/pull/14400))
  is a clean 1:1 rename the heuristic catches confidently; `HL.Window`'s
  `over_fullscreen` → `allowed_over_fullscreen`
  ([hyprwm/Hyprland#15367](https://github.com/hyprwm/Hyprland/pull/15367))
  is genuinely ambiguous by type alone (two new booleans were added, not
  one) and is deliberately left as a plain removal rather than guessed at.

  Every diff is phrased as "the schema changed," never "this will break":
  the generated stub has itself lagged Hyprland's real behavior more than
  once in this project's own research (the `allow`/`mode` field was wrong
  from the version it first shipped in), so a schema diff is evidence of a
  possible behavior change, not proof of one.

### Fixed

- **`check` false-positived on every real layer rule with a `match` table**
  — `HL.LayerRuleSpec.match` is typed `table<string, string|boolean>`
  (LuaLS's generic map syntax), which `_has_table_alternative` didn't
  recognize as table-shaped at all (it only checked for `{` or `HL.` in the
  type expression), so a perfectly valid `match = { namespace = "..." }`
  was flagged as a type mismatch. Found by running `check` against two
  independent real-world Hyprland Lua configs — Garuda Linux's
  distribution-shipped settings
  ([`garuda-hyprland-settings`](https://gitlab.com/garuda-linux/themes-and-settings/settings/garuda-hyprland-settings))
  and the [sea-shell](https://github.com/MiyukiVigil/sea-shell) project —
  both of which hit this identically, since it's the only way to write a
  layer rule at all.

  The same run surfaced a second, *upstream* gap, not a hyprvalidate bug:
  both configs also use `hl.bind(..., { mouse = true })`, and `mouse` isn't
  in `HL.BindOptions` at all. Traced directly into Hyprland's own source —
  `mouse` is a real, implemented flag
  ([`LuaKeybind.cpp`](https://github.com/hyprwm/Hyprland/blob/main/src/config/lua/objects/LuaKeybind.cpp),
  parsed identically to `click`/`drag`, which *are* in the schema) that's
  simply missing, along with `auto_consuming`, `device_inclusive`, and
  `devices`, from a hand-written field list in Hyprland's own
  `meta/generateLuaStubs.py` (lines ~658–677) — the exact "hand-maintained
  table drifts from what's real" bug class this project exists to catch,
  found one level further upstream than usual. Not something hyprvalidate
  can fix on its own without hand-maintaining the same kind of table it
  refuses to elsewhere; a candidate for an upstream report.

## [0.3.0] — 2026-08-28

### Added

- **`check --fix`** applies the corrections that have exactly one right
  answer — wrapping a bare-identifier string value in quotes
  (`possible_missing_quotes`), adding `()` to a referenced-but-uncalled
  dispatcher factory (`uncalled_dispatcher`) — directly to the file, then
  re-checks. Applied as targeted character-offset patches against the
  original source (new `hyprvalidate/fixer.py`), never a full
  AST-regenerate-and-reprint, so everything outside the flagged span —
  comments, formatting, unrelated code — survives untouched; a user's
  hand-written config isn't `convert`'s freshly-generated output. Findings
  with no single correct fix (unknown symbols/keys, type/arity mismatches,
  duplicate binds) are still reported, never guessed at. Before writing,
  the patched source is run through the luac gate and re-checked — same
  discipline `convert` already applies to its own output — so a fix that
  would produce invalid Lua, or reveal a fresh problem (e.g. a dispatcher
  that turns out to need arguments once actually called), is surfaced
  instead of silently written over.

- **A ready-to-copy GitHub Actions workflow** for validating a dotfiles
  repo's Lua config in CI, with no Hyprland installation needed:
  [`examples/ci/validate-hyprland-lua.yml`](examples/ci/validate-hyprland-lua.yml).
  Pins the installed `hyprvalidate` version and its `schema.json` snapshot
  to the same git tag, so the tool and the schema it validates against are
  always in sync. Also fixes the README's own CI section, which had gone
  stale: it referenced `pipx install git+https://...` from before the PyPI
  release, and ran `hyprvalidate check ... --stub schema.json` without ever
  saying where that file comes from. Two jobs: a read-only `check` gate on
  pull requests (safe for fork PRs — no write access needed), and a
  `check --fix` job on push that commits and pushes any mechanical fixes
  straight back onto the branch, still failing the job if something
  unfixable remains. Guards against re-triggering itself on its own
  fix commit.

- **`check` now catches unquoted-string config values that would silently
  evaluate to `nil`** — e.g. `accel_profile = flat` instead of
  `accel_profile = "flat"`. This is the exact real-world bug in
  [hyprwm/Hyprland#15727](https://github.com/hyprwm/Hyprland/discussions/15727):
  a user's config migration dropped the quotes, `accel_profile` silently
  became nothing, and their mouse sensitivity changed — found only because
  a stranger happened to read their config on GitHub. The check fires only
  when the bare identifier is never assigned anywhere in the file (as a
  local, global, for-loop variable, or function parameter) — an identifier
  that genuinely is a variable reference to a defined value is left alone,
  same conservative stance as the rest of this module. New finding kind
  `possible_missing_quotes`, checked in both `hl.config` blocks and
  spec-table arguments (`hl.monitor`, `hl.device`, etc).

- **`check` now catches two error classes Hyprland's own issue
  [hyprwm/Hyprland#15871](https://github.com/hyprwm/Hyprland/issues/15871)
  ("Improve lua error reporting") calls out as currently undetected:**
  - **Uncalled dispatcher factory reference** — `hl.bind("SUPER + Q",
    hl.dsp.window.close)` (missing the trailing `()`). This type-checks
    under the stub's `HL.Dispatcher|function` union, since a bare function
    reference *is* a `function` — nothing previously caught it. New finding
    kind `uncalled_dispatcher`.
  - **Duplicate key binds** — the same key combo bound more than once
    (`hl.bind("SUPER + G", ...)` appearing twice), silently shadowing one
    of the two at runtime. Resolves string-literal `keys` arguments,
    including `..`-concatenation of only string literals; a `keys`
    expression built from a variable (the common `mainMod .. " + Q"`
    pattern) can't be resolved statically and is skipped rather than
    guessed at. New finding kind `duplicate_bind`. Caught four genuine,
    previously-undetected duplicate binds in this project's own vendored
    real-world test fixture (`$mainMod+G/M/V` and `$mainMod+ALT+space`,
    each bound twice to different actions).

  Both checks are derived entirely from the schema (no hand-maintained
  per-dispatcher data) — consistent with this project's approach of never
  hardcoding what the stub can tell it directly. A third case from the
  same issue, arity-checking `dsp.*` dispatcher-builder calls (e.g.
  `hl.dsp.exec_raw("...", {float = true})`), is **not** implemented: the
  stub types every `dsp.*` factory as untyped `fun(...)` with no argument
  count at all, so checking it would require a separately-maintained table
  of per-dispatcher arities — the exact drift risk this project exists to
  avoid (see `docs/COMPARISON.md`).

### Fixed

- **`packaging/PKGBUILD` was pinned to `pkgver=0.1.0`** even after the
  0.2.0 release — stale since that release, unrelated to anything else in
  this changelog entry, noticed and fixed while bumping the version here.

- **`check` crashed with `AttributeError` on a config containing a
  colon-method definition** (`function T:method() end`), found while
  building the checks above. `Method` (that definition node) was grouped
  with `Call` for call-detection, but has no `.func` attribute — only
  `Invoke` (an actual `obj:bar()` call) does. Real Hyprland configs don't
  define OOP-style methods, so this never surfaced in practice, but the
  checker shouldn't crash on any syntactically valid Lua.

- **`convert` emitted empty `hl.config({ <block> = {} })` tables** for blocks
  whose every key was TODO'd out (or that were empty in the source). These
  set nothing, and when the block name itself was unresolvable — e.g. a
  per-device `device:epic-mouse-v1 { ... }` block, which Hyprland's own
  default config ships as a commented example — the leftover table tripped
  `convert`'s own post-convert validation, reporting an issue on a file the
  converter had in fact handled exactly as designed. The explanatory
  `-- TODO(hyprvalidate convert):` comment is unchanged; only the dead
  table is gone. Found running the converter against a real config from
  the wild.

## [0.2.0] — 2026-08-17

### Added

- **Published to PyPI** via GitHub Actions Trusted Publishing —
  `pipx install hyprvalidate` works without a `git+` URL from this release
  onward.
- **`--version` flag.**
- **GitHub repo metadata**: description, topics, homepage; a ready
  `packaging/PKGBUILD` for Arch/AUR.

### Fixed

- **`luac` missing from PATH raised a raw Python traceback** instead of an
  actionable error. Now caught at the CLI boundary and reported as
  `error: ...` with exit 2, consistent with every other failure path.
- **`pip`/`pipx install` failed outright** ("Multiple top-level packages
  discovered") once the project site landed at a top-level `site/`
  directory — setuptools' package discovery is now pinned to
  `hyprvalidate*`.
- **The committed `schema.json` had silently drifted** from the live schema
  (missing a class) — regenerated, and a test now fails if it drifts again.
- **Every test fixture that referenced a path outside the repo** has been
  vendored into `tests/fixtures/` — the suite now passes on a fresh clone
  with no external dependencies, and runs with or without Hyprland
  installed.

### Removed

- **`docs/PLAN.md` and `docs/CONVERTER_PLAN.md`** — these had become an
  internal build log with stale, self-contradicting status and broken
  references to files outside the repo. Deleted rather than fixed in place;
  the reasoning they captured that's still relevant lives in
  `docs/COMPARISON.md` and in-code docstrings.

### Changed

- README restructured: a scannable one-line summary and action row (Try it
  online / Install / Why it's different) ahead of the badges, instead of a
  single bold paragraph.

## [0.1.0] — 2026-08-11

First public release.

### Added

- **`hyprvalidate convert`** — converts an old hyprlang `hyprland.conf` into
  Lua. Symbol names and value types are resolved from Hyprland's own
  autogenerated schema (`hl.meta.lua`) rather than a hand-maintained table.
  - `-o FILE` writes a single file.
  - `--split DIR` writes a modular directory (one file per config area) with
    a `hyprland.lua` entry point that `require()`s the rest.
  - Anything that can't be resolved with confidence becomes a
    `-- TODO(hyprvalidate convert):` comment instead of a silent guess.
  - Runs the `luac -p` gate **and** the full validator on its own output
    before reporting success.
- **`hyprvalidate check`** — validates an existing Lua config against the real
  API: unknown symbols, unknown config keys, type mismatches, call arity, and
  invalid fields inside spec tables. Accepts individual files or a directory.
- **`--stub` accepts a `schema.json` snapshot** as well as the live
  `hl.meta.lua`, so configs can be validated on machines with no Hyprland
  installed (CI for a dotfiles repo, containers).
- **Project site** with a live in-browser demo that runs the real converter
  and validator via Pyodide — <https://paritsingla7.github.io/hyprvalidate/>
- **[`docs/COMPARISON.md`](docs/COMPARISON.md)** — measured comparison against
  the existing converters, with `docs/measure_comparison.py` to reproduce
  every number.
- MIT license, CI across Python 3.10–3.13, contributor docs, issue templates.

### Notes

- Known gaps are listed under **Limitations** in the README — `plugin {}`
  blocks, `source =`, `animation`/`bezier` directives, and `--fix` mode are
  deliberate, documented omissions rather than oversights.
