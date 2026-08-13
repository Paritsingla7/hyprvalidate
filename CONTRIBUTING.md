# Contributing

Thanks for looking. Bug reports about **wrong conversions** are the most
valuable thing you can send — this tool's whole job is being right about
Hyprland's API, so a case where it isn't is a real defect, not a nitpick.

## Reporting a bad conversion

Include:

1. The hyprlang snippet that went in (minimal is fine — a single `bind` line
   is a perfect report).
2. What hyprvalidate produced.
3. What it should have produced, if you know.
4. `hyprvalidate --version` and your Hyprland version.

If the tool emitted a `-- TODO(hyprvalidate convert):` comment, that's it
working as intended — it refuses to guess. Still worth reporting if you think
the case is confidently convertible.

## Setup

```bash
git clone https://github.com/Paritsingla7/hyprvalidate.git && cd hyprvalidate
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest tests/ -q
```

You do **not** need Hyprland installed. The suite prefers the live stub at
`/usr/share/hypr/stubs/hl.meta.lua` and falls back to the committed
`schema.json` snapshot, so it runs anywhere. `luac` (`pacman -S lua`) is
needed for the syntax-gate tests.

## The one rule that matters

**Never hardcode a name the schema can answer.**

This project exists because four other tools hand-typed Hyprland's dispatcher
and config-key names into tables that drifted from reality. If you're adding a
lookup, derive it from the schema.

Where hand-maintained knowledge genuinely is unavoidable — the *old* hyprlang
names have no representation in the new schema, so `converter/rename.py` has to
carry them — every entry must be **asserted against the schema in a test**:

```python
def test_every_dispatcher_rename_target_resolves_against_the_schema():
    for old_name, target in DISPATCHER_RENAME.items():
        is_valid, reason, _ = resolve_symbol(schema, target)
        assert is_valid, f"{old_name} -> {target}: {reason}"
```

A rename table without a test like this will drift. That's the exact bug class
this project was built to eliminate — please don't reintroduce it.

## Other expectations

- **Guess nothing.** If a conversion can't be resolved with confidence, emit a
  `TODO` comment. Silently-wrong output is worse than an obvious gap.
- **Tests use the real config.** `tests/fixtures/hyprland.conf` is a genuine
  527-line config with known ground-truth counts. Prefer asserting against it
  over synthetic examples.
- **Document scope decisions in the code.** Most modules have a docstring
  explaining what they deliberately *don't* handle and why. Keep that up —
  it's how the next person avoids re-litigating a settled decision.
- Match the surrounding style. There's no enforced formatter; the codebase is
  deliberately comment-heavy about *why*, not *what*.

## Updating the schema snapshot

If Hyprland's stub changes, regenerate the snapshot and rebuild the site
bundle:

```bash
python -m hyprvalidate.schema.extractor -o schema.json
python site/build_bundle.py
```

`tests/test_extractor.py` fails if `schema.json` has drifted from an installed
stub, so CI catches this.

## Pull requests

Run the tests, keep the diff scoped to one thing, and say in the description
what you verified rather than just what you changed.
