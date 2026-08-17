"""Tests for the schema-driven checker - the actual Validator logic. Uses
the real schema extracted from the installed stub,
same as the extractor's own tests, so these are checked against ground
truth, not a mock.
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
from hyprvalidate import checker
from hyprvalidate.checker import FindingKind

REPO_ROOT = Path(__file__).parent.parent
HYPRLAND_LUA_DIR = FIXTURES / "hyprland-lua"


def _schema():
    assert Path(SCHEMA_PATH).is_file(), f"expected the installed stub at {SCHEMA_PATH}"
    return load_schema(SCHEMA_PATH)


def test_valid_dispatcher_chain_produces_no_findings():
    schema = _schema()
    findings = checker.check_source(schema, "hl.bind('SUPER + Q', hl.dsp.window.close())")
    assert findings == []


def test_invented_dispatcher_name_is_flagged():
    """The exact class of bug found in real competitor tool output:
    hl.dsp.movefocus / hl.dsp.killactive don't exist in the real API."""
    schema = _schema()
    findings = checker.check_source(schema, "hl.bind('SUPER + left', hl.dsp.movefocus({l}))")
    assert len(findings) == 1
    assert findings[0].kind == FindingKind.UNKNOWN_SYMBOL
    assert "movefocus" in findings[0].message


def test_plugin_namespace_members_are_accepted_dynamically():
    schema = _schema()
    findings = checker.check_source(
        schema,
        "hl.config({ plugin = { dynamic_cursors = { enabled = true } } })",
    )
    assert findings == []


def test_config_boolean_key_with_correct_type_passes():
    schema = _schema()
    findings = checker.check_source(schema, "hl.config({ animations = { enabled = true } })")
    assert findings == []


def test_config_boolean_key_with_wrong_type_is_flagged():
    """The exact bug 3 of 4 real competitor tools made independently:
    animations.enabled given a string instead of a boolean."""
    schema = _schema()
    findings = checker.check_source(
        schema, 'hl.config({ animations = { enabled = "yes, please :)" } })'
    )
    assert len(findings) == 1
    assert findings[0].kind == FindingKind.TYPE_MISMATCH
    assert "animations.enabled" in findings[0].message


def test_unknown_config_key_is_flagged():
    schema = _schema()
    findings = checker.check_source(schema, "hl.config({ generall = { gaps_in = 5 } })")
    assert len(findings) == 1
    assert findings[0].kind == FindingKind.UNKNOWN_CONFIG_KEY
    assert "generall" in findings[0].message


def test_nested_section_recurses_and_checks_leaf_types():
    schema = _schema()
    findings = checker.check_source(
        schema, "hl.config({ general = { gaps_in = 5, gaps_out = 5 } })"
    )
    assert findings == []


def test_gradient_table_value_accepted_without_deep_structural_check():
    """general.col.active_border is typed string|HL.Gradient - a table
    value here is a legitimate alternative, not checked structurally."""
    schema = _schema()
    findings = checker.check_source(
        schema,
        'hl.config({ general = { col = { active_border = { colors = {"rgba(33ccffee)"}, angle = 45 } } } })',
    )
    assert findings == []


def test_non_literal_config_value_is_accepted_uncritically():
    """A variable reference can't be statically type-checked - accepted,
    not flagged, per the documented scope limitation."""
    schema = _schema()
    findings = checker.check_source(
        schema, "local x = true\nhl.config({ animations = { enabled = x } })"
    )
    assert findings == []


def test_the_projects_own_real_migrated_config_has_zero_findings():
    """End-to-end regression: every file in hyprland-lua/ was hand-verified
    against this same schema over the course of this project's own
    migration. If the checker finds something there, either the checker or
    that migration has a bug - this is the strongest test in the suite."""
    schema = _schema()
    assert HYPRLAND_LUA_DIR.is_dir(), f"expected fixture dir at {HYPRLAND_LUA_DIR}"

    all_findings = []
    for lua_file in sorted(HYPRLAND_LUA_DIR.glob("*.lua")):
        tree = __import__(
            "hyprvalidate.luaast.reader", fromlist=["parse_file"]
        ).parse_file(lua_file)
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
