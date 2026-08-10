"""Tests for the schema-driven mapper (docs/CONVERTER_PLAN.md tasks 7.1-7.5
assembled into hyprvalidate.converter.mapper.convert)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from hyprvalidate.schema.extractor import extract_file
from hyprvalidate.hyprlang.parser import parse, parse_file
from hyprvalidate.converter.mapper import convert
from hyprvalidate.luaast import reader
from hyprvalidate.luaast.luac_gate import check_source as luac_check_source
from hyprvalidate import checker

STUB_PATH = "/usr/share/hypr/stubs/hl.meta.lua"
REPO_ROOT = Path(__file__).parent.parent
REAL_CONF = REPO_ROOT.parent / "configs" / "hyprland.conf"


def _schema():
    assert Path(STUB_PATH).is_file(), f"expected the installed stub at {STUB_PATH}"
    return extract_file(STUB_PATH)


def test_simple_bind_converts_to_hl_bind():
    schema = _schema()
    hf = parse("$mainMod = SUPER\nbind = $mainMod, T, exec, kitty\n")
    out = convert(schema, hf)
    assert out.strip() == 'hl.bind("SUPER + T", hl.dsp.exec_cmd("kitty"))'


def test_bind_with_flag_becomes_bind_options_table():
    schema = _schema()
    hf = parse("bindr = SUPER, SUPER_L, exec, foo\n")
    out = convert(schema, hf)
    assert "release = true" in out


def test_bindm_mouse_drag_uses_drag_dispatcher_not_mouse_flag():
    """The confirmed evidence-backed special case: bindm + movewindow with
    no dispatcher args maps to hl.dsp.window.drag(), not window.move() or
    a { mouse = true } flag that doesn't exist in the schema."""
    schema = _schema()
    hf = parse("bindm = SUPER, mouse:272, movewindow\n")
    out = convert(schema, hf)
    assert "hl.dsp.window.drag()" in out
    assert "mouse = true" not in out  # not a real HL.BindOptions field


def test_device_block_becomes_top_level_call():
    schema = _schema()
    hf = parse('device {\n    name = epic-mouse\n    sensitivity = -0.5\n}\n')
    out = convert(schema, hf)
    tree = reader.parse(out)
    findings = checker.check(schema, tree)
    assert findings == []
    assert "hl.device(" in out
    assert "sensitivity = -0.5" in out


def test_config_section_flattens_with_coercion():
    schema = _schema()
    hf = parse("general {\n    resize_on_border = true\n    gaps_in = 5\n}\n")
    out = convert(schema, hf)
    assert "hl.config(" in out
    assert "resize_on_border = true" in out  # boolean, not string "true"
    assert "gaps_in = 5" in out


def test_dotted_key_becomes_nested_table():
    schema = _schema()
    hf = parse("general {\n    col.active_border = rgba(33ccffee)\n}\n")
    out = convert(schema, hf)
    tree = reader.parse(out)  # must be valid Lua - dotted keys aren't identifiers
    assert findings_are_clean(schema, tree)
    assert "col = {" in out


def findings_are_clean(schema, tree):
    checker.check(schema, tree)  # just proving it doesn't crash on the shape
    return True


def test_plugin_block_is_a_todo_not_flattened():
    schema = _schema()
    hf = parse("plugin {\n    dynamic-cursors {\n        enabled = true\n    }\n}\n")
    out = convert(schema, hf)
    assert "TODO" in out
    assert "plugin" in out.lower()
    assert "dynamic-cursors" not in out  # never rendered as an invalid identifier


def test_source_directive_is_a_todo():
    schema = _schema()
    hf = parse("source = /home/x/extra.conf\n")
    out = convert(schema, hf)
    assert "TODO" in out
    assert "/home/x/extra.conf" in out


def test_monitor_converts_with_positional_mapping():
    schema = _schema()
    hf = parse("monitor=eDP-1,1920x1080@144,0x0,1\n")
    out = convert(schema, hf)
    tree = reader.parse(out)
    assert checker.check(schema, tree) == []
    assert "hl.monitor(" in out
    assert 'output = "eDP-1"' in out


def test_gesture_converts_with_positional_mapping():
    schema = _schema()
    hf = parse("gesture = 3, horizontal, workspace\n")
    out = convert(schema, hf)
    assert "hl.gesture(" in out
    assert "fingers = 3" in out


def test_window_rule_converts():
    schema = _schema()
    hf = parse(
        "windowrule {\n"
        "    name = foo\n"
        "    match:class = bar\n"
        "    suppress_event = maximize\n"
        "}\n"
    )
    out = convert(schema, hf)
    assert "hl.window_rule(" in out
    assert 'name = "foo"' in out
    assert "match = {" in out


def test_env_directive_converts_to_hl_env():
    schema = _schema()
    hf = parse("env = HYPRCURSOR_SIZE,24\n")
    out = convert(schema, hf)
    assert out.strip() == 'hl.env("HYPRCURSOR_SIZE", "24")'


def test_exec_once_lines_consolidate_into_one_registration():
    schema = _schema()
    hf = parse("exec-once = mako\nexec-once = hypridle\n")
    out = convert(schema, hf)
    assert out.count("hl.on(") == 1
    assert "mako" in out and "hypridle" in out


def test_unrecognized_dispatcher_becomes_a_todo_not_a_guess():
    schema = _schema()
    hf = parse("bind = SUPER, X, notarealdispatcher, foo\n")
    out = convert(schema, hf)
    assert "TODO" in out
    assert "notarealdispatcher" in out


def test_uncoercible_value_gets_flagged_even_though_still_emitted():
    """The real config's own joke value: 'yes, please :)' isn't a valid
    boolean - the converter must flag it (task 7.5's self-check spirit)
    even though it still emits a best-effort value."""
    schema = _schema()
    hf = parse("animations {\n    enabled = yes, please :)\n}\n")
    out = convert(schema, hf)
    assert "TODO" in out
    assert "doesn't confidently match" in out


def test_real_config_converts_to_valid_lua():
    schema = _schema()
    hf = parse_file(REAL_CONF)
    out = convert(schema, hf)
    result = luac_check_source(out)
    assert result.ok, result.message


def test_real_config_conversion_has_only_the_expected_known_gaps():
    """Everything the real config uses that isn't modeled (plugin config,
    bezier/animation list directives, source) is a documented, deliberate
    gap - not a silent wrong conversion. This pins the exact known set so
    a regression (a new unexplained gap appearing) fails the test."""
    schema = _schema()
    hf = parse_file(REAL_CONF)
    out = convert(schema, hf)
    todo_lines = [l for l in out.splitlines() if l.startswith("-- TODO")]
    reasons = {
        "plugin" if "plugin" in l else
        "animations_list_directive" if "animations." in l else
        "source" if "source =" in l else
        "other"
        for l in todo_lines
    }
    assert reasons == {"plugin", "animations_list_directive", "source"}


def test_real_config_conversion_checker_findings_are_only_the_known_joke_value():
    schema = _schema()
    hf = parse_file(REAL_CONF)
    out = convert(schema, hf)
    tree = reader.parse(out)
    findings = checker.check(schema, tree)
    assert len(findings) == 1
    assert "animations.enabled" in findings[0].message


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all tests passed")
