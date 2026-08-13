"""Tests for the call-shape (arity) checker (docs/PLAN.md row 9).

Motivated by a real gap found in this project: hl.monitor(nil, {...}) in a
GPT-fabricated test config resolved as a valid symbol (it is) but was never
checked against its own 1-required-parameter signature - this closes it.
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
from hyprvalidate.checker import FindingKind, parse_fun_signature

REPO_ROOT = Path(__file__).parent.parent
HYPRLAND_LUA_DIR = FIXTURES / "hyprland-lua"


def _schema():
    assert Path(SCHEMA_PATH).is_file(), f"expected the installed stub at {SCHEMA_PATH}"
    return load_schema(SCHEMA_PATH)


# --- signature parsing -------------------------------------------------

def test_parses_named_params_with_trailing_optional():
    sig = parse_fun_signature("fun(keys: string, dispatcher: HL.Dispatcher|function, opts?: HL.BindOptions): HL.Keybind")
    assert [p.name for p in sig.params] == ["keys", "dispatcher", "opts"]
    assert [p.optional for p in sig.params] == [False, False, True]
    assert sig.has_vararg is False


def test_parses_untyped_variadic_as_no_named_params():
    sig = parse_fun_signature("fun(...): any")
    assert sig.params == []
    assert sig.has_vararg is True


def test_handles_a_nested_fun_type_as_a_param_without_breaking_on_its_parens():
    """hl.on's signature has a function-typed second param - naive paren
    splitting would truncate at the first ')' inside `cb: fun(...)`."""
    sig = parse_fun_signature("fun(event: HL.EventName, cb: fun(...)): HL.EventSubscription")
    assert [p.name for p in sig.params] == ["event", "cb"]
    assert sig.has_vararg is False


def test_non_function_type_expr_returns_none():
    assert parse_fun_signature("boolean") is None
    assert parse_fun_signature("string|HL.Gradient") is None


# --- the actual checker, against the real schema -----------------------

def test_monitor_called_with_extra_positional_arg_is_flagged():
    """The exact motivating bug: hl.monitor(spec) takes ONE argument;
    calling it as hl.monitor(nil, {...}) passes two."""
    schema = _schema()
    findings = checker.check_source(
        schema, 'hl.monitor(nil, { output = "eDP-1" })'
    )
    arity = [f for f in findings if f.kind == FindingKind.ARITY_MISMATCH]
    assert len(arity) == 1
    assert "at most 1" in arity[0].message


def test_monitor_called_correctly_is_not_flagged():
    schema = _schema()
    findings = checker.check_source(schema, 'hl.monitor({ output = "eDP-1" })')
    assert findings == []


def test_bind_missing_required_dispatcher_is_flagged():
    schema = _schema()
    findings = checker.check_source(schema, "hl.bind('SUPER + Q')")
    arity = [f for f in findings if f.kind == FindingKind.ARITY_MISMATCH]
    assert len(arity) == 1
    assert "at least 2" in arity[0].message


def test_bind_with_optional_opts_arg_is_not_flagged():
    schema = _schema()
    findings = checker.check_source(
        schema, "hl.bind('SUPER + Q', hl.dsp.window.close(), { locked = true })"
    )
    assert findings == []


def test_untyped_variadic_function_is_never_arity_checked():
    """hl.env is fun(...): any - no named params to check against, so any
    argument count is accepted, deliberately."""
    schema = _schema()
    findings = checker.check_source(schema, "hl.env('A', 'B', 'C', 'D')")
    assert findings == []


def test_the_projects_own_real_migrated_config_still_has_zero_findings():
    """Regression: arity checking must not introduce false positives
    against real, already-verified-correct usage."""
    schema = _schema()
    assert HYPRLAND_LUA_DIR.is_dir(), f"expected fixture dir at {HYPRLAND_LUA_DIR}"

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
