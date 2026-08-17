"""Tests for the Lua AST builder helpers."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from luaparser.astnodes import Assign, Call, Name, Table

from hyprvalidate.luaast import reader
from hyprvalidate.luaast.writer import hlcall, chunk, to_source, luatable, member, anon_function


def _roundtrip(*statements):
    """Build, render, re-parse, return the reparsed tree - the actual
    round-trip oracle: does what we wrote mean what we intended, per the
    Lua reader's own parsing, not just "did it not crash"."""
    src = to_source(chunk(list(statements)))
    return src, reader.parse(src)


def test_simple_call_round_trips():
    call = hlcall("hl.window_rule", {"name": "foo", "enabled": True})
    src, tree = _roundtrip(call)
    reparsed_call = next(n for n in reader.walk(tree) if isinstance(n, Call))
    assert reader.resolve_dotted_name(reparsed_call.func) == "hl.window_rule"
    table = reparsed_call.args[0]
    assert isinstance(table, Table)
    values = {f.key.id: reader.resolve_literal(f.value) for f in table.fields}
    assert values["name"].value == "foo"
    assert values["enabled"].value is True


def test_nested_table_round_trips():
    call = hlcall("hl.monitor", {"mode": "1920x1080@144", "output": "eDP-1", "scale": 1})
    src, tree = _roundtrip(call)
    reparsed_call = next(n for n in reader.walk(tree) if isinstance(n, Call))
    table = reparsed_call.args[0]
    values = {f.key.id: reader.resolve_literal(f.value) for f in table.fields}
    assert values["mode"].value == "1920x1080@144"
    assert values["output"].value == "eDP-1"
    assert values["scale"].value == 1


def test_bind_shaped_call_round_trips():
    call = hlcall("hl.bind", "SUPER, T, exec, kitty", {"release": True})
    src, tree = _roundtrip(call)
    reparsed_call = next(n for n in reader.walk(tree) if isinstance(n, Call))
    assert reader.resolve_literal(reparsed_call.args[0]).value == "SUPER, T, exec, kitty"


def test_member_chain_builds_dotted_access():
    # A bare dotted-access chain isn't a valid standalone Lua statement -
    # assign it, then confirm the reader's own dotted-name resolver agrees
    # with what was intended, closing the loop through the reader rather
    # than just eyeballing rendered text.
    node = member("hl", "dsp", "window", "close")
    assign = Assign(targets=[Name(identifier="x")], values=[node])
    src, tree = _roundtrip(assign)
    reparsed = next(n for n in reader.walk(tree) if isinstance(n, Assign))
    assert reader.resolve_dotted_name(reparsed.values[0]) == "hl.dsp.window.close"


def test_string_with_special_characters_escapes_and_round_trips():
    call = hlcall("hl.exec", 'echo "hi" \\ done')
    src, tree = _roundtrip(call)
    reparsed_call = next(n for n in reader.walk(tree) if isinstance(n, Call))
    assert reader.resolve_literal(reparsed_call.args[0]).value == 'echo "hi" \\ done'


def test_array_style_table_round_trips():
    call = hlcall("hl.dsp.workspace.set", 1)
    table_call = hlcall("hl.gesture", luatable([3, "horizontal", "workspace"]))
    src, tree = _roundtrip(table_call)
    reparsed_call = next(n for n in reader.walk(tree) if isinstance(n, Call))
    table = reparsed_call.args[0]
    values = [reader.resolve_literal(f.value).value for f in table.fields]
    assert values == [3, "horizontal", "workspace"]


def test_non_identifier_dict_key_uses_bracketed_string_syntax():
    """Real hyprlang keys like 'col.active_border' aren't valid bare Lua
    identifiers (dots aren't allowed) - found running the converter
    against the real config, not anticipated up front."""
    call = hlcall("hl.config", {"col.active_border": "x", "normal": 1})
    src, tree = _roundtrip(call)
    assert '["col.active_border"]' in src
    reparsed_call = next(n for n in reader.walk(tree) if isinstance(n, Call))
    table = reparsed_call.args[0]
    values = {}
    for f in table.fields:
        key = f.key.s.decode() if hasattr(f.key, "s") else f.key.id
        values[key] = reader.resolve_literal(f.value).value
    assert values == {"col.active_border": "x", "normal": 1}


def test_anon_function_wraps_statements_and_round_trips():
    fn = anon_function([hlcall("hl.exec_cmd", "mako"), hlcall("hl.exec_cmd", "hypridle")])
    call = hlcall("hl.on", "hyprland.start", fn)
    src, tree = _roundtrip(call)
    reparsed_call = next(n for n in reader.walk(tree) if isinstance(n, Call))
    assert reader.resolve_dotted_name(reparsed_call.func) == "hl.on"
    assert reader.resolve_literal(reparsed_call.args[0]).value == "hyprland.start"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all tests passed")
