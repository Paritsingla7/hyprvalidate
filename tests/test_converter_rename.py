"""Tests for the hand-curated rename tables (docs/CONVERTER_PLAN.md task 7.3).

The whole point of these tests: every entry is checked against the real
schema, so a typo'd or wrong target fails immediately - the exact discipline
missing from every existing converter's own tables (hypr-migrate's
`bindr`->`repeating` bug, this project's own `mouse`->`drag` history).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from hyprvalidate.schema.extractor import extract_file
from hyprvalidate.checker import resolve_symbol
from hyprvalidate.converter.rename import (
    DISPATCHER_RENAME,
    BIND_FLAG_RENAME,
    SHAPE_CHANGING_BIND_FLAGS,
)

STUB_PATH = "/usr/share/hypr/stubs/hl.meta.lua"


def _schema():
    assert Path(STUB_PATH).is_file(), f"expected the installed stub at {STUB_PATH}"
    return extract_file(STUB_PATH)


def test_every_dispatcher_rename_target_resolves_against_the_schema():
    schema = _schema()
    for old_name, target in DISPATCHER_RENAME.items():
        is_valid, reason, _ = resolve_symbol(schema, target)
        assert is_valid, f"{old_name} -> {target}: {reason}"


def test_every_bind_flag_rename_target_is_a_real_bindoptions_field():
    schema = _schema()
    bind_options = schema.classes["HL.BindOptions"]
    for old_flag, field_name in BIND_FLAG_RENAME.items():
        assert field_name in bind_options.fields, (
            f"flag '{old_flag}' -> '{field_name}' is not a real HL.BindOptions field"
        )
        assert bind_options.fields[field_name] == "boolean", (
            f"flag '{old_flag}' -> '{field_name}' expected a boolean field, "
            f"got {bind_options.fields[field_name]!r}"
        )


def test_release_is_not_confused_with_repeat():
    # The exact bug found in hyprconf2lua's own table: r -> "repeating".
    assert BIND_FLAG_RENAME["r"] == "release"
    assert BIND_FLAG_RENAME["e"] == "repeating"


def test_drag_not_mouse_for_the_g_flag():
    # This project's own historical mouse->drag bug, now locked in as a
    # rename-table regression test.
    assert BIND_FLAG_RENAME["g"] == "drag"
    assert "m" not in BIND_FLAG_RENAME


def test_shape_changing_flags_are_documented_not_silently_dropped():
    for flag in ("d", "s", "m"):
        assert flag in SHAPE_CHANGING_BIND_FLAGS
        assert flag not in BIND_FLAG_RENAME


def test_movefocus_and_workspace_both_target_focus_with_different_shapes():
    # Confirmed by reading hlFocus's actual implementation: direction vs.
    # workspace table keys dispatch to different internal behavior under
    # the same hl.dsp.focus entry point.
    assert DISPATCHER_RENAME["movefocus"] == "hl.dsp.focus"
    assert DISPATCHER_RENAME["workspace"] == "hl.dsp.focus"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all tests passed")
