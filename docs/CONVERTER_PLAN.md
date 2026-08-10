# Converter implementation — task list

Planning only. Nothing here is built yet. Rows 5-7 in `docs/PLAN.md`,
broken into branch-sized tasks matching the workflow used for the
Validator (one task = one branch, tested before commit, PR into main).

## Architecture, resolved before writing tasks (not guessed)

Three things were verified against real evidence rather than assumed,
because getting them wrong would shape the whole design:

1. **`luaparser` can write Lua, not just read it** (`ast.to_lua_source()`).
   Confirmed it produces real Lua text from a hand-built AST. Row 6 does
   **not** need a separate custom Lua AST module - it reuses the same
   dependency as row 3 (the reader), just using it in the other direction.
   Caveat found while checking: `astnodes.String`'s `raw` field needs the
   caller to pass already-Lua-quoted text, not a bare Python string - get
   this wrong and output round-trips incorrectly. A thin builder-helper
   layer (`hlcall(name, *args)`, `luastr(s)`, `luatable({...})`) should sit
   between the mapper and raw `astnodes` construction so this footgun is
   handled in one place, not at every call site.

2. **`hl.config`'s repeated-call merge semantics, confirmed from Hyprland's
   actual source** (`src/config/lua/bindings/LuaBindingsConfigRules.cpp`,
   function `hlConfig`): it walks the table building the same dotted key
   `config_value_types` already uses, and sets each key independently in a
   persistent map. Multiple `hl.config()` calls merge *per-key*
   automatically. **The mapper must NOT pre-merge repeated hyprlang blocks
   (`general {}` appearing twice, etc.) before emission** - emit one
   `hl.config()` call per original block, in original order, and let
   Hyprland's runtime do the merging. This is the opposite of what three of
   the four competitor tools do (they either merge blocks into one Lua
   table before emission - hypr-migrate's fatal bug - or don't merge at
   all and produce duplicate/conflicting output).

3. **The block-type whitelist (which hyprlang directives become a
   top-level `hl.X(spec)` call vs. a nested key under `hl.config({...})`)
   is derivable from the schema, not hand-typed.** A hyprlang block name
   becomes a top-level call if a same-named field exists on `HL.API` whose
   type is a named `fun(spec: HL.SomeSpec)` signature (monitor, device,
   gesture, window_rule, layer_rule, workspace_rule, permission). Otherwise
   it's a section that flattens into `hl.config`'s dotted-key space
   (general, decoration, input, misc, animations, plugin). This whitelist
   *is* effectively rows 4/10's own dispatch logic, already built and
   tested - the mapper reuses `resolve_symbol`'s namespace-walk, it doesn't
   reinvent a parallel one. Hypr-migrate had exactly this right idea
   (`KNOWN_SECTIONS`) and never wired it in - the fix here is architectural
   (derive it live from the schema every run) so it can't go stale *or* go
   unwired, both of which were real bugs in real tools.

## What can't be schema-derived, stated up front

Unlike the Validator (100% schema-derived, zero hand-maintained knowledge),
the converter's *input* side inherently needs hand-curated domain knowledge
the new schema cannot contain, because it describes hyprlang, not Lua:

- Old dispatcher name -> new dispatcher path (`killactive` -> `window.close`,
  `togglefloating` -> `window.float`, `movefocus` -> `focus`,
  `togglespecialworkspace` -> `workspace.toggle_special`, etc). A small
  (~15-entry) hand-built table, checked *against* the schema at build time
  (every target path must resolve via `resolve_symbol`) so it can't silently
  drift the way the four existing tools' tables did.
- Old bind-flag letter -> new `HL.BindOptions` field name (`r` -> `release`,
  `l` -> `locked`, `e` -> `repeating`, `m` -> `mouse`... wait, `mouse` isn't
  real, see row 10's history - this table needs the same "checked against
  the schema" discipline, since this exact class of table is where
  hypr-migrate's `bindr`->`repeating` bug and our own `mouse`->`drag` bug
  both came from).
- hyprlang's own grammar quirks (backslash continuation, `${...}` shell
  expansion, the `:` -flattened `match:key` window-rule syntax, comment
  stripping) - not opinions, just what the old format's lexer needs to
  handle. `hyprconf2lua/lexer.py` already handles these correctly (MIT,
  candidate to adapt per `reference-tools/README.md`).

## Tasks

Each is one branch: implement, test, verify, commit, PR, merge - same
discipline as rows 1-10. Ordered so each task's test oracle exists before
it's needed.

### Row 5 - Hyprlang reader

- **5.1 Lexer.** Adapt `hyprconf2lua/lexer.py` (MIT, attribute it) into
  `hyprvalidate/hyprlang/lexer.py`. Test: tokenize the project's own real
  `configs/hyprland.conf` end to end, no crashes, sane token stream -
  cheap, high-signal smoke test since we already have this exact file.
- **5.2 Parser/AST.** Block structure (`section { ... }`), flat `key = value`
  directives, `$variable` substitution, all `bind`/`binde`/`bindl`/`bindm`/
  `bindr`/`bindel`/etc. variants, `exec`/`exec-once`, `windowrule`/
  `windowrulev2` (both block and one-line forms - hypr2lua's defect 3/4 was
  specifically failing to route block-form window rules to the same handler
  as one-line ones, verify both paths hit the same AST node type), `source`.
  Test: parse the same real `hyprland.conf`, assert specific known
  directives appear correctly in the AST (bind count, monitor count,
  window-rule count - we know the ground-truth counts already from the
  original file).

### Row 6 - Lua writer

- **6.1 Builder helpers.** Thin wrappers over `luaparser.astnodes`
  (`hlcall`, `luastr`, `luatable`, member-chain builder) that get the
  `String.raw` quoting and similar footguns right in one place. Test:
  build a handful of known shapes (a bind call, a nested config table),
  call `to_lua_source`, assert the output re-parses via row-3's reader and
  round-trips to the same values.

### Row 7 - Schema-driven mapper

- **7.1 Block-type dispatch.** The schema-derived whitelist from point 3
  above: given a parsed hyprlang block/directive, decide top-level call vs.
  `hl.config` section. Test: every section name in the real
  `hyprland.conf` gets routed the same way our own hand-migration already
  routed it (that hand-migration *is* the ground truth here).
- **7.2 Value/type coercion.** Schema-typed, not string-sniffed - this is
  the fix for the exact bug 3 of 4 competitor tools made independently
  (`animations.enabled` as a string). Reuses row 4/10's type-compat logic
  rather than a second copy of it.
- **7.3 Dispatcher/bind-flag rename tables.** The hand-curated tables from
  the section above, each entry checked against the schema at build/test
  time so a typo'd target path fails a test immediately rather than
  shipping silently wrong (this exact discipline is what all four
  competitor tools lacked).
- **7.4 Low-confidence TODO emission.** Anything the mapper can't resolve
  with full confidence (an unrecognized directive, an old dispatcher name
  not in the curated table, a `source` line) becomes a clearly-marked
  comment in the output, never a silent guess. This is the single biggest
  differentiator from the four existing tools per the code-reading done on
  them earlier in this project - EIonTusk's does this reasonably, the
  other three don't.
- **7.5 Wire it into the CLI.** `hyprvalidate convert <file.conf>`. Runs
  the row-2 `luac` gate **and** the full checker (rows 4/9/10) on its own
  output before returning success - if the converter's own output fails
  its own validator, that's a converter bug, not something to hand the
  user silently.

## The test oracle we already have for free

`configs/hyprland.conf` (the real original) and `configs/hyprland.lua` /
`configs/hyprland-lua/*.lua` (the hand-migrated, already schema-validated
result from earlier in this project) are a matched pair. Once the
converter exists: run it on `hyprland.conf`, diff the result against the
hand-migrated version (not expecting a byte-identical match, but expecting
semantic agreement on every symbol/key/value), and separately run
`hyprvalidate check` on the converter's own output expecting zero findings.
This is a stronger end-to-end test than anything available to any of the
four existing tools, because we already know the correct answer for this
one real, non-trivial config.

## Explicitly not decided here

- `--fix` mode scope - separate, still open, not part of this plan.
- Whether/when to contribute anything upstream - not a goal of this
  project per earlier discussion, not revisited here.
