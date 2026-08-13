"""Tests for the Lua reader (docs/PLAN.md row 3): parsing + the two
schema-agnostic utilities (dotted-name resolution, literal resolution).
Deliberately does not test any schema cross-referencing - that's row 4.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FIXTURES = Path(__file__).parent / "fixtures"
# Prefer the live installed stub; fall back to the committed snapshot so the
# suite runs in CI and on machines without Hyprland installed.
_LIVE_STUB = Path("/usr/share/hypr/stubs/hl.meta.lua")
SCHEMA_PATH = str(_LIVE_STUB if _LIVE_STUB.is_file() else Path(__file__).parent.parent / "schema.json")

from luaparser.astnodes import Call, Method, Fornum, Function, AnonymousFunction

from hyprvalidate.luaast import reader

REPO_ROOT = Path(__file__).parent.parent
REAL_KEYBINDS = FIXTURES / "hyprland-lua" / "keybinds.lua"


def test_parses_a_simple_config():
    tree = reader.parse("hl.env('XCURSOR_SIZE', '24')")
    calls = [n for n in reader.walk(tree) if isinstance(n, Call)]
    assert len(calls) == 1
    assert reader.resolve_dotted_name(calls[0].func) == "hl.env"


def test_invalid_lua_raises_lua_syntax_error():
    try:
        reader.parse("hl.bind( this is not lua {{{")
        assert False, "expected LuaSyntaxError"
    except reader.LuaSyntaxError:
        pass


def test_resolve_dotted_name_handles_deep_member_chains():
    tree = reader.parse("hl.dsp.window.close()")
    calls = [n for n in reader.walk(tree) if isinstance(n, Call)]
    assert reader.resolve_dotted_name(calls[0].func) == "hl.dsp.window.close"


def test_resolve_dotted_name_returns_none_for_non_chains():
    # A call itself is not a dotted-name chain.
    tree = reader.parse("hl.exec_cmd(foo())")
    calls = [n for n in reader.walk(tree) if isinstance(n, Call)]
    inner_call = calls[0].args[0]
    assert reader.resolve_dotted_name(inner_call) is None


def test_resolve_literal_covers_all_scalar_kinds():
    tree = reader.parse('local t = {"s", 5, 5.5, true, false, nil}')
    from luaparser.astnodes import LocalAssign, Table

    assign = next(n for n in reader.walk(tree) if isinstance(n, LocalAssign))
    table = assign.values[0]
    assert isinstance(table, Table)
    kinds = [reader.resolve_literal(f.value).kind for f in table.fields]
    assert kinds == ["string", "number", "number", "boolean", "boolean", "nil"]


def test_resolve_literal_returns_none_for_non_literals():
    tree = reader.parse("hl.exec_cmd(foo())")
    calls = [n for n in reader.walk(tree) if isinstance(n, Call)]
    inner_call = calls[0].args[0]
    assert reader.resolve_literal(inner_call) is None


def test_real_config_parses_and_reports_correct_line_numbers():
    """Regression anchor: the exact real-world constructs this project's
    own config uses (lambda-bodied binds, a numeric for-loop, deep member
    chains) must parse and be walkable."""
    assert REAL_KEYBINDS.is_file(), f"expected fixture at {REAL_KEYBINDS}"
    tree = reader.parse_file(REAL_KEYBINDS)

    calls = [n for n in reader.walk(tree) if isinstance(n, (Call, Method))]
    assert len(calls) > 90  # measured 101 when this test was written

    bind_calls = [c for c in calls if reader.resolve_dotted_name(c.func) == "hl.bind"]
    assert len(bind_calls) > 0

    lambda_binds = [
        c for c in bind_calls
        if any(isinstance(a, (Function, AnonymousFunction)) for a in c.args)
    ]
    assert len(lambda_binds) == 4  # M, V, G, ALT+space combined binds

    loops = [n for n in reader.walk(tree) if isinstance(n, Fornum)]
    assert len(loops) == 1  # the mainMod+[0-9] workspace-switch loop

    # first hl.bind(...) in the file is on line 4 - anchors that line
    # tracking survived the wrapper, not just luaparser itself.
    first_bind = min(bind_calls, key=lambda c: c.first_token.line)
    assert first_bind.first_token.line == 4


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all tests passed")
