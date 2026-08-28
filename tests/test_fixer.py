"""Tests for hyprvalidate.fixer - applying a Finding's fix, when it has
one. Uses the real schema, same as the checker's own tests, so these are
checked against ground truth, not a mock."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

_LIVE_STUB = Path("/usr/share/hypr/stubs/hl.meta.lua")
SCHEMA_PATH = str(_LIVE_STUB if _LIVE_STUB.is_file() else Path(__file__).parent.parent / "schema.json")

from hyprvalidate.schema.extractor import load_schema
from hyprvalidate import checker, fixer
from hyprvalidate.checker import FindingKind


def _schema():
    assert Path(SCHEMA_PATH).is_file(), f"expected the installed stub at {SCHEMA_PATH}"
    return load_schema(SCHEMA_PATH)


def test_missing_quotes_fix_produces_valid_and_clean_output():
    schema = _schema()
    src = "hl.config({ input = { accel_profile = flat } })"
    findings = checker.check_source(schema, src)
    result = fixer.apply_fixes(src, findings)
    assert result.source == 'hl.config({ input = { accel_profile = "flat" } })'
    assert [f.kind for f in result.applied] == [FindingKind.POSSIBLE_MISSING_QUOTES]
    assert result.remaining == []
    assert checker.check_source(schema, result.source) == []


def test_uncalled_dispatcher_fix_produces_valid_and_clean_output():
    schema = _schema()
    src = "hl.bind('SUPER + Q', hl.dsp.window.close)"
    findings = checker.check_source(schema, src)
    result = fixer.apply_fixes(src, findings)
    assert result.source == "hl.bind('SUPER + Q', hl.dsp.window.close())"
    assert [f.kind for f in result.applied] == [FindingKind.UNCALLED_DISPATCHER]
    assert checker.check_source(schema, result.source) == []


def test_duplicate_bind_has_no_fix_and_is_left_in_remaining():
    """No single correct fix exists - which of two colliding binds is
    "right" isn't knowable from the file alone. apply_fixes must never
    guess; the finding is untouched and the source is byte-for-byte
    identical."""
    schema = _schema()
    src = (
        "hl.bind('SUPER + Q', hl.dsp.window.close())\n"
        "hl.bind('SUPER + Q', hl.dsp.window.kill())\n"
    )
    findings = checker.check_source(schema, src)
    result = fixer.apply_fixes(src, findings)
    assert result.source == src
    assert result.applied == []
    assert len(result.remaining) == 2
    assert all(f.kind == FindingKind.DUPLICATE_BIND for f in result.remaining)


def test_multiple_independent_fixes_in_one_file_apply_correctly():
    """Regression for the back-to-front offset-ordering in apply_fixes:
    two edits in the same file, applied out of source order internally,
    must not corrupt each other's offsets."""
    schema = _schema()
    src = (
        'hl.bind("SUPER + Q", hl.dsp.window.close)\n'
        'hl.config({ input = { accel_profile = flat } })\n'
    )
    findings = checker.check_source(schema, src)
    result = fixer.apply_fixes(src, findings)
    assert result.source == (
        'hl.bind("SUPER + Q", hl.dsp.window.close())\n'
        'hl.config({ input = { accel_profile = "flat" } })\n'
    )
    assert len(result.applied) == 2
    assert checker.check_source(schema, result.source) == []


def test_mixed_fixable_and_unfixable_findings_only_fixable_ones_applied():
    schema = _schema()
    src = (
        "hl.config({ input = { accel_profile = flat } })\n"
        "hl.bind('SUPER + Q', hl.dsp.window.close())\n"
        "hl.bind('SUPER + Q', hl.dsp.window.kill())\n"
    )
    findings = checker.check_source(schema, src)
    result = fixer.apply_fixes(src, findings)
    assert 'accel_profile = "flat"' in result.source
    assert len(result.applied) == 1
    assert result.applied[0].kind == FindingKind.POSSIBLE_MISSING_QUOTES
    assert len(result.remaining) == 2
    assert all(f.kind == FindingKind.DUPLICATE_BIND for f in result.remaining)


def test_clean_source_has_nothing_to_fix():
    schema = _schema()
    src = "hl.bind('SUPER + Q', hl.dsp.window.close())\n"
    findings = checker.check_source(schema, src)
    result = fixer.apply_fixes(src, findings)
    assert result.source == src
    assert result.applied == []
    assert result.remaining == []
