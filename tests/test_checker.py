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


def test_generic_table_type_spec_field_accepts_a_table_value():
    """HL.LayerRuleSpec.match is typed `table<string, string|boolean>` -
    LuaLS's generic map syntax, not `string|HL.Gradient` (a class
    alternative) or a `{...}` literal shape. `_has_table_alternative`
    didn't recognize "table<...>" at all, so this was a false positive on
    every real layer rule with a match table - found by running
    hyprvalidate against two independent real-world Hyprland Lua configs
    (Garuda Linux's distribution settings and the sea-shell project), both
    of which use exactly this pattern and both of which hit it."""
    schema = _schema()
    findings = checker.check_source(
        schema,
        'hl.layer_rule({ name = "blur-all-layers", match = { namespace = ".*" } })',
    )
    assert findings == []


def test_has_table_alternative_recognizes_every_real_table_shaped_form():
    """The schema uses three distinct textual shapes for "this alternative
    is a table, not a scalar": a class reference (`HL.Gradient`), a
    `{...}` literal shape, and LuaLS's generic `table<...>` / bare `table`
    form - the last of which was missing before this fix. A genuinely
    scalar-only type must still correctly return False, or every
    type-mismatch check in this module goes blind."""
    assert checker._has_table_alternative("string|HL.Gradient")
    assert checker._has_table_alternative("integer|table")
    assert checker._has_table_alternative("table<string, string|boolean>")
    assert not checker._has_table_alternative("boolean")
    assert not checker._has_table_alternative("string")


def test_non_literal_config_value_is_accepted_uncritically():
    """A variable reference can't be statically type-checked - accepted,
    not flagged, per the documented scope limitation."""
    schema = _schema()
    findings = checker.check_source(
        schema, "local x = true\nhl.config({ animations = { enabled = x } })"
    )
    assert findings == []


def test_uncalled_dispatcher_factory_is_flagged():
    """Hyprland issue #15871 ("Improve lua error reporting"): binding to a
    factory without calling it, e.g. `hl.dsp.window.close` instead of
    `hl.dsp.window.close()`. Type-checks under the stub's
    `HL.Dispatcher|function` union (a bare function reference IS a
    `function`), so nothing else catches it - this is the dedicated check."""
    schema = _schema()
    findings = checker.check_source(schema, "hl.bind('SUPER + Q', hl.dsp.window.close)")
    assert len(findings) == 1
    assert findings[0].kind == FindingKind.UNCALLED_DISPATCHER
    assert "hl.dsp.window.close" in findings[0].message


def test_called_dispatcher_factory_is_not_flagged():
    schema = _schema()
    findings = checker.check_source(schema, "hl.bind('SUPER + Q', hl.dsp.window.close())")
    assert findings == []


def test_lambda_dispatcher_is_not_flagged():
    """The `function` alternative in `HL.Dispatcher|function` - a genuine
    lambda, not a bare factory reference - must not be flagged."""
    schema = _schema()
    findings = checker.check_source(
        schema, "hl.bind('SUPER + M', function()\n  hl.dispatch(hl.dsp.exec_cmd('x'))\nend)"
    )
    assert findings == []


def test_variable_holding_dispatcher_is_not_flagged():
    """A local variable can't be statically resolved to a factory
    reference - accepted, not flagged, same documented limitation as
    literal-value checking elsewhere in this module."""
    schema = _schema()
    findings = checker.check_source(
        schema, "local d = hl.dsp.window.close()\nhl.bind('SUPER + Q', d)"
    )
    assert findings == []


def test_duplicate_literal_bind_is_flagged():
    """Hyprland issue #15871: repeating keys in a bind."""
    schema = _schema()
    findings = checker.check_source(
        schema,
        "hl.bind('SUPER + Q', hl.dsp.window.close())\n"
        "hl.bind('SUPER + Q', hl.dsp.window.kill())\n",
    )
    assert len(findings) == 2
    assert all(f.kind == FindingKind.DUPLICATE_BIND for f in findings)
    assert {f.line for f in findings} == {1, 2}


def test_duplicate_bind_detected_across_string_concatenation():
    """`"SUPER" .. " + Q"` is a concat of only string literals - resolvable
    without evaluating the script, unlike a variable-based concat."""
    schema = _schema()
    findings = checker.check_source(
        schema,
        "hl.bind('SUPER' .. ' + Q', hl.dsp.window.close())\n"
        "hl.bind('SUPER + Q', hl.dsp.window.kill())\n",
    )
    assert len(findings) == 2
    assert all(f.kind == FindingKind.DUPLICATE_BIND for f in findings)


def test_unique_binds_are_not_flagged():
    schema = _schema()
    findings = checker.check_source(
        schema,
        "hl.bind('SUPER + Q', hl.dsp.window.close())\n"
        "hl.bind('SUPER + W', hl.dsp.window.kill())\n",
    )
    assert findings == []


def test_bind_with_variable_key_is_not_flagged_as_duplicate():
    """A `keys` expression involving a variable (the common real-world
    pattern, e.g. `mainMod .. " + Q"`) can't be resolved without
    evaluating the script - skipped, not guessed at, even if two such
    binds would in fact collide at runtime."""
    schema = _schema()
    findings = checker.check_source(
        schema,
        "local mainMod = 'SUPER'\n"
        "hl.bind(mainMod .. ' + Q', hl.dsp.window.close())\n"
        "hl.bind(mainMod .. ' + Q', hl.dsp.window.kill())\n",
    )
    assert findings == []


def test_unquoted_string_value_is_flagged_as_possible_missing_quotes():
    """The exact real-world bug in github.com/hyprwm/Hyprland#15727: a user
    migrating from the old .conf format wrote `accel_profile = flat`
    instead of `accel_profile = "flat"`. The bare identifier `flat` isn't
    defined anywhere, so it evaluates to nil at runtime, silently discarding
    the accel profile and changing their mouse sensitivity - and was only
    found by a stranger reading their config on GitHub."""
    schema = _schema()
    findings = checker.check_source(schema, "hl.config({ input = { accel_profile = flat } })")
    assert len(findings) == 1
    assert findings[0].kind == FindingKind.POSSIBLE_MISSING_QUOTES
    assert "accel_profile" in findings[0].message
    assert "flat" in findings[0].message


def test_correctly_quoted_string_value_is_not_flagged():
    schema = _schema()
    findings = checker.check_source(schema, 'hl.config({ input = { accel_profile = "flat" } })')
    assert findings == []


def test_bare_identifier_that_is_a_real_local_variable_is_not_flagged():
    """The legitimate pattern this check must not disturb: a config value
    that really is a variable reference to a defined local."""
    schema = _schema()
    findings = checker.check_source(
        schema,
        'local myProfile = "flat"\nhl.config({ input = { accel_profile = myProfile } })',
    )
    assert findings == []


def test_bare_identifier_defined_as_a_global_is_not_flagged():
    schema = _schema()
    findings = checker.check_source(
        schema,
        'myProfile = "flat"\nhl.config({ input = { accel_profile = myProfile } })',
    )
    assert findings == []


def test_bare_identifier_in_spec_table_is_also_flagged():
    """The same missing-quotes bug class inside a spec-table argument
    (hl.monitor's HL.MonitorSpec), not just a top-level hl.config block -
    the two mechanisms are checked by separate code paths in this module."""
    schema = _schema()
    findings = checker.check_source(schema, "hl.monitor({ mode = preferred })")
    assert len(findings) == 1
    assert findings[0].kind == FindingKind.POSSIBLE_MISSING_QUOTES
    assert "preferred" in findings[0].message


def test_colon_method_definition_does_not_crash_the_checker():
    """Regression: `Method` (a `function T:method() end` *definition*) has
    no `.func` attribute - it was previously grouped with `Call` for call
    detection and crashed with AttributeError on any config containing one.
    Real Hyprland configs don't define these, but the checker must not
    crash on arbitrary valid Lua rather than only the subset it expects."""
    schema = _schema()
    findings = checker.check_source(schema, "function T:method(x) end")
    assert findings == []


def test_colon_method_call_does_not_crash_the_checker():
    """The call-side counterpart: `obj:bar(1, 2)` parses as `Invoke`, not
    `Call`. Hyprland's own API is exclusively dot-style, so this harmlessly
    resolves as a non-hl.* call and produces no findings - the point is
    that it doesn't crash."""
    schema = _schema()
    findings = checker.check_source(schema, "obj = {}\nobj:bar(1, 2)")
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
