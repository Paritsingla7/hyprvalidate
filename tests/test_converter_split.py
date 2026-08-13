"""Tests for modular --split conversion (docs/PLAN.md row 11, task 8.1).

The load-bearing tests here are the two invariants that make bucketing
statements into separate files safe at all:
  1. nothing is lost or duplicated, and
  2. relative order is preserved within each module,
because order carries meaning in hyprlang (repeated config keys, duplicate
binds, window-rule precedence). Both are asserted mechanically rather than
argued in a comment.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FIXTURES = Path(__file__).parent / "fixtures"
# Prefer the live installed stub; fall back to the committed snapshot so the
# suite runs in CI and on machines without Hyprland installed.
_LIVE_STUB = Path("/usr/share/hypr/stubs/hl.meta.lua")
SCHEMA_PATH = str(_LIVE_STUB if _LIVE_STUB.is_file() else Path(__file__).parent.parent / "schema.json")

from hyprvalidate.schema.extractor import load_schema
from hyprvalidate.hyprlang.parser import parse, parse_file
from hyprvalidate.converter.mapper import convert, convert_split, _convert_items
from hyprvalidate.luaast.luac_gate import check_source as luac_check_source
from hyprvalidate import checker

REPO_ROOT = Path(__file__).parent.parent
REAL_CONF = FIXTURES / "hyprland.conf"


def _schema():
    assert Path(SCHEMA_PATH).is_file(), f"expected the installed stub at {SCHEMA_PATH}"
    return load_schema(SCHEMA_PATH)


def test_no_statement_is_lost_or_duplicated_by_bucketing():
    """Invariant 1: every converted statement lands in exactly one module."""
    schema = _schema()
    hf = parse_file(REAL_CONF)
    items = _convert_items(schema, hf)

    per_module = {}
    for i in items:
        per_module.setdefault(i.module, []).append(i)

    assert sum(len(v) for v in per_module.values()) == len(items)
    seen = [id(i) for v in per_module.values() for i in v]
    assert len(seen) == len(set(seen))


def test_relative_order_is_preserved_within_each_module():
    """Invariant 2: within a module, statements keep their source order -
    this is what makes duplicate binds, repeated config keys, and
    window-rule precedence survive the split."""
    schema = _schema()
    hf = parse_file(REAL_CONF)
    items = _convert_items(schema, hf)

    per_module = {}
    for idx, i in enumerate(items):
        per_module.setdefault(i.module, []).append((idx, i.line))

    for module, entries in per_module.items():
        positions = [p for p, _ in entries]
        assert positions == sorted(positions), f"{module} reordered relative to source"
        lines = [ln for _, ln in entries if ln is not None]
        assert lines == sorted(lines), f"{module} source lines out of order"


def test_every_emitted_module_is_required_by_the_entry_file():
    """A module file that nothing require()s is silently dropped config -
    the worst possible failure mode for this feature."""
    schema = _schema()
    hf = parse_file(REAL_CONF)
    files = convert_split(schema, hf)

    entry = files["hyprland.lua"]
    required = {
        line.split('"')[1] for line in entry.splitlines() if line.startswith("require(")
    }
    emitted = {name[:-len(".lua")] for name in files if name != "hyprland.lua"}
    assert required == emitted


def test_entry_file_is_always_present_even_for_a_trivial_config():
    schema = _schema()
    files = convert_split(schema, parse("bind = SUPER, Q, killactive,\n"))
    assert "hyprland.lua" in files
    assert 'require("keybinds")' in files["hyprland.lua"]


def test_modules_appear_in_original_source_order():
    schema = _schema()
    hf = parse(
        "windowrule {\n    name = a\n    match:class = x\n}\n"
        "bind = SUPER, Q, killactive,\n"
        "monitor=eDP-1,1920x1080@144,0x0,1\n"
    )
    files = convert_split(schema, hf)
    entry = files["hyprland.lua"]
    order = [l.split('"')[1] for l in entry.splitlines() if l.startswith("require(")]
    assert order == ["windowrules", "keybinds", "monitors"]


def test_binds_all_land_in_keybinds():
    schema = _schema()
    hf = parse("bind = SUPER, Q, killactive,\nbindr = SUPER, W, killactive,\n")
    files = convert_split(schema, hf)
    assert set(files) == {"hyprland.lua", "keybinds.lua"}
    assert files["keybinds.lua"].count("hl.bind(") == 2


def test_config_sections_group_into_appearance():
    schema = _schema()
    hf = parse(
        "general {\n    gaps_in = 5\n}\n"
        "decoration {\n    rounding = 10\n}\n"
    )
    files = convert_split(schema, hf)
    assert set(files) == {"hyprland.lua", "appearance.lua"}
    assert files["appearance.lua"].count("hl.config(") == 2


def test_unlisted_config_section_gets_its_own_file_not_a_guessed_bucket():
    """Sections this project has no worked example for aren't forced into
    an invented taxonomy - they get a file named after themselves."""
    schema = _schema()
    hf = parse("xwayland {\n    force_zero_scaling = true\n}\n")
    files = convert_split(schema, hf)
    assert "xwayland.lua" in files


def test_device_blocks_get_their_own_file():
    """Deliberate divergence from this project's own hand-migration, which
    split device blocks across monitors.lua and input.lua by reading intent
    (output= vs sensitivity=). A tool shouldn't guess intent, so all device
    blocks go to one predictable place."""
    schema = _schema()
    hf = parse(
        'device {\n    name = a\n    output = HDMI-A-1\n}\n'
        'device {\n    name = b\n    sensitivity = -0.5\n}\n'
    )
    files = convert_split(schema, hf)
    assert "devices.lua" in files
    assert files["devices.lua"].count("hl.device(") == 2


def test_source_directive_todo_goes_to_the_entry_file():
    schema = _schema()
    files = convert_split(schema, parse("source = /home/x/extra.conf\n"))
    assert "TODO" in files["hyprland.lua"]
    assert "/home/x/extra.conf" in files["hyprland.lua"]


def test_every_file_from_the_real_config_is_valid_lua():
    schema = _schema()
    files = convert_split(schema, parse_file(REAL_CONF))
    for name, src in files.items():
        result = luac_check_source(src)
        assert result.ok, f"{name}: {result.message}"


def test_real_config_split_findings_match_the_flat_conversion():
    """The split must not introduce or hide findings relative to converting
    the same file flat - same schema issues, same count."""
    schema = _schema()
    hf = parse_file(REAL_CONF)

    flat_findings = checker.check_source(schema, convert(schema, hf))
    split_findings = [
        f for src in convert_split(schema, hf).values()
        for f in checker.check_source(schema, src)
    ]
    assert len(split_findings) == len(flat_findings)
    assert {f.message for f in split_findings} == {f.message for f in flat_findings}


def test_real_config_produces_the_expected_module_set():
    schema = _schema()
    files = convert_split(schema, parse_file(REAL_CONF))
    assert set(files) == {
        "hyprland.lua", "autostart.lua", "plugins.lua", "monitors.lua",
        "devices.lua", "input.lua", "env.lua", "appearance.lua",
        "keybinds.lua", "windowrules.lua",
    }


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all tests passed")
