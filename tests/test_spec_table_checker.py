"""Tests for the spec-table field checker.

Motivated by a real gap found by re-examining test evidence: hl.monitor's
spec-table contents were never checked, only its existence and arity.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FIXTURES = Path(__file__).parent / "fixtures"
# Prefer the live installed stub; fall back to the committed snapshot so the
# suite runs in CI and on machines without Hyprland installed.
_LIVE_STUB = Path("/usr/share/hypr/stubs/hl.meta.lua")
SCHEMA_PATH = str(_LIVE_STUB if _LIVE_STUB.is_file() else Path(__file__).parent.parent / "schema.json")

from luaparser import ast as luaast

from hyprvalidate.schema.extractor import load_schema
from hyprvalidate import checker
from hyprvalidate.checker import FindingKind, _check_spec_table

REPO_ROOT = Path(__file__).parent.parent
HYPRLAND_LUA_DIR = FIXTURES / "hyprland-lua"


def _schema():
    assert Path(SCHEMA_PATH).is_file(), f"expected the installed stub at {SCHEMA_PATH}"
    return load_schema(SCHEMA_PATH)


def test_monitor_with_invented_field_is_flagged():
    """The exact motivating gap: 'resolution' isn't a real HL.MonitorSpec
    field (the real one is 'mode') - was silently accepted before this row."""
    schema = _schema()
    findings = checker.check_source(
        schema, 'hl.monitor({ resolution = "preferred", position = "auto", scale = 1 })'
    )
    spec_findings = [f for f in findings if f.kind == FindingKind.UNKNOWN_SPEC_FIELD]
    assert len(spec_findings) == 1
    assert "resolution" in spec_findings[0].message
    assert "HL.MonitorSpec" in spec_findings[0].message


def test_monitor_with_real_fields_is_not_flagged():
    schema = _schema()
    findings = checker.check_source(
        schema, 'hl.monitor({ mode = "1920x1080@144", output = "eDP-1", position = "0x0", scale = 1 })'
    )
    assert findings == []


def test_bind_opts_with_the_exact_historical_mouse_bug_is_flagged():
    """'mouse' is not a real HL.BindOptions field (confirmed earlier this
    project, fixed in the real config to use 'drag' instead) - this is the
    exact bug class this row exists to catch on someone else's config."""
    schema = _schema()
    findings = checker.check_source(
        schema, "hl.bind('SUPER + mouse:272', hl.dsp.window.drag(), { mouse = true })"
    )
    spec_findings = [f for f in findings if f.kind == FindingKind.UNKNOWN_SPEC_FIELD]
    assert len(spec_findings) == 1
    assert "mouse" in spec_findings[0].message
    assert "HL.BindOptions" in spec_findings[0].message


def test_bind_opts_with_the_real_fix_is_not_flagged():
    schema = _schema()
    findings = checker.check_source(
        schema, "hl.bind('SUPER + mouse:272', hl.dsp.window.drag(), { drag = true })"
    )
    assert findings == []


def test_device_with_wrong_field_name_is_flagged():
    schema = _schema()
    findings = checker.check_source(
        schema, 'hl.device({ name = "epic-mouse-v1", speed = 5 })'  # real field is "sensitivity"
    )
    spec_findings = [f for f in findings if f.kind == FindingKind.UNKNOWN_SPEC_FIELD]
    assert len(spec_findings) == 1
    assert "speed" in spec_findings[0].message


def test_gesture_with_typo_field_name_is_flagged():
    schema = _schema()
    findings = checker.check_source(
        schema, 'hl.gesture({ finger = 3, direction = "horizontal", action = "workspace" })'
    )
    spec_findings = [f for f in findings if f.kind == FindingKind.UNKNOWN_SPEC_FIELD]
    assert len(spec_findings) == 1
    assert "finger" in spec_findings[0].message


def test_window_rule_is_deliberately_excluded_even_with_dynamic_fields():
    """Locks in the exclusion found by this file's own regression test:
    HL.WindowRuleSpec only types 3 universal fields - move/float/workspace
    etc are real, valid, per-rule-type fields the stub doesn't enumerate.
    Must NOT be flagged, unlike layer_rule/workspace_rule which are fully
    typed and DO get checked."""
    schema = _schema()
    findings = checker.check_source(
        schema,
        'hl.window_rule({ name = "x", match = { class = "foo" }, move = "20 20", float = true, workspace = "special:x", suppress_event = "maximize", no_focus = true })',
    )
    assert findings == []


def test_type_mismatch_inside_a_spec_table_is_flagged():
    schema = _schema()
    findings = checker.check_source(
        schema, 'hl.monitor({ mode = "1920x1080", output = 123 })'  # output expects string
    )
    type_findings = [f for f in findings if f.kind == FindingKind.TYPE_MISMATCH]
    assert len(type_findings) == 1
    assert "output" in type_findings[0].message


def test_hl_config_is_untouched_by_this_row_no_double_reporting():
    """hl.config keeps using its own row-4 mechanism - a bad top-level key
    there should produce exactly one finding (UNKNOWN_CONFIG_KEY), not also
    a duplicate UNKNOWN_SPEC_FIELD from this row."""
    schema = _schema()
    findings = checker.check_source(schema, "hl.config({ generall = { gaps_in = 5 } })")
    assert len(findings) == 1
    assert findings[0].kind == FindingKind.UNKNOWN_CONFIG_KEY


def test_recursion_into_a_nested_class_field_works():
    """None of the real target functions happen to have a field typed as
    another *named class* (as opposed to a union alias) in practice, so
    this exercises _check_spec_table's recursion directly with two
    unrelated real schema classes, to prove the mechanism itself is
    correct rather than pretending it's exercised by a real Hyprland call."""
    schema = _schema()
    # Borrow a real nested-class pair that exists in the schema: HL.ConfigOpt
    # nests HL.ConfigOpt.General - reuse that relationship structurally,
    # independent of the hl.config exclusion (calling this helper directly,
    # not through check_source/hl.config's own path).
    tree = luaast.parse("t = { general = { gaps_in = 5, notarealfield = 1 } }")
    from luaparser.astnodes import LocalAssign, Assign, Table

    assign = next(n for n in luaast.walk(tree) if isinstance(n, Assign))
    table = assign.values[0]
    findings = _check_spec_table(schema, table, "HL.ConfigOpt", None)
    kinds_and_msgs = [(f.kind, f.message) for f in findings]
    assert (FindingKind.UNKNOWN_SPEC_FIELD, "'notarealfield' is not a field of HL.ConfigOpt.General") in kinds_and_msgs


def test_the_projects_own_real_migrated_config_still_has_zero_findings():
    """Regression: this row must not introduce false positives against
    real, already-verified-correct usage."""
    schema = _schema()
    from hyprvalidate.luaast import reader

    all_findings = []
    for lua_file in sorted(HYPRLAND_LUA_DIR.glob("*.lua")):
        tree = reader.parse_file(lua_file)
        findings = checker.check(schema, tree)
        for f in findings:
            all_findings.append((lua_file.name, f))

    assert all_findings == [], f"unexpected findings in real config: {all_findings}"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all tests passed")
