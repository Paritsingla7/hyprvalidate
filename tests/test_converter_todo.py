"""Tests for low-confidence TODO emission (docs/CONVERTER_PLAN.md task 7.4)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from hyprvalidate.converter.todo import (
    TodoNote,
    format_todo,
    check_dispatcher,
    check_bind_flag,
    check_source_directive,
    render_program,
)
from hyprvalidate.luaast.writer import hlcall


def test_known_dispatcher_needs_no_todo():
    assert check_dispatcher("killactive") is None


def test_unknown_dispatcher_gets_a_todo():
    note = check_dispatcher("somemadeupdispatcher", line=42)
    assert note is not None
    assert note.line == 42
    assert "somemadeupdispatcher" in note.detail


def test_known_bind_flag_needs_no_todo():
    assert check_bind_flag("l") is None
    assert check_bind_flag("e") is None


def test_shape_changing_bind_flag_is_flagged_as_such():
    note = check_bind_flag("m", line=7)
    assert note is not None
    assert note.reason == "unsupported_bind_flag"
    assert "shape" in note.detail


def test_unknown_bind_flag_is_flagged_generically():
    note = check_bind_flag("z")
    assert note is not None
    assert note.reason == "unknown_bind_flag"


def test_source_directive_always_gets_a_todo():
    note = check_source_directive("/home/x/extra.conf", line=526)
    assert note.reason == "source_directive"
    assert "/home/x/extra.conf" in note.detail
    assert note.line == 526


def test_format_todo_includes_line_number():
    note = TodoNote("x", "something needs review", 10)
    assert format_todo(note) == "-- TODO(hyprvalidate convert): something needs review (hyprland.conf line 10)"


def test_format_todo_without_line_number():
    note = TodoNote("x", "something needs review", None)
    assert format_todo(note) == "-- TODO(hyprvalidate convert): something needs review"


def test_render_program_comment_only():
    note = TodoNote("source_directive", "review this", 5)
    out = render_program([(None, note)])
    assert out == "-- TODO(hyprvalidate convert): review this (hyprland.conf line 5)"


def test_render_program_statement_only():
    call = hlcall("hl.dsp.window.close")
    out = render_program([(call, None)])
    assert out.strip() == "hl.dsp.window.close()"


def test_render_program_comment_above_a_best_effort_statement():
    note = TodoNote("unrecognized_dispatcher", "review this call", 3)
    call = hlcall("hl.dsp.no_op")
    out = render_program([(call, note)])
    lines = out.splitlines()
    assert lines[0] == "-- TODO(hyprvalidate convert): review this call (hyprland.conf line 3)"
    assert "hl.dsp.no_op" in lines[1]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all tests passed")
