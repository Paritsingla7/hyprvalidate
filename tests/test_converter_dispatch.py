"""Tests for schema-derived block-type dispatch (docs/CONVERTER_PLAN.md task 7.1)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FIXTURES = Path(__file__).parent / "fixtures"
# Prefer the live installed stub; fall back to the committed snapshot so the
# suite runs in CI and on machines without Hyprland installed.
_LIVE_STUB = Path("/usr/share/hypr/stubs/hl.meta.lua")
SCHEMA_PATH = str(_LIVE_STUB if _LIVE_STUB.is_file() else Path(__file__).parent.parent / "schema.json")

from hyprvalidate.schema.extractor import load_schema
from hyprvalidate.converter.dispatch import classify_block
from hyprvalidate.hyprlang.parser import parse_file, Block

REPO_ROOT = Path(__file__).parent.parent
REAL_CONF = FIXTURES / "hyprland.conf"


def _schema():
    assert Path(SCHEMA_PATH).is_file(), f"expected the installed stub at {SCHEMA_PATH}"
    return load_schema(SCHEMA_PATH)


def test_device_is_a_top_level_call():
    assert classify_block(_schema(), "device") == "hl.device"


def test_gesture_would_be_a_top_level_call_if_it_were_a_block():
    # gesture is a flat directive in the old format, not a block - the
    # dispatcher itself is name-based and doesn't care about the caller's
    # shape, so this still proves the schema-derived lookup is correct.
    assert classify_block(_schema(), "gesture") == "hl.gesture"


def test_general_flattens_into_config():
    assert classify_block(_schema(), "general") is None


def test_decoration_flattens_into_config():
    assert classify_block(_schema(), "decoration") is None


def test_plugin_flattens_into_config():
    assert classify_block(_schema(), "plugin") is None


def test_master_and_misc_flatten_no_matching_api_field_at_all():
    schema = _schema()
    assert classify_block(schema, "master") is None
    assert classify_block(schema, "misc") is None


def test_unknown_name_flattens():
    assert classify_block(_schema(), "not_a_real_block_name") is None


def test_every_block_in_the_real_config_routes_like_the_hand_migration():
    """The hand-migration is the ground truth: it already routed 'device'
    to hl.device() and everything else (plugin/general/decoration/input/
    master/misc) into hl.config sections."""
    schema = _schema()
    hf = parse_file(REAL_CONF)
    expected = {
        "plugin": None,
        "device": "hl.device",
        "input": None,
        "general": None,
        "decoration": None,
        "master": None,
        "misc": None,
    }
    seen = set()
    for stmt in hf.statements:
        if isinstance(stmt, Block) and stmt.name in expected:
            seen.add(stmt.name)
            assert classify_block(schema, stmt.name) == expected[stmt.name], stmt.name
    assert seen == set(expected), f"missing block names in real config: {set(expected) - seen}"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all tests passed")
