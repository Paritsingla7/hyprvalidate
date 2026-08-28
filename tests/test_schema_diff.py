"""Tests for hyprvalidate.schema.diff - checked against a corpus of real
Hyprland schemas (schemas/v0.55.0.json .. v0.56.2.json, one per actual
tagged release), the same "real data as oracle" policy the rest of this
project's test suite follows. These aren't synthetic what-if schemas: every
change asserted on here is a real, dated change in Hyprland's own history,
traced back to a specific upstream commit while scoping this feature.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

SCHEMAS_DIR = Path(__file__).parent.parent / "schemas"

from hyprvalidate.schema.extractor import Schema
from hyprvalidate.schema.diff import diff_schemas, normalize_type_expr


def _load(version: str) -> Schema:
    path = SCHEMAS_DIR / f"{version}.json"
    assert path.is_file(), f"expected the real schema corpus at {path}"
    return Schema.from_json(path.read_text())


def test_normalize_type_expr_ignores_union_order():
    assert normalize_type_expr("string|HL.Gradient") == normalize_type_expr("HL.Gradient|string")


def test_normalize_type_expr_does_not_split_inside_brackets():
    # The inner "|" belongs to a nested generic, not a top-level union -
    # splitting on it would corrupt the type, not just reorder it.
    t = "table<string, string|number>"
    assert normalize_type_expr(t) == t


def test_diffing_a_schema_against_itself_is_empty():
    v56_2 = _load("v0.56.2")
    assert diff_schemas(v56_2, v56_2).is_empty()


def test_real_permission_allow_to_mode_rename_is_detected_confidently():
    """The exact real regression: hl.permission{}'s `allow` field was
    renamed to `mode` one day after Lua config first shipped
    (v0.55.0 -> v0.55.1, hyprwm/Hyprland#14400). A clean 1:1 same-type
    match (both `string`) - this is exactly the case the rename heuristic
    exists for."""
    diff = diff_schemas(_load("v0.55.0"), _load("v0.55.1"))
    class_diff = diff.class_diffs.get("HL.PermissionSpec")
    assert class_diff is not None
    assert class_diff.fields_removed == {"allow": "string"}
    assert class_diff.fields_added == {"mode": "string"}
    assert len(class_diff.possible_renames) == 1
    rename = class_diff.possible_renames[0]
    assert rename.old_name == "allow"
    assert rename.new_name == "mode"


def test_real_window_over_fullscreen_rename_is_reported_but_not_guessed():
    """The exact real regression: HL.Window's `over_fullscreen` field
    disappeared in v0.56.0 (hyprwm/Hyprland#15367, PR titled "match naming
    convention" - genuinely breaking despite the mild-sounding title).
    Unlike the PermissionSpec case, this one is NOT a clean 1:1 type match:
    v0.56.0 added *two* new boolean fields to HL.Window
    (`allowed_over_fullscreen` and `pin_fullscreened`), not one - so which
    boolean `over_fullscreen` "became" can't be told apart by type alone.
    The diff must report the plain fact (removed) without guessing which
    addition it maps to - asserting the negative here is the whole point:
    a wrong confident guess would be worse than an honest gap."""
    diff = diff_schemas(_load("v0.55.4"), _load("v0.56.0"))
    class_diff = diff.class_diffs.get("HL.Window")
    assert class_diff is not None
    assert "over_fullscreen" in class_diff.fields_removed
    assert class_diff.fields_removed["over_fullscreen"] == "boolean"
    assert "allowed_over_fullscreen" in class_diff.fields_added
    assert "pin_fullscreened" in class_diff.fields_added
    # Two same-typed candidates on the added side - no confident 1:1 match.
    assert not any(r.old_name == "over_fullscreen" for r in class_diff.possible_renames)


def test_real_type_widening_is_detected_as_a_type_change():
    """HL.MonitorSpec.scale went from `string` to `string|number`
    (v0.55.0 -> v0.55.1, hyprwm/Hyprland#14461) - backward compatible at
    runtime, but still a real type-expression change this module should
    surface (it doesn't judge severity, only reports the fact)."""
    diff = diff_schemas(_load("v0.55.0"), _load("v0.55.1"))
    class_diff = diff.class_diffs.get("HL.MonitorSpec")
    assert class_diff is not None
    scale_change = next(
        (c for c in class_diff.fields_type_changed if c.name == "scale"), None
    )
    assert scale_change is not None
    assert scale_change.old_type == "string"
    assert normalize_type_expr(scale_change.new_type) == normalize_type_expr("string|number")


def test_full_version_range_shows_substantial_real_growth():
    """v0.55.0 -> v0.56.2: classes roughly doubled (39 -> 79) as Hyprland
    built out a typed HL.ConfigOpt.* tree - sanity-checks the diff engine
    against the full real range, not just adjacent point releases."""
    diff = diff_schemas(_load("v0.55.0"), _load("v0.56.2"))
    assert len(diff.classes_added) >= 30
    assert diff.classes_removed == []  # no class was ever removed across this range
    assert len(diff.config_keys_added) >= 10


def test_class_added_across_the_full_range_is_reported():
    diff = diff_schemas(_load("v0.55.0"), _load("v0.56.2"))
    assert "HL.ConfigOpt" in diff.classes_added or any(
        c.startswith("HL.ConfigOpt.") for c in diff.classes_added
    )
