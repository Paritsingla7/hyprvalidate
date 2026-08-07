"""Tests for the CLI (docs/PLAN.md row 8) - only the `check` subcommand
exists (see cli.py docstring for why `convert` isn't stubbed yet).

Tests both the pure orchestration function directly (fast, no subprocess)
and the actual installed console-script entry point end to end (proves the
thing a user would actually type works, not just the internals).
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from hyprvalidate.cli import check_files, DEFAULT_STUB_PATH

REPO_ROOT = Path(__file__).parent.parent
REAL_KEYBINDS = REPO_ROOT.parent / "configs" / "hyprland-lua" / "keybinds.lua"

VALID_SNIPPET = "hl.bind('SUPER + Q', hl.dsp.window.close())\n"
BAD_TYPE_SNIPPET = 'hl.config({ animations = { enabled = "yes, please :)" } })\n'
INVALID_LUA_SNIPPET = 'hl.config({ windowrule = { match:class = ".*" } })\n'


def test_clean_file_exits_zero(tmp_path):
    f = tmp_path / "ok.lua"
    f.write_text(VALID_SNIPPET)
    code, lines = check_files([f], DEFAULT_STUB_PATH)
    assert code == 0
    assert "no issues found" in lines[-1]


def test_schema_issue_exits_one_with_located_message(tmp_path):
    f = tmp_path / "bad_type.lua"
    f.write_text(BAD_TYPE_SNIPPET)
    code, lines = check_files([f], DEFAULT_STUB_PATH)
    assert code == 1
    assert any(str(f) in line and "type_mismatch" in line for line in lines)


def test_invalid_lua_exits_two(tmp_path):
    f = tmp_path / "broken.lua"
    f.write_text(INVALID_LUA_SNIPPET)
    code, lines = check_files([f], DEFAULT_STUB_PATH)
    assert code == 2


def test_missing_stub_path_exits_two_with_clear_error():
    code, lines = check_files([], "/nonexistent/hl.meta.lua")
    assert code == 2
    assert "not found" in lines[0]


def test_multiple_files_aggregate_findings(tmp_path):
    ok = tmp_path / "ok.lua"
    ok.write_text(VALID_SNIPPET)
    bad = tmp_path / "bad.lua"
    bad.write_text(BAD_TYPE_SNIPPET)
    code, lines = check_files([ok, bad], DEFAULT_STUB_PATH)
    assert code == 1
    assert any(str(bad) in line for line in lines)
    assert not any(str(ok) in line and "[" in line for line in lines)


def test_real_migrated_config_directory_is_clean():
    files = sorted((REPO_ROOT.parent / "configs" / "hyprland-lua").glob("*.lua"))
    assert files
    code, lines = check_files(files, DEFAULT_STUB_PATH)
    assert code == 0, f"expected the project's own real config to be clean: {lines}"


def test_installed_entry_point_works_end_to_end(tmp_path):
    """Proves the actual `hyprvalidate check ...` command a user would type
    works, not just the internal function. Resolved next to the running
    interpreter rather than assumed to be on PATH - this test runs inside
    the project's own venv, not necessarily an activated shell."""
    entry_point = Path(sys.executable).parent / "hyprvalidate"
    assert entry_point.is_file(), f"expected an installed console script at {entry_point}"

    f = tmp_path / "bad_type.lua"
    f.write_text(BAD_TYPE_SNIPPET)
    result = subprocess.run(
        [str(entry_point), "check", str(f)],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "type_mismatch" in result.stdout


if __name__ == "__main__":
    import inspect
    import tempfile

    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            if "tmp_path" in inspect.signature(fn).parameters:
                with tempfile.TemporaryDirectory() as d:
                    fn(Path(d))
            else:
                fn()
            print(f"ok  {name}")
    print("all tests passed")
