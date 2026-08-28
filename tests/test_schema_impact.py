"""Tests for hyprvalidate.schema.impact - cross-referencing a SchemaDiff
against what a real config actually uses. The rename/removal cases are
tested against the real corpus (same policy as test_schema_diff.py); the
config-key-removed and class-removed paths use small hand-built schemas
since no real config key or class was ever removed across the 8 real
Hyprland versions this project has - those code paths still need covering,
just not from history that doesn't exist yet.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

SCHEMAS_DIR = Path(__file__).parent.parent / "schemas"

from hyprvalidate.schema.extractor import Schema, ClassInfo
from hyprvalidate.schema.diff import diff_schemas
from hyprvalidate.schema.impact import find_used_symbols, compute_impact
from hyprvalidate.luaast import reader


def _load(version: str) -> Schema:
    path = SCHEMAS_DIR / f"{version}.json"
    assert path.is_file(), f"expected the real schema corpus at {path}"
    return Schema.from_json(path.read_text())


def test_real_permission_rename_is_reported_only_once_when_used():
    """The real allow -> mode regression, from a config that actually
    constructs a permission spec table using the old field name. Must
    report the rename guess, and must NOT also separately report a plain
    "removed" for the same field - that would just say the same fact twice."""
    old, new = _load("v0.55.0"), _load("v0.55.1")
    diff = diff_schemas(old, new)
    tree = reader.parse('hl.permission({ allow = "yes", binary = "foo", type = "bar" })')
    used = find_used_symbols(old, tree)
    report = compute_impact(old, diff, used)

    assert len(report.affected_class_fields) == 1
    hit = report.affected_class_fields[0]
    assert hit.class_name == "HL.PermissionSpec"
    assert hit.field == "allow"
    assert hit.kind == "possible_rename"
    assert "mode" in hit.detail


def test_real_permission_rename_is_not_reported_when_config_does_not_use_it():
    """A config that never touches hl.permission at all - the diff between
    these two versions is real, but irrelevant to this specific file."""
    old, new = _load("v0.55.0"), _load("v0.55.1")
    diff = diff_schemas(old, new)
    tree = reader.parse('hl.bind("SUPER + Q", hl.dsp.window.close())')
    used = find_used_symbols(old, tree)
    report = compute_impact(old, diff, used)
    assert report.is_empty()


def test_real_monitor_scale_widening_is_reported_as_type_changed():
    """HL.MonitorSpec.scale: string -> string|number (v0.55.0 -> v0.55.1) -
    a real, backward-compatible widening. Still reported (this module
    reports facts, not severity judgments)."""
    old, new = _load("v0.55.0"), _load("v0.55.1")
    diff = diff_schemas(old, new)
    tree = reader.parse('hl.monitor({ output = "eDP-1", scale = "1.5" })')
    used = find_used_symbols(old, tree)
    report = compute_impact(old, diff, used)

    scale_hits = [f for f in report.affected_class_fields if f.field == "scale"]
    assert len(scale_hits) == 1
    assert scale_hits[0].kind == "type_changed"
    assert scale_hits[0].class_name == "HL.MonitorSpec"


def test_config_key_removal_is_detected_when_used():
    old = Schema(config_value_types={"input.accel_profile": "string", "general.gaps_in": "integer"})
    new = Schema(config_value_types={"general.gaps_in": "integer"})
    diff = diff_schemas(old, new)

    tree = reader.parse('hl.config({ input = { accel_profile = "flat" }, general = { gaps_in = 5 } })')
    used = find_used_symbols(old, tree)
    assert used.config_keys == {"input", "input.accel_profile", "general", "general.gaps_in"}

    report = compute_impact(old, diff, used)
    assert len(report.affected_config_keys) == 1
    hit = report.affected_config_keys[0]
    assert hit.key == "input.accel_profile"
    assert hit.kind == "removed"


def test_config_key_rename_guess_is_reported_and_not_duplicated():
    old = Schema(config_value_types={"input.old_name": "string"})
    new = Schema(config_value_types={"input.new_name": "string"})
    diff = diff_schemas(old, new)

    tree = reader.parse('hl.config({ input = { old_name = "x" } })')
    used = find_used_symbols(old, tree)
    report = compute_impact(old, diff, used)

    assert len(report.affected_config_keys) == 1
    hit = report.affected_config_keys[0]
    assert hit.kind == "possible_rename"
    assert "new_name" in hit.detail


def test_removed_class_used_via_a_call_is_detected():
    old = Schema(classes={
        "HL.API": ClassInfo(name="HL.API", fields={"legacy": "HL.LegacyNamespace"}),
        "HL.LegacyNamespace": ClassInfo(name="HL.LegacyNamespace", fields={"do_thing": "fun(): nil"}),
    })
    new = Schema(classes={
        "HL.API": ClassInfo(name="HL.API", fields={}),
    })
    diff = diff_schemas(old, new)
    assert "HL.LegacyNamespace" in diff.classes_removed

    tree = reader.parse("hl.legacy.do_thing()")
    used = find_used_symbols(old, tree)
    report = compute_impact(old, diff, used)

    assert len(report.affected_classes) == 1
    assert report.affected_classes[0].class_name == "HL.LegacyNamespace"
    assert "hl.legacy.do_thing" in report.affected_classes[0].used_via


def test_unrelated_removed_class_is_not_reported_when_unused():
    old = Schema(classes={
        "HL.API": ClassInfo(name="HL.API", fields={
            "legacy": "HL.LegacyNamespace", "dsp": "HL.DspNamespace",
        }),
        "HL.LegacyNamespace": ClassInfo(name="HL.LegacyNamespace", fields={"do_thing": "fun(): nil"}),
        "HL.DspNamespace": ClassInfo(name="HL.DspNamespace", fields={"exec_cmd": "fun(...): HL.Dispatcher"}),
    })
    new = Schema(classes={
        "HL.API": ClassInfo(name="HL.API", fields={"dsp": "HL.DspNamespace"}),
        "HL.DspNamespace": ClassInfo(name="HL.DspNamespace", fields={"exec_cmd": "fun(...): HL.Dispatcher"}),
    })
    diff = diff_schemas(old, new)
    assert "HL.LegacyNamespace" in diff.classes_removed

    tree = reader.parse('hl.bind("SUPER + Q", hl.dsp.exec_cmd("foo"))')
    used = find_used_symbols(old, tree)
    report = compute_impact(old, diff, used)
    assert report.affected_classes == []
