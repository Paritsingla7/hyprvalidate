"""Tests for schema-typed value coercion (docs/CONVERTER_PLAN.md task 7.2)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FIXTURES = Path(__file__).parent / "fixtures"
# Prefer the live installed stub; fall back to the committed snapshot so the
# suite runs in CI and on machines without Hyprland installed.
_LIVE_STUB = Path("/usr/share/hypr/stubs/hl.meta.lua")
SCHEMA_PATH = str(_LIVE_STUB if _LIVE_STUB.is_file() else Path(__file__).parent.parent / "schema.json")

from hyprvalidate.converter.coerce import coerce_value
from hyprvalidate.schema.extractor import load_schema



def _schema():
    assert Path(SCHEMA_PATH).is_file(), f"expected the installed stub at {SCHEMA_PATH}"
    return load_schema(SCHEMA_PATH)


def test_true_coerces_to_boolean():
    assert coerce_value("boolean", "true") == (True, True)


def test_false_coerces_to_boolean():
    assert coerce_value("boolean", "false") == (False, True)


def test_case_insensitive_boolean():
    assert coerce_value("boolean", "TRUE") == (True, True)


def test_unrecognized_boolean_spelling_is_not_guessed():
    """'yes' isn't a confirmed hyprlang boolean literal (only 'true'/
    'false' are) - must not silently coerce, that would be a guess."""
    value, matched = coerce_value("boolean", "yes")
    assert matched is False
    assert value == "yes"


def test_integer_coerces():
    assert coerce_value("integer", "5") == (5, True)


def test_number_coerces_float():
    assert coerce_value("number", "0.94") == (0.94, True)


def test_number_coerces_int():
    assert coerce_value("number", "5") == (5, True)


def test_non_integer_string_does_not_coerce_to_integer():
    value, matched = coerce_value("integer", "5.5")
    assert matched is False
    assert value == "5.5"


def test_string_type_passes_through_unchanged():
    assert coerce_value("string", "dwindle") == ("dwindle", False)


def test_table_shaped_alternative_falls_through_to_string():
    value, matched = coerce_value("string|HL.Gradient", "rgba(33ccffee) 45deg")
    assert matched is False
    assert value == "rgba(33ccffee) 45deg"


def test_first_matching_alternative_wins_in_declared_order():
    # boolean before number in the type expression - "true" only matches
    # boolean, never accidentally treated as a number.
    assert coerce_value("boolean|number", "true") == (True, True)


def test_real_schema_general_resize_on_border_is_boolean():
    schema = _schema()
    type_expr = schema.config_value_types["general.resize_on_border"]
    assert coerce_value(type_expr, "true") == (True, True)


def test_real_schema_decoration_active_opacity_is_number():
    schema = _schema()
    type_expr = schema.config_value_types["decoration.active_opacity"]
    assert coerce_value(type_expr, "0.94") == (0.94, True)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all tests passed")
