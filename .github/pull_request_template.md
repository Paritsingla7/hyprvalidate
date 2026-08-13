## What this changes

<!-- One or two sentences. -->

## What you verified

<!-- Not what you changed - what you actually ran and observed.
     e.g. "converted tests/fixtures/hyprland.conf, checked the output, 0 findings" -->

- [ ] `pytest tests/ -q` passes
- [ ] If this touches a rename table, its schema-assertion test still passes
- [ ] If this touches a bundled module or `schema.json`, I re-ran `python site/build_bundle.py`
